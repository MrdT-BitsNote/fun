#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全国省市美食 × 商圈 md 生成器

把 .cache/amap/raw/{城市}.json 渲染成可查、可校对的 md 档案。

输出结构
--------
    data/{省}/{市}.md         单城档案（美食 + 商圈 + 关联 + 儿童游乐 + 校对区）
    data/README.md            全国索引与使用说明
    data/_status.tsv          采集进度机读表

设计要点
--------
1. **五级标记沿用 skill 现有口径**（✅A / ✅A- / ✅B / ⚠️ / ❌），
   判据全部写进 md，不写「算法黑箱」。
2. **美食 × 商圈关联用几何就近 + 名称互证双轨**：
   只算距离会把「岳阳楼景区外的肯德基」也算进汴河街，因此要求
   商圈名或其同义段落在 POI 地址/名称中互证，或直线距离 ≤600m
   且同区县。互证失败的降级为 ⚠️。
3. **苍蝇馆不做无据判定**：仅当 POI 命中「苍蝇馆」关键词、或
   名称含 小馆/排挡/家常/私房 等小店语义且评分在 3.6–4.5 区间时
   列为候选，其余一律不标——宁可漏，不可编。
4. **儿童游乐必须区分载体**：
   「商场内」与「独立门店」的可靠性、可达性完全不同，混在一张表里
   会让用户跑空。判定：地址/名称含 商场/购物中心/MALL/广场/百货/大厦
   → 场内；否则 → 独立。
