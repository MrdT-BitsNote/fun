#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
高德 POI 采集器 —— 全国各省地市「美食 + 商圈 + 儿童游乐」建库的数据通道

设计纪律（与百度通道一致，见 tools/chain_probe.py 的 QuotaExceeded 教训）
--------------------------------------------------------------------
1. **配额故障必须显式报错，不得静默降级为空列表。**
   百度通道的事故：配额耗尽返回 status=302 且 results 字段缺失，
   上层把「查无结果」误判成「地图未收录」，所有结论集体降级无人察觉。
   本采集器对每一种非 10000 状态都分类处理：
     - CUQPS / 超限 / quota  → QuotaExceeded，立即停止该城采集并记入进度文件
     - INVALID_USER_KEY      → KeyError，直接终止（key 无效，重试无意义）
     - 其他非 0              → 记为该城市「受限」状态，保留原有缓存不覆盖
2. **原始响应全量落盘，不做任何裁剪**，便于后期换算法重跑。
3. **按城市隔离缓存**（借鉴 v0.5.0 修复：单槽位缓存曾导致跨城污染）。
4. **预算硬闸**：--budget 限制单次运行的总请求数，防止一次跑爆日配额。
5. **offset 上限护栏**：高德 text 接口单次最多返回 20/25 条（视 types 而定），
   翻页上限 offset=25；count 大于 600 时说明被截断，显式标记 truncated。
6. **限速纪律（v0.6.2）**：默认单请求间隔 0.6s、城间休息 2s、每 100 请求
   长休 10s。高频连续请求会触发高德 IP 访问策略（10005 INVALID_USER_IP），
   宁可慢，不可错——错误的空结果比慢更致命。
7. **多 key 池（v0.6.1）**：keys.txt 存多个 key，主 key 被 IP 白名单拒绝
   或无效时自动切换，成功后重置计数支持恢复。

用法
----
    # 全量建库（会自动跳过已完成城市）
    python tools/amap_collect.py --all --budget 800

    # 只跑湖南
    python tools/amap_collect.py --province 湖南省

    # 单城试跑
    python tools/amap_collect.py --city 岳阳市 --verbose
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "amap")
RAW = os.path.join(CACHE, "raw")
PROGRESS = os.path.join(CACHE, "progress.json")
KEYS_FILE = os.path.join(CACHE, "keys.txt")

PLACE_URL = "https://restapi.amap.com/v3/place/text"

# ---------------------------------------------------------------- 凭据池
# v0.6.1：单 key 被 IP 白名单锁死时整批中断（实测损失 168 城 × 13 分钟）。
# 改为多 key 池：主 key 出现 IP 拒绝 / key 无效时自动切备用 key，
# 每个 key 独立记录连续失败次数，恢复后自动切回。
def load_keys():
    keys = []
    env = os.environ.get("AMAP_KEYS", "")
    if env:
        keys += [k.strip() for k in env.split(",") if k.strip()]
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, encoding="utf-8") as f:
            keys += [ln.strip() for ln in f if ln.strip()]
    # 去重保序
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    if not out:
        raise SystemExit(
            "未找到高德 key。设置环境变量 AMAP_KEYS（逗号分隔）"
            "或写入 %s" % KEYS_FILE)
    return out


KEYS = load_keys()
_key_state = {"idx": 0, "fail": [0] * len(KEYS)}


def current_key():
    return KEYS[_key_state["idx"]]


def rotate_key(reason):
    """切到下一个可用 key。返回新 key 序号。"""
    old = _key_state["idx"]
    n = len(KEYS)
    for step in range(1, n + 1):
        i = (old + step) % n
        if _key_state["fail"][i] < 3:      # 连续失败 3 次的 key 暂时弃用
            _key_state["idx"] = i
            _key_state["fail"][old] = 0
            print("    🔑 key %d → %d（%s）" % (old + 1, i + 1, reason))
            return i
    raise QuotaExceeded(
        "全部 %d 个 key 均不可用（%s）——请检查 IP 白名单与配额" % (n, reason))

# ---------------------------------------------------------------- 配额与错误
class QuotaExceeded(RuntimeError):
    pass


class KeyInvalid(RuntimeError):
    pass


class DistrictBlocked(RuntimeError):
    """该城市本次不可用（网络/限流/空结果），保留旧缓存，不覆盖。"""
    pass


