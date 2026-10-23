#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_fun_site.py — 生成 FUN 苹果风静态网站（fun.worldstip.com）。

输入：site/api/ 下 build_api.py 产出的 JSON（index/cities/food/districts/stats）
输出（覆盖写入 site/）：
  assets/style.css, assets/app.js     设计系统与交互
  index.html                          FUN hero + 主站 sections
  cities/<adcode>.html                389 城市页
  provinces/<省>.html                 32 省级页
  api.html                            数据接口完整文档
  sources.html                        数据来源与方法论
  README.html                         部署说明

设计基线：Apple 设计语言——SF 字体栈、#fbfbfd 底、大字号标题、毛玻璃导航、
18px 圆角卡片、克制的阴影与留白；品牌色为 FUN 渐变（橙→粉→紫）。
"""
import html
import json
import os
import re
from datetime import datetime
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
API = os.path.join(SITE, "api")
GH_REPO = "https://github.com/MrdT-BitsNote/fun"
GENERATED = datetime.now().strftime("%Y-%m-%d %H:%M")


def esc(s):
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


_SZ_CACHE = {}


def _file_size(name):
    """全量数据文件的真实体积（原始 + gzip-1），带缓存；供入口卡片与接口文档页展示。"""
    if name in _SZ_CACHE:
        return _SZ_CACHE[name]
    import gzip as _gz
    p = os.path.join(SITE, name)
    if not os.path.isfile(p):
        return _SZ_CACHE.setdefault(name, ("—", "—"))
    with open(p, "rb") as f:
        raw_bytes = f.read()
    gz = len(_gz.compress(raw_bytes, 1))
    val = (f"{len(raw_bytes)/1048576:.1f} MB", f"{gz/1048576:.1f} MB")
    _SZ_CACHE[name] = val
    return val


def load(name):
    """从 site/ 根读取数据文件（v0.9.0 起唯一数据层为 site/data.json）。"""
    with open(os.path.join(SITE, name), encoding="utf-8") as f:
        return json.load(f)


# ================================================================ 设计系统 CSS

CSS = r"""/* FUN · 设计系统（Apple 风格基线 + FUN 品牌渐变） */
:root{
  --bg:#fbfbfd; --surface:#ffffff; --surface-2:#f5f5f7; --surface-3:#ececed;
  --text:#1d1d1f; --text-2:#58585d; --text-3:#6e6e73;
  --line:rgba(0,0,0,.08); --line-2:rgba(0,0,0,.14);
  --blue:#0071e3; --orange:#ff9f0a; --pink:#ff375f; --purple:#bf5af2; --green:#30d158;
  --grad-fun:linear-gradient(120deg,#ff9f0a 0%,#ff375f 52%,#bf5af2 100%);
  --shadow-1:0 1px 3px rgba(0,0,0,.04);
  --shadow-2:0 4px 16px rgba(0,0,0,.06);
  --shadow-3:0 20px 60px rgba(0,0,0,.10);
  --r-s:12px; --r-m:18px; --r-l:26px; --pill:980px;
  --nav-h:52px;
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","PingFang SC","Hiragino Sans GB","Helvetica Neue","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
body{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.5;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;overflow-x:hidden}
a{color:inherit;text-decoration:none}
img{display:block;max-width:100%}
::selection{background:rgba(255,55,95,.18)}
/* 键盘可达性：焦点环统一可见（2px + 2px 偏移），鼠标点击不显示 */
:focus{outline:none}
:focus-visible{outline:2px solid var(--blue);outline-offset:2px;border-radius:4px}
.nav-gh:focus-visible,.btn:focus-visible{outline-color:var(--text)}
.btn:focus-visible{outline-offset:3px}

/* ---------- 导航（毛玻璃） ---------- */
.nav{position:fixed;inset:0 0 auto 0;height:var(--nav-h);z-index:1000;
  background:rgba(251,251,253,.78);backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px);
  border-bottom:1px solid transparent;transform:translateY(-100%);transition:transform .45s cubic-bezier(.22,1,.36,1),border-color .3s}
.nav.show{transform:none;border-bottom-color:var(--line)}
.nav-in{max-width:1120px;margin:0 auto;height:100%;display:flex;align-items:center;gap:26px;padding:0 22px}
.nav-logo{font-weight:800;font-size:19px;letter-spacing:-.02em;display:flex;align-items:center;gap:8px}
.nav-logo i{width:9px;height:9px;border-radius:50%;background:var(--grad-fun);display:inline-block}
.nav-links{display:flex;gap:24px;margin-left:auto;font-size:13px;color:var(--text-2)}
.nav-links a{transition:color .2s}.nav-links a:hover{color:var(--text)}
.nav-gh{font-size:12px;font-weight:600;color:#fff!important;background:var(--text);padding:6px 14px;border-radius:var(--pill)}
@media(max-width:760px){.nav-links a:not(.nav-gh){display:none}}

/* ---------- HERO ---------- */
.hero{height:100svh;min-height:620px;position:relative;display:flex;flex-direction:column;
  align-items:center;justify-content:center;overflow:hidden;background:var(--bg)}
.blob{position:absolute;border-radius:50%;filter:blur(100px);pointer-events:none}
.blob-a{width:56vw;height:56vw;left:-14vw;top:-18vw;background:radial-gradient(circle,rgba(255,159,10,.16),transparent 65%)}
.blob-b{width:52vw;height:52vw;right:-16vw;bottom:-20vw;background:radial-gradient(circle,rgba(191,90,242,.14),transparent 65%)}
.blob-c{width:34vw;height:34vw;right:8vw;top:-10vw;background:radial-gradient(circle,rgba(255,55,95,.10),transparent 65%)}
.hero-in{position:relative;z-index:2;display:flex;flex-direction:column;align-items:center;text-align:center;padding:0 22px;will-change:transform,opacity}
.hero-kicker{font-size:13px;font-weight:600;letter-spacing:.34em;color:var(--text-2);text-transform:uppercase;margin-bottom:4px}
.hero-kicker b{color:transparent;background:var(--grad-fun);-webkit-background-clip:text;background-clip:text}
.fun-word{font-size:clamp(6.5rem,23vw,19rem);font-weight:900;line-height:.82;letter-spacing:-.055em;
  display:flex;align-items:baseline;user-select:none;margin:6px 0 2px}
.fun-word span{display:inline-block;animation:letter-in 1s cubic-bezier(.22,1.4,.36,1) backwards}
.fun-word .f{animation-delay:.05s}
.fun-word .u{animation-delay:.18s;transform:rotate(-5deg) translateY(.02em)}
.fun-word .n{animation-delay:.31s;transform:rotate(2.5deg);
  background:var(--grad-fun);-webkit-background-clip:text;background-clip:text;color:transparent}
.fun-word .dot{width:.16em;height:.16em;border-radius:50%;background:var(--orange);
  margin-left:.07em;animation:letter-in .8s cubic-bezier(.22,1.4,.36,1) .48s backwards,dot-pulse 2.2s ease-in-out 1.4s infinite}
@keyframes letter-in{from{opacity:0;transform:translateY(.42em) scale(.6) rotate(-8deg)}to{opacity:1}}
@keyframes dot-pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.35)}}
.hero-tag{font-size:clamp(1.15rem,2.6vw,1.7rem);font-weight:700;letter-spacing:-.01em;margin-top:14px}
.hero-tag em{font-style:normal;color:transparent;background:var(--grad-fun);-webkit-background-clip:text;background-clip:text}
.hero-sub{font-size:clamp(.95rem,1.6vw,1.12rem);color:var(--text-2);margin-top:12px;max-width:34em}
.hero-cta{display:flex;gap:14px;margin-top:34px;flex-wrap:wrap;justify-content:center}
.btn{display:inline-flex;align-items:center;gap:8px;font-size:15px;font-weight:600;
  padding:13px 30px;border-radius:var(--pill);transition:.25s;cursor:pointer;border:none}
.btn-p{background:var(--text);color:#fff}.btn-p:hover{background:#000;transform:scale(1.03)}
.btn-g{background:rgba(0,0,0,.05);color:var(--text)}.btn-g:hover{background:rgba(0,0,0,.09)}
.hero-hint{position:absolute;bottom:26px;left:50%;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;gap:8px;color:var(--text-3);font-size:12px;letter-spacing:.18em}
.hero-hint .mouse{width:24px;height:38px;border:1.5px solid var(--text-3);border-radius:12px;position:relative}
.hero-hint .mouse::after{content:"";position:absolute;left:50%;top:7px;width:3px;height:7px;margin-left:-1.5px;border-radius:2px;background:var(--text-3);animation:wheel 1.8s infinite}
@keyframes wheel{0%{transform:translateY(0);opacity:1}70%{transform:translateY(12px);opacity:0}100%{opacity:0}}
.scroll-progress{position:fixed;top:0;left:0;height:2.5px;background:var(--grad-fun);z-index:1001;width:0}

/* ---------- 主内容（滑片覆盖 hero） ---------- */
.sheet{position:relative;z-index:5;background:var(--bg);border-radius:42px 42px 0 0;margin-top:-42px;
  box-shadow:0 -24px 80px rgba(0,0,0,.10)}
.wrap{max-width:1120px;margin:0 auto;padding:0 22px}
section{padding:96px 0 8px}
.sec-label{font-size:13px;font-weight:700;letter-spacing:.22em;text-transform:uppercase;
  color:transparent;background:var(--grad-fun);-webkit-background-clip:text;background-clip:text;margin-bottom:10px}
.sec-title{font-size:clamp(1.9rem,4vw,2.9rem);font-weight:800;letter-spacing:-.03em;line-height:1.12}
.sec-desc{font-size:1.05rem;color:var(--text-2);margin-top:12px;max-width:46em}
.sec-head{margin-bottom:40px}

/* ---------- 统计条 ---------- */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:26px}
.stat{background:var(--surface);border-radius:var(--r-l);padding:30px 26px;box-shadow:var(--shadow-1);
  border:1px solid var(--line);transition:.3s}
.stat:hover{transform:translateY(-3px);box-shadow:var(--shadow-2)}
.stat b{font-size:clamp(2rem,3.4vw,2.9rem);font-weight:800;letter-spacing:-.03em;display:block;
  background:var(--grad-fun);-webkit-background-clip:text;background-clip:text;color:transparent}
.stat span{font-size:13.5px;color:var(--text-2);margin-top:4px;display:block}
@media(max-width:860px){.stats{grid-template-columns:repeat(2,1fr)}}

/* ---------- 搜索与筛选 ---------- */
.toolbar{position:sticky;top:var(--nav-h);z-index:50;background:rgba(251,251,253,.85);
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);padding:14px 0;margin:0 -22px;padding-left:22px;padding-right:22px}
.search-row{display:flex;gap:12px;align-items:center}
.search-box{flex:1;display:flex;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--line);
  border-radius:var(--pill);padding:11px 20px;box-shadow:var(--shadow-1);transition:.25s}
.search-box:focus-within{border-color:var(--text-3);box-shadow:var(--shadow-2)}
.search-box input{flex:1;border:none;outline:none;font-size:15.5px;font-family:var(--font);background:transparent;color:var(--text)}
.search-box kbd{font-family:var(--mono);font-size:11px;color:var(--text-3);border:1px solid var(--line-2);border-radius:6px;padding:2px 7px}
.dice{background:var(--surface);border:1px solid var(--line);border-radius:var(--pill);padding:11px 18px;
  font-size:14px;font-weight:600;color:var(--text-2);cursor:pointer;box-shadow:var(--shadow-1);transition:.2s;white-space:nowrap}
.dice:hover{color:var(--text);box-shadow:var(--shadow-2)}
.chips{display:flex;gap:8px;overflow-x:auto;padding:12px 2px 4px;scrollbar-width:none}
.chips::-webkit-scrollbar{display:none}
.chip{white-space:nowrap;font-size:13.5px;font-weight:500;padding:7px 16px;border-radius:var(--pill);
  background:var(--surface);border:1px solid var(--line);color:var(--text-2);cursor:pointer;transition:.2s}
.chip:hover{border-color:var(--text-3);color:var(--text)}
.chip.on{background:var(--text);border-color:var(--text);color:#fff}

/* ---------- 城市卡片 ---------- */
.city-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(246px,1fr));gap:14px;margin-top:20px}
.city-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-m);padding:20px;
  box-shadow:var(--shadow-1);transition:.28s cubic-bezier(.22,1,.36,1);display:flex;flex-direction:column;gap:10px}
.city-card:hover{transform:translateY(-4px) scale(1.008);box-shadow:var(--shadow-3);border-color:transparent}
.cc-top{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.cc-name{font-size:20px;font-weight:700;letter-spacing:-.01em}
.cc-prov{font-size:12px;color:var(--text-3);white-space:nowrap}
.cc-poi{font-size:13px;color:var(--text-2)}
.cc-poi b{color:var(--text);font-weight:700}
.gradebar{display:flex;height:6px;border-radius:3px;overflow:hidden;background:var(--surface-3)}
.gradebar i{display:block;height:100%}
.g-s{background:var(--grad-fun)}.g-a{background:var(--blue)}.g-b{background:#8e8e93}.g-c{background:#d2d2d7}
.cc-dims{display:flex;flex-wrap:wrap;gap:5px}
.dim-tag{font-size:11.5px;color:var(--text-2);background:var(--surface-2);border-radius:6px;padding:2.5px 8px}
.cc-foot{display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:6px}
.cc-go{font-size:13px;font-weight:600;color:var(--blue)}
.cc-go::after{content:" →";transition:.2s}
.city-card:hover .cc-go::after{margin-left:3px}
.empty-hint{grid-column:1/-1;text-align:center;color:var(--text-3);padding:60px 0;font-size:15px}

/* ---------- 商圈/美食卡 ---------- */
.dist-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.dist-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-m);padding:22px;
  box-shadow:var(--shadow-1);transition:.28s;display:flex;flex-direction:column;gap:10px}
.dist-card:hover{transform:translateY(-4px);box-shadow:var(--shadow-3);border-color:transparent}
.dc-head{display:flex;align-items:center;gap:10px}
.dc-name{font-size:17.5px;font-weight:700;letter-spacing:-.01em;flex:1}
.grade-badge{font-size:12px;font-weight:800;min-width:26px;height:26px;border-radius:9px;display:inline-flex;
  align-items:center;justify-content:center;padding:0 7px;letter-spacing:0}
