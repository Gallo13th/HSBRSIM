# 环境接口缺口审计（ENV_INTERFACE_GAPS）

> 任务：暂停训练，把 **观测 / 动作 / 选择 / 回合** 四条接口补到「任何策略都能完整表达」。
> 本文是 **A. 缺口审计** 的交付物：每项给出 **代码位置 + 可复现实验 + 修改前后实测数字**；
> 修复落在 `hsbg/env/**`、`hsbg/agents/**`、`tests/`、`scripts/`（未改 `hsrl2/` 核心、未改 `spec.py`）。
>
> 复现命令（全部可重跑）：
>
> ```powershell
> python -m pytest tests -q                                   # 389 passed, 1 skipped
> python -m pytest hsrl2/tests -q                             # 4468 passed, 2 skipped（并行 card 脚本施工中见 §A7）
> python scripts/audit_env_coverage.py --games 20             # 启发式，门禁 PASS
> python scripts/audit_env_coverage.py --games 20 --agent mixed  # 启发式+随机，门禁 PASS
> python scripts/bench_env.py --seeds 20                      # 0 crash / 0 invalid / 0 reject
> ```
>
> 审计器：`scripts/audit_env_coverage.py`（新增，固化下列全部指标 + JSON 输出 + 退出码门禁）。
> 测试：`tests/test_env_coverage.py`（21 项，覆盖本文 A1–A5 的每一条）。

---

## 0. 结论速览（数字均来自 20 局 × 8 人、seed 0–19）

| 指标 | 修复前 | 修复后（heuristic / mixed） |
|---|---|---|
| 带目标的英雄技能候选（真实对局） | **0**（Lead 59 局实测也是 0；本仓库 20 局 0） | **1308 / 476** |
| 池内 19 个 `needs_target` 英雄技能可用性（synthetic） | 12/19 无法生成任何目标变体 | **19/19 可执行**（18 个出目标变体；Vol'jin 走 choice 链） |
| 定向战吼「以自身为目标」 | 漏枚举（`BG23_357` 0 个、`BG26_814` 0 个、`BG32_340` 缺 self） | 与引擎入场后候选一致 |
| 定向法术非法「无目标回退」 | `BG28_518` 等生成 → 引擎 `GameStateError` 拒绝 | 无目标候选一律不生成；22/22 池内定向法术有靶即出变体 |
| 双目标英雄技能（Vol'jin） | 完全跳过（候选 0） | 候选 1 + 2 个 choice 步选满目标，效果生效 |
| 池内 273 随从 + 76 法术「无候选卡」 | 未审计 | **0**（`pool_*_no_candidate_BUG` 门禁） |
| CANDIDATE_MAX 裁剪 | 尾部动作可能被硬截断（丢英雄技能/升级） | `trim_ratio` 0.43% / 0.71%，`plays_dropped=0`，关键类别不丢 |
| invalid / engine_rejected | 1 次 opponent reject / 20 局（强制生命购买）；另有非 end_turn 致死 **3934 invalid + step_cap**（audit-40 实测） | **0 / 0**；terminated 契约修复后 audit-40 invalid=0、step_cap=0 |
| `Observation.extra`（v2） | 无 | 每步携带（与 `info["obs_extra"]` 同源），冻结/技能次数/任务/饰品/Dark Gift/战斗等可读 |
| 槽位一致性（候选 slot ↔ 观测 slot） | 英雄技能目标 `tgt_zone=""`（不可见） | **0 不一致**（审计器硬门禁） |

`quick check`：`python scripts/audit_env_coverage.py --games 20` 末行输出
`GATE PASS`；JSON 中 `coverage.gates.failures == []`。

---

## A1. 动作枚举覆盖

### A1.1 定向英雄技能：`target_candidates` 全部空 + 槽位未映射（根因 2 个 bug）

代码：`hsbg/env/driver.py::_script_targets`、`_enumerate_hero_powers`。

**根因 1（决定性）**：`_script_targets(script, source, game)` 在脚本未定义
`target_candidates` 时走默认口径 `source.controller.board`；英雄技能路径传入的
`source` 是 **Hero**（Hero 没有 `.controller` 属性）→ 默认候选恒为空。19 个
`needs_target` 技能中 16 个依赖默认口径（"friendly minion"类），全部变成 0 变体。

