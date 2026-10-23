#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
md → 静态网站生成器（fun.worldstip.com 数据站）

把 data/ 下的城市 md 档案转成自包含静态网站：
    site/index.html            全国总览（省卡片网格 + 搜索 + 统计）
    site/provinces/<省>.html   省页（城市列表）
    site/cities/<市>.html      城页（md 渲染为 HTML）
    site/assets/style.css      样式（亮色暖调，无外部依赖）
    site/assets/app.js         搜索 / 筛选 / 主题
    site/data.json             机读全量索引（供其他技能/API 调用）

设计约束
--------------------------------------------------------------------
1. **零依赖**：自带 md→HTML 转换器（只覆盖本库渲染器产出的结构：
   标题/表格/粗体/图片/链接/列表/引用/代码），不引第三方库，
   保证任何静态托管（Cloudflare Pages / GitHub Pages / OSS）都能跑。
2. **亮色暖调**：紧凑布局，拒绝大块空白占位；中文排版优先。
3. **数据可机读**：site/data.json 汇总全部城市的结构化统计，
   其他 skill 可直接 fetch 使用。
4. **图片外链高德**：店铺图仍走高德 CDN，本地不盗链下载。

部署（fun.worldstip.com）
--------------------------------------------------------------------
    python tools/build_site.py          # 生成 site/
    # 任选其一：
    # A. Cloudflare Pages：连接仓库，构建命令留空，输出目录 site/
    #    （推荐：免费、自动 HTTPS、全球 CDN）
    # B. GitHub Pages：推送到 gh-pages 分支，根目录放 site/ 内容，
    #    加 CNAME 文件内容 fun.worldstip.com
    # C. 阿里云 OSS：ossutil cp -r site/ oss://<bucket>/ --update
    #    绑定自定义域名 fun.worldstip.com 并开 CDN
    # DNS：fun CNAME → 托管平台提供的目标
