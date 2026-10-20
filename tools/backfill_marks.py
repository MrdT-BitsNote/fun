#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把三张实测小卡从旧的「● 官方可查 / ○ 待核实」两级标记，升级为 SKILL.md v0.1.1
规定的「✅A 地图 POI 已核验 / ✅B 官方已核对 / ⚠️ 待核实 / ❌ 剔除」四级体系，
并植入「城市源强项声明」。

可重复执行（幂等）：已升级过的卡片再次运行不会重复注入。

用法：python tools/backfill_marks.py
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- 三城配置

CITIES = [
    {
        "file": "岳阳美食小卡.html",
        "ok": 7,
        "pend": 10,
        "src": (
            "<b>岳阳两者皆弱</b>——全市没有本地商务局美食专题，可用的官方源只有岳阳县政府 / 市人社局"
            "考试季「餐饮商户名录」与非遗、地理标志公示。因此本次 7 条 ✅B 主要靠政府公示落门牌，"
            "10 条 ⚠️ 只能多源比对；菜品层亦无官方榜单，「经典」判断来自检索而非官方评选。"
        ),
        "ok_desc": (
            "店名 / 门牌 / 电话经岳阳县政府、市人社局餐饮商户名录等政府公示或名录类来源核对"
            "（含巴陵全鱼席省级非遗、君山虾饼、平江酱干地理标志等口径）。"
        ),
        "pend_desc": (
            "多源一致但缺门牌或电话，或仅有单一来源；品种级条目（粉藕汤、姜盐茶、姜辣系、兰花萝卜）"
            "本就无单一代表门店，故不给具体地址。"
        ),
    },
    {
        "file": "武汉美食小卡.html",
        "ok": 13,
        "pend": 6,
        "src": (
            "<b>武汉强在门店层</b>——武汉市商务局长期发布「过早一条街」「嘬虾地图」「十大名菜」等专题，"
            "老字号公示直接给出门牌与营业时间，13 条 ✅B 由此而来；"
            "<b>弱在菜品排名粒度</b>——「十大名菜」只给名次不给分数，经典菜的排序不如恩施精确。"
        ),
        "ok_desc": (
            "店名 / 门牌 / 营业时间经武汉市商务局公示文章、武汉「十大名菜」评选结果、"
            "老字号非遗名录或品牌官网核对。"
        ),
        "pend_desc": (
            "品牌名经官方点名，但门牌仅来自媒体探店（2026-09）；或属品种级条目（蛋酒），本就无专营店。"
        ),
    },
    {
        "file": "恩施美食小卡.html",
        "ok": 9,
        "pend": 11,
        "src": (
            "<b>恩施强在菜品层</b>——恩施州商务局 2024-05 公示含完整 30 名评分表"
            "（炕土豆 96.55、宣恩烤活鱼 93.73），本卡 20 条菜名与排名全部可核；"
            "<b>弱在门店层</b>——州商务局不发布餐厅名录，故具体门店门牌无一条来自官方公示，"
            "9 条 ✅B 为产地级 / 全州级条目（地理标志产区、非遗项目地）。"
        ),
        "ok_desc": (
            "该条为产地级 / 全州级条目，位置可公开核实（地理标志产区、非遗项目地、全州普遍供应），"
            "不依赖单一门店。"
        ),
        "pend_desc": (
            "该条给出了具体门店门牌，但来源为探店或媒体文章（D 级），未做地图 POI 核验；"
            "其中「张关合渣总店」门牌存在 62 号 / 118 号两种说法，已照实标出。"
        ),
    },
]

# ---------------------------------------------------------------- 样式补丁

CSS_PATCH = """
  .mark b{font-weight:700;margin-right:4px;}
  .mark.okb b{color:var(--green-2);}
  .mark.pend b{color:#B8860B;}
  .okb .ic{color:var(--green-2);}
  .srcnote{margin:0 30px;padding:11px 14px;background:#FDFBF6;border:1px solid var(--line);
    border-left:3px solid var(--green-2);border-radius:0 8px 8px 0;display:flex;gap:11px;align-items:flex-start;}
  .srcnote .lb{flex:0 0 auto;font-size:10px;letter-spacing:.12em;color:var(--green);
    background:var(--green-soft);border-radius:3px;padding:2px 6px;font-weight:700;margin-top:1px;}
  .srcnote p{font-size:11.5px;color:var(--ink-2);line-height:1.7;}
  .srcnote p b{color:var(--ink);font-weight:600;}
  .legend code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px;
    background:var(--green-soft);color:var(--green);padding:1px 4px;border-radius:2px;}
"""