- 证据：修复前 synthetic 探针（每英雄 `start_game` + 棋盘 3 随从）：
  `targeted powers with target variants: 8/19`，12 个为 0；
  `driver._script_targets(EdwinScript, hero, game) == []`（棋盘明明有 3 个随从）。
- 修复：`driver.py:437-439` —— `source` 无 `.controller` 且自身有 `.board` 时按 Hero
  处理，默认候选 = `hero.board`（与引擎 `_hero_power_target_ok` 同源）。

**根因 2（覆盖度可见性）**：`_enumerate_hero_powers` 生成候选时**没把 `zones` 传给
`_desc`** → 即使目标存在，`CandidateAction.tgt_zone/tgt_slot` 仍是 `""/-1`，策略看不到
目标、审计计数为"非目标变体"。

- 证据：`seed=1, hero=TB_BaconShop_HERO_62`（Maiev）棋盘空、酒馆 4 张：修复前
  `obs.candidates` 里 4 个 `hero_power` 候选全是 `tgt_zone=""`；修复后
  `[('hero_power','tavern',0), ..., ('hero_power','tavern',3)]`。
- 修复：`driver.py:759-776` 三处 `_desc(..., zones=zones, ...)`。

**After（真实对局 20 局）**：带目标英雄技能候选 **1308**（heuristic）/ **476**（mixed），
`obs_extra.targeted_power_present` 454 / 241。`_MAX_TARGET_VARIANTS_PER_SOURCE=6`
（`driver.py:712`）防止"一屏 7 个目标"挤爆 CANDIDATE_MAX。

**synthetic 全量验证**：`audit_env_coverage.py::audit_hero_power_targets`
（`--games` 无关，每次都跑）：19 个 `needs_target` 技能 **19/19** 生成候选且
`apply_action` 成功；唯一 `target_count=2` 的 Vol'jin 见 A1.4。

### A1.2 定向战吼：入场后才出现的候选（self / 手牌 / 酒馆）

代码：`hsbg/env/driver.py::_post_summon_targets`、`_play_minion_variants`。

引擎 `Game.play_minion` 先 `summon` 再求 `target_candidates`（"give this minion…"、
"a friendly Pirate"（自己也是海盗）等目标只在入场后出现）。旧实现入场前求值：

| 卡 | 引擎入场后候选数 | 旧实现变体数 | 现状 |
|---|---|---|---|
| `BG23_357` Mind Muck | 1 | **0** | 一致 |
| `BG26_814` Lovesick Balladist | 1 | **0** | 一致（含 self） |
| `BG32_340` Maw Caster | 2 | 1（缺 self） | 一致（含 self） |
| 其余 2 张定向战吼 | — | — | 一致；5/5 apply 成功 |

修复方式（`driver.py:447-503`）：把该随从**临时**放进 `hero.board`（只改 board 列表与
`ZONE_POSITION` tag，不 fire 事件、不改 `Entity.zone` 以免触发手牌监听器注销），
`try/finally` 逐位还原；对每个插入位置分别求值（相邻类战吼依赖位置）。
入场后候选中的不可寻址实体（对手棋盘等）通过一个「不指定目标」变体暴露为
`PendingChoice(kind="battlecry_target")` → **任何合法目标都经 choice 步可选**。

### A1.3 定向法术：非法「无目标回退」与 BG28_518

代码：`hsbg/env/driver.py::_play_spell_variants`。

- 旧实现：目标不在 zones（或候选为空）时返回**不带目标**的候选。
  对 `BG28_518 Chef's Choice`（脚本要求 `ctx['target']`）实测：
  `play_spell(target=None)` + 无候选 → `GameStateError: BG28_518 is a targeted
  spell: ctx['target'] required`（这正是 PPO 训练中遇到的 invalid 样本）。
  全量扫描 59 个注册定向法术（空棋盘）：**仅 BG28_518 会抛异常**，其余是"落空消耗"，
  但对策略同样是误导性候选。
