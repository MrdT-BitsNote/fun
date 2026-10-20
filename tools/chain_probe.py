#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
商圈判别探针：连锁品牌密度 + 到访热度 双信号

用途
----
判定一个锚点是否「已经是商圈 / 人流量较大的地区」，用于两种场景：

1. **反向确认**：用户给出一个街区名（如「东茅岭」），不确定它算不算商圈
   → 先跑本探针，再决定走商圈模式还是城市模式
2. **分段校验**：商圈内部分段（如「汴河街中段 vs 汴河街延伸段」），
   防止把冷清段当成有效消费段

方法来源
--------
用户提出的启发式：**肯德基、麦当劳、星巴克、小米、华为、瑞幸、蜜雪冰城
等品牌专卖店集中 ⇒ 该地区必然是商圈或人流量较大的地区。**

本脚本把它从「感觉」变成可复算的指标，并加上百度地图 POI 自带的
`arrival_heat`（到访热度）作为**独立第二信号**，用于交叉验证——
因为连锁密度单用会假阳性（见下方「适用边界」）。

输出
----
- CHAIN_SCORE  连锁命中数 / 加权命中数
- HEAT         锚点自身的到访热度（0–10 量级）
- VERDICT      三档判定，含触发依据

用法
----
    python tools/chain_probe.py --anchor "岳阳市岳阳楼区汴河街步行街" --city 岳阳市
    python tools/chain_probe.py --anchor "..." --city 岳阳市 --radius 800 --json
