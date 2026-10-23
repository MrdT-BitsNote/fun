#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全国省市「美食 × 商圈 × 娱乐」md 生成器 v0.7.1

v0.7.1：休闲娱乐分类体系（原「成人娱乐」正名扩展）+ 商圈载体判定修复
（剥离分店后缀，防门店误判为商圈载体）

把 .cache/amap/raw/{城市}.json 渲染成可查、可校对的 md 档案。

v0.7.0 结构重构（吸收同类产品优点后重设计）
--------------------------------------------------------------------
对标对象与吸收点：
  1. 大众点评必吃榜 —— 五维评选（真实/口味/稳定/性价比/本地性）：
     评级必须「维度可解释」，因此每个 POI 与商圈都带判据说明，
     不写算法黑箱；商圈级新增 S/A/B/C 评级。
  2. 高德 21 主类 193 子类分类体系 —— 分类码驱动，
     不靠名称猜；名称语义只做兜底。
  3. 开源全国商圈数据集（BusinessDistrict 等）—— 只有「名称+坐标」，
     无评级、无业态构成、无关联，用户查了还得自己跑一趟。
     本库补齐：画像、业态分布、关联、评级、可回查指针。
  4. POI 开源数据集（Iter-X 等）—— 多语言/结构化字段：
     每个实体都带分类、坐标、评级、图片、来源查询面。

输出结构（每城 md）
--------------------------------------------------------------------
  0. 数据可信度
  1. 城市总览（行政层级 + 商圈分布统计 + 业态构成）
  2. 商圈档案（每商圈：画像 + 业态分布总结 + 评级 S/A/B/C）
  3. 休闲娱乐（KTV/夜店/酒吧/清吧/游乐场/卡丁车/体育馆/足疗按摩/影院/游戏厅）
  4. 儿童与亲子（儿童乐园/淘气堡/迷你游乐场/亲子乐园/迷你动物园/萌宠/电玩）
  5. 综合体与商场（购物中心/百货/奥莱/批发城）
  6. 本地美食与特色美食
  7. 苍蝇馆候选
  8. 知名特产
  9. 美食 × 商圈关联
 10. 酒店配套（商圈住宿）
 11. 原始查询清单与数据
 12. 校对待办

设计纪律
--------------------------------------------------------------------
1. 画像能推导的推导（载体类型/消费带宽/动线主轴/关联规模），
   不能推导的如实标「待人工校对」——绝不编造。