PACE = {"req": 0.6, "city": 2.0, "long": 10.0}   # 全局节流：单请求/城间/长休


def throttle(city_rest=False):
    """限速：单请求间隔 + 城间休息 + 每 100 请求长休 10s。

    v0.6.2 用户明确要求「节奏慢一点，太快容易出错」。
    高频请求会触发高德 IP 访问策略（实测 INVALID_USER_IP 10005），
    宁可慢，不可错——错误的空结果比慢更致命。
    """
    global _req_counter
    _req_counter = getattr(sys.modules[__name__], "_req_counter", 0) + 1
    if _req_counter % 100 == 0:
        time.sleep(PACE["long"])
    elif city_rest:
        time.sleep(PACE["city"])
    else:
        time.sleep(PACE["req"])


def request(params, retries=3, pause=None):
    """统一请求入口：带重试、限流保护、错误分类、多 key 轮换。

    v0.6.2：成功后重置该 key 失败计数（支持临时故障恢复）。
    """
    q = dict(params)
    last = None
    for attempt in range(retries + 1):
        q["key"] = current_key()
        url = PLACE_URL + "?" + urllib.parse.urlencode(q)
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                blob = json.loads(r.read().decode("utf-8"))
        except Exception as e:                        # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
            continue
        info = blob.get("info") or ""
        code = blob.get("infocode") or ""
        status = blob.get("status")
        # ── 错误分类：绝不能让配额问题被读成地理问题 ──
        if code == "10021" or "CUQPS" in info or "超" in info and "限" in info:
            raise QuotaExceeded("高德配额受限（%s）：%s" % (code, info[:100]))
        # INVALID_USER_IP（10005）：key 的 IP 白名单/访问策略拒绝。
        # 实测（v0.6.0 全国建库）：连续请求约 51 城后 key 开始对所有城市
        # 返回 10005，影响 168 城全查询面失败。这不是「该城市没有数据」——
        # 若把空结果当真实数据落盘，会渲染出「0 家美食」的假档案，
        # 与百度通道的静默降级事故同构。
        # v0.6.1：属 key 级问题，重试同 key 无效，直接轮换备用 key。
        if code == "10005" or "INVALID_USER_IP" in info:
            _key_state["fail"][_key_state["idx"]] += 1
            if len(KEYS) > 1:
                # 有备用 key 就立即轮换重试（旧 key 的 IP 拒绝不会自愈）
                rotate_key("INVALID_USER_IP")
                continue
            raise DistrictBlocked(
                "高德 IP 访问策略拒绝（%s）：%s——属接口故障，"
                "非地理结论，不可当作「该城无数据」" % (code, info[:80]))
        if code == "10003" or code == "10004" or code == "10001":
            _key_state["fail"][_key_state["idx"]] += 1
            if len(KEYS) > 1:
                rotate_key("key 无效")
                continue
            raise KeyInvalid("高德 key 无效或过期（%s）：%s" % (code, info[:100]))
        if code == "10020" or code == "10022" or code == "20800":
            raise DistrictBlocked("高德接口层拒绝（%s）：%s" % (code, info[:100]))
        if status != "1":
            raise DistrictBlocked(
                "高德返回非成功状态 status=%s code=%s info=%s"
                % (status, code, info[:100]))
        _key_state["fail"][_key_state["idx"]] = 0     # 成功即恢复
        return blob
    raise DistrictBlocked("高德请求失败：%s" % last)


