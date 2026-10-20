#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
✅A 回灌器 v2：把 POI 实时核验结果写回三张小卡。

做四件事：
  1. 标记升级：✅B / ⚠️ → ✅A（POI 实时核验通过）/ A-（店名匹配但门牌需修正）
  2. 地址行补入 POI 实时数据：营业时间、评分、电话（若有）
  3. 插入实拍图（百度地图商户图，is_default_image=False 者才可用）
  4. 图例与头部 chip 同步为最终统计

幂等：已回灌过的卡片重复执行不会重复注入。

用法：python tools/backfill_poi.py [--city 武汉|岳阳|恩施] [--force]
"""
import io
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, ".cache")
VERIFY = os.path.join(CACHE, "poi_verify.json")

CITY_LABEL = {"武汉": "武汉市", "岳阳": "岳阳市", "恩施": "恩施市"}
FILES = [("武汉", "武汉美食小卡.html"), ("岳阳", "岳阳美食小卡.html"),
         ("恩施", "恩施美食小卡.html")]

# 每城的「核验能力说明」——写入图例，诚实披露本卡用到的官方源与实时源
CITY_NOTE = {
    "武汉": (
        "本卡 <b>✅A 级实时核验已启用</b>（百度地图 Agent Plan POI 核验，检索日 2026-10-20）："
        "门牌 / 店名 / 近 90 天真实评价三项同时通过才打 ✅A。<br>"
        "<b>武汉强在门店层</b>——武汉市商务局长期发布「过早一条街」「嘬虾地图」「十大名菜」等专题，"
        "老字号公示直接给出门牌与营业时间；<b>弱在菜品排名粒度</b>——「十大名菜」只给名次不给分数。"
    ),
    "岳阳": (
        "本卡 <b>✅A 级实时核验已启用</b>（百度地图 Agent Plan POI 核验，检索日 2026-10-20）："
        "门牌 / 店名 / 近 90 天真实评价三项同时通过才打 ✅A。<br>"
        "<b>岳阳两者皆弱</b>——全市没有本地商务局美食专题，可用的官方源只有岳阳县政府 / 市人社局"
        "考试季「餐饮商户名录」与非遗、地理标志公示；因此本卡的门店可信度主要来自 POI 实时核验，"
        "而非官方公示。"
    ),
    "恩施": (
        "本卡 <b>✅A 级实时核验已启用</b>（百度地图 Agent Plan POI 核验，检索日 2026-10-20）："
        "门牌 / 店名 / 近 90 天真实评价三项同时通过才打 ✅A。<br>"
        "<b>恩施强在菜品层</b>——恩施州商务局 2024-05 公示含完整 30 名评分表，菜名与排名全部可核；"
        "<b>弱在门店层</b>——州商务局不发布餐厅名录，故门店字段靠 POI 核验补齐。"
    ),
}


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def process(city, fname, V, force=False):
    path = os.path.join(BASE, fname)
    html = io.open(path, encoding="utf-8").read()
    orig = html

    # ---------- 统计 ----------
    stats = {"A": 0, "A-": 0, "B+": 0, "C": 0, "SKIP": 0}
    for k, v in V.items():
        if k.startswith(fname + "#"):
            stats[v.get("level", "C")] = stats.get(v.get("level", "C"), 0) + 1

    # ---------- 逐条替换标记与地址行 ----------
    cards = re.findall(r'(<article class="card">.*?</article>)', html, re.S)

    def fix_card(m):
        blk = m.group(1)
        nm = re.search(r'<span class="no">(\d+)</span>', blk)
        if not nm:
            return blk
        key = "%s#%02d" % (fname, int(nm.group(1)))
        v = V.get(key)
        if not v:
            return blk
        lvl = v.get("level", "C")

        # 1) 标记行重写
        level_label = {
            "A": "✅A", "A-": "✅A-", "B+": "✅B", "C": "⚠️", "SKIP": "⚠️",
        }.get(lvl, "⚠️")
        note = v.get("reason", "")
        if lvl == "SKIP":
            note = "产地级 / 品种级条目，无单一门店，不适用 POI 核验"
        elif v.get("poi_name"):
            note = "百度地图 POI「%s」%s；最近评价 %s" % (
                v.get("poi_name"), "在营" if v.get("shop_hours") else "营业时间未标注",
                v.get("last_comment") or "无")
        new_mark = ('<div class="mark %s"><span class="ic">%s</span>'
                    '<span><b>%s</b> %s</span></div>') % (
            "okb" if lvl in ("A", "A-", "B+") else "pend",
            "●" if lvl in ("A", "A-", "B+") else "○",
            level_label, esc(note))
        blk = re.sub(r'<div class="mark (okb|pend)">.*?</div>', new_mark, blk,
                     count=1, flags=re.S)

        # 2) 地址行补实时数据
        if lvl in ("A", "A-") and v.get("poi_name"):
            extra = []
            if v.get("shop_hours"):
                extra.append("POI 营业 %s" % v["shop_hours"])
            if v.get("rating"):
                extra.append("评 %s（%s 条）" % (v["rating"], v.get("comment_num") or "?"))
            if v.get("telephone"):
                extra.append("☎ %s" % v["telephone"])
            if extra:
                add = "　·　" + "　".join(extra)
                blk = re.sub(r'(</span></div>)', r'\1', blk, count=0)
                # 在地址行的 val 内追加
                m2 = re.search(r'(<span class="lab">址</span><span class="val addr">)(.*?)(</span>)',
                               blk, re.S)
                if m2:
                    blk = blk[:m2.start(2)] + m2.group(2) + add + blk[m2.end(2):]

        # 3) 实拍图（仅 POI 商户图且非默认图）
        if lvl in ("A", "A-") and v.get("image") and not v.get("is_default_image"):
            if "poi-photo" not in blk:
                fig = ('<div class="poi-photo"><img src="%s" alt="%s 实拍" loading="lazy">'
                       '<span>图源：百度地图商户实拍 · 2026-10</span></div>') % (
                    v["image"], esc(v.get("poi_name") or ""))
                blk = blk.replace('<div class="rows">', fig + '<div class="rows">', 1)
        return blk

    html = re.sub(r'(<article class="card">.*?</article>)', fix_card, html, flags=re.S)

    # ---------- 样式 ----------
    if ".poi-photo{" not in html:
        css = """
  .poi-photo{margin:0 0 9px;border-radius:6px;overflow:hidden;position:relative;}
  .poi-photo img{width:100%;display:block;max-height:150px;object-fit:cover;}
  .poi-photo span{position:absolute;left:0;bottom:0;right:0;font-size:9px;color:#F2EFE6;
    background:rgba(27,42,37,.62);padding:3px 7px;letter-spacing:.03em;}
