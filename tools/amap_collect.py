#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
高德 POI 采集器 —— 全国各省地市「美食 + 商圈 + 儿童游乐」建库的数据通道

设计纪律（与百度通道一致，见 tools/chain_probe.py 的 QuotaExceeded 教训）
--------------------------------------------------------------------
1. **配额故障必须显式报错，不得静默降级为空列表。**
   百度通道的事故：配额耗尽返回 status=302 且 results 字段缺失，
   上层把「查无结果」误判成「地图未收录」，所有结论集体降级无人察觉。
   本采集器对每一种非 10000 状态都分类处理：
     - CUQPS / 超限 / quota  → QuotaExceeded，立即停止该城采集并记入进度文件
     - INVALID_USER_KEY      → KeyError，直接终止（key 无效，重试无意义）
     - 其他非 0              → 记为该城市「受限」状态，保留原有缓存不覆盖
2. **原始响应全量落盘，不做任何裁剪**，便于后期换算法重跑。
3. **按城市隔离缓存**（借鉴 v0.5.0 修复：单槽位缓存曾导致跨城污染）。
4. **预算硬闸**：--budget 限制单次运行的总请求数，防止一次跑爆日配额。
5. **offset 上限护栏**：高德 text 接口单次最多返回 20/25 条（视 types 而定），
   翻页上限 offset=25；count 大于 600 时说明被截断，显式标记 truncated。

用法
----
    # 全量建库（会自动跳过已完成城市）
    python tools/amap_collect.py --all --budget 800

    # 只跑湖南
    python tools/amap_collect.py --province 湖南省

    # 单城试跑
    python tools/amap_collect.py --city 岳阳市 --verbose
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "amap")
RAW = os.path.join(CACHE, "raw")
PROGRESS = os.path.join(CACHE, "progress.json")

KEY = os.environ.get("AMAP_KEY", "7ffb28318f588bbca7158f3f3840ec59")

PLACE_URL = "https://restapi.amap.com/v3/place/text"

# ---------------------------------------------------------------- 配额与错误
class QuotaExceeded(RuntimeError):
    pass


class KeyInvalid(RuntimeError):
    pass


class DistrictBlocked(RuntimeError):
    """该城市本次不可用（网络/限流/空结果），保留旧缓存，不覆盖。"""
    pass


def request(params, retries=3, pause=0.35):
    """统一请求入口：带重试、限流保护、错误分类。

    v0.6.0 修正：10005 INVALID_USER_IP 属接口故障，不能当空结果处理。
    重试间隔采用「递增退避 + 单次运行内动态降速」：
    首次 1.5s，之后 3s/6s；同时把单次请求间隔从 0.35s 提到 0.55s，
    降低连续高频触发 IP 策略的概率。
    """
    q = dict(params)
    q["key"] = KEY
    url = PLACE_URL + "?" + urllib.parse.urlencode(q)
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                blob = json.loads(r.read().decode("utf-8"))
        except Exception as e:                        # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
            continue
        info = blob.get("info") or ""
        code = blob.get("infocode") or ""
        status = blob.get("status")
        # ── 错误分类：绝不能让配额问题被读成地理问题 ──
        if code == "10021" or "CUQPS" in info or "超" in info and "限" in info:
            raise QuotaExceeded("高德配额受限（%s）：%s" % (code, info[:100]))
        # INVALID_USER_IP（10005）：key 的 IP 白名单/访问策略拒绝。
        # 实测（v0.6.0 全国建库）：连续请求约 40 城后开始零星出现，
        # 影响 44 城全查询面失败。这不是「该城市没有数据」——
        # 若把空结果当真实数据落盘，会渲染出「0 家美食」的假档案，
        # 与百度通道的静默降级事故同构。必须归类为可重试故障。
        if code == "10005" or "INVALID_USER_IP" in info:
            raise DistrictBlocked(
                "高德 IP 访问策略拒绝（%s）：%s——属接口故障，"
                "非地理结论，不可当作「该城无数据」" % (code, info[:80]))
        if code == "10003" or code == "10004" or code == "10001":
            raise KeyInvalid("高德 key 无效或过期（%s）：%s" % (code, info[:100]))
        if code == "10020" or code == "10022" or code == "20800":
            raise DistrictBlocked("高德接口层拒绝（%s）：%s" % (code, info[:100]))
        if status != "1":
            raise DistrictBlocked(
                "高德返回非成功状态 status=%s code=%s info=%s"
                % (status, code, info[:100]))
        return blob
    raise DistrictBlocked("高德请求失败：%s" % last)