- 修复（`driver.py:596-611`）：**有可寻址目标 → 只给显式目标变体；目标为空或全部
  不可寻址 → 不生成候选**（宁缺勿错）。`_synthetic_operable` 证明：22/22 池内定向
  法术在"有合法目标"的正常状态下都能生成且 apply 成功；`BG28_518` 在空棋盘时
  无候选（正确——引擎本来就会拒绝）。
- 覆盖矩阵：池内 **76 法术**（22 定向）全部可施放；`BG28_607`/`BG36_880` 等按种族
  过滤的卡在多状态审计（`tests/test_env_coverage.py::TestTargetedSpellEnumeration`）
  中均有目标变体。

### A1.4 双目标英雄技能（Vol'jin Spirit Swap，`target_count=2`）

旧实现：`_enumerate_hero_powers` 直接 `continue`（候选 0，技能不可用）。

引擎支持：`use_hero_power(hero, target=None)` 会依次挂起
`PendingChoice(kind="hero_power_target")` 收 2 个目标，收集后以 **list** 传入脚本
`ctx["target"]`（`VoljinScript.hero_power` 明确要求 list）。因此在驱动层**不近似**
目标组合：只需生成 1 个「不指定目标」的合法候选（候选数 ≥ 2 才生成），
组合经两个 choice 步表达。

- 修复：`driver.py:755-766`（`note="targets=2"`，`zones` 也会映射）。
- 验证：`tests/test_env_coverage.py::TestDualTargetHeroPower::test_voljin_two_choice_chain`
  —— env 里观测到 dual 候选 → step → `phase="choice"` → 两次 choose → 两个随从攻击力
  互换且恰好 2 个被 buff。`audit_env_coverage.py` 每次运行也验证
  `dual_target_powers=1, apply_ok`。
- 真实对局 20 局里 `dual_target_power_candidates=0`：只是 20 局没抽到 Vol'jin
  （1/118 英雄；8 人局 20 局期望 <1），synthetic 门禁已覆盖。

### A1.5 Choose One：双分支可达 + 嵌套第二选择

池内 7 张 Choose One（`BG27_084/1230_123/31320/32237/36330/36332/36341`）：
- 候选：`_play_minion_variants`/`_play_spell_variants` 识别 `choose_options` 后生成 1 个
  无目标候选；引擎挂起 `choose_one` PendingChoice（选项 key 即动作）。
- 真实对局：`choice_kinds["choose_one"]` 14 次（heuristic 20 局）。
- 陷阱：`BG27_084 Sprightly Scarab` 选择分支后**还会**挂一个
  `battlecry_target`（因为目标 Beast 由脚本再选）→ 环境必须继续暴露第二个 choice 步。
  测试 `TestChooseOneBranches` 走完整 env 链（choose_one → battlecry_target），
  两个分支效果分别验证（Reborn/+1/+1 vs Windfury/+4）。

### A1.6 磁力吸附扩展（Prosthetic Hand 等）

池内 8 张 Magnetic（`BG26_146/147`、`BG34_170t/t2/t3`、`BG35_341`、`BG_BOT_911`、
`BG_DEEP_015`）。吸附合法性由引擎 `_magnetic_valid`（含数据例外：Prosthetic Hand
可贴 **Undead**；Technical Element 可贴 Elemental）。驱动层直接调用引擎判定即完备。

- 覆盖：真实对局 20 局 `magnetic_attach_candidates=11`（heuristic）/5（mixed）。
- 测试：`TestMagneticTargets` —— Prosthetic Hand → Undead 宿主有候选且 apply 成功
  （宿主获得 Reborn/属性）；非允许宿主（Dragon）无吸附候选。
- 已知展示限制：`CandidateAction` 无 `magnetic` 字段 → 吸附候选与"打出到棋盘"候选
  签名可能同槽（当前实现磁力+战吼只枚举吸附；纯磁力卡两者签名不同）。属 **spec 提案**
  （见 A2 建议字段 `CandidateAction.flags`），不阻塞。

### A1.7 池内卡覆盖矩阵（273 随从 + 76 法术）

