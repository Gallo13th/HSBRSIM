# 训练配方：三个想法的文献调研与落地设计（PPAI GPT-6.1 Sol）

> 作者：`ppai/gpt-6.1-sol` 子代理（只读代码/文档 + 文献核查）。本文件是**讨论稿**，供决定下一阶段
> 训练配方时参考；实现未开始。

## 0. 结论与优先级

**P0 先稳定 stage-3 配方** > **P1 镜像库保真 + 对手池** ≈ **P1 低权重 JEPA next-obs 消融** > **P2 宏动作**；
**goal-conditioned planning 暂不做**（除非能用引擎重置产生反事实轨迹）。镜像库与 JEPA 可并行；
宏动作需在稳定基线之后单独做。

依据（现有实测）：stage-1 KL-anchored 30M 把 C0 mean rank 4.70 → 3.52；stage-2（流水线+bf16）从 3.52
先降到 3.00（10M）后发散到 4.50（25M），entropy 0.370→0.581、decisions/局 165→244、
approx_kl 0.002–0.024、pre_ratio 0.9995→0.9835。直接缓解发散的是**全段 anchor、降 lr/target KL、
lag=0/早停回滚**，不是本文件的三个想法。

## 1. JEPA 风格子任务增强（建议：有条件做，低权重消融）

**文献**（子代理已核对的 arXiv 链接）
- I-JEPA (Assran et al., 2023) https://arxiv.org/abs/2301.08243 —— context→target latent 预测，非像素重建
- V-JEPA (Bardes et al., 2024) https://arxiv.org/abs/2404.08471 —— 视频特征预测
- SPR (Schwarzer et al., ICLR 2021) https://arxiv.org/abs/2007.05929 —— EMA target encoder + latent dynamics，多步预测
- BYOL (Grill et al., NeurIPS 2020) https://arxiv.org/abs/2006.07733 —— online/target EMA + stop-grad
- DreamerV3 (Hafner et al., 2023) https://arxiv.org/abs/2301.04104、TD-MPC2 (Hansen et al., ICLR 2024) https://arxiv.org/abs/2310.16828 —— latent world model + imagined planning（主要在连续控制，**不能声称直接适配**本游戏）
- Decision Transformer (Chen et al., NeurIPS 2021) https://arxiv.org/abs/2106.01345 —— return-conditioned 序列建模，**不能替代 PPO 的证据**

**适配设计**：entity shared trunk 输出 `z`（128–256 维），独立 predictor 输入 `(z_t, action embedding)`
预测 **EMA target** `z_{t+1}`（target stop-grad，BYOL/SPR 套路）；另加 delta head 按
global/board/hand/shop/opponent 分块预测观测变化（Huber/MSE，只对有效字段）。
`L = L_PPO + λ·L_JEPA`，λ 从 0.01 warmup/ramp 到 0.05；共享 trunk 默认回流 policy 梯度，独立 heads；
若 policy 的 KL/entropy 异常升高则 detach trunk 或冻结前 N 轮。

**前置**：现有 records **没有 next_obs** —— 必须按 `(game_id, seat, turn, step)` 配对下一观测、跨 done
不配；采集侧要保存 next obs（Rust collector 顺手可做）。

**风险**：辅助目标压过稀疏 rank 奖励；战斗随机性导致"预测不可识别"；额外显存/IO。

**验收**：latent cosine / linear probe / Δ MAE；C0 mean rank、top4、win（≥512 局 + 未见面板）；
approx_kl / clip / entropy / decisions 每局 / forced 率不得恶化。

**goal-conditioned planning（暂不做）**：只有「可重置引擎 + 反事实轨迹」才谈得上 world model；
离线 goal→动作 BC 不能称为 world model。若做：goal = 胜率/阵容 embedding，采集真轨迹做 BC/对比学习，
不直接用想象轨迹更新 PPO。

## 2. 高强度镜像对手库（建议：先修保真，再做强度消融）

**代码现状**（子代理核查）：`hsbg/az/library.py` + `scripts/build_bot_library.py` 已有 capture/sample/inject，
但 `BoardEntry` 只有 turn/seat/hero/tier/health/board/hand_count/placement，**卡 id 实测仅 2/6 保真**，
手牌内容/酒馆/任务/饰品/技能计数缺失，**尚未接 collect**。

**前置（必须）**：引擎侧 `state_json` + `set_player_state`/`set_minion_state` 完整 round-trip，
逐字段验证；否则只能做"强度分布消融"，不能宣称严格复现历史局面。

