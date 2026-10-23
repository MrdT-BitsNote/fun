#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
route_audit.py — FUN 站点全量路线核查（链接 / 锚点 / 接口 / 同步性）

核查面:
  R1  HTML 页面内 href/src 路线（相对/绝对/锚点/外链分类，逐一落盘校验）
  R2  meta refresh 跳转目标
  R3  canonical 链接目标
  R4  sitemap.xml 全部 URL
  R5  全量数据文件结构核查（data.json 的 cities/provinces/food_top/districts_top
      内嵌 page/city_page 路线 + 统计自洽 + 外链形态）
  R6  孤儿文件核查（cities/ 与 provinces/ 下不对应任何城市的残留页）
  R7  data.json ↔ data.md 同源同值核查（覆盖对齐 + 逐城 8 项数值重解析比对 + md 内锚点可达）
  R8  robots.txt / _headers / CNAME 存在性

用法: python tools/route_audit.py [--site site]
退出码: 0 = 全部通过, 1 = 存在断线
"""
import json
import os
import re
import sys
import tempfile
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_SCHEMES = ("http://", "https://", "//", "data:", "mailto:", "tel:", "javascript:", "about:")


class LinkGrabber(HTMLParser):
    """抓取 href/src/refresh/canonical，带行号。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []      # (line, kind, value)
        self.ids = set()     # 本页锚点 id/name
        self._line = 1

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("a", "link", "area"):
            if "href" in a:
                self.links.append((self.getpos()[0], "href", a["href"]))
            if tag == "link" and a.get("rel") == "canonical" and "href" in a:
                self.links.append((self.getpos()[0], "canonical", a["href"]))
        elif tag in ("img", "script", "iframe", "source", "video", "audio"):
            if "src" in a:
                self.links.append((self.getpos()[0], "src", a["src"]))
        elif tag == "meta":
            if a.get("http-equiv", "").lower() == "refresh" and "content" in a:
                m = re.search(r"url\s*=\s*(.+)$", a["content"], re.I)
                if m:
                    self.links.append((self.getpos()[0], "refresh", m.group(1).strip()))
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and "name" in a:
            self.ids.add(a["name"])


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def classify(url, page_path, site_root):
    """返回 (类别, 站点内绝对路径 or None)。
    类别: external / anchor / internal / empty
    """
    u = url.strip()
    if not u:
        return "empty", None
    if u.startswith(SKIP_SCHEMES):
        return "external", None
    if u.startswith("#"):
        return "anchor", None
    # 去掉 query/fragment 后解析
    path_part = u.split("#", 1)[0].split("?", 1)[0]
    if not path_part:
        return "empty", None
    if path_part.startswith("/"):
        target = os.path.join(site_root, unquote(path_part).lstrip("/"))
    else:
        target = os.path.join(os.path.dirname(page_path), unquote(path_part))
    return "internal", os.path.normpath(target)


def audit_html(site_root, problems, stats):
    html_files = []
    for dirpath, dirnames, filenames in os.walk(site_root):
        if "assets" in dirpath:
            continue
        for fn in filenames:
            if fn.endswith(".html"):
                html_files.append(os.path.join(dirpath, fn))
    html_files.sort()
    stats["html_files"] = len(html_files)

    id_cache = {}
    for hp in html_files:
        rel = os.path.relpath(hp, site_root)
        text = read(hp)
        g = LinkGrabber()
        g.feed(text)
        if hp not in id_cache:
            id_cache[hp] = g.ids
        for line, kind, val in g.links:
            cat, target = classify(val, hp, site_root)
            if cat == "external" or cat == "empty":
                stats[f"skip_{cat}"] = stats.get(f"skip_{cat}", 0) + 1
                continue
            if cat == "anchor":
                if val[1:] and val[1:] not in id_cache[hp]:
                    problems.append(f"[R1 断锚点] {rel}:{line} #{val[1:]} 在本页不存在")
                continue
            # internal
            stats["checked_internal"] = stats.get("checked_internal", 0) + 1
            if not os.path.isfile(target):
                problems.append(f"[R1 断链] {rel}:{line} <{kind}> {val} -> 缺失 {os.path.relpath(target, site_root)}")
                continue
            # 目标为 html 时校验锚点
            if "#" in val and target.endswith(".html"):
                if target not in id_cache:
                    g2 = LinkGrabber()
                    g2.feed(read(target))
                    id_cache[target] = g2.ids
                frag = val.split("#", 1)[1]
                if frag and frag not in id_cache[target]:
                    problems.append(f"[R1 跨页断锚点] {rel}:{line} {val} -> 目标页无 #{frag}")
    return html_files


