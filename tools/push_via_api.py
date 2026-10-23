#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
push_via_api.py — 当 github.com 的 git 传输不可达时，改用 GitHub REST API（Git Data API）
把本地工作区的改动推到远端分支。

流程：读远端 ref -> 读父 commit 的 tree -> 逐文件建 blob（删除项写 sha=null）
      -> 建 tree -> 建 commit -> 更新 ref。

用法:
  python tools/push_via_api.py --owner MrdT-BitsNote --repo fun --branch main \
      --token-file /tmp/gh_valid_token --since HEAD~1 --message "..."

分两批推送的大文件阈值由 --max-blob 控制（默认 5MB），超过的单独成一批，
避免单个超大请求失败连累整次提交。
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://api.github.com"


def req(method, url, token, payload=None, retries=4, timeout=300):
    body = json.dumps(payload).encode() if payload is not None else None
    for attempt in range(1, retries + 1):
        r = urllib.request.Request(url, data=body, method=method)
        r.add_header("Authorization", "token " + token)
        r.add_header("Accept", "application/vnd.github+json")
        r.add_header("User-Agent", "fun-site-publisher")
        if body:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code in (401, 403, 404, 422):
                raise SystemExit(f"[api] {method} {url} -> HTTP {e.code}: {detail}")
            if attempt == retries:
                raise SystemExit(f"[api] {method} {url} -> HTTP {e.code}: {detail}")
        except Exception as e:                                    # 网络层
            if attempt == retries:
                raise SystemExit(f"[api] {method} {url} -> {type(e).__name__}: {e}")
        wait = min(2 ** attempt, 20)
        print(f"   重试 {attempt}/{retries - 1}（{wait}s）", flush=True)
        time.sleep(wait)


def git(*args):
    return subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                          capture_output=True, text=True, check=True).stdout


def collect(since, max_blob):
    """返回 (小文件列表, 大文件列表, 删除列表)；每项 (path, status)。"""
    out = git("diff", "--name-status", since, "HEAD")
    small, big, deleted = [], [], []
    for ln in out.splitlines():
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        st, path = parts[0], parts[-1]
        if st == "D":
            deleted.append(path)
            continue
        if not os.path.isfile(path):
            continue
        (big if os.path.getsize(path) > max_blob else small).append(path)
    return small, big, deleted


BLOB_CACHE = "/tmp/blob_cache.json"


def _cache_load():
    if os.path.isfile(BLOB_CACHE):
        try:
            return json.load(open(BLOB_CACHE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _cache_save(c):
    with open(BLOB_CACHE, "w", encoding="utf-8") as f:
        json.dump(c, f)


def commit_batch(owner, repo, branch, token, files, deletes, message, workers=6,
                 chunk=180):
    ref = req("GET", f"{API}/repos/{owner}/{repo}/git/ref/heads/{branch}", token)
    parent = ref["object"]["sha"]
    pc = req("GET", f"{API}/repos/{owner}/{repo}/git/commits/{parent}", token)
    tree_sha = pc["tree"]["sha"]
    print(f"  父 commit {parent[:10]} · 基线 tree {tree_sha[:10]}", flush=True)

    cache = _cache_load()
    files = sorted(files)
    done = {"n": 0, "reuse": 0}

    def upload(path):
        st = os.stat(path)
        key = f"{path}|{st.st_size}|{int(st.st_mtime)}"
        hit = cache.get(key)
        if hit:
            done["n"] += 1
            done["reuse"] += 1
            return {"path": path, "mode": "100644", "type": "blob", "sha": hit}
        with open(path, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        blob = req("POST", f"{API}/repos/{owner}/{repo}/git/blobs", token,
                   {"content": content, "encoding": "base64"})
        cache[key] = blob["sha"]
        done["n"] += 1
        print(f"  [{done['n']}/{len(files)}] {path} ({st.st_size/1048576:.2f} MB)", flush=True)
        return {"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}

    entries = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for ent in pool.map(upload, files):
            entries.append(ent)
    _cache_save(cache)
    print(f"  blob 完成: 新建 {done['n'] - done['reuse']} / 复用 {done['reuse']}", flush=True)

    for path in sorted(deletes):
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
    print(f"  tree 条目: {len(entries)}（删除 {len(deletes)}）", flush=True)

    # GitHub 单次建树条目过多会 422（input too large），改为分块增量建树
    n_chunk = 0
    for i in range(0, len(entries), chunk):
        part = entries[i:i + chunk]
        n_chunk += 1
        t = req("POST", f"{API}/repos/{owner}/{repo}/git/trees", token,
                {"base_tree": tree_sha, "tree": part})
        tree_sha = t["sha"]
        print(f"  tree 分块 {n_chunk}: {len(part)} 条 -> {tree_sha[:10]}", flush=True)

    cm = req("POST", f"{API}/repos/{owner}/{repo}/git/commits", token,
             {"message": message, "tree": tree_sha, "parents": [parent]})
    req("PATCH", f"{API}/repos/{owner}/{repo}/git/refs/heads/{branch}", token, {"sha": cm["sha"]})
    print(f"  ✅ 提交 {cm['sha'][:10]} 已更新 {branch}", flush=True)
    return cm["sha"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--since", default="HEAD~1")
    ap.add_argument("--message", required=True)
    ap.add_argument("--max-blob", type=int, default=5 * 1024 * 1024)
    ap.add_argument("--batch", choices=["small", "big", "all"], default="all")
    a = ap.parse_args()

    token = open(a.token_file, encoding="utf-8").read().strip()
    small, big, deleted = collect(a.since, a.max_blob)
    print(f"[plan] 小文件 {len(small)} / 大文件 {len(big)} / 删除 {len(deleted)}", flush=True)

    if a.batch in ("small", "all") and (small or deleted):
        commit_batch(a.owner, a.repo, a.branch, token, small, deleted,
                     a.message + "（站点与文档）")
    if a.batch in ("big", "all") and big:
        commit_batch(a.owner, a.repo, a.branch, token, big, [],
                     a.message + "（全量数据文件）")
    print("[done] 全部推送完成", flush=True)


if __name__ == "__main__":
    main()
