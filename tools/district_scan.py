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
    haversine, brand_of, load_token, norm,
)

PLACE_URL = "https://api.map.baidu.com/agent_plan/v1/place"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND_CACHE = os.path.join(ROOT, ".cache", "brand_pois.json")


# ---------------------------------------------------------------- HTTP
def query_place(user_raw_request, city, retries=2):
    qs = urllib.parse.urlencode({
        "user_raw_request": user_raw_request,
        "region": city,
        "sort": "relevance",
    })
    req = urllib.request.Request(
        PLACE_URL + "?" + qs,
        headers={"Authorization": "Bearer " + load_token(),
                 "User-Agent": "curl/8"})
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:                              # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError("POI 请求失败：%s" % last)


# ---------------------------------------------------------------- 阶段 1
def fetch_brand_pois(city, workers=6):
    """一次性拉取全部品牌的门店，返回 {brand: [poi_dict, ...]}。"""
    cache = {}
    if os.path.exists(BRAND_CACHE):
        try:
            with open(BRAND_CACHE, encoding="utf-8") as f:
                blob = json.load(f)
            if blob.get("city") == city:
                cache = blob.get("brands", {})
                print("[阶段1] 命中缓存：%d 个品牌，0 次请求" % len(cache))
                return cache
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

    os.makedirs(os.path.dirname(BRAND_CACHE), exist_ok=True)
    with open(BRAND_CACHE, "w", encoding="utf-8") as f:
        json.dump({"city": city, "brands": res}, f, ensure_ascii=False, indent=2)
    print("[阶段1] 完成，已缓存 → %s" % BRAND_CACHE)
    return res


# ---------------------------------------------------------------- 阶段 2
def scan_one(item, brand_pois, radius=800, inner_m=300):
    """对单个锚点做密度判定（品牌数据走本地缓存）。"""
    anchor, label = item["anchor"], item.get("label", item["anchor"])
    d = query_place("帮我找" + anchor, "岳阳市")
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
    if len(inner) <= 2 and isinstance(heat, (int, float)) and heat >= 5:
        verdict += "｜⚠连锁少但热度高：景区/枢纽/校园型人流，非零售商圈"
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
        futs = [ex.submit(scan_one, it, brand_pois, args.radius) for it in items]
        for fu in futs:
            try:
                rows.append(fu.result())
            except Exception as e:                          # noqa: BLE001
                rows.append({"label": "?", "verdict": "扫描失败：%s" % e})

    # 排序：商圈 > 准商圈 > 非商圈，其次按核心连锁数
    def rank(r):
        v = r["verdict"]
        g = 0 if v.startswith("商圈") else (1 if v.startswith("准商圈") else 2)
        return (g, -r.get("chain_inner", 0), -(r.get("arrival_heat") or 0))
    rows.sort(key=rank)

    print("=" * 92)
    print("%-14s %-30s %5s %5s %7s  %s"
          % ("商圈", "锚点命中", "核心", "加权", "热度", "判定"))
    print("-" * 92)
    for r in rows:
        print("%-14s %-30s %5s %5s %7s  %s"
              % (r["label"][:13], (r.get("anchor") or "-")[:28],
                 r.get("chain_inner", "-"), r.get("chain_inner_weighted", "-"),
                 r.get("heat_note", "-"), r["verdict"]))
    print("=" * 92)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"city": args.city, "radius": args.radius,
                       "rows": rows}, f, ensure_ascii=False, indent=2)
        print("已写入 %s" % args.out)


if __name__ == "__main__":
    main()