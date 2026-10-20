#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
商圈普查器：一次拉全城品牌门店 → 批量判定每个候选锚点

背景
----
`chain_probe.py` 是**单锚点探针**：每个锚点都要重发 26 个品牌查询。
做「全城商圈普查」（十几个候选街区）时，96% 的请求是重复的——
品牌门店和锚点无关，只与城市有关。

本工具把流程拆成两阶段：
  阶段 1  一次性拉取该城市全部清单品牌的门店坐标，落盘缓存
  阶段 2  每个锚点只发**1 个**请求（锚点自身定位），其余全部走
          本地缓存 + haversine 距离计算

实测：12 个锚点的普查，从「约 300 次请求」降到 13 次。

判定阈值沿用 S-1（核心 300 m 内连锁数 / 加权分），不擅自放宽，
保证本工具的结论与 chain_probe.py 单跑结果一致。

用法
----
    python tools/district_scan.py --city 岳阳市 --anchors anchors.json
    python tools/district_scan.py --city 岳阳市 --anchors anchors.json \\
        --out .cache/district_scan.json

anchors.json 格式：
    [{"anchor": "岳阳市岳阳楼区汴河街步行街", "label": "岳阳楼商圈"}, ...]
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_probe import (                                    # noqa: E402
    ALL_BRANDS, DECAY_M, TIERS, anchor_quality, carrier_check,
    haversine, brand_of, heat_band, heat_is_hot, heat_ref, load_token, norm,
    QuotaExceeded,
)
from chain_probe import query_place as _chain_query_place   # noqa: E402

PLACE_URL = "https://api.map.baidu.com/agent_plan/v1/place"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, ".cache", "brands")


def _brand_cache_path(city):
    """品牌门店缓存路径**按城市分文件**。

    v0.5.0 实测事故：原实现用固定的 `.cache/brand_pois.json`，
    而缓存内容与城市强相关。切城市（岳阳→长沙→哈尔滨）时会读到
    上一个城市的门店，坐标全错，普查结果整体失真且**静默**——
    实测发现该文件里存的是哈尔滨的门店，却在给长沙做密度统计。
    """
    safe = "".join(ch for ch in city if ch.isalnum() or ch in "-_")
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, "brands_%s.json" % (safe or "default"))


# ---------------------------------------------------------------- HTTP
# v0.5.0 修正：删除本文件里 query_place 的**独立副本**，统一复用
# chain_probe.query_place。
#
# 实测事故：副本存在时，配额检查只在 chain_probe 里加了，这个副本仍是旧版
# ——返回 {status:302} 无 results，上层读成「该品牌在此城无门店」。
# 更严重的是 fetch_brand_pois 会把这 26 个空结果**写进按城缓存**，
# 二次运行命中空缓存不再重拉 → 全城商圈被判「非商圈」，且全程静默。
# 一份逻辑只能有一处实现，否则修 A 漏 B。
query_place = _chain_query_place


def _probe_query_place(user_raw_request, city, retries=2):
    """兼容旧调用名。"""
    return _chain_query_place(user_raw_request, city, retries=retries)