`scripts/audit_env_coverage.py::_synthetic_operable` 对每张池内卡做"正常对局状态"检查：
随从 = 手牌打出（或酒馆购买）候选存在且 apply 成功；法术 = 手牌施放候选存在且
apply 成功（棋盘预置多种族随从，覆盖按种族过滤的目标）。

- 结果：**273/273 随从、76/76 法术可操作**；`pool_*_no_candidate_BUG = []`（门禁）。
- Lead 指出的 14 张"从未被动作引用的卡"分类见 A5。

### A1.8 购买支付方式：强制生命购买曾产生必然被拒候选

`BG28_571 Hasty Excavation`（"This costs Health to buy instead of Gold"）：
旧 `_enumerate_buys` 只检查金币 → 生成候选；引擎 `buy_from_tavern` 对
`health_cost` 卡**强制生命支付**，`health+armor <= cost` 时返回 False
（即使金币充足）。20 局审计中 `opponent_rejected:buy` 1 次即此卡。

- 修复：`driver.py:360-398` `_forced_health_buy` 复刻引擎 health_buy 判定顺序
  （`health_cost` → `HEALTH_BUY` → 本回合生命购买配额），强制生命时只判生命。
- 验证：`tests/test_env_coverage.py::TestBuyAffordability`（生命够→有候选且成功；
  生命不够→无候选，且引擎确实拒绝）；bench `opponent_rejects=0`。

---

## A2. 观测字段缺口（已按 Lead 契约 v2 接线）

`Observation` 已由 Lead 升级到 **version=2**，新增
`extra: Dict[str, Any]` + `Observation.get_extra(key, default)`（见
`hsbg/env/spec.py`）。环境侧接线：

- **唯一数据源**：`hsbg/env/observation.py::build_extra_state(...)`（纯数据、
  只读、不消耗 RNG）；`hsbg/env/observation.py::_plain_extra` 递归深拷贝，
  保证 **不含引擎对象、可 pickle、每个观测独立**。
- `build_observation(..., extra=None)`：独立使用时自动构建；`game_env._observe`
  传入自己的 `build_extra_state(...)` 结果，使 `obs.extra` 与
  `info["obs_extra"]` **同源**（`_make_info` 复用 `self._obs.extra`，不重复构建）。
- 兼容：`info["obs_extra"]` 保留（旧消费方不破），新代码建议读
  `obs.extra` / `obs.get_extra()`。

### A2.1 `extra` 键清单（真实对局 20 局出现次数，heuristic / mixed）

