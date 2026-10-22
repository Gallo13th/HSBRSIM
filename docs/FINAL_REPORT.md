# 交付报告（FINAL_REPORT）

> 日期：2026-10-18 ｜ 仓库：`C:\HSagent` ｜ 数据基线：官方 build **37.0.0.255130**

## 1. 目标与结论

按需求交付三层能力：

1. **战局模拟环境**：`hsrl2` 引擎（4,187 项回归测试）+ 官方 37.0.0 数据 +
   679 场真实 BG 战斗差分验证（DATA_GAP=0，确定性战斗匹配 76.9%，干净子集 100%）。
2. **强化学习环境对接**：`hsbg/env`（实体 token 观测、候选动作、奖励、名次追踪、
   确定性、多进程向量化），单局 ~0.3–0.5 s，4 进程 7 局/s。
3. **强化学习策略**：1.24M 参数实体 Transformer + BC/PPO 训练管线。
   BC（30,300 教师样本）验证准确率 **85.6%**，100 局平均名次 **4.34**
   （随机 7.80 / 启发式教师 4.24）。

用户强调的「与官方实现完全一致 + 可高并发搜集数据」已落到可度量、可回归的工程能力：
官方数据流水线、官方轨迹差分 harness、REA 逆向报告、版本同步一键流水线。

## 2. 关键交付物

| 类别 | 交付 | 验收 |
|------|------|------|
| 引擎 | `hsrl2/`（含 37.0.0 数据与 ABERRATION 支持） | `pytest hsrl2/tests -q` → 4,588 passed（项目 403，合计 4,991） |
| 数据 | `data/` = 官方 255130；`data/backup_249896/` 旧基线 | `data/bg_summary.json` patch=37.0.0.255130 |
| 环境 | `hsbg/env/`（spec/driver/observation/game_env/vec_env） | `pytest tests -q` → 268 passed；20 seeds 0 崩 |
| 教师/对手 | `hsbg/agents/`（随机 + 引擎感知贪心） | 100 局平均名次 4.24 |
| 策略 | `hsbg/policy/`（实体 Transformer，1.24M 参数） | BC 验证准确率 85.6% |
| 训练 | `hsbg/train/`（BC/PPO/buffer/vec_env/评测） | 60k–300k 步 PPO 实验可复现 |
| 评测 | `hsbg/eval/` + `scripts/evaluate.py` | 固定种子 + bootstrap CI + 名次分布 |
| 真实对局桥 | `hsbg/bridge/`（Power.log/HDT 轨迹/rizling） | 679 条官方战斗轨迹抽取 |
| 一致性工具 | `tools/rea_*.py`、`tools/diff_*.py`、`tools/version_sync.py` | 全部可运行、幂等 |
| 文档 | `docs/` 13 篇 + README + AGENTS | 训练/环境/一致性/版本/逆向全覆盖 |

## 3. 官方一致性证据

### 3.1 数据

- 官方 build 255130（本机客户端 `.product.db` = `37.0.0.255130.254477`）。
- 官方 CardDefs：`CardDefs.Bacon.xml` 5,787 BG 实体（sha256 锁定，见
  `reversed/hsdata_255130/source.json`）。
- 迁移：BG 实体 +175、新卡 +179 / 删 4、384 处数值变化、新种族 ABERRATION(126)、
  新 tag 16 个。
- 迁移后引擎回归 4,175 → **4,187 passed**；补卡后引擎 **4,588** + 项目 **403** = **5,104 passed**。

### 3.2 行为（官方轨迹差分）

- 语料：HDT BobsBuddy 会话日志（27 会话）→ **679 条 `official_combat_trace.v1`**
  （双方战团快照 + 官方实际结果 + 10000 次模拟概率）。
- 差分（679 场 × 64 seeds）：
  - DATA_GAP = **0%**（所有卡 id 均可解析）
  - MATCH **72.3%**；确定性战斗 **86.3%**（tolerant 94.4%）
  - 干净子集（无已知缺口）**100%**（13/13）
  - 官方实际结果 == 引擎众数 **73.7%**
