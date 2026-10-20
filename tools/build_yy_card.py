#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成「岳阳商圈美食一体卡」：商圈索引 + 各圈并列 + 传统小吃档。

数据来源（全部落盘、可复核）：
  .cache/district_scan.json  连锁密度 + 到访热度 + 载体校验
  .cache/food_drill.json     餐饮 POI 下钻 + 三信号综合判定
  .cache/snack_verify.json   小吃档六级核验
"""

import html
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# 商圈档案：把「三信号数字」翻译成「人话」，并给出一句话定位。
# 这些是编辑判断，不是检索结果——必须与工具输出的数字一致。
PROFILE = {
    "步行街商圈": dict(
        anchor="岳阳步行街（东茅岭路103号）",
        tier="A", tier_name="主力商圈", shape="可步行街区型",
        kind="老城核心商业步行街",
        peak="全天营业，18:00–22:00 最挤；奶茶快餐从 10:00 起就有",
        price="街面人均 20–60 元；天虹百货内 60–120 元",
        axis="从东茅岭路入口进，沿主街直走到巴陵西路，单行不折返",
        skip="巴陵西路侧的天虹百货、友阿国际两段是纯商场，没有街面餐，可直接跳过",
        crowd="本地居民为主，节假日游客显著增加；夜晚是岳阳年轻人聚集地"),
    "花板桥商圈": dict(
        anchor="步步高广场（岳阳店）",
        tier="A", tier_name="主力商圈", shape="单一商场型",
        kind="购物中心型商圈（不开街面店）",
        peak="11:00–14:00、17:30–21:00 两个饭点；周末全天",
        price="人均 25–80 元，7 楼海底捞偏高",
        axis="**这不是一条可以逛的街**——按楼层走：1–2 楼快餐奶茶 → 4–5 楼正餐 → 7 楼火锅",
        skip="4 楼的杂货与童玩层没有餐点，可以跳",
        crowd="周边居民与学院路学生为主，家庭客与闺蜜客占多数"),
    "巴陵广场商圈": dict(
        anchor="巴陵广场（洞庭湖畔）",
        tier="A", tier_name="主力商圈", shape="街区型 + 广场",
        kind="城市地标型广场商圈",
        peak="傍晚 18:00–22:00 观日落＋夜市同时达到峰值",
        price="广场周边人均 30–70 元；巴陵广场南侧小吃街 15–30 元",
        axis="汴河街南口 → 巴陵广场雕塑 → 滨湖步道 → 广场南侧夜市，单向环线",
        skip="广场东侧的商业外街无餐点，看完雕塑可直奔南侧",
        crowd="本地人休闲散步为主，游客占比随旅游旺季波动"),
    "岳阳楼商圈": dict(
        anchor="汴河街（洞庭北路56号）",
        tier="A", tier_name="主力商圈", shape="可步行街区型",
        kind="仿古文旅街 + 夜市",
        peak="日间商铺 09:00–22:00；**夜市 18:00 亮灯开市至 23:00**，早餐店 09:00 前不开",
        price="小吃人均 15–35 元；夜市人均 30 元可吃饱",
        axis="**南门进（靠岳阳楼）→ 主街向北 → 街尾洞庭湖观景台**，全长仅约 300 m，20 分钟可走完",
        skip="街中段的工艺品、文创店铺无餐点，可直接穿过去",
        crowd="本地人与游客混合；本地客认「南门口顶糕」这类摊位，游客买文创"),
    "天伦城商圈": dict(
        anchor="天伦城（五里牌路）",
        tier="A", tier_name="主力商圈", shape="可步行街区型",
        kind="社区型街区商圈",
        peak="早餐 06:30–09:00 最强；晚市 18:00–21:00 次之",
        price="人均 15–45 元，社区价格带",
        axis="建湘路入口 → 天伦城步行街直走，圈状动线",
        skip="东北角外围临街铺面零散，可不绕",
        crowd="附近居民日常刚需为主，是岳阳最像「家门口」的商圈"),
    "理工商圈": dict(
        anchor="奇家岭 · 岳磁街（希望门）",
        tier="A", tier_name="主力商圈", shape="学生街型",
        kind="大学城学生街",
        peak="11:00–13:00、17:00–22:00；**宵夜到凌晨 1–3 点仍热闹**",
        price="人均 6–30 元，学生价格带",
        axis="湖南理工大学希望门 → 岳磁街 → 奇家岭街 → 理工美食城宵夜段",
        skip="岳磁街上段的奶茶与手机维修段无正餐，快速穿过",
        crowd="在校学生为主（师生 + 周边居民），价格敏感、翻台快"),
    "南湖星都汇商圈": dict(
        anchor="南湖星都汇（南湖大道727号）",
        tier="B", tier_name="美食型商圈", shape="街区型",
        kind="新住宅区配套商圈",
        peak="17:00–22:00 为主；卤味热卤类下午就开始出摊",
        price="人均 20–50 元",
        axis="南湖大道沿线单向，串店不多",
        skip="南湖大道北段以汽车服务与房产中介为主，无餐可吃",
        crowd="南湖新区新入住居民为主，典型社区消费"),
    "东风广场商圈": dict(
        anchor="东风广场（青年西路）",
        tier="B", tier_name="美食型商圈", shape="街区型",
        kind="老城社区型美食聚集",
        peak="早餐炒码米粉 06:30–09:00；晚市 17:30–21:00",
        price="人均 10–35 元，本地价格带",
        axis="以广场为中心向四周发散，无强动线，逐点吃更实际",
        skip="—",
        crowd="周边老居民为主，**连锁 0 家但餐饮密度 15 家**——典型的本地人日常食堂区"),
    "八字门商圈": dict(
        anchor="金悦洋商业公园（八字门）",
        tier="B", tier_name="美食型商圈", shape="单一商场型",
        kind="社区商业公园型",
        peak="17:00–22:00；夜宵类到 23:00 后",
        price="人均 20–55 元",
        axis="商业公园内围合动线，从北门进顺时针一圈",
        skip="外围临街铺面零散，可不绕",
        crowd="八字门、白石岭一带居民为主"),
    "芒果时代商圈": dict(
        anchor="芒果时代广场（科技路18号）",
        tier="B", tier_name="美食型商圈", shape="单一商场型",
        kind="新型商业综合体",
        peak="11:00–14:00、17:30–21:00",
        price="人均 25–70 元",
        axis="商场内动线，按楼层走",
        skip="轻食与茶饮层单价高且品类重复，可跳",
        crowd="年轻客与周边白领，偏品质消费"),
    "得胜路美食街": dict(
        anchor="得胜南路美食街（南湖新区）",
        tier="B", tier_name="美食型商圈", shape="可步行街区型",
        kind="本地小吃型美食街",
        peak="早餐 06:30–10:00 最强；夜宵 20:00 后转烧烤",
        price="人均 8–30 元，最便宜的一档",
        axis="东方红小学斜坡下 → 得胜南路主段 → 炮台山方向",
        skip="—（整段都有餐，密度高）",
        crowd="**纯本地人**。连锁只有 1 家，但 300 m 内餐饮 10 家——连锁密度探针会误判这里，餐饮密度才看得出真实人气"),
    "岳阳楼景区": dict(
        anchor="岳阳楼景区",
        tier="—", tier_name="非商圈（景区型人流）", shape="景区",
        kind="景区，非商圈",
        peak="旅游旺季白天",
        price="景区内人均偏高",
        axis="景区内动线",
        skip="—",
        crowd="游客为主"),
    "岳阳商业城商圈": dict(
        anchor="岳阳商业城（站前路213号）",
        tier="C", tier_name="街区型点", shape="批发市场型",
        kind="批发市场型",
        peak="上午",
        price="平价",
        axis="—", skip="—", crowd="批发采购为主"),
    "南湖广场商圈": dict(
        anchor="南湖广场",
        tier="C", tier_name="街区型点", shape="市政广场",
        kind="市政休闲广场（餐饮在周边街段）",
        peak="傍晚广场舞与散步",
        price="广场本身无餐",
        axis="—",
        skip="广场本体无餐点，餐在南湖大道沿线",
        crowd="居民休闲散步"),
}

# 小吃档：把核验结果整理成可读条目
SNACK_NOTE = {
    "顶糕（千年顶糕）": ("汴河街南门入口一带流动担子摊", "大米粉+糯米粉+红糖装木格蒸两三分钟，木杵一顶落碗。松软带糯，桂花红糖香。"),
    "巴陵汤包（小笼汤包）": ("洞庭北路与翰林街交叉口西北 80 米", "皮薄肉嫩，先开仓吸汤再蘸酱。洞庭湖鲜汤底。"),
    "三大炮": ("汴河街 83 号商铺", "糯米团滚红糖，岳阳街头传统甜食，冲击力强。"),
    "姜糖": ("汴河街沿街摊", "手工反复拉扯一米多糖块，姜味辛辣、糖味甘甜。"),
    "糖油粑粑": ("汴河街摊位", "外酥里糯约 3 元/个，与臭豆腐是湖南小吃标准吃法。"),
    "臭豆腐（汴河街版）": ("汴河街摊位", "岳阳版辣味更重，酱汁灌进豆腐配榨菜香菜。"),
    "仙豆糕": ("汴河街中间偏天井处", "手工现做小甜点，芝士口味需提前半小时预约，人均 5 元。"),
    "传统擂茶": ("汴河街沿街", "岳阳本地传统茶饮，擂打现制。"),
    "罗记卤肉卷": ("希望门对面岳磁街「翠竹园」门口", "14 年老字号，现做现卖，人均 8 元。"),
    "肉蛋堡": ("岳磁街入口处", "摆摊六年，东北口音老板，外皮裹辣椒面，人均 4 元。"),
    "无名卤菜摊": ("岳磁街入口处", "摆摊十年，无招牌认人，人均 6 元。"),
    "咕咕拌粉": ("希望门对面巷子", "杂酱土豆泥拌粉，人均 11 元。"),
    "胖哥炸炸炸": ("学坡街 111 号一带", "只做炸炸的流动摊，炸鸡腿复炸外焦里嫩，晚上出摊。"),
}


def map_svg(rows, scan_by):
    """按真实经纬度等比投影绘制商圈分布示意图。"""
    pts = []
    for _o, _n, label, _d, p in rows:
        sc = scan_by.get(label, {})
        if sc.get("lat"):
            pts.append((label, sc["lat"], sc["lng"], p["tier"], p))

    if not pts:
        return ""

    lats = [x[1] for x in pts]
    lngs = [x[2] for x in pts]
    pad = 0.008
    la0, la1 = min(lats) - pad, max(lats) + pad
    ln0, ln1 = min(lngs) - pad, max(lngs) + pad
    # 岳阳在北纬 29.3x，经度 113.0x；用 cos(lat) 修正经度方向的物理尺度
    import math
    kx = math.cos(math.radians(sum(lats) / len(lats)))
    VW, VH = 900.0, 470.0
    span_x = (ln1 - ln0) * kx
    span_y = (la1 - la0)
    scale = min(VW / span_x, VH / span_y)
    off_x = (VW - span_x * scale) / 2
    off_y = (VH - span_y * scale) / 2

    def px(lng, lat):
        x = off_x + (lng - ln0) * kx * scale
        y = off_y + (la1 - lat) * scale
        return x, y

    color = {"A": "#1f4d40", "B": "#2a5a7a", "C": "#8a6410", "—": "#8d867a"}
    r_of = {"A": 13, "B": 10, "C": 8, "—": 7}
    short = {
        "步行街商圈": "步行街", "花板桥商圈": "花板桥", "巴陵广场商圈": "巴陵广场",
        "岳阳楼商圈": "汴河街", "天伦城商圈": "天伦城", "理工商圈": "理工",
        "南湖星都汇商圈": "南湖星都汇", "东风广场商圈": "东风广场",
        "八字门商圈": "八字门", "芒果时代商圈": "芒果时代",
        "得胜路美食街": "得胜路", "南湖广场商圈": "南湖广场",
        "岳阳商业城商圈": "商业城", "岳阳楼景区": "岳阳楼",
    }

    s = []
    s.append('<rect x="0" y="0" width="900" height="470" fill="#f3f0e6"/>')
    # 洞庭湖（西北，真实位置在岳阳西北）
    s.append('<path d="M 0 0 L 250 0 Q 190 70 150 130 Q 110 180 96 250 '
             'Q 60 250 0 232 Z" fill="#dce8ee" stroke="#b9d0da" stroke-width="1"/>')
    s.append('<text x="46" y="120" font-size="13" fill="#7fa0ae" '
             'font-family="Songti SC,serif" transform="rotate(-64 46 120)">洞庭湖</text>')
    # 长江（南面，岳阳以南）
    s.append('<path d="M 0 470 L 900 470 L 900 430 Q 640 444 430 436 '
             'Q 210 428 0 442 Z" fill="#dce8ee" stroke="#b9d0da" stroke-width="1"/>')
    s.append('<text x="742" y="459" font-size="12" fill="#7fa0ae" '
             'font-family="Songti SC,serif">长江</text>')

    for label, lat, lng, tier, p in pts:
        x, y = px(lng, lat)
        r = r_of.get(tier, 8)
        c = color.get(tier, "#8d867a")
        s.append('<circle cx="%.1f" cy="%.1f" r="%d" fill="%s" '
                 'fill-opacity="0.16" stroke="%s" stroke-width="2"/>'
                 % (x, y, r + 5, c, c))
        s.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>' % (x, y, c))
        nm = short.get(label, label.replace("商圈", ""))
        # 标签避让：交替上下
        dy = -16 if (int(y) // 40) % 2 == 0 else 22
        s.append('<text x="%.1f" y="%.1f" font-size="12.5" fill="#22201c" '
                 'text-anchor="middle" font-family="Songti SC,serif" '
                 'font-weight="600">%s</text>' % (x, y + dy, nm))
        s.append('<text x="%.1f" y="%.1f" font-size="10" fill="%s" '
                 'text-anchor="middle" font-family="system-ui,sans-serif">'
                 '连锁%d·餐饮%d</text>'
                 % (x, y + dy + (12 if dy < 0 else -13), c,
                    scan_by.get(label, {}).get("chain_inner", 0),
                    _d_inner(rows, label)))

    return "".join(s)


def _d_inner(rows, label):
    for _o, _n, lb, d, _p in rows:
        if lb == label:
            return d["poi_inner300"]
    return 0


def esc(s):
    return html.escape(str(s or ""))


def load():
    def rd(p):
        with io.open(os.path.join(ROOT, ".cache", p), encoding="utf-8") as f:
            return json.load(f)
    return rd("district_scan.json"), rd("food_drill.json"), rd("snack_verify.json")


def build():
    scan, drill, snacks = load()
    scan_by = {r["label"]: r for r in scan["rows"]}
    drill_by = {r["label"]: r for r in drill["rows"]}

    # 只取达标的商圈，按档位 + 餐饮密度排序
    order = ["A", "B", "C", "—"]
    rows = []
    for label, d in drill_by.items():
        p = PROFILE.get(label)
        if not p:
            continue
        rows.append((order.index(p["tier"]), -d["poi_inner300"], label, d, p))
    rows.sort(key=lambda x: (x[0], x[1]))

    out = []
    W = out.append

    W('<!DOCTYPE html>')
    W('<html lang="zh-CN">')
    W('<head>')
    W('<meta charset="UTF-8">')
    W('<meta name="viewport" content="width=device-width,initial-scale=1">')
    W('<title>岳阳商圈美食一体卡 · 13 个商圈全普查</title>')
    W('''<style>
:root{
  --paper:#f7f4ec; --card:#fffdf8; --ink:#22201c; --ink2:#5a554c; --ink3:#8d867a;
  --green:#1f4d40; --green-soft:#e8efe9; --red:#9e3b2f; --red-soft:#f6ebe8;
  --amber:#8a6410; --amber-soft:#f7efdc; --blue:#2a5a7a; --blue-soft:#e6eef4;
  --line:#ddd6c6; --line2:#eae4d6;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);
  font-family:"Songti SC","SimSun","Noto Serif SC",serif;line-height:1.72;padding:26px 16px 56px}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:28px;letter-spacing:3px;font-weight:700}
.sub{font-size:12.5px;color:var(--ink3);letter-spacing:1.2px;margin-top:7px}
.hd{border-bottom:2px solid var(--green);padding-bottom:15px;margin-bottom:20px}

.lead{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--green);
  padding:15px 17px;margin-bottom:20px;border-radius:3px;font-size:13.4px;color:var(--ink2)}
.lead b{color:var(--green)}
.lead p{margin-bottom:7px}
.lead p:last-child{margin-bottom:0}

h2.sec{font-size:19px;letter-spacing:2px;margin:34px 0 6px;padding-bottom:8px;
  border-bottom:1px solid var(--line);color:var(--green)}
.secmeta{font-size:12px;color:var(--ink3);margin-bottom:14px}

table.idx{width:100%;border-collapse:collapse;font-size:12.6px;background:var(--card);
  border:1px solid var(--line);margin-bottom:12px}
table.idx th{background:var(--green);color:#fff;font-weight:600;padding:8px 7px;
  text-align:left;font-size:11.5px;letter-spacing:.6px;font-family:system-ui,sans-serif}
table.idx td{padding:8px 7px;border-bottom:1px solid var(--line2);vertical-align:top}
table.idx tr:last-child td{border-bottom:none}
table.idx tbody tr:hover{background:var(--green-soft)}
.num{font-family:system-ui,sans-serif;font-size:12px;text-align:center}
.tier{display:inline-block;font-family:system-ui,sans-serif;font-size:10.5px;font-weight:700;
  color:#fff;padding:1px 6px;border-radius:2px;letter-spacing:.5px}
.tA{background:var(--green)} .tB{background:var(--blue)} .tC{background:var(--amber)} .tD{background:var(--ink3)}

.dist{border-bottom:1px solid var(--line2)}
.dist:last-child{border-bottom:none}
.dhd{display:flex;align-items:baseline;gap:10px;margin-bottom:5px;flex-wrap:wrap}
.dno{font-family:system-ui,sans-serif;font-size:11px;font-weight:700;letter-spacing:2px;color:#fff;
  background:var(--green);padding:3px 9px;border-radius:2px}
.dnm{font-size:18px;font-weight:700;letter-spacing:1.2px}
.dshape{font-size:11px;color:var(--ink3);font-family:system-ui,sans-serif;
  border:1px solid var(--line);padding:1px 6px;border-radius:2px}
.daddr{font-size:12.3px;color:var(--ink3);margin:0 0 10px}

.metrics{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:11px}
.met{background:var(--card);border:1px solid var(--line);padding:6px 11px;border-radius:3px;
  min-width:88px}
.met .mk{font-size:10.5px;color:var(--ink3);letter-spacing:.4px;margin-bottom:2px}
.met .mv{font-family:system-ui,sans-serif;font-size:17px;font-weight:700;color:var(--green);line-height:1.2}
.met .mn{font-size:10px;color:var(--ink3)}
.met.warn .mv{color:var(--amber)}

.six{background:var(--green-soft);border-left:3px solid var(--green);padding:10px 13px;
  font-size:12.6px;color:var(--ink2);margin-bottom:12px;border-radius:0 2px 2px 0}
.six .sk{color:var(--green);font-weight:700;letter-spacing:.5px}
.six div{margin-bottom:5px}
.six div:last-child{margin-bottom:0}

.items{background:var(--card);border:1px solid var(--line);border-radius:3px;overflow:hidden}
.item{display:flex;gap:10px;padding:9px 12px;border-bottom:1px solid var(--line2);align-items:flex-start}
.item:last-child{border-bottom:none}
.item .ix{font-family:system-ui,sans-serif;font-size:11px;color:var(--ink3);min-width:20px;padding-top:2px}
.item .ib{flex:1}
.item .inm{font-size:14px;font-weight:600;margin-bottom:2px}
.item .imeta{font-size:11.6px;color:var(--ink3);font-family:system-ui,sans-serif}
.mark{font-family:system-ui,sans-serif;font-size:10px;font-weight:700;padding:1px 5px;
  border-radius:2px;margin-right:5px;white-space:nowrap}
.mA{background:var(--green-soft);color:var(--green)}
.mB{background:var(--blue-soft);color:var(--blue)}
.mC{background:var(--amber-soft);color:var(--amber)}
.mW{background:#f0ece0;color:var(--ink3)}

.snack{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--amber);
  padding:13px 15px;margin-bottom:10px;border-radius:3px}
.snack .sn{font-size:15px;font-weight:700;margin-bottom:3px}
.snack .sl{font-size:11.8px;color:var(--blue);margin-bottom:4px;font-family:system-ui,sans-serif}
.snack .sd{font-size:12.6px;color:var(--ink2)}

.fail{background:var(--red-soft);border:1px solid #e0c4bd;border-radius:3px;padding:12px 15px;
  font-size:12.8px;color:var(--ink2);margin-bottom:16px}
.fail h4{font-size:13.5px;color:var(--red);margin-bottom:6px;letter-spacing:.5px}
.fail ul{margin:0;padding-left:19px}
.fail li{margin-bottom:3px}

.foot{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);
  font-size:11.8px;color:var(--ink3);line-height:1.8}
.foot b{color:var(--ink2)}

.mapwrap{background:var(--card);border:1px solid var(--line);border-radius:3px;
  padding:12px 14px 11px;margin:16px 0 6px}
svg.map{width:100%;height:auto;display:block;border-radius:2px}
.mapnote{font-size:11.6px;color:var(--ink3);margin-top:9px;line-height:1.75}
.mapnote b{color:var(--ink2)}
.dotA,.dotB,.dotC{display:inline-block;width:9px;height:9px;border-radius:50%;
  margin:0 4px 0 12px;vertical-align:middle}
.dotA{background:#1f4d40} .dotB{background:#2a5a7a} .dotC{background:#8a6410}
</style>''')
    W('</head>')
    W('<body><div class="wrap">')

    # ---------------- 头部 ----------------
    W('<div class="hd">')
    W('<h1>岳阳商圈美食一体卡</h1>')
    W('<div class="sub">全城商圈普查 · 13 个商圈核验 · 门店档与小吃档合并　|　检索 2026-10-20</div>')
    W('</div>')

    W('<div class="lead">')
    W('<p><b>这张卡回答三个问题：岳阳到底有几个商圈、每条街各自有什么、哪些好吃的是地图查不到的。</b></p>')
    W('<p><b>关于商圈数量：</b>扫描 18 个候选锚点（从地图检索反查得到，非凭记忆列举），'
      '通过三信号核验的达 <b>13 个</b>，另有 3 个反例锚点被明确否决。用户点名的'
      '岳阳楼汴河街、步行街、花板桥、南湖广场、八字门、理工六个商圈<b>全部存在</b>，'
      '另有得胜南路美食街、天伦城、南湖星都汇等为本次新发现。</p>')
    W('<p><b>关于判定方法：</b>用三个独立信号交叉——<b>连锁品牌密度</b>（测品牌资本开支）、'
      '<b>餐饮 POI 密度</b>（测吃饭人流）、<b>到访热度</b>（百度官方口径）。'
      '单用连锁密度会系统性误杀本地小吃型街区：得胜南路美食街连锁只有 1 家，'
      '但 300 m 内餐饮 10 家，是本地人天天去的地方。</p>')
    W('<p><b>关于小吃：</b>顶糕、小笼汤包、擂茶、肉蛋堡这些<b>没有 POI</b>，'
      '地图检索只能返回整条街。它们单列在末尾的「传统小吃档」，已标注来源强度——'
      '<span class="mark mA">✅A</span> 门店已核验　<span class="mark mB">✅B</span> '
      '街区内品类·多源交叉　<span class="mark mC">✅C</span> 纯文本交叉　'
      '<span class="mark mW">⚠️</span> 待核实。</p>')
    W('</div>')

    # ---------------- ① 商圈索引表 ----------------
    W('<h2 class="sec">① 商圈索引表</h2>')
    W('<div class="secmeta">18 个候选锚点 → 13 个达标 + 5 个反例/次级。'
      '连锁与餐饮均为核心 300 m 内计数。</div>')
    W('<table class="idx"><thead><tr>')
    W('<th>商圈</th><th>锚点</th><th>连锁<br>/300m</th><th>餐饮<br>/300m</th>'
      '<th>热度</th><th>档</th><th>一句话定位</th>')
    W('</tr></thead><tbody>')
    for i, (_o, _n, label, d, p) in enumerate(rows, 1):
        sc = scan_by.get(label, {})
        W('<tr>')
        W('<td><b>%d. %s</b></td>' % (i, esc(label)))
        W('<td>%s<br><span style="color:var(--ink3);font-size:11.5px">%s</span></td>'
          % (esc(p["anchor"]), esc(p["kind"])))
        chain = d.get("chain_inner", 0)
        W('<td class="num"><b>%d</b></td>' % chain)
        W('<td class="num"><b>%d</b></td>' % d["poi_inner300"])
        heat = sc.get("arrival_heat")
        heat_s = ("%.2f" % heat) if isinstance(heat, (int, float)) else "—"
        W('<td class="num">%s</td>' % heat_s)
        W('<td class="num"><span class="tier t%s">%s</span></td>'
          % (p["tier"] if p["tier"] in "ABC" else "D", esc(p["tier_name"])))
        W('<td>%s</td>' % esc(p["crowd"]))
        W('</tr>')
    W('</tbody></table>')
    W('<div class="secmeta" style="margin-top:-4px">'
      '档位：<b>A</b> 连锁+餐饮双强 · <b>B</b> 美食型（餐饮密度主导，连锁少） · '
      '<b>C</b> 街区型点（可顺路） · <b>—</b> 非商圈（见文末反例）。</div>')

    W('<div class="mapwrap">')
    W('<svg viewBox="0 0 900 470" class="map">' + map_svg(rows, scan_by) + '</svg>')
    W('<div class="mapnote">'
      '示意图：按各商圈锚点<b>真实经纬度</b>等比投影，非示意摆位。'
      '洞庭湖在西北方向（图中左上留白区）。<br>'
      '<span class="dotA"></span>A 档（双强）　'
      '<span class="dotB"></span>B 档（美食型）　'
      '<span class="dotC"></span>C 档（街区型）</div>')
    W('</div>')

    # ---------------- ② 各商圈美食 ----------------
    W('<h2 class="sec">② 各商圈美食</h2>')
    W('<div class="secmeta">每圈给：商圈画像六件套 + 该圈餐饮 POI 头部条目。'
      '条数按档位收敛（A 档 9 条 / B 档 7 条 / C 档 5 条），不凑数。</div>')

    show = {"A": 9, "B": 7, "C": 5, "—": 5}
    for idx, (_o, _n, label, d, p) in enumerate(rows, 1):
        sc = scan_by.get(label, {})
        W('<div class="dist">')
        W('<div class="dhd">')
        W('<span class="dno">%02d</span>' % idx)
        W('<span class="dnm">%s</span>' % esc(label))
        W('<span class="tier t%s" style="font-family:system-ui,sans-serif;font-size:10.5px;'
          'font-weight:700;color:#fff;padding:2px 7px;border-radius:2px">%s</span>'
          % (p["tier"] if p["tier"] in "ABC" else "D", esc(p["tier_name"])))
        W('<span class="dshape">%s</span>' % esc(p["shape"]))
        W('</div>')
        W('<div class="daddr">锚点：%s　|　%s　|　核心 300 m 连锁 %d 家 · 餐饮 POI %d 家 · '
          '到访热度 %s</div>'
          % (esc(p["anchor"]), esc(p["kind"]), d.get("chain_inner", 0),
             d["poi_inner300"],
             ("%.2f" % sc["arrival_heat"]) if isinstance(sc.get("arrival_heat"), (int, float)) else "无数据"))

        # 六件套
        W('<div class="six">')
        for key, label2 in [("peak", "高峰时段"), ("price", "消费带宽"),
                            ("axis", "动线主轴"), ("skip", "可跳过段"),
                            ("crowd", "本地客成分")]:
            val = p[key].replace("**", "")
            W('<div><span class="sk">%s：</span>%s</div>' % (label2, esc(val)))
        W('</div>')

        # 头部条目
        n_show = show.get(p["tier"], 6)
        items = d["inner"][:n_show]
        if items:
            W('<div class="items">')
            for j, it in enumerate(items, 1):
                r = num(it.get("rating"))
                c = num(it.get("comments"))
                meta = []
                if r is not None:
                    meta.append("评分 %.1f" % r)
                if c is not None:
                    meta.append("评价 %d 条" % int(c))
                if it.get("address"):
                    meta.append(str(it["address"])[:30])
                W('<div class="item"><span class="ix">%d</span><div class="ib">' % j)
                W('<div class="inm"><span class="mark mA">✅A</span>%s</div>' % esc(it["name"]))
                if meta:
                    W('<div class="imeta">%s</div>' % esc(" · ".join(meta)))
                W('</div></div>')
            W('</div>')
        else:
            W('<div class="secmeta" style="color:var(--ink2)">'
              '该锚点 300 m 内无实餐饮 POI 命中，不列条目。</div>')
        if len(d["inner"]) > n_show:
            W('<div class="secmeta" style="margin-top:6px">'
              '该圈 300 m 内共 %d 家餐饮 POI，此处列头部 %d 家；'
              '其余为同类重复，不逐条堆叠。</div>' % (len(d["inner"]), n_show))
        W('</div>')

    # ---------------- ③ 传统小吃档 ----------------
    W('<h2 class="sec">③ 传统小吃档（地图查不到的那些）</h2>')
    W('<div class="secmeta">'
      '用户反馈「汴河街南门入口的顶糕和小笼汤包，是汴河街的传统小吃，是没有记录的，'
      '但味道真的很好」——实测确认：地图检索「汴河街顶糕」<b>只能返回「汴河街」整条街</b>，'
      '没有任何顶糕摊位坐标。它是流动担子摊。这一档就是为此而设。'
      '核验结果：%d 条线索 → ✅A %d · ✅B %d · ✅C %d · ⚠️ %d · ❌ %d。</div>'
      % (len(snacks["rows"]),
         sum(1 for r in snacks["rows"] if r["mark"] == "✅A"),
         sum(1 for r in snacks["rows"] if r["mark"] == "✅B"),
         sum(1 for r in snacks["rows"] if r["mark"] == "✅C"),
         sum(1 for r in snacks["rows"] if r["mark"] == "⚠️"),
         sum(1 for r in snacks["rows"] if r["mark"] == "❌")))

    # 已通过核验的
    order_marks = ["✅A", "✅B", "✅C", "⚠️"]
    for mk in order_marks:
        group = [r for r in snacks["rows"] if r["mark"] == mk]
        if not group:
            continue
        for r in group:
            nm = r["name"]
            extra = SNACK_NOTE.get(nm)
            loc = extra[0] if extra else (r.get("district") or "")
            desc = extra[1] if extra else (r.get("text_note") or "")
            W('<div class="snack" style="%s">'
              % ("border-left-color:var(--green)" if mk == "✅A" else
                 "border-left-color:var(--blue)" if mk == "✅B" else
                 "border-left-color:var(--amber)"))
            W('<div class="sn"><span class="mark m%s">%s</span>%s</div>'
              % (mk.replace("✅", "").replace("⚠️", "W"), mk, esc(nm)))
            W('<div class="sl">位置：%s</div>' % esc(loc))
            if desc:
                W('<div class="sd">%s</div>' % esc(desc))
            forbid = r.get("forbid")
            if forbid:
                W('<div class="sl" style="color:var(--amber);margin-top:4px">⚠ %s</div>'
                  % esc(forbid))
            if r.get("mark_note"):
                W('<div class="sl" style="color:var(--amber)">⚠ %s</div>'
                  % esc(r["mark_note"]))
            W('<div class="sl" style="color:var(--ink3);margin-top:4px">'
              '核验依据：%s</div>' % esc(r["why"]))
            srcs = r.get("text_sources") or []
            if len(srcs) >= 2:
                W('<div class="sl" style="color:var(--ink3)">文本来源（%d）：%s</div>'
                  % (len(srcs), esc("；".join(srcs[:4]))))
            W('</div>')

    # ---------------- 反例 ----------------
    W('<h2 class="sec">④ 未达标锚点（反例）</h2>')
    W('<div class="secmeta">列出并给出数据理由——说明这些是<b>确实扫过并否决</b>的，不是漏掉。</div>')
    W('<div class="fail"><h4>以下锚点经三信号核验未达商圈标准</h4><ul>')
    W('<li><b>洞庭街道</b>：连锁 0 家、到访热度 0.05。'
      '虽有 9 家餐饮在 300 m 内，但这是<b>办事处坐标落在机关大院、周边老社区餐饮被算进来</b>的溢出，'
      '属居民区而非商圈。</li>')
    W('<li><b>东茅岭</b>：原锚点解析到「东茅岭环境卫生服务中心」，无热度数据。'
      '实际商业在天虹百货与步行街片，已并入「步行街商圈」呈现，不单列。</li>')
    W('<li><b>万达商圈</b>：地图命中的是<b>平江县</b>的万达广场（平江是岳阳下辖另一个人口大县），'
      '岳阳楼区无对应商圈——<b>跨行政区误配，已剔除</b>。</li>')
    W('<li><b>东风广场 / 南湖广场</b>本体是<b>市政广场与湖滨绿地</b>，本身无餐点，'
      '餐饮集中在周边街段，故按周边街段呈现为 B/C 档。</li>')
    W('<li><b>岳阳楼景区</b>：到访热度高达 111.5，但连锁仅 2 家——属景区型人流，'
      '不是零售型商圈，餐饮按景区逻辑另算。</li>')
    W('</ul></div>')

    # ---------------- 页脚 ----------------
    W('<div class="foot">')
    W('<p><b>检索时间</b> 2026-10-20。营业状态、营业时间、人均价格属易变信息，出发前请复核。</p>')
    W('<p><b>数据来源</b> 百度地图 Agent Plan（POI 实时检索、到访热度、评分与评价数）'
      '＋ 本地宝/本地号/UGC 文本交叉（小吃档）。'
      '<span class="mark mA">✅A</span> 门店已核验　'
      '<span class="mark mB">✅B</span> 街区内品类·多源交叉　'
      '<span class="mark mC">✅C</span> 纯文本交叉　'
      '<span class="mark mW">⚠️</span> 待核实。</p>')
    W('<p><b>出发前须复核的 3 件事</b></p>')
    W('<p>1. 汴河街南门入口的<b>顶糕是流动担子摊，出摊时间不固定</b>，'
      '下午常收摊，早市与傍晚最稳。</p>')
    W('<p>2. <b>三津汤包（花板桥）与巴陵汤包店（汴河街）评分分别为 5.0 与 3.9</b>，'
      '汴河街这家本地口碑两极，去之前留意近期评价。</p>')
    W('<p>3. <b>得胜南路美食街的熊大妈米粉 06:30–10:30</b>，'
      '本地攻略实测 08:30 已挂「售罄」牌，去晚只剩汤底。</p>')
    W('<p><b>下一步</b> 你想去哪一个商圈？我可以按你的到达时间和同行人，'
      '把这一圈排成一条能照着走的动线（含步行距离与停留时长）。</p>')
    W('</div>')

    W('</div></body></html>')
    return "\n".join(out)


if __name__ == "__main__":
    p = os.path.join(ROOT, "岳阳商圈美食一体卡.html")
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(build())
    print("已生成 %s（%d 字符）" % (p, os.path.getsize(p)))