| 键 | 类型 | 内容 | 出现 |
|---|---|---|---|
| `version` / `turn` | int | 观测协议版本（=2）/ 回合 | 每步 |
| `frozen_tavern` | bool | 酒馆冻结 | heuristic 0（该策略不冻结）/ **mixed 92** |
| `free_refresh_left` | int | 免费刷新剩余 | 53 / 31 |
| `health_refreshes_left` / `refresh_cost` | int | 血量刷新/刷新价 | 每步 |
| `gold_spent_this_turn` / `cards_played_this_turn` / `tavern_spells_cast_this_turn` / `tavern_spells_cast_this_game` / `minions_sold_this_turn` | int | 本回合经济计数 | 每步 |
| `blood_gem_atk_bonus` / `blood_gem_health_bonus` / `next_spell_cost_reduction` | int | 血宝石/法术折扣 | 每步 |
| `powers` | list[dict] | 主槽+第二槽：`power_id, cost, uses_left_this_turn, uses_per_turn, uses_left_this_game, passive, needs_target, target_count` | **2111/1329 每步**；`targeted_power_present` 454/241 |
| `power_uses_left` | dict[str,int] | `power_id → 本回合剩余次数` | 每步 |
| `second_power_id` / `second_power_cost` / `second_power_uses_left` | str/int | 第二技能槽（无则 `""/-1/0`） | 每步 |
| `dark_gift` / `dark_gift_uses_left` | dict/int | S14 黑暗赠礼状态/剩余 | enabled 1959/1169 |
| `quest` | dict\|None | `card_id, progress, target, completed, reward_ids, pending_reward_id` | 1810/1027 |
| `quest_progress` / `quest_target` / `quest_completed` / `quest_reward_ids` | int/bool/list | 任务进度/目标/完成/奖励（平铺） | progress>0 1337/651 |
| `trinkets` / `trinket_ids` | list | 饰品卡 id + 计数器（Avenge/Lockbox/Activate） | 1500/736 |
| `board_states` | list[dict] | 随从临时状态：`exhausted, frozen, activate_used_this_turn, windfury_attacks, divine_shield_hits, venomous_consumed` | 每步（有随从时） |
| `hand_states` | list[dict] | 手牌 `locked_in_hand` | 每步 |
| `minion_flags` | dict[int,dict] | `entity_id → 标志`（含 `locked_in_hand`），供策略按实体索引 | 2082/1278 |
| `pending_hand_queue` / `pending_hand_card_ids` | int/list | 满手等待入场的卡（跨回合补发） | `>0` 63/71 |
| `next_opponent` / `last_opponent` | str\|None | 对手 hero_id（官方 HUD 可见） | 2000/1271 |
| `next_opponent_info` / `last_opponent_info` | dict\|None | 对手 name/health/alive | 每步 |
| `elimination` / `elimination_order` | list | 已淘汰玩家名次 / 先淘汰先出 | 中后期 |
| `last_combat` | dict\|None | **仅己方**最近战斗摘要（winner/loser/damage/rounds） | 2027/1263 |
| `deaths_by_card_id` | dict[str,int] | 己方按卡死亡计数（Eternal Knight 类动态属性源） | 每步 |
| `turn_stats` / `env_stats` | dict | 本回合/累计统计（奖励核对/调试） | 每步 |

> **POMDP 边界**：`last_combat` 只透出**己方**战斗（他人战斗细节属隐藏信息）；
> 上一对手战团仍由 `Observation.opponent_board`（官方可见）提供。

### A2.2 接线测试与门禁

- `tests/test_env_coverage.py::TestObservationV2Extra`（8 项）：version=2、
  必需键、`obs.extra == info["obs_extra"]`（同源）、pickle 往返、递归纯数据、
  动态字段（frozen/技能剩余/任务/黑暗赠礼/随从标志）、重复构建无副作用、
  `VecEnv(multiprocess=True)` 跨进程 extra 完整。
- 审计器新增：`coverage.extra_missing_keys`（必需键缺失计数）、
  `obs_extra_missing`（空 extra 步数）、`obs_extra_mismatch`
  （`info` vs `obs.extra` 不一致）、关键键出现率；任一 >0 → 退出码 1。
  20 局 heuristic/mixed 均 `failures=[]`。

### A2.3 仍未纳入 spec 的建议（可选，非阻塞）

- `CandidateAction` 增加 `flags: Tuple[str,...]`：区分 `magnetic` /
  `power_id` / `targets=2` 等同签名但语义不同的候选（当前索引式 API 已可用；
  特征式策略可在候选 index 上自行消歧）。

## A3. CANDIDATE_MAX=64 裁剪量化

指标来自每步 `driver.enumerate_actions(stats=env._stats)`（`driver.py:849`）：

| 指标 | heuristic 20 局 | mixed 20 局 |
|---|---|---|
| `candidates_generated`（裁剪前） | 29,989 | 15,835 |
| `candidates_trimmed` | 129（**0.43%**） | 113（**0.71%**） |
| `max_candidates_generated`（单步峰值） | 84 | 84 |
| `max_candidates`（返回峰值） | 64 | 64 |
| `plays_dropped`（手牌组整组消失） | **0** | **0** |

**被裁掉的类别**：全部是手牌打出的"位置 × 目标"变体（满手 10 张 + 多目标战吼时
单步可达 84）；买/卖/技能/升级/刷新等"结构动作"从未被裁。

**修复（不改 spec）**：
1. 手牌预算改为**轮转分配**（`driver.py:631 _apply_hand_budget`）：先保证每张手牌
   至少 1 个变体，再轮流追加 → `plays_dropped=0`（旧实现"前几张吃掉预算，后面的整组
   消失"）。
