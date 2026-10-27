# HSBRSIM Web 控制台（本地）

一个**无第三方 Web 依赖**的本地页面，用于查看状态、评测训练结果、浏览 runs/checkpoint 和
TavernBench 评分。基于标准库 `ThreadingHTTPServer`，仅监听 `127.0.0.1`。

> 说明：AutoTavern 公开仓库（main，commit `fb61201`）**没有 web 前端**；这里复用它
> vendored 到本仓库的 TavernBench 评分快照，并提供 HSBRSIM 自己的轻量控制台。

## 启动

```powershell
cd C:\HSagent
python scripts/webui.py --port 8765
# 或
python -m hsbg.webui.server --port 8765
```

浏览器打开 <http://127.0.0.1:8765>。

## 功能

| 标签 | 内容 |
|---|---|
| 概览 / 状态 | 主引擎（优先 `hsbg_engine`，否则 legacy `hsrl2`）、版本、backend、checkpoint/runs 数 |
| 评测训练结果 | 调 `python -m hsbg.rl.evaluate`：random/heuristic/teacher/checkpoint；显示 mean rank、top4/win、games/s、名次分布 |
| Runs / Checkpoints | 扫描 `runs/**/*.json`、`*.pt/.pth/.ckpt/.npz`，显示最近产物 |
| TavernBench | 展示 vendored `benchmarks/tavernbench/expected/eval_report.json` 的已发布系统评分；可跑 `--check` |

评测结果写到 `runs/webui/eval_<timestamp>.json`，同时出现在 Runs 页。

## 示例

```powershell
# 打开页面后：
# 1) policy=heuristic, episodes=5, backend=auto → 开始评测
# 2) 若要测 checkpoint：policy=runs/bc/.../policy_bc.pt
```

## 设计边界

- 只监听 localhost；无认证，不要绑定 `0.0.0.0` 到公网。
- 评测是同步子进程（timeout 900s），页面会等待；大 episodes 建议用 CLI/后台。
- Rust 主引擎未安装时页面显示 `hsrl2-legacy`，评测 backend=`auto` 自动走可用后端。
- TavernBench 页面只读发布快照；真正重打分用 `scripts/run_tavernbench.py`。

## 对战回放（搜索 + Bot 先验）

页面新增「对战回放」标签，读取：

```text
runs/webui/search_botprior_demo.json
```

生成回放（需在已构建 `hsbg_engine` 的机器上运行；当前本地 Web 页面只负责展示）：

```bash
cd ~/projects/HSBRSIM
PYTHONPATH=$PWD:$PWD/rust/python python scripts/az_webui_match.py   --seed 90004 --simulations 32 --determinizations 2   --out runs/webui/search_botprior_demo.json
```

回放内容：

- seat0：`search_az + BotPriorEvaluator`（特权先验，仅演示/诊断；不是 AZ 训练输入）；
- 其余 7 座：引擎 bot；
- 展示 rank、回合、决策数、耗时、每步动作/搜索根价值/visits；
- 可逐步查看 seat0 的 board/hand/shop、对手公开血量/tier/最近战团。

本机示例（2026-10-27）：

```text
seed=90004, rank=1, turns=15, decisions=244, 6.2s
placements=[1,3,8,4,6,2,5,7]
```
