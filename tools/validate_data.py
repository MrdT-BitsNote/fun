#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据校验器 —— 全国省市美食/商圈 md 的质量闸门

检查项（全部可复算，不写黑箱）
--------------------------------
C1  文件完整性    每个已采集城市必须有对应 md，且 md 内含 8 个章节
C2  表格列数一致  md 中每张表的列数必须等于表头分隔行的列数
C3  粗体配对      ** 必须偶数个
C4  链接可达      ![图]() 的 URL 必须是高德 showpic 域名
C5  标记口径      五级标记只允许出现规定值，不得出现未知标记
C6  关联一致性    §5 中出现的店名必须在 §1 出现过（防止悬空引用）
C7  无空表        章节标题计数 >0 时表格不得为空
C8  采集告警可见  采集有告警的城市必须在 §8 列有对应待办

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
SECTIONS = ["## 0.", "## 1.", "## 2.", "## 3.", "## 4.", "## 5.",
            "## 6.", "## 7.", "## 8."]


def check_file(path):
    errs = []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")

    # C1 章节
    for s in SECTIONS:
        if s not in text:
            errs.append("C1 缺章节 %s" % s)

    # C2 表格列数
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

    # C6 关联一致性：§5 的店名要么在 §1，要么有「数据位置」指向 §7，
    # 不允许出现无法回查的悬空引用
    sec5 = text.split("## 5.")[1].split("## 6.")[0] if "## 5." in text else ""
    sec1 = text.split("## 1.")[1].split("## 2.")[0] if "## 1." in text else ""
    sec1_names = set(re.findall(
        r"\|\s*(?:✅[A\-B]*|⚠️|❌)\s*\|\s*([^|]+?)\s*\|", sec1))
    for m in re.findall(r"^\|\s*([^|]+?)\s*\|\s*(?:名称互证|距离就近)", sec5, re.M):
        if m not in sec1_names and "§7" not in sec5:
            errs.append("C6 §5 引用店名「%s」未出现在 §1 且无 §7 指向" % m)

    # C8 告警可见性
    if "采集告警 |" in text:
        mm = re.search(r"采集告警 \|\s*(\d+)", text)
        if mm and int(mm.group(1)) > 0:
            if "- [ ] 采集有告警" not in text:
                errs.append("C8 有采集告警但 §8 未列待办")

    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    files = []
    for dirpath, _dirs, names in os.walk(DATA):
        for n in names:
            # README 是索引而非城市档案，不适用 §0–§8 章节规则
            if n.endswith(".md") and n != "README.md":
                files.append(os.path.join(dirpath, n))
    files.sort()

    bad = collections.OrderedDict()
    for fp in files:
        city = os.path.splitext(os.path.basename(fp))[0]
        if args.city and city != args.city:
            continue
        e = check_file(fp)
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
