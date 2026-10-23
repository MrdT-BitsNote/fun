#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
package_upload.py — 将 site/ 打包为「解压即传」的静态产品 fun-site-upload.zip。

产物（写入项目根目录）:
  fun-site-upload.zip   site/ 全量 + DEPLOY.md（上传指南），index.html 位于包根
"""
import os
import zipfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
OUT = os.path.join(os.path.dirname(ROOT), "fun-site-upload.zip")

DEPLOY_MD = """# FUN · 全国美食 × 商圈 × 娱乐探索站 — 直接上传产品

> fun.worldstip.com · v0.8.1 · {cities} 城 / {provs_data} 个有数据省级行政区（页面全覆盖 34）/ {poi:,} POI
> 本包为纯静态零依赖产物，**解压即传、无需构建、无需服务器**。

## 包内容

| 路径 | 内容 |
|---|---|
| `index.html` | FUN hero（巨型字体 + 滚动入场）+ 主站六区块，首页内含**数据调用入口**（base URL 一键复制 / JSON·MD 端点快捷键 / 现场调用演示） |
| `cities/<adcode>.html` | {cities} 个城市档案页 |
| `cities/<市名>.html` | 城市名 URL 兼容存根（meta refresh 自动跳转 adcode 页） |
| `provinces/<省>.html` | {prov_pages} 个省级页面（{provs_data} 个有数据 + 2 个特别行政区空态兜底页） |
| `api.html` / `sources.html` / `README.html` | 接口文档 / 数据来源 / 使用说明 |
| `api/` | JSON 数据接口层（index / stats / cities / provinces / food/top / districts/top） |
| `md/` | 全量 Markdown 内容（{md_count} 个文件：城市档案 + 省级索引 + README/API/SOURCES/行政层级总览） |
| `assets/` | style.css + app.js（零依赖，自包含） |
| `404.html` | FUN 风格错误页 |
| `robots.txt` / `sitemap.xml` | SEO（{sitemap} 条 URL） |
| `_headers` | Cloudflare Pages 缓存规则（/api/* 与 /md/* 24h，/assets/* 1 年 immutable） |
| `CNAME` | fun.worldstip.com |

## 上传方式（三选一）

### 1. Netlify Drop（最快，30 秒）

打开 https://app.netlify.com/drop ，把本包**解压后的文件夹整个拖进去**，即时获得预览链接。
绑定自定义域名 `fun.worldstip.com` 后在 Site settings → Domain management 中添加，DNS 加 CNAME 记录。

### 2. Cloudflare Pages 直接上传（推荐，自带 CDN 与 _headers 规则）

```bash
# 解压
unzip fun-site-upload.zip -d fun-site
cd fun-site

# 方式 A：Dashboard → Workers & Pages → Create → Pages → Upload assets
# 方式 B：wrangler CLI
npx wrangler pages deploy . --project-name=fun
```

上传后 Pages 项目设置中绑定 `fun.worldstip.com`（CNAME 文件已包含在包内，Git 集成方式同样生效）。

### 3. GitHub Pages

```bash
cd fun-site
git init && git add -A && git commit -m "FUN site"
git branch -M gh-pages
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git push -u origin gh-pages
```

仓库 Settings → Pages → Source 选 `gh-pages` 分支；自定义域名填 `fun.worldstip.com`（包内 CNAME 会自动被 GitHub Pages 读取）。

### 4. 自有 Nginx

```nginx
server {
    listen 443 ssl;
    server_name fun.worldstip.com;
    root /var/www/fun-site;   # 解压后的目录
    index index.html;
    location / { try_files $uri $uri.html $uri/ =404; }
}
```

## 调用数据（skill / agent）

```bash
# 全国总索引
curl -s https://fun.worldstip.com/api/index.json

# 城市全量数据（adcode）
curl -s https://fun.worldstip.com/api/cities/430600.json

# 城市档案 Markdown 原文
curl -s https://fun.worldstip.com/md/湖南省/岳阳市.md
```

字段口径见 `api.html` 与 `/md/API.md`；JSON 与 MD 由同一数据层生成，同源同值。

---

数据来源：高德地图 Web 服务 POI · 美团 · 大众点评 ｜ 生成时间 {gen}
"""


def count(pred):
    n = 0
    for dirpath, _, filenames in os.walk(SITE):
        for fn in filenames:
            if pred(os.path.join(dirpath, fn)):
                n += 1
    return n


def main():
    import json
    stats = json.load(open(os.path.join(SITE, "api", "stats.json"), encoding="utf-8"))
    idx = json.load(open(os.path.join(SITE, "api", "index.json"), encoding="utf-8"))
    sitemap_n = open(os.path.join(SITE, "sitemap.xml"), encoding="utf-8").read().count("<loc>")
    md_n = count(lambda p: p.endswith(".md"))
    prov_pages = count(lambda p: p.startswith(os.path.join(SITE, "provinces")) and p.endswith(".html"))

    deploy = (DEPLOY_MD
              .replace("{cities}", str(stats["cities"]))
              .replace("{provs_data}", str(stats["provinces"]))
              .replace("{poi}", f'{stats["poi_total"]:,}')
              .replace("{prov_pages}", str(prov_pages))
              .replace("{md_count}", str(md_n))
              .replace("{sitemap}", str(sitemap_n))
              .replace("{gen}", datetime.now().strftime("%Y-%m-%d %H:%M")))

    if os.path.exists(OUT):
        os.remove(OUT)
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dirpath, _, filenames in os.walk(SITE):
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                arc = os.path.relpath(full, SITE)
                z.write(full, arc)
                n += 1
        z.writestr("DEPLOY.md", deploy)
        n += 1
    size = os.path.getsize(OUT) / 1048576
    print(f"[package] {OUT} · {n} files · {size:.1f} MB")


if __name__ == "__main__":
    main()