def audit_sitemap(site_root, problems, stats):
    sp = os.path.join(site_root, "sitemap.xml")
    if not os.path.isfile(sp):
        problems.append("[R4] sitemap.xml 缺失")
        return
    base = "https://fun.worldstip.com"
    locs = re.findall(r"<loc>(.*?)</loc>", read(sp))
    stats["sitemap_urls"] = len(locs)
    for u in locs:
        if u.startswith(base):
            path = unquote(u[len(base):])
        else:
            path = unquote(u)
        if path.endswith("/"):
            path += "index.html"
        target = os.path.join(site_root, path.lstrip("/"))
        if not os.path.isfile(target):
            problems.append(f"[R4 sitemap 断链] {u} -> 缺失 {path}")


def _load(site_root, name):
    p = os.path.join(site_root, name)
    if not os.path.isfile(p):
        return None
    return json.loads(read(p))


def audit_json_routes(site_root, problems, stats):
    """R5 全量 data.json：内嵌路线落盘 + 聚合统计自洽 + 外链形态。"""
    checked = 0

    def chk(field, url, ctx):
        nonlocal checked
        if not url:
            return
        checked += 1
        cat, target = classify(url, os.path.join(site_root, "x.html"), site_root)
        if cat == "external":
            return
        if target and not os.path.isfile(target):
            problems.append(f"[R5 全量数据断链] {ctx} {field}={url} -> 缺失")

    d = _load(site_root, "data.json")
    if d is None:
        problems.append("[R5] data.json 缺失")
        return

    cities = d.get("cities") or []
    provs = d.get("provinces") or []
    st = d.get("stats") or {}
    stats["data_cities"] = len(cities)
    stats["data_provinces"] = len(provs)

    # ① 内嵌路线
    for c in cities:
        chk("page", c.get("page"), f"cities[{c.get('city')}]")
    for pv in provs:
        chk("page", pv.get("page"), f"provinces[{pv.get('province')}]")
    for it in d.get("food_top") or []:
        chk("city_page", it.get("city_page"), f"food_top[{it.get('name')}]")
    for it in d.get("districts_top") or []:
        chk("city_page", it.get("city_page"), f"districts_top[{it.get('name')}]")

    # ② 顶层结构与聚合自洽
    for k in ("meta", "stats", "provinces", "cities", "food_top", "districts_top"):
        if k not in d:
            problems.append(f"[R5] data.json 缺顶层键: {k}")
    if st.get("cities") != len(cities):
        problems.append(f"[R5] stats.cities={st.get('cities')} 与 cities 实际 {len(cities)} 不符")
    if st.get("provinces") != len(provs):
        problems.append(f"[R5] stats.provinces={st.get('provinces')} 与 provinces 实际 {len(provs)} 不符")
    if sum(c.get("poi_total") or 0 for c in cities) != st.get("poi_total"):
        problems.append(f"[R5] stats.poi_total={st.get('poi_total')} 与逐城求和不符")
    if sum(c.get("district_count") or 0 for c in cities) != st.get("districts_total"):
        problems.append(f"[R5] stats.districts_total={st.get('districts_total')} 与逐城商圈数求和不符")
    for g in ("S", "A", "B", "C"):
        if sum((c.get("grades") or {}).get(g, 0) for c in cities) != (st.get("grades") or {}).get(g):
            problems.append(f"[R5] stats.grades.{g} 与逐城求和不符")
    # 省级汇总 vs 城市明细
    acc_poi, acc_city, acc_dist = {}, {}, {}
    for c in cities:
        pv = c.get("province")
        acc_city[pv] = acc_city.get(pv, 0) + 1
        acc_poi[pv] = acc_poi.get(pv, 0) + (c.get("poi_total") or 0)
        acc_dist[pv] = acc_dist.get(pv, 0) + (c.get("district_count") or 0)
    for pv in provs:
        n = pv.get("province")
        if pv.get("cities") != acc_city.get(n):
            problems.append(f"[R5] provinces[{n}].cities={pv.get('cities')} 与明细 {acc_city.get(n)} 不符")
        if pv.get("poi") != acc_poi.get(n):
            problems.append(f"[R5] provinces[{n}].poi={pv.get('poi')} 与明细 {acc_poi.get(n)} 不符")
        if pv.get("districts") != acc_dist.get(n):
            problems.append(f"[R5] provinces[{n}].districts={pv.get('districts')} 与明细 {acc_dist.get(n)} 不符")
    # ③ 必填字段
    required_city = ("city", "province", "adcode", "poi_total", "page", "districts", "grades")
    for c in cities:
        for k in required_city:
            if k not in c:
                problems.append(f"[R5] cities[{c.get('city', '?')}] 缺字段 {k}")
                break
    # ④ 外链形态（美团/大众点评）
    meituan_cnt = 0
    for c in cities:
        ext = c.get("external") or {}
        for k, u in (ext.items() if isinstance(ext, dict) else []):
            if not u:
                continue
            meituan_cnt += 1
            if not str(u).startswith(("http://", "https://")):
                problems.append(f"[R5] {c.get('city')} external.{k} 非合法 URL: {u}")
    stats["json_routes_checked"] = checked
    stats["external_links"] = meituan_cnt