.gb-s{background:var(--grad-fun);color:#fff}
.gb-a{background:var(--blue);color:#fff}
.gb-b{background:#8e8e93;color:#fff}
.gb-c{background:transparent;border:1.5px solid var(--line-2);color:var(--text-3)}
.dc-meta{font-size:13px;color:var(--text-2)}
.dc-meta b{color:var(--text)}
.dc-counts{display:flex;flex-wrap:wrap;gap:6px}
.cnt{font-size:12px;background:var(--surface-2);border-radius:7px;padding:3px 9px;color:var(--text-2)}
.cnt b{color:var(--text)}
.dc-city{font-size:12.5px;color:var(--blue);font-weight:600;margin-top:auto;padding-top:4px}

.food-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(228px,1fr));gap:14px}
.food-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-m);overflow:hidden;
  box-shadow:var(--shadow-1);transition:.28s;display:flex;flex-direction:column}
.food-card:hover{transform:translateY(-4px);box-shadow:var(--shadow-3);border-color:transparent}
.food-img{aspect-ratio:4/3;background:linear-gradient(135deg,#f5f5f7,#ececed);position:relative;overflow:hidden}
.food-img img{width:100%;height:100%;object-fit:cover;transition:transform .5s}
.food-card:hover .food-img img{transform:scale(1.05)}
.food-img .ph{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-size:44px;font-weight:800;color:#d2d2d7}
.food-img .rt{position:absolute;left:10px;top:10px;background:rgba(0,0,0,.72);backdrop-filter:blur(8px);
  color:#fff;font-size:12.5px;font-weight:700;border-radius:8px;padding:3px 9px}
.food-body{padding:14px 16px 16px;display:flex;flex-direction:column;gap:5px;flex:1}
.food-name{font-size:15.5px;font-weight:700;letter-spacing:-.01em;line-height:1.3}
.food-type{font-size:12px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.food-foot{display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:6px}
.food-avg{font-size:13px;font-weight:700;color:var(--orange)}

/* ---------- 休闲聚合条 ---------- */
.play-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:860px){.play-grid{grid-template-columns:1fr}}
.play-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-l);padding:26px;box-shadow:var(--shadow-1)}
.play-card h3{font-size:17px;font-weight:700;margin-bottom:16px}
.bar-row{display:flex;align-items:center;gap:10px;margin-bottom:9px;font-size:13px}
.bar-row .lb{width:112px;color:var(--text-2);text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-row .track{flex:1;height:10px;background:var(--surface-3);border-radius:5px;overflow:hidden}
.bar-row .fill{height:100%;border-radius:5px;background:var(--grad-fun)}
.bar-row .vl{width:44px;font-weight:700;font-size:12.5px}

/* ---------- 数据接口 ---------- */
.api-table{width:100%;border-collapse:collapse;background:var(--surface);border-radius:var(--r-m);
  overflow:hidden;box-shadow:var(--shadow-1);border:1px solid var(--line);font-size:14px}
.api-table th{background:var(--surface-2);text-align:left;padding:12px 16px;font-size:12.5px;color:var(--text-2);font-weight:600}
.api-table td{padding:13px 16px;border-top:1px solid var(--line);vertical-align:top}
.api-table code,.code{font-family:var(--mono);font-size:12.8px;background:var(--surface-2);border-radius:7px;padding:2.5px 8px;color:#c2410c}
.api-table a{color:var(--blue)}
pre.code{display:block;padding:18px 20px;line-height:1.65;overflow-x:auto;white-space:pre;color:var(--text)}
pre.code .cm{color:var(--text-3)}
pre.code .st{color:var(--green)}
pre.code .kw{color:var(--purple);font-weight:600}
.copy-btn{font-size:12px;font-weight:600;color:var(--blue);background:transparent;border:1px solid var(--line-2);
  border-radius:8px;padding:4px 12px;cursor:pointer;transition:.2s;margin-left:8px;white-space:nowrap}
.copy-btn:hover{background:var(--surface-2)}
.note-box{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-m);padding:20px 24px;
  font-size:14px;color:var(--text-2);box-shadow:var(--shadow-1)}
.note-box b{color:var(--text)}
.note-box ul{margin:8px 0 0 18px}
.note-box li{margin:4px 0}

/* ---------- 数据调用入口 ---------- */
.api-entry{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-l);
  box-shadow:var(--shadow-2);padding:22px 24px;margin-bottom:18px}
.api-entry-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}
.aeh-kicker{font-size:11.5px;font-weight:700;letter-spacing:.14em;color:var(--blue);margin-bottom:10px}
.aeh-base{display:flex;align-items:center;gap:6px;background:var(--surface-2);border:1px solid var(--line);
  border-radius:12px;padding:9px 12px 9px 14px;width:fit-content;max-width:100%}
.aeh-base code{font-family:var(--mono);font-size:15px;font-weight:600;color:var(--text);word-break:break-all}
.aeh-left{flex:1 1 320px;min-width:0}
.aeh-tip{font-size:13px;color:var(--text-2);margin-top:10px;max-width:46em}
.api-try{flex-shrink:0;background:var(--grad-fun);color:#fff;border:0;border-radius:var(--pill);
  padding:11px 22px;font-size:14px;font-weight:700;cursor:pointer;transition:.2s;
  box-shadow:0 4px 14px rgba(255,55,95,.28);font-family:var(--font)}
.api-try:hover{transform:scale(1.04)}
.api-try:disabled{opacity:.55;cursor:default;transform:none}
/* 两个全量文件卡片：并列双卡，格式色区分，超大幽灵字符作背景层 */
.aq-files{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:18px}
.aq-file{position:relative;overflow:hidden;isolation:isolate;display:flex;flex-direction:column;gap:9px;
  background:var(--surface-2);border:1px solid var(--line);border-radius:var(--r-m);
  padding:18px 20px 16px;text-decoration:none;color:inherit;
  transition:transform .28s cubic-bezier(.16,1,.3,1),box-shadow .28s,border-color .28s,background .28s}
.aq-file::before{content:"";position:absolute;inset:0;z-index:-1;opacity:0;transition:opacity .28s;
  background:radial-gradient(120% 92% at 100% 0%,rgba(0,113,227,.11),transparent 62%)}
.aq-file::after{content:"{ }";position:absolute;right:-10px;bottom:-30px;font-family:var(--mono);
  font-size:92px;font-weight:700;line-height:1;letter-spacing:-.06em;color:rgba(0,0,0,.035);
  pointer-events:none;user-select:none}
.aq-file.md::before{background:radial-gradient(120% 92% at 100% 0%,rgba(48,209,88,.15),transparent 62%)}
.aq-file.md::after{content:"#"}
.aq-file:hover{background:#fff;border-color:rgba(0,113,227,.42);
  transform:translateY(-2px);box-shadow:var(--shadow-2)}
.aq-file.md:hover{border-color:rgba(48,209,88,.48)}
.aq-file:hover::before{opacity:1}
.aq-file-top{display:flex;align-items:center;justify-content:space-between;gap:10px}
.aq-tag{font-size:10.5px;font-weight:800;letter-spacing:.12em;border-radius:6px;padding:3px 8px}
.aq-tag.tj{color:#0060c7;background:rgba(0,113,227,.10)}
.aq-tag.tm{color:#1b7a36;background:rgba(48,209,88,.15)}
.aq-size{font-family:var(--mono);font-size:11.5px;color:var(--text-3);white-space:nowrap}
.aq-file>code{font-family:var(--mono);font-size:20px;font-weight:700;letter-spacing:-.02em;color:var(--text)}
.aq-file>p{font-size:12.5px;line-height:1.62;color:var(--text-2)}
.aq-file>p b{color:var(--text);font-weight:700}
.aq-file>p code{font-family:var(--mono);font-size:11.5px;color:var(--text);
  background:rgba(0,0,0,.05);border-radius:4px;padding:1px 4px}
.aq-go{margin-top:auto;padding-top:8px;display:inline-flex;align-items:center;gap:6px;
  font-size:12.5px;font-weight:700;color:#0060c7;transition:gap .2s}
.aq-file.md .aq-go{color:#1b7a36}
.aq-file:hover .aq-go{gap:11px}
.api-live{margin-top:16px;border:1px dashed var(--line-2);border-radius:12px;padding:14px 16px;background:var(--surface-2)}
.api-live-head{font-family:var(--mono);font-size:12px;color:var(--text-2);margin-bottom:10px}
.api-live-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(108px,1fr));gap:10px}
.alv{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.alv b{display:block;font-size:18px;font-weight:800;letter-spacing:-.02em;color:var(--text)}
.alv span{font-size:11.5px;color:var(--text-3)}
.dd-sub{font-size:11.5px;color:var(--text-3);font-variant-numeric:tabular-nums}
.api-live-err{font-size:13px;color:#b42318;line-height:1.6}
@media(max-width:760px){.aq-files{grid-template-columns:1fr}.api-entry{padding:18px;border-radius:var(--r-m)}
  .aq-file>code{font-size:18px}.api-entry-head{gap:12px}.api-try{width:100%;text-align:center}}

/* ---------- 数据来源 ---------- */
.src-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media(max-width:860px){.src-grid{grid-template-columns:1fr}}
.src-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-l);padding:28px;
  box-shadow:var(--shadow-1);transition:.28s;display:flex;flex-direction:column;gap:10px}
.src-card:hover{transform:translateY(-4px);box-shadow:var(--shadow-3)}
.src-ico{width:46px;height:46px;border-radius:14px;display:flex;align-items:center;justify-content:center;
  font-size:22px;font-weight:800;color:#fff}
.src-card h3{font-size:18px;font-weight:700}
.src-card p{font-size:13.5px;color:var(--text-2);line-height:1.65}
.src-card .role{font-size:12px;font-weight:700;letter-spacing:.08em;color:var(--text-3);text-transform:uppercase}
.src-links{margin-top:auto;padding-top:8px;display:flex;gap:14px;font-size:13.5px;font-weight:600}
.src-links a{color:var(--blue)}

/* ---------- 页脚 ---------- */
.footer{margin-top:110px;border-top:1px solid var(--line);background:var(--surface-2)}
.foot-in{max-width:1120px;margin:0 auto;padding:52px 22px 40px;display:grid;grid-template-columns:2fr 1fr 1fr;gap:30px}
@media(max-width:760px){.foot-in{grid-template-columns:1fr}}
.foot-brand{font-size:26px;font-weight:900;letter-spacing:-.03em}
.foot-brand i{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--grad-fun);margin-left:3px}
.foot-desc{font-size:13px;color:var(--text-2);margin-top:8px;max-width:30em;line-height:1.7}
.foot-col h4{font-size:12.5px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:.1em;margin-bottom:12px}
.foot-col a{display:block;font-size:13.5px;color:var(--text-2);margin:7px 0;transition:.2s}
.foot-col a:hover{color:var(--text)}
.foot-base{max-width:1120px;margin:0 auto;padding:0 22px 34px;font-size:12px;color:var(--text-3);line-height:1.7}

/* ---------- 城市页 ---------- */
.city-hero{padding:calc(var(--nav-h) + 54px) 0 30px}
.back-link{font-size:13.5px;color:var(--text-2);font-weight:500;display:inline-flex;gap:6px;margin-bottom:18px;transition:.2s}
.back-link:hover{color:var(--text)}
.city-title-row{display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap}
.city-title{font-size:clamp(2.6rem,6vw,4.4rem);font-weight:900;letter-spacing:-.035em;line-height:1}
.city-prov-chip{font-size:14px;font-weight:600;color:var(--text-2);background:var(--surface);
  border:1px solid var(--line);border-radius:var(--pill);padding:6px 16px;margin-bottom:8px}
.city-sub{color:var(--text-2);font-size:15px;margin-top:14px;max-width:44em;line-height:1.7}
.chip-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:22px}
.metric-chip{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:10px 16px;
  font-size:13px;color:var(--text-2);box-shadow:var(--shadow-1)}
.metric-chip b{display:block;font-size:19px;font-weight:800;color:var(--text);letter-spacing:-.02em}
.anchor-nav{position:sticky;top:var(--nav-h);z-index:40;background:rgba(251,251,253,.85);
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border-bottom:1px solid var(--line);
  display:flex;gap:4px;overflow-x:auto;padding:0 22px;scrollbar-width:none}
.anchor-nav::-webkit-scrollbar{display:none}
.anchor-nav a{white-space:nowrap;font-size:13.5px;font-weight:600;color:var(--text-2);padding:13px 13px;
  border-bottom:2px solid transparent;transition:.2s}
.anchor-nav a:hover,.anchor-nav a.on{color:var(--text);border-bottom-color:var(--pink)}
.anchor-nav-in{max-width:1120px;margin:0 auto;display:flex;gap:4px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-l);
  padding:28px;box-shadow:var(--shadow-1);margin-bottom:16px}
.panel h3{font-size:19px;font-weight:800;letter-spacing:-.01em;margin-bottom:6px}
.panel .p-desc{font-size:13.5px;color:var(--text-2);margin-bottom:18px;line-height:1.65}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kv div{background:var(--surface-2);border-radius:12px;padding:12px 16px;font-size:13px;color:var(--text-2)}
.kv div b{display:block;font-size:16px;color:var(--text);font-weight:700}
.dist-detail{border-top:1px solid var(--line);padding:18px 0}
.dist-detail:first-of-type{border-top:none;padding-top:4px}
.dd-head{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.dd-name{font-size:16.5px;font-weight:700}
.dd-facts{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0}
.fact{font-size:12px;color:var(--text-2);background:var(--surface-2);border-radius:7px;padding:2.5px 9px}
.mix-bar{display:flex;height:8px;border-radius:4px;overflow:hidden;margin:10px 0 4px;background:var(--surface-3)}
.mix-bar i{height:100%}
.mix-legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--text-2)}
.mix-legend span{display:inline-flex;align-items:center;gap:5px}
.mix-legend i{width:8px;height:8px;border-radius:3px;display:inline-block}
.tbl-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--r-m);background:var(--surface);box-shadow:var(--shadow-1)}
table.dt{width:100%;border-collapse:collapse;font-size:13.5px;min-width:560px}
table.dt th{background:var(--surface-2);text-align:left;padding:10px 14px;font-size:12.5px;color:var(--text-2);font-weight:600;white-space:nowrap}
table.dt td{padding:10px 14px;border-top:1px solid var(--line);vertical-align:top}
table.dt tr:hover td{background:#fafafc}
.td-name{font-weight:600;white-space:nowrap}
.td-sub{color:var(--text-3);font-size:12px}
.mark-ok{color:var(--green);font-weight:700}
.mark-warn{color:var(--orange);font-weight:700}
.mark-bad{color:var(--pink);font-weight:700}
.api-box{background:#1d1d1f;color:#f5f5f7;border-radius:var(--r-l);padding:26px 28px;display:flex;
  flex-wrap:wrap;gap:18px;align-items:center;justify-content:space-between}
.api-box .ab-t{font-size:15px;font-weight:700}
.api-box .ab-d{font-size:12.5px;color:#aeaeb2;margin-top:3px}
.api-box code{font-family:var(--mono);font-size:12.5px;background:rgba(255,255,255,.1);border-radius:8px;
  padding:8px 14px;color:#ffd60a;display:block;margin-top:8px;word-break:break-all}
.ab-links{display:flex;gap:10px;flex-wrap:wrap}
.ab-btn{font-size:13px;font-weight:600;color:#1d1d1f;background:#f5f5f7;border-radius:var(--pill);
  padding:9px 20px;transition:.2s;white-space:nowrap}
.ab-btn:hover{background:#fff;transform:scale(1.04)}
.ab-btn.ghost{background:transparent;color:#f5f5f7;border:1px solid rgba(255,255,255,.25)}
.ab-btn.ghost:hover{background:rgba(255,255,255,.1)}
.sec-block{padding-top:64px}
.poi-bars{display:flex;flex-direction:column;gap:7px}
.poi-bar{display:flex;align-items:center;gap:10px;font-size:13px}
.poi-bar .lb{width:96px;text-align:right;color:var(--text-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.poi-bar .track{flex:1;height:14px;background:var(--surface-2);border-radius:4px;overflow:hidden}
.poi-bar .fill{height:100%;background:linear-gradient(90deg,#ff9f0a,#ff375f);border-radius:4px}
.poi-bar .vl{width:64px;color:var(--text-2);font-size:12.5px}
.assoc-block{border:1px solid var(--line);border-radius:var(--r-m);padding:18px 20px;margin-bottom:12px;background:var(--surface-2)}
.assoc-block h4{font-size:15px;font-weight:700;display:flex;justify-content:space-between;align-items:baseline}
.assoc-block h4 small{font-size:12px;color:var(--text-3);font-weight:500}
.assoc-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.assoc-tag{font-size:12.5px;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:4px 10px;color:var(--text-2)}
.assoc-tag b{color:var(--text);font-weight:600}
.assoc-tag .w{color:var(--orange)}

/* ---------- 进场动画 ---------- */
.reveal{opacity:0;transform:translateY(26px);transition:opacity .7s cubic-bezier(.22,1,.36,1),transform .7s cubic-bezier(.22,1,.36,1)}
.reveal.in{opacity:1;transform:none}
.reveal[data-d="1"]{transition-delay:.08s}.reveal[data-d="2"]{transition-delay:.16s}
.reveal[data-d="3"]{transition-delay:.24s}.reveal[data-d="4"]{transition-delay:.32s}
@media(prefers-reduced-motion:reduce){.reveal{opacity:1;transform:none;transition:none}
  .fun-word span,.fun-word .dot{animation:none}
  .aq-file,.aq-file:hover,.aq-go,.aq-file:hover .aq-go,.api-try:hover{transform:none;transition:none;gap:6px}}

/* ---------- 省份页 ---------- */
.prov-hero{padding:calc(var(--nav-h) + 64px) 0 24px}
.prov-title{font-size:clamp(2.4rem,5.5vw,4rem);font-weight:900;letter-spacing:-.035em}
.prov-stats{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}
.doc-hero{padding:calc(var(--nav-h) + 64px) 0 10px}
.doc-body{font-size:15px;color:var(--text);line-height:1.75}
.doc-body h2{font-size:1.6rem;font-weight:800;letter-spacing:-.02em;margin:44px 0 14px}
.doc-body h3{font-size:1.15rem;font-weight:700;margin:28px 0 10px}
.doc-body p{margin:10px 0;color:var(--text-2);max-width:46em}
.doc-body ul{margin:10px 0 10px 20px;color:var(--text-2)}
.doc-body li{margin:5px 0}
.doc-body table{width:100%;border-collapse:collapse;margin:14px 0;font-size:13.5px;background:var(--surface);
  border-radius:var(--r-m);overflow:hidden;box-shadow:var(--shadow-1);border:1px solid var(--line)}
.doc-body th{background:var(--surface-2);text-align:left;padding:11px 15px;font-size:12.5px;color:var(--text-2)}
.doc-body td{padding:11px 15px;border-top:1px solid var(--line);vertical-align:top}
.doc-body code{font-family:var(--mono);font-size:12.8px;background:var(--surface-2);border-radius:6px;padding:2px 7px;color:#c2410c}
.doc-body pre.code{background:#1d1d1f;color:#f5f5f7;border-radius:var(--r-m);padding:20px 22px;overflow-x:auto;
  font-size:13px;line-height:1.7;margin:14px 0}
.doc-body pre.code code{background:transparent;color:inherit;padding:0}
.doc-body .callout{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--orange);
  border-radius:var(--r-m);padding:16px 20px;font-size:14px;color:var(--text-2);margin:16px 0}
.doc-body .callout b{color:var(--text)}
"""

# ================================================================ 交互 JS

JS = r"""(function(){
"use strict";
var nav=document.querySelector('.nav'),bar=document.querySelector('.scroll-progress');
var heroIn=document.querySelector('.hero-in');
function onScroll(){
  var y=window.scrollY||document.documentElement.scrollTop;
  if(nav)nav.classList.toggle('show',y>640);
  if(bar){var h=document.documentElement.scrollHeight-window.innerHeight;
    bar.style.width=(h>0?(y/h*100):0)+'%';}
  if(heroIn&&y<window.innerHeight*1.2){
    var p=Math.min(y/(window.innerHeight*.85),1);
    heroIn.style.transform='translateY('+(y*.32)+'px) scale('+(1-p*.14)+')';
    heroIn.style.opacity=String(1-p*.9);
  }
}
window.addEventListener('scroll',onScroll,{passive:true});onScroll();

/* 进场动画 */
var io=('IntersectionObserver'in window)?new IntersectionObserver(function(es){
  es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});
},{threshold:.08,rootMargin:'0px 0px -30px 0px'}):null;
document.querySelectorAll('.reveal').forEach(function(el){io?io.observe(el):el.classList.add('in');});

/* 数字滚动 */
function countUp(el){
  var target=parseFloat(el.getAttribute('data-count'))||0,dec=+(el.getAttribute('data-dec')||0);
  var t0=performance.now(),dur=1400;
  function step(t){
    var p=Math.min((t-t0)/dur,1),e=1-Math.pow(1-p,3);
    var v=target*e;
    el.textContent=dec?v.toFixed(dec):Math.round(v).toLocaleString('zh-CN');
    if(p<1)requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
var cio=('IntersectionObserver'in window)?new IntersectionObserver(function(es){
  es.forEach(function(e){if(e.isIntersecting){countUp(e.target);cio.unobserve(e.target);}});
},{threshold:.4}):null;
document.querySelectorAll('[data-count]').forEach(function(el){cio?cio.observe(el):
  el.textContent=(+(el.getAttribute('data-dec')||0)?(+el.getAttribute('data-count')).toFixed(+(el.getAttribute('data-dec')||0)):(+el.getAttribute('data-count')).toLocaleString('zh-CN'));});

/* 城市搜索 + 省筛选 */
var grid=document.getElementById('city-grid'),q=document.getElementById('city-q'),
    chips=document.getElementById('prov-chips'),cnt=document.getElementById('city-count');
var CITIES=[];try{CITIES=JSON.parse(document.getElementById('cities-data').textContent);}catch(e){}
var curProv='全部';
function renderCities(){
  if(!grid)return;
  var kw=(q&&q.value||'').trim().toLowerCase(),n=0,frag=document.createDocumentFragment();
  CITIES.forEach(function(c){
    var okP=curProv==='全部'||c.province===curProv;
    var okK=!kw||c.city.toLowerCase().indexOf(kw)>=0||c.province.toLowerCase().indexOf(kw)>=0;
    if(!okP||!okK)return;n++;
    var el=document.createElement('a');
    el.className='city-card';el.href=c.page;
    var gd='';
    ['S','A','B','C'].forEach(function(g){var v=c.grades[g]||0;
      if(v>0)gd+='<i class="g-'+g.toLowerCase()+'" style="width:'+(v/Math.max(c.districts||1,1)*100)+'%" title="'+g+'级 '+v+' 个"></i>';});
    el.innerHTML='<div class="cc-top"><span class="cc-name">'+esc(c.city)+'</span><span class="cc-prov">'+esc(c.province)+'</span></div>'
      +'<div class="cc-poi"><b>'+(c.poi||0).toLocaleString('zh-CN')+'</b> POI · 商圈 <b>'+(c.districts||0)+'</b> 处</div>'
      +'<div class="gradebar">'+gd+'</div>'
      +'<div class="cc-dims">'
      +dim(c.dims.food,'美食')+dim(c.dims.district,'商圈')+dim(c.dims.leisure,'休闲')
      +dim(c.dims.kids,'儿童')+dim(c.dims.hotel,'酒店')+dim(c.dims.product,'特产')
      +'</div><div class="cc-foot"><span class="cc-go">进入城市</span></div>';
    frag.appendChild(el);
  });
  grid.innerHTML='';
  if(n===0){grid.innerHTML='<div class="empty-hint">没有匹配的城市，换个关键词试试</div>';}
  else grid.appendChild(frag);
  if(cnt)cnt.textContent=n;
  function dim(v,l){return v>0?'<span class="dim-tag">'+l+' '+v+'</span>':'';}
}
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
if(q)q.addEventListener('input',renderCities);
if(chips)chips.addEventListener('click',function(e){
  var b=e.target.closest('.chip');if(!b)return;
  chips.querySelectorAll('.chip').forEach(function(x){x.classList.remove('on');});
  b.classList.add('on');curProv=b.getAttribute('data-prov');renderCities();
});
/* 随机城市 */
var dice=document.getElementById('dice');
if(dice)dice.addEventListener('click',function(){
  var c=CITIES[Math.floor(Math.random()*CITIES.length)];
  if(c)location.href=c.page;
});
/* "/" 聚焦搜索 */
document.addEventListener('keydown',function(e){
  if(e.key==='/'&&document.activeElement!==q){e.preventDefault();if(q)q.focus();}
});

/* 商圈评级筛选 */
var dgrid=document.getElementById('dist-grid'),dchips=document.getElementById('dist-chips');
if(dgrid){
  var DTOP=[];try{DTOP=JSON.parse(document.getElementById('dist-data').textContent);}catch(e){}
  var curG='SA';
  function renderTop(){
    var frag=document.createDocumentFragment(),n=0;
    DTOP.forEach(function(d){
      if(curG.indexOf(d.grade)<0)return;n++;if(n>48)return;
      var el=document.createElement('a');el.className='dist-card';el.href=d.city_page;
      el.innerHTML='<div class="dc-head"><span class="grade-badge gb-'+d.grade.toLowerCase()+'">'+d.grade+'</span>'
        +'<span class="dc-name">'+esc(d.name)+'</span></div>'
        +'<div class="dc-meta">'+esc(d.carrier)+' · 评分 <b>'+(d.rating!=null?d.rating:'—')+'</b></div>'
        +'<div class="dc-counts"><span class="cnt">美食 <b>'+(d.food||0)+'</b></span>'
        +'<span class="cnt">休闲 <b>'+(d.leisure||0)+'</b></span>'
        +'<span class="cnt">儿童 <b>'+(d.kids||0)+'</b></span>'
        +'<span class="cnt">酒店 <b>'+(d.hotel||0)+'</b></span></div>'
        +'<div class="dc-city">'+esc(d.city)+' · '+esc(d.province)+'</div>';
      frag.appendChild(el);
    });
    dgrid.innerHTML='';dgrid.appendChild(frag);
  }
  if(dchips)dchips.addEventListener('click',function(e){
    var b=e.target.closest('.chip');if(!b)return;
    dchips.querySelectorAll('.chip').forEach(function(x){x.classList.remove('on');});
    b.classList.add('on');curG=b.getAttribute('data-g');renderTop();
  });
  renderTop();
}

/* 城市页：图片失败降级 + 复制链接 + 锚点高亮 */
document.querySelectorAll('.food-img img').forEach(function(img){
  img.addEventListener('error',function(){img.style.display='none';});
});
document.querySelectorAll('[data-copy]').forEach(function(btn){
  btn.addEventListener('click',function(){
    var txt=btn.getAttribute('data-copy');
    function done(){btn.textContent='已复制';setTimeout(function(){btn.textContent='复制';},1600);}
    if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(done,done);}
    else{var ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);
      ta.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);done();}
  });
});
var anchors=document.querySelectorAll('.anchor-nav a'),secs=[];
anchors.forEach(function(a){var s=document.querySelector(a.getAttribute('href'));if(s)secs.push([a,s]);});
if(secs.length){
  var aio=new IntersectionObserver(function(es){
    es.forEach(function(e){if(e.isIntersecting){
      anchors.forEach(function(a){a.classList.remove('on');});
      for(var i=0;i<secs.length;i++)if(secs[i][1]===e.target){secs[i][0].classList.add('on');break;}
    }});
  },{rootMargin:'-30% 0px -60% 0px'});
  secs.forEach(function(p){aio.observe(p[1]);});
}
/* 城市页商圈等级筛选 */
var cgrid=document.getElementById('city-dist-grid');
if(cgrid){
  var cchips=document.getElementById('city-dist-chips');
  function filt(g){
    cgrid.querySelectorAll('[data-g]').forEach(function(el){
      el.style.display=(g==='all'||el.getAttribute('data-g')===g)?'':'none';});
  }
  if(cchips)cchips.addEventListener('click',function(e){
    var b=e.target.closest('.chip');if(!b)return;
    cchips.querySelectorAll('.chip').forEach(function(x){x.classList.remove('on');});
    b.classList.add('on');filt(b.getAttribute('data-g'));
  });
}

/* 首页数据调用入口：单次 Range 请求演示
   全量 data.json 有几十 MB，但「meta + stats」集中在文件头 4KB 内，
   故只取前 8KB 即可解析出全站统计——这也是推荐的高效调用方式。 */
var tryBtn=document.getElementById('api-try'),liveBox=document.getElementById('api-live'),
    liveMeta=document.getElementById('api-live-meta'),liveGrid=document.getElementById('api-live-grid');
if(tryBtn&&liveBox&&liveGrid){
  /* 只读取响应体的第一段即取消下载，避免为看统计而拉完整个大文件 */
  function readHead(res,limit){
    if(res.body&&res.body.getReader){
      var rd=res.body.getReader(),parts=[],len=0,dec=new TextDecoder();
      return new Promise(function(resolve,reject){
        function pump(){
          rd.read().then(function(ch){
            if(ch.done){resolve(parts.join(''));return;}
            var s=dec.decode(ch.value,{stream:true});
            parts.push(s);len+=s.length;
            if(len>=limit){rd.cancel();resolve(parts.join(''));return;}
            pump();
          }).catch(reject);
        }
        pump();
      });
    }
    return res.text();
  }
  /* 从首段文本中按花括号配对提取顶层 "stats" 对象 */
  function pickStats(txt){
    var i=txt.indexOf('"stats": {');
    if(i<0)return null;
    var j=txt.indexOf('{',i+8),d=0,k=-1;
    for(var p2=j;p2<txt.length;p2++){
      var c=txt.charAt(p2);
      if(c==='{')d++;
      else if(c==='}'){d--;if(d===0){k=p2;break;}}
    }
    if(k<0)return null;
    try{return JSON.parse(txt.slice(j,k+1));}catch(e){return null;}
  }
  tryBtn.addEventListener('click',function(){
    if(!window.fetch){
      liveBox.hidden=false;liveMeta.textContent='';
      liveGrid.innerHTML='<div class="api-live-err">当前浏览器不支持 fetch，请点击上方文件卡片直接查看原文。</div>';
      return;
    }
    tryBtn.disabled=true;tryBtn.textContent='调用中…';
    var t0=performance.now();
    fetch('data.json',{headers:{'Range':'bytes=0-8191'},cache:'no-store'}).then(function(r){
      if(!r.ok&&r.status!==206)throw new Error('HTTP '+r.status);
      return readHead(r,8192).then(function(txt){return {r:r,txt:txt};});
    }).then(function(o){
      var s=pickStats(o.txt);
      if(!s)throw new Error('首段未解析到 stats');
      var ms=Math.round(performance.now()-t0);
      var served=o.txt.length;
      liveBox.hidden=false;
      liveMeta.textContent='HTTP '+o.r.status+' · '+ms+' ms · 传输 '+served+' 字节'
        +(o.r.status===206?'（Range 分段）':'（流式截断）');
      var g=s.grades||{};
      var vals=[[s.provinces,'省级行政区'],[s.cities,'已建库城市'],[s.poi_total,'POI（去重）'],
                [s.districts_total,'商圈档案'],[g.S,'S 级商圈'],[g.A,'A 级商圈'],[g.B,'B 级商圈'],[g.C,'C 级商圈']];
      liveGrid.innerHTML=vals.map(function(p){
        if(p[0]==null)return '';
        return '<div class="alv"><b>'+(typeof p[0]==='number'?p[0].toLocaleString('zh-CN'):esc(p[0]))+'</b><span>'+p[1]+'</span></div>';
      }).join('');
      tryBtn.textContent='✓ 调用成功，可再次调用';
    }).catch(function(err){
      liveBox.hidden=false;liveMeta.textContent='';
      liveGrid.innerHTML='<div class="api-live-err">现场调用未成功：'+esc(err.message||String(err))
        +'。<br>该按钮对 <code>/data.json</code> 发起 <code>Range: bytes=0-8191</code> 请求，读取首段后即取消下载，解析其中 stats；'
        +'以 file:// 本地打开时浏览器会拦截 fetch——请用 http(s) 访问，或直接点击上方文件卡片查看原文。</div>';
      tryBtn.textContent='▶ 重新调用';
    }).then(function(){tryBtn.disabled=false;});
  });
}
})();"""


# ================================================================ 公共组件

def favicon():
    return ('<link rel="icon" href="data:image/svg+xml,'
            '%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 64 64\'%3E'
            '%3Cdefs%3E%3ClinearGradient id=\'g\' x1=\'0\' y1=\'0\' x2=\'1\' y2=\'1\'%3E'
            '%3Cstop offset=\'0\' stop-color=\'%23ff9f0a\'/%3E%3Cstop offset=\'.55\' stop-color=\'%23ff375f\'/%3E'
            '%3Cstop offset=\'1\' stop-color=\'%23bf5af2\'/%3E%3C/linearGradient%3E%3C/defs%3E'
            '%3Crect width=\'64\' height=\'64\' rx=\'14\' fill=\'%231d1d1f\'/%3E'
            '%3Ctext x=\'32\' y=\'44\' font-family=\'Arial Black,Arial\' font-size=\'30\' font-weight=\'900\' '
            'text-anchor=\'middle\' fill=\'url(%23g)\'%3EF%3C/text%3E%3C/svg%3E">')


def head(title, desc, path_prefix=""):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="FUN · fun.worldstip.com">
{favicon()}
<link rel="stylesheet" href="{path_prefix}assets/style.css">
</head>
<body>
<div class="scroll-progress"></div>
<nav class="nav"><div class="nav-in">
<a class="nav-logo" href="{path_prefix}index.html">FUN<i></i></a>
<div class="nav-links">
<a href="{path_prefix}index.html#cities">城市</a>
<a href="{path_prefix}index.html#districts">商圈评级</a>
<a href="{path_prefix}api.html">数据接口</a>
<a href="{path_prefix}sources.html">数据来源</a>
<a class="nav-gh" href="{GH_REPO}" target="_blank" rel="noopener">GitHub</a>
</div></div></nav>"""


def footer(path_prefix=""):
    p = path_prefix
    return f"""<footer class="footer"><div class="foot-in">
<div><div class="foot-brand">FUN<i></i></div>
<p class="foot-desc">全国美食 × 商圈 × 娱乐探索站。覆盖 32 个省级行政区 · 389 座城市，数据驱动你的本地生活。</p></div>
<div class="foot-col"><h4>站点</h4>
<a href="{p}index.html">首页</a><a href="{p}index.html#cities">探索城市</a><a href="{p}index.html#districts">商圈评级</a></div>
<div class="foot-col"><h4>数据</h4>
<a href="{p}api.html">数据接口</a><a href="{p}sources.html">数据来源</a>
<a href="{p}data.json">data.json</a><a href="{GH_REPO}" target="_blank" rel="noopener">GitHub 仓库</a></div>
</div><div class="foot-base">数据来源：高德地图 Web 服务 POI（restapi.amap.com）· 美团 · 大众点评 · 生成时间 {GENERATED}<br>
数据仅供探索参考，营业状态与评分以各平台实时信息为准。FUN · fun.worldstip.com</div></footer>
<script src="{p}assets/app.js"></script>
</body></html>"""


def grade_badge(g):
    g = (g or "C").upper()
    return f'<span class="grade-badge gb-{g.lower()}">{esc(g)}</span>'


def mark_span(m):
    m = m or ""
    cls = "mark-ok" if m.startswith("✅") else ("mark-warn" if m.startswith("⚠") else ("mark-bad" if m.startswith("❌") else ""))
    return f'<span class="{cls}">{esc(m)}</span>' if m else ""


def fmt_int(v):
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_price(v):
    return f"¥{v:g}" if isinstance(v, (int, float)) else "—"


# ================================================================ 首页

def render_index(idx, stats, dist_top):
    cities = idx["city_index"]
    provs = sorted(set(c["province"] for c in cities))
    poi_total = idx["poi_total"]

    # 全量数据文件实测体积（入口卡片展示）
    data_jraw, data_jgz = _file_size("data.json")
    data_mraw, data_mgz = _file_size("data.md")

    # 休闲娱乐子类全国聚合（从全量 data.json 一次读取）
    leisure_agg = {}
    kids_agg = {}
    try:
        full_data = load("data.json")
        for c in full_data.get("cities", []):
            for s in c.get("leisure", {}).get("subcats", []):
                leisure_agg[s["name"]] = leisure_agg.get(s["name"], 0) + (s.get("count") or 0)
            for s in c.get("kids", {}).get("subcats", []):
                kids_agg[s["name"]] = kids_agg.get(s["name"], 0) + (s.get("count") or 0)
    except Exception:
        pass
    leisure_top = sorted(leisure_agg.items(), key=lambda x: -x[1])[:12]
    kids_top = sorted(kids_agg.items(), key=lambda x: -x[1])[:8]
    lmax = leisure_top[0][1] if leisure_top else 1
    kmax = kids_top[0][1] if kids_top else 1

    cities_js = json.dumps([{
        "city": c["city"], "province": c["province"], "poi": c["poi"],
        "page": c["page"], "districts": sum(c["grades"].values()),
        "grades": c["grades"], "dims": c["dims"],
    } for c in cities], ensure_ascii=False)
    dist_js = json.dumps(dist_top["items"][:600], ensure_ascii=False)

    chips = "".join(
        f'<button class="chip{" on" if p == "全部" else ""}" data-prov="{esc(p)}">{esc(p)}</button>'
        for p in ["全部"] + provs)

    leisure_bars = "".join(
        f'<div class="bar-row"><span class="lb">{esc(k)}</span>'
        f'<span class="track"><span class="fill" style="width:{max(v/lmax*100,2):.1f}%"></span></span>'
        f'<span class="vl">{v:,}</span></div>' for k, v in leisure_top)
    kids_bars = "".join(
        f'<div class="bar-row"><span class="lb">{esc(k)}</span>'
        f'<span class="track"><span class="fill" style="width:{max(v/kmax*100,2):.1f}%"></span></span>'
        f'<span class="vl">{v:,}</span></div>' for k, v in kids_top)

    body = f"""<header class="hero">
<div class="blob blob-a"></div><div class="blob blob-b"></div><div class="blob blob-c"></div>
<div class="hero-in">
<div class="hero-kicker">FUN<b>.</b>WORLDSTIP.COM</div>
<h1 class="fun-word" aria-label="FUN"><span class="f">F</span><span class="u">U</span><span class="n">N</span><span class="dot"></span></h1>
<p class="hero-tag">全国 <em>{stats['cities']}</em> 城 · 美食 × 商圈 × 娱乐 一站式探索</p>
<p class="hero-sub">一座城市一种玩法。从街头馆子到城市商圈，从夜市到亲子乐园——用数据找到值得去的地方。</p>
<div class="hero-cta">
<a class="btn btn-p" href="#cities">开始探索 ↓</a>
<a class="btn btn-g" href="#api">数据接口 →</a>
</div></div>
<div class="hero-hint"><span class="mouse"></span>向下滚动进入主站</div>
</header>

<main class="sheet"><div class="wrap">

<section id="stats">
<div class="sec-head reveal"><div class="sec-label">Overview</div>
<h2 class="sec-title">一座数据库，看懂中国城市生活</h2>
<p class="sec-desc">基于高德地图 POI 全量采集，辅以美团、大众点评的美食维度参考。每座城市都有独立的商圈画像与 S/A/B/C 评级。</p></div>
<div class="stats">
<div class="stat reveal" data-d="1"><b data-count="{stats['cities']}">0</b><span>已建库城市</span></div>
<div class="stat reveal" data-d="2"><b data-count="{stats['provinces']}">0</b><span>省级行政区</span></div>
<div class="stat reveal" data-d="3"><b data-count="{poi_total}">0</b><span>POI 兴趣点（去重）</span></div>
<div class="stat reveal" data-d="4"><b data-count="{stats['districts_total']}">0</b><span>商圈档案</span></div>
</div></section>

<section id="cities">
<div class="sec-head reveal"><div class="sec-label">Explore</div>
<h2 class="sec-title">探索城市</h2>
<p class="sec-desc">搜索或按省份筛选，进入任意城市的完整档案：商圈、美食、休闲娱乐、儿童亲子、酒店与特产。</p></div>
<div class="toolbar">
<div class="search-row">
<label class="search-box"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#aeaeb2" stroke-width="2.4"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
<input id="city-q" type="text" placeholder="搜索城市或省份…" autocomplete="off"><kbd>/</kbd></label>
<button class="dice" id="dice" title="随机去一座城市">🎲 随机</button>
</div>
<div class="chips" id="prov-chips">{chips}</div>
</div>
<div class="city-grid" id="city-grid"></div>
<p class="sec-desc" style="margin-top:14px">共 <b id="city-count">{len(cities)}</b> 座城市。</p>
<script type="application/json" id="cities-data">{cities_js}</script>
</section>

<section id="districts">
<div class="sec-head reveal"><div class="sec-label">Districts</div>
<h2 class="sec-title">商圈评级榜</h2>
<p class="sec-desc">按关联美食数、业态覆盖与评分综合评定 S/A/B/C 四级。这里是全国 S/A 级商圈的前列。</p></div>
<div class="chips" id="dist-chips" style="margin-bottom:18px">
<button class="chip on" data-g="SA">S + A</button><button class="chip" data-g="S">仅 S 级</button><button class="chip" data-g="A">仅 A 级</button></div>
<div class="dist-grid" id="dist-grid"></div>
<script type="application/json" id="dist-data">{dist_js}</script>
</section>

<section id="play">
<div class="sec-head reveal"><div class="sec-label">Beyond Food</div>
<h2 class="sec-title">不止于吃</h2>
<p class="sec-desc">休闲娱乐 14 子类与儿童亲子业态的全国聚合——KTV、酒吧、电影院、电玩、密室、足疗、儿童乐园、迷你动物园，一座城市一个夜晚。</p></div>
<div class="play-grid">
<div class="play-card reveal" data-d="1"><h3>🎮 休闲娱乐子类 TOP12</h3>{leisure_bars}</div>
<div class="play-card reveal" data-d="2"><h3>🧸 儿童亲子业态 TOP8</h3>{kids_bars}</div>
</div></section>

<section id="api">
<div class="sec-head reveal"><div class="sec-label">API</div>
<h2 class="sec-title">数据接口</h2>
<p class="sec-desc">全国数据整合为两个全量文件——一次请求拿全量，不必逐城拼凑。JSON 供机器与 skill 消费，Markdown 供人读与模型直读。</p></div>
<div class="api-entry reveal">
<div class="api-entry-head">
<div class="aeh-left">
<div class="aeh-kicker">DATA ENTRY · 全国全量双文件</div>
<div class="aeh-base">
<code id="api-base">https://fun.worldstip.com</code>
<button class="copy-btn" id="copy-base" type="button" data-copy="https://fun.worldstip.com">复制</button>
</div>
<p class="aeh-tip">整个数据集就是这两个文件：一次请求拿全量。若只要概览，用 <code>Range: bytes=0-8191</code> 取首段即可拿到 stats——右上按钮现场演示。</p>
</div>
<button class="api-try" id="api-try" type="button">▶ 现场调用</button>
</div>
<div class="aq-files">
<a class="aq-file" href="data.json" target="_blank" rel="noopener">
<div class="aq-file-top"><span class="aq-tag tj">JSON</span><span class="aq-size">{data_jraw} · gzip 约 {data_jgz}</span></div>
<code>/data.json</code>
<p>meta · stats · <b>32 省汇总</b> · <b>389 城全量明细</b>（商圈 / 美食 / 休闲 / 儿童 / 商场 / 特产 / 酒店 / 商圈×美食关联）· 全国美食榜 800 · S/A 商圈榜 1000。POI 为英文字段：<code>mark / name / sub / type / rating / avg / addr / img</code>。</p>
<span class="aq-go">打开 JSON →</span>
</a>
<a class="aq-file md" href="data.md" target="_blank" rel="noopener">
<div class="aq-file-top"><span class="aq-tag tm">MARKDOWN</span><span class="aq-size">{data_mraw} · gzip 约 {data_mgz}</span></div>
<code>/data.md</code>
<p>可跳转目录 + 全国统计 + 32 省索引 + <b>389 城档案全文</b>（每城 13 章）+ 接口与来源附录。人类可读，LLM / skill 可直接 ingest。</p>
<span class="aq-go">打开 Markdown →</span>
</a>
</div>
<div class="api-live" id="api-live" hidden><div class="api-live-head">GET <code>/data.json</code> · Range: bytes=0-8191 · <span id="api-live-meta"></span></div>
<div class="api-live-grid" id="api-live-grid"></div></div>
</div>
<div class="panel reveal" style="padding:0;overflow:hidden">
<table class="api-table"><thead><tr><th style="width:22%">端点</th><th style="width:12%">格式</th><th>说明</th></tr></thead><tbody>
<tr><td><code>/data.json</code></td><td>JSON</td><td>全国全量单文件：meta / stats / provinces（32 省汇总）/ cities（389 城全量明细，英文字段）/ food_top（800，已剔除住宿业主导 POI）/ districts_top（1000）</td></tr>
<tr><td><code>/data.md</code></td><td>Markdown</td><td>全国全量单文件：目录 + 统计 + 32 省索引 + 389 城档案 + 附录；与 data.json 同源同值</td></tr>
</tbody></table></div>
<div class="note-box reveal" style="margin-top:16px">
<b>调用示例</b>
<pre class="code"><code><span class="cm"># 全量一次落地（{data_jraw}，CDN 自动 gzip / br 压缩）</span>
curl -s https://fun.worldstip.com/data.json -o fun-data.json

<span class="cm"># 只要概览：stats 在文件头 4KB 内，Range 取首段即可（省 99.9% 流量）</span>
curl -s -r 0-8191 https://fun.worldstip.com/data.json

<span class="cm"># 只要某座城市（Python 标准库，json.load 直接读流）</span>
import json, urllib.request
with urllib.request.urlopen("https://fun.worldstip.com/data.json") as r:
    d = json.load(r)
yy = next(c for c in d["cities"] if c["city"] == "岳阳市")
print(yy["poi_total"], len(yy["food"]), yy["grades"])

<span class="cm"># 全国美食榜前 10（评分降序）</span>
curl -s https://fun.worldstip.com/data.json | jq '.food_top[:10]'

<span class="cm"># 人类可读全量 Markdown</span>
curl -s https://fun.worldstip.com/data.md -o fun-data.md</code></pre>
<ul><li>两个文件即完整数据集，只读、无鉴权、无速率限制，允许 CDN 长缓存；数据更新时全量刷新。</li>
<li>JSON 与 MD 由同一数据层生成，可交叉校验；字段口径见<a href="api.html" style="color:var(--blue)">接口文档</a>。</li>
<li>评分/人均为高德快照，采集时间见 data.md 各城市档案头部。</li></ul>
</div></section>

<section id="sources">
<div class="sec-head reveal"><div class="sec-label">Sources</div>
<h2 class="sec-title">数据来源</h2>
<p class="sec-desc">三层数据源各司其职：高德提供全量 POI 底账，美团与大众点评补充美食消费维度视角。</p></div>
<div class="src-grid">
<div class="src-card reveal" data-d="1"><div class="src-ico" style="background:linear-gradient(135deg,#0091ff,#00c6ff)">高</div>
<div class="role">Primary · 全量底账</div><h3>高德地图 POI</h3>
<p>32 个省级行政区 / 389 城全量采集：商圈载体、餐饮、休闲娱乐、儿童亲子、酒店、特产六大维度，约 60 个查询面/城，POI 去重后 {poi_total:,} 条。</p>
<div class="src-links"><a href="https://lbs.amap.com/" target="_blank" rel="noopener">开放平台 →</a></div></div>
<div class="src-card reveal" data-d="2"><div class="src-ico" style="background:linear-gradient(135deg,#ffd100,#ff9f0a)">美</div>
<div class="role">Food · 消费视角</div><h3>美团</h3>
<p>美食榜单与团购消费维度参考。每座城市页提供美团搜索直达链接，按城市 + 关键词检索实时结果。</p>
<div class="src-links"><a href="https://www.meituan.com/" target="_blank" rel="noopener">meituan.com →</a></div></div>
<div class="src-card reveal" data-d="3"><div class="src-ico" style="background:linear-gradient(135deg,#ff375f,#ff6482)">点</div>
<div class="role">Food · 评价视角</div><h3>大众点评</h3>
<p>必吃榜与用户评价维度参考。每座城市页提供点评城市美食频道直达链接（/城市拼音/ch10）。</p>
<div class="src-links"><a href="https://www.dianping.com/" target="_blank" rel="noopener">dianping.com →</a></div></div>
</div></section>

</div></main>{footer()}"""

    return head(f"FUN · 全国美食 × 商圈 × 娱乐探索站",
                f"覆盖 {stats['provinces']} 省级单位 / {stats['cities']} 城，{poi_total:,} POI。商圈评级、城市美食、休闲娱乐、儿童亲子、酒店特产，JSON/MD 双格式开放。") + body


# ================================================================ 城市页

MIX_COLORS = {"美食": "#ff9f0a", "休闲娱乐": "#bf5af2", "儿童娱乐": "#30d158", "酒店配套": "#0071e3"}


def render_city(rec):
    c, prov = rec["city"], rec["province"]
    cred = rec.get("credibility", {})
    dims = cred.get("dims", {})
    ov = rec.get("overview", {})
    admin = ov.get("admin", {})
    adcode = rec.get("adcode", "")
    urls = rec.get("urls", {})
    ext = rec.get("external", {})
    districts = rec.get("districts", [])
    grades = {"S": 0, "A": 0, "B": 0, "C": 0}
    for d in districts:
        if d.get("grade") in grades:
            grades[d["grade"]] += 1

    # ---- 指标 chips
    chips = [
        ("POI 总量", fmt_int(rec.get("poi_total"))),
        ("商圈档案", fmt_int(len(districts))),
        ("美食", fmt_int(dims.get("美食", 0))),
        ("休闲娱乐", fmt_int(dims.get("休闲娱乐", 0))),
        ("儿童娱乐", fmt_int(dims.get("儿童娱乐", 0))),
        ("酒店", fmt_int(dims.get("酒店", 0))),
        ("特产", fmt_int(dims.get("特产", 0))),
    ]
    metric_html = "".join(f'<div class="metric-chip"><b>{esc(v)}</b>{esc(k)}</div>' for k, v in chips)

    # ---- 可信度
    cred_html = f"""<div class="kv">
<div><b>{cred.get('poi_total', '—')}</b>POI 去重总数</div>
<div><b>{esc(cred.get('rated_ratio', '—'))}</b>有评分比例</div>
<div><b>{cred.get('warnings', 0)}</b>采集告警</div>
<div><b>{esc(' + '.join(str(w) for w in rec.get('waves', [])) or '—')}</b>查询波次</div>
</div>"""

    # ---- 区县 POI 分布
    dist_poi = ov.get("district_poi", [])
    if dist_poi:
        mx = max((d.get("poi") or 0) for d in dist_poi) or 1
        poi_bars = "".join(
            f'<div class="poi-bar"><span class="lb">{esc(d.get("district", ""))}</span>'
            f'<span class="track"><span class="fill" style="width:{max((d.get("poi") or 0)/mx*100,1.5):.1f}%"></span></span>'
            f'<span class="vl">{d.get("poi", 0):,} · {esc(d.get("ratio", ""))}</span></div>'
            for d in dist_poi)
    else:
        poi_bars = '<p class="p-desc">暂无区县分布数据。</p>'
    carriers = ov.get("carrier_types", [])
    carrier_html = "".join(
        f'<span class="fact">{esc(t.get("type", ""))} <b>{t.get("count", 0)}</b></span>' for t in carriers)

    # ---- 商圈档案（含详情）
    dist_cards = []
    for d in districts:
        det = d.get("detail") or {}
        counts = f'<div class="dc-counts"><span class="cnt">美食 <b>{d.get("food") or 0}</b></span>' \
                 f'<span class="cnt">休闲 <b>{d.get("leisure") or 0}</b></span>' \
                 f'<span class="cnt">儿童 <b>{d.get("kids") or 0}</b></span>' \
                 f'<span class="cnt">酒店 <b>{d.get("hotel") or 0}</b></span></div>'
        facts = []
        if det.get("address"):
            facts.append(f'<span class="fact">📍 {esc(det["address"])}</span>')
        if det.get("bandwidth"):
            facts.append(f'<span class="fact">💰 {esc(det["bandwidth"])}</span>')
        if det.get("axis"):
            facts.append(f'<span class="fact">🛣 {esc(det["axis"])}</span>')
        if det.get("criteria"):
            facts.append(f'<span class="fact">📏 {esc(det["criteria"])}</span>')
        # 业态混排条
        mixes = det.get("mixes") or []
        mix_html = ""
        if mixes:
            tot = sum(m.get("count") or 0 for m in mixes) or 1
            seg = "".join(
                f'<i style="width:{max((m.get("count") or 0)/tot*100,0):.1f}%;background:{MIX_COLORS.get(m.get("type"), "#8e8e93")}" title="{esc(m.get("type"))} {m.get("count")}"></i>'
                for m in mixes)
            leg = "".join(
                f'<span><i style="background:{MIX_COLORS.get(m.get("type"), "#8e8e93")}"></i>{esc(m.get("type"))} {m.get("count")}</span>'
                for m in mixes)
            mix_html = f'<div class="mix-bar">{seg}</div><div class="mix-legend">{leg}</div>'
        tops = []
        for m in mixes:
            if m.get("type") == "美食" and m.get("top"):
                tops = m["top"][:4]
        top_html = f'<div class="assoc-tags" style="margin-top:8px">' + "".join(
            f'<span class="assoc-tag">{esc(t)}</span>' for t in tops) + "</div>" if tops else ""
        dist_cards.append(f"""<div class="dist-detail" data-g="{esc(d.get("grade", "C"))}">
<div class="dd-head">{grade_badge(d.get("grade"))}<span class="dd-name">{esc(d.get("name", ""))}</span>
<span class="dd-sub" style="margin-left:auto">{esc(d.get("carrier", ""))} · 评分 {d.get("rating") if d.get("rating") is not None else "—"}</span></div>
{counts}
<div class="dd-facts">{''.join(facts)}</div>
{mix_html}{top_html}</div>""")
    dist_chips = '<button class="chip on" data-g="all">全部</button>' + "".join(
        f'<button class="chip" data-g="{g}">{g} 级 · {grades[g]}</button>' for g in ("S", "A", "B", "C") if grades[g])
    dist_html = f'<div class="chips" id="city-dist-chips" style="margin-bottom:16px">{dist_chips}</div>' \
                f'<div id="city-dist-grid">{"".join(dist_cards)}</div>'

    # ---- 通用表格渲染
    def table(rows, cols, empty="暂无数据"):
        if not rows:
            return f'<p class="p-desc">{empty}</p>'
        th = "".join(f"<th>{esc(t)}</th>" for _, t in cols)
        body = []
        for r in rows:
            tds = []
            for key, _ in cols:
                v = r.get(key, "")
                if key == "标记":
                    tds.append(f"<td>{mark_span(v)}</td>")
                elif key in ("评分",):
                    tds.append(f'<td><b>{esc(v)}</b></td>')
                elif key in ("人均",):
                    tds.append(f'<td style="color:var(--orange);font-weight:600">{esc(v)}</td>')
                elif key in ("名称", "店名", "商圈名"):
                    tds.append(f'<td class="td-name">{esc(v)}</td>')
                elif key in ("类型", "子类", "载体类型"):
                    tds.append(f'<td class="td-sub">{esc(v)}</td>')
                else:
                    tds.append(f"<td>{esc(v)}</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        return f'<div class="tbl-wrap"><table class="dt"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'

    leisure = rec.get("leisure", {})
    lsub = "".join(f'<span class="fact">{esc(s.get("name", ""))} <b>{s.get("count", 0)}</b></span>'
                   for s in leisure.get("subcats", []))
    l_rows = [{k: r.get(k, "") for k in ("标记", "名称", "子类", "评分", "人均", "地址")}
              for r in leisure.get("list", [])[:150]]
    kids = rec.get("kids", {})
    ksub = "".join(f'<span class="fact">{esc(s.get("name", ""))} <b>{s.get("count", 0)}</b></span>'
                   for s in kids.get("subcats", []))
    k_cols = [("标记", "标记"), ("名称", "名称"), ("子类", "子类"), ("位置", "位置"), ("评分", "评分"), ("地址", "地址")]
    k_rows = [{k2: r.get(k2, "") for k2, _ in k_cols} for r in kids.get("list", [])[:150]]
    m_rows = [{k: r.get(k, "") for k in ("标记", "名称", "载体类型", "评分", "场内儿童娱乐", "关联美食", "地址")}
              for r in rec.get("malls", [])[:120]]
    f_rows = [{k: r.get(k, "") for k in ("标记", "店名", "类型", "评分", "人均", "地址")}
              for r in rec.get("food", [])]
    x_rows = [{k: r.get(k, "") for k in ("店名", "来源查询面", "评分", "人均", "地址", "备注")}
              for r in rec.get("xiaocan", [])[:120]]
    s_rows = [{k: r.get(k, "") for k in ("标记", "名称", "类型", "评分", "地址")}
              for r in rec.get("specialties", [])[:120]]
    h_rows = [{k: r.get(k, "") for k in ("标记", "名称", "类型", "评分", "地址")}
              for r in rec.get("hotels", [])[:150]]

    # ---- 美食图片卡（前 60 张带图的）
    food_cards = []
    for r in rec.get("food", []):
        if len(food_cards) >= 60:
            break
        if not r.get("image"):
            continue
        food_cards.append(f"""<div class="food-card reveal" data-d="{len(food_cards)%4+1}">
<div class="food-img"><img src="{esc(r['image'])}" alt="{esc(r.get('店名',''))}" loading="lazy" decoding="async">
<div class="ph">{esc((r.get('店名') or '?')[0])}</div><span class="rt">★ {esc(r.get('评分',''))}</span></div>
<div class="food-body"><div class="food-name">{esc(r.get('店名', ''))}</div>
<div class="food-type">{esc(r.get('类型', '') or '')}</div>
<div class="food-foot"><span class="food-avg">{esc(r.get('人均') or '—')}</span>
<span class="td-sub">{esc((r.get('地址') or '')[:22])}</span></div></div></div>""")
    food_img_html = f'<div class="food-grid">{"".join(food_cards)}</div>' if food_cards else ""

    # ---- §9 关联
    assoc_html = ""
    for a in rec.get("assoc", [])[:14]:
        tags = "".join(
            f'<span class="assoc-tag">{esc(it.get("name", ""))}'
            + (f' <b>{it.get("rating")}</b>' if it.get("rating") else "")
            + (' <span class="w">⚠</span>' if it.get("how") == "距离就近" else "")
            + "</span>"
            for it in a.get("items", [])[:10])
        assoc_html += f"""<div class="assoc-block"><h4>{esc(a.get("district", ""))}<small>{a.get("count", 0)} 家关联 · ⚠ = 仅距离就近</small></h4>
<div class="assoc-tags">{tags}</div></div>"""

    # ---- 锚点导航
    anchors = [("sec-cred", "可信度"), ("sec-ov", "总览"), ("sec-dist", f"商圈 {len(districts)}"),
               ("sec-leisure", f"休闲 {len(leisure.get('list', []))}"), ("sec-kids", f"儿童 {len(kids.get('list', []))}"),
               ("sec-mall", f"商场 {len(rec.get('malls', []))}"), ("sec-food", f"美食 {len(rec.get('food', []))}"),
               ("sec-xiaocan", "小店"), ("sec-spec", f"特产 {len(rec.get('specialties', []))}"),
               ("sec-assoc", "美食×商圈"), ("sec-hotel", f"酒店 {len(rec.get('hotels', []))}")]
    anchor_html = '<div class="anchor-nav"><div class="anchor-nav-in">' + "".join(
        f'<a href="#{i}">{esc(t)}</a>' for i, t in anchors) + "</div></div>"

    api_url = "https://fun.worldstip.com/data.json"
    md_url = "https://fun.worldstip.com/data.md"

    # 预计算头部文本（避免 f-string 内嵌引号冲突）
    admin_level = ""
    if admin.get("所属"):
        admin_level = " · " + esc(admin["所属"].split("·")[-1].strip())
    sub_line = (f"{esc(c)}市（区划代码 {esc(adcode)}）· 下级区县 {esc(admin.get('下级区县', '—'))} 个 · "
                f"街道/镇/乡 {esc(admin.get('街道/镇/乡', '—'))} 个 · 数据更新于 {esc(rec.get('updated') or '—')}。")
    prov_chip = f"{esc(prov)}{admin_level}"

    body = f"""<main>
<div class="city-hero"><div class="wrap">
<a class="back-link" href="../index.html#cities">← 返回城市列表</a>
<div class="city-title-row"><h1 class="city-title">{esc(c)}</h1>
<span class="city-prov-chip">{prov_chip}</span></div>
<p class="city-sub">{sub_line}</p>
<div class="chip-row">{metric_html}</div>
<div class="chip-row">
<a class="btn btn-p" href="{esc(ext.get('meituan_search', '#'))}" target="_blank" rel="noopener">美团搜「{esc(c)}美食」</a>
<a class="btn btn-g" href="{esc(ext.get('dianping_food', '#'))}" target="_blank" rel="noopener">大众点评 · {esc(c)}美食频道</a>
</div></div></div>
{anchor_html}
<div class="wrap" style="padding-top:34px">

<div class="api-box reveal" id="sec-api">
<div><div class="ab-t">本页数据的机器可读版本</div>
<div class="ab-d">全国数据已整合为两个全量文件，本市档案包含在内——一次请求拿全量，不必逐城拼凑</div>
<code>https://fun.worldstip.com/data.json</code></div>
<div class="ab-links">
<a class="ab-btn" href="../data.json" target="_blank" rel="noopener">全量 JSON（含本市）</a>
<a class="ab-btn ghost" href="../data.md" target="_blank" rel="noopener">全量 Markdown</a>
<button class="ab-btn ghost" data-copy="https://fun.worldstip.com/data.json">复制 JSON 地址</button>
</div></div>

<section class="sec-block" id="sec-cred">
<div class="sec-head reveal"><div class="sec-label">Credibility</div><h2 class="sec-title">数据可信度</h2></div>
<div class="panel reveal">{cred_html}</div></section>

<section class="sec-block" id="sec-ov">
<div class="sec-head reveal"><div class="sec-label">Overview</div><h2 class="sec-title">城市总览</h2>
<p class="sec-desc">POI 在区县间的分布，与商圈载体类型构成。</p></div>
<div class="panel reveal"><h3>区县 POI 分布</h3><div class="poi-bars">{poi_bars}</div>
<h3 style="margin-top:22px">商圈载体类型（{len(carriers)} 类）</h3>
<div class="dd-facts" style="margin-top:8px">{carrier_html}</div></div></section>

<section class="sec-block" id="sec-dist">
<div class="sec-head reveal"><div class="sec-label">Districts</div><h2 class="sec-title">商圈档案</h2>
<p class="sec-desc">S：关联美食 ≥20 家且均分 ≥4.3、覆盖 ≥3 类业态；A：美食 ≥10 家且均分 ≥4.0、覆盖 ≥2 类；B：美食 ≥5 家或单业态 ≥10 家；C：数据稀薄待人工补充。</p></div>
{dist_html}</section>

<section class="sec-block" id="sec-leisure">
<div class="sec-head reveal"><div class="sec-label">Leisure</div><h2 class="sec-title">休闲娱乐</h2>
<p class="sec-desc">KTV/量贩KTV、夜店、酒吧、清吧、游乐场、卡丁车、体育馆、足疗按摩、电影院、游戏厅等 14 子类。</p></div>
<div class="panel reveal"><div class="dd-facts">{lsub}</div>
<div style="margin-top:14px">{table(l_rows, [("标记", "标记"), ("名称", "名称"), ("子类", "子类"), ("评分", "评分"), ("人均", "人均"), ("地址", "地址")])}</div>
<p class="p-desc" style="margin-top:10px">仅显示前 150 家，全量见 JSON 接口。</p></div></section>

<section class="sec-block" id="sec-kids">
<div class="sec-head reveal"><div class="sec-label">Kids</div><h2 class="sec-title">儿童与亲子娱乐</h2>
<p class="sec-desc">儿童乐园、电玩中心、迷你游乐场、迷你动物园/萌宠；「场内」可顺路，「独立」需单独规划。</p></div>
<div class="panel reveal"><div class="dd-facts">{ksub}</div>
<div style="margin-top:14px">{table(k_rows, k_cols)}</div></div></section>

<section class="sec-block" id="sec-mall">
<div class="sec-head reveal"><div class="sec-label">Malls</div><h2 class="sec-title">综合体与商场</h2></div>
<div class="panel reveal">{table(m_rows, [("标记", "标记"), ("名称", "名称"), ("载体类型", "载体类型"), ("评分", "评分"), ("场内儿童娱乐", "场内儿童"), ("关联美食", "关联美食"), ("地址", "地址")])}</div></section>

<section class="sec-block" id="sec-food">
<div class="sec-head reveal"><div class="sec-label">Food</div><h2 class="sec-title">本地美食与特色美食</h2>
<p class="sec-desc">标记口径：✅A 评分 ≥4.6 且带本地/老字号语义；✅A- 评分 ≥4.6；✅B 4.3–4.6；⚠️ 3.5–4.3 或无评分；❌ &lt;3.5 或无地址。</p></div>
{food_img_html}
<div class="panel reveal" style="margin-top:16px">{table(f_rows, [("标记", "标记"), ("店名", "店名"), ("类型", "类型"), ("评分", "评分"), ("人均", "人均"), ("地址", "地址")])}
<p class="p-desc" style="margin-top:10px">全量 {len(rec.get('food', []))} 家，含图片的已在上方卡片展示（前 60 张）。</p></div></section>

<section class="sec-block" id="sec-xiaocan">
<div class="sec-head reveal"><div class="sec-label">Local Gems</div><h2 class="sec-title">苍蝇馆 / 小店候选</h2>
<p class="sec-desc">不凭空判定：命中「苍蝇馆」关键词或店名含小馆/排挡/家常/私房/土菜/大排档等小店语义方列入。</p></div>
<div class="panel reveal">{table(x_rows, [("店名", "店名"), ("来源查询面", "来源"), ("评分", "评分"), ("人均", "人均"), ("地址", "地址"), ("备注", "备注")])}</div></section>

<section class="sec-block" id="sec-spec">
<div class="sec-head reveal"><div class="sec-label">Specialties</div><h2 class="sec-title">知名特产</h2></div>
<div class="panel reveal">{table(s_rows, [("标记", "标记"), ("名称", "名称"), ("类型", "类型"), ("评分", "评分"), ("地址", "地址")])}</div></section>

<section class="sec-block" id="sec-assoc">
<div class="sec-head reveal"><div class="sec-label">Cross</div><h2 class="sec-title">美食 × 商圈 关联</h2>
<p class="sec-desc">① 名称互证；② 距离就近（≤600m 且同区县）。仅靠距离的关联标 ⚠。</p></div>
{assoc_html or '<p class="p-desc">暂无关联数据。</p>'}</section>

<section class="sec-block" id="sec-hotel">
<div class="sec-head reveal"><div class="sec-label">Hotels</div><h2 class="sec-title">酒店配套</h2></div>
<div class="panel reveal">{table(h_rows, [("标记", "标记"), ("名称", "名称"), ("类型", "类型"), ("评分", "评分"), ("地址", "地址")])}</div></section>

</div></main>{footer(path_prefix='../')}"""

    return head(f"{c} · {prov} 美食与商圈档案 · FUN",
                f"{prov}{c}的完整本地档案：商圈评级、城市美食、休闲娱乐、儿童亲子、酒店与特产，JSON/MD 数据接口开放。",
                path_prefix="../") + body


# ================================================================ 省份页

def render_province(prov, cities, stats):
    def dim(v, l):
        return f'<span class="dim-tag">{l} {v}</span>' if v else ""

    s = sum(c["grades"]["S"] for c in cities)
    a = sum(c["grades"]["A"] for c in cities)
    b = sum(c["grades"]["B"] for c in cities)
    cc = sum(c["grades"]["C"] for c in cities)
    poi = sum(c["poi"] or 0 for c in cities)
    cards = []
    for c in sorted(cities, key=lambda x: -(x["poi"] or 0)):
        gd = ""
        for g in ("S", "A", "B", "C"):
            v = c["grades"][g]
            if v:
                gd += f'<i class="g-{g.lower()}" style="width:{v/max(sum(c["grades"].values()),1)*100}%" title="{g}级 {v} 个"></i>'
        cards.append(f"""<a class="city-card reveal" href="../{esc(c['page'])}" data-d="{len(cards)%4+1}">
<div class="cc-top"><span class="cc-name">{esc(c['city'])}</span><span class="cc-poi">{fmt_int(c['poi'])} POI</span></div>
<div class="gradebar">{gd}</div>
<div class="cc-dims">{dim(c['dims']['food'],'美食')}{dim(c['dims']['district'],'商圈')}{dim(c['dims']['leisure'],'休闲')}{dim(c['dims']['kids'],'儿童')}{dim(c['dims']['hotel'],'酒店')}{dim(c['dims']['product'],'特产')}</div>
<div class="cc-foot"><span class="cc-go">进入城市</span></div></a>""")
    body = f"""<main>
<div class="prov-hero"><div class="wrap">
<a class="back-link" href="../index.html#cities">← 返回全国</a>
<h1 class="prov-title">{esc(prov)}</h1>
<div class="prov-stats">
<div class="metric-chip"><b>{len(cities)}</b>已建库城市</div>
<div class="metric-chip"><b>{poi:,}</b>POI（去重）</div>
<div class="metric-chip"><b>{s}</b>S 级商圈</div>
<div class="metric-chip"><b>{a}</b>A 级商圈</div>
<div class="metric-chip"><b>{b + cc}</b>B/C 级商圈</div>
</div></div></div>
<div class="wrap" style="padding-top:26px">
<h2 style="font-size:1.4rem;font-weight:800;letter-spacing:-.02em;margin-bottom:16px">城市列表</h2>
<div class="city-grid">{''.join(cards)}</div>
</div></main>{footer(path_prefix='../')}"""

    return head(f"{prov} · 美食与商圈 · FUN", f"{prov}下辖城市的本地档案总览：商圈评级、美食、休闲娱乐、儿童亲子、酒店与特产。",
                path_prefix="../") + body


# 全国 34 个省级行政区（含暂无建库城市的特别行政区，用于空态页与 sitemap 全覆盖）
ALL_PROVINCES = [
    "北京市", "天津市", "河北省", "山西省", "内蒙古自治区", "辽宁省", "吉林省", "黑龙江省",
    "上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省", "河南省",
    "湖北省", "湖南省", "广东省", "广西壮族自治区", "海南省", "重庆市", "四川省", "贵州省",
    "云南省", "西藏自治区", "陕西省", "甘肃省", "青海省", "宁夏回族自治区", "新疆维吾尔自治区",
    "台湾省", "香港特别行政区", "澳门特别行政区",
]


def render_province_empty(prov, stats):
    """暂无建库城市数据的省级行政区空态页（如香港/澳门）：路线可达、文案诚实、导流回主站。"""
    body = f"""<main>
<div class="prov-hero"><div class="wrap">
<a class="back-link" href="../index.html#cities">← 返回全国</a>
<h1 class="prov-title">{esc(prov)}</h1>
<div class="prov-stats">
<div class="metric-chip"><b>0</b>已建库城市</div>
<div class="metric-chip"><b>—</b>POI（去重）</div>
</div></div></div>
<div class="wrap" style="padding-top:8px">
<div class="panel reveal" style="max-width:760px;text-align:center;padding:52px 28px">
<div style="font-size:44px;line-height:1;margin-bottom:14px">🗺️</div>
<h2 style="font-size:1.35rem;font-weight:800;letter-spacing:-.02em;margin-bottom:10px">暂无建库城市数据</h2>
<p style="color:var(--text-2);max-width:34em;margin:0 auto 8px">当前数据层覆盖全国 {stats['cities']} 座城市 / {stats['provinces']} 个省级行政区，
{esc(prov)}暂未纳入采集范围，因此没有可展示的商圈、美食与娱乐档案。</p>
<p style="color:var(--text-3);font-size:13.5px;max-width:34em;margin:0 auto 24px">我们只呈现真实采集到的数据，不用占位内容充数。
后续采集波次覆盖后将自动生成本省全部城市档案。</p>
<div class="hero-cta" style="justify-content:center">
<a class="btn btn-p" href="../index.html#cities">探索已建库城市</a>
<a class="btn btn-g" href="../api.html">查看数据接口</a>
</div></div></div></main>{footer(path_prefix='../')}"""

    return head(f"{prov} · 暂无建库数据 · FUN",
                f"{prov}暂未纳入采集范围。当前数据层覆盖全国 {stats['cities']} 城美食与商圈档案。",
                path_prefix="../") + body


# ================================================================ API 文档页

def render_api_doc(idx, stats):
    jraw, jgz = _file_size("data.json")
    mraw, mgz = _file_size("data.md")

    body = f"""<main>
<div class="doc-hero"><div class="wrap">
<a class="back-link" href="index.html">← 返回首页</a>
<div class="sec-label">API</div>
<h1 class="sec-title" style="font-size:clamp(2.2rem,5vw,3.4rem)">数据接口文档</h1>
<p class="sec-desc">全国数据整合为两个全量文件——一次请求拿全量，不必逐城拼凑。所有端点只读、无鉴权、可被 CDN 缓存，适合 skill / agent / 前端直接消费。</p>
</div></div>
<div class="wrap doc-body" style="padding-top:30px;padding-bottom:10px">

<h2>端点总览</h2>
<table><thead><tr><th>端点</th><th>格式</th><th>内容</th><th>体积</th></tr></thead><tbody>
<tr><td><code>/data.json</code></td><td>JSON</td><td>全国全量单文件：meta / stats / provinces（32 省汇总）/ <b>cities（389 城全量明细）</b> / food_top（800）/ districts_top（1000）</td><td>{jraw} · gzip 约 {jgz}</td></tr>
<tr><td><code>/data.md</code></td><td>Markdown</td><td>全国全量单文件：目录 + 统计 + 32 省索引 + 389 城档案（每城 13 章）+ 接口与来源附录</td><td>{mraw} · gzip 约 {mgz}</td></tr>
</tbody></table>

<h2><code>/data.json</code> 顶层结构</h2>
<pre class="code"><code>{{
  "meta":  {{ "name": "FUN 全国美食×商圈×娱乐数据库", "version": "v0.9.0",
            "generated": "...", "home": "https://fun.worldstip.com", "schema": {{...}} }},
  "stats": {{ "provinces": 32, "cities": 389, "poi_total": 328980,
            "districts_total": 15405, "grades": {{"S": 231, "A": 3345, "B": 5300, "C": 6529}} }},
  "provinces": [ {{"province": "湖南省", "cities": 14, "poi": 11628,
                  "districts": 428, "grades": {{...}}, "page": "provinces/湖南省.html"}} ],  <span class="cm">// ×32</span>
  "cities": [ {{ <span class="cm">// ×389，字段见下</span> }} ],
  "food_top": [ {{"name": "...", "type": "餐饮服务;中餐厅;...", "rating": 4.8,
                 "avg": 63, "address": "...", "image": "https://store.is.autonavi.com/...",
                 "city": "岳阳市", "province": "湖南省", "city_page": "cities/430600.html"}} ],  <span class="cm">// ×800，已剔除住宿业主导 POI</span>
  "districts_top": [ {{"name": "...", "grade": "S", "carrier": "...", "rating": 4.8,
                      "food": 120, "leisure": 88, "city": "...", "province": "...", "city_page": "..."}} ]  <span class="cm">// ×1000，S/A 级</span>
}}</code></pre>

<h2>城市记录字段（<code>cities[]</code>）</h2>
<table><thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead><tbody>
<tr><td><code>city / province / adcode</code></td><td>str</td><td>城市名 / 所属省 / 高德区划代码（页面文件名同 adcode）</td></tr>
<tr><td><code>poi_total / district_count</code></td><td>int</td><td>去重 POI 总数 / 商圈档案数</td></tr>
<tr><td><code>waves / updated</code></td><td>array / str</td><td>采集波次（1 美食商圈 / 2 酒店亲子商场 / 3 休闲全维度）/ 采集时间</td></tr>
<tr><td><code>credibility</code></td><td>obj</td><td>§0 可信度：poi_total / rated_ratio / warnings / dims 六维计数</td></tr>
<tr><td><code>overview</code></td><td>obj</td><td>§1 总览：行政层级 / 各区县 POI 分布 / 载体类型分布</td></tr>
<tr><td><code>districts</code></td><td>array</td><td>§2 商圈档案：name / grade(S·A·B·C) / carrier / rating / food / leisure / kids / hotel / detail</td></tr>
<tr><td><code>grades</code></td><td>obj</td><td>本市商圈评级计数 {{S, A, B, C}}</td></tr>
<tr><td><code>food / xiaocan</code></td><td>array</td><td>§6 美食 / §7 小店候选（POI 记录，字段见下）</td></tr>
<tr><td><code>leisure / kids</code></td><td>obj</td><td>§3 / §4：{{"subcats": [{{name, count}}], "list": [POI]}}</td></tr>
<tr><td><code>malls / specialties / hotels</code></td><td>array</td><td>§5 综合体商场 / §8 特产 / §10 酒店</td></tr>
<tr><td><code>assoc</code></td><td>array</td><td>§9 商圈×美食关联：{{district, count, items: [{{name, how, dist, rating, src}}]}}</td></tr>
<tr><td><code>queries / external</code></td><td>array / obj</td><td>§11 原始查询面统计 / 美团·大众点评城市外链</td></tr>
<tr><td><code>page</code></td><td>str</td><td>城市页相对地址 <code>cities/&lt;adcode&gt;.html</code></td></tr>
</tbody></table>

<h2>POI 记录字段（各明细表内）</h2>
<table><thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead><tbody>
<tr><td><code>mark</code></td><td>str</td><td>商圈携带标记，如 <code>✅A-</code>；空 = 不属任何已评商圈</td></tr>
<tr><td><code>name</code></td><td>str</td><td>店名 / 名称</td></tr>
<tr><td><code>sub</code></td><td>str</td><td>细分 / 备注 / 载体类型 / 来源查询面（各节表头归一）</td></tr>
<tr><td><code>type</code></td><td>str</td><td>高德多段类型串，<code>;</code> 分隔，首段为主类（如 <code>餐饮服务;中餐厅;海鲜酒楼</code>）</td></tr>
<tr><td><code>rating</code></td><td>num</td><td>高德快照评分 0–5，无评分为 null</td></tr>
<tr><td><code>avg</code></td><td>num</td><td>人均消费（元），无则 null</td></tr>
<tr><td><code>addr</code></td><td>str</td><td>地址</td></tr>
<tr><td><code>img</code></td><td>str</td><td>高德商家实拍图 URL，无图为空串</td></tr>
</tbody></table>

<h2>调用示例</h2>
<pre class="code"><code><span class="cm"># 1. 全量一次落地（约 {jraw}，CDN 自动 gzip/br）</span>
curl -s https://fun.worldstip.com/data.json -o fun-data.json

<span class="cm"># 2. Python 流式读取，只保留目标城市</span>
<span class="kw">import</span> json, urllib.request
with urllib.request.urlopen("https://fun.worldstip.com/data.json") as r:
    d = json.load(r)
yy = next(c <span class="kw">for</span> c <span class="kw">in</span> d["cities"] <span class="kw">if</span> c["city"] == "岳阳市")
print(yy["poi_total"], yy["grades"], len(yy["food"]))

<span class="cm"># 3. 只要某省汇总 / 某城商圈 S 级</span>
curl -s https://fun.worldstip.com/data.json | jq '.provinces[] | select(.province=="湖南省")'
curl -s https://fun.worldstip.com/data.json | jq '.cities[] | select(.city=="岳阳市") | .districts[] | select(.grade=="S")'

<span class="cm"># 4. 全国美食榜前 10（评分降序，已剔住宿业主导 POI）</span>
curl -s https://fun.worldstip.com/data.json | jq '.food_top[:10]'

<span class="cm"># 5. 带图美食（jq 过滤 img 非空）</span>
curl -s https://fun.worldstip.com/data.json | jq '[.cities[] | select(.city=="岳阳市") | .food[] | select(.img != "")][:10]'

<span class="cm"># 6. 人类可读全量 Markdown（LLM / skill 直读）</span>
curl -s https://fun.worldstip.com/data.md -o fun-data.md</code></pre>

<h2>使用约定</h2>
<div class="callout"><b>一致性承诺：</b>data.json 与 data.md 由同一数据层（<code>build_api.py</code>）从 <code>data/</code> 源档案一次生成，同源同值；任一字段都能在 data.md 对应城市档案中找到出处。</div>
<ul>
<li><b>无鉴权无限率</b>：静态托管 + CDN 缓存，请合理使用（建议客户端侧缓存 24h）。</li>
<li><b>评分口径</b>：高德快照评分（0–5），采集时间见各城市 <code>updated</code> 字段；人均单位元。</li>
<li><b>标记口径</b>：✅ 优质 / ⚠️ 待核 / ❌ 不推荐；派生规则见各城市页说明。</li>
<li><b>美食榜口径</b>：已剔除名称命中酒店/宾馆/旅馆/民宿/客栈/客舍等关键词、或主类型段为住宿服务的 POI。</li>
<li><b>变更频率</b>：数据层随采集波次滚动更新，全量文件整体刷新；大版本变更在 GitHub Releases 说明。</li>
<li><b>许可</b>：数据仅可正当使用，不得整库转售；请保留来源标注（高德/美团/大众点评）。</li>
</ul>
</div></main>{footer()}"""

    return head("数据接口文档 · FUN", "FUN 全国全量数据接口文档：data.json / data.md 端点、Schema 字段、调用示例与使用约定。") + body


# ================================================================ 数据来源页

def render_sources(stats):
    body = f"""<main>
<div class="doc-hero"><div class="wrap">
<a class="back-link" href="index.html">← 返回首页</a>
<div class="sec-label">Sources</div>
<h1 class="sec-title" style="font-size:clamp(2.2rem,5vw,3.4rem)">数据来源与方法论</h1>
<p class="sec-desc">三层数据源，各司其职；所有字段可复算、可追溯。</p>
</div></div>
<div class="wrap doc-body" style="padding-top:30px;padding-bottom:10px">

<h2>三层数据源</h2>
<table><thead><tr><th>层级</th><th>来源</th><th>作用</th><th>覆盖</th></tr></thead><tbody>
<tr><td><b>Primary 底账</b></td><td>高德地图 Web 服务 POI（restapi.amap.com）</td><td>商圈载体、餐饮、休闲娱乐、儿童亲子、酒店、特产六大维度全量采集</td><td>{stats['provinces']} 省级单位 / {stats['cities']} 城 / {stats['poi_total']:,} POI（去重）</td></tr>
<tr><td><b>Food 消费视角</b></td><td>美团</td><td>美食榜单、团购与实时消费热度参考；城市页提供搜索直达</td><td>每城搜索外链</td></tr>
<tr><td><b>Food 评价视角</b></td><td>大众点评</td><td>必吃榜与用户评价参考；城市页提供城市美食频道直达（/拼音/ch10）</td><td>每城频道外链</td></tr>
</tbody></table>

<h2>采集与评级方法</h2>
<ul>
<li><b>查询面</b>：每城约 60 个查询面，覆盖类型码（中餐厅/步行街/购物中心/酒吧/KTV/电影院/运动场馆/游乐场等）与关键词（美食/老字号/大排档/苍蝇馆/小吃/夜市/特产等）双通道。</li>
<li><b>去重</b>：按高德 POI id 去重；跨查询面命中去重后计入维度。</li>
<li><b>商圈评级</b>：S = 关联美食 ≥20 家且均分 ≥4.3、覆盖 ≥3 类业态；A = 美食 ≥10 家且均分 ≥4.0、覆盖 ≥2 类；B = 美食 ≥5 家或单业态 ≥10 家；C = 数据稀薄，仅登记待人工补充。</li>
<li><b>载体识别</b>：剥离分店后缀、地址不参与判定、类型码须为 06 购物类或 050000 餐饮载体，三重护栏防止餐厅混入商圈列表。</li>
<li><b>苍蝇馆纪律</b>：不凭空判定，仅命中关键词或小店语义（小馆/排挡/家常/私房/土菜/大排档）方列为候选。</li>
<li><b>美食×商圈关联</b>：① 名称互证；② 距离就近（≤600m 且同区县）。仅靠距离的关联标注 ⚠。</li>
</ul>

<h2>更新策略</h2>
<ul>
<li>数据层随采集波次滚动更新（wave1 底账 → wave2 酒店/迷你动物园/商场 → wave3 休闲娱乐）。</li>
<li>每城档案头部记录采集时间与告警数；全量文件 <a href="data.json" style="color:var(--blue)">/data.json</a> 的 <code>stats</code> 字段为全局快照。</li>
<li>评分为快照值，营业状态以美团/大众点评实时信息为准。</li>
</ul>

<div class="callout"><b>合规提示：</b>数据用于正当的信息聚合与探索参考，不整库转售；引用请标注「高德地图 POI / 美团 / 大众点评」。</div>
</div></main>{footer()}"""

    return head("数据来源与方法论 · FUN", "高德 POI 全量底账 + 美团/大众点评美食视角：采集方法、评级判据与更新策略。") + body


# ================================================================ README（部署说明）

def render_readme(stats):
    body = f"""<main>
<div class="doc-hero"><div class="wrap">
<a class="back-link" href="index.html">← 返回首页</a>
<div class="sec-label">Deploy</div>
<h1 class="sec-title" style="font-size:clamp(2.2rem,5vw,3.4rem)">部署与备份说明</h1>
<p class="sec-desc">FUN 站点为纯静态零依赖产物，任意静态托管均可运行。</p>
</div></div>
<div class="wrap doc-body" style="padding-top:30px;padding-bottom:10px">
<h2>站点结构</h2>
<pre class="code"><code>site/
├── index.html              <span class="cm"># FUN hero + 主站（含数据调用入口）</span>
├── data.json               <span class="cm"># 全国全量 JSON（meta/stats/32省/389城全量明细/美食榜/商圈榜）</span>
├── data.md                 <span class="cm"># 全国全量 Markdown（目录+统计+32省索引+389城档案+附录）</span>
├── assets/                 <span class="cm"># style.css / app.js（零依赖）</span>
├── cities/&lt;adcode&gt;.html   <span class="cm"># 城市页（389）</span>
├── cities/&lt;市名&gt;.html     <span class="cm"># 城市名 URL 兼容存根 → 跳转 adcode 页</span>
├── provinces/&lt;省&gt;.html    <span class="cm"># 省份页（32）</span>
├── api.html                <span class="cm"># 数据接口文档</span>
├── sources.html            <span class="cm"># 数据来源</span>
├── 404.html                <span class="cm"># FUN 风格错误页</span>
├── robots.txt · sitemap.xml  <span class="cm"># SEO（389 城 + 省页 + 文档页）</span>
├── _headers                <span class="cm"># Cloudflare Pages 缓存规则</span>
├── CNAME                   <span class="cm"># fun.worldstip.com</span>
└── README.html             <span class="cm"># 本页</span></code></pre>

<h2>fun.worldstip.com 部署（Cloudflare Pages）</h2>
<ul>
<li>构建命令：留空（纯静态）；输出目录：<code>site</code>。</li>
<li>DNS：<code>fun</code> CNAME 到 Cloudflare Pages 域名，橙色云 proxied。</li>
<li>缓存规则已随站交付（<code>_headers</code>）：<code>/data.json</code> 与 <code>/data.md</code> 24h、<code>/assets/*</code> 一年 immutable、HTML 1h。</li>
<li>备选：GitHub Pages（本仓库根目录 + Actions）、Netlify Drop、任意 Nginx。</li>
</ul>

<h2>直接上传产品（零配置上线）</h2>
<ul>
<li>交付物 <code>fun-site-upload.zip</code> 为 <code>site/</code> 的完整打包（含 CNAME / _headers / robots / sitemap / 404），<b>解压即传、无需构建</b>。</li>
<li><b>Netlify Drop</b>：app.netlify.com/drop 拖入 zip 或解压后的文件夹 → 秒级上线，自定义域名绑定 fun.worldstip.com。</li>
<li><b>Cloudflare Pages 直传</b>：Direct Upload 选该目录；<b>GitHub Pages</b>：推送本仓库后 Settings → Pages 选 main 分支根目录。</li>
<li><b>任意 Nginx/宝塔</b>：解压到站点根目录，<code>try_files $uri $uri/ /404.html</code> 即可。</li>
</ul>

<h2>GitHub 备份</h2>
<ul>
<li>仓库：<a href="{GH_REPO}" style="color:var(--blue)">MrdT-BitsNote/fun</a>（public）。</li>
<li>纳入版本管理：<code>site/</code>（网站 + JSON/MD 数据接口）与 <code>data/</code>（md 档案源）。</li>
<li>不入库：<code>.cache/</code>（高德采集缓存，162MB 级）。</li>
</ul>

<h2>重新生成</h2>
<pre class="code"><code>python tools/build_api.py        <span class="cm"># md 档案 → JSON 数据层（site/api + site/md 全量内容）</span>
python tools/build_fun_site.py  <span class="cm"># JSON → 网站（site/*.html + assets + 部署资产）</span>
python tools/validate_data.py   <span class="cm"># C1–C10 数据校验</span></code></pre>
</div></main>{footer()}"""

    return head("部署与备份说明 · FUN", "FUN 静态站点结构、fun.worldstip.com 部署方案与 GitHub 备份说明。") + body


# ================================================================ 部署资产

def build_redirect_stubs(idx):
    """城市名 URL → adcode URL 兼容存根：保留 /cities/岳阳市.html 可读地址，301 语义由 meta refresh + canonical 表达。"""
    n = 0
    for c in idx["city_index"]:
        ad = c["page"].split("/")[-1]  # <adcode>.html
        stub = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="0; url={ad}">
<link rel="canonical" href="{ad}">
<title>{esc(c['city'])} · FUN</title>
{favicon()}
<style>body{{margin:0;background:#fbfbfd;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Helvetica Neue",sans-serif}}a{{color:#0071e3}}</style>
</head>
<body>
<div style="min-height:100dvh;display:flex;align-items:center;justify-content:center;text-align:center">
<div><div style="font-size:2rem;font-weight:900;letter-spacing:-.02em;color:#1d1d1f">{esc(c['city'])}</div>
<p style="color:#6e6e73;margin-top:8px">正在跳转至 <a href="{ad}">{esc(c['city'])}档案页</a>…</p></div>
</div>
</body>
</html>"""
        # 文件名用城市名原文（URL 侧由浏览器/服务器自动编解码），与 site/md 命名一致
        out = os.path.join(SITE, "cities", f"{c['city']}.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(stub)
        n += 1
    return n


def build_404():
    """FUN 风格 404 页（静态托管默认错误页）。"""
    body = """<main>
<div class="doc-hero" style="min-height:72dvh;display:flex;align-items:center"><div class="wrap" style="text-align:center">
<div class="sec-label">404</div>
<h1 style="font-size:clamp(4rem,13vw,8.5rem);font-weight:900;letter-spacing:-.04em;line-height:1;margin:.08em 0">走<span style="background:linear-gradient(135deg,#ff9f0a,#ff375f 55%,#bf5af2);-webkit-background-clip:text;background-clip:text;color:transparent">丢</span>了</h1>
<p class="sec-desc" style="margin:14px auto 26px;max-width:34em">这条路线没有数据。回首页重新探索，或直接搜一座城市——389 城的美食与商圈都在。</p>
<div class="hero-cta" style="justify-content:center">
<a class="btn btn-p" href="index.html">回到首页</a>
<a class="btn btn-g" href="index.html#cities">探索城市</a>
<a class="btn btn-g" href="api.html">数据接口</a>
</div></div></div></main></body></html>"""
    with open(os.path.join(SITE, "404.html"), "w", encoding="utf-8") as f:
        f.write(head("页面不存在 · FUN", "你访问的路线没有数据。回首页探索 389 城美食与商圈。") + body)


def build_deploy_files(idx, empty_provs=()):
    """robots.txt / sitemap.xml / _headers / CNAME —— 部署与 SEO 资产。"""
    base = "https://fun.worldstip.com"
    # robots.txt
    with open(os.path.join(SITE, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    # sitemap.xml（首页 1.0 / 省份页 0.8 / 城市页 0.7 / 文档页 0.5 / 空态省份 0.3）
    urls = [(f"{base}/", "1.0", "weekly"), (f"{base}/index.html", "1.0", "weekly"),
            (f"{base}/api.html", "0.5", "monthly"), (f"{base}/sources.html", "0.5", "monthly"),
            (f"{base}/README.html", "0.4", "monthly")]
    for prov in sorted(set(c["province"] for c in idx["city_index"])):
        urls.append((f"{base}/provinces/{quote(prov)}.html", "0.8", "weekly"))
    for prov in sorted(empty_provs):
        urls.append((f"{base}/provinces/{quote(prov)}.html", "0.3", "monthly"))
    for c in idx["city_index"]:
        urls.append((f"{base}/{c['page']}", "0.7", "weekly"))
    items = "".join(f"<url><loc>{u}</loc><changefreq>{cf}</changefreq><priority>{p}</priority></url>"
                    for u, p, cf in urls)
    with open(os.path.join(SITE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + items + "</urlset>")
    # _headers（Cloudflare Pages 缓存规则）
    with open(os.path.join(SITE, "_headers"), "w", encoding="utf-8") as f:
        f.write("# Cloudflare Pages 缓存规则\n"
                "/data.json\n  Cache-Control: public, max-age=86400\n"
                "/data.md\n  Cache-Control: public, max-age=86400\n"
                "/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n"
                "/*.html\n  Cache-Control: public, max-age=3600\n")
    # CNAME（Cloudflare Pages / GitHub Pages 自定义域名）
    with open(os.path.join(SITE, "CNAME"), "w", encoding="utf-8") as f:
        f.write("fun.worldstip.com\n")
    return len(urls)


# ================================================================ 主流程

def _dims(c):
    """从全量城市记录提取六维度计数（供首页/省份页轻索引用）。"""
    dims = (c.get("credibility") or {}).get("dims", {})
    return {"food": dims.get("美食", 0), "district": dims.get("商圈", 0),
            "leisure": dims.get("休闲娱乐", 0), "kids": dims.get("儿童娱乐", 0),
            "hotel": dims.get("酒店", 0), "product": dims.get("特产", 0)}


def main():
    # v0.9.0：site/data.json 是唯一数据层（全国全量单文件）
    from build_api import parse_city_md
    data_dir = os.path.join(os.path.dirname(SITE), "data")

    full = load("data.json")
    stats = full["stats"]
    dist_top = {"items": full["districts_top"]}
    idx = {
        "poi_total": stats["poi_total"],
        "city_index": [{
            "city": c["city"], "province": c["province"], "adcode": c["adcode"],
            "poi": c["poi_total"], "page": c["page"], "grades": c["grades"],
            "dims": _dims(c), "updated": c.get("updated"),
        } for c in full["cities"]],
    }

    # 资产
    os.makedirs(os.path.join(SITE, "assets"), exist_ok=True)
    with open(os.path.join(SITE, "assets", "style.css"), "w", encoding="utf-8") as f:
        f.write(CSS)
    with open(os.path.join(SITE, "assets", "app.js"), "w", encoding="utf-8") as f:
        f.write(JS)

    # 首页
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(idx, stats, dist_top))
    print("[fun_site] index.html")

    # 城市页（从 data/ 源 md 同源解析，保持中文字段渲染）
    for c in idx["city_index"]:
        rec = parse_city_md(os.path.join(data_dir, c["province"], c["city"] + ".md"), c["province"])
        rec["adcode"] = c["adcode"]
        rec["urls"] = {"page": c["page"], "json": "data.json", "md": "data.md"}
        out = os.path.join(SITE, "cities", f"{c['adcode']}.html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_city(rec))
    print(f"[fun_site] cities: {len(idx['city_index'])}")

    # 省份页
    by_prov = {}
    for c in idx["city_index"]:
        by_prov.setdefault(c["province"], []).append(c)
    for prov, cities in by_prov.items():
        out = os.path.join(SITE, "provinces", f"{prov}.html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_province(prov, cities, stats))
    # 空态省份页（无建库城市的省级行政区，如香港/澳门）：覆盖旧版残留页，保证路线可达
    empty_provs = [p for p in ALL_PROVINCES if p not in by_prov]
    for prov in empty_provs:
        out = os.path.join(SITE, "provinces", f"{prov}.html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_province_empty(prov, stats))
    print(f"[fun_site] provinces: {len(by_prov)}（含空态 {len(empty_provs)}: {'、'.join(empty_provs) or '无'}）")

    # 文档页
    for name, fn in (("api.html", lambda: render_api_doc(idx, stats)),
                     ("sources.html", lambda: render_sources(stats)),
                     ("README.html", lambda: render_readme(stats))):
        with open(os.path.join(SITE, name), "w", encoding="utf-8") as f:
            f.write(fn())
        print(f"[fun_site] {name}")

    # 部署资产：城市名重定向存根 / 404 / robots / sitemap / _headers / CNAME
    n_stub = build_redirect_stubs(idx)
    build_404()
    n_url = build_deploy_files(idx, empty_provs=empty_provs)
    print(f"[fun_site] deploy assets: {n_stub} 重定向存根 + 404 + robots + sitemap({n_url} urls) + _headers + CNAME")


if __name__ == "__main__":
    main()
