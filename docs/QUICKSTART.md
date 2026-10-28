# HSBRSIM 快速开始（一键环境 + 一键训练）

> 目标：**克隆 → 一条命令装好环境 → 一条命令开始训练**。
> 全仓库只需要 Python ≥3.10、Rust ≥1.98（编译引擎用）、可选 1–4 张 NVIDIA GPU。

## 0. 系统要求

| 组件 | 要求 | 说明 |
|---|---|---|
| OS | Linux（推荐）/ macOS | Windows 需要 WSL2 |
| Python | ≥3.10 | 训练需要 PyTorch ≥2.0 |
| Rust | ≥1.98 | 编译 `hsbg_engine`；`rust/rust-toolchain.toml` 已固定版本 |
| GPU | 可选，0–4 张 | 单卡可跑；4 卡（每卡 2 进程）是 stage-1 的实测配置 |
| 磁盘 | ≥20 GB | 引擎编译产物 + checkpoint（每个 61 MB）+ records 临时文件 |

## 1. 一键装环境

```bash
git clone https://github.com/Gallo13th/HSBRSIM.git
cd HSBRSIM
bash scripts/bootstrap.sh
```

它会：装 Python 依赖（`pip install -e ".[train,dev,plot]"`）→ 编译安装 Rust 引擎
（`cd rust && pip install -e .`，首次 2–5 分钟）→ 打印引擎版本/数据版本 → 跑快速门禁
（`scripts/verify_all.py --fast`）。

可选环境变量：`PYTHON=/path/to/python`、`SKIP_PIP=1`（复用已有 torch）、
`SKIP_ENGINE=1`（引擎已装好）。

## 2. 一键训练

```bash
# (a) 冒烟：tiny 网络、2 分钟、验证链路（CPU 即可）
bash scripts/train_stage1.sh --smoke

# (b) 小预算：单卡 5M decisions（约 1 小时）
bash scripts/train_stage1.sh --gpus 0 --decisions 5M

# (c) 完整 stage-1：4 卡、30M decisions
#     旧串行版实测 5h18m；开流水线后实测 3,100 dec/s ≈ 2.7–3h（含评测）
bash scripts/train_stage1.sh --gpus 0,5,6,7 --decisions 30M
# 想关掉流水线：PIPELINE=0 bash scripts/train_stage1.sh ...
```

脚本的默认行为：

1. **起点**：若存在 `runs/az_entity_1m_s0/model.pt` 就用它；否则先跑 **BC 冷启动**
   （`train_bc_bot.py`，50 万样本，8–15 分钟），所以**不需要我们私有的 checkpoint**；
2. **训练**：`train_entity_sync.py`，entity 14.8M、`sims=0`（无 MCTS）、
   **double-buffer 流水线**（`PIPELINE=1`，实测 3,100 dec/s；脚本会自动把 learner 卡
   从 actor 列表里剔除——同卡会让两者互抢、只剩 +19% 而非 +44%）、论文超参
   （clip 0.2 / target KL 0.05 / λ=0.995 / entropy 0.002 / grad-clip 1.0 /
   lr 6e-6→5e-6 / 有效 minibatch 8192 梯度累积）、**KL anchor β=0.1 前 100 iter**；
3. **监控**：每 5M decisions 自动跑 512 局 C0 评测（`eval/history.json`）；
4. **收尾**：未见面板（seed_base 440000）再跑一次 512 局，并汇总曲线。

常用参数：`--gpus 0,1`、`--processes 4`、`--threads 8`、`--games 128`、
`--init runs/xxx/model.pt`、`--out runs/my_run`、`--seed 900`。

## 3. 预期结果（本机实测，供对照）

stage-1（30.08M decisions，4 卡，5h18m）在 512 局 C0 上的曲线：

| decisions | mean rank | top4 | 说明 |
|---:|---:|---:|---|
| 0（起点） | 4.70 | 44.9% | 1M sims=0 基线 |
| 1.1M（流水线复核） | 3.40 | 71.9% | 同 seed 串行 3.47，配对 CI 覆盖 0 |
| 10.01M | 4.40 | 52.7% | 首次统计显著（配对 CI 不含 0） |
| 15.02M | 4.18 | 59.4% | |
| 25.02M | 4.08 | 60.2% | |
| **30.02M** | **3.52** | **70.7%** | 未见面板 3.63–3.65 |