def audit_orphans(site_root, problems, stats):
    """R6 cities/ 与 provinces/ 下不对应任何城市的残留文件。"""
    d = _load(site_root, "data.json")
    if d is None:
        return
    cities = d.get("cities") or []
    legit = set()
    provs_with_cities = set()
    for c in cities:
        legit.add(os.path.basename(c.get("page") or ""))          # <adcode>.html
        legit.add(f"{c['city']}.html")                             # 城市名存根
        provs_with_cities.add(c["province"])
    # --- cities/
    cdir = os.path.join(site_root, "cities")
    actual = {fn for fn in os.listdir(cdir) if fn.endswith(".html")}
    stats["city_pages"] = len(actual)
    for o in sorted(actual - legit):
        problems.append(f"[R6 孤儿文件] cities/{o} 不对应任何城市（建议删除）")
    for m in sorted(legit - actual):
        problems.append(f"[R6 缺页面] cities/{m} 应有页面缺失")
    # --- provinces/（空态省份页合法）
    pdir = os.path.join(site_root, "provinces")
    pactual = {fn[:-5] for fn in os.listdir(pdir) if fn.endswith(".html")}
    stats["province_pages"] = len(pactual)
    for o in sorted(pactual - provs_with_cities):
        if o not in ("香港特别行政区", "澳门特别行政区"):
            problems.append(f"[R6 孤儿省份页] provinces/{o}.html 无建库城市且不在空态白名单（建议删除或重建）")
    for m in sorted(provs_with_cities - pactual):
        problems.append(f"[R6 缺省份页] provinces/{m}.html 应有页面缺失")


