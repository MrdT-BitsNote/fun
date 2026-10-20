#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
小吃档交叉核验器：文本线索 → POI 验证 → 归入可信档位

要解决的问题
------------
用户反馈：「汴河街南门入口有顶糕和小笼汤包，这两个就是汴河街的传统小吃，
是没有记录的，但味道真的很好。」

实测确认这个反馈是对的，而且比想象的更普遍：

- 「顶糕」——地图检索**只能返回汴河街整条街**，没有任何顶糕摊位 POI。
  它是流动担子摊，只在文本攻略里出现（本地宝、搜狐、网易多篇提到）。
- 「咕咕拌粉」「肉蛋堡」「无名卤菜摊」——同样无 POI，但多条本地攻略
  明确给出位置与人均。

因此**传统小吃必须与门店条目分层呈现**，且核验方式不同：

| 档 | 来源 | 能写什么 | 不能写什么 |
|---|---|---|---|
| ✅A | 百度 POI 实时核验到具体门店 | 门牌、营业时间、评分、评价数 | — |
| ✅B | POI 命中但坐标落在**父级 POI**（如只命中「汴河街」） | 名称、所在街区、品类 | **不能写门牌**，只能写「街区内，具体摊位见现场」 |
| ✅C | 纯文本多源交叉（≥2 个独立来源提到，且位置描述一致） | 名称、街区、品类、口味描述、价格区间（取交集） | 不能写门牌、营业时间 |
| ⚠️ | 仅 1 个文本来源，或来源冲突 | 名称、街区 | 位置、价格均需标注「待现场确认」 |
| ❌ | POI 命中但跨区 / 名称完全不符 | — | 剔除 |

**实测踩坑**：文本线索「何氏手工姜糖」→ POI 返回「何氏宗祠（平江县）」。
品牌词相同但完全不是同一家——因此 ✅B 档必须做**跨区校验**与
**品类校验**（宗祠不是店）。

用法
----
    python tools/snack_verify.py --city 岳阳市 \\
        --items .cache/snack_items.json --out .cache/snack_verify.json
"""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_probe import _regions_in, norm                        # noqa: E402
from district_scan import query_place                             # noqa: E402

# 品类合理性：文本线索是「吃的」，POI 命中的却是祠堂/学校/公园 → 误配
NON_FOOD_CTX = ("宗祠", "庙", "寺", "教堂", "陵园", "墓", "学校", "学院",
                "医院", "银行", "公司", "管理处", "委员会", "政府",
                "博物馆", "公园", "广场", "车站", "机场", "小区", "社区")

# 品类名（小吃品项而非店铺名）。这类线索**本来就不该期待门店 POI**——
# 地图会返回品类词最相关但语义无关的条目。实测「糖油粑粑」→ 返回
# 「人人菜馆(巴陵广场店)」，被误判为跨品类误配而剔除。正确处理是
# 承认它没有独立坐标，走 ✅B（街区内品类，位置见现场）。
CATEGORY_ONLY = ("糖油粑粑", "臭豆腐", "擂茶", "姜糖", "顶糕", "仙豆糕",
                 "三大炮", "糖画", "锅盔", "油粑粑", "麻花", "凉粉",
                 "炸炸", "肉蛋堡", "卤菜", "豆腐脑", "豆浆", "米豆腐")


def is_category_name(name):
    """线索是否为「品类名」而非「店名」。"""
    n = name.strip()
    for c in CATEGORY_ONLY:
        if c in n:
            return True
    return False


# 父级 POI 判定：只有当 POI 名**本身就是**街/景区/广场这类容器，
# 且不含任何店铺性成分时，才算「只命中父级」。
# 实测 bug：首版用 `any(k in pname ...)`，导致
#   「巴陵汤包店(汴河街店)」「食尚坊·家宴(美食街店)」「陈大锅(步行街店)」
# 这类**精确命中的门店**因为店名里带「街」字被误判为父级 POI。
# 正确做法：容器词必须出现在**店名的主干**（括号前）或整名无店铺特征。
PARENT_KW = ("步行街", "商业街", "美食街", "小吃城", "老街", "景区",
             "公园", "广场", "步行", "商业街", "街区", "夜市")
SHOP_FEATURE = ("店", "馆", "坊", "轩", "居", "堂", "阁", "摊", "铺",
                "餐", "吧", "厅", "城", "园", "楼", "社", "食", "味",
                "香", "鲜", "美", "乐", "家", "婆", "哥", "姐", "弟",
                "妈", "爸", "爷", "奶", "王", "记", "师", "炮", "粉", "面",
                "鱼", "肉", "鸡", "鸭", "牛", "羊", "虾", "蟹")
# 街巷类后缀：专名街（汴河街、得胜南路）不带「步行街」等通用词，
# 但同样是**容器**——地图只能返回整条街，没有摊位坐标。
STREET_SUFFIX = ("街", "巷", "弄", "胡同")


def _lcs_len(a, b):
    """最长公共子串长度（用于名称相似度放宽判断）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def is_parent_poi(pname):
    """判断 POI 是否只是父级容器（而非具体店铺）。

    判据按优先级：
    1. 括号前的主体以**容器词或街巷后缀收尾** → 容器
       （汴河街 / 步行街 / 美食街 / 巴陵广场）
    2. 主体含容器词但**不带店铺特征** → 容器
    3. 其余（主体含店铺特征）→ 具体门店
    """
    head = re.split(r"[（(]", pname)[0].strip()
    if not head:
        return False

    container_tail = (r"(步行街|商业街|美食街|小吃城|老街|景区|公园|广场|"
                      r"步行|街区|夜市|商业步行)$")
    if re.search(container_tail, head) or head.endswith(STREET_SUFFIX):
        return True

    has_shop = any(k in head for k in SHOP_FEATURE)
    has_parent = any(k in head for k in PARENT_KW)
    if has_shop:
        return False
    return has_parent


