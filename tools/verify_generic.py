#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用门店 POI 核验器（v0.5.0 新增）。

**为什么需要它**
`verify_poi.py` 是为已产出卡片设计的回灌工具——它的 `QUERY_MAP` 是
「卡片条目号 → 真实店名」的人工映射表，硬编码了武汉/岳阳/恩施三城。
换城市直接 KeyError，导致 SKILL.md §2 把城市模式绑定到一个只有 3 城
能用的工具上。

本脚本按**「名称 + 地址」实时查 POI**，任意城市可用，不需要预置映射。

**用法**
```
# 1) 从候选清单核验（JSON 数组，每项含 name / address 可选）
python tools/verify_generic.py --city 长沙 --items .cache/candidates.json \
       --out .cache/verify_generic.json

# 2) 从标准输入读（每行 "店名|地址"，便于手工喂数据）
printf "费大厨|芙蓉区解放西路\\n" | python tools/verify_generic.py --city 长沙

# 3) 只验证工具是否可用（自检）
python tools/verify_generic.py --city 长沙 --selftest
```

**输入 JSON 格式**
```json
[
  {"name": "费大厨", "address": "芙蓉区解放西路三王街口"},
  {"name": "玉楼东", "address": null}
]
```

**输出标记**（与 SKILL.md §5 Step 4 / §7.2 口径一致）
| 标记 | 含义 |
|---|---|
| ✅A  | 店名匹配 + 门牌一致 + 近 90 天有评价 |
| ✅A- | 店名匹配 + 有评价，但门牌与输入不一致 |
| ✅B  | 店名匹配，但无近 90 天评价（属快照级） |
| ⚠️  | 未命中 / 非餐饮实体 / 跨行政区 |
| ❌  | 明确不是该实体（如命中停车场） |
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_probe import load_token, norm, query_place          # noqa: E402
from snack_verify import is_parent_poi, _lcs_len               # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE, ".cache", "verify")


class QuotaExceeded(RuntimeError):
    """百度 Agent Plan 配额耗尽（status=302）。

    实测（v0.5.0）：一次全国 6 城普查会打掉「近 5 小时」配额，
    之后所有查询返回 `status:302 message:近5小时请求总量超限额`，
    **results 为空但不报错**——上层脚本会误判成「地图未收录」。
    这是最危险的静默失败，必须显式拦截。
    """


def _is_quota_msg(msg):
    return bool(msg) and ("超限额" in msg or "超额" in msg
                          or "quota" in str(msg).lower())

NON_FOOD_CTX = ("停车场", "出入口", "地铁站", "公交站", "卫生间", "楼梯",
                "宗祠", "庙", "寺", "教堂", "陵园", "墓", "学校", "学院",
                "医院", "银行", "公司", "管理处", "委员会", "政府",
                "博物馆", "公园", "广场", "车站", "机场", "小区", "社区")

# 餐饮以外的通用后缀，用于剥离后做前缀匹配
GENERIC_SUFFIX = ("餐厅", "酒楼", "总店", "旗舰店", "分店", "店", "馆")


def _match_score(query, poi_name):
    """名称关联度 0–1。品类名与店名要分开处理。"""
    q, p = norm(query), norm(poi_name)
    if not q or not p:
        return 0.0
    if q in p:
        return 1.0
    if p in q:
        return 0.95
    # 剥离通用后缀后再比
    q2 = q
    for s in GENERIC_SUFFIX:
        if q2.endswith(norm(s)):
            q2 = q2[:-len(norm(s))]
            break
    if q2 and (q2 in p):
        return 0.88
    # 最长公共子串（实测「熊大妈炒码米粉」vs「熊大妈米粉」需靠这个）
    return min(0.8, _lcs_len(query, poi_name) / max(len(query), 1))


def _district_of(addr):
    """粗取地址里的区县名（用于跨区判定）。"""
    m = re.search(r"([\u4e00-\u9fff]{2,6}?(?:区|县|市))", addr or "")
    return m.group(1) if m else ""