- 分歧归因：`missing_script` 246（37.x 新卡缺效果脚本）、`CONTEXT_GAP` 9
  （日志隐藏上下文：BG 秘密/外部亡语/Teron 目标状态/动态属性）、
  `unmodeled_dynamic_state` 4、`behavior_mismatch` **0**（修复 Ozumat 后）。

### 3.3 已修复的引擎问题

| 编号 | 问题 | 影响 | 状态 |
|------|------|------|------|
| F-01 | 战斗快照 `deepcopy` 实体引用（KILLER） | 整局 7.2×、ERP 11×、内存 98×；战斗污染 | ✅ 修复 + 回归测试 |
| F-02 | Ozumat SoC `while not board_full()` 召唤 6-7 只 Tentacle | 官方 loss 被判 win | ✅ 修复 + 官方轨迹测试 |
| F-03 | 动态 `SCRIPT_DATA_NUM_1..5` 通道（官方 enumID 2/3/2889/2919/2920） | Eternal Knight 等动态属性无法建模 | ✅ 独立命名空间 + 注入 API（Eternal Knight 验证；其余台账） |
| F-04 | 伤害上限外部注入（官方 tag 2089/3403） | 本地 turn 表只是近似 | ✅ `Game.set_damage_cap` / 构造参数；默认行为不变 |
| F-05 | 剧毒/烈毒、顺劈的「攻击者存活」门槛 | 与官方文本 "Destroy any minion damaged by this minion"/同时伤害语义不符 | ✅ 去门槛 + 8 条规则级测试 |

**引擎回归**：`pytest hsrl2/tests` → **4,313 passed / 2 skipped**；
项目测试 `pytest tests` → **366+ passed**（含 RL 接口 57 项）。

### 3.5 RL 接口层（新增，用户当前核心）

`hsbg/rl/`（~3.2k 行）：

- **协议**：`Policy` / `EnvLike` / `Transition` / `EpisodeRecord`，唯一单局驱动
  `run_episode()`；策略支持 `random/heuristic/teacher/checkpoint:<path>/callable`。
- **Gymnasium 包装**：`GymBattlegroundsEnv`（Dict 观测 11 字段 ≡ 策略编码器输出、
  `Discrete(64)` + `action_masks()`），`TimeLimit` / `RecordEpisode` /
  `AutoResetWrapper`；gymnasium 官方 `check_env` **通过**（可选依赖）。
- **高并发采集器**：多进程 + JSONL（header/step/episode/error 四种行）+ 断点续采；
  实测 **8 workers = 12.7 局/s（1,515 步/s）**，4 workers = 8.2 局/s；同 seed
  不同 worker 数动作序列逐条一致。
- **评测器**：多进程 + 复用 `hsbg.eval.metrics`（bootstrap CI/名次分布）+ 多策略对照。
- 观测契约升级 **v2**：`Observation.extra`（冻结/技能次数/任务进度/暗黑赠礼/
  对手身份/淘汰顺序/最近战斗等）——来源与 `info["obs_extra"]` 同源、纯数据可 pickle。

### 3.4 逆向结论（REA + ilspycmd + BobsBuddy）

- REA（rea-agents 6.7.0，便携 Node 24）已跑通：BobsBuddy `Simulator` 完整成员图
  （99 方法/25 字段/2,617 call edges）；Assembly-CSharp 成员级受 64MiB 预算限制，
  artifact 级完整（类型级沿用既有清单）。
- 官方客户端**无战斗模拟器**（`Simulate*` 仅 5–6 个且与战斗无关；战斗由服务器
  `PowerTaskList` 权威下发）→ 离线跑官方实现不可行；差分只能用官方可观测轨迹。
- BobsBuddy 与引擎逐条对照（`reversed/rea/bobsbuddy_vs_hsrl2.md`）：6 个 P0
  差异（复生属性、猛毒时机、顺劈同组、伤害上限来源、死亡批处理、SoC 顺序），
  其中「伤害上限=服务端 tag 2089」与「顺劈同组/剧毒语义」有官方文本支持，
  列入后续修复排期（需官方 Power.log 佐证高风险项）。
- rizling 最新包 0.6.1 仍停在 36.6.3，无模拟器/模型/自动点击；仅作版本参考。

