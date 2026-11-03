# CLEANUP_DONE — P2 runs 权重清理验收（2026-11-04）

> 执行 repo-clean；Lead 00:41 GO。只动 `runs/`；`data/`、`reversed/`、`$t/`、`.tmp_trace/` 未动（P3）。**未 commit**。
> 配套证据：`runs/_archive/DELETED_MANIFEST.jsonl`（2012 删除项 + 311 保留项，保留项含 sha256）。

## 1. 结果

| 指标 | 前 | 后 | 变化 |
|---|---:|---:|---|
| `runs/` | 207G | **7.0G** | −200G（du） |
| 删除 | — | **2012 项 / 214.05 GB** | 零 missing、保护项命中 0 |
| `/home/data` 空闲 | 5754.4G | **5967.8G** | **+213.4G**（含训练轮转删除） |
| `runs/` 目录数 | 250 | 250 | 未丢 run 目录 |

## 2. 批次（≤30G/批，记前后 df；箭头=批后 df）

B1 217项/29.88G/36.6s→5784.3G；B2 243/29.78/27.2→5814.1；B3 236/29.77/41.1→5843.9；B4 184/27.78/72.9→5871.6
B5 453/28.15/47.9→5899.8；B6 186/29.48/26.0→5929.2；B7 95/14.77/11.8→5943.8；B8 398/24.43/60.9→5967.8
> B8 修正 pass-1 剪枝误跳过嵌套 `arm*/snapshots`、`_weights`（遗留 387 .pt/26.3G），按同规则补删并清 61 个空权重目录。
> 训练同期健康：iter 443→498，dec/s 10.6–11.6k（末 20 中位 11.35k），illegal=0，未触发 <5k 暂停线。

## 3. 保护项校验（全部存在）

`s61`（23 文件/1.43G）：ckpt `a2bd7f0c58b0722c5d1fe4e662334bde9ce3d114a06d754aff441ec3c0f4478c`、trainer `5cfa5d32…f7396`、model `7ff9cd50…bcdf`，与清理前一致。
`s73`（20 文件/1.11G）：训练中；model.pt sha 待训练+评测完成后重算（本文件不写临时值）。
其余：`eval_panel` 17 文件/20KB、`comp_scripts` 152/10M、`_lead` 7、`_archive` 10、`exam` 42/407.6M、`quality` 69；
`CHAIN_300M.csv` 仅表头（原件快照 `runs/_archive/CHAIN_300M.csv.precleanup`），`CHAIN_300M.log` 与 `next_block.sh` 在。

## 4. 保留清单

- **12 个历史 eval ckpt（751.3MB）**：s14 `ckpt_120027725`、s8b `ckpt_030016228`、s13 `ckpt_120013838`、s15 `ckpt_030023070`、s10 `ckpt_060003693`、s25 `ckpt_010070431`、s58×2、s59×2、s60b、s72。
- **8 个根级 `champion_c0_*.pt`（505MB）**：1746/1768/1975/2182/2279/2279_seq/2760/3004（Lead 指示保留，C0 门禁证据）。
- `s61/**`、`s73/**` 全保留；所有 run 的 `history.jsonl`/`latest.json`/`summary.json`/`eval/*.json`/`*.log` 保留。

## 5. stale panel 处置

`s62_final.json`、`s63_final.json`（2113B，与 `s61_20m.json` 同长，chain 复评旧 ckpt 的错账）、`s64_final.json`（0B）
→ `runs/_archive/stale_panel/`，README 标注「chain 错账，勿引用」；`runs/eval_panel` 现 17 文件。

## 6. 剩余体积与 `.pt` 构成（4.44G / 53 文件）

| 分组 | 文件 | 体积 |
|---|---:|---:|
| s73（protected，在涨） | 13 | 1356.6MB |
| s61（protected） | 14 | 1424.4MB |
| exam（protected） | 6 | 407.2MB |
| 保留历史 eval ckpt | 12 | 751.3MB |
| 根级 champion | 8 | 505.0MB |

其余 ~2.6G 为 metadata，大头：`az_entity_1m_s0` 753M（summary/history 各 394M）、`scaling_carrier` 438M、`exam` 389M。

## 7. 证据与边界

证据：`runs/_archive/{DELETED_MANIFEST.jsonl,README.md,CHAIN_300M.csv.precleanup}`、`runs/_archive/stale_panel/README.md`。
未动：`data/` 6.1G、`reversed/` 16M、`$t/` 75K、`.tmp_trace/` 24K（P3）。遗留：s73 sha 终算；task-10 待 task-8 解依赖后 claim/complete。