2. 单来源目标变体上限 6（`driver.py:712`），尾部动作（卖/技能/Activate/升级/刷新/
   Dark Gift）在极端情况下按优先级裁剪（`driver.py:783 _trim_tail_preserving`）：
   升级/刷新/冻结/Dark Gift/技能优先，卖随从/Activate 最后裁；**不再**像旧实现那样
   硬截断把英雄技能/升级整个丢掉。
3. `CANDIDATE_MAX` 是否提高（如 96/128）→ **需要 Lead 改 spec + 训练侧重训**；本次
   数据表明 0.4–0.7% 裁剪且无结构动作被裁，**暂不建议**提高。

---

## A4. 非法 / 引擎拒绝 / 无进展 保护覆盖

| 指标（20 局） | 修复前 | 修复后 heuristic | 修复后 mixed |
|---|---|---|---|
| `invalid`（非候选动作） | 0 | **0** | **0** |
| `engine_rejected`（候选被引擎拒） | 1（强制生命购买） | **0** | **0** |
| opponent 侧拒绝 | 1 | **0** | **0** |
| `noop_actions`（指纹无变化） | 0 | 28 / 2132 步 | 24 / 1327 步 |
| `budget_exhausted`（每回合 40 动作预算触发） | 0 | 0 | 0 |
| `step_cap_hit`（max_steps 护栏） | 0 | 0 | 0 |

- freeze 无限 toggle 已在此前修复（单向 freeze + 每回合预算 + 无进展保护）；
  `noop_actions` 均来自"合法但不改指纹"的动作（如免费刷新未改变酒馆、Dark Gift 同回合
  重复等被预算/保护兜底），不会拖死回合。
- `engine_rejected` 唯一来源（A1.8）已修；`audit_env_coverage.py` 中
  `engine_rejected != 0` 为硬门禁。

---

### A4.1 终止契约阻断 bug（非 end_turn 分支不检查终止）

**现象（Lead 报障，已复现）**：`BattlegroundsEnv(num_players=8, seed=24)` 用
HeuristicPolicy 驱动，第 67 步（`hero_power` = `TB_BaconShop_HP_049`
"Steal a card from the Tavern. **Take 2 damage**"）智能体血量 1→0：

- 观测已是 `phase="game_over"`（`candidates=()`），但 `step()` 返回
  `(obs, r, False, False)`、`_done=False`；
- 之后任何动作都走 "非候选动作" 分支 → `invalid=True` 且**永不终止**，
  实测 audit-40 出现 `invalid_actions=3934`、`step_cap_hit=1`。

**根因**：`hsbg/env/game_env.py::step` 的**非 end_turn** 分支在
`apply_action → _drain_choices → _observe` 后直接返回 `False, False`，
没有检查智能体死亡 / `game.finished` / `max_steps` / `max_turns`（这些只在
`_end_turn_step` 检查）。

**修复**（`hsbg/env/game_env.py`）：

1. 抽取统一终止 helper（所有分支共用）：
   - `_agent_rank()`：淘汰名次（`_rank_by_hero`）/ 存活估计；
   - `_terminal_reward()`：step_penalty + placement（+ timeout）；
   - `_terminal_obs_info()`：置 `_done`、`_was_truncated`、清残余选择、
     重观测为 `phase=game_over`、写 `agent_rank/elimination_order/truncated`；
   - `_termination_check()`：判定顺序 **淘汰 → 全胜结束 → max_steps →
     max_turns → 兜底**（`obs.phase == game_over` 或 `obs.candidates` 为空
     但 `_done=False` → 立即收口）。
2. `step()` 接线：入口先做兜底终止检查（不消耗步数）；非 end_turn 分支在
   apply/drain 后调用 `_termination_check()`；invalid 分支返回前也先检查；
   `_end_turn_step` 改走同一 helper（行为不变）。
3. step-after-done 不再标 `invalid=True`（改为 `episode_done` warning，
   `terminated=True`、步数不增长）。

**回归测试**（`tests/test_env_coverage.py::TestTerminationContract`，5 项）：