## 4. 环境与数据吞吐

| 指标 | 数值 |
|------|------|
| 单局 8 人（启发式） | 0.24–0.69 s（典型 ~0.45 s），~100 步 |
| 招募阶段单动作 | 0.76 ms（p50） |
| `end_recruit_phase`（含战斗） | p50 ~10 ms |
| 单进程吞吐 | 2–3 局/s（采集 1.6 局/s 含记录） |
| 4 进程 BCE 采集 | **7.4 局/s** |
| 4 进程环境 VecEnv | 训练 194 steps/s（PPO，8 人局） |
| 8 进程 RL 采集器 | **12.7 局/s（1,515 步/s）**；JSONL 落盘 |

## 5. 策略结果（100 局固定种子，seed=100..199）

| 策略 | 平均名次 [95% CI] | 冠军率 | 前四率 |
|------|-------------------|--------|--------|
| random | 7.85 [7.76, 7.93] | 0% | 0% |
| heuristic（教师） | 4.30 [3.89, 4.70] | 12% | 54% |
| BC | **4.06** [3.69, 4.47] | 9% | 62% |
| PPO（多组实验） | 4.4–6.6（不稳定，未超过 BC） | — | — |

结论：BC 管线有效（相对随机提升 3.46 名），达到教师水平；PPO 在稀疏终局奖励 +
8 人局高方差 + 12–30 万步预算下未稳定超过 BC——这是后续工作（课程学习/自对弈/
BC 辅助损失/更长训练），不是管线不可用。

## 5.1 评测报告

完整评测见 `docs/EVAL_REPORT.md`（含名次分布图 `docs/assets/eval_rank_distribution.png`）：
同 seed 100 局下 BC 平均名次 **4.06**、前四率 62%，优于启发式教师（4.30）。

## 6. 已知缺口与后续优先级

1. **37.x 新卡效果脚本**（37 张池内随从 + 94 条非池条目）——当前差分分歧主因；
   已有专项工作线按差分频次补齐（BG27_004 / BG34_630 / BG34_921 / BG35_801 …）。
2. **PPO 超过 BC**：课程学习（2/4/8 人）、自对弈对手池、BC 辅助损失、1M+ 步。
3. **动态 `SCRIPT_DATA_NUM_1..5`** 建模（官方 tag 与引擎内部 1068/1069/1070 撞号）。
4. **真实 BG Power.log 采集**（已完成 3 局 / 26 场战斗）→ 事件级差分/战斗顺序验证，
   尤其高风险项：复生属性、死亡波次、SoC 顺序。
5. 伤害上限改为从 Power.log 服务端 tag（2089/3403）注入（零规则风险）。
6. 更大规模数据搜集与真实轨迹混训。

## 7. 复现命令

```powershell
cd C:\HSagent
python -m pytest hsrl2/tests -q                  # 引擎 4,588 passed
python -m pytest tests -q                        # 项目 268 passed
python scripts/demo_env.py --seed 42             # 单局演示
python scripts/bench_env.py --seeds 20           # 吞吐基准
python scripts/evaluate.py --baseline random     --episodes 100 --seed 100
python scripts/evaluate.py --checkpoint runs/bc/official_320/policy_bc.pt --episodes 100 --seed 100
python tools/diff_replay_combat.py --traces runs/official_traces --limit 10
python tools/version_sync.py --check
```

训练产物（未入库）：`runs/bc/official_320/policy_bc.pt`（BC 最优）、
`runs/ppo/*/policy_final.pt`（PPO 实验）。

## 8. 风险与边界

- 数据/规则会随官方补丁变化：用 `tools/version_sync.py` 跟踪；rizling 参考版本
  落后于客户端属正常。
- 引擎机制精度以「官方可观测轨迹 + 官方 CardDefs + 规则文档」为准；客户端逆向
  不能获得服务端裁决实现。
- 差分 59.9% 总匹配率不代表机制正确性：主因是缺脚本卡（246 条）；干净子集 100%。
- 本项目默认只做**离线模拟与训练**；未实现也不建议线上自动操作（ToS/封号风险）。

