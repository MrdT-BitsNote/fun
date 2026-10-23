#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全国索引生成器 —— data/README.md + data/_status.tsv

产出：
  data/README.md        全国总索引：省 → 市 的可点击目录、各省 POI 统计、
                       全国维度汇总、数据使用与校对入口
  data/_status.tsv       机读进度表：省/市/adcode/POI数/查询面/告警

README 是给人看的入口，_status.tsv 是给脚本/校对工具读的。
"""

import json
import os

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
    prov_lines = []
    for pname, v in provs.items():
        cities = v.get("cities") or []
        tot, cnt, errs = 0, 0, 0
        lines = []
        for ad, cname, lvl in cities:
            cache = load(cname)
            if cache is None:
                lines.append("  - %s —— ⏳ 未采集" % cname)
                continue
            n, qn = city_stats(cache)
            bad = len(cache.get("errors") or [])
            tot += n
            cnt += 1
            errs += bad
            flag = "⚠️" if bad else "✅"
            lines.append("  - %s [%s](%s.md) —— %d POI / %d 查询面"
                         % (flag, cname, cname, n, qn))
            rows.append((pname, cname, ad, n, qn, bad))
        grand += tot
        if cnt:
            prov_lines.append(
                "| [%s](%s/%s.md) | %s | %d | %d | %d |" % (
                    pname, pname, pname, v["adcode"], len(cities), cnt, tot))
        prov_lines.append("")
        prov_lines.append("<details><summary>展开 %s 各市</summary>" % pname)
        prov_lines.append("")
        prov_lines.extend(lines)
        prov_lines.append("")
        prov_lines.append("</details>")
        prov_lines.append("")

    with open(os.path.join(DATA, "_status.tsv"), "w", encoding="utf-8") as f:
        f.write("省\t市\tadcode\tPOI数\t查询面数\t告警数\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")

    done = len(rows)
    md = []
    w = md.append
    w("# 全国美食 × 商圈 数据总索引")
    w("")
    w("> 本目录是「本地美食探索」skill 的数据层。")
    w("> 每个地级市一份 md，含 8 个章节：可信度 / 本地美食 / 苍蝇馆 / "
      "特产 / 商圈 / 美食×商圈关联 / 商圈儿童游乐 / 原始数据与校对。")
    w(">")
    w("> 数据源：高德地图 Web 服务 POI（restapi.amap.com），"
      "采集工具 `tools/amap_collect.py`，渲染 `tools/render_md.py`，"
      "校验 `tools/validate_data.py`。")
    w("")
    w("## 进度")
    w("")
    w("| 省 | adcode | 城市数 | 已采集 | POI 合计 |")
    w("|---|---|---|---|---|")
    for line in prov_lines:
        if line.startswith("| ["):
            w(line)
    w("")
    w("**全国合计：%d / 390 城已建库，POI 共 %d 条（去重后）。**" % (done, grand))
    w("")
    w("## 各省目录")
    w("")
    for line in prov_lines:
        if not line.startswith("| [") and line.strip():
            w(line)
    w("")
    w("## ⚠️ 当前阻塞：高德 key IP 白名单")
    w("")
    w("本批建库进行到 51 城（34,426 POI）时，高德 key 开始对所有城市返回")
    w("`INVALID_USER_IP`（infocode 10005）——这是 key 配置的 **IP 白名单**")
    w("限制，不是限流、不会自愈、重试无效。剩余约 339 城未采集。")
    w("")
    w("**解除步骤**：登录高德开放平台控制台 → 应用管理 → 该 key 的")
    w("「IP 白名单」设置 → 加入当前出口 IP（或清空白名单）→")
    w("重新跑 `python tools/amap_collect.py --all --budget <上限>`。")
    w("脚本会跳过已采城市（progress.json），只补未采部分。")
    w("")
    w("## 维度定义")
    w("")
    w("| 维度 | 章节 | 高德依据 |")
    w("|---|---|---|")
    w("| 本地美食 / 特色美食 | §1 | 050100 中餐厅 / 050108 湘菜 / "
      "050118 地方风味 + 关键词 特色美食/本地菜/老字号 |")
    w("| 苍蝇馆 / 小店 | §2 | 关键词 苍蝇馆 + 店名小店语义（小馆/排挡/"
      "家常/私房/土菜/大排档）|")
    w("| 知名特产 | §3 | 关键词 特产/土特产/地方特产 + 0607 类 |")
    w("| 商业街 / 购物 / 美食街 | §4 | 061001 步行街 / 061000 特色商业街 / "
      "060101 购物中心 / 060100 商场 + 关键词 美食街/夜市/小吃街 |")
    w("| 酒吧 / 酒馆 / LIVEHOUSE | §4 §5 | 080304 酒吧 + 关键词 酒馆/livehouse |")
    w("| 美食 × 商圈关联 | §5 | 名称互证 + 距离就近（≤600m 同区县）|")
    w("| 商圈儿童游乐 / 电玩 / 迷你游乐场 | §6 | 关键词 儿童乐园/电玩城/"
      "游乐场/淘气堡/亲子乐园 + 0805 休闲场所，区分 场内/独立 载体 |")
    w("")
    w("## 校对入口")
    w("")
    w("1. 打开任一城市 md 的 **§8 校对待办**，那是机器已识别的问题清单。")
    w("2. 全量机器校验：`python tools/validate_data.py`（8 项规则，"
      "含表格列数、粗体配对、悬空引用）。")
    w("3. 补采单城：`python tools/amap_collect.py --city XX市`，"
      "**注意预算**（单城约 48–50 请求）。")
    w("4. 重渲染：`python tools/render_md.py --all`。")
    w("")
    w("## 数据口径与已知边界")
    w("")
    w("- **评分**取高德 `biz_ext.rating`，无人工干预；无评分者一律 ⚠️，"
      "不做无据推荐。")
    w("- **人均**取高德 `biz_ext.cost`，单位元，可能滞后于实际涨价。")
    w("- **图片**取高德店铺图 URL，仅供校对时肉眼确认门店真实性。")
    w("- **苍蝇馆不做无据判定**：小店语义 + 评分区间双条件，"
      "宁可漏列也不编造。")
    w("- **关联为机器初判**：仅靠距离的关联必须人工确认，"
      "防止景区边界、跨街区误配。")
    w("- **撤柜风险**：§6 场内儿童游乐的撤柜率高，"
      "去之前需二次确认营业状态。")
    w("")
    with open(os.path.join(DATA, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("索引生成：%d 城，POI %d 条" % (done, grand))


if __name__ == "__main__":
    main()
