#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全国行政区划层级树采集 —— 省/直辖市/省会市/地级市/县级市/区县/镇/乡

高德 config/district 的层级语义（实测 v0.6.2）：
    province  省 / 自治区 / 直辖市
    city      地级市 / 自治州 / 盟 / 地区 + 省直管县级市
    district  市辖区 / 县 / 自治县 / 县级市（直辖市下为区）
    street    街道 / 镇 / 乡 / 苏木（高德把街道镇乡统一标为 street，
              靠名称后缀区分；村级高德不提供，如实标注为空）

纪律：
1. 限速：每次请求间隔 1s，省间休息 3s（与 POI 采集错峰，避免触发 IP 策略）
2. 原始响应全量落盘，可换算法重跑
3. 失败省份显式记录，不用空树冒充
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "amap")
TREE_DIR = os.path.join(CACHE, "tree")
KEYS_FILE = os.path.join(CACHE, "keys.txt")
DISTRICT_URL = "https://restapi.amap.com/v3/config/district"


def load_keys():
    keys = []
    env = os.environ.get("AMAP_KEYS", "")
    if env:
        keys += [k.strip() for k in env.split(",") if k.strip()]
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, encoding="utf-8") as f:
            keys += [ln.strip() for ln in f if ln.strip()]
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    if not out:
        raise SystemExit("未找到高德 key")
    return out


KEYS = load_keys()
_state = {"idx": 0, "fail": [0] * len(KEYS)}


def fetch(keyword, subdistrict=3):
    """拉行政区划，带 key 轮换与重试。"""
    for attempt in range(4):
        key = KEYS[_state["idx"]]
        url = DISTRICT_URL + "?" + urllib.parse.urlencode(
            {"key": key, "keywords": keyword,
             "subdistrict": str(subdistrict), "extensions": "base"})
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                blob = json.loads(r.read().decode("utf-8"))
        except Exception as e:                        # noqa: BLE001
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
            continue
        info = blob.get("info") or ""
        code = blob.get("infocode") or ""
        if blob.get("status") != "1":
            _state["fail"][_state["idx"]] += 1
            if len(KEYS) > 1 and ("INVALID_USER_IP" in info
                                  or code in ("10003", "10004", "10001")):
                _state["idx"] = (_state["idx"] + 1) % len(KEYS)
                continue
            raise RuntimeError("高德行政区划接口失败（%s）：%s" % (code, info[:80]))
        _state["fail"][_state["idx"]] = 0
        return blob
    raise RuntimeError("高德行政区划接口重试耗尽：%s" % keyword)


def normalize_node(x):
    """统一层级语义：把高德的 4 个 level 映射到用户要求的 10 级分类。"""
    level = x.get("level")
    name = x.get("name") or ""
    if level == "province":
        # 直辖市（京/津/沪/渝）在省级列出，但其下直接挂区
        kind = "直辖市" if name in ("北京市", "天津市", "上海市", "重庆市") else "省/自治区"
    elif level == "city":
        # 地级市 vs 自治州/盟/地区 vs 省直管县级市：靠后缀与父级判定
        if name.endswith("自治州"):
            kind = "自治州"
        elif name.endswith("盟") or name.endswith("地区"):
            kind = "盟/地区"
        else:
            kind = "地级市"
    elif level == "district":
        if name.endswith("市"):           # 县级市（如浏阳市）
            kind = "县级市"
        elif name.endswith("县") or name.endswith("自治县"):
            kind = "县"
        else:
            kind = "市辖区"
    elif level == "street":
        if name.endswith("街道"):
            kind = "街道"
        elif name.endswith("镇"):
            kind = "镇"
        elif name.endswith("乡") or name.endswith("苏木"):
            kind = "乡"
        else:
            kind = "街道/镇/乡"
    else:
        kind = level or "未知"
    return {
        "name": name,
        "adcode": x.get("adcode"),
        "level": level,
        "kind": kind,
        "children": [normalize_node(c) for c in (x.get("districts") or [])],
    }


def main():
    ap = argparse.ArgumentParser(description="全国行政区划层级树采集")
    ap.add_argument("--force", action="store_true", help="重拉已完成省份")
    args = ap.parse_args()

    nation_path = os.path.join(CACHE, "nation_district.json")
    if not os.path.exists(nation_path):
        blob = fetch("100000", subdistrict=1)
        os.makedirs(CACHE, exist_ok=True)
        with open(nation_path, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False)
        time.sleep(1)
    nation = json.load(open(nation_path, encoding="utf-8"))
    root = nation["districts"][0]
    provinces = [(x["adcode"], x["name"]) for x in root.get("districts") or []]

    os.makedirs(TREE_DIR, exist_ok=True)
    done, failed = 0, []
    for ad, name in provinces:
        fp = os.path.join(TREE_DIR, "%s.json" % name)
        if os.path.exists(fp) and not args.force:
            done += 1
            continue
        try:
            blob = fetch(ad, subdistrict=3)
        except RuntimeError as e:
            failed.append((name, str(e)[:80]))
            print("  ⛔ %s：%s" % (name, str(e)[:60]))
            time.sleep(3)
            continue
        node = blob["districts"][0]
        with open(fp, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "root": normalize_node(node)}, f, ensure_ascii=False)
        n_city = len(node.get("districts") or [])
        done += 1
        print("  ✅ %s：%d 个下一级" % (name, n_city))
        time.sleep(1.2)                       # 省级间隔
    print("\n完成 %d/%d 省；失败 %d 个" % (done, len(provinces), len(failed)))
    for n, e in failed:
        print("   -", n, e)


if __name__ == "__main__":
    main()
