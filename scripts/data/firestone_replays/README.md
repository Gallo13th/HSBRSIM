# data/firestone_replays

Firestone Web 回放（BG）原始数据与派生动作样本。抓取/解析说明见
`docs/FIRESTONE_REPLAY_INGEST.md`。

| 路径 | 说明 |
|---|---|
| `bgs-perfect-games.json` | 公开 feed 原始快照（1000 条，约 5 天窗口） |
| `index.json` | 本次采集的 500 局元数据（reviewId / replayKey / MMR / 英雄 / 回合数） |
| `xmlz/<reviewId>.xml.zip` | HSReplay XML（zip 内 `replay.xml`，约 11 MB 解压） |
| `pms/<reviewId>.json` | Firestone post-match stats（含双方 `battleInfo` 战团） |
| `firestone_recent_actions.jsonl.gz` | 149,166 条逐动作样本（XML Block 解析） |

原始 XML/PMS 体积约 455 MB，`.gitignore` 已排除；只保留派生的小文件。
重新生成：

```bash
python scripts/fetch_firestone_replays.py --root data/firestone_replays --limit 500 --workers 4
python scripts/parse_firestone_replay_xml.py --workers 8
```

解析产物：

- `data/real_library/library_firestone_recent.jsonl`（10,811 行战团帧）
- `data/real_library/library_firestone_recent_stats.json`（统计/覆盖/一致性）
- `data/firestone_replays/firestone_recent_actions.jsonl.gz`（动作样本）