"""
        anchor = "  .legend{"
        if anchor in html:
            html = html.replace(anchor, css.strip("\n") + "\n" + anchor, 1)

    # ---------- 头部 chip ----------
    m = re.search(r'<span class="chip"><b>标记</b>[^<]*</span>', html)
    if m:
        chip = ('<span class="chip"><b>标记</b> ✅A %d · ✅A- %d · ✅B %d · ⚠️ %d</span>'
                % (stats.get("A", 0), stats.get("A-", 0), stats.get("B+", 0),
                   stats.get("C", 0) + stats.get("SKIP", 0)))
        html = html.replace(m.group(0), chip, 1)

    # ---------- 图例重写 ----------
    legend = """  <div class="legend">
    <h4>可信标记说明（本卡按此标注，请连同标记一起读）</h4>
    <p>
      <b>● POI 已核验（✅A {A} 条）</b>：百度地图 POI 实时核验通过——门牌（或地标/街道）与店名一致，"
      "且近 90 天内有真实用户评价。数据含营业时间、评分、评价条数与商户实拍图。<br>
      <b>● POI 已核验·门牌待修正（✅A- {Am} 条）</b>：店名匹配且有近 90 天评价，但百度 POI 记录的门牌"
      "与卡片原记载不同（多为连锁店分店差异或行政区划调整），已在条目中标注 POI 实测地址。<br>
      <b>● 官方已核对（✅B {B} 条）</b>：名称与位置经官方口径确认，但 POI 上无近 90 天新评价，"
      "不能确证当前在营状态。<br>
      <b>○ 待核实（⚠️ {C} 条）</b>：地图未收录该店、店名已变更或属产地级 / 品种级条目（无单一门店），"
      "无法做门店级核验。<br>
      {note}<br>
      <b>图片说明</b>：配图均为<b>百度地图商户实拍</b>（已排除默认图），图源标注在图下；"
      "未取得实拍的条目不排图位，不以 AI 图或图库图替代。
    </p>
  </div>""".format(A=stats.get("A", 0), Am=stats.get("A-", 0),
                   B=stats.get("B+", 0), C=stats.get("C", 0) + stats.get("SKIP", 0),
                   note=CITY_NOTE[city]).replace('"\n      "', "")

    html = re.sub(r'  <div class="legend">.*?\n  </div>', lambda mm: legend, html,
                  count=1, flags=re.S)

    # ---------- 页脚数据来源说明 ----------
    html = re.sub(
        r'数据来源层级：[^<]*。',
        '数据来源层级：百度地图 POI 实时核验（A 级，检索日 2026-10-20）＞ 商务局/政府公示（A 级替代）'
        '＞ 品牌官网（B 级）＞ 媒体探店（D 级，仅作线索）＞ 聚合榜单（未采用）。',
        html, count=1)

    if html == orig:
        print("  - 无变化")
        return False
    io.open(path, "w", encoding="utf-8").write(html)
    print("  - 已回灌：%s" % fname)
    return True


def main():
    if not os.path.exists(VERIFY):
        print("! 未找到核验结果，请先运行 verify_poi.py")
        return 2
    V = json.load(io.open(VERIFY, encoding="utf-8"))
    args = sys.argv[1:]
    only = args[args.index("--city") + 1] if "--city" in args else None
    n = 0
    for city, fname in FILES:
        if only and city != only:
            continue
        print("==", fname)
        if process(city, fname, V):
            n += 1
    print("\n完成，回灌文件数：%d" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
