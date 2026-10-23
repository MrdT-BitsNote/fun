#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_api.py — 将 data/<省>/<市>.md 档案解析为结构化 JSON 数据接口层。

输出（写入 site/ 目录）:
  api/index.json            全国总索引（省 -> 市 -> 轻量 meta + 统计）
  api/stats.json            全站统计
  site/data.json             全国全量单文件（meta/stats/provinces/389 城全量明细/美食榜/商圈榜）
  site/data.md               全国全量单文件 Markdown（目录+32 省索引+389 城档案+附录）
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
import shutil
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
API = os.path.join(SITE, "api")          # 旧散片目录（v0.9.0 起整体退场，构建时清理）
MD_OUT = os.path.join(SITE, "md")        # 旧逐城 md 目录（同上）

# POI 明细表（城市档案的八个数据表）
POI_TABLES = ("food", "xiaocan", "leisure", "kids", "malls", "specialties", "hotels", "assoc")

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


# POI 记录中文键 -> 英文短键（机读友好、体积更小；data.md 仍为中文表头，同源同值）
# 注意各节表头不完全统一：名称列美食节为「店名」、其余节为「名称」；细分/备注/载体类型等归入 sub
def en_poi(x):
    return {
        "mark": x.get("标记", ""),
        "name": x.get("店名") or x.get("名称") or "",
        "sub": x.get("细分") or x.get("备注") or x.get("载体类型") or x.get("来源查询面") or "",
        "type": x.get("类型", ""),
        "rating": num(x.get("评分")),
        "avg": num(x.get("人均")),
        "addr": x.get("地址", ""),
        "img": x.get("image", ""),
    }


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

    # ---------- 全量 cities（POI 记录键名英文化：机读友好 + 体积更小） ----------
    all_cities = []
    for prov, lst in prov_files.items():
        for city, rec in lst:
            ad = rec["adcode"] or city
            out = {k: rec.get(k) for k in (
                "city", "province", "adcode", "poi_total", "waves", "updated",
                "overview", "credibility", "districts", "district_count",
                "queries", "external")}
            for t in POI_TABLES:
                v = rec.get(t)
                if t in ("leisure", "kids"):
                    # 休闲/儿童为 {subcats, list} 包装结构
                    out[t] = {"subcats": (v or {}).get("subcats", {}),
                              "list": [en_poi(x) for x in ((v or {}).get("list") or [])]}
                elif t == "assoc":
                    out[t] = v or []          # 已是英文键结构（district/count/items）
                else:
                    out[t] = [en_poi(x) for x in (v or [])]
            g = {"S": 0, "A": 0, "B": 0, "C": 0}
            for dd in out["districts"]:
                if dd.get("grade") in g:
                    g[dd["grade"]] += 1
            out["grades"] = g
            out["page"] = f"cities/{quote(ad)}.html"
            all_cities.append(out)

    # ---------- 省级汇总 ----------
    prov_summary = {}
    for c in all_cities:
        g = {"S": 0, "A": 0, "B": 0, "C": 0}
        for d in c["districts"]:
            if d.get("grade") in g:
                g[d["grade"]] += 1
        p = prov_summary.setdefault(c["province"],
                                    {"cities": 0, "poi": 0, "districts": 0,
                                     "grades": {"S": 0, "A": 0, "B": 0, "C": 0}})
        p["cities"] += 1
        p["poi"] += c["poi_total"] or 0
        p["districts"] += len(c["districts"])
        for k in ("S", "A", "B", "C"):
            p["grades"][k] += g[k]
    provinces = [{
        "province": prov, "cities": s["cities"], "poi": s["poi"],
        "districts": s["districts"], "grades": s["grades"],
        "page": f"provinces/{quote(prov)}.html",
    } for prov, s in sorted(prov_summary.items())]

    # ---------- 全国美食榜（每城评分前列，带图优先；仅收餐饮业主导 POI） ----------
    # 剔除规则：名称命中住宿关键词，或高德主类型段为「住宿服务」（餐饮仅作次要类型的不算美食）
    LODGING_NAME = re.compile(r"酒店|宾馆|旅馆|招待所|客栈|民宿|度假村|山庄|旅社|客房|公寓|青年旅舍|客舍")

    def _foodish(x):
        t = x.get("type") or ""
        n = x.get("name") or ""
        if "餐饮" not in t:
            return False
        if t.split("｜")[0].strip().startswith("住宿服务"):
            return False
        if LODGING_NAME.search(n):
            return False
        return True

    food_top = []
    for r in all_cities:
        pool = [x for x in r["food"] if x.get("rating") not in (None, "") and _foodish(x)]
        pool.sort(key=lambda x: (-(x["rating"] or 0), -(x["avg"] or 0)))
        picked, withimg = [], 0
        for x in pool:
            has_img = bool(x.get("img"))
            if len(picked) >= 8:
                break
            if withimg >= 3 and not has_img:
                continue
            if has_img:
                withimg += 1
            picked.append({
                "name": x.get("name", ""), "type": x.get("type", ""),
                "rating": x.get("rating"), "avg": x.get("avg"),
                "address": x.get("addr", ""), "image": x.get("img", ""),
                "mark": x.get("mark", ""), "city": r["city"], "province": r["province"],
                "city_page": r["page"],
            })
        food_top.extend(picked)
    food_top.sort(key=lambda x: (-(x["rating"] or 0), x["city"]))
    food_top = food_top[:800]

    # ---------- 全国商圈榜 ----------
    dist_top = []
    for r in all_cities:
        for d in r.get("districts", []):
            if d.get("grade") in ("S", "A"):
                dist_top.append({
                    "name": d["name"], "grade": d["grade"], "carrier": d.get("carrier", ""),
                    "rating": d.get("rating"), "food": d.get("food"), "leisure": d.get("leisure"),
                    "kids": d.get("kids"), "hotel": d.get("hotel"),
                    "city": r["city"], "province": r["province"], "city_page": r["page"],
                })
    dist_top.sort(key=lambda x: (-(x["food"] or 0), -(x["rating"] or 0)))
    dist_top = dist_top[:1000]

    # ---------- 全站统计 ----------
    stats = {
        "provinces": len(prov_summary),
        "cities": len(all_cities),
        "poi_total": sum(c["poi_total"] or 0 for c in all_cities),
        "full_dim_cities": sum(1 for c in all_cities if 3 in (c.get("waves") or [])),
        "districts_total": sum(len(c.get("districts", [])) for c in all_cities),
        "grades": {g: sum(p["grades"][g] for p in prov_summary.values()) for g in ("S", "A", "B", "C")},
        "sources": ["高德地图 Web 服务 POI（restapi.amap.com）", "美团", "大众点评"],
        "site": "https://fun.worldstip.com",
    }

    # ---------- 清理旧散片（可复现：api/ 390+32 文件、md/ 421 文件整体退场） ----------
    shutil.rmtree(API, ignore_errors=True)
    shutil.rmtree(MD_OUT, ignore_errors=True)

    # ---------- 写 site/data.json（全国全量单文件，流式编码省内存） ----------
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    doc = {
        "meta": {
            "name": "FUN 全国美食×商圈×娱乐数据库",
            "version": "v0.9.0",
            "generated": gen,
            "home": "https://fun.worldstip.com",
            "source": "高德地图 Web 服务 POI（restapi.amap.com）+ 美团 + 大众点评",
            "format": "全国全量单文件 JSON；人类可读全量版见 /data.md",
            "files": {"json": "/data.json", "md": "/data.md", "docs": "/api.html"},
            "schema": {
                "meta": "版本/生成时间/数据源说明",
                "stats": "全站统计（省数/城数/POI/商圈/SABC）",
                "provinces": "32 省级汇总 [{province,cities,poi,districts,grades,page}]",
                "cities": "389 城全量 [{city,province,adcode,poi_total,overview,districts,food,xiaocan,leisure,kids,malls,specialties,hotels,assoc,page}]",
                "poi": "POI 记录 {mark,name,sub,type,rating,avg,addr,img}；mark=✅S-/✅A- 等商圈携带标记，sub=细分/备注/载体类型，type 为高德多段类型串（; 分隔，首段为主类）",
                "food_top": "全国美食榜 800 条（已剔除住宿业主导 POI）",
                "districts_top": "全国 S/A 商圈榜 1000 条",
            },
        },
        "stats": stats,
        "provinces": provinces,
        "cities": all_cities,
        "food_top": food_top,
        "districts_top": dist_top,
    }
    out_json = os.path.join(SITE, "data.json")
    with open(out_json, "w", encoding="utf-8") as f:
        for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(doc):
            f.write(chunk)
    jsize = os.path.getsize(out_json)

    # ---------- 写 site/data.md（全国全量单文件 Markdown） ----------
    msize = build_data_md(provinces, all_cities, stats, gen)

    dt = (datetime.now() - t0).total_seconds()
    print(f"[build_api] data.json {jsize/1048576:.1f}MB + data.md {msize/1048576:.1f}MB / "
          f"{len(all_cities)} cities / {len(provinces)} provinces / "
          f"poi={stats['poi_total']} / {dt:.1f}s")