def audit_json_md_sync(site_root, problems, stats):
    """R7 data.json ↔ data.md 同源同值：覆盖对齐 + 逐城重解析比对 + md 内锚点可达。"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import build_api as B

    d = _load(site_root, "data.json")
    md_path = os.path.join(site_root, "data.md")
    if d is None or not os.path.isfile(md_path):
        problems.append("[R7] data.json / data.md 缺失")
        return
    cities = d.get("cities") or []
    md = read(md_path)

    # 解析 md 的章节结构：## <省> / ### <市>，记录每段落字节范围与标题集合
    import re
    heads = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^(#{1,3}) ", md)]

    def slug(h):
        return h.strip().lower().replace(" ", "-")

    anchors = set()
    for i, (pos, _) in enumerate(heads):
        line_end = md.find("\n", pos)
        title = md[pos:line_end]
        level = len(title.split(" ")[0])
        name = title[level + 1:].strip()
        anchors.add(slug(name))
    # md 内锚点链接可达性
    bad_anchor = 0
    for a in set(re.findall(r"\]\(#([^)]+)\)", md)):
        if a not in anchors and unquote(a) not in anchors:
            bad_anchor += 1
            if bad_anchor <= 10:
                problems.append(f"[R7 md 死锚点] ](#{a}) 无对应标题")
    if bad_anchor > 10:
        problems.append(f"[R7 md 死锚点] 另有 {bad_anchor - 10} 处")
    stats["md_anchors"] = len(anchors)

    # 逐城切分：每个 ### <市> 段由此处到下一个同级以上标题之前
    # 注意：省级索引正文下沉后会产生 `### 城市列表` 之类的非城市三级标题，须按已知城市名过滤
    json_cities = {(c["province"], c["city"]) for c in cities}
    lines = heads[:]
    sec_pos = []
    cur_prov = None
    n_skip_h3 = 0
    for i, (pos, _) in enumerate(lines):
        line_end = md.find("\n", pos)
        title = md[pos:line_end]
        lvl = len(title.split(" ")[0])
        nxt = lines[i + 1][0] if i + 1 < len(lines) else len(md)
        name = title[lvl + 1:].strip()
        if lvl == 2:
            cur_prov = name if (name, name) in json_cities or any(p == name for p, _ in json_cities) else None
            continue
        if lvl == 3:
            if cur_prov is not None and (cur_prov, name) in json_cities:
                sec_pos.append((cur_prov, name, md[line_end + 1:nxt]))
            else:
                n_skip_h3 += 1
    md_cities = {}
    for pv, nm, body in sec_pos:
        md_cities.setdefault((pv, nm), body)
    stats["md_h3_index_subsections"] = n_skip_h3

    for miss in sorted(json_cities - set(md_cities)):
        problems.append(f"[R7] data.md 缺城市章节: {miss[0]}/{miss[1]}")
    for extra in sorted(set(md_cities) - json_cities):
        problems.append(f"[R7] data.md 多余城市章节: {extra[0]}/{extra[1]}（data.json 无对应）")

    n_city = 0
    n_img_ok = 0
    for c in cities:
        body = md_cities.get((c["province"], c["city"]))
        if body is None:
            continue
        # 还原成可被 parse_city_md 解析的形态：补回一级标题 + 撤销 data.md 的标题下沉（-2 级）
        body = re.sub(r"(?m)^(#{1,6})(\s+)",
                      lambda m: "#" * max(len(m.group(1)) - 2, 1) + m.group(2), body)
        txt = f"# {c['city']}\n" + body
        tmp = os.path.join(tempfile.gettempdir(), "_ra_%s.md" % abs(hash((c["province"], c["city"]))))
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(txt)
        try:
            rp = B.parse_city_md(tmp, c["province"])
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
        def _n(v):
            return len(v.get("list", [])) if isinstance(v, dict) else len(v or [])
        checks = [
            ("poi_total", c.get("poi_total"), rp.get("poi_total")),
            ("district_count", c.get("district_count"), rp.get("district_count")),
            ("food", len(c.get("food") or []), len(rp.get("food") or [])),
            ("leisure", _n(c.get("leisure")), _n(rp.get("leisure"))),
            ("kids", _n(c.get("kids")), _n(rp.get("kids"))),
            ("malls", len(c.get("malls") or []), len(rp.get("malls") or [])),
            ("hotels", len(c.get("hotels") or []), len(rp.get("hotels") or [])),
            ("specialties", len(c.get("specialties") or []), len(rp.get("specialties") or [])),
            ("waves", c.get("waves"), rp.get("waves")),
        ]
        for name, a, b in checks:
            if a != b:
                problems.append(f"[R7 JSON≠MD] {c['city']} {name}: json={a} md={b}")
        n_city += 1
        if c.get("food"):
            n_img_ok += 1
    stats["sync_cities"] = n_city
    # data.md 尾部附录存在性
    for sec in ("附录 A", "附录 B"):
        if sec not in md:
            problems.append(f"[R7] data.md 缺附录: {sec}")


def audit_assets(site_root, problems, stats):
    for f in ("robots.txt", "_headers", "CNAME", "404.html", "assets/style.css", "assets/app.js"):
        if not os.path.isfile(os.path.join(site_root, f)):
            problems.append(f"[R8] 部署资产缺失: {f}")
    rb = os.path.join(site_root, "robots.txt")
    if os.path.isfile(rb) and "sitemap.xml" not in read(rb):
        problems.append("[R8] robots.txt 未声明 sitemap")


def main():
    site = sys.argv[sys.argv.index("--site") + 1] if "--site" in sys.argv else os.path.join(ROOT, "site")
    site_root = os.path.abspath(site)
    problems, stats = [], {}
    print(f"[route_audit] site = {site_root}")
    audit_html(site_root, problems, stats)
    audit_sitemap(site_root, problems, stats)
    audit_json_routes(site_root, problems, stats)
    audit_orphans(site_root, problems, stats)
    audit_json_md_sync(site_root, problems, stats)
    audit_assets(site_root, problems, stats)

    print(f"[route_audit] 统计: {json.dumps(stats, ensure_ascii=False)}")
    if problems:
        print(f"[route_audit] 发现 {len(problems)} 个问题:")
        for p in problems[:80]:
            print("  -", p)
        if len(problems) > 80:
            print(f"  ... 其余 {len(problems) - 80} 个从略")
        sys.exit(1)
    print("[route_audit] ✅ 全部路线核查通过（R1–R8）")


if __name__ == "__main__":
    main()
