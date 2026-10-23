# fun.worldstip.com 部署方案

> 目标：把「本地美食探索」skill 的全国 md 数据层发布为公开数据网站。
> 拟定域名：**fun.worldstip.com**（worldstip.com 已有解析权，加一条 CNAME 即可）

---

## 1. 现状：md 数据如何变成网站

数据流（全部本地完成，无后端）：

```
data/<省>/<市>.md ──┐
                    ├─→ tools/build_site.py ─→ site/（纯静态 HTML/CSS/JS）
.cache/amap/raw/*.json ─┘         │
                                  ├─ index.html          全国总览（省卡片+搜索+统计）
                                  ├─ provinces/<省>.html 省页（城市列表+筛选）
                                  ├─ cities/<市>.html    城页（md 渲染为 HTML）
                                  ├─ assets/style.css    样式（亮色暖调，零依赖）
                                  ├─ assets/app.js       搜索/筛选
                                  ├─ data.json           机读全量索引（其他 skill 可 fetch）
                                  └─ README.html         使用说明
```

一条命令重新生成全站：

```bash
python tools/build_site.py        # 输出到 site/，约 15MB/百城
```

**为什么是纯静态**：无数据库、无构建依赖（自带 md→HTML 转换器，不引第三方库）、
任何静态托管都能跑、被流量打爆也不会挂、数据可整包下载复用。

**给其他技能调用的两个口子**：
1. `site/data.json` —— 全部城市的结构化索引（城市/省份/adcode/POI 数/波次/更新时间/URL）
2. `data/<省>/<市>.md` —— 人类可读、可校对的底稿，其他技能可直接读取

---

## 2. 部署三选一

### 方案 A：Cloudflare Pages（推荐）

| 项 | 说明 |
|---|---|
| 费用 | 免费额度足够（每月无限请求 + 100GB 带宽，静态站够用） |
| 步骤 | 1) 把仓库推到 GitHub；2) Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect to Git；3) 构建命令**留空**，输出目录填 `site`；4) Custom domains 添加 `fun.worldstip.com`，按提示加 CNAME |
| 优点 | 自动 HTTPS、全球 CDN、每次 push 自动部署、无限环境预览 |
| 注意 | 仓库里 `site/` 若不想入库可加 `.gitignore`，改用 Cloudflare 的构建命令 `python tools/build_site.py`、输出目录 `site` |

### 方案 B：GitHub Pages

```bash
# 在仓库内
python tools/build_site.py
cd site
git init && git add -A && git commit -m "deploy"
git branch -M gh-pages
git remote add origin https://github.com/<用户>/<仓库>.git
git push -f origin gh-pages
echo fun.worldstip.com > CNAME && git add -A && git commit -m "cname" && git push
```

GitHub 仓库 Settings → Pages → Source 选 `gh-pages` 分支；
DNS 加 `fun CNAME <用户名>.github.io`。
优点：免费、和 GitHub 账号体系一体；缺点：国内访问不稳定（无 CDN 节点）。

### 方案 C：阿里云 OSS 静态托管（国内速度最好）

```bash
ossutil config                                    # 首次配 AK
python tools/build_site.py
ossutil cp -r site/ oss://<你的bucket>/ --update  # 上传/增量
```

OSS 控制台 →  bucket → 基础设置 → 静态页面：首页 index.html、404 页 404.html；
绑定自定义域名 `fun.worldstip.com`（需备案过的域名），开 CDN 加速。
优点：国内访问快；缺点：备案 + 按量计费（流量小则费用极低）。

---

## 3. DNS 配置

在 worldstip.com 的 DNS 服务商处加一条记录：

| 类型 | 主机记录 | 值 |
|---|---|---|
| CNAME | fun | 按所选方案：Cloudflare Pages 提供的 `<hash>.pages.dev` / `<用户名>.github.io` / OSS 绑定的 CDN 域名 |

解析生效后 `https://fun.worldstip.com` 即可访问（HTTPS 由托管平台自动签发）。

---

## 4. 上线前检查清单

- [ ] `python tools/build_site.py` 在**全量采集完成后**重跑一次
      （当前为增量数据，站点会持续变大）
- [ ] `python tools/validate_data.py` 全绿（10 项校验）
- [ ] 首页统计数字与 data.json 一致（POI 总数、城市数）
- [ ] 抽查 3 个城市页：表格渲染正常、图片可加载（高德 CDN 外链）
- [ ] 搜索框输入「岳阳」「火锅」等关键词有结果
- [ ] 手机宽度（≤640px）下无横向滚动（表格已做 overflow-x 包裹）
- [ ] `data.json` 可正常下载且 JSON 合法

## 5. 增量更新节奏

采集是长期的（当前 104/389 城）。建议：

1. 每次采集批次完成后：`render_md.py --all` → `build_index.py` → `validate_data.py` → `build_site.py`
2. Cloudflare Pages 用户：把这四步写成 CI（GitHub Actions）或一条脚本 `tools/deploy.sh`
3. 站点体积预期：389 城全量约 **50–60MB 静态文件**，GitHub/Cloudflare 均无压力

## 6. SEO 与公开数据属性

- 每页 `<title>` 已含「城市 · 省份」，描述信息在首屏 hero
- 建议上线后在 Google Search Console / 百度站长平台提交 sitemap
  （可由 `tools/build_site.py` 扩展生成 `sitemap.xml`，当前未做）
- `data.json` 即公开数据集入口，可在 README 页注明数据许可与来源
  （高德 POI 数据的使用需遵守高德地图 API 使用条款）
