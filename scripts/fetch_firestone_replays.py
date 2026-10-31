#!/usr/bin/env python3
"""抓取 Firestone 公开的 Battlegrounds 回放（最近 1000 局 perfect-games feed）。

已探明的三个公开端点（2026-10，无需登录、无 Cloudflare challenge）：

1. 列表 feed::

       https://static.zerotoheroes.com/api/bgs/bgs-perfect-games.json

   最近约 5 天的 curated BG 对局（1000 条），字段含 ``reviewId`` / ``replayKey`` /
   ``playerRank`` / ``buildNumber`` / ``gameDurationTurns`` / ``bgsCompArchetype``。

2. 回放 XML（zip 内是 ``replay.xml``，HSReplay 格式，~11 MB/局）::

       https://xml.firestoneapp.com/<replayKey>
       # replayKey = hearthstone/replay/YYYY/MM/DD/<reviewId>.xml.zip

3. Firestone post-match stats（gzip JSON，~190 KB/局）::

       https://bgs-post-match-stats.firestoneapp.com/<reviewId>.gz.json

   其中 ``battleResultHistory[].battleInfo`` 同时含 ``playerBoard`` /
   ``opponentBoard`` 的完整战团、英雄血量、酒馆等级，是解析战团的首选来源。

另外，replay 观看页的 SPA bundle 用到的单条元数据端点（可选，本脚本不需要）::

    GET https://itkmxena7k2kkmkgpevc6skcie0tlwmk.lambda-url.us-west-2.on.aws//<reviewId>
    header: x-firestone-client: coliseum

用法::

    python scripts/fetch_firestone_replays.py --root data/firestone_replays \
        --limit 500 --workers 4

礼貌抓取：并发 <=4、每请求重试 <=2、只补缺失文件。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

FEED_URL = "https://static.zerotoheroes.com/api/bgs/bgs-perfect-games.json"
XML_URL = "https://xml.firestoneapp.com/"
PMS_URL = "https://bgs-post-match-stats.firestoneapp.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
LOCK = threading.Lock()
DONE = [0]
FAIL = []


def _get(url: str, dest: str, retries: int = 2, min_bytes: int = 1024) -> bool:
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Referer": "https://replays.firestoneapp.com/",
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            if len(data) < min_bytes:
                raise ValueError(f"short body {len(data)}")
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return True
        except Exception as e:  # noqa: BLE001
            if attempt == retries:
                with LOCK:
                    FAIL.append({"url": url, "error": f"{type(e).__name__}: {e}"})
                return False
            time.sleep(1.0 * (attempt + 1))
    return False


def fetch_feed(root: str) -> list:
    path = os.path.join(root, "bgs-perfect-games.json")
    if not os.path.exists(path) or os.path.getsize(path) < 1024:
        print(f"feed -> {path}", file=sys.stderr)
        if not _get(FEED_URL, path, retries=2, min_bytes=1024):
            raise SystemExit("could not download feed")
    return json.load(open(path, "r", encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/firestone_replays")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-xml", action="store_true")
    ap.add_argument("--skip-pms", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    xmlz = os.path.join(root, "xmlz")
    pms = os.path.join(root, "pms")
    os.makedirs(xmlz, exist_ok=True)
    os.makedirs(pms, exist_ok=True)
    games = fetch_feed(root)
    games.sort(key=lambda g: g.get("creationTimestamp") or 0, reverse=True)
    games = [g for g in games if g.get("reviewId") and g.get("replayKey")]
    games = games[args.offset: args.offset + args.limit]

    index = []
    tasks = []
    for g in games:
        rid = g["reviewId"]
        index.append({
            "reviewId": rid,
            "replayKey": g.get("replayKey"),
            "creationDate": g.get("creationDate"),
            "creationTimestamp": g.get("creationTimestamp"),
            "buildNumber": g.get("buildNumber"),
            "playerCardId": g.get("playerCardId"),
            "playerRank": g.get("playerRank"),
            "gameDurationTurns": g.get("gameDurationTurns"),
            "gameDurationSeconds": g.get("gameDurationSeconds"),
            "bgsCompArchetype": g.get("bgsCompArchetype"),
            "bgsAvailableTribes": g.get("bgsAvailableTribes"),
            "bgsBannedTribes": g.get("bgsBannedTribes"),
            "finalComp": g.get("finalComp"),
            "anomalies": g.get("anomalies"),
            "postMatchStats": g.get("postMatchStats"),
            "source": "bgs-perfect-games",
        })
        if not args.skip_xml:
            dest = os.path.join(xmlz, rid + ".xml.zip")
            if not (os.path.exists(dest) and os.path.getsize(dest) > 1024):
                tasks.append((XML_URL + g["replayKey"], dest, "xml"))
        if not args.skip_pms:
            dest = os.path.join(pms, rid + ".json")
            if not (os.path.exists(dest) and os.path.getsize(dest) > 200):
                tasks.append((PMS_URL + rid + ".gz.json", dest, "pms"))

    with open(os.path.join(root, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"games={len(games)} todo={len(tasks)} workers={args.workers}", file=sys.stderr)

    def work(t):
        url, dest, kind = t
        ok = _get(url, dest, retries=2, min_bytes=200 if kind == "pms" else 1024)
        with LOCK:
            DONE[0] += 1
            n = DONE[0]
        if n % 25 == 0 or not ok:
            print(f"  {n}/{len(tasks)} ok={ok} {kind}", file=sys.stderr)
        return ok

    t0 = time.time()
    if tasks:
        with ThreadPoolExecutor(max_workers=max(1, min(4, args.workers))) as ex:
            for f in as_completed([ex.submit(work, t) for t in tasks]):
                f.result()
    print(f"done={DONE[0]}/{len(tasks)} fail={len(FAIL)} elapsed={time.time()-t0:.1f}s",
          file=sys.stderr)
    if FAIL:
        print(json.dumps(FAIL[:10], ensure_ascii=False, indent=1), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