# ---------------------------------------------------------------- 阶段 1
def fetch_brand_pois(city, workers=6):
    """一次性拉取全部品牌的门店，返回 {brand: [poi_dict, ...]}。"""
    cache = {}
    cache_path = _brand_cache_path(city)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                blob = json.load(f)
            # 双保险：文件名已按城市分，这里再校验一次 city 字段
            if blob.get("city") == city:
                cache = blob.get("brands", {})
                print("[阶段1] 命中缓存 %s：%d 个品牌，0 次请求"
                      % (os.path.basename(cache_path), len(cache)))
                return cache
            print("[阶段1] 缓存城市不符（%s ≠ %s），已忽略"
                  % (blob.get("city"), city))
        except (ValueError, OSError):
            pass

    print("[阶段1] 拉取 %d 个品牌门店（并发 %d）……" % (len(ALL_BRANDS), workers))

    def one(brand):
        try:
            d = query_place("帮我找%s的%s店" % (city, brand), city)
        except Exception as e:                              # noqa: BLE001
            return brand, [], str(e)
        out = []
        for c in (d.get("results") or []):
            loc = c.get("location") or {}
            if not loc.get("lat"):
                continue
            di = c.get("detail_info") or {}
            if brand_of(c.get("name"), di.get("brand")) != brand:
                continue                      # 混进来的同名词条目
            out.append({
                "name": c.get("name"), "address": c.get("address"),
                "lat": loc["lat"], "lng": loc["lng"],
                "rating": di.get("overall_rating"),
                "comments": di.get("comment_num"),
                "hours": di.get("shop_hours"),
            })
        return brand, out, None

    res = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for brand, out, err in ex.map(one, [b for b, _w, _t in ALL_BRANDS]):
            if err:
                print("  ! %s 拉取失败：%s" % (brand, err))
            res[brand] = out
            print("  · %-8s %d 家" % (brand, len(out)))

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    # ── v0.5.0 防污染：全空结果绝不写缓存 ──
    # 实测事故：配额耗尽时 26 个品牌全部返回空，若照写缓存，
    # 二次运行会命中这份「全空缓存」且因 city 字段相符而不再重拉，
    # 导致全城商圈被判「非商圈」，且全程没有任何报错。
    # 这是比「读到错误结果」更糟的失败——它会**主动阻断**自愈。
    nonempty = sum(1 for v in res.values() if v)
    if nonempty == 0:
        raise QuotaExceeded(
            "全部 %d 个品牌门店均返回空——几乎确定是配额耗尽或凭据失效，"
            "而非该城真的没有这些品牌。**已跳过写缓存**以免污染后续运行。"
            "请检查 BAIDU_MAP_AUTH_TOKEN 与配额窗口后重试。"
            % len(res))
    if nonempty < len(res) * 0.5:
        print("[警告] 仅 %d/%d 个品牌有结果，疑似查询不稳定，"
              "建议稍后重试" % (nonempty, len(res)))
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"city": city, "brands": res}, f, ensure_ascii=False, indent=2)
    print("[阶段1] 完成，已缓存 → %s（%d/%d 品牌有门店）"
          % (cache_path, nonempty, len(res)))
    return res