def _parse_review_date(text):
    """从评价文本里尝试抽日期，返回 date 或 None。"""
    if not text:
        return None
    m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", str(text))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def verify_one(item, city):
    """核验单条候选。返回可直接落交付物的 dict。"""
    name = (item.get("name") or "").strip()
    addr_in = (item.get("address") or "").strip()
    base = {"input_name": name, "input_address": addr_in,
            "city": city, "checked_at": date.today().isoformat()}

    if not name:
        base.update(mark="⚠️", why="未提供店名，无法核验")
        return base

    d = query_place("帮我找%s%s" % (city, name), city)
    results = d.get("results") or []
    if not results:
        base.update(mark="⚠️", why="地图未收录该名称（可能是流动摊、已关店，"
                                    "或名称为菜品而非店名）")
        return base

    # 取关联度最高的一条
    scored = []
    for r in results:
        rn = r.get("name") or ""
        s = _match_score(name, rn)
        if s > 0:
            scored.append((s, r))
    if not scored:
        top = results[0]
        tn = top.get("name") or ""
        base.update(mark="⚠️",
                    poi={"name": tn, "address": top.get("address")},
                    why="地图返回结果与「%s」无名称关联（最接近的是「%s」），"
                        "疑似名称不符" % (name, tn))
        return base
    scored.sort(key=lambda x: -x[0])
    best_s, best = scored[0]
    pname = best.get("name") or ""
    paddr = best.get("address") or ""
    di = best.get("detail_info") or {}

    # 非餐饮实体
    bad = [k for k in NON_FOOD_CTX if k in pname]
    if bad:
        base.update(mark="❌",
                    poi={"name": pname, "address": paddr},
                    why="命中「%s」，属%s类非餐饮实体" % (pname, bad[0]))
        return base

    # 父级容器（整条街/景区）→ 不可写门牌
    if is_parent_poi(pname):
        base.update(mark="✅B",
                    poi={"name": pname, "address": paddr},
                    why="仅命中父级容器「%s」，无可用门店坐标；"
                        "禁止书写门牌" % pname)
        return base

    # 跨行政区判定
    d_in, d_out = _district_of(addr_in), _district_of(paddr)
    if addr_in and d_in and d_out and d_in != d_out \
            and d_out not in addr_in and d_in not in d_out:
        base.update(mark="⚠️",
                    poi={"name": pname, "address": paddr},
                    why="输入地址在「%s」，POI 落在「%s」，跨区，请确认"
                        % (d_in, d_out))
        return base

    # 评价时效
    reviews = di.get("reviews") or di.get("user_reviews") or []
    latest = None
    for rv in reviews:
        rd = _parse_review_date(rv if isinstance(rv, str) else rv.get("date"))
        if rd and (latest is None or rd > latest):
            latest = rd
    if latest is None:
        cmts = di.get("comment_num") or 0
        base.update(mark="✅B" if best_s >= 0.85 else "⚠️",
                    poi={"name": pname, "address": paddr,
                         "rating": di.get("overall_rating"),
                         "comments": cmts},
                    why=("店名匹配（关联度 %.2f），但无法确认近 90 天有评价；"
                         "属快照级，建议出发前复核" % best_s))
        return base

    age = (date.today() - latest).days
    fresh = age <= 90
    # 门牌一致性
    addr_match = True
    if addr_in:
        n_in, n_out = norm(addr_in), norm(paddr)
        addr_match = (n_in and n_out
                      and (n_in in n_out or n_out in n_in
                           or _lcs_len(addr_in, paddr) >= 6))
    if fresh and addr_match:
        mark = "✅A"
        why = "店名匹配、门牌一致，最近评价 %s（%d 天前）" % (latest, age)
    elif fresh and not addr_match:
        mark = "✅A-"
        why = ("店名匹配且有近 90 天评价（%s），但门牌不一致："
               "输入「%s」/ POI「%s」" % (latest, addr_in or "未填", paddr))
    else:
        mark = "✅B"
        why = ("店名匹配，但最近评价为 %s（%d 天前，超过 90 天），"
               "降为快照级" % (latest, age))

    base.update(mark=mark,
                poi={"name": pname, "address": paddr,
                     "rating": di.get("overall_rating"),
                     "comments": di.get("comment_num"),
                     "hours": di.get("shop_hours"),
                     "latest_review": latest.isoformat()},
                match_score=round(best_s, 2), why=why)
    return base


def _selftest(city):
    """工具可用性自检。"""
    print("[自检] 凭据：%s" % ("已注入" if load_token() else "缺失"))
    d = query_place("帮我找%s市中心的商场" % city, city)
    rs = d.get("results") or []
    print("[自检] 检索「%s市中心商场」返回 %d 条" % (city, len(rs)))
    for r in rs[:3]:
        di = r.get("detail_info") or {}
        print("   · %s | heat=%s | 评分=%s"
              % (r.get("name"), di.get("arrival_heat"),
                 di.get("overall_rating")))
    if not rs:
        print("[自检] 失败：检索无结果，请检查凭据或城市名", file=sys.stderr)
        return 1
    print("[自检] 通过。heat 量纲提醒：不是 0–10，"
          "跨 4 个数量级，判定须用 heat_band()。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="通用门店 POI 核验器")
    ap.add_argument("--city", required=True)
    ap.add_argument("--items", help="候选清单 JSON 数组")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--delay", type=float, default=0.25)
    args = ap.parse_args()

    if args.selftest:
        sys.exit(_selftest(args.city))

    items = []
    if args.items:
        with open(args.items, encoding="utf-8") as f:
            items = json.load(f)
    elif not sys.stdin.isatty():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 1)
            items.append({"name": parts[0].strip(),
                          "address": parts[1].strip() if len(parts) > 1 else ""})
    else:
        ap.error("需要 --items 或从标准输入传入「店名|地址」")

    os.makedirs(CACHE_DIR, exist_ok=True)
    rows = []
    for i, it in enumerate(items, 1):
        print("[%d/%d] %s" % (i, len(items), it.get("name")))
        try:
            rows.append(verify_one(it, args.city))
        except Exception as e:                              # noqa: BLE001
            rows.append({"input_name": it.get("name"), "mark": "⚠️",
                         "why": "查询异常：%s" % e})
        time.sleep(args.delay)

    tally = {}
    for r in rows:
        tally[r.get("mark", "⚠️")] = tally.get(r.get("mark", "⚠️"), 0) + 1
    print("\n汇总：%s" % " / ".join("%s %d" % (k, v)
                                   for k, v in sorted(tally.items())))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"city": args.city,
                       "checked_at": datetime.now().isoformat(timespec="seconds"),
                       "tally": tally, "rows": rows},
                      f, ensure_ascii=False, indent=2)
        print("已写出 → %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())