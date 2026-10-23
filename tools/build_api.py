#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_api.py — 将 data/<省>/<市>.md 档案解析为结构化 JSON 数据接口层。

输出（写入 site/ 目录）:
  api/index.json            全国总索引（省 -> 市 -> 轻量 meta + 统计）
  api/stats.json            全站统计
  api/cities/index.json     城市轻索引数组（含 html/api/md 三地址）
  api/cities/<adcode>.json  城市全量结构化数据（skill 可直接消费）
  api/provinces/<省>.json   省级汇总
  api/food/top.json         全国美食榜（跨城，按评分）
  api/districts/top.json    全国商圈榜（S/A 级，按关联美食数）
  md/<省>/<市>.md            原始 Markdown 副本（skill 直读源）
  data.json                 兼容旧版的轻量总索引

设计纪律:
  1. 只解析，不改数——JSON 与 md 档案同源同值，任何字段都能在 md 中找到出处。
  2. 空表/缺章不造假：缺失章节记 null 或空数组，绝不填默认值。
  3. 图片字段保留高德原图 URL（store.is.autonavi.com），缺图记 null。
"""
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from urllib.parse import quote

try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE = os.path.join(ROOT, "site")
API = os.path.join(SITE, "api")
MD_OUT = os.path.join(SITE, "md")

# ---------------------------------------------------------------- 基础工具

def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, separators=(",", ": "))


def num(s):
    """'4.7'->4.7 '226.00'->226.0 '—'/''/None->None '21'->21"""
    if s is None:
        return None
    s = str(s).strip()
    if s in ("", "—", "-", "–", "N/A", "暂无"):
        return None
    try:
        f = float(s)
        return int(f) if f == int(f) and "." not in s else f
    except ValueError:
        return None


def clean_cell(s):
    """去掉 markdown 图片/链接语法，返回纯文本"""
    if s is None:
        return ""
    s = re.sub(r"!\[[^\]]*\]\(([^)]*)\)", "", s)  # 图片
    s = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1", s)  # 链接
    return s.strip()


def cell_image(s):
    """提取单元格中的第一张图 URL"""
    if not s:
        return None
    m = re.search(r"!\[[^\]]*\]\(([^)]*)\)", s)
    return m.group(1).strip() if m else None


def sanitize(s):
    """去掉竖线，防止污染 JSON 字符串（防御性）"""
    return str(s).replace("|", "/").strip() if s else ""


def parse_table(lines, i):
    """从 lines[i] 开始解析一个 markdown 表。
    返回 (rows, next_i)。rows 为 dict 列表；非表格返回 ([], i)。"""
    if i >= len(lines) or not lines[i].lstrip().startswith("|"):
        return [], i
    rows = []
    header = None
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        raw = lines[i].strip().strip("|")
        cells = [c.strip() for c in raw.split("|")]
        if header is None:
            header = [sanitize(clean_cell(c)) for c in cells]
        elif all(re.fullmatch(r":?-{2,}:?", c or "---") for c in cells):
            pass  # 分隔行
        else:
            # 对齐到表头长度
            cells += [""] * (len(header) - len(cells))
            rows.append({header[j] or f"col{j}": sanitize(clean_cell(cells[j])) for j in range(len(header))})
        i += 1
    return rows, i


def split_sections(text):
    """按 '## N. ' 切章，返回 {编号: (标题, 章节文本)}"""
    parts = re.split(r"(?m)^(## \d+\. .+)$", text)
    secs = {}
    if parts:
        secs["_head"] = parts[0]
    for k in range(1, len(parts) - 1, 2):
        title = parts[1 + k - 1].strip()
        body = parts[k + 1] if k + 1 < len(parts) else ""
        m = re.match(r"## (\d+)\.", title)
        if m:
            secs[m.group(1)] = (title, body)
    return secs


def first_table_rows(body):
    """章节正文中的第一个表格"""
    lines = body.split("\n")
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("|"):
            rows, _ = parse_table(lines, i)
            if rows:
                return rows
    return []


# ---------------------------------------------------------------- 城市解析

GRADE_RE = re.compile(r"^###\s+(.+?)\s*——\s*评级\s*([SABCD])")


def parse_city_md(path, province):
    text = read(path)
    city = os.path.splitext(os.path.basename(path))[0]
    lines = text.split("\n")
    secs = split_sections(text)

    # ---- 头部元信息
    poi_total = None
    waves = []
    updated = None
    for ln in lines[:8]:
        m = re.search(r"POI 总量：(\d+)", ln)
        if m:
            poi_total = int(m.group(1))
        m = re.search(r"查询波次：([\d+]+)", ln)
        if m:
            waves = [int(x) for x in m.group(1).split("+") if x.isdigit()]
        m = re.search(r"采集时间：([\d\-: ]+)", ln)
        if m:
            updated = m.group(1).strip()

    out = {
        "city": city,
        "province": province,
        "poi_total": poi_total,
        "waves": waves,
        "updated": updated,
    }

    # ---- §0 数据可信度
    cred = {}
    if "0" in secs:
        for r in first_table_rows(secs["0"][1]):
            k = r.get("项", "")
            v = r.get("值", "")
            if k == "POI 总数（去重）":
                cred["poi_total"] = num(v)
            elif k == "有评分的比例":
                cred["rated_ratio"] = v
            elif k == "维度覆盖":
                dims = {}
                for mm in re.finditer(r"([一-龥]+)\s+(\d+)", v):
                    dims[mm.group(1)] = int(mm.group(2))
                cred["dims"] = dims
            elif k == "采集告警":
                cred["warnings"] = num(v) or 0
    out["credibility"] = cred

    # ---- §1 总览
    ov = {}
    if "1" in secs:
        body = secs["1"][1]
        # 1.1 行政层级
        admin = {}
        dist_poi = []
        carriers = []
        sub = re.split(r"(?m)^(### .+)$", body)
        for k in range(1, len(sub) - 1, 2):
            head = sub[k].strip()
            subbody = sub[k + 1]
            if "行政层级" in head:
                for r in first_table_rows(subbody):
                    admin[r.get("项", "")] = r.get("值", "")
            elif "业态分布" in head or "商圈" in head:
                rows = []
                for r in first_table_rows(subbody):
                    rows.append({
                        "district": r.get("区县", ""),
                        "poi": num(r.get("POI 数")),
                        "ratio": r.get("占比", ""),
                    })
                if rows:
                    dist_poi = rows
                # 载体类型表（第二张）
                allrows = []
                sl = subbody.split("\n")
                seen = 0
                for i, ln in enumerate(sl):
                    if ln.lstrip().startswith("|"):
                        rr, _ = parse_table(sl, i)
                        if rr:
                            allrows.append(rr)
                if len(allrows) >= 2:
                    carriers = [{"type": r.get("载体类型", ""), "count": num(r.get("数量"))} for r in allrows[1]]
        ov["admin"] = admin
        ov["district_poi"] = dist_poi
        ov["carrier_types"] = carriers
    out["overview"] = ov

    # ---- §2 商圈档案
    districts = []
    if "2" in secs:
        title, body = secs["2"]
        blines = body.split("\n")
        # 顺序扫描：主表 + 详情块，每张表只解析一次
        tables = []
        i = 0
        while i < len(blines):
            if blines[i].lstrip().startswith("|"):
                rr, nxt = parse_table(blines, i)
                if rr:
                    tables.append(rr)
                i = nxt
            else:
                i += 1
        main = None
        for t in tables:
            if t and "商圈名" in t[0]:
                main = t
                break
        # 详情块：### name —— 评级 X 之后的 bullet + 业态表
        detail_blocks = {}
        cur = None
        j = 0
        while j < len(blines):
            ln = blines[j]
            gm = GRADE_RE.match(ln.strip())
            if gm:
                cur = gm.group(1).strip()
                detail_blocks[cur] = {"grade": gm.group(2), "fields": {}, "mixes": []}
                j += 1
                continue
            if cur is not None:
                blk = detail_blocks[cur]
                s = ln.strip()
                if s.startswith("- **"):
                    mm = re.match(r"- \*\*(.+?)\*\*：(.+)", s)
                    if mm:
                        blk["fields"][mm.group(1)] = mm.group(2).strip()
                elif s.startswith("| 业态"):
                    rr, nxt = parse_table(blines, j)
                    blk["mixes"] = [{"type": r.get("业态", ""), "count": num(r.get("家数")),
                                     "top": [x.strip() for x in r.get("代表（按评分）", "").split("、") if x.strip()]}
                                    for r in rr]
                    j = nxt
                    continue
            j += 1
        if main:
            for r in main:
                name = r.get("商圈名", "")
                d = {
                    "name": name,
                    "grade": r.get("评级", ""),
                    "carrier": r.get("载体类型", ""),
                    "rating": num(r.get("评分")),
                    "food": num(r.get("关联美食")),
                    "leisure": num(r.get("休闲娱乐")),
                    "kids": num(r.get("儿童娱乐")),
                    "hotel": num(r.get("酒店")),
                }
                blk = detail_blocks.get(name)
                if blk:
                    f = blk["fields"]
                    d["detail"] = {
                        "criteria": f.get("评级判据", ""),
                        "address": f.get("地址", ""),
                        "bandwidth": f.get("消费带宽", ""),
                        "axis": f.get("动线主轴", ""),
                        "mixes": blk["mixes"],
                    }
                districts.append(d)
    out["districts"] = districts
    out["district_count"] = len(districts)

    # ---- §3~§8 §10 列表类章节
    def list_section(no):
        """返回 (子类统计, 明细列表)。同一张表只解析一次。"""
        if no not in secs:
            return [], []
        body = secs[no][1]
        blines = body.split("\n")
        tables = []
        i = 0
        while i < len(blines):
            if blines[i].lstrip().startswith("|"):
                rr, nxt = parse_table(blines, i)
                if rr:
                    tables.append((blines, rr))
                i = nxt
            else:
                i += 1
        subcats, rows = [], []
        for _, t in tables:
            if t and "子类" in t[0] and "家数" in t[0]:
                subcats = [{"name": r.get("子类", ""), "count": num(r.get("家数"))} for r in t]
            elif t:
                rows = t
        # 图片列：从原始行提取 URL
        for r in rows:
            if "图片" in r:
                nm = r.get("店名") or r.get("名称", "")
                for ln in blines:
                    if nm and nm[:6] in ln and "![" in ln:
                        r["image"] = cell_image(ln)
                        break
                else:
                    r["image"] = None
                del r["图片"]
        return subcats, rows

    sub_leisure, leisure = list_section("3")
    out["leisure"] = {"subcats": sub_leisure, "list": leisure}
    sub_kids, kids = list_section("4")
    out["kids"] = {"subcats": sub_kids, "list": kids}
    out["malls"] = list_section("5")[1]
    out["food"] = list_section("6")[1]
    out["xiaocan"] = list_section("7")[1]
    out["specialties"] = list_section("8")[1]
    out["hotels"] = list_section("10")[1]

    # ---- §9 美食×商圈关联
    assoc = []
    if "9" in secs:
        body = secs["9"][1]
        blocks = re.split(r"(?m)^### (.+?)（(\d+)\s*家）\s*$", body)
        for k in range(1, len(blocks) - 1, 3):
            name = blocks[k].strip()
            cnt = int(blocks[k + 1])
            blines = blocks[k + 2].split("\n")
            items = []
            for i, ln in enumerate(blines):
                if ln.lstrip().startswith("|") and "店名" in ln:
                    rr, _ = parse_table(blines, i)
                    items = [{"name": r.get("店名", ""), "how": r.get("关联方式", ""),
                              "dist": r.get("直线距离", ""), "rating": num(r.get("评分")),
                              "src": r.get("数据位置", "")} for r in rr[:120]]
                    break
            assoc.append({"district": name, "count": cnt, "items": items})
    out["assoc"] = assoc

    # ---- §11 原始查询面（轻量：维度统计）
    queries = []
    if "11" in secs:
        for r in first_table_rows(secs["11"][1]):
            if r.get("维度") and r.get("查询面"):
                queries.append({"dim": r.get("维度"), "query": r.get("查询面"), "hits": num(r.get("命中"))})
    out["queries"] = queries

    # ---- 外部数据源链接（美团 / 大众点评）
    py = lazy_pinyin(city) if lazy_pinyin else None
    dianping_slug = "".join(py) if py else ""
    # 点评城市频道 slug 不带「市」：岳阳市 -> yueyang；县/州/盟保持全拼
    if city.endswith("市") and dianping_slug.endswith("shi"):
        dianping_slug = dianping_slug[:-3]
    out["external"] = {
        "meituan_search": "https://www.meituan.com/s/" + quote(f"{city}美食"),
        "meituan_home": "https://www.meituan.com/",
        "dianping_food": f"https://www.dianping.com/{dianping_slug}/ch10" if dianping_slug else "https://www.dianping.com/",
        "dianping_search": f"https://www.dianping.com/search/keyword/2/0_{quote(city)}",
    }
    return out


# ---------------------------------------------------------------- 主流程

def main():
    t0 = datetime.now()
    status = {}
    stpath = os.path.join(DATA, "_status.tsv")
    adcodes = {}
    if os.path.exists(stpath):
        with open(stpath, encoding="utf-8") as f:
            header = f.readline()
            for ln in f:
                p = ln.rstrip("\n").split("\t")
                if len(p) >= 4:
                    adcodes[(p[0], p[1])] = p[2]

    cities = []
    prov_files = {}
    for prov in sorted(os.listdir(DATA)):
        pdir = os.path.join(DATA, prov)
        if not os.path.isdir(pdir):
            continue
        for fn in sorted(os.listdir(pdir)):
            if not fn.endswith(".md"):
                continue
            city = fn[:-3]
            # 省级索引/说明文件首行含「索引」，非城市档案；直辖市城市文件名与省同名，须保留
            with open(os.path.join(pdir, fn), encoding="utf-8") as fh:
                first = fh.readline()
            if "索引" in first:
                continue
            rec = parse_city_md(os.path.join(pdir, fn), prov)
            rec["adcode"] = adcodes.get((prov, city), "")
            prov_files.setdefault(prov, []).append((city, rec))

    # 逐城写 JSON + 复制 md
    for prov, lst in prov_files.items():
        for city, rec in lst:
            ad = rec["adcode"] or city
            rec["urls"] = {
                "page": f"cities/{quote(ad)}.html",
                "json": f"api/cities/{ad}.json",
                "md": f"md/{quote(prov)}/{quote(city)}.md",
            }
            write_json(os.path.join(API, "cities", f"{ad}.json"), rec)
            # md 副本
            mdd = os.path.join(MD_OUT, prov)
            os.makedirs(mdd, exist_ok=True)
            src = os.path.join(DATA, prov, city + ".md")
            dst = os.path.join(mdd, city + ".md")
            if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
                with open(src, encoding="utf-8") as a, open(dst, "w", encoding="utf-8") as b:
                    b.write(a.read())
            cities.append(rec)

    # 城市轻索引
    light = []
    for r in cities:
        dims = r.get("credibility", {}).get("dims", {})
        grades = {"S": 0, "A": 0, "B": 0, "C": 0}
        for d in r.get("districts", []):
            g = d.get("grade")
            if g in grades:
                grades[g] += 1
        light.append({
            "city": r["city"], "province": r["province"], "adcode": r["adcode"],
            "poi": r.get("poi_total"), "waves": r.get("waves"), "updated": r.get("updated"),
            "page": r["urls"]["page"], "json": r["urls"]["json"], "md": r["urls"]["md"],
            "grades": grades,
            "dims": {"food": dims.get("美食", 0), "district": dims.get("商圈", 0),
                     "leisure": dims.get("休闲娱乐", 0), "kids": dims.get("儿童娱乐", 0),
                     "hotel": dims.get("酒店", 0), "product": dims.get("特产", 0)},
        })
    write_json(os.path.join(API, "cities", "index.json"), {
        "count": len(light), "cities": light,
    })

    # 全国总索引 + 省级汇总
    prov_summary = {}
    for r in light:
        p = prov_summary.setdefault(r["province"], {"cities": 0, "poi": 0, "grades": {"S": 0, "A": 0, "B": 0, "C": 0}})
        p["cities"] += 1
        p["poi"] += r["poi"] or 0
        for g in ("S", "A", "B", "C"):
            p["grades"][g] += r["grades"][g]
    for prov, lst in prov_files.items():
        s = prov_summary.get(prov, {"cities": 0, "poi": 0, "grades": {}})
        write_json(os.path.join(API, "provinces", f"{prov}.json"), {
            "province": prov,
            "stats": s,
            "cities": [c for c in light if c["province"] == prov],
        })
    write_json(os.path.join(API, "index.json"), {
        "name": "FUN 全国美食×商圈×娱乐数据库",
        "home": "https://fun.worldstip.com",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provinces": len(prov_summary),
        "cities": len(light),
        "poi_total": sum(c["poi"] or 0 for c in light),
        "province_index": {k: {"cities": v["cities"], "poi": v["poi"], "grades": v["grades"]}
                           for k, v in sorted(prov_summary.items())},
        "city_index": light,
    })

    # 全国美食榜（每城取评分前列，带图优先；仅收餐饮类，防酒店/娱乐混入）
    food_top = []
    for r in cities:
        pool = [x for x in r.get("food", [])
                if x.get("评分") not in (None, "") and "餐饮" in (x.get("类型") or "")]
        pool.sort(key=lambda x: (-(num(x.get("评分")) or 0), -(num(x.get("人均")) or 0)))
        picked, withimg = [], 0
        for x in pool:
            has_img = bool(x.get("image"))
            if len(picked) >= 8:
                break
            if withimg >= 3 and not has_img:
                continue
            if has_img:
                withimg += 1
            picked.append({
                "name": x.get("店名", ""), "type": x.get("类型", ""), "rating": num(x.get("评分")),
                "avg": num(x.get("人均")), "address": x.get("地址", ""), "image": x.get("image"),
                "mark": x.get("标记", ""), "city": r["city"], "province": r["province"],
                "city_page": r["urls"]["page"],
            })
        food_top.extend(picked)
    food_top.sort(key=lambda x: (-(x["rating"] or 0), x["city"]))
    food_top = food_top[:800]
    write_json(os.path.join(API, "food", "top.json"), {
        "note": "按高德评分排序；每人每城最多 8 家，优先带图。字段含城市与城市页地址，可直接跳转。",
        "count": len(food_top), "items": food_top,
    })

    # 全国商圈榜
    dist_top = []
    for r in cities:
        for d in r.get("districts", []):
            if d.get("grade") in ("S", "A"):
                dist_top.append({
                    "name": d["name"], "grade": d["grade"], "carrier": d.get("carrier", ""),
                    "rating": d.get("rating"), "food": d.get("food"), "leisure": d.get("leisure"),
                    "kids": d.get("kids"), "hotel": d.get("hotel"),
                    "city": r["city"], "province": r["province"], "city_page": r["urls"]["page"],
                })
    dist_top.sort(key=lambda x: (-(x["food"] or 0), -(x["rating"] or 0)))
    write_json(os.path.join(API, "districts", "top.json"), {
        "note": "S/A 级商圈，按关联美食数降序。",
        "count": len(dist_top), "items": dist_top[:1000],
    })

    # 全站统计
    write_json(os.path.join(API, "stats.json"), {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provinces": len(prov_summary),
        "cities": len(light),
        "poi_total": sum(c["poi"] or 0 for c in light),
        "full_dim_cities": sum(1 for c in light if 3 in (c.get("waves") or [])),
        "districts_total": sum(len(r.get("districts", [])) for r in cities),
        "grades": {g: sum(c["grades"][g] for c in light) for g in ("S", "A", "B", "C")},
        "sources": ["高德地图 Web 服务 POI（restapi.amap.com）", "美团", "大众点评"],
        "site": "https://fun.worldstip.com",
    })

    # 兼容旧版 data.json
    write_json(os.path.join(SITE, "data.json"), {
        "generated_by": "build_api.py",
        "source": "高德地图 Web 服务 POI",
        "skill": "local-food-explorer v0.8.0",
        "cities_total": len(light),
        "cities_built": len(light),
        "cities_full_dims": sum(1 for c in light if 3 in (c.get("waves") or [])),
        "poi_total": sum(c["poi"] or 0 for c in light),
        "cities": [{"city": c["city"], "province": c["province"], "adcode": c["adcode"],
                    "poi": c["poi"], "waves": c["waves"], "updated": c["updated"],
                    "url": c["page"]} for c in light],
    })

    dt = (datetime.now() - t0).total_seconds()
    print(f"[build_api] {len(light)} cities / {len(prov_summary)} provinces / "
          f"poi={sum(c['poi'] or 0 for c in light)} / {dt:.1f}s")


if __name__ == "__main__":
    main()