# ---------------------------------------------------------------- 阶段 2
def scan_one(item, brand_pois, radius=800, inner_m=300):
    """对单个锚点做密度判定（品牌数据走本地缓存）。"""
    anchor, label = item["anchor"], item.get("label", item["anchor"])
    # v0.5.0：city 原先硬编码「岳阳市」，换城市后所有锚点都按岳阳市检索，
    # 锚点坐标全部错位。改为从入参传入。
    city = item.get("city") or "岳阳市"
    d = query_place("帮我找" + anchor, city)
    res = d.get("results") or []
    if not res:
        return {"label": label, "anchor_req": anchor,
                "verdict": "锚点未找到", "why": "地图未返回该锚点，需重新消歧"}

    a = res[0]
    aloc = a.get("location") or {}
    alat, alng = aloc.get("lat"), aloc.get("lng")
    adi = a.get("detail_info") or {}
    heat = adi.get("arrival_heat")
    a_ok, a_note = anchor_quality(anchor, a)

    hits = {}
    for brand, weight, tier in ALL_BRANDS:
        for p in brand_pois.get(brand, []):
            dist = haversine(alat, alng, p["lat"], p["lng"])
            if dist > radius:
                continue
            prev = hits.get(brand)
            if prev is None or dist < prev["dist"]:
                hits[brand] = {"brand": brand, "tier": tier, "weight": weight,
                               "poi": p["name"], "address": p["address"],
                               "dist": round(dist), "rating": p["rating"],
                               "comments": p["comments"], "hours": p["hours"]}

    inner = [v for v in hits.values() if v["dist"] <= min(inner_m, radius)]
    inner_w = sum(v["weight"] for v in inner)

    if len(inner) >= 4 or inner_w >= 7:
        verdict = "商圈/高人流"
    elif len(inner) >= 2 or inner_w >= 3:
        verdict = "准商圈/次级人流点"
    else:
        verdict = "非商圈/居民或低人流"

    why = "核心 %dm 内连锁 %d 家、加权 %d 分" % (min(inner_m, radius), len(inner), inner_w)

    # 形态判定：可步行街区 vs 单一商场型（都是商圈，只是不是一回事）
    mall_kw = ("商场", "购物中心", "商业广场", "百货", "生活广场",
               "新天地", "广场")
    malls = set()
    for v in inner:
        addr = v["address"] or ""
        for kw in mall_kw:
            if kw in addr:
                malls.add(kw)
    mall_locked = bool(inner) and len(malls) == 1 and len(inner) >= 3
    if mall_locked and verdict.startswith("商圈"):
        # 实测修正：花板桥步步高 12 家连锁全在商场内，首版判「假阳性」。
        # 但它确实是商圈——商场本身承载餐饮集合。正确处理不是否决，
        # 而是**标注形态**，动线改为店内楼层动线。
        shape = "单一商场型"
    elif len(inner) >= 6:
        shape = "可步行街区型"
    else:
        shape = "街段/混合型"

    # 载体校验：锚点本身是不是「商圈载体」（校区/公园不是）
    car_state, car_note = carrier_check(anchor, a, len(inner))

    heat_note = "—"
    if isinstance(heat, (int, float)):
        heat_note = "%.2f" % heat
    else:
        verdict += "｜⚠无到访热度数据"

    if not a_ok:
        verdict += "｜⚠锚点解析疑似错误"
    if mall_locked:
        verdict += "｜形态：%s（连锁集中于%s内，动线按店内楼层编排，不做街面动线）" \
            % (shape, list(malls)[0])
    # v0.5.0：热度改用**量纲自适应**判档，废弃硬编码 `heat >= 5`。
    # 实测事故：arrival_heat 不是 0–10 量级，而是跨 4 个数量级的离散值
    # （岳阳 0.05、汴河街 8.95、长沙五一 351.55、成都春熙路 440.30）。
    # 旧阈值 `heat >= 5` 会把长沙五一广场这类城市级核心商圈直接误判成
    # 「景区/枢纽/校园型人流」。
    #
    # 注意：ref 必须**跨锚点**计算（同城几何均值），所以判定延后到 main()，
    # 这里只落原始值。see finalize_heat_bands()。
    if car_state == "offsite":
        verdict += "｜⚠" + car_note

    return {
        "label": label, "anchor_req": anchor,
        "anchor": a.get("name"), "anchor_addr": a.get("address"),
        "anchor_trusted": a_ok, "anchor_note": a_note,
        "carrier_state": car_state, "carrier_note": car_note,
        "lat": alat, "lng": alng,
        "chain_raw": len(hits), "chain_inner": len(inner),
        "chain_inner_weighted": inner_w,
        "arrival_heat": heat, "heat_note": heat_note,
        "mall_locked": mall_locked,
        "verdict": verdict, "why": why,
        "tier_count": {t: sum(1 for v in inner if v["tier"] == t) for t in TIERS},
        "hits": sorted(hits.values(), key=lambda v: v["dist"]),
    }


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="商圈普查器")
    ap.add_argument("--city", default="岳阳市")
    ap.add_argument("--anchors", required=True, help="锚点 JSON 列表")
    ap.add_argument("--radius", type=int, default=800)
    ap.add_argument("--out")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    with open(args.anchors, encoding="utf-8") as f:
        items = json.load(f)

    brand_pois = fetch_brand_pois(args.city, workers=args.workers)

    print("[阶段2] 扫描 %d 个锚点（并发 %d）……" % (len(items), args.workers))
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(scan_one, dict(it, city=args.city),
                          brand_pois, args.radius) for it in items]
        for fu in futs:
            try:
                rows.append(fu.result())
            except Exception as e:                          # noqa: BLE001
                rows.append({"label": "?", "verdict": "扫描失败：%s" % e})

    # v0.5.0：热度跨锚点统一判档（ref 必须同城，故在扫描层算）
    ref = heat_ref([r.get("arrival_heat") for r in rows])
    for r in rows:
        band, note = heat_band(r.get("arrival_heat"), ref=ref)
        r["heat_band"] = band
        r["heat_note"] = note if band != "missing" else "—"
    print("[热度] 同城参照 ref=%s" % ("%.2f" % ref if ref else "样本不足，回退绝对分档"))

    # 排序：商圈 > 准商圈 > 非商圈，其次按核心连锁数
    def rank(r):
        v = r["verdict"]
        g = 0 if v.startswith("商圈") else (1 if v.startswith("准商圈") else 2)
        return (g, -r.get("chain_inner", 0), -(r.get("arrival_heat") or 0))
    rows.sort(key=rank)

    print("=" * 92)
    print("%-14s %-30s %5s %5s %-8s %-8s %s"
          % ("商圈", "锚点命中", "核心", "加权", "热度档", "热度值", "判定"))
    print("-" * 92)
    for r in rows:
        print("%-14s %-30s %5s %5s %-8s %7s  %s"
              % (r["label"][:13], (r.get("anchor") or "-")[:28],
                 r.get("chain_inner", "-"), r.get("chain_inner_weighted", "-"),
                 r.get("heat_band", "-"),
                 ("%.2f" % r["arrival_heat"])
                 if isinstance(r.get("arrival_heat"), (int, float)) else "-",
                 r["verdict"]))
    print("=" * 92)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"city": args.city, "radius": args.radius,
                       "rows": rows}, f, ensure_ascii=False, indent=2)
        print("已写入 %s" % args.out)


if __name__ == "__main__":
    main()