| 测试 | 覆盖 |
|---|---|
| `test_self_elimination_terminates_replay_seed24` | 真实复现（seed=24 第 67 步自伤）：terminated=True、reason=eliminated、rank/agent_rank 一致、phase game_over、后续 3 次 step 均 terminated 且步数不变 |
| `test_self_elimination_minimal_hero_power` | 最小构造：1 血 + `TB_BaconShop_HP_049` 自伤致死；校验 placement 奖励公式 |
| `test_no_invalid_loop_after_game_over` | 强制 `obs.phase=game_over` 且 `_done=False`：step 立即 terminated（reason game_over）、步数不增长、无 invalid |
| `test_max_steps_truncates_any_branch` | `max_steps=5` + 连续非 end_turn 动作：truncated=True、reason=max_steps、info["truncated"]=True、之后 step 仍 terminated |
| `test_terminated_info_has_rank_and_reason` | 终局 info 必含 rank/agent_rank/terminated_reason/truncated/episode_steps 且合法；`info["obs_extra"]` 与 `obs.extra` 同源 |

**门禁实测**：`audit_env_coverage.py --games 40`（Lead 的复现命令）→
invalid=0、engine_rejected=0、step_cap=0、`GATE PASS`；`--games 20 --agent mixed`
同样 PASS；`validate_env.py --games 30` → `ok:true, failures:[]`；
`bench_env.py --seeds 20` → 0 crash/invalid/reject，game avg 395ms。

## A5. 从未被动作引用的卡（Lead 清单逐项分类）

方法：20 局（mixed）里统计 **观测可见卡**（board/hand/tavern/trinket/quest/opponent）
与 **候选动作引用卡**（descriptor 的 `src_entity`/`tgt_entity`）之差；对差集中的池内卡
再做 `_synthetic_operable`（手牌/酒馆能否生成并 apply 成功）判定是否真 bug。

分类结果（20 局 mixed）：`never_referenced = 114` 张：

| 分类 | 数量 | 含义 |
|---|---|---|
| `token_data_chain` | 16 | 由其他卡数据链（triple/evolution 等）生成，不该直接操作 |
| `token_script_literal` | 38 | 脚本字面量 token/法术（奖励、饰品、任务） |
| `pool_minion_operable_not_sampled` | 49 | 池内随从，**synthetic 可操作**，只是 20 局没在"可买"时机出现 |
| `pool_spell_operable_not_sampled` | 4 | 同上（法术） |
| `unplayable` | 1 | `BG36_520t Lockbox`（数据 `Unplayable`） |
| `unreferenced_no_evidence` | 2 | 非池内、无数据链/脚本证据（数据旧版残留） |
| **`pool_*_no_candidate_BUG`** | **0** | **无"本应可操作却无候选"** |

Lead 清单 14 张逐项（20 局 mixed）：

| 卡 | 名称 | 本次分类 | 结论 |
|---|---|---|---|
| `BG26_152` | Utility Drone | 已引用 | 非缺口 |
| `BG28_169` | Azerite Empowerment | 已引用 | 非缺口 |
| `BG28_550` | Rodeo Performer | 已引用 | 非缺口 |
| `BG31_035` | Groundbreaker | 已引用 | 非缺口 |
| `BG32_837` | Fauna Whisperer | `pool_minion_operable_not_sampled` | synthetic 可买/可打出；采样问题 |
| `BG34_858` | Air Revenant | 已引用 | 非缺口 |
| `BG36_344` | Hooktusk, Master Marauder | 已引用 | 非缺口 |
| `BG36_352` | Unbound Tempest | 已引用 | 非缺口 |
| `BG36_367` | Auto Reveille | 已引用 | 非缺口 |
| `BG36_520t` | Lockbox | `unplayable` | 数据 Unplayable（正确不可操作） |
| `BG36_700` | Sewer Escapee | 已引用 | 非缺口 |
| `BG36_762` | Devilish Distractor | 已引用 | 非缺口 |
| `EBG_Spell_017` | Eyes of the Earth Mother | 已引用 | 非缺口 |
| `EBG_Spell_038` | Lost Staff of Hamuul | 已引用 | 非缺口 |

