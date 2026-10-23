#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
route_audit.py — FUN 站点全量路线核查（链接 / 锚点 / 接口 / 同步性）

核查面:
  R1  HTML 页面内 href/src 路线（相对/绝对/锚点/外链分类，逐一落盘校验）
  R2  meta refresh 跳转目标
  R3  canonical 链接目标
  R4  sitemap.xml 全部 URL
  R5  JSON 内嵌路线（cities/index.json、index.json、food/top.json、
      districts/top.json、provinces/*.json、data.json 的 page/json/md/city_page 字段）
  R6  孤儿文件核查（cities/ 下不对应任何城市的残留页）
  R7  JSON↔MD 同源同值核查（md 副本与 data 源字节一致 + JSON 数值与 md 重解析一致）
  R8  robots.txt / _headers / CNAME 存在性

用法: python tools/route_audit.py [--site site]
退出码: 0 = 全部通过, 1 = 存在断线
"""
import json
import os
import re
import sys
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


def audit_json_routes(site_root, problems, stats):
    """JSON 内嵌的 page/json/md/city_page 路线。"""
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
            problems.append(f"[R5 JSON 断链] {ctx} {field}={url} -> 缺失")

    # 1. cities/index.json + index.json
    for jf in ("api/cities/index.json", "api/index.json", "data.json"):
        p = os.path.join(site_root, jf)
        if not os.path.isfile(p):
            problems.append(f"[R5] {jf} 缺失")
            continue
        d = json.loads(read(p))
        rows = d.get("cities") if isinstance(d.get("cities"), list) else None
        if rows is None:
            rows = d.get("city_index") if isinstance(d.get("city_index"), list) else []
        for c in rows:
            for f in ("page", "json", "md", "url"):
                chk(f, c.get(f), f"{jf}[{c.get('city')}]")
    # 2. food/top.json + districts/top.json
    for jf, field in (("api/food/top.json", "city_page"), ("api/districts/top.json", "city_page")):
        p = os.path.join(site_root, jf)
        if not os.path.isfile(p):
            problems.append(f"[R5] {jf} 缺失")
            continue
        d = json.loads(read(p))
        for it in d.get("items", []):
            chk(field, it.get(field), f"{jf}[{it.get('name')}]")
    # 3. provinces/*.json
    pdir = os.path.join(site_root, "api", "provinces")
    if os.path.isdir(pdir):
        for fn in sorted(os.listdir(pdir)):
            if not fn.endswith(".json"):
                continue
            d = json.loads(read(os.path.join(pdir, fn)))
            for c in d.get("cities", []):
                for f in ("page", "json", "md"):
                    chk(f, c.get(f), f"api/provinces/{fn}[{c.get('city')}]")
    stats["json_routes_checked"] = checked


def audit_orphans(site_root, problems, stats):
    """cities/ 与 provinces/ 下不对应任何城市的残留文件。"""
    idx = os.path.join(site_root, "api", "cities", "index.json")
    if not os.path.isfile(idx):
        return
    d = json.loads(read(idx))
    # --- cities/
    legit = set()
    provs_with_cities = set()
    for c in d["cities"]:
        legit.add(os.path.basename(c["page"]))          # <adcode>.html
        legit.add(f"{c['city']}.html")                   # 城市名存根
        provs_with_cities.add(c["province"])
    cdir = os.path.join(site_root, "cities")
    actual = {fn for fn in os.listdir(cdir) if fn.endswith(".html")}
    stats["city_pages"] = len(actual)
    for o in sorted(actual - legit):
        problems.append(f"[R6 孤儿文件] cities/{o} 不对应任何城市（建议删除）")
    for m in sorted(legit - actual):
        problems.append(f"[R6 缺页面] cities/{m} 应有页面缺失")
    # --- provinces/（空态省份页合法：34 省全覆盖，允许无城市省份存在）
    pdir = os.path.join(site_root, "provinces")
    pactual = {fn[:-5] for fn in os.listdir(pdir) if fn.endswith(".html")}
    stats["province_pages"] = len(pactual)
    for o in sorted(pactual - provs_with_cities):
        # 仅允许清单内的空态省份（如香港/澳门），其余为旧版残留
        if o not in ("香港特别行政区", "澳门特别行政区"):
            problems.append(f"[R6 孤儿省份页] provinces/{o}.html 无建库城市且不在空态白名单（建议删除或重建）")
    for m in sorted(provs_with_cities - pactual):
        problems.append(f"[R6 缺省份页] provinces/{m}.html 应有页面缺失")


def audit_json_md_sync(site_root, problems, stats):
    """R7 JSON↔MD 同源同值: ① md 副本与 data 源字节一致 ② JSON 数值与 md 重解析一致 ③ 双格式覆盖对齐。"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import build_api as B

    idx = os.path.join(site_root, "api", "cities", "index.json")
    d = json.loads(read(idx))
    data_root = os.path.join(ROOT, "data")
    n_city = 0
    for c in d["cities"]:
        prov, city = c["province"], c["city"]
        src = os.path.join(data_root, prov, city + ".md")
        dst = os.path.join(site_root, "md", prov, city + ".md")
        jpath = os.path.join(site_root, c["json"].lstrip("/"))
        # ① md 副本存在且与源一致
        if not os.path.isfile(dst):
            problems.append(f"[R7] md 副本缺失: md/{prov}/{city}.md")
            continue
        if os.path.isfile(src) and read(src) != read(dst):
            problems.append(f"[R7] md 副本与 data 源不一致: md/{prov}/{city}.md")
        # ② JSON 存在且与 md 重解析同值
        if not os.path.isfile(jpath):
            problems.append(f"[R7] JSON 缺失: {c['json']}")
            continue
        j = json.loads(read(jpath))
        reparsed = B.parse_city_md(dst, prov)
        checks = [
            ("poi_total", j.get("poi_total"), reparsed.get("poi_total")),
            ("district_count", j.get("district_count"), reparsed.get("district_count")),
            ("food_count", len(j.get("food", [])), len(reparsed.get("food", []))),
            ("leisure_count", len(j.get("leisure", {}).get("list", [])), len(reparsed.get("leisure", {}).get("list", []))),
            ("kids_count", len(j.get("kids", {}).get("list", [])), len(reparsed.get("kids", {}).get("list", []))),
            ("hotels_count", len(j.get("hotels", [])), len(reparsed.get("hotels", []))),
            ("specialties_count", len(j.get("specialties", [])), len(reparsed.get("specialties", []))),
            ("waves", j.get("waves"), reparsed.get("waves")),
        ]
        for name, a, b in checks:
            if a != b:
                problems.append(f"[R7 JSON≠MD] {city}({c['json']}) {name}: json={a} md={b}")
        n_city += 1
    stats["sync_cities"] = n_city
    # ③ md 目录下城市文件与 JSON 覆盖对齐（无多余 md）
    mdir = os.path.join(site_root, "md")
    md_cities = set()
    for prov in os.listdir(mdir):
        pdir = os.path.join(mdir, prov)
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if fn.endswith(".md") and fn != prov + ".md":
                md_cities.add((prov, fn[:-3]))
    json_cities = {(c["province"], c["city"]) for c in d["cities"]}
    for extra in sorted(md_cities - json_cities):
        problems.append(f"[R7] md 有多余城市档案: md/{extra[0]}/{extra[1]}.md（无对应 JSON）")


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
