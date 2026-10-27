# 训练：不完全信息 MCTS + 自对弈 + PPO

唯一训练栈：`hsbg/az/train`（不完全信息 MCTS + 自对弈 + PPO）。

## 1. 问题形式

- 单座位 POMDP：状态 = 8 人完整对局；观测 `o = observe(seat)`（3227 floats + 124 cards），
  只含客户端可见信息。
- 动作：245 个固定离散动作（0..244），精确 mask；扩展段 245..273 只用于环境完整性，
  **AZ 训练/搜索严格只用 245**。
- 回报：终局名次 utility `z = 1 - 2*(rank-1)/7 ∈ [-1, 1]`。

## 2. 不完全信息 MCTS

`hsbg/az/search.py`：

```text
公开观测 o_t
  → belief sampler 采样 W 个隐藏世界（determinization）
  → 每个世界：PUCT（P = 网络先验 / 启发式先验；Q = 子树回报）
  → 根 visit 数跨世界聚合 → π[245]
  → 温度采样 / argmax + 根先验 tie-break
```

- 只使用 `observe(seat)` 与 `legal_mask(seat)`；不允许 `view()` 的隐藏信息进入策略。
- Rust 后端调用 `hsbg_engine.mcts_search`（`EndTurn` 宏动作内折叠 7 座 bot + 配对/战斗 RNG）；
  Python 后端是同构 PIMC 对照，支持 `resample_on_end_turn` 作为 chance 节点对照。
- 任何 eval 异常 / 非法动作 / 全失败 → 合法动作或 bot 兜底，不抛到训练进程。

## 3. 自对弈

`hsbg/az/train/selfplay.py` 两条路径：

1. `mode="game"`：`Game` 逐座驱动，可接 MCTS/网络策略，收 `(features,cards,mask,π,action,rank)`；
2. `mode="batch"`：`BatchEnv(controlled=range(8))` 快速 8 座自对弈（轻量网络）。

终局把 rank 回填为 utility；`π` 来自 MCTS 或 one-hot 行为策略。

## 4. 策略/价值网络

`hsbg/az/train/entity_model.py`（AutoTavern 风格实体 Transformer）与 `model.py`（tiny smoke）：

- 实体 token：己方 7 随从 + 10 手牌 + 8 酒馆 + 16 待选 + 7 对手 + 1 global；
- 卡牌 = identity embedding + 静态特征 + 规则文本 hash embedding；
- pointer head 输出 245 masked logits；
- 名次头 8 logits → placement/value；
- 默认 d=384/8 层/8 头/约 18M 参数；`arch="tiny"` 用于快速 smoke。

## 5. 训练阶段

```text
A. 冷启动：MCTS/启发式先验自对弈 → 策略 CE(π) + 名次价值 CE
B. PPO：自对弈轨迹（网络行为）→ GAE(λ) + clipped ratio + value/rank loss + entropy
         （π 可作为辅助 CE 目标；KL 早停）
C. 评测：固定 seed，seat0=被评策略 vs 7 引擎 bot；mean rank / top4 / win / legal rate
D. 迭代：新 checkpoint 进入自对弈/对手池；重复 A–C
```

PPO 命令：

```bash
python scripts/train_az_ppo.py --games 2 --epochs 1 --arch tiny --device cpu --out runs/az_ppo
```

监督 smoke：

```bash
python scripts/az_selfplay_smoke.py --games 2 --epochs 2 --arch tiny --device cpu
```

## 6. 确定性/可复现

- 同 seed 同动作序列逐位一致；自对弈/评测 seed 分离。
- checkpoint 保存模型配置、数据版本、引擎 build info、normalization 统计。
- 报告 JSON 包含 engine/data version、协议（games/seeds/seat/opponent）、合法率、耗时。

## 7. 不做什么

- 不做其它搜索/行为克隆路线；训练只走本文件的 MCTS + 自对弈 + PPO。
- 不把 TavernBench 分数当 RL 回报；TavernBench 只做静态决策/值校准。
- 不做 oracle 隐藏信息搜索（PIMC 只用公开观测）。
