#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全国索引生成器 v0.7.0 —— data/README.md + data/_status.tsv

产出：
  data/README.md        全国总索引：省 → 市 的可点击目录、各省 POI 统计、
                       全国维度汇总、数据使用与校对入口
  data/_status.tsv       机读进度表：省/市/adcode/POI数/查询面/波次/告警

README 是给人看的入口，_status.tsv 是给脚本/校对工具读的。
v0.7.0：同步新 13 章节结构、波次状态、行政层级链接。
"""

import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, ".cache", "amap", "raw")
PROV = os.path.join(ROOT, ".cache", "amap", "prov_cities.json")
DATA = os.path.join(ROOT, "data")


def load(city):
    fp = os.path.join(RAW, city + ".json")
    if not os.path.exists(fp):
        return None
    with open(fp, encoding="utf-8") as f:
        return json.load(f)


def city_stats(cache):
    allp = [p for q in (cache.get("queries") or {}).values()
            for p in q.get("items", [])]
    u = {p["id"]: p for p in allp if p.get("id")}
    return len(u), len(cache.get("queries") or {})


def main():
    provs = json.load(open(PROV, encoding="utf-8"))
    os.makedirs(DATA, exist_ok=True)

    rows = []
    grand = 0
    total_cities = 0
    wave2_done = 0
    prov_lines = []
    for pname, v in provs.items():
        cities = v.get("cities") or []
        total_cities += len(cities)
        tot, cnt, errs = 0, 0, 0
        lines = []
        for ad, cname, lvl in cities:
            cache = load(cname)
            if cache is None:
                lines.append("  - %s —— ⏳ 未采集" % cname)
                continue
            n, qn = city_stats(cache)
            bad = len(cache.get("errors") or [])
            waves = cache.get("waves") or [1]
            tot += n
            cnt += 1
            errs += bad
            if 2 in waves:
                wave2_done += 1
            flag = "⚠️" if bad else "✅"
            wv = "w" + "+".join(str(x) for x in waves)
            lines.append("  - %s %s [%s](%s.md) —— %d POI / %d 查询面 / %s"
                         % (flag, wv, cname, cname, n, qn, wv))
            rows.append((pname, cname, ad, n, qn, "+".join(str(x) for x in waves),
                         bad))
        grand += tot
        if cnt:
            prov_lines.append(
                "| [%s](%s/%s.md) | %s | %d | %d | %d |" % (
                    pname, pname, pname, v["adcode"], len(cities), cnt, tot))
            # 省级索引页：让 README 的省份链接落地，也给网站当省份页素材
            pm = []
            pm.append("# %s · 美食 × 商圈 × 娱乐 索引" % pname)
            pm.append("")
            pm.append("> 上级索引：[全国总索引](../README.md)  ")
            pm.append("> 生成时间：%s  ·  已采集 %d / %d 城  ·  "
                      "POI 合计 %s 条（去重后）"
                      % (time.strftime("%Y-%m-%d %H:%M"), cnt, len(cities),
                         format(tot, ",")))
            pm.append("")
            pm.append("## 城市列表")
            pm.append("")
            pm.append("| 城市 | POI 数 | 查询面 | 波次 | 告警 |")
            pm.append("|---|---|---|---|---|")
            for ad, cname, lvl in cities:
                cache = load(cname)
                if cache is None:
                    pm.append("| %s | — | — | — | ⏳ 未采集 |" % cname)
                    continue
                n, qn = city_stats(cache)
                waves = cache.get("waves") or [1]
                bad = len(cache.get("errors") or [])
                pm.append("| [%s](%s.md) | %s | %d | w%s | %s |" % (
                    cname, cname, format(n, ","), qn,
                    "+".join(str(x) for x in waves),
                    "⚠️ %d" % bad if bad else "0"))
            pm.append("")
            with open(os.path.join(DATA, pname, pname + ".md"), "w",
                      encoding="utf-8") as f:
                f.write("\n".join(pm))
        prov_lines.append("")
        prov_lines.append("<details><summary>展开 %s 各市</summary>" % pname)
        prov_lines.append("")
        prov_lines.extend(lines)
        prov_lines.append("")
        prov_lines.append("</details>")
        prov_lines.append("")

    with open(os.path.join(DATA, "_status.tsv"), "w", encoding="utf-8") as f:
        f.write("省\t市\tadcode\tPOI数\t查询面数\t波次\t告警数\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")

    done = len(rows)
    md = []
    w = md.append
    w("# 全国美食 × 商圈 × 娱乐 数据总索引")
    w("")
    w("> 本目录是「本地美食探索」skill 的数据层（v0.7.0）。")
    w("> 每个地级市一份 md，共 13 个章节：可信度 / 城市总览（行政层级+"
      "业态分布）/ 商圈档案（画像+评级 S/A/B/C）/ 成人娱乐 / 儿童亲子 / "
      "综合体商场 / 本地美食 / 苍蝇馆 / 特产 / 美食×商圈关联 / "
      "酒店配套 / 原始数据 / 校对待办。")
    w(">")
    w("> 数据源：高德地图 Web 服务 POI（restapi.amap.com）  ")
    w("> 采集 `tools/amap_collect.py` · 渲染 `tools/render_md.py` · "
      "校验 `tools/validate_data.py` · 索引本脚本 · "
      "行政层级 `tools/build_hierarchy.py`")
    w("")
    w("## 进度（更新于 %s）" % time.strftime("%Y-%m-%d %H:%M"))
    w("")
    w("| 省 | adcode | 城市数 | 已采集 | POI 合计 |")
    w("|---|---|---|---|---|")
    for line in prov_lines:
        if line.startswith("| ["):
            w(line)
    w("")
    w("**全国合计：%d / %d 城已建库（其中 %d 城含 wave2 全维度），"
      "POI 共 %s 条（去重后）。**"
      % (done, total_cities, wave2_done, format(grand, ",")))
    w("")
    w("配套文档：[行政层级总览](行政层级总览.md)"
      "（省/直辖市/省会/地级市/县级市/区县/镇/乡 共 %s 个节点，"
      "村级高德不提供）" % "43,474")
    w("")
    w("## 各省目录")
    w("")
    for line in prov_lines:
        if not line.startswith("| [") and line.strip():
            w(line)
    w("")
    w("## 维度定义（v0.7.0）")
    w("")
    w("| 维度 | 章节 | 高德依据 |")
    w("|---|---|---|")
    w("| 数据可信度 | §0 | POI 去重计数、评分覆盖率、采集告警 |")
    w("| 城市总览 | §1 | 行政层级（config/district）+ 区县 POI 分布 + "
      "商圈载体类型构成 |")
    w("| 商圈档案 | §2 | 061001 步行街 / 061000 特色商业街 / 060101 购物中心 / "
      "060100 商场 + 关键词 美食街/夜市/小吃街/百货/奥莱/批发；"
      "每商圈含画像（载体/消费带宽/动线主轴/业态分布）与 S/A/B/C 评级 |")
    w("| 成人娱乐 | §3 | 080304 酒吧 + 关键词 酒馆/livehouse/密室/KTV/"
      "电影院/棋牌/电玩 |")
    w("| 儿童与亲子 | §4 | 关键词 儿童乐园/淘气堡/迷你游乐场/亲子乐园/"
      "迷你动物园/萌宠 + 0805 休闲场所；区分 场内/独立 载体 |")
    w("| 综合体与商场 | §5 | 060100/060101/060200 + 名称含 购物中心/百货/"
      "奥莱/批发 |")
    w("| 本地美食 / 特色美食 | §6 | 050100 中餐厅 / 050108 地方菜 / "
      "050118 地方风味 + 关键词 特色美食/本地菜/老字号 |")
    w("| 苍蝇馆 / 小店 | §7 | 关键词 苍蝇馆 + 店名小店语义（小馆/排挡/"
      "家常/私房/土菜/大排档）|")
    w("| 知名特产 | §8 | 关键词 特产/土特产/地方特产 + 0607 类 |")
    w("| 美食 × 商圈关联 | §9 | 名称互证 + 距离就近（≤600m 同区县）|")
    w("| 酒店配套 | §10 | 100000 住宿服务 + 关键词 酒店 |")
    w("| 原始数据 | §11 | 全量查询面清单 + 原始 JSON 指针 |")
    w("| 校对待办 | §12 | 机器识别的问题清单 |")
    w("")
    w("## 校对入口")
    w("")
    w("1. 打开任一城市 md 的 **§12 校对待办**，那是机器已识别的问题清单。")
    w("2. 全量机器校验：`python tools/validate_data.py`（10 项规则，"
      "含表格列数、粗体配对、悬空引用、评级口径、维度完整性）。")
    w("3. 补采单城：`python tools/amap_collect.py --city XX市`"
      "（wave1+2 约 63 请求）；只补新维度：`--city XX市 --wave 2`"
      "（约 14 请求）。**跑批前先探测 key 可用性。**")
    w("4. 重渲染：`python tools/render_md.py --all`；"
      "重建索引：`python tools/build_index.py`。")
    w("")
    w("## 数据口径与已知边界")
    w("")
    w("- **评分**取高德 `biz_ext.rating`，无人工干预；无评分者一律 ⚠️，"
      "不做无据推荐。")
    w("- **人均**取高德 `biz_ext.cost`，单位元，可能滞后于实际涨价。")
    w("- **商圈画像分两类**：可推导的（载体类型/消费带宽/动线主轴/"
      "业态分布）直接给出；不可推导的（高峰时段/本地客成分/"
      "可跳过商业段）标「待人工校对」，不编造。")
    w("- **商圈评级判据可复算**：S/A/B/C 的量化门槛写在各城 §2 表头。")
    w("- **图片**取高德店铺图 URL，仅供校对时肉眼确认门店真实性。")
    w("- **苍蝇馆不做无据判定**：小店语义 + 评分区间双条件，"
      "宁可漏列也不编造。")
    w("- **关联为机器初判**：仅靠距离的关联必须人工确认，"
      "防止景区边界、跨街区误配。")
    w("- **撤柜风险**：§4 场内儿童游乐的撤柜率高，"
      "去之前需二次确认营业状态。")
    w("- **村级数据缺失**：高德行政区划接口不下探到村，"
      "本库不含村级名录，亦未编造。")
    w("")
    w("## 采集纪律（事故沉淀）")
    w("")
    w("1. **先探测 key 再跑批**：高德 key 可能配 IP 白名单，"
      "表现为 `INVALID_USER_IP`（10005），重试无效、不会自愈。"
      "探测命令见 SKILL.md §6.7。")
    w("2. **限速**：默认单请求 0.6s、城间 2s、每 100 请求长休 10s。"
      "宁可慢，不可错——错误的空结果比慢更致命。")
    w("3. **全查询面 0 条 = 接口故障**，不得当作「该城无数据」落盘。")
    w("4. **多 key 池**：`keys.txt` 多行，主 key 被拒自动切换，"
      "成功后恢复。")
    w("5. **预算硬闸**：`--budget` 必给，防打爆日配额。")
    w("")
    with open(os.path.join(DATA, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("索引生成：%d 城，POI %d 条，wave2 %d 城" % (done, grand, wave2_done))


if __name__ == "__main__":
    main()