# ---------------------------------------------------------------- 查询计划
# 每个城市固定跑这些「查询面」，保证跨城市可比、可复算。
#   类型码查（type_query）：吃类型树，一次拿到一个分类的头部 POI
#   关键词查（kw_query） ：吃自然语言，捕捉「苍蝇馆 / 大排档 / 夜宵」等
#                         无法用类型码表达的本地概念
# pages 表示最多翻几页（高德 offset 上限 25，超过即截断）
#
# v0.7.0 分三波：
#   wave 1 = 原美食/特产/商圈/夜生活/儿童游乐面（51+69 城已采）
#   wave 2 = 用户 v0.7 新增维度：酒店配套、迷你动物园/萌宠、休闲娱乐
#            （密室/KTV/影院/棋牌）、百货/奥莱/批发城
#   wave 3 = 用户 v0.7.1 休闲娱乐扩展：运动场馆/电影院/KTV夜总会/足疗/
#            按摩/卡丁车/清吧/夜店/桌游/蹦床/游乐场（成人向）/游戏厅
#   --wave 2/3 可单独补采，与已有缓存合并，不重复采已有波次。
QUERIES = [
    # ── wave 1 ──
    (1, "food", "类型:中餐厅",          dict(types="050100", pages=2)),
    (1, "food", "类型:湘菜/地方菜",     dict(types="050108", pages=1)),
    (1, "food", "类型:地方风味餐厅",    dict(types="050118", pages=1)),
    (1, "food", "类型:酒楼/火锅/海鲜",  dict(types="050101", pages=1)),
    (1, "food", "类型:火锅",            dict(types="050117", pages=1)),
    (1, "food", "类型:海鲜酒楼",        dict(types="050119", pages=1)),
    (1, "food", "关键词:特色美食",      dict(keywords="特色美食", pages=2)),
    (1, "food", "关键词:老字号",        dict(keywords="老字号", pages=1)),
    (1, "food", "关键词:大排档",        dict(keywords="大排档", pages=1)),
    (1, "food", "关键词:苍蝇馆",        dict(keywords="苍蝇馆", pages=1)),
    (1, "food", "关键词:小吃",          dict(keywords="小吃", pages=2)),
    (1, "food", "关键词:本地菜",        dict(keywords="本地菜", pages=1)),
    # ── 特产 ──
    (1, "product", "关键词:特产",       dict(keywords="特产", pages=2)),
    (1, "product", "关键词:土特产",     dict(keywords="土特产", pages=1)),
    (1, "product", "关键词:地方特产",   dict(keywords="地方特产", pages=1)),
    # ── 商圈：商业街 / 购物 / 美食街 / 夜市 ──
    (1, "district", "类型:步行街",      dict(types="061001", pages=1)),
    (1, "district", "类型:特色商业街",   dict(types="061000", pages=2)),
    (1, "district", "类型:购物中心",     dict(types="060101", pages=3)),
    (1, "district", "类型:商场",        dict(types="060100", pages=2)),
    (1, "district", "关键词:美食街",     dict(keywords="美食街", pages=2)),
    (1, "district", "关键词:夜市",      dict(keywords="夜市", pages=2)),
    (1, "district", "关键词:小吃街",     dict(keywords="小吃街", pages=1)),
    (1, "district", "关键词:步行街",     dict(keywords="步行街", pages=1)),
    (1, "district", "关键词:购物中心",   dict(keywords="购物中心", pages=2)),
    # ── 商圈：酒吧 / 酒馆 / 娱乐 ──
    (1, "nightlife", "类型:酒吧",       dict(types="080304", pages=2)),
    (1, "nightlife", "关键词:酒馆",      dict(keywords="酒馆", pages=1)),
    (1, "nightlife", "关键词:LIVEHOUSE", dict(keywords="livehouse", pages=1)),
    (1, "nightlife", "类型:娱乐场所",    dict(types="080300", pages=1)),
    # ── 商场儿童游乐（用户 v0.6 新增维度）──
    (1, "kids", "关键词:儿童乐园",       dict(keywords="儿童乐园", pages=2)),
    (1, "kids", "关键词:电玩城",        dict(keywords="电玩城", pages=2)),
    (1, "kids", "关键词:游乐场",        dict(keywords="游乐场", pages=2)),
    (1, "kids", "关键词:迷你游乐场",     dict(keywords="迷你游乐场", pages=1)),
    (1, "kids", "关键词:亲子乐园",       dict(keywords="亲子乐园", pages=1)),
    (1, "kids", "关键词:淘气堡",        dict(keywords="淘气堡", pages=1)),
    (1, "kids", "关键词:儿童体验",       dict(keywords="儿童体验", pages=1)),
    # ── wave 2：酒店配套（用户 v0.7 新增）──
    (2, "hotel", "类型:住宿服务",       dict(types="100000", pages=1)),
    (2, "hotel", "关键词:酒店",         dict(keywords="酒店", pages=1)),
    # ── wave 2：迷你动物园 / 萌宠（用户 v0.7 新增）──
    (2, "kids", "关键词:迷你动物园",     dict(keywords="迷你动物园", pages=1)),
    (2, "kids", "关键词:萌宠乐园",       dict(keywords="萌宠乐园", pages=1)),
    (2, "kids", "关键词:室内动物园",     dict(keywords="室内动物园", pages=1)),
    (2, "kids", "关键词:动物园",        dict(keywords="动物园", pages=1)),
    # ── wave 2：休闲娱乐初版（密室/KTV/影院/棋牌，v0.7.1 起并入 wave 3）──
    (2, "adult", "关键词:密室逃脱",      dict(keywords="密室逃脱", pages=1)),
    (2, "adult", "关键词:KTV",          dict(keywords="KTV", pages=1)),
    (2, "adult", "关键词:电影院",        dict(keywords="电影院", pages=1)),
    (2, "adult", "关键词:棋牌室",        dict(keywords="棋牌室", pages=1)),
    # ── wave 2：百货 / 奥莱 / 批发城 ──
    (2, "district", "关键词:百货",       dict(keywords="百货", pages=1)),
    (2, "district", "关键词:奥特莱斯",    dict(keywords="奥特莱斯", pages=1)),
    (2, "district", "关键词:批发市场",    dict(keywords="批发市场", pages=1)),
    (2, "district", "关键词:商贸城",      dict(keywords="商贸城", pages=1)),
    # ── wave 3：休闲娱乐（用户 v0.7.1 正名，「成人娱乐」→「休闲娱乐」）──
    # 语义扩展：KTV/量贩KTV/夜店/酒吧/清吧/游乐场/卡丁车/体育馆/
    #           洗脚按摩/电影院/游戏厅/桌游/蹦床/密室
    # 类型码实测（v0.7.1 岳阳探测）：080101 运动场馆、080601 电影院、
    # 080301 KTV/夜总会；足疗按摩与卡丁车高德无独立类型码，走关键词
    (3, "leisure", "类型:运动场馆",      dict(types="080101", pages=2)),
    (3, "leisure", "类型:影剧院",        dict(types="080601", pages=2)),
    (3, "leisure", "类型:KTV/夜总会",    dict(types="080301", pages=2)),
    (3, "leisure", "关键词:足疗",        dict(keywords="足疗", pages=2)),
    (3, "leisure", "关键词:按摩",        dict(keywords="按摩", pages=1)),
    (3, "leisure", "关键词:卡丁车",       dict(keywords="卡丁车", pages=1)),
    (3, "leisure", "关键词:清吧",        dict(keywords="清吧", pages=1)),
    (3, "leisure", "关键词:夜店",        dict(keywords="夜店", pages=1)),
    (3, "leisure", "关键词:桌游",        dict(keywords="桌游", pages=1)),
    (3, "leisure", "关键词:蹦床",        dict(keywords="蹦床", pages=1)),
    (3, "leisure", "关键词:游乐场",       dict(keywords="游乐场", pages=1)),
    (3, "leisure", "关键词:游戏厅",       dict(keywords="游戏厅", pages=1)),
]


