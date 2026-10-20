#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
商圈美食下钻器：给每个商圈一次性拉齐餐饮 POI + 补盲区判据

解决的三个问题
--------------
1. **连锁密度探针有结构性盲区。**
   实测：得胜南路美食街有 10+ 家实打实的餐厅（光头强大排档 3.9、
   陈大锅岳阳菜 4.4、二两香豆皮大王等），但清单品牌连锁只有 1 家，
   探针判「非商圈」。原因很清楚——**连锁密度测的是「品牌资本开支」，
   不是「吃饭人流」**。老城/local 小吃型街区天然低连锁、高餐饮密度。
   → 因此增加第三信号：**餐饮 POI 密度**（核心 300 m 内实餐饮条目数）。

2. **传统小吃常无 POI。** 汴河街南门入口的顶糕、小笼汤包是流动摊，
   地图不收录。→ 见 `--snack` 文本补充通道，由人工/用户提供，
   本工具只负责把它与 POI 条目分层呈现。

3. **逐个商圈重复检索太慢。** → 一次性批量下钻 + 落盘复用。

用法
----
    python tools/food_drill.py --city 岳阳市 \\
        --scan .cache/district_scan.json --out .cache/food_drill.json

只对通过 S-1 的商圈下钻；`--force` 可指定 label 强制下钻。
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_probe import haversine, heat_band                  # noqa: E402
from district_scan import query_place                        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 餐饮下钻的检索式：多个角度并发，合并去重。
# 单一「附近的美食」会漏掉小吃/夜宵/早餐，补品类词提高召回。
QUERIES = [
    "帮我找{city}{district}附近生意好的美食餐厅",
    "帮我找{city}{district}附近的小吃和快餐",
    "帮我找{city}{district}附近的特色餐馆和夜宵",
    "帮我找{city}{district}附近的早餐和早点",
    "帮我找{city}{district}附近的老字号和传统美食",
]

# 非餐饮条目过滤（地图常把周边服务混进餐饮检索）
NOT_FOOD = ("停车", "停车场", "便利店", "超市", "药店", "药房", "银行",
            "酒店", "宾馆", "公寓", "售楼", "中介", "美容", "美发", "理发",
            "网吧", "诊所", "医院", "药房", "服装", "鞋", "数码", "手机",
            "烟酒", "茶叶", "快递", "打印", "培训机构", "培训学校", "书店")


def is_food(name, addr=""):
    n = name or ""
    if any(k in n for k in NOT_FOOD):
        return False
    # 纯生活服务类后缀
    if n.endswith(("照相馆", "干洗店", "洗衣店", "美容院", "足浴", "按摩",
                   "健身房", "培训", "教育", "托管", "中介", "招待所")):
        return False
    return True


def norm_key(name, addr):
    """店名+地址归一化键，用于跨检索式去重。"""
    return (name or "").replace(" ", "") + "|" + (addr or "")[:12]


def drill(anchor_name, district, city, radius=500, workers=5):
    """对单个商圈做餐饮下钻，返回去重后的 POI 列表 + 密度统计。"""
    qs = [q.format(city=city, district=district) for q in QUERIES]

    def run(q):
        try:
            return query_place(q, city)
        except Exception:                                     # noqa: BLE001
            return {}

    merged = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for d in ex.map(run, qs):
            for c in (d.get("results") or []):
                loc = c.get("location") or {}
                if not loc.get("lat"):
                    continue
                name = c.get("name") or ""
                if not is_food(name, c.get("address")):
                    continue
                di = c.get("detail_info") or {}
                k = norm_key(name, c.get("address"))
                rec = {
                    "name": name, "address": c.get("address"),
                    "lat": loc["lat"], "lng": loc["lng"],
                    "rating": di.get("overall_rating"),
                    "comments": di.get("comment_num"),
                    "hours": di.get("shop_hours"),
                    "price": (di.get("price") or {}).get("avg_price")
                    if isinstance(di.get("price"), dict) else di.get("price"),
                    "tag": di.get("tag"),
                    "heat": di.get("arrival_heat"),
                }
                prev = merged.get(k)
                # 合并时取信息更全的一条
                if prev is None:
                    merged[k] = rec
                else:
                    for f in ("rating", "comments", "hours", "price", "tag"):
                        if prev.get(f) in (None, "", 0) and rec.get(f) not in (None, "", 0):
                            prev[f] = rec[f]

    pois = list(merged.values())
    inner = [p for p in pois
             if haversine(*[anchor_name[k] for k in ("lat", "lng")],
                          p["lat"], p["lng"]) <= 300]
    mid = [p for p in pois
           if 300 < haversine(*[anchor_name[k] for k in ("lat", "lng")],
                              p["lat"], p["lng"]) <= radius]

    fv, fv_why = classify(len(inner), anchor_name.get("chain_inner", 0),
                          anchor_name.get("heat"),
                          anchor_name.get("carrier_state"))

    def num(v):
        """百度返回的 rating/comments 时而是 str 时而是 int，统一成数字。"""
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def score(p):
        """口碑分：评分优先、评价数次之（类型安全）。

        实测坑：百度 detail_info 的 overall_rating / comment_num
        返回类型不稳定（同一接口出现 str 与 int 混用），直接排序会抛
        `'<' not supported between instances of 'int' and 'str'`。
        """
        return (num(p.get("rating")), num(p.get("comments")))

    return {
        "anchor": anchor_name["name"],
        "label": anchor_name.get("label"),
        "lat": anchor_name["lat"], "lng": anchor_name["lng"],
        "poi_total": len(pois),
        "poi_inner300": len(inner),
        "poi_300_500": len(mid),
        "food_verdict": fv,
        "food_verdict_why": fv_why,
        "inner": sorted(inner, key=score, reverse=True),
        "mid": sorted(mid, key=score, reverse=True),
    }