def build_legend(c):
    return """  <div class="legend">
    <h4>可信标记说明（本卡按此标注，请连同标记一起读）</h4>
    <p>
      <b>● 官方已核对（✅B，{ok} 条）</b>：{ok_desc}<br>
      <b>○ 待核实（⚠️，{pend} 条）</b>：{pend_desc}<br>
      <b>POI 已核验（✅A，0 条）</b>：本次运行环境未配置地图 API 凭据"
      "（<code>BAIDU_MAP_AUTH_TOKEN</code> 与腾讯地图 key 均缺失），无法做实时在营与门牌核验，"
      "故本卡无 ✅A 条目。<b>本卡最高标记为 ✅B，属非实时核验</b>——营业状态、营业时间、人均价格均为检索快照，出发前请复核。<br>
      <b>已剔除（❌，0 条）</b>：本次未发现已关店或地址指向他店的条目；若有已剔除项，将在此列明原因。<br>
      <b>源强项</b>：{src}<br>
      <b>无图说明</b>：本卡不配任何菜品图——未取得可核验的实拍图，而 AI 生成图与图库图不能冒充该店的菜。留白不排图位，好过放一张「看起来像」的假图。
    </p>
  </div>""".format(
        ok=c["ok"], pend=c["pend"], ok_desc=c["ok_desc"],
        pend_desc=c["pend_desc"], src=c["src"]
    ).replace('"\n      "', "")


def build_srcnote(c):
    return (
        '  <div class="srcnote">\n'
        '    <span class="lb">源强项</span>\n'
        '    <p>' + c["src"] + '</p>\n'
        '  </div>\n\n'
    )


def process(path, c):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    orig = html

    # 1) 标记升级：class 与图标保持视觉一致，另加显式级别文字标签
    #    用负向前瞻保证幂等：已打过标签的条目不再重复注入（否则每次重跑标签会累加）
    html = re.sub(
        r'<div class="mark ok"><span class="ic">●</span><span>(?!<b>✅B</b>)',
        '<div class="mark okb"><span class="ic">●</span><span><b>✅B</b> ',
        html,
    )
    html = re.sub(
        r'<div class="mark pend"><span class="ic">○</span><span>(?!<b>⚠️</b>)',
        '<div class="mark pend"><span class="ic">○</span><span><b>⚠️</b> ',
        html,
    )

    # 2) 注入样式
    if ".srcnote{" not in html:
        anchor = ".pend .ic{color:#B8860B;}"
        if anchor in html:
            html = html.replace(anchor, anchor + "\n" + CSS_PATCH, 1)
        else:
            print("  ! 未找到样式锚点，跳过 CSS 注入")
            return False

    # 3) 移动端边距补丁
    mobile_anchor = ".legend{margin-left:16px;margin-right:16px;}"
    if mobile_anchor in html and ".srcnote{margin-left:16px" not in html:
        html = html.replace(
            mobile_anchor,
            mobile_anchor + "\n    .srcnote{margin-left:16px;margin-right:16px;}",
            1,
        )

    # 4) 头部 chip 汇总标记
    if "<b>标记</b>" not in html:
        chip = (
            '<span class="chip"><b>标记</b> ✅A 0 · ✅B {ok} · ⚠️ {pend}</span>\n      '.format(
                ok=c["ok"], pend=c["pend"]
            )
        )
        html = re.sub(
            r'(<div class="meta-row">.*?)(\n\s*</div>)',
            lambda m: m.group(1) + "\n      " + chip.strip() + m.group(2),
            html,
            count=1,
            flags=re.S,
        )

    # 5) 植入城市源强项声明
    if 'class="srcnote"' not in html:
        chapter_anchor = "  <!-- ========== 01 ========== -->"
        if chapter_anchor in html:
            html = html.replace(chapter_anchor, build_srcnote(c) + chapter_anchor, 1)
        else:
            print("  ! 未找到章节锚点，跳过源强项注入")
            return False

    # 6) 重写图例
    html = re.sub(
        r'  <div class="legend">.*?\n  </div>',
        lambda m: build_legend(c),
        html,
        count=1,
        flags=re.S,
    )

    if html == orig:
        print("  - 无变化（可能已升级过）")
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return True


def main():
    changed = 0
    for c in CITIES:
        path = os.path.join(BASE, c["file"])
        if not os.path.exists(path):
            print("! 缺文件:", c["file"])
            continue
        print("==>", c["file"])
        if process(path, c):
            changed += 1
    print("\n完成，更新文件数：%d" % changed)
    # 幂等工具：0 变化属正常状态，不作为错误退出
    return 0


if __name__ == "__main__":
    sys.exit(main())