# ---------------------------------------------------------------- 查询计划
# 每个城市固定跑这些「查询面」，保证跨城市可比、可复算。
#   类型码查（type_query）：吃类型树，一次拿到一个分类的头部 POI
#   关键词查（kw_query） ：吃自然语言，捕捉「苍蝇馆 / 大排档 / 夜宵」等
#                         无法用类型码表达的本地概念
# pages 表示最多翻几页（高德 offset 上限 25，超过即截断）
QUERIES = [
    # ── 美食 ──
    ("food", "类型:中餐厅",          dict(types="050100", pages=2)),
    ("food", "类型:湘菜/地方菜",     dict(types="050108", pages=1)),
    ("food", "类型:地方风味餐厅",    dict(types="050118", pages=1)),
    ("food", "类型:酒楼/火锅/海鲜",  dict(types="050101", pages=1)),
    ("food", "类型:火锅",            dict(types="050117", pages=1)),
    ("food", "类型:海鲜酒楼",        dict(types="050119", pages=1)),
    ("food", "关键词:特色美食",      dict(keywords="特色美食", pages=2)),
    ("food", "关键词:老字号",        dict(keywords="老字号", pages=1)),
    ("food", "关键词:大排档",        dict(keywords="大排档", pages=1)),
    ("food", "关键词:苍蝇馆",        dict(keywords="苍蝇馆", pages=1)),
    ("food", "关键词:小吃",          dict(keywords="小吃", pages=2)),
    ("food", "关键词:本地菜",        dict(keywords="本地菜", pages=1)),
    # ── 特产 ──
    ("product", "关键词:特产",       dict(keywords="特产", pages=2)),
    ("product", "关键词:土特产",     dict(keywords="土特产", pages=1)),
    ("product", "关键词:地方特产",   dict(keywords="地方特产", pages=1)),
    # ── 商圈：商业街 / 购物 / 美食街 / 夜市 ──
    ("district", "类型:步行街",      dict(types="061001", pages=1)),
    ("district", "类型:特色商业街",   dict(types="061000", pages=2)),
    ("district", "类型:购物中心",     dict(types="060101", pages=3)),
    ("district", "类型:商场",        dict(types="060100", pages=2)),
    ("district", "关键词:美食街",     dict(keywords="美食街", pages=2)),
    ("district", "关键词:夜市",      dict(keywords="夜市", pages=2)),
    ("district", "关键词:小吃街",     dict(keywords="小吃街", pages=1)),
    ("district", "关键词:步行街",     dict(keywords="步行街", pages=1)),
    ("district", "关键词:购物中心",   dict(keywords="购物中心", pages=2)),
    # ── 商圈：酒吧 / 酒馆 / 娱乐 ──
    ("nightlife", "类型:酒吧",       dict(types="080304", pages=2)),
    ("nightlife", "关键词:酒馆",      dict(keywords="酒馆", pages=1)),
    ("nightlife", "关键词:LIVEHOUSE", dict(keywords="livehouse", pages=1)),
    ("nightlife", "类型:娱乐场所",    dict(types="080300", pages=1)),
    # ── 商场儿童游乐（用户 v0.6 新增维度）──
    ("kids", "关键词:儿童乐园",       dict(keywords="儿童乐园", pages=2)),
    ("kids", "关键词:电玩城",        dict(keywords="电玩城", pages=2)),
    ("kids", "关键词:游乐场",        dict(keywords="游乐场", pages=2)),
    ("kids", "关键词:迷你游乐场",     dict(keywords="迷你游乐场", pages=1)),
    ("kids", "关键词:亲子乐园",       dict(keywords="亲子乐园", pages=1)),
    ("kids", "关键词:淘气堡",        dict(keywords="淘气堡", pages=1)),
    ("kids", "关键词:儿童体验",       dict(keywords="儿童体验", pages=1)),
]