def classify(poi_inner, chain_inner, heat, carrier_state):
    """综合判定该锚点是否构成「有口碑的美食商圈」。

    第三代判据（v0.4.0）。三个信号各有盲区，必须组合：

    | 信号 | 强 | 盲区 |
    |---|---|---|
    | 连锁密度 | 品牌投票，可信 | 老城/local 小吃街区天然低连锁 |
    | 餐饮 POI 密度 | 直接测「吃饭人流」 | 大街区/行政区中心会溢出 |
    | 到访热度 | 官方人流口径 | 行政区 POI 热度天然低 |

    实测修正：单看餐饮密度会把**洞庭街道（居民区，300m 内 9 家餐饮）**
    误判为餐饮密集型商圈。原因是行政区 POI 坐标落在办事处大院，
    周边整片老社区的餐饮都被算进 300m。因此增加**联动否决**：
    连锁为 0 且到访热度 < 1 时，餐饮密度单独不足以判定商圈。
    """
    if poi_inner >= 8:
        food_sig = "餐饮密集/本地小吃型"
    elif poi_inner >= 4:
        food_sig = "餐饮成型/街段型"
    else:
        food_sig = "餐饮稀疏"

    # 行政区/居民区否决：既无连锁投票，人流读数也处于 floor 档。
    # v0.5.0：原判定 `heat < 1` 写死了「0–10 量纲」假设。实测 arrival_heat
    # 跨 4 个数量级（岳阳 0.05 / 汴河街 8.95 / 长沙五一 351.55），
    # `heat < 1` 对长沙/成都这类城市等于「恒真」，会把真实商圈全否掉。
    # 改用 heat_band 的 floor 档（≤0.1，跨城绝对可靠）。
    if chain_inner == 0:
        if heat is None:
            admin_kill = True
        else:
            _band, _ = heat_band(heat)
            admin_kill = (_band == "floor")
    else:
        admin_kill = False
    if admin_kill and poi_inner >= 8:
        return "非商圈/居民区（餐饮为周边溢出，非街区人流）", "联动否决"
    if admin_kill:
        return "非商圈/居民或低人流", "信号不足"

    if chain_inner >= 4 and food_sig.startswith("餐饮密集"):
        return "商圈/高人流（连锁+餐饮双强）", "双信号一致"
    if chain_inner >= 4 or food_sig.startswith("餐饮密集"):
        return "商圈/美食型人流点", "餐饮密度主导"
    if chain_inner >= 2 or food_sig.startswith("餐饮成型"):
        return "准商圈/次级人流点", "单项达标"
    return "非商圈/居民或低人流", "信号不足"


def main():
    ap = argparse.ArgumentParser(description="商圈美食下钻器")
    ap.add_argument("--city", default="岳阳市")
    ap.add_argument("--scan", required=True, help="district_scan.py 的输出")
    ap.add_argument("--out", required=True)
    ap.add_argument("--radius", type=int, default=500)
    ap.add_argument("--force", nargs="*", default=[], help="强制下钻的 label")
    ap.add_argument("--min-chain", type=int, default=2,
                    help="核心连锁数下限，低于此值默认跳过多餐饮型街区会被 force 覆盖")
    ap.add_argument("--all", action="store_true", help="对全部锚点下钻")
    args = ap.parse_args()

    with open(args.scan, encoding="utf-8") as f:
        scan = json.load(f)

    todo = []
    for r in scan["rows"]:
        if r.get("lat") is None:
            continue
        want = (args.all or r["label"] in args.force
                or r.get("chain_inner", 0) >= args.min_chain
                or r.get("carrier_state") == "offsite")
        if want:
            todo.append(r)

    print("下钻 %d 个商圈（并发 4）……" % len(todo))

    def one(r):
        anchor = {"name": r.get("anchor"), "label": r["label"],
                  "lat": r["lat"], "lng": r["lng"],
                  "chain_inner": r.get("chain_inner", 0),
                  "heat": r.get("arrival_heat"),
                  "carrier_state": r.get("carrier_state")}
        try:
            d = drill(anchor, anchor["name"], args.city, args.radius)
            d["chain_inner"] = r.get("chain_inner", 0)
            d["chain_verdict"] = r.get("verdict", "")
            d["shape"] = r.get("shape", "")
            d["heat"] = r.get("arrival_heat")
            return d
        except Exception as e:                                 # noqa: BLE001
            return {"label": r["label"], "error": str(e)}

    out = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for d in ex.map(one, todo):
            if "error" in d:
                print("  ! %s 下钻失败：%s" % (d["label"], d["error"]))
                continue
            out.append(d)
            print("  · %-12s 餐饮 %3d 家（300m %2d）｜连锁 %s｜%s"
                  % (d["label"], d["poi_total"], d["poi_inner300"],
                     d["chain_inner"], d["food_verdict"]))

    out.sort(key=lambda d: -(d["poi_inner300"] * 10 + d["chain_inner"]))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"city": args.city, "rows": out}, f, ensure_ascii=False, indent=2)
    print("已写入 %s" % args.out)


if __name__ == "__main__":
    main()