def verify(item, city):
    """对一条小吃线索做 POI 核验，返回档位判定。"""
    q = item.get("q") or item["name"]
    d = query_place("帮我找%s的%s" % (city, q), city)
    res = d.get("results") or []

    base = {
        "name": item["name"],
        "district": item.get("district"),
        "text_sources": item.get("sources", []),
        "text_note": item.get("note"),
        "poi_query": "帮我找%s的%s" % (city, q),
    }

    if not res:
        if len(item.get("sources", [])) >= 2:
            base.update(mark="✅C", poi=None,
                        why="地图无 POI（流动摊/未收录），但 %d 个独立文本来源交叉提及"
                            % len(item["sources"]),
                        forbid="无门牌、无营业时间")
        else:
            base.update(mark="⚠️", poi=None,
                        why="地图无 POI，且仅 1 个文本来源",
                        forbid="位置与价格均待现场确认")
        return base

    p = res[0]
    di = p.get("detail_info") or {}
    pname = p.get("name") or ""
    paddr = p.get("address") or ""

    # 误配 1：跨区
    mine = _regions_in(item.get("district") or "")
    theirs = _regions_in(paddr)
    clash = [r for r in theirs if r not in mine and mine]
    if clash:
        base.update(mark="❌", poi={"name": pname, "address": paddr},
                    why="POI 命中「%s」（%s），与目标街区 %s 跨区不符，判定为同名误配"
                        % (pname, "/".join(clash), "/".join(mine)))
        return base

    # 误配 2：品类不符（要吃的却命中祠堂/学校/公园）
    hit_ctx = [k for k in NON_FOOD_CTX if k in pname]
    cat_only = is_category_name(item["name"])
    if hit_ctx and not cat_only:
        base.update(mark="❌", poi={"name": pname, "address": paddr},
                    why="POI 命中「%s」，属%s类非餐饮实体，判定为词面误配"
                        % (pname, hit_ctx[0]))
        return base

    # 误配 3：判档优先级
    #   ① POI 与线索有词面关联 + 独立地址（商铺号/门牌）→ ✅A
    #   ② POI 仅为父级容器（整条街）→ ✅B
    #   ③ POI 与线索无词面关联（品类词/名称不同）→ 按文本来源数定 ✅B/⚠️
    # 实测修正：首版把「品类名」规则放在最前，导致「三大炮(岳阳店)」
    # （汴河街83号商铺、评分5.0）被误压成 ⚠️。品类降级只在
    # **POI 与线索无词面关联**时才成立。
    parent = is_parent_poi(pname)
    exact = norm(q) and norm(q) in norm(pname)
    # 线索核心词（去掉括注）是否出现在 POI 名中。
    # 实测：线索名常带修饰（「熊大妈**炒码**米粉」vs POI「熊大妈米粉」），
    # 直接全串比对会漏。因此先用最长公共子串放宽到 ≥3 字即视为关联。
    core = re.sub(r"[（(].*?[)）]", "", item["name"]).strip()
    core = re.split(r"[·、，]", core)[0]
    linked = bool(core) and (norm(core) in norm(pname))
    if not linked and core:
        cn, pn = norm(core), norm(pname)
        linked = _lcs_len(cn, pn) >= 3
    # 独立地址判定：**只判断地址是否存在**，不判容器性。
    # 实测 bug：首版对地址也跑 is_parent_poi，导致
    # 「熊大妈米粉」的地址写着「东茅岭街道步行街得胜南路东方红小学正对面…」
    # 被判为容器地址而降级。地址里出现街名是**正常现象**（店确实开在街上），
    # 真正的容器判据只应作用于 POI 名。
    addr_ok = bool(paddr)

    if linked and addr_ok and not parent:
        base.update(mark="✅A", poi={"name": pname, "address": paddr,
                                    "rating": di.get("overall_rating"),
                                    "comments": di.get("comment_num"),
                                    "hours": di.get("shop_hours")},
                    why="POI 精确命中门店「%s」" % pname)
        # 名称相似度：POI 名与文本线索名差异大时提示核对
        a, b = norm(item["name"]), norm(pname)
        if a not in b and b not in a:
            base["name_mismatch"] = True
            base["mark_note"] = ("线索名为「%s」，POI 名为「%s」，请核对是否同一家"
                                 % (item["name"], pname))
        return base

    if parent or not linked:
        src = len(item.get("sources", []))
        if src >= 2:
            base.update(mark="✅B", poi={"name": pname, "address": paddr},
                        why="地图无该摊位独立坐标（返回「%s」为语义相关条目，"
                            "不作门店定位）；%d 个文本来源交叉提及" % (pname, src),
                        forbid="不可写门牌，只能写「%s」内，具体摊位见现场"
                               % item.get("district", "该街区"))
        else:
            base.update(mark="⚠️", poi={"name": pname, "address": paddr},
                        why="地图无该摊位独立坐标，且仅 1 个文本来源",
                        forbid="位置与价格均待现场确认")
        return base

    if parent and not exact:
        base.update(mark="✅B", poi={"name": pname, "address": paddr,
                                    "rating": di.get("overall_rating"),
                                    "comments": di.get("comment_num")},
                    why="POI 仅命中父级「%s」，无独立摊位坐标" % pname,
                    forbid="不可写门牌，只能写「%s」内，具体摊位见现场"
                           % item.get("district", "该街区"))
    else:
        base.update(mark="✅A", poi={"name": pname, "address": paddr,
                                    "rating": di.get("overall_rating"),
                                    "comments": di.get("comment_num"),
                                    "hours": di.get("shop_hours")},
                    why="POI 精确命中门店")

    # 名称相似度：POI 名与文本线索名差异大时提示核对
    if base["mark"] == "✅A":
        a, b = norm(item["name"]), norm(pname)
        if a not in b and b not in a:
            base["name_mismatch"] = True
            base["mark_note"] = ("线索名为「%s」，POI 名为「%s」，请核对是否同一家"
                                 % (item["name"], pname))
    return base


def main():
    ap = argparse.ArgumentParser(description="小吃档交叉核验器")
    ap.add_argument("--city", default="岳阳市")
    ap.add_argument("--items", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.items, encoding="utf-8") as f:
        items = json.load(f)

    print("核验 %d 条小吃线索（并发 4）……" % len(items))
    out = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(lambda it: verify(it, args.city), items):
            out.append(r)
            print("  %s %-16s %s" % (r["mark"], r["name"][:15], r["why"][:64]))

    cnt = {}
    for r in out:
        cnt[r["mark"]] = cnt.get(r["mark"], 0) + 1
    print("-" * 60)
    print("档位统计：%s" % "　".join("%s %d" % (k, cnt[k])
                                  for k in sorted(cnt)))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"city": args.city, "rows": out}, f, ensure_ascii=False, indent=2)
    print("已写入 %s" % args.out)


if __name__ == "__main__":
    main()