# ================================================================ 全量 Markdown（单文件）

def _rewrite_links(txt):
    """md 源内链改写为 data.md 锚点：](<市>.md) -> ](#<市>)；](../README.md) -> ](#目录)。"""
    txt = re.sub(r"\]\(([^)#:/]+?)\.md\)", r"](#\1)", txt)
    txt = txt.replace("](../README.md)", "](#目录)")
    return txt


def _shift_headings(txt, n):
    """把 md 源内的 ATX 标题整体下沉 n 级（最小 1 级、最大 6 级），
    使城市原文内部的 `## 0. 数据可信度` / `### 商圈 —— 评级 A` 等正确嵌套在省/市标题之下。
    围栏代码块（```）内的 # 行不处理。"""
    out, fence = [], False
    for ln in txt.split("\n"):
        if ln.lstrip().startswith("```"):
            fence = not fence
            out.append(ln)
            continue
        if not fence:
            m = re.match(r"^(#{1,6})(\s+)", ln)
            if m:
                lvl = min(len(m.group(1)) + n, 6)
                ln = "#" * lvl + m.group(2) + ln[m.end():]
        out.append(ln)
    return "\n".join(out)


def _strip_h1(txt):
    """去掉 md 源的一级标题行（合并时由区块自己给出标题）。"""
    return re.sub(r"^# [^\n]*\n", "", txt, count=1)


