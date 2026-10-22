# 架构（ARCHITECTURE）

## 1. 分层

```
┌──────────────────────────────────────────────────────────────────┐
│ 训练/评测入口  scripts/  hsbg/train  hsbg/eval                    │
│   - BC 预训练 → PPO 微调 → 名次评测 → checkpoint                  │
└───────────────▲──────────────────────────────────────────────────┘
                │ Observation / CandidateAction / Reward
┌───────────────┴──────────────────────────────────────────────────┐
│ hsbg.env —— 强化学习环境层                                        │
│   spec.py        契约（观测/动作/奖励/配置，零依赖）               │
│   driver.py      引擎驱动：合法动作枚举 + 应用 + PendingChoice     │
│   observation.py 引擎状态 → 实体 token 观测                        │
│   game_env.py    单智能体 8 人对局循环（step/reset/奖励/名次）      │
│   vec_env.py     多进程向量化（训练吞吐）                          │
└───────────────▲──────────────────────────────────────────────────┘
                │ 引擎公开 API（Game / Hero / Minion / CardDB）
┌───────────────┴──────────────────────────────────────────────────┐
│ hsrl2 —— 战局模拟引擎（vendored，机制精度权威）                    │
│   game.py   回合流程 / 配对 / 战斗 / 淘汰 / 任务 / 饰品 / 异变      │
│   combat.py 游标轮转攻击循环 / 死亡顺序 / 同时伤害                  │
│   scripts/  1200+ 卡牌效果脚本（REGISTRY）                         │
│   data/     CardDefs 生成数据（S14 36.2.2 基线）                   │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ hsbg.agents —— 脚本对手 / 教师（随机、启发式、搜索）               │
│ hsbg.policy —— 实体 Transformer（候选打分 + 名次分布价值）         │
│ hsbg.bridge —— 真实对局桥（Power.log / AgenticAssistant 数据）     │
└──────────────────────────────────────────────────────────────────┘
```

## 2. 一次决策的数据流

```
env.step(candidate)
   │ driver.apply_action(engine)            # 校验+执行
   │ 重复: 对手 PendingChoice 自动结算
   ▼
observation.build(game, hero, candidates)   # 实体 token + 全局标量
   ▼
encoder: Observation → tensors
   │  实体序列 [B, N, F] + mask
   │  候选动作 [B, C] → 指向实体下标
   ▼
policy: EntityTransformer
   │  ┌─ 实体编码（card emb + 数值 + zone/type + 位置）
   │  └─ Transformer × L
   │  logits[B,C] = score(global, src_entity, tgt_entity, kind, pos)
   │  value[B]    = E[rank]（名次分布头）
   ▼
masked argmax / sample → candidate index → env.step
```

## 3. 回合边界

```
招募阶段（可 N 个决策步）
  buy / sell / play / reroll / upgrade / freeze / hero_power / activate / choose…
  END_TURN
        │
        ▼
对手依次完成招募（自动，脚本策略）
        │
        ▼
game.end_recruit_phase()
  1. EoT 效果（饰品→任务奖励→随从，Drakkari 翻倍）
  2. 丢弃 Spellcraft
  3. 战前棋盘快照
  4. 配对 + 逐对 run_combat（同步；战斗内选择自动结算）
  5. 奇数人幽灵战
  6. 淘汰结算（记录名次）
  7. 终局判定 / 下一回合
        │
        ▼
确定性的新观测（或 terminated）
```

## 4. 训练范式

1. **BC 预训练**：用启发式教师（`hsbg.agents.heuristic`）跑对局，采样
   `(Observation, 教师动作)`，交叉熵训练策略头（+ 价值回归）。
2. **PPO 微调**：8 个并行环境（7 个脚本对手 + 1 个策略控制位），
   回合级奖励 + 终局名次奖励，GAE(λ)，clip 目标，KL 早停。
3. **自我对弈（后续）**：对手池 = 历史 checkpoint + 启发式，按胜率采样。
4. **评测**：固定种子集上平均名次 / 前四率 / 冠军率 / 每回合战力曲线，
   对比 random / heuristic / BC / PPO。

## 5. 关键不变量

- 引擎规则不在环境层重写；环境只做"枚举/应用/观测/奖励"。
- 候选动作 = 合法动作，非法动作绝不进入候选。
- 同 seed ⇒ 同轨迹（训练可复现）。
- 观测不含隐藏信息（对手手牌/金币/酒馆）。
- 战斗内的 PendingChoice 由环境自动结算（不可中断）；招募期选择可暴露。
- 名次由环境按淘汰顺序记录，引擎不提供最终排名对象。