"""

import argparse
import html
import json
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(ROOT, ".cache", "amap", "raw")
PROV = os.path.join(ROOT, ".cache", "amap", "prov_cities.json")
SITE = os.path.join(ROOT, "site")

# ---------------------------------------------------------------- md → HTML
def md_inline(s):
    """行内转换：先转义 HTML，再处理粗体/图片/链接/代码。"""
    s = html.escape(s, quote=False)
    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
               r'<img loading="lazy" alt="\1" src="\2">', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def md_to_html(md):
    """把本库产出的 md 转 HTML。结构：标题/引用/表格/列表/分割线/段落。"""
    lines = md.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        stripped = ln.strip()
        if not stripped:
            i += 1
            continue
        # 表格
        if stripped.startswith("|") and i + 1 < n and \
                re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
            head = [c.strip() for c in stripped.strip("|").split("|")]
            out.append('<div class="tw"><table><thead><tr>%s</tr></thead>'
                       '<tbody>' % "".join("<th>%s</th>" % md_inline(h)
                                           for h in head))
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|")
                         .split("|")]
                out.append("<tr>%s</tr>" % "".join(
                    "<td>%s</td>" % md_inline(c) for c in cells))
                i += 1
            out.append("</tbody></table></div>")
            continue
        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            lv = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lv, md_inline(m.group(2)), lv))
            i += 1
            continue
        # 引用块
        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>%s</blockquote>"
                       % "<br>".join(md_inline(b) for b in buf if b))
            continue
        # 分割线
        if re.match(r"^-{3,}$", stripped):
            out.append("<hr>")
            i += 1
            continue
        # 待办列表
        if stripped.startswith("- [ ]"):
            items = []
            while i < n and lines[i].strip().startswith("- [ ]"):
                items.append(lines[i].strip()[5:].strip())
                i += 1
            out.append('<ul class="todo">%s</ul>' % "".join(
                '<li><input type="checkbox" disabled> %s</li>'
                % md_inline(x) for x in items))
            continue
        # 无序列表
        if stripped.startswith("- "):
            items = []
            while i < n and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            out.append("<ul>%s</ul>" % "".join(
                "<li>%s</li>" % md_inline(x) for x in items))
            continue
        # 段落
        buf = [stripped]
        i += 1
        while i < n and lines[i].strip() and \
                not lines[i].strip().startswith(("|", "#", ">", "- ")) and \
                not re.match(r"^-{3,}$", lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % md_inline(" ".join(buf)))
    return "\n".join(out)


# ---------------------------------------------------------------- 样式与脚本
STYLE = """
:root{--bg:#faf7f2;--card:#fff;--ink:#2b2620;--sub:#7a7064;--line:#e8e0d5;
--acc:#c2540a;--acc2:#0a7c5a;--chip:#f3ece1;--red:#c0392b;--green:#1e7d4f}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);
font:15px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
header.top{background:var(--card);border-bottom:1px solid var(--line);
position:sticky;top:0;z-index:50}
header.top .wrap{display:flex;align-items:center;gap:16px;
height:56px;flex-wrap:wrap}
.brand{font-weight:700;font-size:17px;white-space:nowrap}
.brand small{color:var(--sub);font-weight:400;margin-left:8px;font-size:12px}
nav{display:flex;gap:14px;font-size:14px;margin-left:auto;flex-wrap:wrap}
.search{flex:1;min-width:180px;max-width:420px}
.search input{width:100%;height:34px;border:1px solid var(--line);
border-radius:17px;padding:0 14px;background:var(--bg);font-size:14px;
outline:none}
.search input:focus{border-color:var(--acc)}
.hero{padding:36px 0 8px}
.hero h1{font-size:26px;letter-spacing:.5px}
.hero p{color:var(--sub);margin-top:6px;font-size:14px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:12px;margin:20px 0 8px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 16px}
.stat b{font-size:22px;display:block;color:var(--acc)}
.stat span{color:var(--sub);font-size:12.5px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));
gap:14px;margin:18px 0 40px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px;display:block;color:inherit;transition:box-shadow .15s}
.card:hover{box-shadow:0 4px 18px rgba(60,40,10,.10);text-decoration:none}
.card h3{font-size:16px;margin-bottom:6px}
.card .meta{color:var(--sub);font-size:12.5px;line-height:1.9}
.chips{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap}
.chip{background:var(--chip);border-radius:10px;padding:1px 9px;font-size:11.5px;
color:#6b5a3e}
.chip.w2{background:#e2f2ea;color:var(--green)}
.chip.part{background:#fdf0e2;color:var(--acc)}
main{padding:26px 0 60px}
.doc{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:28px 32px;margin-top:18px}
.doc h1{font-size:24px;margin:6px 0 14px}
.doc h2{font-size:19px;margin:26px 0 10px;padding-bottom:8px;
border-bottom:2px solid var(--line)}
.doc h3{font-size:16px;margin:18px 0 8px;color:#8a4a12}
.doc p{margin:8px 0}
.doc blockquote{background:var(--chip);border-left:4px solid var(--acc);
border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 0;color:#6b5a3e;
font-size:13.5px}
.doc hr{border:none;border-top:1px solid var(--line);margin:22px 0}
.tw{overflow-x:auto;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{background:var(--chip);text-align:left;font-weight:600}
th,td{border:1px solid var(--line);padding:6px 10px;vertical-align:top}
tbody tr:nth-child(even){background:#fcfaf6}
img{border-radius:8px;max-width:100%;height:auto}
ul{padding-left:22px;margin:8px 0}
ul.todo{list-style:none;padding-left:4px}
ul.todo li{margin:4px 0;color:#5a5044}
code{background:var(--chip);border-radius:5px;padding:1px 6px;font-size:12.5px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}
.filters button{background:var(--card);border:1px solid var(--line);
border-radius:16px;padding:4px 14px;font-size:13px;cursor:pointer;color:var(--sub)}
.filters button.on{background:var(--acc);border-color:var(--acc);color:#fff}
footer{border-top:1px solid var(--line);padding:22px 0;color:var(--sub);
font-size:12.5px;text-align:center}
.badge{display:inline-block;border-radius:6px;padding:0 8px;font-size:12px;
font-weight:700}
.badge.S{background:#c2540a;color:#fff}.badge.A{background:#0a7c5a;color:#fff}
.badge.B{background:#8a6d3b;color:#fff}.badge.C{background:#b8aea0;color:#fff}
@media(max-width:640px){.doc{padding:18px 16px}.hero h1{font-size:21px}}
"""

APP_JS = """
(function(){
  var box=document.getElementById('q');
  if(!box)return;
  var cards=[].slice.call(document.querySelectorAll('[data-name]'));
  var chips=[].slice.call(document.querySelectorAll('.filters button'));
  var filt='all';
  box.addEventListener('input',function(){
    var v=box.value.trim().toLowerCase();
    cards.forEach(function(c){
      var hit=!v||c.getAttribute('data-name').toLowerCase().indexOf(v)>=0
        ||c.getAttribute('data-prov').toLowerCase().indexOf(v)>=0;
      var f=filt==='all'||c.getAttribute('data-dim')===filt;
      c.style.display=(hit&&f)?'':'none';
    });
  });
  chips.forEach(function(b){
    b.addEventListener('click',function(){
      chips.forEach(function(x){x.classList.remove('on')});
      b.classList.add('on');filt=b.getAttribute('data-f');
      box.dispatchEvent(new Event('input'));
    });
  });
})();
"""


def page(title, body, nav=""):
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header class="top"><div class="wrap">
<div class="brand">fun.worldstip.com<small>全国美食 × 商圈 × 娱乐 数据站</small></div>
<nav><a href="index.html">首页</a><a href="index.html#prov">省份</a>
<a href="data.json">数据 JSON</a><a href="README.html">使用说明</a></nav>
</div></header>
%s
<footer><div class="wrap">数据来源：高德地图 Web 服务 POI ·
本地美食探索 skill 数据层 v0.7.0 · 页面由 md 自动生成</div></footer>
<script src="assets/app.js"></script>
</body></html>""" % (html.escape(title), body)


def city_stats(cache):
    allp = [p for q in (cache.get("queries") or {}).values()
            for p in q.get("items", [])]
    u = {p["id"]: p for p in allp if p.get("id")}
    waves = cache.get("waves") or [1]
    return len(u), waves, (cache.get("updated") or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=SITE)
    args = ap.parse_args()
    site = args.out
    if os.path.exists(site):
        shutil.rmtree(site)
    os.makedirs(os.path.join(site, "assets"))
    os.makedirs(os.path.join(site, "provinces"))
    os.makedirs(os.path.join(site, "cities"))

    with open(os.path.join(site, "assets", "style.css"), "w",
              encoding="utf-8") as f:
        f.write(STYLE)
    with open(os.path.join(site, "assets", "app.js"), "w",
              encoding="utf-8") as f:
        f.write(APP_JS)

    provs = json.load(open(PROV, encoding="utf-8"))
    index_rows = []
    grand = 0
    cities_n = 0
    w2_n = 0

    for pname, v in provs.items():
        cities = v.get("cities") or []
        prov_cards = []
        prov_tot = 0
        prov_done = 0
        for ad, cname, lvl in cities:
            fp = os.path.join(RAW, cname + ".json")
            if not os.path.exists(fp):
                prov_cards.append((cname, None, 0, None, ""))
                continue
            cache = json.load(open(fp, encoding="utf-8"))
            n, waves, upd = city_stats(cache)
            prov_tot += n
            prov_done += 1
            cities_n += 1
            grand += n
            if 2 in waves:
                w2_n += 1
            # 城页
            mdfp = os.path.join(DATA, pname, cname + ".md")
            if os.path.exists(mdfp):
                md = open(mdfp, encoding="utf-8").read()
                body = ('<main><div class="wrap">'
                        '<p><a href="../provinces/%s.html">← 返回%s</a> · '
                        '<a href="../index.html">全国总览</a></p>'
                        '<article class="doc">%s</article></div></main>'
                        % (pname, pname, md_to_html(md)))
                with open(os.path.join(site, "cities", cname + ".html"),
                          "w", encoding="utf-8") as f:
                    f.write(page("%s · %s" % (cname, pname), body))
            prov_cards.append((cname, n, waves, upd, ""))
            index_rows.append({
                "city": cname, "province": pname, "adcode": ad,
                "poi": n, "waves": waves, "updated": upd,
                "url": "cities/%s.html" % cname,
            })

        # 省页
        cards = []
        for cname, n, waves, upd, _x in prov_cards:
            if n is None:
                cards.append(
                    '<div class="card" data-name="%s" data-prov="%s">'
                    '<h3>%s</h3><div class="meta">⏳ 未采集</div></div>'
                    % (html.escape(cname), html.escape(pname),
                       html.escape(cname)))
                continue
            wchip = ('<span class="chip w2">全维度</span>' if 2 in waves
                     else '<span class="chip part">基础维度</span>')
            cards.append(
                '<a class="card" href="cities/%s.html" data-name="%s" '
                'data-prov="%s" data-dim="%s"><h3>%s</h3>'
                '<div class="meta">POI %s 条 · 更新 %s</div>'
                '<div class="chips">%s</div></a>'
                % (cname, html.escape(cname), html.escape(pname),
                   "w2" if 2 in waves else "w1", html.escape(cname),
                   format(n, ","), (upd or "")[:10], wchip))
        body = ('<main><div class="wrap">'
                '<div class="hero"><h1>%s</h1>'
                '<p>已采集 %d / %d 城 · POI 合计 %s 条 · '
                '上级：<a href="index.html">全国总览</a></p></div>'
                '<div class="filters">'
                '<button class="on" data-f="all">全部</button>'
                '<button data-f="w2">全维度</button>'
                '<button data-f="w1">基础维度</button></div>'
                '<div class="search"><input id="q" placeholder="搜索城市…">'
                '</div>'
                '<div class="grid">%s</div></div></main>'
                % (html.escape(pname), prov_done, len(cities),
                   format(prov_tot, ","), "".join(cards)))
        with open(os.path.join(site, "provinces", pname + ".html"), "w",
                  encoding="utf-8") as f:
            f.write(page("%s · 省份页" % pname, body))

    # 首页
    prov_grid = []
    for pname, v in provs.items():
        cities = v.get("cities") or []
        done = sum(1 for ad, c, l in cities
                   if os.path.exists(os.path.join(RAW, c + ".json")))
        tot = 0
        for ad, c, l in cities:
            fp = os.path.join(RAW, c + ".json")
            if os.path.exists(fp):
                tot += city_stats(json.load(open(fp, encoding="utf-8")))[0]
        prov_grid.append(
            '<a class="card" href="provinces/%s.html" data-name="%s" '
            'data-prov="%s"><h3>%s</h3><div class="meta">%d / %d 城 · '
            'POI %s 条</div></a>'
            % (pname, html.escape(pname), html.escape(pname),
               html.escape(pname), done, len(cities), format(tot, ",")))
    body = ('<main><div class="wrap">'
            '<div class="hero"><h1>全国美食 × 商圈 × 娱乐 数据库</h1>'
            '<p>覆盖全国 34 省级单位 · 389 个地级市 · '
            '美食 / 商圈 / 成人娱乐 / 儿童亲子 / 酒店 / 特产 六维数据，'
            '每城含商圈画像与 S/A/B/C 评级。数据可机读调用：'
            '<a href="data.json">data.json</a></p></div>'
            '<div class="stats">'
            '<div class="stat"><b>%d</b><span>已建库城市</span></div>'
            '<div class="stat"><b>%d</b><span>全维度城市（wave2）</span></div>'
            '<div class="stat"><b>%s</b><span>POI 总数（去重）</span></div>'
            '<div class="stat"><b>34</b><span>省级单位</span></div>'
            '</div>'
            '<div class="search"><input id="q" placeholder="搜索省份或城市…">'
            '</div>'
            '<div class="filters"><button class="on" data-f="all">全部</button>'
            '</div>'
            '<div class="grid" id="prov">%s</div>'
            '</div></main>'
            % (cities_n, w2_n, format(grand, ","), "".join(prov_grid)))
    with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as f:
        f.write(page("全国美食 × 商圈 × 娱乐 数据库", body))

    # 机读索引
    with open(os.path.join(site, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_by": "tools/build_site.py",
                   "source": "高德地图 Web 服务 POI",
                   "skill": "本地美食探索 v0.7.0",
                   "cities_total": sum(len(v.get("cities") or [])
                                       for v in provs.values()),
                   "cities_built": cities_n,
                   "cities_full_dims": w2_n,
                   "poi_total": grand,
                   "cities": index_rows}, f, ensure_ascii=False, indent=1)

    # 使用说明页
    readme_src = os.path.join(DATA, "README.md")
    if os.path.exists(readme_src):
        md = open(readme_src, encoding="utf-8").read()
        body = ('<main><div class="wrap">'
                '<article class="doc">%s</article></div></main>'
                % md_to_html(md))
        with open(os.path.join(site, "README.html"), "w",
                  encoding="utf-8") as f:
            f.write(page("使用说明", body))

    print("网站生成 → %s（%d 城 / %d 省 / POI %s）"
          % (site, cities_n, len(provs), format(grand, ",")))


if __name__ == "__main__":
    main()
