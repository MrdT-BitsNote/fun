# FUN 数据接口文档

> 站点：https://fun.worldstip.com  ·  生成时间：2026-10-24 02:23
> 所有端点只读、无鉴权、无速率限制，可被 CDN 缓存。JSON 与 Markdown 由同一数据层生成，同源同值。

## 端点总览

| 端点 | 格式 | 内容 | 体积量级 |
|---|---|---|---|
| `/api/index.json` | JSON | 全国总索引：省 → 市 → 轻量 meta + 评级统计 | ~150 KB |
| `/api/stats.json` | JSON | 全站统计快照 | < 1 KB |
| `/api/cities/index.json` | JSON | 城市轻索引数组（含页面/JSON/MD 三地址） | ~120 KB |
| `/api/cities/<adcode>.json` | JSON | 城市全量结构化数据（见下方 Schema） | 50–500 KB/城 |
| `/api/provinces/<省>.json` | JSON | 省级汇总：城市列表 + 聚合统计 | ~10–60 KB |
| `/api/food/top.json` | JSON | 全国美食榜（按评分降序，含图与城市跳转；已剔除住宿业主导 POI） | ~600 KB |
| `/api/districts/top.json` | JSON | 全国 S/A 级商圈榜（按关联美食数） | ~400 KB |
| `/md/<省>/<市>.md` | Markdown | 城市档案原文（13 章），skill 直读 | 20–80 KB/城 |
| `/data.json` | JSON | 兼容旧版轻量总索引 | ~100 KB |

## 城市 JSON Schema（`/api/cities/<adcode>.json`）

```json
{
  "city": "岳阳市",                  // 城市名
  "province": "湖南省",              // 所属省级单位
  "adcode": "430600",                // 高德区划代码
  "poi_total": 1018,                 // 去重 POI 总数
  "waves": [2, 3],                   // 采集波次
  "updated": "2026-10-23 20:07:00",  // 采集时间
  "credibility": {                  // §0 可信度
    "poi_total": 1018, "rated_ratio": "99%", "warnings": 0,
    "dims": {"美食": 311, "商圈": 184, "休闲娱乐": 386, "儿童娱乐": 40, "酒店": 32, "特产": 41}
  },
  "overview": {                     // §1 总览
    "admin": {"下级区县": "9", "街道/镇/乡": "134"},
    "district_poi": [{"district": "岳阳楼区", "poi": 534, "ratio": "52%"}],
    "carrier_types": [{"type": "购物中心/综合体", "count": 59}]
  },
  "districts": [{                   // §2 商圈档案（含 S/A/B/C 评级与详情）
    "name": "步步高新天地", "grade": "A", "carrier": "购物中心/综合体",
    "rating": 4.7, "food": 21, "leisure": 51, "kids": 1, "hotel": 3,
    "detail": {"address": "东茅岭路1号", "bandwidth": "¥45（8–81）", "axis": "东茅岭街", "mixes": [...]}
  }],
  "leisure":  {"subcats": [...], "list": [...]},   // §4 休闲娱乐（14 子类）
  "kids":     {"subcats": [...], "list": [...]},   // 儿童亲子
  "malls":    [...],                  // §5 综合体与商场
  "food":     [...],                  // §6 美食（image 为高德实拍图 URL）
  "xiaocan":  [...],                  // §7 苍蝇馆/小店候选
  "specialties": [...],               // §8 特产
  "assoc":    [...],                  // §9 美食×商圈关联
  "hotels":   [...],                  // §10 酒店
  "queries":  [...],                  // §11 原始查询面
  "external": {                      // 美团 / 大众点评外链
    "meituan_search": "https://www.meituan.com/s/...",
    "dianping_food": "https://www.dianping.com/yueyang/ch10"
  }
}
```

## 调用示例

```bash
# 1. 拿全国索引，筛出目标城市
curl -s https://fun.worldstip.com/api/index.json | jq '.city_index[] | select(.province=="湖南省")'

# 2. 取城市全量数据
curl -s https://fun.worldstip.com/api/cities/430600.json

# 3. 只取 S 级商圈
curl -s https://fun.worldstip.com/api/cities/430600.json | jq '.districts[] | select(.grade=="S")'

# 4. 取带图的美食 TOP10
curl -s https://fun.worldstip.com/api/cities/430600.json | jq '[.food[] | select(.image)][:10]'

# 5. Markdown 原文（skill 直读，零解析成本）
curl -s https://fun.worldstip.com/md/湖南省/岳阳市.md
```

```python
# 6. Python 一行读取
import json, urllib.request
data = json.load(urllib.request.urlopen("https://fun.worldstip.com/api/cities/430600.json"))
```

## 使用约定

- **一致性承诺**：JSON 与 Markdown 由同一数据层（`build_api.py`）生成，同源同值；任一字段都能在对应城市的 md 档案中找到出处。
- **无鉴权无限率**：静态托管 + CDN 缓存，请合理使用（建议客户端侧缓存 24h）。
- **评分口径**：高德快照评分（0–5），采集时间见城市 JSON 的 `updated` 字段；人均单位元。
- **标记口径**：✅ 优质 / ⚠️ 待核 / ❌ 不推荐；派生规则见各城市页说明。
- **许可**：数据仅可正当使用，不得整库转售；请保留来源标注（高德/美团/大众点评）。

## Markdown 内容索引（/md/）

| 路径 | 内容 |
|---|---|
| `/md/README.md` | 全国数据总索引 |
| `/md/行政层级总览.md` | 43,474 个行政节点（省→镇街） |
| `/md/<省>/<省>.md` | 省级索引（城市列表 + 聚合统计） |
| `/md/<省>/<市>.md` | 城市档案原文（13 章），与 JSON 同源同值 |