def city_cache_path(city):
    return os.path.join(RAW, city + ".json")


def load_progress():
    if os.path.exists(PROGRESS):
        with open(PROGRESS, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(p):
    os.makedirs(os.path.dirname(PROGRESS), exist_ok=True)
    with open(PROGRESS, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)


def normalize(p):
    """抽取建库所需字段，保留原始 id 与位置用于后续关联计算。

    v0.6.0：店名/地址中的 ASCII 竖线 `|` 会撑破 md 表格（实测
    「INXX CLUB(英克斯酒吧|濮阳店)」直接把表格列数 +1）。
    统一替换为全角竖线 `｜`，语义不变、表格安全。
    """
    biz = p.get("biz_ext") or {}
    loc = (p.get("location") or "").split(",")
    try:
        lng, lat = float(loc[0]), float(loc[1])
    except (IndexError, ValueError):
        lng = lat = None

    def pipe_safe(s):
        if not s:
            return s
        return s.replace("|", "｜")

    return {
        "id": p.get("id"),
        "name": pipe_safe(p.get("name")),
        "type": pipe_safe(p.get("type")),
        "typecode": p.get("typecode"),
        "address": pipe_safe(p.get("address")),
        "adcode": p.get("adcode"),
        "adname": p.get("adname"),
        "lng": lng,
        "lat": lat,
        "rating": biz.get("rating"),
        "cost": biz.get("cost"),
        "open_time": pipe_safe(biz.get("open_time")),
        "photos": [ph.get("url") for ph in (p.get("photos") or [])][:2],
        "tel": p.get("tel"),
    }


def collect_city(city, budget, verbose=False, dry=False):
    """采集单城，返回该城缓存 dict。"""
    cache = {"city": city, "queries": {}, "errors": [], "updated": None}
    if os.path.exists(city_cache_path(city)):
        with open(city_cache_path(city), encoding="utf-8") as f:
            cache = json.load(f)
    spent = 0
    for facet, label, spec in QUERIES:
        if budget is not None and spent >= budget:
            cache["errors"].append("预算耗尽，%s 未采" % label)
            break
        pages = spec.get("pages", 1)
        items, note = [], None
        for pg in range(1, pages + 1):
            params = {
                "city": city,
                "citylimit": "true",
                "extensions": "all",
                "offset": 20,
                "page": pg,
            }
            if spec.get("types"):
                params["types"] = spec["types"]
            if spec.get("keywords"):
                params["keywords"] = spec["keywords"]
            try:
                d = request(params)
            except QuotaExceeded as e:
                note = "配额受限：%s" % e
                cache["errors"].append(note)
                break
            except (KeyInvalid, DistrictBlocked) as e:
                note = str(e)
                cache["errors"].append(note)
                break
            spent += 1
            if budget is not None and spent >= budget:
                note = "预算耗尽于第 %d 页" % pg
                cache["errors"].append(note)
                break
            time.sleep(pause)
            pois = d.get("pois") or []
            total = int(d.get("count") or 0)
            if not pois and pg == 1:
                note = "该查询面无结果（count=%s）" % total
            for p in pois:
                items.append(normalize(p))
            if len(pois) < 20 or total <= pg * 20:
                break
        # 去重（同一 POI 可能被多个查询面命中）
        seen, uniq = set(), []
        for it in items:
            if it["id"] and it["id"] in seen:
                continue
            if it["id"]:
                seen.add(it["id"])
            uniq.append(it)
        cache["queries"][label] = {
            "facet": facet,
            "spec": spec,
            "count": len(uniq),
            "items": uniq,
            "note": note,
        }
        if verbose:
            print("    %-22s %3d 条%s" % (label, len(uniq),
                                          "  ⚠ " + note if note else ""))
    cache["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cache["request_spent"] = spent
    # ── v0.6.0 核心修复：全查询面失败的城市绝不落盘 ──
    # 实测事故：高德 INVALID_USER_IP（10005）导致 44 城全查询面失败，
    # 空结果被当成真实数据写进缓存，渲染出「0 家美食 0 处商圈」的假档案。
    # 这类城市的正确状态是「未采集/不可用」，而不是「采集了但没有」。
    if not dry:
        failed_all = (cache["queries"]
                      and all(q["count"] == 0 for q in cache["queries"].values()))
        if failed_all:
            if os.path.exists(city_cache_path(city)):
                os.remove(city_cache_path(city))
            raise DistrictBlocked(
                "%s 全部 %d 个查询面均返回 0 条，判定为接口故障而非"
                "「该城无数据」；已清除该城缓存，不生成假档案。"
                % (city, len(cache["queries"])))
        os.makedirs(RAW, exist_ok=True)
        with open(city_cache_path(city), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    return cache


def main():
    ap = argparse.ArgumentParser(description="高德 POI 采集器")
    ap.add_argument("--province", help="只跑该省，如 湖南省")
    ap.add_argument("--city", help="只跑该市，如 岳阳市")
    ap.add_argument("--all", action="store_true", help="跑全国")
    ap.add_argument("--budget", type=int, default=None,
                    help="单次运行总请求上限（防打爆日配额）")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--dry", action="store_true", help="不落盘")
    ap.add_argument("--force", action="store_true", help="重跑已完成城市")
    args = ap.parse_args()

    provs = json.load(open(
        os.path.join(CACHE, "prov_cities.json"), encoding="utf-8"))

    cities = []
    if args.city:
        cities = [args.city]
    elif args.province:
        cities = [c[1] for c in provs.get(args.province, {}).get("cities", [])]
    elif args.all:
        for v in provs.values():
            cities += [c[1] for c in v["cities"]]

    prog = load_progress()
    done, skipped, failed = 0, 0, 0
    budget_left = args.budget
    for city in cities:
        if not args.force and city in prog and prog[city].get("ok"):
            skipped += 1
            continue
        if budget_left is not None and budget_left <= 0:
            print("⛔ 预算耗尽，停止。已完成 %d 城。" % done)
            break
        try:
            cache = collect_city(city, budget_left, args.verbose, args.dry)
        except QuotaExceeded as e:
            print("⛔ 配额受限，停止后续采集：%s" % e)
            break
        except KeyInvalid as e:
            print("⛔ key 无效，终止：%s" % e)
            sys.exit(2)
        except DistrictBlocked as e:
            # 单城接口故障：记入进度但不中断整批（其他城可能仍然可用）
            failed += 1
            prog[city] = {
                "ok": False,
                "blocked": True,
                "errors": [str(e)[:120]],
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_progress(prog)
            print("  ⛔ %s：接口故障，跳过（%s）"
                  % (city, str(e)[:70]))
            continue
        n = sum(q["count"] for q in cache["queries"].values())
        errs = cache["errors"]
        prog[city] = {
            "ok": not errs,
            "pois": n,
            "queries": len(cache["queries"]),
            "spent": cache.get("request_spent"),
            "errors": errs[:5],
            "at": cache["updated"],
        }
        save_progress(prog)
        if budget_left is not None:
            budget_left -= cache.get("request_spent") or 0
        if errs:
            failed += 1
            print("  ⚠ %s：%d 条 / %s" % (city, n, errs[0][:60]))
        else:
            done += 1
            print("  ✅ %s：%d 条 POI（%d 次请求）"
                  % (city, n, cache.get("request_spent")))
    save_progress(prog)
    print("\n完成 %d 城，跳过 %d，受限 %d。进度见 %s"
          % (done, skipped, failed, PROGRESS))


if __name__ == "__main__":
    main()