**数据**：保留现有 records 字段，追加 `checkpoint_id/source/opponent_id/state_hash/strength`、
完整注入状态、legal-mask hash。

**对手策略**：首选 **BC 模型**（state→masked logits）；历史轨迹动作**仅在 turn/state_hash/合法 mask
严格匹配时回放**，否则 nearest-state 只能作候选并做合法性校验，失败回退 bot/EndTurn。
历史对手的行为**不是**可反事实适应的策略，其 old_logprob **不能**当作 learner 的 on-policy 数据。

**防塌缩**：train/exam 双来源隔离；按 turn×strength 分层 reservoir/去重；建议 30% 当前 bot +
50% 最新 checkpoint + 20% 旧/难库，周期重校准，保留 10–20% bot；冠军池取上一 stage，避免自举。

**评估**：强度（同 C0 seed ≥512 / 独立未见面板 mean rank/top4/win、对手交叉矩阵）与**速度分开报**
（wall clock、dec/s、games/s、engine step vs forward、IO、CPU/GPU、decisions/局）。只有"注入回合牌面"
才可能真正跳过 7 个 bot 的招募推进；BC 仍需前向，回放若只注入状态可能快但任务分布/随机性不同。
**不要承诺吞吐大幅提升**（当前瓶颈是前向固定 ~5 ms）。

## 3. 动作 motif / 宏动作（建议：P2，后置）

**文献**：Options/SMDP（Sutton, Precup, Singh, 1999）https://doi.org/10.1016/S0004-3702(99)00052-1。

**定义**：先统计轨迹的频繁 n-gram + 手工审核，按回合/状态条件成模板；每个 macro 要有
前置条件、primitive 列表、逐步 mask/资源/回合合法性、终止/abort，失败立即回退 primitive。
初试 ≤8–16 个高支持短 macro（如 买 A→打出 A→卖 A，必须绑定同一张牌/eid，不能只看卡名），
固定 executor，禁止"同时扩词表 + PPO"。

**数学**（宏必须按 SMDP 处理，不能当 γ=1 的单步）：
`R_i = Σ_{j=0}^{k_i-1} γ^j r_{t+j}`，`Γ_i = γ^{k_i}`；
`δ_i = R_i + γ^{k_i}(1−done)V(s_{i+1}) − V(s_i)`；
`A_i = δ_i + (γλ)^{k_i}(1−done)A_{i+1}`（或明确在 option 层定义 λ，不能混用）；
`old_logprob` 是高层 macro 概率；若宏由 primitive policy 采样，需要联合 logprob。

**记录**：`macro_id, k, primitive_actions, abort_reason`。

**验收**：合法率 ≥99.5%、abort/fallback <1–2%、decisions/局 ↓≥10% 而 mean rank/top4/win 不降（CI）、
GAE 方差/entropy/KL/回合长度不恶化。

**注意**：宏可能缓解"回合变长"，但会改变 MDP 与信用分配，且新动作分布非平稳 —— 不能直接修
stage-2 的漂移，必须在稳定基线之后再做。

## 4. 与 stage-2 发散的关系

- 真正直接缓解发散：**全段 KL anchor**（β=0.1 前 20%，之后 ≥0.02）、lr 2e-6、target KL 0.02、
  每 2.5M 一次 512 局评测 + 连续两点差 >0.2 早停回滚、以及可选 lag=0。
- 镜像库：让对手/advantage 不再固定为 bot 的零均值，可能**间接**减少漂移，但更强对手也会增方差。
- JEPA：主要改善表征/样本效率，**不能当作 entropy 保险**，需低权重。
- 宏动作：能减少决策数与循环，但 action head 扩张本身可能增 entropy。

## 5. 建议的实验顺序

1. **stage-3 稳定配方**（1–2 天）：从 `runs/champion_c0_3004.pt` 续训，anchor 全段 + lr 2e-6 +
   评测早停；验收 = 30M 内 C0 ≤3.0 且不复发散（entropy ≤0.45、decisions/局 ≤200）。
2. **镜像库保真**（并行，2–3 天）：`set_player_state` round-trip 测试 → BC 对手 → 30/50/20 混合池。
3. **JEPA next-obs 消融**（并行，2–3 天）：λ=0.01 vs 0.05 vs 0；先只做 next-latent，不做 delta head。
4. **宏动作**（稳定后，1 周）：8–16 个模板 + SMDP GAE，先固定 executor 只训高层。
5. goal-conditioned planning：暂不立项。