def build_data_md(provinces, all_cities, stats, gen):
    """全国全量单文件 Markdown：目录 + 全国统计 + 32 省索引 + 389 城档案 + 附录。"""
    by_prov = {}
    for c in all_cities:
        by_prov.setdefault(c["province"], []).append(c["city"])

    parts = []
    w = parts.append
    w("# FUN 全国美食 × 商圈 × 娱乐数据库（全量 Markdown 版）\n\n")
    w(f"> 版本 v0.9.0 · 生成 {gen} · 机器可读全量 JSON：[`/data.json`](/data.json)  \n")
    w("> 数据源：高德地图 Web 服务 POI（restapi.amap.com）+ 美团 + 大众点评  \n")
    w(f"> 覆盖 {stats['provinces']} 个省级行政区 / {stats['cities']} 城 / "
      f"POI 去重 {stats['poi_total']:,} 条 / 商圈 {stats['districts_total']:,} 处\n")

    # 目录（省 -> 城 两级锚点）
    w("\n## 目录\n")
    for p in provinces:
        name = p["province"]
        w(f"- **[{name}](#{name})**（{p['cities']} 城 · POI {p['poi']:,}）")
        cities_of = by_prov.get(name, [])
        # 直辖市：省名即市名，目录里不再重复列一次同名城市
        if not (len(cities_of) == 1 and cities_of[0] == name):
            w(" · ".join(f"[{c}](#{c})" for c in cities_of))
        w("\n")

    # 全国统计
    g = stats["grades"]
    w("\n## 全国统计\n\n")
    w("| 项 | 值 |\n|---|---|\n")
    w(f"| 省级行政区 | {stats['provinces']} |\n")
    w(f"| 已建库城市 | {stats['cities']} |\n")
    w(f"| POI（去重） | {stats['poi_total']:,} |\n")
    w(f"| 商圈档案 | {stats['districts_total']:,} |\n")
    w(f"| 商圈评级 | S {g['S']} · A {g['A']} · B {g['B']} · C {g['C']} |\n")
    w(f"| 全维度城市（wave1+2+3） | {stats['full_dim_cities']} |\n")

    # 省索引 + 城市档案（标题层级下沉 + 内链改锚点）
    # 层级约定：省标题 ## -> 省级索引正文下沉 1 级（## 变 ###）
    #           市标题 ### -> 城市档案正文下沉 2 级（## 变 ####，### 变 #####）
    for prov in sorted(by_prov):
        cities_in_prov = by_prov[prov]
        w(f"\n## {prov}\n")
        src = os.path.join(DATA, prov, prov + ".md")
        # 直辖市只有 1 座城市且与省同名：索引文件即城市档案本身，避免重复收录
        is_single = len(cities_in_prov) == 1 and cities_in_prov[0] == prov
        if os.path.isfile(src) and not is_single:
            body = _shift_headings(_strip_h1(read(src)), 1)
            w(_rewrite_links(body).rstrip() + "\n")
        for city in cities_in_prov:
            src = os.path.join(DATA, prov, city + ".md")
            if not os.path.isfile(src):
                continue
            body = _shift_headings(_strip_h1(read(src)), 2)
            w(f"\n### {city}\n")
            w(_rewrite_links(body).rstrip() + "\n")

    # 附录：接口与来源
    w("\n## 附录 A · 数据接口\n\n")
    w("| 端点 | 格式 | 内容 |\n|---|---|---|\n")
    w("| `/data.json` | JSON | 全国全量单文件：meta / stats / provinces / cities（389 城全量明细）/ food_top / districts_top |\n")
    w("| `/data.md` | Markdown | 本文件：全量人类可读版（目录 + 32 省索引 + 389 城档案） |\n")
    w("\nPOI 记录字段：`mark`（商圈携带标记）/ `name`（店名）/ `type`（高德多段类型串，`;` 分隔，首段为主类）/ "
      "`rating`（评分）/ `avg`（人均）/ `addr`（地址）/ `img`（商家实拍图，无图为空串）。\n")
    w("\n## 附录 B · 数据来源与边界\n\n")
    w("- POI 来自高德地图 Web 服务（restapi.amap.com）文本检索，按城市 + 60 查询面采集，高德 POI id 去重。\n")
    w("- 美食/酒店/特产等维度计数以高德类型串判定；美食榜已剔除酒店/宾馆/旅馆/民宿/客栈/客舍等住宿业主导 POI。\n")
    w("- 无评分条目标记 ⚠️，不做推荐；人均/图片以高德返回为准，缺图为空。\n")
    w("- 数据用于正当的信息聚合与探索参考，不整库转售；引用请标注「高德地图 POI / 美团 / 大众点评」。\n")

    out = os.path.join(SITE, "data.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return os.path.getsize(out)


if __name__ == "__main__":
    main()