def city_cache_path(city):
    return os.path.join(RAW, city + ".json")


def load_progress():
    if os.path.exists(PROGRESS):
        with open(PROGRESS, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(p):
    os.makedirs(os.path.dirname(PROGRESS), exist_ok=True)
    with open(PROGRESS, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)


def normalize(p):
    """抽取建库所需字段，保留原始 id 与位置用于后续关联计算。

    v0.6.0：店名/地址中的 ASCII 竖线 `|` 会撑破 md 表格（实测
    「INXX CLUB(英克斯酒吧|濮阳店)」直接把表格列数 +1）。
    统一替换为全角竖线 `｜`，语义不变、表格安全。
    """
    biz = p.get("biz_ext") or {}
    loc = (p.get("location") or "").split(",")
    try:
        lng, lat = float(loc[0]), float(loc[1])
    except (IndexError, ValueError):
        lng = lat = None

    def pipe_safe(s):
        if not s:
            return s
        return s.replace("|", "｜")

    return {
        "id": p.get("id"),
        "name": pipe_safe(p.get("name")),
        "type": pipe_safe(p.get("type")),
        "typecode": p.get("typecode"),
        "address": pipe_safe(p.get("address")),
        "adcode": p.get("adcode"),
        "adname": p.get("adname"),
        "lng": lng,
        "lat": lat,
        "rating": biz.get("rating"),
        "cost": biz.get("cost"),
        "open_time": pipe_safe(biz.get("open_time")),
        "photos": [ph.get("url") for ph in (p.get("photos") or [])][:2],
        "tel": p.get("tel"),
    }


def collect_city(city, budget, verbose=False, dry=False, waves=(1, 2, 3)):
    """采集单城，返回该城缓存 dict。

    waves：跑哪几波查询面。补采时传 (2,) 只跑新增面，与已有缓存合并。
    """
    cache = {"city": city, "queries": {}, "errors": [], "updated": None}
    if os.path.exists(city_cache_path(city)):
        with open(city_cache_path(city), encoding="utf-8") as f:
            cache = json.load(f)
        # v0.6.2 修复：上次部分失败残留的 errors 会被继承，导致本次
        # 全量成功的城市仍被标记 ok=False（实测：武汉市 50 次请求全部
        # 成功，却因残留的 10005 记录被判受限）。重采即重新开始，
        # 旧错误一律清零，由本次运行结果决定状态。
        cache["errors"] = []
    spent = 0
    for wave, facet, label, spec in QUERIES:
        if wave not in waves:
            continue
        if budget is not None and spent >= budget:
            cache["errors"].append("预算耗尽，%s 未采" % label)
            break
        pages = spec.get("pages", 1)
        items, note = [], None
        for pg in range(1, pages + 1):
            params = {
                "city": city,
                "citylimit": "true",
                "extensions": "all",
                "offset": 20,
                "page": pg,
            }
            if spec.get("types"):
                params["types"] = spec["types"]
            if spec.get("keywords"):
                params["keywords"] = spec["keywords"]
            try:
                d = request(params)
            except QuotaExceeded as e:
                note = "配额受限：%s" % e
                cache["errors"].append(note)
                break
            except (KeyInvalid, DistrictBlocked) as e:
                note = str(e)
                cache["errors"].append(note)
                break
            spent += 1
            if budget is not None and spent >= budget:
                note = "预算耗尽于第 %d 页" % pg
                cache["errors"].append(note)
                break
            throttle()                 # v0.6.2 限速：单请求间隔 + 定期长休
            pois = d.get("pois") or []
            total = int(d.get("count") or 0)
            if not pois and pg == 1:
                note = "该查询面无结果（count=%s）" % total
            for p in pois:
                items.append(normalize(p))
            if len(pois) < 20 or total <= pg * 20:
                break
        # 去重（同一 POI 可能被多个查询面命中）
        seen, uniq = set(), []
        for it in items:
            if it["id"] and it["id"] in seen:
                continue
            if it["id"]:
                seen.add(it["id"])
            uniq.append(it)
        cache["queries"][label] = {
            "facet": facet,
            "spec": spec,
            "count": len(uniq),
            "items": uniq,
            "note": note,
        }
        if verbose:
            print("    %-22s %3d 条%s" % (label, len(uniq),
                                          "  ⚠ " + note if note else ""))
    cache["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cache["request_spent"] = spent
    done_waves = set(cache.get("waves") or [])
    done_waves |= set(waves)
    cache["waves"] = sorted(done_waves)
    # ── v0.6.0 核心修复：全查询面失败的城市绝不落盘 ──
    # 实测事故：高德 INVALID_USER_IP（10005）导致 44 城全查询面失败，
    # 空结果被当成真实数据写进缓存，渲染出「0 家美食 0 处商圈」的假档案。
    # 这类城市的正确状态是「未采集/不可用」，而不是「采集了但没有」。
    if not dry:
        # 补采波次（waves 不含 1）时，缓存里已有 wave1 数据，
        # 不能因「本轮查询面 0 条」就整体否决，只否决本轮全空。
        if 1 in waves:
            failed_all = (cache["queries"]
                          and all(q["count"] == 0
                                  for q in cache["queries"].values()))
        else:
            new_labels = {lbl for wv, _f, lbl, _s in QUERIES if wv in waves}
            new_qs = [q for lbl, q in cache["queries"].items()
                      if lbl in new_labels]
            failed_all = (new_qs
                          and all(q["count"] == 0 for q in new_qs))
        if failed_all:
            if 1 not in waves:
                # 补采失败：只回滚本轮新增的查询面，保留 wave1 数据
                for lbl in new_labels:
                    cache["queries"].pop(lbl, None)
                cache["waves"] = sorted(done_waves - set(waves))
                with open(city_cache_path(city), "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False)
            elif os.path.exists(city_cache_path(city)):
                os.remove(city_cache_path(city))
            raise DistrictBlocked(
                "%s 本轮 %d 个查询面均返回 0 条，判定为接口故障而非"
                "「该城无数据」；不生成假档案。"
                % (city, len(cache["queries"])))
        os.makedirs(RAW, exist_ok=True)
        with open(city_cache_path(city), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    return cache


def main():
    ap = argparse.ArgumentParser(description="高德 POI 采集器")
    ap.add_argument("--province", help="只跑该省，如 湖南省")
    ap.add_argument("--city", help="只跑该市，如 岳阳市")
    ap.add_argument("--all", action="store_true", help="跑全国")
    ap.add_argument("--budget", type=int, default=None,
                    help="单次运行总请求上限（防打爆日配额）")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--pace", type=float, default=0.6,
                    help="单请求间隔秒数（默认 0.6；越大越慢越稳）")
    ap.add_argument("--dry", action="store_true", help="不落盘")
    ap.add_argument("--force", action="store_true", help="重跑已完成城市")
    ap.add_argument("--wave", default="1,2,3",
                    help="跑哪些查询波次：1=基础面 2=新增面（酒店/动物园/"
                         "休闲娱乐）。补采用 --wave 3")
    args = ap.parse_args()
    PACE["req"] = max(0.2, args.pace)
    try:
        waves = tuple(sorted({int(x) for x in args.wave.split(",")
                              if x.strip()}))
    except ValueError:
        raise SystemExit("--wave 只能是 1/2/3，如 --wave 3")
    if not waves:
        raise SystemExit("--wave 不能为空")

    provs = json.load(open(
        os.path.join(CACHE, "prov_cities.json"), encoding="utf-8"))

    cities = []
    if args.city:
        cities = [args.city]
    elif args.province:
        cities = [c[1] for c in provs.get(args.province, {}).get("cities", [])]
    elif args.all:
        for v in provs.values():
            cities += [c[1] for c in v["cities"]]

    prog = load_progress()
    done, skipped, failed = 0, 0, 0
    budget_left = args.budget
    for city in cities:
        prev = prog.get(city) or {}
        prev_waves = set(prev.get("waves") or (1,))   # 旧记录无 waves 视为已采 wave1
        # 只跑「缺失波次」：老城市已有 wave1 就只补 wave2，不重复采
        run_waves = tuple(sorted(set(waves) - prev_waves))
        if not args.force and prev.get("ok") and not run_waves:
            skipped += 1
            continue
        if run_waves and 1 not in prev_waves and not args.force:
            # 补采波次（wave2/3）要求 wave1 已采；否则会造出只有新维度的残档
            skipped += 1
            continue
        if budget_left is not None and budget_left <= 0:
            print("⛔ 预算耗尽，停止。已完成 %d 城。" % done)
            break
        try:
            cache = collect_city(city, budget_left, args.verbose, args.dry,
                                 run_waves or waves)
        except QuotaExceeded as e:
            print("⛔ 配额受限，停止后续采集：%s" % e)
            break
        except KeyInvalid as e:
            print("⛔ key 无效，终止：%s" % e)
            sys.exit(2)
        except DistrictBlocked as e:
            # 单城接口故障：记入进度但不中断整批（其他城可能仍然可用）
            failed += 1
            prog[city] = {
                "ok": False,
                "blocked": True,
                "errors": [str(e)[:120]],
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_progress(prog)
            print("  ⛔ %s：接口故障，跳过（%s）"
                  % (city, str(e)[:70]))
            continue
        n = sum(q["count"] for q in cache["queries"].values())
        errs = cache["errors"]
        prog[city] = {
            "ok": not errs,
            "pois": n,
            "queries": len(cache["queries"]),
            "spent": cache.get("request_spent"),
            "waves": sorted(prev_waves | set(run_waves or waves)),
            "errors": errs[:5],
            "at": cache["updated"],
        }
        save_progress(prog)
        if budget_left is not None:
            budget_left -= cache.get("request_spent") or 0
        if errs:
            failed += 1
            print("  ⚠ %s：%d 条 / %s" % (city, n, errs[0][:60]))
        else:
            done += 1
            print("  ✅ %s：%d 条 POI（%d 次请求）"
                  % (city, n, cache.get("request_spent")))
        throttle(city_rest=True)      # 城间休息，避免连续高压
    save_progress(prog)
    print("\n完成 %d 城，跳过 %d，受限 %d。进度见 %s"
          % (done, skipped, failed, PROGRESS))


if __name__ == "__main__":
    main()