"""

import argparse
import collections
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, ".cache", "amap", "raw")
PROV = os.path.join(ROOT, ".cache", "amap", "prov_cities.json")
DATA = os.path.join(ROOT, "data")

# ── 城市 → 省会/省份映射由 prov_cities.json 反推 ──

MALL_CTX = ("商场", "购物中心", "MALL", "mall", "广场", "百货", "大厦",
            "购物广场", "商业广场", "购物城", "商贸城", "城市广场", "广场")
STREET_CTX = ("步行街", "商业街", "美食街", "老街", "小吃街", "夜市", "街区",
              "后街", "巷", "大街", "路", "牌坊", "古镇", "码头", "坡子街")
SMALL_SHOP_KW = ("小馆", "排挡", "家常", "私房", "苍蝇馆", "小店", "夫妻店",
                 "土菜", "农家", "食堂", "小吃店", "夜宵店", "烧烤店", "大排档")
LOCAL_DISH_KW = ("本地菜", "地方菜", "土菜", "湘菜", "特色", "老字号",
                 "传统", "家乡", "农家", "私房", "正宗", "小吃")

PRODUCT_CTX = ("特产", "土特产", "地方特产", "老字号", "腊味", "酱", "茶叶",
               "糕饼", "糖", "酒", "米粉", "腐乳", "辣椒", "干货", "竹")


def haversine(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def has_ctx(text, words):
    if not text:
        return False
    return any(w in text for w in words)


def mark_poi(p):
    """五级标记：✅A / ✅A- / ✅B / ⚠️ / ❌"""
    r = p.get("rating")
    try:
        r = float(r) if r is not None else None
    except (TypeError, ValueError):
        r = None
    name = p.get("name") or ""
    addr = p.get("address") or ""
    ty = p.get("type") or ""
    if not p.get("id"):
        return "❌", "无 POI ID，无法回查原始记录"
    if not addr:
        return "❌", "无地址，用户无法前往"
    if r is None:
        return "⚠️", "高德未收录评分，口碑未知"
    if r >= 4.6 and has_ctx(name + addr, LOCAL_DISH_KW):
        return "✅A", "评分 %.1f 且带本地/老字号语义" % r
    if r >= 4.6:
        return "✅A-", "评分 %.1f（无本地语义标记）" % r
    if r >= 4.3:
        return "✅B", "评分 %.1f" % r
    if r < 3.5:
        return "❌", "评分 %.1f，低于 3.5 不建议推荐" % r
    return "⚠️", "评分 %.1f，处于待观察区间" % r


def is_mall(text):
    return has_ctx(text, MALL_CTX)


def street_of(p):
    """取该 POI 所属街道/商圈线索，用于关联匹配。"""
    return (p.get("adname") or "") + (p.get("address") or "")


# ---------------------------------------------------------------- 关联逻辑
def link_food_to_district(foods, districts):
    """为每个商圈找其关联美食。返回 {district_name: [(poi, dist, mode)]}"""
    out = collections.defaultdict(list)
    for d in districts:
        dname = d.get("name") or ""
        # 商圈名简化：取去掉括号的核心词
        core = dname.split("(")[0].split("（")[0]
        for f in foods:
            blob = (f.get("name") or "") + " " + (f.get("address") or "")
            dist = haversine(d["lat"], d["lng"], f["lat"], f["lng"])
            mode = None
            if core and len(core) >= 2 and core in blob:
                mode = "名称互证"
            elif dist is not None and dist <= 600 and \
                    (f.get("adname") or "") == (d.get("adname") or ""):
                mode = "距离就近"
            if mode:
                out[dname].append((f, dist, mode))
    for k in out:
        out[k].sort(key=lambda t: (t[1] if t[1] is not None else 9e9))
    return out


# ---------------------------------------------------------------- 渲染
def fmt_addr(p):
    a = p.get("address") or ""
    return a if a else "—"


def cell(v):
    """表格单元格净化：ASCII 竖线会撑破 md 表格列数，统一转全角。

    实测缺陷（v0.6.0）：高德店名「INXX CLUB(英克斯酒吧|濮阳店)」
    原样写入后表格列数 +1，校验器 C2 抓到。既在采集端 normalize()
    做了替换，渲染端也兜底——旧缓存数据没有这层净化。
    """
    if v is None:
        return "—"
    s = str(v)
    if not s:
        return "—"
    return s.replace("|", "｜")


def render_city(city, cache, prov_name):
    qs = cache.get("queries") or {}
    allp = [p for q in qs.values() for p in q.get("items", [])]
    uniq = {}
    for p in allp:
        if p.get("id"):
            uniq[p["id"]] = p
    pois = list(uniq.values())
    updated = cache.get("updated") or "未知"
    errs = cache.get("errors") or []

    # 分类
    food, product, district, night, kids = [], [], [], [], []
    for p in pois:
        facet = qs.get("", {})
        tc = p.get("typecode") or ""
        ty = p.get("type") or ""
        name = p.get("name") or ""
        addr = p.get("address") or ""
        blob = name + " " + addr
        if tc.startswith("0501") or tc.startswith("050300"):
            food.append(p)
        if any(k in blob for k in PRODUCT_CTX) or tc.startswith("0607"):
            product.append(p)
        if tc.startswith("061") or is_mall(blob) or has_ctx(blob, STREET_CTX):
            district.append(p)
        if tc.startswith("080304") or "酒馆" in blob or "livehouse" in blob.lower():
            night.append(p)
        if tc.startswith("0805") or any(k in blob for k in (
                "儿童乐园", "电玩", "游乐场", "淘气堡", "亲子",
                "儿童体验", "迷你游乐")):
            kids.append(p)

    # 去重
    def dedup(lst):
        seen, out = set(), []
        for p in lst:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            out.append(p)
        return out
    food, product, district, night, kids = (
        dedup(food), dedup(product), dedup(district),
        dedup(night), dedup(kids))

    # 排序：评分高者优先
    def key(p):
        try:
            return -float(p.get("rating") or 0)
        except (TypeError, ValueError):
            return 0
    food.sort(key=key)
    product.sort(key=key)
    district.sort(key=key)
    night.sort(key=key)
    kids.sort(key=key)

    linked = link_food_to_district(food + night, district[:40])

    L = []
    w = L.append
    w("# %s · %s 美食与商圈档案" % (city, prov_name))
    w("")
    w("> 数据来源：高德地图 Web 服务 POI（restapi.amap.com）  ")
    w("> 采集时间：%s  ·  POI 总量：%d（去重后）  ·  查询面：%d  " % (
        updated, len(pois), len(qs)))
    w("> 文件用途：本 skill 的城市级数据可查与人工校对底稿。")
    w("")

    # ── 0. 数据可信度 ──
    w("## 0. 数据可信度")
    w("")
    w("| 项 | 值 | 说明 |")
    w("|---|---|---|")
    w("| POI 总数（去重） | %d | 高德 POI id 去重 |" % len(pois))
    w("| 有评分的比例 | %.0f%% | 无评分者标 ⚠️，不强行推荐 |" % (
        100.0 * sum(1 for p in pois if p.get("rating")) / max(len(pois), 1)))
    w("| 查询面数 | %d | 见 §7 原始查询清单 |" % len(qs))
    if errs:
        w("| ⚠️ 采集告警 | %d 条 | %s |" % (len(errs), "；".join(errs[:3])))
    else:
        w("| 采集告警 | 0 | 本次采集无配额或接口错误 |")
    w("")

    # ── 1. 本地美食 / 特色美食 ──
    w("## 1. 本地美食与特色美食（%d 家）" % len(food))
    w("")
    w("标记口径：✅A 评分≥4.6 且带本地/老字号语义；✅A- 评分≥4.6；"
      "✅B 评分 4.3–4.6；⚠️ 3.5–4.3 或无评分；❌ <3.5 或无地址。")
    w("")
    w("| 标记 | 店名 | 类型 | 评分 | 人均 | 地址 | 图片 |")
    w("|---|---|---|---|---|---|---|")
    for p in food[:80]:
        mk, _why = mark_poi(p)
        img = "![图](https://store.is.autonavi.com/showpic/%s)" % \
              (p["photos"][0].split("/")[-1]) if p.get("photos") else ""
        w("| %s | %s | %s | %s | %s | %s | %s |" % (
            mk, cell(p.get("name")), (p.get("type") or "").replace("|", "/"),
            p.get("rating") or "—", p.get("cost") or "—",
            cell(p.get("address")), img))
    if len(food) > 80:
        w("")
        w("（另 %d 家见 §7 原始数据，评分排序后 80 名未列入）" % (len(food) - 80))
    w("")

    # ── 2. 苍蝇馆候选 ──
    w("## 2. 苍蝇馆 / 小店候选（%d 家）" % len(
        [p for p in food if has_ctx(p.get("name") or "", SMALL_SHOP_KW)]))
    w("")
    w("**判定纪律**：不凭空判定「苍蝇馆」。仅当命中高德「苍蝇馆」关键词，"
      "或店名含 小馆/排挡/家常/私房/土菜/大排档 等小店语义时列为候选；"
      "「苍蝇馆」本意是环境朴素但味道好的小店，与评分无必然关系，"
      "因此评分区间放宽到 3.6–4.6。")
    w("")
    w("| 店名 | 来源查询面 | 评分 | 人均 | 地址 | 备注 |")
    w("|---|---|---|---|---|---|")
    for p in food:
        name = p.get("name") or ""
        if not has_ctx(name, SMALL_SHOP_KW):
            continue
        src = "苍蝇馆关键词" if "苍蝇馆" in name else "店名小店语义"
        try:
            r = float(p.get("rating") or 0)
        except (TypeError, ValueError):
            r = 0
        note = ""
        if r < 3.6 or r > 4.6:
            note = "评分 %.1f 超出苍蝇馆常见区间，仅登记不推荐" % r
        w("| %s | %s | %s | %s | %s | %s |" % (
            cell(name), src, p.get("rating") or "—", p.get("cost") or "—",
            cell(p.get("address")), note))
    w("")

    # ── 3. 知名特产 ──
    w("## 3. 知名特产（%d 家）" % len(product))
    w("")
    w("| 标记 | 名称 | 类型 | 评分 | 地址 |")
    w("|---|---|---|---|---|")
    for p in product[:60]:
        mk, _ = mark_poi(p)
        w("| %s | %s | %s | %s | %s |" % (
            mk, cell(p.get("name")), (p.get("type") or "").replace("|", "/"),
            p.get("rating") or "—", cell(p.get("address"))))
    if len(product) > 60:
        w("")
        w("（另 %d 家见 §7）" % (len(product) - 60))
    w("")

    # ── 4. 商圈 ──
    w("## 4. 商圈总览（%d 处）" % len(district))
    w("")
    w("口径：购物服务 061001 步行街 / 061000 特色商业街 / 060101 购物中心 / "
      "060100 商场，或名称地址含商业街/步行街/夜市/美食街等载体词。")
    w("")
    w("| 标记 | 商圈名 | 类型 | 评分 | 关联美食数 | 地址 |")
    w("|---|---|---|---|---|---|")
    for p in district[:60]:
        mk, _ = mark_poi(p)
        n = len(linked.get(p.get("name") or "", []))
        w("| %s | %s | %s | %s | %d | %s |" % (
            mk, cell(p.get("name")), (p.get("type") or "").replace("|", "/"),
            p.get("rating") or "—", n, cell(p.get("address"))))
    if len(district) > 60:
        w("")
        w("（另 %d 处见 §7）" % (len(district) - 60))
    w("")

    # ── 5. 商圈 × 美食 关联 ──
    w("## 5. 美食 × 商圈 关联")
    w("")
    w("关联方式：① 名称互证（美食店名/地址含商圈核心词）；"
      "② 距离就近（≤600m 且同区县）。仅靠距离的关联标 ⚠️，"
      "因为景区边界、跨街区的误配都靠距离无法排除。")
    w("")
    for dname, lst in list(linked.items())[:25]:
        w("### %s（%d 家）" % (dname, len(lst)))
        w("")
        w("| 店名 | 关联方式 | 直线距离 | 评分 | 数据位置 |")
        w("|---|---|---|---|---|")
        for f, dist, mode in lst[:25]:
            nm = f.get("name") or ""
            # §1 只列评分前 80 名，其余条目指向 §7 原始 JSON，
            # 保证任何引用都可回查（C6：引用完整性，而非位置一致）
            where = "§1" if any(f.get("name") == q.get("name")
                                for q in food[:80]) else "§7"
            w("| %s | %s | %s | %s | %s |" % (
                cell(nm), mode,
                ("%dm" % round(dist)) if dist is not None else "—",
                f.get("rating") or "—", where))
        w("")

    # ── 6. 商圈儿童游乐 ──
    w("## 6. 商圈儿童游乐 / 电玩 / 迷你游乐场（%d 家）" % len(kids))
    w("")
    w("**载体区分**：`场内` = 位于商场/购物中心/广场内（可顺路，"
      "通常与逛吃同动线）；`独立` = 独立门店或园区内点位（需单独规划）。"
      "两者可靠性、可达性完全不同，混表会导致跑空。")
    w("")
    w("| 标记 | 名称 | 载体 | 类型 | 评分 | 地址 |")
    w("|---|---|---|---|---|---|")
    for p in kids[:60]:
        mk, _ = mark_poi(p)
        blob = (p.get("name") or "") + " " + (p.get("address") or "")
        carrier = "场内" if is_mall(blob) else "独立"
        w("| %s | %s | %s | %s | %s | %s |" % (
            mk, cell(p.get("name")), carrier,
            (p.get("type") or "").replace("|", "/"),
            p.get("rating") or "—", cell(p.get("address"))))
    if len(kids) > 60:
        w("")
        w("（另 %d 家见 §7）" % (len(kids) - 60))
    w("")

    # ── 7. 原始查询清单 ──
    w("## 7. 原始查询清单与原始数据")
    w("")
    w("| 维度 | 查询面 | 命中 | 备注 |")
    w("|---|---|---|---|")
    for label, q in qs.items():
        w("| %s | %s | %d | %s |" % (
            q.get("facet"), label, q.get("count"), q.get("note") or ""))
    w("")
    w("原始 JSON：`.cache/amap/raw/%s.json`（含高德返回全字段，"
      "含照片 URL、电话、营业时间）。" % city)
    w("")

    # ── 8. 校对待办 ──
    w("## 8. 校对待办")
    w("")
    todo = []
    noaddr = [p for p in pois if not p.get("address")]
    if noaddr:
        todo.append("**%d 个 POI 无地址**，需人工补：%s"
                    % (len(noaddr), "、".join(p["name"] for p in noaddr[:5])))
    norat = [p for p in pois if not p.get("rating")]
    if norat:
        todo.append("**%d 个 POI 无评分**，暂标 ⚠️：%s"
                    % (len(norat), "、".join(p["name"] for p in norat[:5])))
    mall_ct = sum(1 for p in kids if is_mall(
        (p.get("name") or "") + " " + (p.get("address") or "")))
    todo.append("儿童游乐 %d 家，其中场内 %d 家、独立 %d 家——"
                "需确认场内点位是否仍在营业（商场撤柜率高）。"
                % (len(kids), mall_ct, len(kids) - mall_ct))
    todo.append("§5 关联中，仅靠距离就近的条目需逐条确认"
                "（防止景区/跨街区误配）。")
    if errs:
        todo.append("采集有告警：%s" % "；".join(errs[:3]))
    todo.append("本城 POI 覆盖 %d 个区县：%s——缺区县的需补充采集。"
                % (len(set(p.get("adname") for p in pois if p.get("adname"))),
                   "、".join(sorted(set(
                       p["adname"] for p in pois if p.get("adname"))))))
    for t in todo:
        w("- [ ] %s" % t)
    w("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", help="只生成该市")
    ap.add_argument("--province")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    provs = json.load(open(PROV, encoding="utf-8"))
    os.makedirs(DATA, exist_ok=True)

    targets = []          # (省, 市)
    if args.city:
        for pname, v in provs.items():
            for c in v["cities"]:
                if c[1] == args.city:
                    targets.append((pname, args.city))
    elif args.province:
        for c in provs.get(args.province, {}).get("cities", []):
            targets.append((args.province, c[1]))
    elif args.all:
        for pname, v in provs.items():
            for c in v["cities"]:
                targets.append((pname, c[1]))

    made = 0
    for pname, city in targets:
        fp = os.path.join(RAW, city + ".json")
        if not os.path.exists(fp):
            continue
        cache = json.load(open(fp, encoding="utf-8"))
        outdir = os.path.join(DATA, pname)
        os.makedirs(outdir, exist_ok=True)
        md = render_city(city, cache, pname)
        outp = os.path.join(outdir, city + ".md")
        with open(outp, "w", encoding="utf-8") as f:
            f.write(md)
        made += 1
    print("生成 %d 个城市档案 → %s" % (made, DATA))


if __name__ == "__main__":
    main()