曲线：`runs/<run>/eval/stage1_curves.png`；分析：`python scripts/analyze_stage1.py --run runs/<run>`。
细节与解读见 `docs/MULTISTAGE_TRAINING.md` §12。

## 4. 仓库里有什么、没有什么

| 已入库 | 说明 |
|---|---|
| `hsbg/`（搜索/训练/评测 + 库原型） | 唯一训练栈 |
| `rust/`（引擎源码 + `data/cards.json`） | `hsbg_engine` fork |
| `data/`、`data/p2/` | 37.0.0.255790 派生数据 |
| `scripts/`（bootstrap / train_stage1 / bench / eval / plot） | 入口 |
| `docs/`（架构、契约、训练设计、结果、吞吐、竞技场） | 设计与结果 |
| `tests/` | 门禁 |

| 不入库（`.gitignore`） | 获取方式 |
|---|---|
| `runs/`（checkpoint、曲线、日志） | 训练产生；`runs/<run>/model.pt` 每个 61 MB |
| `reversed/hsdata_*/`（原始 xml） | 用 `tools/rea_fetch_hsdata.py` 重新拉 |
| `rust/target/`、`*.so` | 由 `bootstrap.sh` 编译 |
| 竞技场密钥 | 只从环境变量 `ARENA_API_KEY` 读，**永远不入库** |

## 5. 常见问题

**Q: `pip install -e .` 报 `Cannot import 'maturin'`？**
A: 不要加 `--no-build-isolation`；正常 `pip install -e rust/` 会自动装 maturin。
若离线，先 `pip install "maturin>=1.15,<2"`。

**Q: `verify_all.py` 里 `data_check` 被 SKIP？**
A: 正常。数据重建校验需要上游 AutoTavern checkout（`HSBRSIM_AT_ROOT` 或 `../AutoTavern`）；
日常开发与训练不需要它。

**Q: 只有 1 张卡 / 想限制显存？**
A: 用 `--gpus 0 --processes 2 --threads 16 --games 64`；每个 actor 进程约 0.6 GB 显存，
learner 峰值约 12 GB（微批 1024、fp32）。

**Q: GPU 被别人占了？**
A: `nvidia-smi --query-gpu=index,memory.used --format=csv` 先看；`--gpus` 只填空闲卡。
`scripts/bench_process_pool.py` 会拒绝在忙碌卡上跑（`--allow-busy` 可强行）。

**Q: 训练要不要 MCTS？**
A: stage-1 不需要（`sims=0`）。论文也没有搜索；`--sims 4` 只用于消融，吞吐约降 6–7 倍。

**Q: 想接在线竞技场？**
A: 见 `docs/ARENA.md`；需要 `ARENA_API_KEY` 环境变量（自备账号），模型只在本地推理。

## 6. 复现我们报告里的具体数字

```bash
# stage-1（4 卡）
bash scripts/train_stage1.sh --gpus 0,5,6,7 --decisions 30M --seed 900 --out runs/az_entity_kl_30m

# 吞吐基线（sims=0，3 分钟）
PYTHONPATH=rust/python:. python scripts/bench_process_pool.py \
  --checkpoint runs/az_entity_kl_30m/model.pt --arch entity \
  --processes 8 --gpus 0,5,6,7 --threads 16 --games 192 --sims 0 \
  --warmup-rounds 0 --minutes 3 --out runs/bench/sims0_3min.json

# 单 iteration 时间轴（Gantt）
python scripts/plot_iteration_timeline.py --run runs/az_entity_kl_30m --iter 3 \
  --out runs/profile_timeline/iteration_timeline.png
```

> 注意：不同 GPU（4090 vs H200）、不同 CPU 核数、不同并发下，**吞吐会差 2–4 倍**，
> 但 same-seed 的 C0 曲线形状应当一致；比较时请先跑 `--smoke` 与 5M 小预算。