"""

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

PLACE_URL = "https://api.map.baidu.com/agent_plan/v1/place"

# ---------------------------------------------------------------- 凭据
CRED_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".cache", "baidu_token.txt")


def load_token():
    """从环境变量或 .cache 缓存读取 Agent Plan token。"""
    tok = os.environ.get("BAIDU_MAP_AUTH_TOKEN")
    if tok:
        return tok
    if os.path.exists(CRED_FILE):
        with open(CRED_FILE, encoding="utf-8") as f:
            tok = f.read().strip()
            if tok:
                return tok
    raise SystemExit(
        "未找到百度地图 Agent Plan token。\n"
        "  设置环境变量 BAIDU_MAP_AUTH_TOKEN，"
        "或写入 %s" % CRED_FILE)


# ---------------------------------------------------------------- 品牌清单
# 分档：每档代表不同的「人流承载量级」，用于加权计分。
#   餐饮  = 直接带来客流，且与本技能主题同源，权重最高
#   零售  = 逛街型消费，指示商业步行量
#   数码  = 3C 连锁，人流大但目的性强、停留短
#   便利  = 密度型业态，最能反映日常人流基线
TIERS = {
    "餐饮": [
        ("肯德基", 3), ("麦当劳", 3), ("星巴克", 2), ("瑞幸咖啡", 2),
        ("蜜雪冰城", 2), ("古茗", 1), ("茶百道", 1), ("沪上阿姨", 1),
        ("海底捞", 2), ("必胜客", 1),
    ],
    "零售": [
        ("优衣库", 2), ("名创优品", 2), ("屈臣氏", 1), ("无印良品", 1),
        ("耐克", 2), ("阿迪达斯", 2),
    ],
    "数码": [
        ("小米之家", 3), ("华为", 2), ("OPPO", 1), ("vivo", 1),
        ("苹果", 3),
    ],
    "便利": [
        ("7-ELEVEN", 2), ("罗森", 2), ("全家便利店", 1), ("美宜佳", 1),
        ("芙蓉兴盛", 1),
    ],
}

ALL_BRANDS = [(b, w, t) for t, lst in TIERS.items() for b, w in lst]

# 归一化时用的距离衰减（米）。命中半径内线性衰减到 0。
DECAY_M = 1500.0


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
        except Exception as e:                      # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError("POI 请求失败：%s" % last)


def norm(s):
    """去掉空白、全角转半角、括号内容，用于品牌名宽松比对。"""
    if not s:
        return ""
    s = s.translate(str.maketrans("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪ"
                                 "ＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
                                 "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐ"
                                 "ｑｒｓｔｕｖｗｘｙｚ（）　",
                                 "0123456789ABCDEFGHIJ"
                                 "KLMNOPQRSTUVWXYZ"
                                 "abcdefghijklmnopqrstuvwxyz() "))
    s = re.sub(r"[（(].*?[)）]", "", s)
    return re.sub(r"\s+", "", s).lower()


def haversine(lat1, lng1, lat2, lng2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def brand_of(poi_name, brand_field):
    """判断该 POI 属于哪个品牌清单项。"""
    cn, cb = norm(poi_name), norm(brand_field)
    for brand, _w, _tier in ALL_BRANDS:
        nb = norm(brand)
        # 品牌名或 branded 字段命中即算；避免「星巴克咖啡」漏判
        if nb and (nb in cn or nb in cb):
            return brand
    return None


GENERIC_STREET = ("步行街", "商业街", "美食街", "老街", "街区", "夜市",
                  "商业步行", "步行", "大街", "街")

# 只收**无歧义**的经营实体尾缀。
# 首版混入 市/广场/中心 三字导致语义冲突，回归测试抓到两处反向错误：
#   夜市(公共空间) 与 超市(店铺) 都以「市」结尾；
#   「汴河街商业广场」被误判为店铺——商业广场本身是合法商圈锚点。
# 现改为：这些字不作判据，宁可漏判（后续距离计算仍大致正确）也不误拒。
SHOP_TAIL = re.compile(
    r"(店|馆|铺|摊|坊|轩|居|堂|阁|超市|便利店|药房|银行|酒店|公寓|"
    r"书屋|大排档|茶饮|咖啡厅|餐厅|酒楼|小吃城)$")

# 县级行政区（含下辖县市）。用于跨区误配检测——同为「万达广场」，
# 岳阳楼区和平江县各有一座，品牌词命中不等于位置命中。
COUNTY_REGIONS = (
    "岳阳楼区", "君山区", "云溪区", "平江县", "湘阴县", "华容县",
    "汨罗市", "临湘市", "岳阳县", "湘阴", "华容", "汨罗", "临湘",
    "平江", "岳阳楼", "云溪", "君山",
)


def _regions_in(text):
    """取出文本中出现的县级行政区（去重、去包含项）。"""
    t = norm(text)
    found = []
    for r in COUNTY_REGIONS:
        if norm(r) in t:
            # 「湘阴县」与「湘阴」去重：保留更长的那个
            if not any(r in f or f in r for f in found):
                found = [f for f in found if f not in r] + [r]
    return found


def _strip_admin(s):
    """剥离行政区前缀，但**不得把地名本体一起吃掉**。

    实测事故（v0.5.0）：首版用 `[\\u4e00-\\u9fff]{2,6}?(?:省|市|区|…)` 左到右
    贪婪匹配，结果把地名本体当成行政前缀剥掉了：
      「岳阳楼景区」              → 「岳阳楼」+「区」被剥 → 残留「景」
      「中共…洞庭街道…委员会」   → 剥到只剩「委员会」
      「汕头小公园海滨旅游区」   → 「汕头小」被当成「市」剥掉
    一旦剥空，绿线/景区判断全部失效（错误返回 ok），等于把上一处修复打了回去。

    修正：逐段从**前缀**匹配 + 长度护栏。
      1) 只剥开头连续的行政层级（省→市/州→区县→街道镇乡），不碰中间；
      2) 剥完必须留得下 ≥2 个汉字（地名本体），否则停止；
      3) 剥空则回退原文——宁可不剥，也不误伤。
    """
    if not s:
        return s
    t = s.strip()
    for _ in range(5):                      # 最多 5 层行政前缀
        m = re.match(
            r"^(?:中华人民共和国)?\s*"
            r"(?:[\u4e00-\u9fff]{2,4}?(?:省|特别行政区)\s*)?"
            r"(?:[\u4e00-\u9fff]{2,6}?(?:市|自治州|地区|盟)\s*)?"
            r"(?:[\u4e00-\u9fff]{2,6}?(?:区|县|旗)\s*)?"
            r"(?:[\u4e00-\u9fff]{2,6}?(?:街道|镇|乡|苏木|民族乡)\s*)?",
            t)
        head = m.group(0) if m else ""
        rest = t[len(head):]
        if not head or rest == t:
            break
        # 护栏：剥完必须留得下地名本体
        if len(re.findall(r"[\u4e00-\u9fff]", rest)) < 2:
            break
        t = rest
    return t.strip() or s



def anchor_quality(anchor, poi):
    """校验锚点解析是否命中正确的 POI。

    实测缺陷（三代）：
    1. 请求「东茅岭街道步行街」→ 命中「田良君(步行街店)」
       —— 一家把「步行街」写在店名里的土特产店，坐标在得胜南路。
    2. 首版修复用「中文整串当一个 token」，因该串含「街道」被过滤成空，
       反而 fallback 放行，等于没修。
    3. 做全城商圈普查时暴露：请求「岳阳市岳阳楼区万达广场」→ 命中
       「平江万达广场」（平江县，岳阳下辖另一个人口大县）。
       —— 同品牌名 POI 在下辖县市也存在，品牌词命中不等于位置命中。

    修正后的判定：
    a) 剥掉「省/市/区/县/街道/镇/乡/村」等行政前缀，得到残留词；
    b) 残留词含通用街型词（步行街/商业街/老街…）时，命中 POI 不得是
       一家店——否则判为解析错误；
    c) 残留词为专名（汴河街、万达广场）时，要求它出现在 POI 名中；
    d) 【v0.4.0 新增】跨行政区校验：命中 POI 的地址若落在另一个
       明确的县级行政区（且请求词没提到它），判为跨区误配。

    返回 (是否可信, 说明)。
    """
    name = poi.get("name") or ""
    addr = poi.get("address") or ""
    # (a) 剥行政前缀：岳阳市岳阳楼区东茅岭街道步行街 -> 步行街
    residue = re.sub(
        r"[\u4e00-\u9fff]{2,4}?(?:省|市|区|县|街道|镇|乡|村|自治州)", "", anchor)
    residue = re.sub(r"[^\w\u4e00-\u9fff]", "", residue)

    # (b) 通用街型词 → 不得命中一家店
    if any(g in residue for g in GENERIC_STREET):
        # 实测坑：若先剥掉括注，「田良君(步行街店)」会变成「田良君」，
        # 尾缀「店」丢失 → 漏判。括注本身就是门店类型标记，必须一起看。
        head = re.split(r"[（(]", name)[0]
        paren = re.findall(r"[（(]([^)）]*)[)）]", name)
        parts = [head] + paren
        hit_shop = any(SHOP_TAIL.search(p) for p in parts if p)
        if hit_shop:
            return False, ("锚点解析到店铺「%s」而非街本体；"
                           "其坐标在店铺处，不等于街区中心" % name)


    # (c) 专名 → 须词面命中
    if residue and not any(g in residue for g in GENERIC_STREET):
        if norm(residue) not in norm(name):
            # 退一步：允许 POI 名是残留词的扩展（如「汴河街」→「汴河街步行街」）
            if norm(name) not in norm(residue):
                return False, ("锚点专名「%s」未出现在命中的 POI 名「%s」中，"
                               "疑似匹配到同名他处" % (residue, name))

    # (d) 跨行政区校验：县级行政区出现冲突即误配
    mine = _regions_in(anchor)
    theirs = _regions_in(addr)
    clash = [r for r in theirs if r not in mine]
    if clash:
        return False, ("锚点在「%s」，但命中的 POI 地址落在「%s」——"
                       "跨行政区误配（同品牌名在下辖县市也存在）"
                       % ("/".join(mine) or "未指定", "/".join(clash)))
    return True, "锚点解析一致"




# ---------------------------------------------------------------- 探针
def carrier_check(anchor, poi, chain_inner):
    """判定锚点本身是否适合作为「商圈」的讨论对象。

    实测缺陷（v0.4.0）：请求「湖南理工学院周边」→ 锚点命中
    **湖南理工大学（校园本体）**，坐标在湘北大道。校区本身
    不是商圈，真实载体是校门外的奇家岭岳磁街学生街。
    同理「南湖广场」锚在湖边绿地，连锁 0 家但热度 15.1——
    热度属于公园，不是商圈。

    这里不判定「是不是商圈」（那是连锁密度的事），只判定
    **锚点是否可能被误解为商圈本体**，据此提示改锚点。

    返回 (状态, 说明)：
      ok        锚点即商圈载体，可直接讨论
      offsite   锚点是学校/公园/景区等非商业场所，应改锚点
    """
    name = (poi.get("name") or "")
    addr = (poi.get("address") or "")

    # ── v0.5.0 重大修正：分类只认 POI 自己的名字，不认地址 ──
    # 实测事故（污染了岳阳基线）：首版把 name+addr 拼成 blob 后做子串匹配，
    # 而非商业词表里有单字「湖」，于是
    #   「湖南省岳阳市…洞庭北路56号」→ 命中「湖」→ 判水系绿地
    #   「广东省汕头市龙湖区万象城」 → 命中「湖」→ 判水系绿地
    #   「南湖星都汇」               → 命中「湖」→ 判水系绿地
    # 结果汕头万象城这种明确商业综合体被误杀，汴河街/南湖星都汇的商圈
    # 结论失真。教训：**行政区名里的字不能当语义词**（湖南省、龙湖区、
    # 北湖区、南湖、开封兰考…全都含「湖」）。
    #
    # 修正三步：
    #   a) 地址先剥掉省/市/区/县/街道/镇/乡/村等行政成分再判断；
    #   b) 绿地/水系类词只在 POI 名上匹配，且要求成词（不是单字）；
    #   c) 商业修饰词的判定只看 POI 名，且要求在同一名称片段内。
    name_c = _strip_admin(name)
    addr_c = _strip_admin(addr)
    blob = name_c + " " + addr_c

    # 机构类：这类名称即主体，地址不参与
    org_kw = [
        ("大学", "校园"), ("学院", "校园"), ("职业", "校园"), ("中学", "校园"),
        ("小学", "校园"), ("校区", "校园"),
        ("博物馆", "公共场馆"), ("体育馆", "公共场馆"), ("文化馆", "公共场馆"),
        ("政务", "行政区"), ("办事处", "行政区"), ("居委会", "行政区"),
        ("社区服务", "行政区"), ("退役军人服务", "行政区"), ("派出所", "行政区"),
        ("人民医院", "公共场馆"), ("中医院", "公共场馆"), ("卫生院", "公共场馆"),
        # 党务/行政机构的组织形态词（实测「…社区委员会」被剥到只剩
        #「委员会」而漏判，补齐后缀形态）
        ("委员会", "行政区"), ("管理委员会", "行政区"), ("工作委员会", "行政区"),
        ("党工委", "行政区"), ("管委会", "行政区"), ("筹备处", "行政区"),
        ("人民政府", "行政区"), ("党群服务中心", "行政区"),
    ]
    # 景区类：需成词，且「风景区/景区/名胜」才算；「XX湖」不算景区
    scenic_kw = [("风景区", "景区"), ("景区", "景区"), ("名胜", "景区"),
                 ("古镇", "景区"), ("寺", "宗教场所"), ("庙", "宗教场所")]
    # 绿地类：必须成词。单字「湖」「江」「山」一律不作为依据。
    green_kw = [("湿地公园", "湿地"), ("森林公园", "市政绿地"), ("植物园", "市政绿地"),
                ("市政广场", "市政绿地"), ("体育公园", "市政绿地"),
                ("中心广场", "市政绿地"), ("文化广场", "市政绿地"),
                ("文化公园", "市政绿地"), ("主题公园", "市政绿地"),
                ("纪念公园", "市政绿地"), ("儿童公园", "市政绿地"),
                ("广场", "市政绿地"), ("公园", "市政绿地"),
                ("绿地", "市政绿地"), ("街心花园", "市政绿地")]
    # 居民区类
    resi_kw = [("住宅区", "居民区"), ("小区", "居民区"), ("家属院", "居民区"),
               ("社区", "居民区"), ("新村", "居民区")]

    # 商业语境修饰词：只作用于 POI 名，且必须在名称的同一片段内出现。
    # v0.5.0 修正：把「广场」「中心」从 BIZ 移除。
    # 实测事故：「人民广场」「中心广场」是市政广场，不是商业载体；BIZ 里
    # 有「广场」时会被直接放行，导致居民区/广场型锚点判成 ok。
    # 正确做法：广场类一律先按市政绿地判，靠 **强商业词** 豁免——
    # 「商业广场」「购物广场」「万达广场」「印象城」这类才算。
    BIZ = ("商业", "购物", "百货", "商厦", "综合体", "购物中心",
           "步行街", "美食街", "商业街", "夜市", "不夜城", "天地",
           "市集", "集市", "港", "汇", "坊", "城", "街", "巷", "苑")
    # 强商业词：命中即无条件豁免（本身就是商业项目名）
    BIZ_STRONG = ("商业", "购物", "百货", "商厦", "综合体", "购物中心",
                  "步行街", "美食街", "商业街", "步行", "夜市", "不夜城")

    def _biz_ctx(n):
        """POI 名中是否带商业语境修饰（分片段判定，避免跨词误判）。"""
        for seg in re.split(r"[（）()·\s\-—－|｜/、,，]+", n):
            if not seg:
                continue
            if any(b in seg for b in BIZ_STRONG):
                return seg
        return None

    biz_seg = _biz_ctx(name_c)

    # v0.5.0 新增：锚点命中一家**具体店铺**时不可当商圈载体。
    # 实测：锚点检索可能返回「星巴克(岳阳店)」这类门店——坐标是店门，
    # 不是街区中心，后续所有距离计算都会以门店为原点。
    if SHOP_TAIL.search(name_c):
        return "offsite", ("锚点命中的是一家店铺「%s」，坐标在店门而非街区中心；"
                           "请改用街区名（如 XX 步行街 / XX 商业街）作锚点"
                           % name[:16])

    for kw, kind in org_kw + scenic_kw + green_kw + resi_kw:
        if kw not in name_c:          # ← 只在 POI 名上匹配
            continue
        if biz_seg and kw not in biz_seg:
            # 商业词出现在别的片段（如「南湖」+「商业街」），不算商业载体误判
            pass
        else:
            if biz_seg:
                return "ok", "锚点名称含商业语境「%s」，视为商业载体" % biz_seg
            if chain_inner >= 4:
                return "ok", ("锚点为%s，但核心 300m 内连锁 %d 家，"
                              "载体可能已与商业街融合，可继续讨论"
                              % (kind, chain_inner))
            return "offsite", ("锚点命中「%s」——%s本体，非商圈载体；"
                               "连锁 %d 家未达商圈线，应改锚点为"
                               "周边的步行街/商业街/美食街"
                               % (name[:14], kind, chain_inner))
    # 地址里出现绿地词但名称是商业实体（如「万象城（湖边店）」）→ 不判 offsite
    _ = blob
    # 兜底：锚点命中医院/诊所/银行等单一机构，坐标无商圈意义
    ORG = ("医院", "门诊", "诊所", "银行", "支行", "邮政", "派出所",
           "办事处", "居委会", "管委会", "幼儿园", "敬老院")
    for kw in ORG:
        if kw in blob and chain_inner < 4:
            return "offsite", ("锚点命中「%s」——单一机构网点，非商圈载体；"
                               "连锁 %d 家未达商圈线，应改锚点"
                               % (name[:14], chain_inner))
    return "ok", "锚点即商圈载体"


def probe(anchor, city, radius=800, quiet=False):
    # 1) 锚点自身：坐标 + 到访热度
    d = query_place("帮我找" + anchor, city)
    res = d.get("results") or []
    if not res:
        raise SystemExit("锚点未找到：%s（请先做地名消歧）" % anchor)
    a = res[0]
    aloc = a.get("location") or {}
    alat, alng = aloc.get("lat"), aloc.get("lng")
    adi = a.get("detail_info") or {}
    heat = adi.get("arrival_heat")

    # 1.5 锚点可信度校验（防止解析到同名店铺）
    a_ok, a_note = anchor_quality(anchor, a)

    hits = {}                       # brand -> 最近的那家
    for brand, weight, tier in ALL_BRANDS:
        d2 = query_place("帮我找%s的%s店" % (city, brand), city)
        for c in (d2.get("results") or []):
            loc = c.get("location") or {}
            if not loc.get("lat"):
                continue
            dist = haversine(alat, alng, loc["lat"], loc["lng"])
            if dist > radius:
                continue
            di = c.get("detail_info") or {}
            b = brand_of(c.get("name"), di.get("brand"))
            if b is None:
                continue
            prev = hits.get(b)
            if prev is None or dist < prev["dist"]:
                hits[b] = {
                    "brand": b, "tier": tier, "weight": weight,
                    "poi": c.get("name"), "address": c.get("address"),
                    "dist": round(dist),
                    "rating": di.get("overall_rating"),
                    "comments": di.get("comment_num"),
                    "hours": di.get("shop_hours"),
                }

    weighted = sum(v["weight"] for v in hits.values())
    raw = len(hits)

    # 2) 密度归一化：半径越大，同样命中数越稀释。
    #    实测教训：汴河街全长仅 300 m，用 800 m 半径会把 3 条街外的
    #    麦当劳/海底捞算进来（命中 8 家），改用 300 m 后只剩 5 家——
    #    后者才反映街本体。因此判定优先看「有效半径」下的密度。
    inner = [v for v in hits.values() if v["dist"] <= min(300, radius)]
    inner_w = sum(v["weight"] for v in inner)

    # 3) 判定：以「核心 300 m 内命中」为主判据
    if len(inner) >= 4 or inner_w >= 7:
        verdict = "商圈/高人流"
        why = "核心 300 m 内连锁 %d 家、加权 %d 分" % (len(inner), inner_w)
    elif len(inner) >= 2 or inner_w >= 3:
        verdict = "准商圈/次级人流点"
        why = "核心 300 m 内连锁 %d 家、加权 %d 分（未达商圈线）" % (len(inner), inner_w)
    else:
        verdict = "非商圈/居民或低人流"
        why = "核心 300 m 内连锁 %d 家、加权 %d 分" % (len(inner), inner_w)

    # 4) 第二信号交叉：到访热度
    heat_note = "—"
    if isinstance(heat, (int, float)):
        if heat >= 5:
            heat_note = "%.2f（强人流公共空间）" % heat
        elif heat >= 1:
            heat_note = "%.2f（有稳定到访）" % heat
        else:
            heat_note = "%.2f（低到访）" % heat

        if not a_ok:
            # 锚点本身不可信时，热度读数属于该店铺而非该街区，必须弃用
            heat_note += "　⚠锚点不可信，本热度读数不采信"
            verdict += "｜⚠锚点解析疑似错误，需重新定位后再判定"
        elif len(inner) >= 4 and heat < 0.5:
            # 实测修正：东茅岭是真正的商圈（15 家连锁，含天虹/步步高/百盛），
            # 但街区 POI 本身热度仅 0.05——因为「街道」POI 是行政区，
            # 不是承载人流的实体点。原判「疑似封闭园区」是错的。
            # 真正的假阳性是「单一商场内店铺集中」：连锁全在同一个 mall 里。
            malls = set()
            for v in inner:
                addr = v["address"] or ""
                for kw in ("商场", "购物中心", "商业广场", "百货", "广场",
                           "购物", "生活广场", "新天地"):
                    if kw in addr:
                        malls.add(kw)
            verdict += "｜⚠行政区型锚点热度天然偏低，不作为否定依据"
            heat_note += "（行政区 POI，非人流承载点，属正常）"
        elif len(inner) <= 2 and heat >= 5:
            verdict += "｜⚠连锁少但到访热度高：可能是景区/公园/交通枢纽，非零售型商圈"
    else:
        if not a_ok:
            verdict += "｜⚠锚点解析疑似错误，且无到访热度可交叉，需重新定位"
        else:
            verdict += "｜⚠锚点无到访热度数据，本次仅凭连锁密度单信号判定"

    if not a_ok:
        why += "（且锚点解析存疑，结果不可用）"

    out = {
        "anchor_req": anchor,
        "anchor": a.get("name"),
        "anchor_addr": a.get("address"),
        "anchor_trusted": a_ok,
        "anchor_note": a_note,
        "anchor_lat": alat,
        "anchor_lng": alng,
        "radius_m": radius,
        "chain_raw": raw,
        "chain_weighted": weighted,
        "chain_inner_raw": len(inner),
        "chain_inner_weighted": inner_w,
        "arrival_heat": heat,
        "heat_note": heat_note,
        "verdict": verdict,
        "why": why,
        "hits": sorted(hits.values(), key=lambda v: v["dist"]),
        "tier_count": {t: sum(1 for v in inner if v["tier"] == t)
                       for t in TIERS},
    }

    if not quiet:
        print("=" * 66)
        print("请求锚点　%s" % anchor)
        print("命中 POI　%s（%s）" % (out["anchor"], out["anchor_addr"]))
        print("锚点可信　%s —— %s" % ("是" if a_ok else "否", a_note))
        print("坐标　　　%.5f, %.5f　检索半径 %d m" % (alat, alng, radius))
        print("-" * 66)
        print("全半径命中　%d 家　加权 %d 分" % (raw, weighted))
        print("核心 300m　%d 家　加权 %d 分　%s"
              % (len(inner), inner_w,
                 "　".join("%s%d" % (k, v) for k, v in out["tier_count"].items())))
        print("到访热度　%s" % heat_note)
        print("-" * 66)
        print("命中明细（按距离，★ = 街本体 300 m 内）")
        for v in sorted(hits.values(), key=lambda x: x["dist"]):
            star = "★" if v["dist"] <= 300 else " "
            print("  %s %5d m  [%s] %-14s %s"
                  % (star, v["dist"], v["tier"], v["brand"], v["poi"]))
        if not out["hits"]:
            print("  （半径内无清单品牌门店）")
        print("-" * 66)
        print("判定　　　%s" % verdict)
        print("依据　　　%s" % why)
        print("=" * 66)
    return out



def main():
    ap = argparse.ArgumentParser(description="商圈判别探针")
    ap.add_argument("--anchor", required=True, help="锚点名称，含城市与区")
    ap.add_argument("--city", required=True, help="城市名，用于 region 限定")
    ap.add_argument("--radius", type=int, default=800, help="检索半径（米）")
    ap.add_argument("--json", action="store_true", help="仅输出 JSON")
    ap.add_argument("--out", help="同时写入 JSON 文件")
    args = ap.parse_args()

    r = probe(args.anchor, args.city, args.radius, quiet=args.json)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