2. 商圈评级判据全部写进 md，可复算。
3. 五级标记沿用 skill 口径：✅A / ✅A- / ✅B / ⚠️ / ❌。
4. 表格单元格净化 ASCII 竖线（v0.6.0 事故）。
"""

import argparse
import collections
import json
import math
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, ".cache", "amap", "raw")
PROV = os.path.join(ROOT, ".cache", "amap", "prov_cities.json")
HIER = os.path.join(ROOT, ".cache", "amap", "city_districts.json")
DATA = os.path.join(ROOT, "data")

# ── 分类码口径（高德 21 主类，本文档用到的子集）──
TC = {
    "food": ("050100", "050101", "050102", "050103", "050104", "050105",
             "050106", "050107", "050108", "050109", "050110", "050111",
             "050112", "050113", "050114", "050115", "050116", "050117",
             "050118", "050119", "050120", "050121", "050122", "050123",
             "050200", "050300", "050301", "050302", "050500"),
    "hotel": ("100000", "100100", "100200", "100300", "100400", "100500",
              "100600", "100700", "100800", "100900", "101000", "101100",
              "101200", "101300"),
    "mall": ("060100", "060101", "060102", "060200", "060201", "060202",
             "060400", "060401", "060402", "060500"),
    "street": ("061000", "061001", "061002", "061100", "061101"),
    "night": ("080304", "080301", "080302", "080303", "080305"),
    # 休闲娱乐（v0.7.1）：酒吧/KTV/电影院/运动场馆/游乐场全族
    "leisure": ("080300", "080301", "080302", "080303", "080304", "080305",
                "080400", "080401", "080402", "080500", "080501", "080502",
                "080503", "080504", "080505", "080506", "080507", "080508",
                "080600", "080601", "080602", "080603", "080700", "080701",
                "080702", "080703"),
    "kids": ("080501", "080502", "080503", "080504", "080505", "080506",
             "080507", "080508"),
}

# 商圈载体类型（按优先级判定）
CARRIER_RULES = [
    ("美食街/小吃街", ("美食街", "小吃街", "食品街", "餐饮街")),
    ("夜市", ("夜市", "夜间集市")),
    ("步行街", ("步行街", "步行街")),
    ("商业街", ("商业街", "大街", "老街", "街区")),
    ("购物中心/综合体", ("购物中心", "购物广场", "商业广场", "城市广场",
                        "综合体", "SHOPPING", "Shopping")),
    ("百货/商场", ("百货", "商场", "商贸城", "商城")),
    ("奥特莱斯", ("奥特莱斯", "outlets", "Outlets")),
    ("批发城", ("批发", "商贸城", "小商品")),
]

MALL_CTX = ("商场", "购物中心", "MALL", "mall", "广场", "百货", "大厦",
            "购物广场", "商业广场", "购物城", "商贸城", "城市广场")
STREET_CTX = ("步行街", "商业街", "美食街", "老街", "小吃街", "夜市", "街区",
              "后街", "巷", "大街", "牌坊", "古镇", "码头")
SMALL_SHOP_KW = ("小馆", "排挡", "家常", "私房", "苍蝇馆", "小店", "夫妻店",
                 "土菜", "农家", "食堂", "小吃店", "夜宵店", "烧烤店", "大排档")
LOCAL_DISH_KW = ("本地菜", "地方菜", "土菜", "特色", "老字号", "传统",
                 "家乡", "农家", "私房", "正宗", "小吃")

# 休闲娱乐细分（v0.7.1：原「成人娱乐」正名并扩展语义）
# 覆盖：KTV/量贩KTV、夜店、酒吧、清吧、游乐场（成人向）、卡丁车、
#       体育馆/运动场馆、洗脚按摩（足疗/足浴/推拿）、电影院、游戏厅、
#       桌游、蹦床、密室逃脱、剧本杀、棋牌
LEISURE_ENT = [
    ("酒吧/清吧", ("酒吧", "酒馆", "清吧", "啤酒吧", "精酿", "bar ", "Bar",
                   "BAR", "CLUB", "club", "夜店", "Speakeasy", "speakeasy",
                   "小酒馆", "酒馆")),
    ("Livehouse", ("livehouse", "Livehouse", "LIVEHOUSE", "LiveHouse",
                   " liveshow", "LIVESHOW")),
    ("KTV/夜总会", ("KTV", "ktv", "量贩式KTV", "卡拉OK", "歌厅", "夜总会")),
    ("电影院", ("电影院", "影城", "影剧院", "剧院", "影咖")),
    ("游戏厅/电玩", ("电玩", "游戏厅", "游戏城", "桌游")),
    ("密室逃脱/剧本杀", ("密室", "剧本杀", "推理馆")),
    ("棋牌室", ("棋牌", "麻将馆")),
    ("运动场馆/体育馆", ("体育馆", "体育中心", "运动馆", "体育场", "体育馆",
                        "健身中心", "健身房")),
    ("卡丁车/赛车", ("卡丁车", "赛车", "竞速")),
    ("足疗按摩", ("足疗", "足浴", "按摩", "推拿", "艾灸", "spa", "SPA",
                  "沐足", "养生会所")),
    ("游乐场（成人向）", ("游乐场", "游乐园", "蹦床", "蹦极", "运动公园")),
    ("水上乐园/游泳馆", ("水上乐园", "水世界", "游泳馆", "游泳场", "水上活动")),
    ("度假村/农家乐", ("度假村", "农家乐", "生态园", "采摘", "疗养")),
    ("网吧/网咖/电竞", ("网咖", "网吧", "电竞", "网鱼")),
]
# 儿童娱乐细分（仅儿童向；成人向游乐场归休闲娱乐）
KIDS_ENT = [
    ("迷你动物园/萌宠", ("动物园", "萌宠", "宠物乐园", "动物乐园")),
    ("儿童乐园/游乐场", ("儿童乐园", "游乐场", "游乐园", "儿童游乐")),
    ("淘气堡", ("淘气堡",)),
    ("迷你游乐场", ("迷你游乐",)),
    ("亲子乐园", ("亲子", "儿童成长", "儿童体验")),
]

# 儿童向判定词：命中即归儿童类，不进休闲娱乐（即使名称含「游乐场」）
KIDS_ONLY = ("儿童", "亲子", "淘气堡", "迷你", "孕婴童", "婴童", "少儿")
# 强餐饮词：名称命中且不含娱乐词时，判定为餐饮店而非娱乐场所
# （v0.7.1 实测：高德会给餐酒吧/园区餐厅打混合 type，
#  「网网有鱼特色河鲜」type=娱乐场所;酒吧 但实为餐厅）
FOOD_STRONG = ("菜", "餐厅", "饭", "粉", "面馆", "海鲜", "河鲜", "火锅",
               "烧烤", "酒楼", "小吃", "农家", "食堂", "粥", "烤鱼",
               "龙虾", "牛肉", "羊肉", "鸡", "鸭", "鱼")


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


def strip_branch(name):
    """剥离分店区位后缀：「盛香亭转转热卤(岳阳步行街店)」→「盛香亭转转热卤」。

    v0.7.1 修复：门店名带区位后缀（步行街店/美食街店/百盛广场旗舰店）
    会让名称判定把门店误判成商圈载体——实测岳阳 §2 商圈档案混入了
    「酒蜗KTV(岳阳北辅街店)」「盛香亭(岳阳步行街店)」等门店。
    判定载体前必须先剥后缀；地址同样不参与载体判定（地址里的
    「XX路/百货」是门店位置，不是门店性质）。
    """
    n = name or ""
    prev = None
    while prev != n:
        prev = n
        n = re.sub(r"[（(][^）)]*[）)]\s*$", "", n).strip()
    return n


def has_ctx(text, words):
    if not text:
        return False
    return any(w in text for w in words)


def tc_in(p, group):
    tc = p.get("typecode") or ""
    return any(tc.startswith(t) or tc == t for t in TC.get(group, ()))


def mark_poi(p):
    """五级标记：✅A / ✅A- / ✅B / ⚠️ / ❌，判据可解释。"""
    r = p.get("rating")
    try:
        r = float(r) if r is not None else None
    except (TypeError, ValueError):
        r = None
    name = p.get("name") or ""
    addr = p.get("address") or ""
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


def carrier_of(poi):
    """POI 的商圈载体类型（剥离分店后缀后按名称判定，类型码兜底）。"""
    name = strip_branch(poi.get("name") or "")
    ty = poi.get("type") or ""
    blob = name + " " + ty
    for label, kws in CARRIER_RULES:
        if has_ctx(blob, kws):
            return label
    if tc_in(poi, "street"):
        return "商业街"
    if tc_in(poi, "mall"):
        return "购物中心/综合体"
    if has_ctx(name, STREET_CTX):
        return "商业街"
    return "其他商业载体"


def cell(v):
    """表格单元格净化：ASCII 竖线撑破列数（v0.6.0 实测事故）。"""
    if v is None:
        return "—"
    s = str(v)
    if not s:
        return "—"
    return s.replace("|", "｜")


def w_or_none(w, rows, note):
    """空表防护：无数据时不渲染空表头，显式写「无」及原因。

    实测缺陷（v0.7.0）：新星市（兵团新城）无购物中心 POI，
    §5 渲染出只有表头的空表，校验器 C7 抓到。小城市维度稀疏是
    真实情况，必须显式说明，不能留一张空表让校对者困惑。
    """
    if not rows:
        w("")
        w("（%s）" % note)
        return False
    return True


def rating_of(lst):
    """列表均分（仅计有评分的）。"""
    rs = []
    for p in lst:
        try:
            v = float(p.get("rating"))
            if v > 0:
                rs.append(v)
        except (TypeError, ValueError):
            pass
    return (sum(rs) / len(rs)) if rs else None


def cost_band(lst):
    """人均带宽：返回 (中位数, 最低, 最高)，无人均返回 None。"""
    cs = []
    for p in lst:
        try:
            v = float(p.get("cost"))
            if v > 0:
                cs.append(v)
        except (TypeError, ValueError):
            pass
    if not cs:
        return None
    cs.sort()
    n = len(cs)
    med = cs[n // 2] if n % 2 else (cs[n // 2 - 1] + cs[n // 2]) / 2
    return (med, cs[0], cs[-1])


def unwrap(lst):
    """关联列表元素是 (poi, dist, mode) 三元组，取出 POI。"""
    return [t[0] if isinstance(t, tuple) else t for t in lst]


def district_grade(d, linked_food, linked_night, linked_kids, linked_hotel):
    """商圈级评级 S/A/B/C——判据可解释、可复算。

    借鉴必吃榜「维度化评选」：不搞单一人气分，而是分维度达标。
      S：关联美食 ≥20 家且均分 ≥4.3，且覆盖 ≥3 类业态（美食/娱乐/酒店）
      A：关联美食 ≥10 家且均分 ≥4.0，且覆盖 ≥2 类业态
      B：关联美食 ≥5 家，或任一业态 ≥10 家
      C：其余（数据稀薄，仅登记）
    """
    lf, ln, lk, lh = (unwrap(linked_food), unwrap(linked_night),
                      unwrap(linked_kids), unwrap(linked_hotel))
    n_food, n_night, n_kids, n_hotel = len(lf), len(ln), len(lk), len(lh)
    dims = sum(1 for x in (n_food, n_night, n_kids, n_hotel) if x > 0)
    avg = rating_of(lf)
    if n_food >= 20 and avg is not None and avg >= 4.3 and dims >= 3:
        return "S", ("美食 %d 家（均分 %.2f）+ %d 类业态"
                     % (n_food, avg, dims))
    if n_food >= 10 and avg is not None and avg >= 4.0 and dims >= 2:
        return "A", ("美食 %d 家（均分 %.2f）+ %d 类业态"
                     % (n_food, avg, dims))
    if n_food >= 5 or max(n_food, n_night, n_kids, n_hotel) >= 10:
        return "B", ("美食 %d 家 / 娱乐 %d / 酒店 %d"
                     % (n_food, n_night + n_kids, n_hotel))
    return "C", "关联数据稀薄，仅登记待人工补充"


def link_poi_to_district(pois, districts):
    """商圈关联：① 名称互证；② 距离就近 ≤600m 且同区县。"""
    out = collections.defaultdict(list)
    for d in districts:
        dname = d.get("name") or ""
        core = dname.split("(")[0].split("（")[0]
        for f in pois:
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


def main_road_of(pois):
    """动线主轴：关联 POI 地址里出现最多的道路/街道词。"""
    cnt = collections.Counter()
    for p in pois:
        addr = p.get("address") or ""
        for seg in ("大道", "大街", "路", "街", "巷"):
            i = addr.find(seg)
            if i > 1:
                cnt[addr[max(0, i - 4):i + len(seg)]] += 1
                break
    if not cnt:
        return None
    return cnt.most_common(1)[0][0]


def render_city(city, cache, prov_name, hier=None):
    qs = cache.get("queries") or {}
    allp = [p for q in qs.values() for p in q.get("items", [])]
    uniq = {}
    for p in allp:
        if p.get("id"):
            uniq[p["id"]] = p
    pois = list(uniq.values())
    updated = cache.get("updated") or "未知"
    errs = cache.get("errors") or []
    waves = cache.get("waves") or [1]

    # ── POI 分类：facet 优先，类型码兜底 ──
    facets = collections.defaultdict(set)
    for label, q in qs.items():
        for p in q.get("items", []):
            if p.get("id"):
                facets[p["id"]].add(q.get("facet"))

    food, product, district, night, kids, hotel, leisure = \
        [], [], [], [], [], [], []
    for p in pois:
        fs = facets.get(p["id"], set())
        name = p.get("name") or ""
        addr = p.get("address") or ""
        blob = name + " " + addr + " " + (p.get("type") or "")
        low = blob.lower()
        # 美食
        if "food" in fs or tc_in(p, "food"):
            food.append(p)
        # 特产
        if "product" in fs or ("特产" in blob):
            product.append(p)
        # 商圈载体（v0.7.1：三重修正）
        # ① 剥离分店后缀后按名称判定——「盛香亭(岳阳步行街店)」不是载体
        # ② 地址不参与判定——地址含「XX路/百货」是位置不是性质
        # ③ 类型码护栏：06 购物服务 或 050000 餐饮相关场所（高德把
        #    美食街/夜市归在 050000）；050100+ 是具体餐厅，不是载体。
        #    实测：关键词"小吃街"夹带「细毛私房菜」tc=050100，
        #    "本地菜"返回「巴陵玖号老街菜馆」名称含"老街" tc=050100
        core_name = strip_branch(name)
        tc = p.get("typecode") or ""
        is_carrier_tc = tc.startswith("06") or tc == "050000"
        if (is_carrier_tc
                and ("district" in fs or tc_in(p, "street")
                     or tc_in(p, "mall") or has_ctx(core_name, STREET_CTX)
                     or is_mall(core_name))):
            district.append(p)
        # 夜生活（酒吧/酒馆/livehouse，休闲娱乐的酒吧子类来源）
        if "nightlife" in fs or tc_in(p, "night"):
            night.append(p)
        # 休闲娱乐（v0.7.1：原成人娱乐，含 wave3 补采面与语义兜底）
        ent_kw = ("密室", "剧本杀", "KTV", "ktv", "电影院",
                  "影城", "影剧院", "棋牌", "游戏厅", "游戏城",
                  "足疗", "足浴", "按摩", "推拿", "艾灸",
                  "卡丁车", "体育馆", "体育中心", "蹦床", "网咖",
                  "网吧", "电竞")
        if ("leisure" in fs or "adult" in fs or tc_in(p, "leisure")
                or has_ctx(blob, ent_kw)):
            # 儿童向游乐场（儿童乐园/亲子/淘气堡/迷你）归儿童类，不进休闲娱乐
            if has_ctx(name + addr, KIDS_ONLY):
                pass
            # 餐饮护栏：名称是强餐饮词且无任何娱乐语义，判为餐厅
            elif (has_ctx(name, FOOD_STRONG)
                  and not has_ctx(name, ("吧", "CLUB", "club", "酒", "咖",
                                         "KTV", "ktv", "影", "玩", "乐"))):
                pass
            else:
                leisure.append(p)
        # 儿童（仅儿童向）
        if "kids" in fs or has_ctx(blob, (
                "儿童乐园", "电玩", "游乐场", "淘气堡", "亲子",
                "儿童体验", "迷你游乐", "动物园", "萌宠")):
            if has_ctx(name + addr, KIDS_ONLY) or has_ctx(
                    name, ("儿童乐园", "淘气堡", "亲子", "迷你", "萌宠")):
                kids.append(p)
        # 酒店
        if "hotel" in fs or tc_in(p, "hotel"):
            hotel.append(p)

    def dedup(lst):
        seen, out = set(), []
        for p in lst:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            out.append(p)
        return out

    food, product, district, night, kids, hotel, leisure = (
        dedup(food), dedup(product), dedup(district), dedup(night),
        dedup(kids), dedup(hotel), dedup(leisure))

    def key(p):
        try:
            return -float(p.get("rating") or 0)
        except (TypeError, ValueError):
            return 0
    for lst in (food, product, district, night, kids, hotel, leisure):
        lst.sort(key=key)

    # 商圈关联（美食 + 休闲娱乐 + 儿童 + 酒店）
    leisure_all = dedup(night + leisure)   # 两列表有重叠，先去重再关联
    linked = link_poi_to_district(
        food + leisure_all + kids + hotel, district[:60])
    food_linked = link_poi_to_district(food, district[:60])
    leisure_linked = link_poi_to_district(leisure_all, district[:60])
    kids_linked = link_poi_to_district(kids, district[:60])
    hotel_linked = link_poi_to_district(hotel, district[:60])

    # 区县分布
    adname_cnt = collections.Counter(
        p.get("adname") for p in pois if p.get("adname"))
    # 商圈载体类型构成
    carrier_cnt = collections.Counter(carrier_of(p) for p in district)

    L = []
    w = L.append
    w("# %s · %s 美食与商圈档案" % (city, prov_name))
    w("")
    w("> 数据来源：高德地图 Web 服务 POI（restapi.amap.com）  ")
    w("> 采集时间：%s  ·  POI 总量：%d（去重后）  ·  查询面：%d  ·  "
      "查询波次：%s  " % (updated, len(pois), len(qs),
                        "+".join(str(x) for x in waves)))
    w("> 文件用途：本 skill 的城市级数据可查与人工校对底稿。")
    w("")

    # ── 0. 可信度 ──
    w("## 0. 数据可信度")
    w("")
    w("| 项 | 值 | 说明 |")
    w("|---|---|---|")
    w("| POI 总数（去重） | %d | 高德 POI id 去重 |" % len(pois))
    rated = sum(1 for p in pois if p.get("rating"))
    w("| 有评分的比例 | %.0f%% | 无评分者标 ⚠️，不强行推荐 |"
      % (100.0 * rated / max(len(pois), 1)))
    w("| 维度覆盖 | 美食 %d · 商圈 %d · 休闲娱乐 %d · 儿童娱乐 %d · 酒店 %d · 特产 %d | 各维度去重计数 |"
      % (len(food), len(district), len(leisure_all),
         len(kids), len(hotel), len(product)))
    if errs:
        w("| ⚠️ 采集告警 | %d 条 | %s |" % (len(errs), "；".join(errs[:3])))
    else:
        w("| 采集告警 | 0 | 本次采集无配额或接口错误 |")
    miss = [wv for wv in (1, 2, 3) if wv not in waves]
    if miss:
        miss_desc = {1: "美食/特产/商圈基础面",
                     2: "酒店/迷你动物园/百货奥莱",
                     3: "休闲娱乐（KTV/影院/体育馆/足疗/卡丁车）"}
        w("| ⚠️ 维度不全 | 缺 wave%s | 本档案未含%s补采面，"
          "需跑 `amap_collect.py --city %s --wave %s` |"
          % ("/".join(str(m) for m in miss),
             "、".join(miss_desc[m] for m in miss), city,
             "/".join(str(m) for m in miss)))
    w("")

    # ── 1. 城市总览 ──
    w("## 1. 城市总览")
    w("")
    if hier and city in hier:
        h = hier[city]
        w("### 1.1 行政层级")
        w("")
        w("| 项 | 值 |")
        w("|---|---|")
        w("| 所属 | %s · %s |" % (h["province"], h["kind"]))
        w("| 下级区县 | %d 个 |" % len(h["districts"]))
        tw_total = sum(d["township_total"] for d in h["districts"])
        w("| 街道/镇/乡 | %d 个 |" % tw_total)
        dk = collections.Counter(d["kind"] for d in h["districts"])
        w("| 区县构成 | %s |" % "、".join(
            "%s×%d" % (k, v) for k, v in dk.most_common()))
        w("")
        w("（村级数据高德不提供，未列入；行政层级详见 "
          "`data/行政层级总览.md`）")
        w("")
    w("### 1.2 商圈与业态分布")
    w("")
    w("| 区县 | POI 数 | 占比 |")
    w("|---|---|---|")
    for ad, n in adname_cnt.most_common(15):
        w("| %s | %d | %.0f%% |"
          % (cell(ad), n, 100.0 * n / max(len(pois), 1)))
    if len(adname_cnt) > 15:
        w("")
        w("（另 %d 个区县见原始数据）" % (len(adname_cnt) - 15))
    w("")
    w("**商圈载体类型构成**（%d 处商圈锚点）：" % len(district))
    w("")
    if w_or_none(w, carrier_cnt.most_common(),
                 "本城未采集到购物服务类（06 开头）或餐饮相关场所"
                 "（050000）POI，无商圈锚点"):
        w("")
        w("| 载体类型 | 数量 |")
        w("|---|---|")
        for k, v in carrier_cnt.most_common():
            w("| %s | %d |" % (k, v))
    w("")

    # ── 2. 商圈档案 ──
    w("## 2. 商圈档案（%d 处，按评级排序）" % len(district))
    w("")
    w("商圈评级判据（借鉴必吃榜维度化评选，可复算）：")
    w("")
    w("| 评级 | 判据 |")
    w("|---|---|")
    w("| S | 关联美食 ≥20 家且均分 ≥4.3，覆盖 ≥3 类业态（美食/娱乐/儿童/酒店） |")
    w("| A | 关联美食 ≥10 家且均分 ≥4.0，覆盖 ≥2 类业态 |")
    w("| B | 关联美食 ≥5 家，或任一业态 ≥10 家 |")
    w("| C | 其余（数据稀薄，仅登记待人工补充） |")
    w("")

    # 评级排序
    graded = []
    for p in district[:40]:
        dname = p.get("name") or ""
        lf = food_linked.get(dname, [])
        ln = leisure_linked.get(dname, [])
        lk = kids_linked.get(dname, [])
        lh = hotel_linked.get(dname, [])
        g, why = district_grade(p, lf, ln, lk, lh)
        graded.append((g, p, lf, ln, lk, lh, why))
    gorder = {"S": 0, "A": 1, "B": 2, "C": 3}
    graded.sort(key=lambda t: (gorder[t[0]], -len(t[2])))

    if not w_or_none(w, graded, "本城未采集到商圈锚点 POI"):
        w("")
    else:
        w("| 评级 | 商圈名 | 载体类型 | 评分 | 关联美食 | 休闲娱乐 | 儿童娱乐 | 酒店 |")
        w("|---|---|---|---|---|---|---|---|")
    for g, p, lf, ln, lk, lh, why in graded[:40]:
        w("| %s | %s | %s | %s | %d | %d | %d | %d |" % (
            g, cell(p.get("name")), carrier_of(p),
            p.get("rating") or "—", len(lf), len(ln), len(lk), len(lh)))
    w("")

    # 每个商圈一节画像
    for g, p, lf, ln, lk, lh, why in graded[:15]:
        dname = p.get("name") or ""
        w("### %s —— 评级 %s" % (cell(dname), g))
        w("")
        w("- **评级判据**：%s" % why)
        w("- **载体类型**：%s（%s）" % (carrier_of(p), cell(p.get("type") or "")))
        w("- **地址**：%s" % cell(p.get("address") or "—"))
        cb = cost_band([f for f, _d, _m in lf])
        if cb:
            w("- **消费带宽**：关联美食人均中位数 ¥%.0f（区间 ¥%.0f–%.0f）"
              % (cb[0], cb[1], cb[2]))
        else:
            w("- **消费带宽**：待人工校对（高德未收录人均）")
        mr = main_road_of([f for f, _d, _m in lf])
        w("- **动线主轴**：%s" % (mr or "待人工校对（关联 POI 地址无道路词）"))
        w("- **业态分布**：美食 %d · 休闲娱乐 %d · 儿童娱乐 %d · 酒店 %d"
          % (len(lf), len(ln), len(lk), len(lh)))
        # 业态分布总结表
        rows = [
            ("步行街/商业街载体", [p]),
            ("美食", [f for f, _d, _m in lf]),
            ("休闲娱乐", [f for f, _d, _m in ln]),
            ("儿童娱乐", [f for f, _d, _m in lk]),
            ("酒店配套", [f for f, _d, _m in lh]),
        ]
        w("")
        w("| 业态 | 家数 | 代表（按评分） |")
        w("|---|---|---|")
        for label, lst in rows:
            if not lst:
                continue
            top = sorted(lst, key=key)[:3]
            w("| %s | %d | %s |" % (
                label, len(lst),
                "、".join(cell(x.get("name")) for x in top)))
        w("")

    # ── 3. 休闲娱乐（v0.7.1：原成人娱乐正名，含 KTV/夜店/酒吧/清吧/
    #     游乐场/卡丁车/体育馆/足疗按摩/影院/游戏厅/桌游/密室/棋牌）──
    w("## 3. 休闲娱乐（%d 家）" % len(leisure_all))
    w("")
    sub_cnt = collections.Counter()
    for p in leisure_all:
        blob = ((p.get("name") or "") + " " + (p.get("address") or "") + " "
                + (p.get("type") or ""))
        for label, kws in LEISURE_ENT:
            if has_ctx(blob, kws):
                sub_cnt[label] += 1
                break
        else:
            sub_cnt["其他娱乐场所"] += 1
    if sub_cnt:
        w("| 子类 | 家数 |")
        w("|---|---|")
        for k, v in sub_cnt.most_common():
            w("| %s | %d |" % (k, v))
        w("")
    if w_or_none(w, leisure_all, "本城未采集到休闲娱乐 POI"):
        w("")
        w("| 标记 | 名称 | 子类 | 类型 | 评分 | 人均 | 地址 |")
        w("|---|---|---|---|---|---|---|")
    for p in leisure_all[:60]:
        mk, _ = mark_poi(p)
        blob = ((p.get("name") or "") + " " + (p.get("address") or "") + " "
                + (p.get("type") or ""))
        sub = "其他娱乐场所"
        for label, kws in LEISURE_ENT:
            if has_ctx(blob, kws):
                sub = label
                break
        w("| %s | %s | %s | %s | %s | %s | %s |" % (
            mk, cell(p.get("name")), sub,
            (p.get("type") or "").replace("|", "/"),
            p.get("rating") or "—", p.get("cost") or "—",
            cell(p.get("address"))))
    if len(leisure_all) > 60:
        w("")
        w("（另 %d 家见 §11 原始数据）" % (len(leisure_all) - 60))
    w("")

    # ── 4. 儿童与亲子 ──
    w("## 4. 儿童与亲子娱乐（%d 家）" % len(kids))
    w("")
    w("**载体区分**：`场内` = 位于商场/购物中心/广场内（可顺路，"
      "与逛吃同动线）；`独立` = 独立门店或园区点位（需单独规划）。"
      "两者可靠性、可达性完全不同，混表会导致跑空。")
    w("")
    kidsub = collections.Counter()
    for p in kids:
        blob = (p.get("name") or "") + " " + (p.get("address") or "")
        for label, kws in KIDS_ENT:
            if has_ctx(blob, kws):
                kidsub[label] += 1
                break
        else:
            kidsub["其他儿童场所"] += 1
    if kidsub:
        w("| 子类 | 家数 |")
        w("|---|---|")
        for k, v in kidsub.most_common():
            w("| %s | %d |" % (k, v))
        w("")
    if w_or_none(w, kids, "本城未采集到儿童娱乐 POI"):
        w("")
        w("| 标记 | 名称 | 子类 | 载体 | 评分 | 地址 |")
        w("|---|---|---|---|---|---|")
    for p in kids[:60]:
        mk, _ = mark_poi(p)
        blob = (p.get("name") or "") + " " + (p.get("address") or "")
        sub = "其他儿童场所"
        for label, kws in KIDS_ENT:
            if has_ctx(blob, kws):
                sub = label
                break
        carrier = "场内" if is_mall(blob) else "独立"
        w("| %s | %s | %s | %s | %s | %s |" % (
            mk, cell(p.get("name")), sub, carrier,
            p.get("rating") or "—", cell(p.get("address"))))
    if len(kids) > 60:
        w("")
        w("（另 %d 家见 §11 原始数据）" % (len(kids) - 60))
    w("")

    # ── 5. 综合体与商场 ──
    malls = [p for p in district if carrier_of(p) in (
        "购物中心/综合体", "百货/商场", "奥特莱斯", "批发城")]
    w("## 5. 综合体与商场（%d 家）" % len(malls))
    w("")
    w("口径：060100 商场 / 060101 购物中心 / 060200 百货 等类型码，"
      "或名称含购物中心/百货/奥莱/批发。")
    w("")
    if w_or_none(w, malls, "本城未采集到购物中心/百货/奥莱/批发类 POI"):
        w("")
        w("| 标记 | 名称 | 载体类型 | 评分 | 场内儿童娱乐 | 关联美食 | 地址 |")
        w("|---|---|---|---|---|---|---|")
    for p in malls[:50]:
        mk, _ = mark_poi(p)
        dname = p.get("name") or ""
        nk = len(kids_linked.get(dname, []))
        nf = len(food_linked.get(dname, []))
        w("| %s | %s | %s | %s | %d | %d | %s |" % (
            mk, cell(p.get("name")), carrier_of(p),
            p.get("rating") or "—", nk, nf, cell(p.get("address"))))
    if len(malls) > 50:
        w("")
        w("（另 %d 家见 §11 原始数据）" % (len(malls) - 50))
    w("")

    # ── 6. 本地美食 ──
    w("## 6. 本地美食与特色美食（%d 家）" % len(food))
    w("")
    w("标记口径：✅A 评分≥4.6 且带本地/老字号语义；✅A- 评分≥4.6；"
      "✅B 评分 4.3–4.6；⚠️ 3.5–4.3 或无评分；❌ <3.5 或无地址。")
    w("")
    if w_or_none(w, food, "本城未采集到餐饮 POI"):
        w("")
        w("| 标记 | 店名 | 类型 | 评分 | 人均 | 地址 | 图片 |")
        w("|---|---|---|---|---|---|---|")
    for p in food[:80]:
        mk, _why = mark_poi(p)
        img = ("![图](https://store.is.autonavi.com/showpic/%s)"
               % p["photos"][0].split("/")[-1]) if p.get("photos") else ""
        w("| %s | %s | %s | %s | %s | %s | %s |" % (
            mk, cell(p.get("name")), (p.get("type") or "").replace("|", "/"),
            p.get("rating") or "—", p.get("cost") or "—",
            cell(p.get("address")), img))
    if len(food) > 80:
        w("")
        w("（另 %d 家见 §11 原始数据，评分排序后 80 名未列入）"
          % (len(food) - 80))
    w("")

    # ── 7. 苍蝇馆 ──
    small = [p for p in food if has_ctx(p.get("name") or "", SMALL_SHOP_KW)]
    w("## 7. 苍蝇馆 / 小店候选（%d 家）" % len(small))
    w("")
    w("**判定纪律**：不凭空判定「苍蝇馆」。仅当命中高德「苍蝇馆」关键词，"
      "或店名含 小馆/排挡/家常/私房/土菜/大排档 等小店语义时列为候选；"
      "「苍蝇馆」本意是环境朴素但味道好的小店，与评分无必然关系，"
      "因此评分区间放宽到 3.6–4.6。")
    w("")
    if w_or_none(w, small, "未命中苍蝇馆关键词或小店语义——需人工补充"):
        w("")
        w("| 店名 | 来源查询面 | 评分 | 人均 | 地址 | 备注 |")
        w("|---|---|---|---|---|---|")
    for p in small:
        name = p.get("name") or ""
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

    # ── 8. 特产 ──
    w("## 8. 知名特产（%d 家）" % len(product))
    w("")
    if w_or_none(w, product, "本城未采集到特产类 POI"):
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
        w("（另 %d 家见 §11）" % (len(product) - 60))
    w("")

    # ── 9. 美食 × 商圈关联 ──
    w("## 9. 美食 × 商圈 关联")
    w("")
    w("关联方式：① 名称互证（美食店名/地址含商圈核心词）；"
      "② 距离就近（≤600m 且同区县）。仅靠距离的关联标 ⚠️，"
      "因为景区边界、跨街区的误配都靠距离无法排除。")
    w("")
    if not linked:
        w("（本城商圈锚点与餐饮 POI 无互证/就近关联——可能是锚点过少"
          "或餐饮 POI 距离均超 600m，需人工补充）")
        w("")
    for dname, lst in list(linked.items())[:25]:
        w("### %s（%d 家）" % (cell(dname), len(lst)))
        w("")
        w("| 店名 | 关联方式 | 直线距离 | 评分 | 数据位置 |")
        w("|---|---|---|---|---|")
        for f, dist, mode in lst[:25]:
            nm = f.get("name") or ""
            where = ("§6" if any(f.get("name") == q.get("name")
                                 for q in food[:80]) else "§11")
            w("| %s | %s | %s | %s | %s |" % (
                cell(nm), mode,
                ("%dm" % round(dist)) if dist is not None else "—",
                f.get("rating") or "—", where))
        w("")

    # ── 10. 酒店 ──
    w("## 10. 酒店配套（%d 家）" % len(hotel))
    w("")
    if hotel:
        w("| 标记 | 名称 | 类型 | 评分 | 人均 | 地址 |")
        w("|---|---|---|---|---|---|")
        for p in hotel[:50]:
            mk, _ = mark_poi(p)
            w("| %s | %s | %s | %s | %s | %s |" % (
                mk, cell(p.get("name")),
                (p.get("type") or "").replace("|", "/"),
                p.get("rating") or "—", p.get("cost") or "—",
                cell(p.get("address"))))
        if len(hotel) > 50:
            w("")
            w("（另 %d 家见 §11 原始数据）" % (len(hotel) - 50))
    elif 2 not in waves:
        w("（本档案未采集酒店维度——wave 2 未跑，"
          "执行 `amap_collect.py --city %s --wave 2` 补齐）" % city)
    else:
        w("（wave 2 已采集住宿服务查询面，但本城返回 0 条酒店 POI——"
          "可能是该城酒店 POI 收录较少，需人工确认；"
          "原始查询面明细见 §11）")
    w("")

    # ── 11. 原始查询清单 ──
    w("## 11. 原始查询清单与原始数据")
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

    # ── 12. 校对待办 ──
    w("## 12. 校对待办")
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
    todo.append("§2 商圈画像中「动线主轴」由地址道路词频推导，"
                "「高峰时段 / 本地客成分 / 可跳过商业段」待人工校对。")
    todo.append("§9 关联中，仅靠距离就近的条目需逐条确认"
                "（防止景区/跨街区误配）。")
    if errs:
        todo.append("采集有告警：%s" % "；".join(errs[:3]))
    if 2 not in waves:
        todo.append("本档案缺 wave 2 维度（酒店/迷你动物园/百货奥莱），"
                    "需补采。")
    todo.append("本城 POI 覆盖 %d 个区县：%s——缺区县的需补充采集。"
                % (len(adname_cnt), "、".join(sorted(adname_cnt))))
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
    hier = {}
    if os.path.exists(HIER):
        hier = json.load(open(HIER, encoding="utf-8"))
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
        md = render_city(city, cache, pname, hier)
        outp = os.path.join(outdir, city + ".md")
        with open(outp, "w", encoding="utf-8") as f:
            f.write(md)
        made += 1
    print("生成 %d 个城市档案 → %s" % (made, DATA))


if __name__ == "__main__":
    main()
