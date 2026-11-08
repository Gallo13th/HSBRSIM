# AutoTavern 参考研究（TavernGym / TavernBench / TavernAgent 对标）

> **上游**：[MCG-NJU/AutoTavern](https://github.com/MCG-NJU/AutoTavern)（MIT）；论文
> [arXiv:2610.33845](https://arxiv.org/abs/2610.33845)，Ma & Wang, 2026。
> **取证（2026-11-04）**：`git clone` 失败（`fetch-pack: unexpected disconnect`），改用
> `curl codeload.github.com/MCG-NJU/AutoTavern/tar.gz/refs/heads/main` 解包到 `/tmp/AutoTavern`
> （11.8 MB）。下文 `AT:<file>:<line>` 指该只读快照，`<file>:<line>` 指本仓库。
> 快照版本 = **v1.0.0**（`AT:Cargo.toml:6`、`AT:pyproject.toml:7`），与 `rust/FORK.md:8` 的 fork
> 基点 `fb61201` 一致：`diff -rq` 我们 `src` 与上游仅 15 处差异，全部是 fork 改动（新增
> `search.rs`/`snapshot.rs`/`turn_search.rs` + 数据换版）。
> **上游不发布 TavernAgent 权重与训练代码**（`AT:README.md:44-45`；全仓 grep
> `ppo|self-play|actor-learner` 零命中）⇒ §5/§6 只能引论文，不能引代码。

## 1. 仓库结构（AT v1.0.0）

```text
crates/taverngym/          # 纯 Rust 引擎：22 个顶层模块 + content/ 58 个卡牌脚本模块（+mod.rs）
  src/{cards,config,state,engine,recruit,combat,flow,event,script,actions,obs,
       env,batch,bot,experimental,debug,invariants,rng,types,guard,workers}.rs
  src/content/*.rs         # 一卡一 Script（hooks 表），content::all_scripts 汇总
  data/cards.json          # 编译期 include_str! 嵌入，CardDb 单例
  tests/                   # 34 个集成测试文件 + common/（mechanics/persistence/games/shown_*）
crates/taverngym-py/       # PyO3 薄层 = taverngym._core
python/taverngym/{__init__,env,batch}.py   # BattlegroundsEnv / BatchEnv 包装
tavernbench/               # data/{full 960,eval 368}、results/{eval 12 系统,tools 5 系统}
docs/                      # ARCHITECTURE(283) CONTENT(1040) TAVERNGYM(123) TAVERNBENCH(72) TIMEWARP(118)
tools/gen_carddb.py + overlays/36.6.3.json # cards.json 唯一生成路径
tests/                     # 6 个 pytest（batch/env/rules/smoke/tavernbench/debug）
```

内容规模：**978 个游戏对象 / patch 36.6.3**（`AT:README.md:37`），`cards.json` meta
`{"client_version":"36.6.3.253932","server_patch":"36.6.3","count":3983}`。

## 2. 数据 schema：`cards.json`（与我们逐字段同构）

```json
{"meta": {"client_version","server_patch","source","count","overlay"},
 "cards": [{"id","dbf","kind","name","name_zh","tier","atk","hp","armor","cost",
            "races","assoc","keywords","golden","normal","pools","text","text_zh",
            "pool_tag","reachable","window"}]}
```

- `golden`/`normal` 互链；`pool_tag`/`reachable` 决定是否进池；`window:[from,to]` 是 Dark Gift
  可用回合窗（`AT:data/cards.json:3071`）；`kind ∈ minion|tavern_spell|trinket|dark_gift|hero|…`。
- 生成链：内容包 → `tools/gen_carddb.py` → overlay → `cards.json`，**禁止手改**
  （`AT:docs/ARCHITECTURE.md:32-38`）。
- 表身份 `CardDb::fingerprint`；`Game::check_loaded` 拒绝异表状态
  （`AT:docs/ARCHITECTURE.md:182-183`）——我们必须保留，换数据后旧 `state_json` 必须失效。
- 我们的对应物 `rust/crates/hsbg-engine/data/cards.json`：`client_version=37.0.0.255790`、
  `count=3983`（`mapped_count=3695` + `compat_count=288`）、`at_baseline=36.6.3.253932`，
  由 `tools/p2_data/gen_carddb_37.py` 生成（`rust/FORK.md:25,47`）。

## 3. 动作契约：245 个离散动作 + 精确 mask

| 段 | 索引 | 说明 |
|---|---|---|
| EndTurn/Refresh/Freeze/Upgrade | 0–3 | 回合级按钮 |
| HeroPower(slot) | 4–5 | `N_POWERS=2` |
| DarkGift / Cancel | 6 / 7 | Cancel 只在选取目标时可退 |
| Buy(shop) / Sell / Activate(board) | 8–15 / 16–22 / 23–29 | 8 槽 / 7 位 / 7 位 |
| Choose(option) | 30–45 | 16 项：Discover/目标/英雄/饰品… |
| Play(hand,pos) | 46–125 | 10×8；法术只用 pos 0 |
| Magnetize(hand,board) / Move(from,to) | 126–195 / 196–244 | 10×7 / 7×7 |

- 常量链 `N_ACTIONS = A_MOVE + N_BOARD*N_BOARD = 245`（`AT:actions.rs:33-50`，断言在
  `AT:actions.rs:401`）。
- **mask 精确性**：`legal_mask` 允许的动作 `apply` 必然接受（`AT:docs/ARCHITECTURE.md:192-193`，
  测试 `every_masked_legal_action_applies`）。
- 实验模式额外动作走 `Game::extra_action`（`AT:experimental.rs:116`），**在固定 245 空间之外**，
  不改变 `N_ACTIONS`；与我们 245..273 扩展段取向一致但实现路径不同（见 §8）。
- 我们的映射：`hsbg/env/action_space_std.py:138-142`（`A_MOVE=196`/`N_ACTIONS=245`/
  `N_TOTAL_ACTIONS=274`）、`docs/ACTION_OBS.md:5-25`。

## 4. 观测契约：3227 floats + 124 cards

`OBS_FLOATS = GLOBAL_F + 3*2 + 9 + 7*MINION_F + 10*ITEM_F + 8*ITEM_F + 16*ITEM_F + 7*9 +
7*7*MINION_F`（`AT:obs.rs:32-42`）；`MINION_F = 8 + 12 关键词 + 11 种族 = 31`（`AT:obs.rs:14`、
`AT:types.rs:28`）；`ITEM_F = 9 + 31 = 40`（`AT:obs.rs:18`）；`GLOBAL_F = 42 + 11 = 53`
（`AT:obs.rs:19`）⇒ 3227。

| 块 | 宽度 | 内容 |
|---|---:|---|
| global | 53 | 42 标量（回合/血量/金币/等级/阶段/池计数…）+ 11 种族位 |
| quests / pending_kinds | 6 / 9 | 3 任务 ×(present, progress/goal)；待选类型 one-hot |
| board_minions | 7×31 | 己方战团 |
| hand_items / shop_items | 10×40 / 8×40 | 手牌（无价格）/ 酒馆（含价格、冻结） |
| choice_items | 16×40 | 待选项 |
| opponents | 7×9 | 公开摘要（tier/血量/护甲…） |
| opponent_boards | 7×7×31 | **上次交手见到的**战团 |

`OBS_CARDS = 1+2+2+9+5+7+10+8+16+8+7+49 = 124`（`AT:obs.rs:44-59`）；卡牌下标 = `CardId+1`，
0 = 空槽。**信息边界**：只编码客户端可见信息，没打过的对手战团不给（`Game::known_board`，
`AT:docs/ARCHITECTURE.md:199`）；`taverngym.layout()` 给出全部块宽，模型不必硬编码偏移。

> **版本分层**：以上是 v1 布局。公开竞技场跑 TavernGym **1.1.0**，观测 v2 =
> `features[4017] + cards[447] + mask[245]`，且 v1 是 v2 的**前缀**（`docs/ARENA.md:49-57`）；
> 上游 GitHub 发布物仍只有 1.0.0。

## 5. 模型结构（TavernAgent，仅论文）

- **实体 token**：己方随从 7 / 手牌 10 / 酒馆 8 / 待选 / 对手 7，**至多 56 entity + 1 global**。
- **卡牌表示** = identity embedding + 静态特征投影 + **卡牌规则文本的 embedding 投影**（让稀有卡
  有合理初值）；磁力/Dark Gift 附件加到宿主 token；饰品/持续效果/计数器池化进 global；对手 token
  = 公开信息 + 上次见到的战团 + 那场战斗结果。
- 输入做**对称对数**压缩；三个头：**pointer head（245 masked logits）+ value head + placement 辅助头**。
- 容量 d=384 / 8 层 / 8 头 / **18M**；同配方 3.5M / 8M / 18M 平均名次 **3.84 / 3.77 / 3.67**
  （Table 8）。我们的差异见 §8 第 11、18 行。

## 6. 训练算法：纯 PPO + 校准对手库（无 MCTS、无自对弈、无 BC）

| 配置（Table 7，TA-23 末 stage） | 值 |
|---|---|
| games/member × steps、iterations/stage | 512 × 256、300 |
| decisions/iter、**一个 stage** | ≈1.05×10⁶、**≈310M ≈ 57 万局** |
| minibatch / epochs、lr | 8,192 / 1、6e-6→5e-6 |
| clip / target KL、γ / λ / grad-clip | 0.2 / 0.05、1.0 / 0.995 / 1.0 |
| entropy / value / aux | 0.002 / 0.5 / 0.1 |
| **KL anchor 到 stage 起点** | β=0.1，**只前 100 iter** |

- **对手（论文称最大单项收益）**：不是 self-play，而是 7 个 **library seat**——每回合从「按顶尖
  人类统计 + 录制对局」构造的牌面库（board+hand+hidden counters）抽一条，并**逐回合按天梯实际
  遇到的对手重校准**；训练库与 **exam 库是 twin，exam 永不训练**。消融（Table 3，同起点同预算
  150 iter）吃鸡率 **20.9%→27.2%**（主 exam）/ **10.3%→13.5%**（更难 exam）。
- **课程**：简化规则 → 全内容 → 玩家视角（只用公开信息）→ 吃鸡目标 → library 对手。
- **交付**：23 版 / 20 天、14 次重校准；天梯 rating 6,000→≈15,000，最近 20 局平均名次 **1.60**、
  80% 吃鸡，优于服务端前十（**2.34**、59%）。门 G4：候选必须在**未用于挑选的 seed** 上复查。
- **算力**：8×H200/128C；交付主线 **1,900 GPU-h**，试错 16,700，评测 1,300。
- **搜索**：训练与在线都**没有树搜索**；推理只做「一次前向 + 每候选最多 **256 次战斗模拟**」的
  一步 lookahead。唯一一次搜索尝试是**假增益**：拷贝局面带 RNG 状态 ⇒ 搜索「看到未来」，表面
  +23.6 分，**重播种后 −0.65 ± 1.14**（论文 §8(i)）。
- 证据：`docs/AUTOTAVERN_PAPER_TRAINING.md:22-38,40-122`（原文核对版）；人类数据只作对手库、
  **无动作级 BC**：`docs/AUTOTAVERN_HUMAN_DATA.md:6-21`。

## 7. benchmark：TavernBench（我本地复算，2026-11-04）

- 规模：**960 任务 / 40 场景 / 8 类别**；论文固定集 **368 = 37×8 + D4(16)+N1(29)+N2(27)**；状态
  720（full）/ 288（eval）；答案 12 个 eval 系统 + 5 个 tool-use 系统（`AT:docs/TAVERNBENCH.md:5-14`；
  实测 `wc -l` = 960/960/368/368、`zcat|wc -l` = 288）。
- 标签由 TavernGym 模拟生成：战斗 4,096 局、站位每方案 2,048 局、短期决策每选项 1,024 局、策略题
  每条计划 128 次 rollout（`AT:docs/TAVERNBENCH.md:25-28`）。
**复现**（纯标准库，~1s）：`cd /tmp/AutoTavern/tavernbench && python3 -m tavernbench.report
--set data/eval --runs results/eval --systems …`，输出：

```text
system                       play  rule   1v1 comba posit order targe selec strat econo
chance                       0.22  0.05   0.33 0.13  0.20  0.21  0.25  0.30  0.25  0.12
tavernagent                  0.91  1.00   1.00 1.00  0.97  1.00  0.97  0.64  0.75  1.00
gpt-6-astra                  0.63  0.95   1.00 0.75  0.55  0.72  0.55  0.50  0.54  0.75
claude-sonnet-5.5            0.53  0.85   1.00 0.58  0.45  0.68  0.53  0.39  0.29  0.50
claude-opus-5.5              0.52  0.93   1.00 0.67  0.33  0.60  0.53  0.41  0.38  0.50
gpt-6.1-sol                  0.46  0.56   1.00 0.50  0.42  0.47  0.28  0.55  0.43  0.38
gemini-3.8-flash             0.44  0.90   1.00 0.52  0.33  0.33  0.47  0.41  0.43  0.62
glm-5.3                      0.40  0.65   0.62 0.54  0.20  0.40  0.38  0.41  0.34  0.38
jev                          0.37  0.35   0.75 0.56  0.25  0.20  0.45  0.40  0.17  0.12
kimi-k2.6                    0.28  0.56   0.62 0.31  0.07  0.23  0.38  0.36  0.27  0.25
deepseek-v4.1-flash          0.26  0.29   0.75 0.29  0.17  0.15  0.33  0.25  0.19  0.38
grok-4.7                     0.22  0.79   1.00 0.29  0.00  0.05  0.20  0.38  0.37  0.12
intern-s2-preview            0.32  0.54   0.50 0.31  0.12  0.33  0.40  0.44  0.34  0.12
```

与 vendored golden（`benchmarks/tavernbench/expected/eval_report.json`，
`python3 scripts/run_tavernbench.py --check` 26/26）**逐项一致**（`docs/TAVERNBENCH.md:142-160`）。

- 结论口径：造系统的 agent > 当玩家的 LLM；TavernAgent **0.03 s/题**，LLM 1.4–26 s。**不能**用
  TavernBench 分数替代我们的 self-play 名次（边界见 `docs/TAVERNBENCH.md:290-318`）。

## 8. 与我们逐项对照

| # | 维度 | AutoTavern | HSBRSIM 现状（证据） | 判定 |
|---:|---|---|---|---|
| 1 | 引擎基座 | TavernGym v1.0.0（`AT:Cargo.toml:6`） | fork → `hsbg_engine`（`rust/FORK.md:8-21`） | **一致** |
| 2 | 数据 | 36.6.3.253932 / 3983 卡 | **37.0.0.255790** / 3983=3695+288（`rust/FORK.md:25,47`） | 我们领先一 patch |
| 3 | 动作 0..244 | 245（`AT:actions.rs:3-50`） | 245 逐位一致（`hsbg/env/action_space_std.py:138-142`） | **一致** |
| 4 | 动作 245..273 | 无（额外动作走 `extra_action`，`AT:experimental.rs:116`） | 29 项扩展仅 Python 声明，引擎未实现（`docs/ACTION_OBS.md:17-24`） | 我们扩展 |
| 5 | 观测 | 3227+124（`AT:obs.rs:32-59`） | 同公式（`hsbg/env/obs_std.py:159-172`） | **一致** |
| 6 | 信息边界 | 只用客户端可见 + `known_board` | 同（`docs/ACTION_OBS.md:46`）；信念采样禁读隐藏态（`hsbg/az/belief.py:1-14`） | **一致** |
| 7 | 奖励 | 终局名次线性 1..−1 + 非法 −0.01（`AT:docs/ARCHITECTURE.md:201-202`） | 同 | **一致** |
| 8 | 确定性/存档 | xoshiro256**、`state_json` 精确、异表拒绝 | 同（`rust/FORK.md:43`） | **一致** |
| 9 | 环境 API | `BatchEnv`（controlled/self-play/逐局 save）+ 20 字段卡 schema | 同 | **一致** |
| 10 | 模型 | 56+1 token / 18M / pointer / 学习式文本嵌入 | 49 token（或 57 派生补位）/ 14.8M→17.98M / pointer / **字符 3-gram 哈希 64 维**（`hsbg/az/train/entity_model.py:1-16`） | 近似，缺文本编码 |
| 11 | 训练 | 纯 PPO，无搜索、无自对弈 | MCTS-guided PPO + 8 座自对弈（`hsbg/az/train/ppo.py:1-24`） | 我们扩展 |
| 12 | KL anchor | β=0.1，前 100/300 iter | **已实现** `anchor_coef`/`set_anchor()`/逐动作 KL（`hsbg/az/train/ppo.py:1161-1163,2798-2806`；`ppo_trainer.py:105,136`），主入口已接线（`scripts/train_entity_sync.py:3203,3939`） | 一致，默认 0 |
| 13 | 对手分布 | 7 个校准 library seat + exam twin + 逐回合强度曲线 | `hsbg/az/library.py`（冠军镜像库）、`train/library_pool.py`、`train/human_board_pool.py`（真实 10k MMR，board/hand/full 保真，p50/p75/p90 曲线）；入口 `--library-pool/--human-board-seats/--human-board-quantile-ramp` | 部分：缺真人统计校准态与 exam 纪律 |
| 14 | 每 stage 预算 | **310M decisions / 57 万局** | 最大累计 **40M**（`docs/TRAINING_CURVE_300M.md:7-12`）；单 stage 仍 ~1M 级 | 缺失 ~8×/stage |
| 15 | 评测规模 | 24,576 局/点（3 未见 seed × 8192） | `--eval-games` 默认 **512**（`scripts/train_entity_sync.py:2123`）；冻结 panel **96 局 / 5 席 / seed 520000**（`docs/TRAINING_CURVE_300M.md:3`） | 缺失 ~48–256× |
| 16 | 搜索 | 无 MCTS；一步 + 256 次战斗模拟；**拷贝必须重播种 RNG**（`AT:docs/ARCHITECTURE.md:174-179`） | PIMC/ISMCTS + PUCT + 信念采样全栈（`hsbg/az/search.py:1-3`）；推理期 rollout 叶值（`train/infer_search.py:1-12`） | 我们扩展 + 泄漏风险 |
| 17 | 卡牌文本 | 学习式 rule-text encoder | 字符 3-gram 哈希（`entity_model.py:5`） | 我们缺失 |
| 18 | TavernBench | 发布方（v1.0.0, 36.6.3） | 只读 vendored + golden 对拍 26/26（`benchmarks/tavernbench/MANIFEST.json`） | **一致** |
| 19 | 在线闭环 | 23 版/20 天、14 次重校准、天梯 top100 | arena 客户端可用；实测 10 局 practice mean 3.50、3 局计分中止（`docs/ARENA.md:72-74`） | 缺失（闭环节奏） |

## 9. 对下一阶段最有价值的三条可执行借鉴

### R1 对手库从「已实现」推到「校准 + exam 纪律」（性价比最高）
- **做什么**：① exam 侧固定一份**从未参与训练**的库（现有 `--eval-human-boards` 分文件机制，
  `scripts/train_entity_sync.py:3230-3233`），seed 也分 train/exam；② 每 stage 末按**训练中实际
  遇到的对手强度**重设 `--human-board-quantile-ramp` 分位曲线（不是固定 p75）；③ 用现有
  `--human-board-seats` 把 5 席扩到 7 席，跑「对齐 vs 未对齐」同预算 150 iter 消融。
- **为什么**：论文实测这是**最大单项收益**（20.9%→27.2%、10.3%→13.5%，Table 3）；我们的库是自指
  镜像（`docs/LIBRARY_SEATS.md` §2 限制 4：强度上限受自身策略限制）且无 exam 隔离。
- **验收**：同 checkpoint/预算下 exam 库吃鸡率与 `mean_rank` 的跨 seed 改善 ≥ 噪声（panel 现仅 96
  局，先扩到 3 seed × 1024 局再判定）。成本：低（脚本/参数已有）。

### R2 把「一个 stage」做成 30M decisions 的交付单元，KL anchor 从默认关改为默认开
- **做什么**：① 每 stage ≥30M decisions（我们吞吐下约 12h/4 卡，`docs/AUTOTAVERN_PAPER_TRAINING.md:170-171`）；
  ② stage 前 1/3 iteration 打开 `anchor_coef=0.1`（代码已就绪，只需改默认值并在
  `train_entity_sync.py:3939` 按 iteration 衰减到 0）；③ 超参就近对齐 λ=0.995、entropy=0.002、
  grad-clip=1.0、minibatch 8,192（梯度累积）、lr 6e-6。
- **为什么**：论文一个 stage 310M ≈ 我们全部历史（40M）的 8 倍；「越训越差」的直接嫌疑是 stage 太短
  + 无 anchor（anchor 是论文显式设计，我们在 `ppo.py` 里实现了却默认 β=0）。
- **验收**：固定 exam panel 上跨 stage `mean_rank` 不退化，并记录 `anchor_kl` 曲线。成本：中（GPU 时间）。

### R3 PIMC 的 RNG 重播种审计（防止搜索收益是「看到未来」）
- **做什么**：① 把 determinization 的 `game.copy()` 换成**重播种 RNG** 的拷贝（`Game.rng` 是 public，
  `AT:docs/ARCHITECTURE.md:174-179`）；② 同 seed 做「重播种 vs 不重播种」A/B：既比强度，也比
  「搜索前后预测的未来商店/Discover 一致率」；③ 结论写进 `docs/AZ_IMPERFECT_SEARCH_DESIGN.md`。
- **为什么**：上游明说 copy 携带随机状态、「rollout 会看到原局的未来商店与 Discover」；论文唯一一次
  搜索尝试正栽在这里（表观 +23.6 分，重播种后 **−0.65 ± 1.14**）。我们的 `belief.py` 就是
  `world = game.copy()` 后覆写隐藏量，`infer_search.py` 也用 `game.copy()` 跑 rollout。
- **验收**：A/B 同预算同 exam seed；若增益消失，搜索降级为「评测/重搜消融」，训练主环退回纯 PPO
  （与论文一致）。成本：低（接口 + 一组对照）。

## 10. 现有 docs 的过期 / 合并清单

| 文件 | 状态 | 理由与动作 |
|---|---|---|
| `docs/AUTOTAVERN_PAPER_TRAINING.md` | **§1–8 保留，§9–10 过期** | §9 表「KL anchor 未实现」「对手=7 个同一 bot」「PPO 只做过 1 局 smoke」已被 `ppo.py:1161`、`train/human_board_pool.py`、`MULTISTAGE_TRAINING.md` 推翻。动作：§9–10 收缩为「历史差距快照（2026-10-27）」，现状指向本文 §8 |
| `docs/AZ_AUTOTAVERN_MODEL_TRANSFER.md` | **部分过期** | §3 表三行 ❌（PPO/anchor/library）已落地；§4 的 14.8M vs tiny 对照是 2026-10-27 旧数。动作：保留「论文设计→迁移映射」，状态列指向本文 §8，数值只留最新一次 |
| `docs/AUTOTAVERN_HUMAN_DATA.md` | **保留** | 内容仍准确（人类数据只作对手库、无动作 BC），且已自声明「§9–10 已过时」 |
| `docs/AT_LAYOUT_CONTRACT.md` | **保留** | 245/3227/124、`N_CHOICE=16`、57 token 派生补位经本次实测复核全部正确；建议加一行指向本文 §4 的「v2 = 4017/447」 |
| `docs/TAVERNBENCH.md` | **保留（不要合并）** | 318 行完整集成指南 + 复现证据，独立主题；本文只摘要以免重复维护 |
| `docs/LIBRARY_SEATS.md` | **需更新后合并** | 仍写「尚未接进 collect」「卡 id 保真度不足」——前者已被 `--library-pool/--human-board-seats` 推翻，后者已被 `human_obs_full.inject_quasi_state`（fidelity=hand/full）缓解。动作：刷新状态后并入本文 R1 或 `docs/MIRROR_SNAPSHOT_DESIGN.md` |
| `docs/ARENA.md` | **保留，需交叉引用** | 「公开 TavernGym 1.1.0 / v2 4017+447」与「我们对齐 v1.0.0 / 3227+124」并存不矛盾，但必须显式写版本分层，否则会被读成过期 |
| `docs/ENGINE.md` / `rust/FORK.md` | **保留（真源）** | fork 声明与数据版本以它们为准，本文不重复维护 |
| `docs/*.remote.md`（7 个：`HUMAN_TRACE_CHECK`/`HUMAN_PLAY_3GAMES`/`HUMAN_ACTION_RECIPE`/`AUTOTAVERN_HUMAN_DATA`/`COMP_SCRIPTS`/`SMALL_FULLGAME_RL`/`ECONOMY_CEILING`） | **本地镜像残留** | 远端 `git status docs/` 干净、`ls docs/*.md` 112 个里无这些名字 ⇒ 只存在于本地镜像、不入库；清理本地副本即可（不在本任务写范围内执行） |

## 11. 证据索引与诚实边界

- 上游只读快照 `/tmp/AutoTavern`（v1.0.0，2026-11-04 由 codeload tar 解包）；复算命令见 §7，
  输出与 `benchmarks/tavernbench/expected/eval_report.json` 一致。
- 关键对照文件：`rust/FORK.md`、`hsbg/env/{action_space_std,obs_std}.py`、
  `hsbg/az/{search,belief,library}.py`、`hsbg/az/train/{ppo,ppo_trainer,entity_model,
  human_board_pool,library_pool}.py`、`scripts/train_entity_sync.py`、`docs/TRAINING_CURVE_300M.md`。
- 诚实边界：TavernAgent 权重/训练代码/item generators 均未发布，论文数字只能按论文引用；我们的
  `entity18m`「57 token」里 8 个是派生补位，**不是**上游 obs 有 56 个 entity 槽位
  （`docs/AT_LAYOUT_CONTRACT.md:53-65`）。
