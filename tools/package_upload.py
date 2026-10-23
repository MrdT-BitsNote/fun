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

> fun.worldstip.com · v0.9.0 · {cities} 城 / {provs_data} 个省级行政区 / {poi:,} 条 POI / 商圈 {dist:,} 处
> 数据集已整合为 **两个全量文件**：`data.json`（机读）+ `data.md`（人读 / LLM 直读）。
> 本包为纯静态零依赖产物，**解压即传、无需构建、无需服务器**。

## 包内容

| 路径 | 内容 |
|---|---|
| `index.html` | FUN hero（巨型字体 + 滚动入场）+ 主站六区块，首页内含**数据调用入口**（两个全量文件卡片 + Range 现场调用演示） |
| `cities/<adcode>.html` | {cities} 个城市档案页 |
| `cities/<市名>.html` | 城市名 URL 兼容存根（meta refresh 自动跳转 adcode 页） |
| `provinces/<省>.html` | {prov_pages} 个省级页面（{provs_data} 个有数据 + 2 个特别行政区空态兜底页） |
| `data.json` | **全国全量 JSON 单文件**（{jraw} / gzip {jgz}）：meta · stats · {provs_data} 省汇总 · **{cities} 城全量明细** · 美食榜 800 · 商圈榜 1000 |
| `data.md` | **全国全量 Markdown 单文件**（{mraw} / gzip {mgz}）：目录 + 统计 + {provs_data} 省索引 + {cities} 城档案全文 + 附录 |
| `api.html` / `sources.html` / `README.html` | 接口文档 / 数据来源 / 部署说明 |
| `assets/` | style.css + app.js（零依赖，自包含） |
| `404.html` | FUN 风格错误页 |
| `robots.txt` / `sitemap.xml` | SEO（{sitemap} 条 URL） |
| `_headers` | Cloudflare Pages 缓存规则（data.json / data.md 24h，/assets/* 1 年 immutable） |
| `CNAME` | fun.worldstip.com |

## 上传方式（四选一）

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

整个数据集就**两个文件**，一次请求拿全量：

```bash
# ① 全量落地（服务端/CND 自动 gzip 或 br）
curl -s https://fun.worldstip.com/data.json -o fun-data.json
curl -s https://fun.worldstip.com/data.md   -o fun-data.md

# ② 只要一座城市（Python 标准库读流）
python -c "import json,urllib.request as u;d=json.load(u.urlopen('https://fun.worldstip.com/data.json'));\
print(next(c for c in d['cities'] if c['city']=='岳阳市')['poi_total'])"

# ③ 高效取法：meta/stats 集中在文件头 4KB 内，只要概览就用 Range 取首段
curl -s -r 0-8191 https://fun.worldstip.com/data.json | head -c 2000
curl -s https://fun.worldstip.com/data.json | jq '.cities[] | select(.city=="岳阳市") | .districts[] | select(.grade=="S")'
```

字段 Schema 与完整示例见 `api.html`；data.json 与 data.md 由同一数据层一次生成，同源同值。

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
    import gzip
    d = json.load(open(os.path.join(SITE, "data.json"), encoding="utf-8"))
    stats = d["stats"]
    sitemap_n = open(os.path.join(SITE, "sitemap.xml"), encoding="utf-8").read().count("<loc>")
    prov_pages = count(lambda p: p.startswith(os.path.join(SITE, "provinces")) and p.endswith(".html"))

    deploy = (DEPLOY_MD
              .replace("{cities}", str(stats["cities"]))
              .replace("{provs_data}", str(stats["provinces"]))
              .replace("{poi:,}", f'{stats["poi_total"]:,}')
              .replace("{prov_pages}", str(prov_pages))
              .replace("{dist:,}", f'{stats["districts_total"]:,}')
              .replace("{jraw}", f'{os.path.getsize(os.path.join(SITE, "data.json"))/1048576:.1f} MB')
              .replace("{jgz}", f'{len(gzip.compress(open(os.path.join(SITE, "data.json"), "rb").read(), 1))/1048576:.1f} MB')
              .replace("{mraw}", f'{os.path.getsize(os.path.join(SITE, "data.md"))/1048576:.1f} MB')
              .replace("{mgz}", f'{len(gzip.compress(open(os.path.join(SITE, "data.md"), "rb").read(), 1))/1048576:.1f} MB')
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