> 注：同一清单在 heuristic 20 局的结果略有差异（`never_referenced=101`，池内"未采样"
> 30+2 张），但 `pool_*_no_candidate_BUG` 同样为 0；差异纯属"该局是否在可买时机出现"。

---

## A6. 修改文件

| 文件 | 变更 |
|---|---|
| `hsbg/env/driver.py` | `_script_targets` Hero 默认候选；`_post_summon_targets`（入场后目标 + 自 target）；`_play_minion_variants` 重写定向分支；`_play_spell_variants` 删除非法无目标回退；`_enumerate_hero_powers` 多目标 + `zones` 映射 + 单来源上限；`_forced_health_buy`；`_hand_play_groups`/`_apply_hand_budget` 轮转；`_trim_tail_preserving`；`enumerate_actions(stats=)` 审计计数 |
| `hsbg/env/observation.py` | `_extra_hero_state` / `build_extra_state`（冻结/技能/任务/饰品/Dark Gift/随从临时状态/等待队列/对手/战斗/淘汰/统计；只读） |
| `hsbg/env/game_env.py` | `_stats` 新增覆盖/裁剪/预算/noop 计数；`_account_step`；`obs.extra`/`info["obs_extra"]` 同源；`extra_state()`；**统一终止 helper（`_termination_check/_terminal_obs_info/_agent_rank/_terminal_reward`）并接入 step 全部分支**（§A4.1） |
| `hsbg/env/__init__.py` | 导出 `build_extra_state` |
| `hsbg/agents/base.py` | `choose_option_index`（统一选择步入口：策略自带实现 or `game.rng` 随机，保确定性） |
| `hsbg/agents/__init__.py` | 导出 `choose_option_index` |
| `tests/test_env_coverage.py` | **新增 32 项**：定向法术/战吼/双目标/Choose One/磁力/槽位一致性/统计/obs v2 extra/池内卡可操作/覆盖门禁/多人数/强制生命购买/**终止契约 5 项（§A4.1）** |
| `scripts/audit_env_coverage.py` | **新增**：可复现审计器（动作/目标/选择/裁剪/非法/未覆盖卡/obs_extra + JSON + 退出码门禁） |
| `docs/ENV_INTERFACE_GAPS.md` | 本文 |

未修改：`hsbg/env/spec.py`（Lead 契约）、`docs/ENV_SPEC.md`（等待 spec 决策后由 Lead 同步）、
`hsrl2/**` 核心、`data/`。

---

## A7. 刻意不支持 / 边界（记录在案）

1. **战斗期 PendingChoice**：引擎在 `run_combat` 内产生的选择（如战斗中的亡语发现）
   由环境自动结算，不暴露给策略（Lead 已确认的边界；训练阶段不建模战斗内决策）。
2. **隐藏信息区域目标**：`target_candidates` 若返回对手棋盘/引擎内部实体（当前池内
   定向法术/战吼无此情况），定向法术候选**不生成**（宁缺勿错）；定向战吼可通过
   "不指定目标→choice 步"表达（引擎会挂起 `battlecry_target`）。
3. **`CandidateAction` 无 `power_id`/`magnetic`/`note`**：同 kind 同槽位但不同技能/
   吸附语义的候选签名可能相同；索引式 API（`env.step(int)`）不受影响，
   特征式策略需按 index 消歧。建议 spec 增 `flags: Tuple[str,...]`（见 A2 方案 A/B）。
4. **候选上限 64**：见 A3；当前裁剪率 <1% 且无结构动作被裁。
5. **`target_count>2` 的英雄技能**：当前池内仅 Vol'jin（=2）；机制已按 N 泛化
   （`len(cands) >= target_count` 才生成，choice 链由引擎处理 N 次）。
6. **并行施工备注**：本 agent 最终验收时 `hsrl2/tests` 有 2 个**注册表类**测试
   失败 + 1 个 untracked 测试文件 collection error，均来自其他 agent 正在改的
   card 脚本（`test_batch_37x_payloadgap1/poolgap2`、`test_batch_diff_driven1`），
   与本环境改动无关；忽略该 untracked 文件后 `4468 passed, 2 skipped`。