---

## 9. 2026-10-18 晚 · 环境/接口收口与最终指标（更新）

### 9.1 模拟环境精度

- **池内效果脚本覆盖 279/280 = 99.6%**（唯一剩余 `BG28_583 Geomagus`：双互触发无官方触发链上限，证据性 DEFERRED）。
- 新增引擎子系统：**F-06** 本回合元素计数、**F-07** Deity（隐藏目标/战斗 Aberration 死亡进度/awaken）、
  **F-08** Discard（`discard_card`/`card_discarded`/`on_discard` + Activate cost=0 数据缺陷修复）、
  **F-09** Sneed's New Shredder 亡语"从手牌召唤"应移出手牌（修复 8 人局无限重召崩溃）。
- **长尾压测**：2/4/8 人各 200 局 = **600 局 0 崩溃 / 0 incomplete**；Deity 专项 60/60、Discard 60/60、
  Activate cost=0 11/11；确定性 20/20 指纹一致（跨进程 digest 一致）。
- 工程细节见 `docs/ENGINE_NOTES.md` F-01…F-09 与 `docs/EXACTNESS_STATUS.md`。

### 9.2 官方一致性差分（679 场真实 BG 战斗，最终）

| 指标 | 数值 |
|------|------|
| strict MATCH | **400 / 679 = 72.3%** |
| 确定性战斗匹配率 | **84.55%**（tolerant 92.71%） |
| 干净子集（无阻断缺口） | **13/13 = 100%** |
| `behavior_mismatch` | **0** |
| `DATA_GAP` | **0** |
| ENGINE_DIVERGENCE | 180（全部 `missing_script`，均为历史非池卡） |

CI 门禁：`python scripts/audit_official_consistency.py`（硬门禁 DATA_GAP=0 / behavior_mismatch=0 /
干净子集 100% + 基线 Δ），已接入 `scripts/verify_all.py` 第 6 项。

### 9.3 RL 环境与接口（最终）

- **终止契约修复（阻断级）**：非 end_turn 分支此前不检查智能体死亡/游戏结束/max_steps → 终局后
  无限 invalid 循环（seed=24 复现）。已统一 helper 修复，所有分支（含 step-after-done）都返回
  正确 `terminated/truncated`；`docs/ENV_SPEC.md` 增加"终止契约"章节。
- **观测契约 v2**：`Observation.extra`（31+ 决策相关键），纯数据可 pickle，与 `info["obs_extra"]` 同源。
- **动作枚举补全**：带目标英雄技能候选 0→1308（20 局）、定向法术/战吼/双目标技能/Choose One/磁力；
  273 随从 + 76 法术全部可操作；候选裁剪 0.43–0.71%（结构动作从不被裁）。
- **接口层**：`hsbg/rl`（Policy/EnvLike 协议、Gymnasium 包装 `check_env` 通过、JSONL 采集器、
  多进程评测）；采集吞吐 **12 workers = 12.57 局/s**、4 workers teacher = 6–7 局/s；
  checkpoint 策略采集 4 workers 2.18 局/s（mean_rank 4.25）。
- **测试稳健性**：5 个依赖固定 seed 的统计型测试改为意图断言/构造性局面，全量连续两次
  **4,991 passed / 3 skipped / 0 failed**，无顺序敏感。

### 9.4 最终门禁

```powershell
python scripts/verify_all.py
# 7/7 gates PASS（engine_tests / project_tests / smoke_8p / env_validation /
#                env_bench / official_consistency / version_check），约 173s
```

### 9.5 仍待（需要外部输入）

1. **真实 Power.log**（开日志打一局）：事件级校准伤害上限 5/10 档位、复生 buff 保留、死亡波次/
   SoC 顺序——当前均为 NO EVIDENCE，按约定不改。
2. `BG28_583 Geomagus` 触发链配额需规则裁定；C'Thun awaken "split" 需官方证据。
3. 历史非池卡脚本（180 条 missing_script）可按差分频次继续补；不影响当前池训练环境。
4. 模型训练按用户指示暂停；BC 策略（4.34 平均名次）与 BC/PPO 管线已就绪，随时可恢复。
