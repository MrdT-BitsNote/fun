#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
行政区划层级构建器 —— 把高德 34 省树整理为用户要求的 10 级分类体系

分类口径（v0.6.2）
--------------------------------------------------------------------
省 / 自治区 / 直辖市
  └─ 直辖市（京/津/沪/渝）——高德在直辖市下多一层「XX城区 / XX郊县」
     中间节点（level=city 且非真实行政单元），构建时折叠掉。
  └─ 省会市 / 地级市 / 自治州 / 盟 / 地区（高德 level=city）
  └─ 省直辖县级市（如河南济源、湖北仙桃/天门/潜江，高德挂在省级下）
县 / 县级市 / 市辖区 / 自治县（高德 level=district）
街道 / 镇 / 乡 / 苏木 / 类似乡级单位（高德 level=street）
  └─ 类似乡级单位：国营农场、林场、牧场、开发区、管委会等
     （高德 street 级共 40,842 个，其中 1,085 个不属于标准街道镇乡）

村级：高德行政区划接口不提供村一级数据，如实标注为空，不编造。

输出
----
.cache/amap/hierarchy.json     机读全量树（供网站/其他 skill 调用）
data/行政层级总览.md           人读总览：各级数量、分省明细、口径说明
.cache/amap/city_districts.json 市 → 下级区县映射（供城市卡片注入）
"""

import argparse
import collections
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "amap")
TREE_DIR = os.path.join(CACHE, "tree")
DATA = os.path.join(ROOT, "data")

# 台湾省辖 20 个行政单元的真实口径（公开行政区划事实）：
# 6 直辖市 + 3 市 + 11 县
TW_MUNICIPAL = {"台北市", "新北市", "桃园市", "台中市", "台南市", "高雄市"}
TW_CITY = {"基隆市", "新竹市", "嘉义市"}

# 类似乡级单位关键词（高德 street 级里的非标准行政单元）
QUASI_TOWNSHIP = ("农场", "林场", "牧场", "畜场", "种场", "殖场", "渔场",
                  "开发区", "发区", "园区", "业局", "营所", "理区", "理处",
                  "管委会", "公司", "马场", "盐场", "良种场", "实验中心")

KIND_ORDER = ["省/自治区", "直辖市", "特别行政区", "省会市", "地级市",
              "自治州", "盟/地区", "县级市", "直辖市辖区", "市辖区", "县",
              "自治县", "街道", "镇", "乡", "类似乡级单位"]

FOLD = "（直辖市中间层·折叠）"     # 内部标记，不出现在输出

PROV_CAPITAL = {
    "河北省": "石家庄市", "山西省": "太原市", "辽宁省": "沈阳市",
    "吉林省": "长春市", "黑龙江省": "哈尔滨市", "江苏省": "南京市",
    "浙江省": "杭州市", "安徽省": "合肥市", "福建省": "福州市",
    "江西省": "南昌市", "山东省": "济南市", "河南省": "郑州市",
    "湖北省": "武汉市", "湖南省": "长沙市", "广东省": "广州市",
    "海南省": "海口市", "四川省": "成都市", "贵州省": "贵阳市",
    "云南省": "昆明市", "陕西省": "西安市", "甘肃省": "兰州市",
    "青海省": "西宁市", 
    "广西壮族自治区": "南宁市", "内蒙古自治区": "呼和浩特市",
    "宁夏回族自治区": "银川市", "新疆维吾尔自治区": "乌鲁木齐市",
    "西藏自治区": "拉萨市",
}


def is_quasi(name):
    return any(k in name for k in QUASI_TOWNSHIP)


def street_kind(name):
    if name.endswith("街道"):
        return "街道"
    if name.endswith("镇"):
        return "镇"
    if name.endswith("乡") or name.endswith("苏木") or name.endswith("民族乡"):
        return "乡"
    if is_quasi(name):
        return "类似乡级单位"
    return "街道/镇/乡"


def classify_city(name, parent_name):
    """地级单元细分：省会市 / 地级市 / 自治州 / 盟 / 地区 / 县级市。"""
    if name.endswith("自治州"):
        return "自治州"
    if name.endswith("盟") or name.endswith("地区"):
        return "盟/地区"
    if PROV_CAPITAL.get(parent_name) == name:
        return "省会市"
    return "地级市"


def classify_tw_city(name):
    if name in TW_MUNICIPAL:
        return "直辖市"
    if name in TW_CITY:
        return "市"
    return "县"


def kind_of(name, level, prov_name, in_tw=False):
    """单纯分类：返回该节点的用户口径层级名，不含建树逻辑。"""
    if prov_name in ("北京市", "天津市", "上海市", "重庆市"):
        if level == "city" and (name.endswith("城区") or name.endswith("郊县")):
            return FOLD                       # 直辖市中间层，折叠
        if level == "province":
            return "直辖市"
        if level == "district":
            return "直辖市辖区"
        if level == "street":
            return street_kind(name)
        return level or "未知"
    if in_tw and level == "city":
        return classify_tw_city(name)
    if level == "province":
        if name in ("北京市", "天津市", "上海市", "重庆市"):
            return "直辖市"
        if name.endswith("特别行政区"):
            return "特别行政区"
        return "省/自治区"
    if level == "city":
        return classify_city(name, prov_name or "")
    if level == "district":
        if name.endswith("市"):
            return "县级市"
        if name.endswith("自治县"):
            return "自治县"
        if name.endswith("县"):
            return "县"
        return "市辖区"
    if level == "street":
        return street_kind(name)
    return level or "未知"


def build_node(x, prov_name=None, in_tw=False):
    """建树；直辖市中间层在此折叠：其子节点直接挂到父级。"""
    name = x["name"]
    level = x.get("level")
    kind = kind_of(name, level, prov_name, in_tw)
    node = {"name": name, "adcode": x.get("adcode"), "level": level,
            "kind": kind, "children": []}
    in_tw_c = in_tw or prov_name == "台湾省"
    for c in x.get("children") or []:
        ckind = kind_of(c["name"], c.get("level"), prov_name, in_tw_c)
        if ckind == FOLD:
            # 折叠「XX城区 / XX郊县」：孙节点（区县）直接挂上来
            for gc in c.get("children") or []:
                node["children"].append(build_node(gc, prov_name, in_tw_c))
        else:
            node["children"].append(build_node(c, prov_name, in_tw_c))
    return node


def flatten(node, out=None, depth=0):
    if out is None:
        out = []
    out.append((depth, node["name"], node["kind"], node["adcode"]))
    for c in node["children"]:
        flatten(c, out, depth + 1)
    return out


def main():
    ap = argparse.ArgumentParser(description="构建全国行政层级")
    ap.add_argument("--md", action="store_true", help="同时输出 md 总览")
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(TREE_DIR) if f.endswith(".json"))
    tree, city_districts = {}, {}
    for f in files:
        prov = f[:-5]
        raw = json.load(open(os.path.join(TREE_DIR, f), encoding="utf-8"))
        node = build_node(raw["root"], prov)
        tree[prov] = node

    # 市 → 下级区县映射（供城市卡片注入）
    for prov, pnode in tree.items():
        for c in pnode["children"]:
            if c["kind"] in ("省会市", "地级市", "自治州", "盟/地区",
                             "直辖市", "市", "县") or c["level"] == "city":
                districts = []
                for d in c["children"]:
                    towns = collections.Counter(
                        t["kind"] for t in d["children"])
                    districts.append({
                        "name": d["name"], "kind": d["kind"],
                        "adcode": d["adcode"],
                        "townships": dict(towns),
                        "township_total": sum(towns.values()),
                    })
                city_districts[c["name"]] = {
                    "province": prov,
                    "kind": c["kind"],
                    "adcode": c["adcode"],
                    "districts": districts,
                }

    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, "hierarchy.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "kinds": KIND_ORDER,
                   "note": "村级数据高德不提供，未编造",
                   "provinces": tree}, fh, ensure_ascii=False)
    with open(os.path.join(CACHE, "city_districts.json"), "w",
              encoding="utf-8") as fh:
        json.dump(city_districts, fh, ensure_ascii=False)

    # 统计
    cnt = collections.Counter()
    for prov, pnode in tree.items():
        for _d, _n, kind, _a in flatten(pnode):
            cnt[kind] += 1
    print("=== 全国行政层级统计（v0.6.2 口径）===")
    for k in KIND_ORDER:
        if cnt.get(k):
            print("  %-14s %6d" % (k, cnt[k]))
    other = {k: v for k, v in cnt.items() if k not in KIND_ORDER}
    if other:
        print("  其他口径:", other)
    print("  合计节点:", sum(cnt.values()))
    print("  覆盖市级单元:", len(city_districts))

    if args.md:
        write_md(tree, cnt, city_districts)


def write_md(tree, cnt, city_districts):
    os.makedirs(DATA, exist_ok=True)
    L = []
    w = L.append
    w("# 全国行政层级总览")
    w("")
    w("> 数据来源：高德行政区划接口（config/district, subdistrict=3），"
      "采集时间 %s。" % time.strftime("%Y-%m-%d"))
    w("> 口径说明见文末。**村级数据高德不提供，本文档不含村级，亦未编造。**")
    w("")
    w("## 1. 各级数量")
    w("")
    w("| 层级 | 数量 | 说明 |")
    w("|---|---|---|")
    desc = {
        "省/自治区": "23 个省 + 5 个自治区 + 台湾省（高德口径）",
        "直辖市": "北京 / 天津 / 上海 / 重庆（已折叠高德中间层）",
        "省会市": "27 个省会/自治区首府",
        "地级市": "非省会的地级市",
        "自治州": "30 个民族自治州",
        "盟/地区": "内蒙古盟 + 地区",
        "县级市": "省直辖县级市 + 地级市代管县级市",
        "直辖市辖区": "京津沪渝直辖的区/县",
        "市辖区": "地级市市辖区",
        "县": "县",
        "自治县": "民族自治县",
        "街道": "城市基层行政单元",
        "镇": "建制镇",
        "乡": "乡 / 苏木 / 民族乡",
        "类似乡级单位": "国营农场、林场、牧场、开发区、管委会等",
    }
    for k in KIND_ORDER:
        if cnt.get(k):
            w("| %s | %s | %s |" % (k, format(cnt[k], ","),
                                     desc.get(k, "")))
    w("")
    w("合计 **%s** 个行政节点。" % format(sum(cnt.values()), ","))
    w("")
    w("## 2. 分省结构")
    w("")
    w("| 省/直辖市 | 下一级单元数 | 区县数 | 街道/镇/乡数 | 类似乡级单位 |")
    w("|---|---|---|---|---|")
    for prov in sorted(tree):
        pnode = tree[prov]
        kids = pnode["children"]
        n_kid = len(kids)
        n_dis = sum(len(c["children"]) for c in kids)
        n_tw = n_quasi = 0
        for c in kids:
            for d in c["children"]:
                for t in d["children"]:
                    if t["kind"] == "类似乡级单位":
                        n_quasi += 1
                    else:
                        n_tw += 1
        w("| %s | %d | %d | %s | %s |" % (
            prov, n_kid, n_dis, format(n_tw, ","),
            format(n_quasi, ",") if n_quasi else "—"))
    w("")
    w("## 3. 层级定义与口径")
    w("")
    w("| 用户口径 | 本库对应 | 依据 |")
    w("|---|---|---|")
    w("| 省 | 省/自治区 | 高德 level=province |")
    w("| 直辖市 | 直辖市（折叠高德「XX城区/郊县」中间层） | 京/津/沪/渝 |")
    w("| 省会市 | 省会市 | 省人民政府驻地 |")
    w("| 地级市 | 地级市 / 自治州 / 盟 / 地区 | 高德 level=city |")
    w("| 县级市 | 县级市 | 高德 level=district 且名称为「市」结尾 |")
    w("| 区县级 | 市辖区 / 县 / 自治县 | 高德 level=district |")
    w("| 县级 | 县 | 同上 |")
    w("| 镇 | 镇 | 高德 level=street 且「镇」结尾 |")
    w("| 乡 | 乡 / 苏木 / 民族乡 | 高德 level=street 且「乡」结尾 |")
    w("| 村 | **不提供** | 高德无村级数据，未编造 |")
    w("")
    w("## 4. 市级单元清单（%d 个）" % len(city_districts))
    w("")
    w("| 市级单元 | 所属省 | 类型 | 下级区县数 | 区县清单 |")
    w("|---|---|---|---|---|")
    for cname in sorted(city_districts,
                        key=lambda c: (city_districts[c]["province"], c)):
        v = city_districts[cname]
        ds = "、".join(d["name"] for d in v["districts"])
        if len(ds) > 60:
            ds = ds[:60] + "…"
        w("| %s | %s | %s | %d | %s |" % (
            cname, v["province"], v["kind"], len(v["districts"]), ds))
    w("")
    w("---")
    w("")
    w("## 口径备注")
    w("")
    w("1. **台湾省**：高德列出 20 个行政单元，与公开行政区划一致"
      "（6 直辖市 + 3 市 + 11 县），本文按此口径标注。")
    w("2. **香港/澳门**：高德分别列出 18 / 8 个区级单元，无下级。")
    w("3. **类似乡级单位**：高德 street 级共 40,842 个，其中 1,085 个为"
      "国营农场、林场、牧场、开发区、管委会等非标准行政单元，"
      "已单列，未混入街道/镇/乡统计。")
    w("4. **村级缺失**：高德行政区划接口不下探到村。村镇级 POI 可通过"
      "POI 搜索的 citylimit + 关键词覆盖，但无权威村名录，不编造。")
    w("5. **直辖市中间层**：高德在直辖市下挂「XX城区 / XX郊县」节点，"
      "非真实行政单元，构建时已折叠，其区县直接归直辖市。")
    fp = os.path.join(DATA, "行政层级总览.md")
    with open(fp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n已写入 %s（%d 行）" % (fp, len(L)))


if __name__ == "__main__":
    main()
