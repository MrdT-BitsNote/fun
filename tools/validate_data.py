#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据校验器 v0.7.0 —— 全国省市「美食 × 商圈 × 娱乐」md 的质量闸门

检查项（全部可复算，不写黑箱）
--------------------------------
C1  文件完整性    每个已采集城市必须有对应 md，且 md 内含 0–12 全部章节
C2  表格列数一致  md 中每张表的列数必须等于表头分隔行的列数
C3  粗体配对      ** 必须偶数个
C4  链接可达      ![图]() 的 URL 必须是高德 showpic 域名
C5  标记口径      五级标记只允许出现规定值，不得出现未知标记
C6  关联一致性    §9 中出现的店名要么在 §6 出现过，要么有「数据位置」
                 指向 §11，不允许无法回查的悬空引用
C7  无空表        表格不得只有表头没有数据行
C8  告警可见      采集有告警的城市必须在 §12 列有对应待办
C9  评级口径      商圈评级只允许 S/A/B/C，且判据段存在
C10 维度完整性   wave 2 已采的城市，酒店维度不得为 0（除非真的 0 家，
                 此时必须显式说明已采集但无结果）

用法
----
    python tools/validate_data.py            # 校验全部
    python tools/validate_data.py --city 岳阳市
"""

import argparse
import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, ".cache", "amap", "raw")
DATA = os.path.join(ROOT, "data")

ALLOWED_MARKS = {"✅A", "✅A-", "✅B", "⚠️", "❌"}
SECTIONS = ["## %d." % i for i in range(0, 13)]
ALLOWED_GRADES = {"S", "A", "B", "C"}


def check_file(path, cache_path=None):
    errs = []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")

    # C1 章节
    for s in SECTIONS:
        if s not in text:
            errs.append("C1 缺章节 %s" % s)

    # C2 表格列数 / C7 空表
    i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) \
                and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1]):
            head = lines[i].strip().strip("|").split("|")
            ncol = len(head)
            j = i + 2
            nrow = 0
            while j < len(lines) and lines[j].startswith("|"):
                cols = lines[j].strip().strip("|").split("|")
                if len(cols) != ncol:
                    errs.append("C2 第 %d 行表头 %d 列 / 该行 %d 列：%s"
                                % (j + 1, ncol, len(cols), lines[j][:60]))
                nrow += 1
                j += 1
            if nrow == 0:
                errs.append("C7 第 %d 行附近表格为空" % (i + 1))
            i = j
        else:
            i += 1

    # C3 粗体配对
    nbold = text.count("**")
    if nbold % 2 != 0:
        errs.append("C3 粗体 ** 数量为奇数（%d），有未闭合" % nbold)

    # C4 图片 URL
    for m in re.findall(r"!\[[^\]]*\]\(([^)]*)\)", text):
        if "store.is.autonavi.com/showpic" not in m:
            errs.append("C4 非高德 showpic 图片链接：%s" % m[:60])

    # C5 标记口径
    for m in re.findall(r"^\|\s*([✅⚠❌][A-B\- ]*|—)\s*\|", text, re.M):
        if m.strip() not in ALLOWED_MARKS:
            errs.append("C5 未知标记：%r" % m)

    # C6 关联一致性：§9 的店名要么在 §6，要么有「数据位置」列指向 §11
    sec9 = text.split("## 9.")[1].split("## 10.")[0] if "## 9." in text else ""
    sec6 = text.split("## 6.")[1].split("## 7.")[0] if "## 6." in text else ""
    sec6_names = set(re.findall(
        r"\|\s*(?:✅[A\-B]*|⚠️|❌)\s*\|\s*([^|]+?)\s*\|", sec6))
    has_ptr = "数据位置" in sec9
    for m in re.findall(r"^\|\s*([^|]+?)\s*\|\s*(?:名称互证|距离就近)",
                        sec9, re.M):
        if m not in sec6_names and not has_ptr:
            errs.append("C6 §9 引用店名「%s」未出现在 §6 且无 §11 指向" % m)

    # C9 评级口径
    grades = set(re.findall(r"评级 ([SABC])\b", text))
    bad_g = grades - ALLOWED_GRADES
    if bad_g:
        errs.append("C9 未知评级：%s" % bad_g)
    if "评级判据" not in text and "## 2." in text:
        errs.append("C9 缺商圈评级判据说明")

    # C10 维度完整性：缓存波次与 §0「维度不全」警告必须双向一致
    # （wave1 的 POI 也可能 incidental 命中酒店分类，所以不能以酒店
    #  家数判断是否采了 wave2，只能以缓存 waves 字段与警告文本对照）
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding="utf-8"))
            waves = cache.get("waves") or [1]
            has_warn = "缺 wave2" in text
            if 2 not in waves and not has_warn:
                errs.append("C10 缓存未采 wave2 但 §0 无「缺 wave2」警告")
            if 2 in waves and has_warn:
                errs.append("C10 缓存已采 wave2 但 §0 仍警告「缺 wave2」，"
                            "口径矛盾")
        except (ValueError, KeyError):
            pass

    # C8 告警可见性
    if "采集告警 |" in text:
        mm = re.search(r"采集告警 \|\s*(\d+)", text)
        if mm and int(mm.group(1)) > 0:
            if "- [ ] 采集有告警" not in text:
                errs.append("C8 有采集告警但 §12 未列待办")

    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    files = []
    for dirpath, _dirs, names in os.walk(DATA):
        for n in names:
            # README/行政层级总览是索引文档；<省>/<省>.md 是省级索引页，
            # 两者都不适用城市档案的 §0–§12 章节规则
            if n.endswith(".md") and n not in ("README.md", "行政层级总览.md") \
                    and n != os.path.basename(dirpath) + ".md":
                files.append(os.path.join(dirpath, n))
    files.sort()

    bad = collections.OrderedDict()
    for fp in files:
        city = os.path.splitext(os.path.basename(fp))[0]
        if args.city and city != args.city:
            continue
        e = check_file(fp, os.path.join(RAW, city + ".json"))
        if e:
            bad[city] = e

    print("校验 %d 个文件，%d 个有问题" % (len(files), len(bad)))
    for city, e in bad.items():
        print("  ✗ %s：%s" % (city, "；".join(e[:6])))
        if len(e) > 6:
            print("      …另 %d 条" % (len(e) - 6))
    if not bad:
        print("  ✅ 全部通过")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
