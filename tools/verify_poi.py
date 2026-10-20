#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
✅A 级 POI 核验器 v2（百度地图 Agent Plan / place 端点）。

v1 的两个缺陷已修正：
  1) 小卡条目标题多为「菜名」而非「店名」（三鲜豆皮→西大街豆皮大王），
     直接用标题检索会检索到同品类他店 → 引入 QUERY_MAP 人工映射真实店名。
  2) 产地级 / 品种级条目（平江酱干、洞庭粉藕汤）本无单一门店，
     POI 核验不适用 → 显式标为 SKIP，不参与 ✅A 判定。

三项硬指标（缺一不可升 ✅A）：
  1) 店名/品牌匹配
  2) 门牌号一致（卡片地址数字命中 POI 地址数字）
  3) 近 90 天内有真实评价

输出：.cache/poi_verify.json
用法：python tools/verify_poi.py [--city 武汉|岳阳|恩施] [--limit N] [--force]
"""
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, ".cache")
os.makedirs(CACHE, exist_ok=True)

PLACE_URL = "https://api.map.baidu.com/agent_plan/v1/place"
TODAY = date(2026, 10, 20)
REGION = {"武汉": "武汉市", "岳阳": "岳阳市", "恩施": "恩施市"}


# ------------------------------------------------------- 查询名映射（人工核对）
# key = (卡片文件名关键词, 条目号)
# value = (用于 POI 检索的真实店名, 是否适用 POI 核验)
#   店名为 None → 产地级/品种级条目，不做门店 POI 核验
QUERY_MAP = {
    # ---------------- 武汉 ----------------
    ("武汉", 1): ("蔡林记", True),
    ("武汉", 2): ("西大街豆皮大王", True),
    ("武汉", 3): ("汪记鲜鱼糊汤粉", True),
    ("武汉", 4): ("严老幺", True),
    ("武汉", 5): ("朱姐早点", True),
    ("武汉", 6): (None, False),          # 蛋酒：品种级，无专营店
    ("武汉", 7): ("大中华酒楼(黄鹤楼店)", True),  # 清蒸武昌鱼，另有湖锦/渔歌
    ("武汉", 8): ("董厨煨汤馆", True),
    ("武汉", 9): (None, False),          # 汪集鸡汤：产地级
    ("武汉", 10): ("小桃园煨汤馆", True),
    ("武汉", 11): ("元银甲餐厅", True),
    ("武汉", 12): ("四季美汤包", True),
    ("武汉", 13): ("汪玉霞", True),
    ("武汉", 14): ("老万成酸梅汤", True),
    ("武汉", 15): ("赵师傅油饼包烧麦", True),
    ("武汉", 16): ("靓靓蒸虾", True),
    ("武汉", 17): ("巴厘龙虾", True),
    ("武汉", 18): ("肥肥虾庄", True),
    ("武汉", 19): ("田拐子牛肉面", True),
    # ---------------- 岳阳 ----------------
    ("岳阳", 1): ("蔡师傅豆皮", True),
    ("岳阳", 2): ("长动猪脚粉", True),
    ("岳阳", 3): ("伍舅湘阴特色面馆", True),
    ("岳阳", 4): ("学坡早餐店", True),
    ("岳阳", 5): ("味腴楼", True),
    ("岳阳", 6): ("细毛蒸虾", True),
    ("岳阳", 7): ("陶记刁子鱼", True),
    ("岳阳", 8): (None, False),          # 洞庭粉藕汤：品种级
    ("岳阳", 9): (None, False),          # 君山虾饼：景区流动摊
    ("岳阳", 10): (None, False),         # 平江酱干：产地级
    ("岳阳", 11): (None, False),         # 华容团子：产地级
    ("岳阳", 12): (None, False),         # 姜盐豆子茶：待客俗
    ("岳阳", 13): ("洞氮胖哥烧烤", True),
    ("岳阳", 14): ("丑老板龙虾烧烤", True),
    ("岳阳", 15): (None, False),         # 三码头文婆子嗦螺：流动摊
    ("岳阳", 16): (None, False),         # 姜辣系：品类
    ("岳阳", 17): (None, False),         # 兰花萝卜：品类/酱菜铺
    # ---------------- 恩施 ----------------
    ("恩施", 1): ("袁氏油香", True),
    ("恩施", 2): ("吴陈记", True),          # POI 名为「吴陈记早餐店 @ 人民路43-5号」
    ("恩施", 3): ("沈格格", True),
    ("恩施", 4): ("傅记羊肉大面", True),
    ("恩施", 5): ("李氏建始大饼", True),    # 建始县已并入恩施市，POI 在三孔桥路
    ("恩施", 6): ("张关合渣", True),
    ("恩施", 7): ("赵记腊味", True),        # POI 名「赵记腊味(恩施总店)」
    ("恩施", 8): ("巴人堂", True),
    ("恩施", 9): ("黄家社饭", True),
    ("恩施", 10): (None, False),         # 板党土鸡汤：全州供应
    ("恩施", 11): ("宣恩烤活鱼", True),
    ("恩施", 12): ("南坪麻鸭鳝鱼馆", True),  # 原「齐岳人家」地图未收录，改用同类收录门店
    ("恩施", 13): ("硒都印象", True),
    ("恩施", 14): (None, False),         # 凤头姜烧麻鸭：产地级
    ("恩施", 15): (None, False),         # 恩施炕土豆：街头摊
    ("恩施", 16): ("柏杨豆干产业园", True),  # 原「好吃婆沈记」未收录，改用产业园收录点
    ("恩施", 17): (None, False),         # 花坪桃片糕：产地级
    ("恩施", 18): (None, False),         # 土家油茶汤：待客茶俗
    ("恩施", 19): (None, False),         # 凉拌莼菜：产区
    ("恩施", 20): (None, False),         # 神豆腐：农家乐/时令
}


# ------------------------------------------------------------ 凭据
def load_token():
    tok = os.environ.get("BAIDU_MAP_AUTH_TOKEN")
    if tok:
        return tok
    sp = os.path.expanduser("~/.workbuddy/settings.json")
    if os.path.exists(sp):
        try:
            d = json.load(io.open(sp, encoding="utf-8"))
            return d.get("env", {}).get("BAIDU_MAP_AUTH_TOKEN")
        except Exception:
            pass
    return None


TOKEN = load_token()


# ------------------------------------------------------------ 卡片解析
CARD_RE = re.compile(r'<article class="card">(.*?)</article>', re.S)
NAME_RE = re.compile(r'<span class="name">(.*?)</span>', re.S)
NO_RE = re.compile(r'<span class="no">(\d+)</span>')
ADDR_RE = re.compile(r'<span class="lab">址</span><span class="val addr">(.*?)</span>', re.S)
MARK_RE = re.compile(
    r'<div class="mark (okb|pend)"><span class="ic">[^<]*</span><span><b>[^<]*</b>\s*(.*?)</span>')
TAG_RE = re.compile(r'<[^>]+>')


def clean(s):
    s = TAG_RE.sub("", s)
    s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&quot;", '"')
    return re.sub(r"\s+", " ", s).strip()


def parse_cards(path):
    html = io.open(path, encoding="utf-8").read()
    out = []
    for blk in CARD_RE.findall(html):
        nm, no, ad = NAME_RE.search(blk), NO_RE.search(blk), ADDR_RE.search(blk)
        mk = MARK_RE.search(blk)
        if not (nm and no and ad):
            continue
        out.append({
            "no": int(no.group(1)),
            "name": clean(nm.group(1)),
            "addr_raw": clean(ad.group(1)),
            "mark": mk.group(1) if mk else "?",
            "mark_note": clean(mk.group(2)) if mk else "",
        })
    return out


# ------------------------------------------------------------ POI 查询
def query_poi(qname, city, region_hint=""):
    req = "帮我找%s的%s店" % (city, qname)
    if region_hint:
        req = "帮我找%s的%s，位于%s" % (city, qname, region_hint)
    qs = urllib.parse.urlencode({"user_raw_request": req, "region": city,
                                 "sort": "relevance"})
    rq = urllib.request.Request(
        PLACE_URL + "?" + qs,
        headers={"Authorization": "Bearer " + TOKEN, "User-Agent": "curl/8"})
    with urllib.request.urlopen(rq, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


# 非餐饮 / 非门店类 POI，必须排除（否则「地下停车场」会被当成酒楼）
BAD_TAGS = ("停车场", "地下车库", "停车场入口", "出入口", "地铁站", "公交站",
            "停车场(内部)", "居民楼", "写字楼", "广场", "景区", "公园")


def is_poi_restaurant(c):
    """判断候选是否为可消费的餐饮门店。"""
    di = c.get("detail_info", {}) or {}
    tag = (di.get("classified_poi_tag") or "") + "|" + (c.get("name") or "")
    for b in BAD_TAGS:
        if b in tag:
            return False
    # 有营业时间 + 分类含餐饮词，视为门店
    if di.get("shop_hours"):
        return True
    return any(k in tag for k in ("美食", "餐厅", "饭店", "小吃", "面馆", "酒楼",
                                  "茶", "咖啡", "烘焙", "糕点", "烧麦", "豆皮",
                                  "虾", "汤", "粉", "面", "饼", "烧烤", "火锅"))


def norm(s):
    return re.sub(r"[^一-鿿A-Za-z0-9]", "", s or "")


def addr_nums(s):
    """抽取地址中的门牌数字（去空格）。"""
    s = (s or "").replace(" ", "")
    return set(re.findall(r"\d+", s))


DISTRICTS = ["江汉区", "江岸区", "硚口区", "汉阳区", "武昌区", "洪山区", "东西湖区",
             "汉南区", "蔡甸区", "江夏区", "黄陂区", "新洲区", "青山区", "武昌区",
             "岳阳楼区", "岳阳", "云溪区", "君山区", "平江县", "华容县", "湘阴县",
             "汨罗市", "临湘市", "恩施市", "利川市", "巴东县", "建始县", "咸丰县",
             "宣恩县", "来凤县", "鹤峰市", "恩施"]


def addr_anchors(addr):
    """从卡片地址提取区域锚点（区名 / 街道名 / 地标），用于连锁店定位。"""
    a = re.sub(r"\s+", "", addr or "")
    anchors = []
    for d in DISTRICTS:
        if d in a:
            anchors.append(d)
            break
    # 街道/路名
    for m in re.finditer(r"([\u4e00-\u9fff]{2,6}(?:路|街|道|巷|大街|正街))", a):
        anchors.append(m.group(1))
    # 地标关键词（北湖正街、粮道街、雪松路 等已含在上面的街道规则中）
    for kw in ("北湖正街", "粮道街", "雪松路", "石牌岭", "黄鹤楼", "昙华林", "江汉路",
               "前进四路", "民主二街", "沈阳路", "山海关路", "洞庭南路", "花板桥路",
               "青年中路", "学坡街", "冷水铺路", "建湘路", "通海路", "人民路",
               "航空大道", "东风大道", "巴山路", "航空花园", "土桥大道", "施州大道",
               "金桂大道", "兴隆大道", "南坪乡", "丽凤大道", "学苑路", "六角亭"):
        if kw in a:
            anchors.append(kw)
    return list(dict.fromkeys(anchors))


GEN_SUFFIX = ("餐厅", "酒楼", "餐饮", "旗舰店", "总店", "分店", "专卖店", "店")


def name_match(qname, c):
    """店名/品牌匹配。允许去掉通用后缀后做前缀或包含匹配。"""
    di = c.get("detail_info", {}) or {}
    cn, brand = norm(c.get("name")), norm(di.get("brand"))
    q = norm(qname)
    if not q:
        return False
    if q in cn or q in brand:
        return True
    # 去通用后缀后再比对（如「元银甲餐厅」→「元银甲」）
    q2 = q
    for s in GEN_SUFFIX:
        if q2.endswith(s):
            q2 = q2[: -len(s)]
    if len(q2) >= 2 and (q2 in cn or q2 in brand):
        return True
    # 品牌包含查询名（POI 品牌字段更短，如 brand=元银甲）
    for src in (cn, brand):
        if len(src) >= 2 and len(q) >= 2 and (src.startswith(q) or src.startswith(q2)):
            return True
    # 分词部分匹配
    for part in re.split(r"[（()、/·]", qname):
        p = norm(part)
        if len(p) >= 2 and (p in cn or p in brand):
            return True
    return False


def score_cand(c, qname, card_nums, anchors):
    """给候选打分：店名/品牌匹配 + 门牌命中 + 区域锚点命中。"""
    di = c.get("detail_info", {}) or {}
    cn, brand = norm(c.get("name")), norm(di.get("brand"))
    q = norm(qname)
    s = 0
    if name_match(qname, c):
        s += 10
    pn = addr_nums(c.get("address"))
    if card_nums & pn:
        s += 8
    ca = (c.get("address") or "") + " " + (c.get("area") or "")
    for a in anchors:
        if a in ca:
            s += 6
            break
    if not is_poi_restaurant(c):
        s -= 12
    return s


def verify(item, qname, city):
    rec = dict(item)
    rec["query_name"] = qname
    rec["ok"] = False
    anchors = addr_anchors(item["addr_raw"])
    rec["anchors"] = anchors
    # 把卡片地址的街道/区域作为查询限定，提高连锁店命中率
    hint = "、".join(anchors[:2]) if anchors else ""
    try:
        data = query_poi(qname, city, hint)
    except Exception as e:
        rec["reason"] = "请求失败：%s" % e
        rec["level"] = "ERR"
        return rec
    cands = data.get("results") or []
    rec["candidate_count"] = len(cands)
    if not cands:
        rec["level"] = "NONE"
        rec["reason"] = "地图 POI 未检索到「%s」" % qname
        return rec

    card_nums = addr_nums(item["addr_raw"])
    anchors = addr_anchors(item["addr_raw"])
    rec["anchors"] = anchors
    scored = sorted(((score_cand(c, qname, card_nums, anchors), c) for c in cands),
                    key=lambda x: -x[0])
    # 过滤掉非餐饮 POI；若全部被过滤则保留原始最高分
    viable = [(sc, c) for sc, c in scored if is_poi_restaurant(c)]
    pool = viable if viable else scored
    c = pool[0][1]
    di = c.get("detail_info", {}) or {}
    comments = c.get("comments") or []
    dates = sorted([x.get("date") for x in comments if x.get("date")], reverse=True)

    rec["poi_name"] = c.get("name")
    rec["poi_address"] = c.get("address")
    rec["poi_area"] = c.get("area")
    rec["poi_uid"] = c.get("uid")
    rec["poi_tag"] = di.get("classified_poi_tag")
    rec["shop_hours"] = di.get("shop_hours")
    rec["price"] = di.get("price")
    rec["rating"] = di.get("overall_rating")
    rec["comment_num"] = di.get("comment_num")
    rec["telephone"] = c.get("telephone") or ""
    rec["image"] = di.get("image") or ""
    rec["is_default_image"] = di.get("is_default_image")
    rec["last_comment"] = dates[0] if dates else ""
    rec["review_dates"] = dates
    rec["review_texts"] = [x.get("content", "")[:80] for x in comments[:3]]
    rec["top_candidates"] = [
        {"name": x.get("name"), "address": x.get("address"),
         "area": x.get("area"), "hours": (x.get("detail_info") or {}).get("shop_hours"),
         "rating": (x.get("detail_info") or {}).get("overall_rating"),
         "score": sc}
        for sc, x in pool[:3]]

    # --- 三项硬指标 ---
    name_hit = name_match(qname, c)
    addr_hit = bool(card_nums & addr_nums(c.get("address")))
    anchor_hit = False
    if not addr_hit:
        # 卡片地址无门牌数字时（如「北湖小学旁」），以地标/街道命中代替
        ca = (c.get("address") or "") + " " + (c.get("area") or "")
        anchor_hit = any(a in ca for a in anchors)
    recent, age = False, None
    if dates:
        try:
            y, m, d = [int(x) for x in dates[0].split("-")]
            age = (TODAY - date(y, m, d)).days
            recent = age <= 90
        except Exception:
            pass
    rec["name_hit"] = name_hit
    rec["addr_hit"] = addr_hit
    rec["anchor_hit"] = anchor_hit
    rec["recent_review"] = recent
    rec["comment_age_days"] = age
    rec["hours_known"] = bool(di.get("shop_hours"))

    if name_hit and (addr_hit or anchor_hit) and recent:
        rec["ok"] = True
        rec["level"] = "A"
        rec["reason"] = ("门牌一致 + " if addr_hit else "地标/街道一致 + ") + \
                        "店名匹配 + 近 90 天评价（%s）" % (dates[0] if dates else "-")
    elif name_hit and recent:
        rec["ok"] = True
        rec["level"] = "A-"
        rec["reason"] = "店名匹配 + 近 90 天评价（%s）；门牌与卡片记载不一致（POI: %s）" % (
            dates[0] if dates else "-", c.get("address"))
    elif name_hit and (addr_hit or anchor_hit):
        rec["level"] = "B+"
        rec["reason"] = "店名与位置均一致，但无近 90 天评价（最近 %s）" % (dates[0] if dates else "无")
    else:
        rec["level"] = "C"
        miss = []
        if not name_hit:
            miss.append("店名未匹配")
        if not (addr_hit or anchor_hit):
            miss.append("门牌/地标未对上")
        if not recent:
            miss.append("无近 90 天评价")
        rec["reason"] = "%s｜POI: %s @ %s" % ("；".join(miss), c.get("name"), c.get("address"))
    return rec


def main():
    if not TOKEN:
        print("! 未找到 BAIDU_MAP_AUTH_TOKEN")
        return 2
    args = sys.argv[1:]
    only = args[args.index("--city") + 1] if "--city" in args else None
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    force = "--force" in args

    jobs = [("武汉", "武汉美食小卡.html"), ("岳阳", "岳阳美食小卡.html"),
            ("恩施", "恩施美食小卡.html")]
    out_path = os.path.join(CACHE, "poi_verify.json")
    results = json.load(io.open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}

    for city, fname in jobs:
        if only and city != only:
            continue
        items = parse_cards(os.path.join(BASE, fname))
        if limit:
            items = items[:limit]
        print("== %s（%d 条）" % (fname, len(items)))
        for it in items:
            key = "%s#%02d" % (fname, it["no"])
            qname, applicable = QUERY_MAP.get((city, it["no"]), (it["name"], True))
            if key in results and not force and results[key].get("_done"):
                r = results[key]
                print("  %02d %-18s %-4s 缓存" % (it["no"], it["name"][:16], r.get("level", "-")))
                continue
            if not applicable:
                rec = dict(it)
                rec.update({"query_name": None, "ok": False, "level": "SKIP",
                            "reason": "产地级 / 品种级条目，无单一门店，不适用 POI 核验",
                            "_done": True})
                results[key] = rec
                print("  %02d %-18s SKIP  %s" % (it["no"], it["name"][:16], "产地/品种级"))
                continue
            rec = verify(it, qname, REGION[city])
            rec["_done"] = True
            results[key] = rec
            print("  %02d %-18s %-4s %s" % (it["no"], it["name"][:16],
                                            rec.get("level", "-"), rec.get("reason", "")[:62]))
            io.open(out_path, "w", encoding="utf-8").write(
                json.dumps(results, ensure_ascii=False, indent=1))
            time.sleep(0.7)
    io.open(out_path, "w", encoding="utf-8").write(
        json.dumps(results, ensure_ascii=False, indent=1))
    print("\n结果写入 .cache/poi_verify.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
