# 环境层动作 / 观测覆盖审计（AUDIT_ENV_ACTIONS）

> 审计对象：`hsbg/env/**` 对真实酒馆战棋 7 类交互的动作枚举、目标表达、观测暴露与结算闭环。
> 方法：**纯静态只读**（代码/文档/数据/测试），未运行游戏、未改代码；行号取自当前工作树。
> 结论速览：**1 项完全不支持（随从换位）**、**2 项 P0 语义缺口（Dark Gift 配对 gift 不可观测；
> 非暂停阶段智能体选择被自动结算）**、多项 P1 目标枚举/身份/测试缺口。
> 已有审计 `docs/ENV_INTERFACE_GAPS.md` 覆盖了 A1 目标枚举修复史；本文按「真实交互」重新归类，
> 并补它未覆盖的 Choose One 语义、Dark Gift 配对、三连/发现/饰品、换位。

---

## 1. 架构与数据流摘要

```
BattlegroundsEnv.reset(seed)
  └─ game.start_game() → _drain_choices() → _observe()
BattlegroundsEnv.step(action)
  ├─ _resolve_action：按 CandidateAction.signature() 匹配 descriptors（game_env.py:477-503）
  ├─ driver.apply_action → 引擎 API（driver.py:962-1027）
  │    BUY/SELL/PLAY_MINION/PLAY_SPELL/REROLL/UPGRADE/FREEZE/
  │    HERO_POWER/ACTIVATE/USE_DARK_GIFT/CHOOSE（driver.py:972-1010）
  ├─ _drain_choices：非智能体选择自动结算；智能体选择返回 → phase="choice"
  │    （driver.resolve_pending_choices 契约：FIFO 弹出→choose→已弹出，driver.py:1092-1137）
  ├─ end_turn：驱动 7 名对手招募（_drain_all_choices）→ game.end_recruit_phase()
  │    └─ ChoiceQueue「入队即结算」，仅 `game.turn > turn_before` 的智能体选择被保留
  │       （game_env.py:845-882, driver.py:1140-1192）
  └─ _observe：唯一槽位视图 driver.Zones → Observation（槽位与候选同源）
```

- **槽位同源**：`driver.collect_zones()`（driver.py:137-159）一次生成 board/hand/tavern/trinkets
  有序列表；动作枚举与 `observation.build_observation()`（observation.py:771-849）共用，
  因此 `CandidateAction.src/tgt_zone+slot` 就是观测槽位。
- **动作契约**：`spec.ActionKind`（spec.py:68-86）共 12 类；`CandidateAction`（spec.py:209-235）
  字段 `kind/src_zone/src_slot/tgt_zone/tgt_slot/position/option/cost`。
- **观测契约**：`Observation.version=2`（spec.py:251）；实体槽 + 全局标量 + `pending_choice`
  + `extra`（observation.py:643-769，纯数据、可 pickle）。
- **选择即动作**：所有引擎 `PendingChoice` 走 `phase="choice"`、候选只有 `choose`（option 下标），
  `driver.enumerate_choice`（driver.py:935-940）；观测把 options 序列化为 `EntityToken`
  （observation.py:447-460）。
- **不可暂停边界**：`end_recruit_phase` 内（EoT/战斗/淘汰）产生的选择不能暂停；`ChoiceQueue`
  入队即结算；只有新回合开始后的选择（任务/饰品三选一）会保留（game_env.py:24-28, 845-882）。

---

## 2. 逐交互审计

### 交互 1：选择一个随从（战吼 / 法术 / 英雄技能 / 磁力）

**live 需要**：打出带目标卡后进入目标选择（点选/拖拽）；目标域可为己方棋盘、手牌、酒馆
（如 Maiev/Arcane Alteration/Lock and Load）；多目标技能需连续选 N 个；磁力需选吸附宿主。
证据：`docs/LIVE_TO_SIM_GAP.md:58`（L06 target 法术）、`docs/LIVE_AUTOMATION_PROTOCOL.md:174,185`；
引擎端待选协议 `PendingChoice(kind="battlecry_target"/"spell_target"/"hero_power_target")`
（game.py:1148-1152, 1538-1541, 2166-2169）。

**env 现状（支持主路径）**
- 目标用 `tgt_zone/tgt_slot` 表达（spec.py:219-228），apply 时传引擎：
  `PLAY_MINION target/magnetic_target`（driver.py:976-984）、`PLAY_SPELL target`（driver.py:985-987）、
  `HERO_POWER target`（driver.py:999-1002）。
- 战吼：`_post_summon_targets`（driver.py:447-486）按「入场后」引擎口径算候选（含 self），
  对每个插入位置求变体（driver.py:546-566）；目标不在槽位视图时追加「不指定目标」变体，
  由引擎挂起 `battlecry_target` 经 choice 步补齐（driver.py:558-565; game.py:1138-1152）。
- 法术：`_script_targets`（driver.py:425-444）按脚本 `target_candidates`；仅枚举显式目标变体
  （driver.py:587-600），目标为空/全部不可寻址 → **不生成候选**（driver.py:601-607，BG28_518 教训）。
- 英雄技能：单目标逐个枚举（driver.py:767-776）；多目标（Vol'jin）只给 1 个无目标候选，
  引擎连续挂起两次 `hero_power_target` 由 choice 链表达（driver.py:749-762; game.py:2149-2172）。
- 磁力：`_magnetic_valid`（game.py:1437-1461）判定宿主，每宿主一个 `magnetic=True` 变体
  （driver.py:516-528），apply 走 `magnetic_target`。
- 观测：目标实体由 `tgt_zone/tgt_slot` 指向（observation.py:802-811 各 zone 实体）；choice 步
  options 为 `EntityToken`（observation.py:447-460）。

**缺口**
1. **P1 定向法术无 choice 回退**：`target_candidates` 非空但被 `CANDIDATE_MAX`/手牌预算裁剪，
   或目标实体不可寻址时，该目标在 env 中**不可选**；引擎其实支持 `target=None` 挂起
   `spell_target`（game.py:1531-1544）。建议非空候选时补 1 个无目标候选，目标经 choice 选
   （与战吼同构），可完全消除目标裁剪问题（driver.py:587-607 为现状）。
2. **P1 英雄技能单目标硬上限 6**：`_MAX_TARGET_VARIANTS_PER_SOURCE=6`（driver.py:712）对每个
   来源截断（driver.py:770-776），而技能目标域可到 7（酒馆：batch_hero_actives.py:156-157、
   365-366、608-609）甚至 10（手牌：batch_hero_actives.py:484-485）→ 多出的目标不可选，
   且单目标路径没有 no-target 回退。建议补无目标候选走 `hero_power_target` choice
   （引擎 game.py:2139-2172 已支持单目标 no-target 挂起）。
3. **P2 战吼 target×position 矩阵裁剪**：有可寻址目标时不发 no-target 回退（driver.py:558-566），
   矩阵被预算裁掉的目标无法通过 choice 补回（driver.py:631-668, 897-905）。建议同样补
   「无目标→choice」候选。
4. **P1 动作身份字段缺失（磁力 / 技能）**：`CandidateAction` 无 `magnetic`/`power_id` 字段
   （spec.py:209-235）。`_play_minion_variants` 在「有可吸附宿主」时**只枚举吸附**，普通打出
   （会触发战吼/占格子）不暴露，且与描述符靠 `ActionDescriptor.magnetic` 区分（driver.py:191,
   534-541）；策略/外部按 CandidateAction 签名无法区分。同类问题见交互 5。
5. **P2 候选目标不可寻址域**：目标若为 Hero/隐藏区实体则无槽位引用；当前池内定向卡目标域为
   board/hand/tavern（可寻址），属已记录边界（ENV_INTERFACE_GAPS A7-2）。

**测试建议**
- 已覆盖：`tests/test_env_coverage.py:150-197`（定向法术池）、`:198-257`（定向战吼/self）、
  `:258-294`（Vol'jin 双目标）、`:355-389`（磁力）、`:390-460`（槽位一致性）。
- 待补：`tests/test_env_actions.py::test_hero_power_targets_over_6_use_choice`（Maiev 7 酒馆目标 →
  无目标候选 → 两次？一次 choice 选满 7）；`test_targeted_spell_choice_fallback_when_trimmed`；
  `test_magnetic_normal_play_variant`（磁力+战吼卡普通打出）；`test_battlecry_target_choice_fallback`。

---

### 交互 2：抉择 Choose One（法术 / 随从上二选一）

**live 需要**：弹出二选一（两个分支文本），选择后结算；部分卡选择后还要选目标
（Sprightly Scarab）；部分光环/特殊卡两效合并（Thorned Trailblazer、Fandral's Fortune）。
证据：引擎协议 game.py:1120-1135（随从）、1513-1530（法术）；组合缺口注释
`hsrl2/scripts/batches/batch_misc.py:52-54`；法术自建协议 `batch_spells4.py:13-17,61-69`。

**env 现状（支持主路径）**
- 打出候选：随从在 `_play_minion_variants` 识别 `choose_options` 后不生成目标变体、只给位置变体
  （driver.py:507-509, 546-568）；法术在 `_play_spell_variants` 直接给 1 个候选
  （driver.py:583-586）。apply 后引擎挂起 `choose_one`（game.py:1131-1134, 1527-1529）。
- 选择步：`_drain_choices` 把智能体选择暴露为 `phase="choice"`，候选 `choose(option)`
  （game_env.py:452-460; driver.py:935-940, 948-959）；choose 触发脚本 `resolve_callback`
  （如 `_run_play_effects(..., choose=key)`），可再挂第二个选择（Scarab → `battlecry_target`，
  batch_misc.py:1116-1174），env 继续以 choice 步暴露。
- CHOOSE_BOTH：引擎自动双效、不产生 PendingChoice（game.py:1123-1129, 1516-1521）→ env 无需动作。
- 观测：`pending_choice.kind="choose_one"`，options 为 key 字符串经 `entity_token` 转
  `EntityToken(card_id=key, card_type=unknown)`（observation.py:292-303, 447-460）。

**缺口**
1. **P1 分支语义丢失**：`choose_options=[(key,label),…]` 的 **label 文本没有进入观测**
   （engine 的 PendingChoice options 只放 key，game.py:1130-1134；`_pending_token` 不读
   `choose_options`，observation.py:447-460），`PendingChoice.prompt` 永远为空
   （spec.py:198-206）。策略只能看到 `card_id="reborn"/"windfury"` 这类 key，跨卡同 key 时无法
   区分具体卡的分支效果。建议 options 增 `label`/`prompt` 结构化字段（见 P0-2 同一改造）。
2. **P2 `choose_one + needs_target` 组合是潜在缺口**：driver 在 `has_choose` 时不枚举目标
   （driver.py:546），引擎 choose 分支也吞掉 needs_target 分支（game.py:1126-1135；
   脚本缺口记录 batch_misc.py:52-54）。现有 Scarab 靠脚本自建第二段 choice 才能工作；若后续卡
   按标准 `needs_target` 声明，env 无法在打出时传 target，目标将不可选。
3. **P1 非暂停阶段的 Choose One 被自动结算**：见交互 6 缺口 2（EoT/淘汰/对手招募期产生的选择
   全部走 `default_pick_index`，choose_one 默认恒选 0，driver.py:1056-1057）。
4. 观测 options 复用 `EntityToken`（`atk/health/tier/races/keywords` 全空），语义容器不匹配
   （同 P0-2）。

**测试建议**
- 已覆盖：`tests/test_env_coverage.py:296-354`（两条分支 + 嵌套 battlecry_target，真实 env 链）。
- 待补：`test_choose_one_option_labels_preserved`（构造带 choose_options 的卡，断言观测能区分
  两分支语义）；`test_choose_one_needs_target_latent`；`test_choice_created_at_eot_is_held`。

---

### 交互 3：ACTIVATE 关键词

**live 需要**：点随从 Activate 按钮 → 付 `activate_cost`（可能 0）→ 需要目标的脚本再选目标；
每回合 1 次。证据：引擎 `use_activate`（game.py:1908-1922）；定向 Activate 协议
`PendingChoice(kind="activate_target")`（`hsrl2/scripts/minions.py:278-321`；
`batch_37x_payloadgap1.py:1199-1232`；`batch_misc.py:1006-1050`）；池内约 40 张 Activate 卡
（`data/bg_pool_minions.json:1048,3229-3230` 等 `"activate": true`）。

**env 现状（支持主路径）**
- 动作：`ActionKind.ACTIVATE`（spec.py:82）；`_enumerate_activate` 对棋盘上
  `ACTIVATE && !ACTIVATE_USED_THIS_TURN && gold>=ACTIVATE_COST` 的随从各生成 1 个候选
  （driver.py:818-831）；apply → `game.use_activate`（driver.py:1003-1004）。
- 目标：引擎 `use_activate` **无 target 参数**（game.py:1908-1922），定向由脚本在 activate 钩子内
  自挂 `activate_target`；env 的 `_drain_choices` 会把它暴露为 choice 步（game_env.py:452-460），
  apply 正常。即「先激活、再选择目标」两段式闭环已具备。
- 观测：实体 `keywords` 含 `"activate"`（observation.py:115）；本回合已用见
  `extra.board_states[].activate_used_this_turn`（observation.py:596-618, 711-721）；
  候选 `cost` 即激活费（driver.py:826-830）。

**缺口**
1. **P2 可能枚举「必然落空」的激活候选**：脚本无合法目标时官方裁定「仍可按但无效果」
   （minions.py:293-294），`use_activate` 先扣费并置 used（game.py:1918-1921）→ env 候选被选中
   后成功但无效果；live UI 通常仍可点，属语义等价，但训练会浪费动作/金币。
2. **P2 观测无 `activate_cost` 实体字段**：只有候选 cost；对「看一眼棋盘就知道哪些可激活」的
   策略特征不足（policy/encoder 未编码 `board_states` 的 activate 状态，见交互 7 相关）。
3. **P1 测试空白**：`tests/test_env_*.py` 无任何定向 Activate 用例；覆盖门禁只用合成 Minion
   断言 `activate` 类出现（`tests/test_env_coverage.py:893-925`），targeted activate 全链路
   （activate → phase=choice → choose → 效果）未回归。建议新增
   `test_env_coverage.py::TestActivateTarget`（Kelp Keeper + 棋盘战友 → 触发战吼）。

**测试建议**：上述 3；另加 `test_activate_cost_and_once_per_turn`（0 费/2 费/同回合第二次无候选）。

---

### 交互 4：购买「黑暗之赐」随从 / Dark Gift 选择

**live 需要**：T3 起花 3 金点 Dark Gift 按钮 → 出现 3 个「随从 + Dark Gift」配对选项
（每个随从绑不同 gift，gift 是持久附魔）→ 选一个，随从带 gift 入手；饰品（Ominous Stone /
Wax Lance / Maldraxxus Dagger）、英雄技能也会触发同一协议。证据：规则/数据
`docs/reference_old/REFACTOR_PLAN.md:135-138`、`docs/ENGINE_API.md:331,1152,1441`（43 个 gift）、
引擎实现 game.py:2261-2315（主路径）、`batch_trinkets20.py:426-470`（饰品触发）、
`batch_trinkets22.py:300-386`（SoT 触发）。

**env 现状（动作支持，选项语义不完整）**
- 动作：`ActionKind.USE_DARK_GIFT`（spec.py:83）；`_enumerate_dark_gift` 复刻引擎门槛
  （turn>=DARK_GIFT_START_TURN、uses_left、本回合已用、gold>=cost；driver.py:834-846）；
  apply → `game.use_dark_gift`（driver.py:1005-1006）。
- 选择：引擎产生 `PendingChoice(kind="dark_gift", options=[(card_id,gift_id),…])`
  （game.py:2290-2314）；env 的 `_drain_choices` 暴露为 choice（game_env.py:452-460），
  `choose(option)` 结算（driver.py:948-959）。
- 观测：`extra.dark_gift` = enabled/cost/uses_left/used_this_turn
  （observation.py:548-558, 697-699）；候选 cost=3（driver.py:846）。

**缺口（核心 P0）**
1. **P0 gift_id 不可观测**：`_pending_token` 用 `entity_token(tuple)` 把
   `(card_id, gift_id)` 序列化为 `card_id=随从id`，gift_id 只拼进 **`name="随从名|gift_id"`**
   （observation.py:304-323, 447-460），而 `EntityToken` 没有第二 id/文本字段
   （spec.py:127-149），且 `name` 是「仅调试与日志，策略不得依赖」（spec.py:148-149）。
   → 策略能看随从属性，**看不到选了哪个 Dark Gift**，与 live 决策信息严重不等价。
2. **P2 auto_choice 对 Dark Gift 只用「有 gift +0.5 分」的平局偏好**，不评估 gift 效果
   （driver.py:1073-1076）——仅在不可暂停阶段（见交互 6-缺口 2）影响自动结算质量。
3. **P2 饰品种类触发路径无 env 回归**：Ominous Stone/Wax Lance 在 on_bind、Maldraxxus Dagger 在
   SoT 触发；新回合的会由 ChoiceQueue 保留（game_env.py:858-865），但 `phase="choice"` 的
   kind=dark_gift 未任何 `tests/test_env_*.py` 覆盖。
4. 同一「二元组信息丢失」问题也命中 `quest_offer` 的 (quest_id, reward_id)（game.py:3934, 3949）
   与 `trinket_offer` 的 skip(None) 选项（game.py:5050-5052）——建议一次改造统一解决。

**建议修改（与交互 2 共用）**
- spec 升 v3：新增 `PendingChoiceOption`（或扩 `EntityToken`）：`card_id, secondary_id,
  label, cost, kind`；`PendingChoice.options` 改为该类型（保留 `EntityToken` 兼容入口）。
  序列化点：observation.py:447-460（dark_gift/quest_offer/trinket_offer/choose_one 分支）。
- 同步 policy encoder：`hsbg/policy/encoder.py:115-121, 589-591` 目前把 ZONE_CHOICE 实体按
  `EntityToken.card_id` 编码，需为 secondary_id 增加 vocab/数值特征；`Observation.version` +1
  （AGENTS §3 契约要求）。
- 若不改 spec：至少把 `gift_id` 写进 `Observation.extra["dark_gift"]["offer_gift_ids"]`
  （按选项下标），作为过渡方案。

**测试建议**
- 新文件/类 `tests/test_env_coverage.py::TestDarkGiftObservation`：
  1) turn>=3、gold>=3 构造 game → `driver.apply_action(USE_DARK_GIFT)` →
     `obs = env._observe()`；断言 `obs.phase=="choice"`、`kind=="dark_gift"`、
     每个 option 的 `secondary_id == game.pending_choices[0].options[i][1]`；
  2) 选不同 gift 后 minion 的附魔/属性差异可复现（同 seed）；
  3) 3 个选项两两可区分（secondary_id 不同）。

---

### 交互 5：英雄技能（含目标 / 多目标 / 第二技能槽）

**live 需要**：点英雄技能按钮（扣费/计次）；带目标技能进入目标选择；多目标技能连续选 N 个
（Vol'jin "Choose 2"）；异变/奖励可给第二技能槽（每技能次数独立）。证据：引擎
game.py:2079-2172（主/副槽、single/multi target），`docs/ENGINE_API.md:331`。

**env 现状（部分支持）**
- 动作：`ActionKind.HERO_POWER`（spec.py:81）；`_enumerate_hero_powers` 遍历
  `game.hero_power_ids(hero)`（主+副槽，game.py:2012-2031），复刻 available/uses_per_turn/
  uses_per_game/cost/target_count（driver.py:715-780）；apply 传 `target` 与 `power_id`
  （driver.py:999-1002）。
- 多目标：`target_count>1` 只生成 1 个无目标候选（候选数>=N 才发），引擎连续挂起
  `hero_power_target`（driver.py:749-762; game.py:2149-2172）→ choice 链完整表达组合，**不丢失**。
- 观测：`HeroToken`（observation.py:395-428）与 `extra.powers[]`（observation.py:508-545）含
  `power_id/cost/uses_left/passive/needs_target/target_count`。

**缺口**
1. **P1 单目标 6 变体上限**：见交互 1 缺口 2（driver.py:712, 770-776）；Maiev（酒馆 7）/
   Arcane Alteration（手牌 ≤10）会丢目标，且无 no-target choice 回退。
2. **P1 候选无法区分技能身份**：`CandidateAction` 无 `power_id`（spec.py:209-235），
   `ActionDescriptor.power_id` 未进入候选（driver.py:195-205）；两个「无需目标且同签名」的
   技能候选签名完全相同，`_resolve_action` 只匹配第一个（game_env.py:500-503），
   encoder 候选特征也不含 power（`hsbg/policy/encoder.py:700-726`）→ 第二技能槽经
   CandidateAction API **不可达**（整数下标 API 可达）。建议 spec 加 `power_id`（或
   `flags: Tuple[str,...]`，ENV_INTERFACE_GAPS A2.3 已提案）。
3. **P2 HeroToken 只暴露主技能**：`power_id/power_cost/power_usable` 取 `power_ids[0]`
   （observation.py:397-399），第二技能仅在 `extra.powers`；仅消费 HeroToken 的策略会漏副槽。
4. **P2 多目标候选的「两次选择」不在候选上标注**：`note="targets=2"` 只存在于
   `ActionDescriptor.note`（driver.py:759-761），`CandidateAction` 无此信息；策略无法从候选
   知道该动作会进入两次 choice。
5. **P2 未覆盖「目标域含 Hero/隐藏实体」**的技能（当前池内无；`_hero_power_target_ok`
   game.py:2241-2257 支持任意候选域）。

**测试建议**
- 已覆盖：`tests/test_env_coverage.py:258-294`（Vol'jin 双目标 choice 链）；
  `tests/test_env_actions.py:505-521`（主动技能候选可执行）。
- 待补：`test_second_hero_power_candidate_reachable`（构造 `_second_power_id` 双主动技能、
  两候选可区分）；`test_hero_power_more_than_6_targets`（Maiev + 7 酒馆随从，经选择步选中
  第 7 个）；`test_multi_target_note_not_exposed`（记录现状/改造后断言 flags）。

---

### 交互 6：三连奖励与发现 / 饰品选择（含任务 offer）

**live 需要**：三连合成后弹 Discover（tier+1，三选一）→ 选择并入手机；T6/T9 饰品商店三选一
（显示价格，可能买不起/跳过）；任务 T4 三对（任务+奖励）选一；各种 Discover（随从/酒馆法术/
英雄技能）。证据：`docs/LIVE_TO_SIM_GAP.md:56`（L04）、`:59`（L07）；
`docs/LIVE_AUTOMATION_PROTOCOL.md:181-184`。

**env 现状（通用 choice 支持）**
- 机制：所有 PendingChoice 都由 `phase="choice"` + `choose(option)` 表达（driver.py:935-940,
  948-959；game_env.py:666-728）；观测 `pending_choice.options` 为 `EntityToken`
  （observation.py:447-460）。
- 三连：`check_for_triple` → `_grant_triple_reward` → `Discover(kind="triple_reward")`
  （game.py:1378-1401; `hsrl2/actions/discover.py:118-207`）→ PendingChoice；若三连由智能体
  buy/play 触发，apply 后 `_drain_choices` 立即暴露 choice（game_env.py:452-460）。
- 饰品：T6/T9 在**新回合开始** `_begin_recruit_for` 内 `_offer_trinkets`
  （game.py:419-431, 4997-5052），turn 已 +1（game.py:2797-2801）→ ChoiceQueue 的
  `_hold` 条件 `game.turn > turn_before` 成立 → 保留为 choice（game_env.py:858-865）；
  选项为 CardDef + 末尾 `None`（跳过）（game.py:5050-5052），`EntityToken.cost` 含价格。
- 任务：T4 同理 `_offer_quests`（game.py:415-418, 3909-3950），新回合开始 → 保留。
- 自动结算兜底：`default_pick_index`（driver.py:1046-1089）按价值挑最大（choose_one/quest 选 0）。

**缺口**
1. **P1 零 env 回归**：`tests/test_env_*.py` 中 grep 不到 `triple_reward/discover/trinket_offer/
   quest_offer` 的用例（仅 `tests/test_env_coverage.py:499-520` 间接看 quest_progress；
   `scripts/audit_env_coverage.py:226-227` 只统计 choice_kinds，且 `GATE_KINDS`
   不含任何 choice 类，`audit_env_coverage.py:62-65`）。三连/饰品/发现是 live P0 操作
   （L04/L07），环境层无回归风险高。
2. **P1 非暂停阶段智能体选择被自动结算**：
   - `_run_end_recruit_phase` 内 `ChoiceQueue._hold` 只保留「新回合之后」的选择
     （game_env.py:858-861）；EoT 效果（game.py:2737-2747）与淘汰结算（game.py:2791,
     `_process_eliminations` 3136-3175）都在 turn+1 之前 → 智能体在这些时点的 Discover/
     Choose One 全部按启发式自动选，策略无法决策。
   - 具体卡例：Mr. Bigglesworth 被动「其他英雄死亡→Discover 其战团」
     （`batch_hero_passives2.py:817-884`，PendingChoice 在 HERO_ELIMINATED 回调内入队，
     game.py:3175）→ env 必自动结算。
   - 对手招募期间 `_drive_opponents` 每步 `_drain_all_choices`（game_env.py:838, 750-759），
     智能体因「对手动作」触发的选择同样被自动结算。
   - 战斗内选择是既定边界（ENV_INTERFACE_GAPS A7-1），但**淘汰/EoT/对手期**不应等同处理。
   - 建议：选择保留条件从「turn 变化」改为「选择创建阶段可决策」；`_drive_opponents` 改为
     `resolve_pending_choices(game, agent)` 保留智能体选择并中断回合推进（或至少记录 pending
     到下一次观测），需要 Lead 决定语义；短期可在 `info/stats` 记录 `agent_choice_autoresolved`。
3. **P2 trinket_offer 选项金币不足未过滤**：`enumerate_choice` 只给 option 下标
   （driver.py:935-940），候选无 cost；引擎 resolve 在金币不足时静默不购买
   （game.py:5036-5037）→ 会得到「选了但没买」的合法无效步；live UI 会禁用。建议二选一：
   候选带 cost 或 choice 前过滤不可负担选项。
4. **P2 `CHOICE_OPTION_MAX=5` 契约与实际不符**：Galakrond 技能 `galakrond_tavern` 的 options
   是酒馆全部随从（至多 7）（`batch_hero_combat3.py:1362,1399-1401`）；spec 常量 5
   （spec.py:35）导致 policy encoder 的 ZONE_CHOICE 布局只编码 5 个
   （`hsbg/policy/encoder.py:115-121,589-591`），第 6/7 个选项无法编码。建议 spec 提高为 7
   并升 version（或限制此类 choice 的 options 数）。
5. **P2 二元组语义丢失**：三连/发现本身选项是 card_id（可观测），但 `quest_offer` 的
   reward_id 只在 `name`（同交互 4 P0-2）；`trinket_replace`/`reward_replace` 等未测试。

**测试建议**
- 三连：同池 3 张同名卡受控构造（buy/buy/play 或直接 `check_for_triple`）→ 断言
  `phase="choice"`、`kind=="triple_reward"`、`choose` 后手牌 +1 且 tier 正确。
- 饰品：`env.game.turn=6` 后调用 `_begin_recruit_for(agent)` 或 `_offer_trinkets` →
  断言 choice 被保留（不是自动结算）、options 含 `None`、价格在 `EntityToken.cost`、
  选一个后 `hero.trinkets` +1 且金币扣减。
- 任务：T4 同上，断言 options 携带 quest/reward 二元组语义。
- EoT 选择：构造一个 EoT 触发 Discover 的饰品/随从 → 断言当前实现会
  `auto-resolve`（记录为已知缺口，改造后断言 `phase="choice"`）。
- 跨进程：`tests/test_env_coverage.py:676-701` 已测 VecEnv extra；补 choice 选项序列化 pickle。

---

### 交互 7：随从位置 / 换位（board reorder）

**live 需要**：招募阶段可把棋盘随从拖到任意槽位（重排/换位），位置决定战斗攻击顺序与
相邻效果（Cleave/Rally/相邻 buff）。证据：`docs/LIVE_TO_SIM_GAP.md:57`（L05：live
「随从换位/重排 未实现；引擎 position 参数存在，env 候选少」）；
`docs/LIVE_AUTOMATION_PROTOCOL.md:185`；引擎 `_update_positions` 维护 `ZONE_POSITION`
（game.py:5124-5126），战斗按 board 列表顺序（summon 插入 position，game.py:1403-1426）。

**env 现状（只支持「打出时插入位置」，不支持换位）**
- 打出位置：`CandidateAction.position`（spec.py:222-223；-1=最右），
  `_position_variants` 生成 -1 与 0..n-1（driver.py:420-422），apply 传给
  `game.play_minion(position=...)`（driver.py:976-984）。观测 board 元组顺序即槽位
  （observation.py:802-803; spec.py:257-258）。测试：`tests/test_env_actions.py:196-215`。
- **没有任何 reorder/move/swap 动作**：`ActionKind` 12 类中无对应项（spec.py:68-86）；
  `driver.enumerate_actions` 无此类枚举（driver.py:849-920）；`apply_action` 无此类分支
  （driver.py:962-1027）；`hsbg/env/spec.py` 的 `CandidateAction` 也无「目标槽位移动」表达
  （position 仅用于 play）。
- **引擎侧也没有公开重排 API**：只有内部 `_update_positions`（game.py:5124-5126）与
  `summon` 插入（game.py:1418-1421）、脚本私有 `hero.board.remove/insert`（如
  `batch_hero_actives.py:574-581` 的 Jandice 换位）。ENV_SPEC/AGENTS 禁止 env 直接篡改引擎
  棋盘（`docs/ENV_SPEC.md:147-150`「只使用引擎公开 API…不得直接篡改棋盘」）。

**缺口**
1. **P0 完全缺失换位动作**：训练/评测环境无法表达 live 每回合都可做的核心定位操作；
   策略只能在「打出瞬间」决定位置，无法在后续调整（卖掉/换位保护关键随从、调整 cleave 顺序）。
2. 需引擎新增公开 API（vendored 只读，必须走 AGENTS §1 的发动机变更流程）：
   建议 `Game.move_minion(hero, minion, position) -> bool`：
   校验 minion 在 board、position 0..len-1、不触发 on_summon、更新 `ZONE_POSITION`
   （`_update_positions`）、必要时 fire 轻量事件；返回合法性。
3. env 侧配套：spec 加 `ActionKind.MOVE_MINION`（升 Observation.version）；driver 枚举
   「每个 board 随从 × 每个目标槽位（排除原槽位）」或交换对（2×C(7,2)≈42 个 → 会挤占
   CANDIDATE_MAX，需优先级/预算策略，参考 `_trim_tail_preserving` driver.py:783-815）；
   apply 分支；observation 无需改（board 顺序已被观测）。
4. 测试：`tests/test_env_actions.py::test_move_minion_changes_board_order`（枚举 + apply +
   ZONE_POSITION/board 顺序一致 + 非法位置被拒）；引擎回归测试需加在 `hsrl2/tests/`
   并保持全绿（AGENTS §1）；策略 encoder 无需改字段（board 顺序已有 slot 特征）。

---

## 3. 总表：交互 / ActionKind / 目标字段 / 观测字段 / 状态

| # | 交互 | ActionKind | 目标字段（动作） | 观测字段 | 状态 |
|---|------|-----------|-----------------|----------|------|
| 1a | 战吼目标 | `PLAY_MINION` | `tgt_zone/tgt_slot`（+ `position`） | `hand[].keywords=battlecry`、`tgt_*`、choice options | ✅ 支持（裁剪边界 P2/P1） |
| 1b | 法术目标 | `PLAY_SPELL` | `tgt_zone/tgt_slot` | `hand[]`、`tgt_*`、`pending_choice(kind=spell_target)` | ⚠️ 部分（无 choice 回退 P1） |
| 1c | 技能目标（单） | `HERO_POWER` | `tgt_zone/tgt_slot` | `hero.power_*`、`extra.powers`、`tgt_*` | ⚠️ 部分（6 上限 P1） |
| 1d | 技能目标（多） | `HERO_POWER` | 无（choice 链） | `pending_choice(kind=hero_power_target)` | ✅ 支持（候选无 N 标注 P2） |
| 1e | 磁力吸附 | `PLAY_MINION` | `tgt_zone/tgt_slot`（宿主） | `keywords=magnetic`、宿主槽位 | ⚠️ 部分（普通打出丢失、无 flag P1/P2） |
| 2 | 抉择 Choose One | `PLAY_MINION`/`PLAY_SPELL` + `CHOOSE` | 无（打出时）；嵌套 `battlecry_target` | `pending_choice(kind=choose_one)`、options | ⚠️ 支持但选项语义丢失（P1） |
| 3 | ACTIVATE | `ACTIVATE` + `CHOOSE` | 无（目标经 `activate_target` choice） | `keywords=activate`、`extra.board_states[].activate_used_this_turn`、候选 `cost` | ✅ 支持主路径（落空候选 P2、无测试 P1） |
| 4 | Dark Gift（购买/选择） | `USE_DARK_GIFT` + `CHOOSE` | 无（选项即目标） | `pending_choice(kind=dark_gift)`、`extra.dark_gift` | ⚠️ 动作支持；**gift 不可观测 P0** |
| 5 | 英雄技能（主/副槽） | `HERO_POWER` | 单目标 `tgt_*`；多目标 choice | `hero.power_*`（仅主）、`extra.powers[]` | ⚠️ 部分（身份 P1、6 上限 P1、副槽观测 P2） |
| 6a | 三连奖励 Discover | `CHOOSE` | 无（选项下标） | `pending_choice(kind=triple_reward)`、options | ✅ 机制支持（无测试 P1、非暂停期自动结算 P1） |
| 6b | 饰品商店 | `CHOOSE` | 无（选项下标） | `pending_choice(kind=trinket_offer)`、`trinkets`、option cost | ✅ 机制支持（可买性/测试 P2/P1） |
| 6c | 其他 Discover（随从/法术/技能） | `CHOOSE` | 无 | `pending_choice(kind=discover_*)`、options | ✅ 机制支持（无测试 P1） |
| 6d | 任务 offer | `CHOOSE` | 无 | `pending_choice(kind=quest_offer)`、`extra.quest*` | ⚠️ 二元组语义丢失 P2 |
| 7a | 打出位置 | `PLAY_MINION` | `position`（-1/0..n） | `board[]` 顺序 | ✅ 支持（tests/test_env_actions.py:196-215） |
| 7b | 棋盘换位/重排 | **无** | **无** | board 顺序（可观测但不可修改） | ❌ **不支持（P0）** |

---

## 4. 缺口清单与优先级

### P0（阻断真实交互等价 / 训练动作空间完整性）
| ID | 缺口 | 证据 | 建议 |
|----|------|------|------|
| P0-1 | 无棋盘换位/重排动作；引擎亦无公开 API | spec.py:68-86；driver.py:849-1027；game.py:5124-5126；LIVE_TO_SIM_GAP.md:57 | 引擎加 `move_minion` + spec 加 `ActionKind.MOVE_MINION` + driver 枚举/apply + 测试 |
| P0-2 | Dark Gift（及 quest_offer 等二元组）选项的第二 id 只存在于 `name` 调试字段，策略不可依赖 | observation.py:304-323, 447-460；spec.py:127-149,198-206；game.py:2294,2313,3934 | spec v3 增 `PendingChoiceOption{card_id,secondary_id,label,cost}`（或扩 EntityToken）；encoder/obs 同步 |
| P0-3 | 非暂停阶段（EoT/淘汰/对手招募期）智能体 PendingChoice 被自动结算，无法决策 | game_env.py:750-759,858-861；driver.py:1140-1192；game.py:2737-2747,2791,3136-3175；batch_hero_passives2.py:879-881 | 保留 agent 选择并作为 choice 暴露（或至少统计+文档化）；改 `_hold` 判据为「选择产生阶段可决策」 |

### P1（关键交互部分不可达 / 观测语义不完整 / 无回归）
| ID | 缺口 | 证据 |
|----|------|------|
| P1-1 | 英雄技能单目标 6 变体硬上限（Maiev 7 / Arcane Alteration 10 目标丢失），无 no-target choice 回退 | driver.py:712,770-776；batch_hero_actives.py:156-157,365-366,484-485,608-609；game.py:2139-2172 |
| P1-2 | 定向法术/被裁剪战吼无 choice 回退（目标不可达） | driver.py:546-566,587-607；game.py:1138-1152,1531-1544 |
| P1-3 | 技能候选无 `power_id`；磁力候选无 `magnetic`；同签名候选不可区分，`_resolve_action` 取第一个 | spec.py:209-235；driver.py:195-205,534-541；game_env.py:500-503；encoder.py:700-726 |
| P1-4 | Choose One 的 branch label/prompt 不进入观测（options 仅 key） | observation.py:292-303,447-460；game.py:1130-1134,1527-1529；spec.py:198-206 |
| P1-5 | 三连/发现/饰品/任务/targeted-activate **零 env 回归测试**；审计门禁不含 choice 类 | grep `tests/test_env_*.py`；audit_env_coverage.py:62-65,226-227；tests/test_env_coverage.py:870-1018 |
| P1-6 | 非暂停期选择自动结算（P0-3 的具体影响面）：Bigglesworth 淘汰 Discover、EoT Discover、对手期触发选择 | game_env.py:750-759,838,858-861；game.py:3175；batch_hero_passives2.py:817-884 |

### P2（语义/契约/边界）
| ID | 缺口 | 证据 |
|----|------|------|
| P2-1 | 磁力+战吼卡只枚举吸附，普通打出（触发战吼/占格）候选丢失 | driver.py:534-541 |
| P2-2 | `CHOICE_OPTION_MAX=5` 与实际 choice 选项数（Galakrond 至多 7）不符，encoder 只编码 5 | spec.py:35；encoder.py:115-121,589-591；batch_hero_combat3.py:1362,1399-1401 |
| P2-3 | trinket_offer 候选不带 cost、不过滤买不起选项；引擎静默不购买 | driver.py:935-940；game.py:5033-5039 |
| P2-4 | ACTIVATE 可能枚举「必然落空」候选（引擎先扣费置 used） | driver.py:818-831；game.py:1908-1922；minions.py:293-294 |
| P2-5 | `choose_one+needs_target` 组合 latent（driver 只在无 choose 时处理目标） | driver.py:546；game.py:1126-1135；batch_misc.py:52-54 |
| P2-6 | 观测无实体 `activate_cost`；`board_states` 未进入策略编码器 | observation.py:596-618；encoder.py:657-682 |
| P2-7 | spec/文档卫生：`EnvConfig.max_steps` 重复字段；`ENV_SPEC` 写 version=1；spec 注释引用不存在的 `hsbg/env/actions.py` | spec.py:374,381；spec.py:71；docs/ENV_SPEC.md:38 vs :55 |
| P2-8 | 手牌预算裁剪 target×position 变体（CANDIDATE_MAX=64） | driver.py:631-668,897-905 |

---

## 5. 测试建议汇总（按优先级）

| 优先级 | 测试（建议位置/名称） | 断言要点 |
|--------|------------------------|----------|
| P0 | `tests/test_env_coverage.py::TestReorder`（需引擎 API 后） | 枚举换位候选 → apply → board 顺序/ZONE_POSITION 一致；非法位置被拒 |
| P0 | `tests/test_env_coverage.py::TestDarkGiftObservation` | choice 选项带 secondary_id(gift)；不同 gift 可区分；选择生效 |
| P0 | `tests/test_env_coverage.py::TestChoicePauseBoundary` | EoT/淘汰/对手期 agent 选择保留为 choice（改造后）或自动结算计数可见（现状） |
| P1 | `tests/test_env_actions.py::test_hero_power_targets_over_6` | 7/10 目标全可达（choice 回退） |
| P1 | `tests/test_env_actions.py::test_targeted_spell_choice_fallback` | 目标被裁/不可寻址时仍可施放并选择 |
| P1 | `tests/test_env_actions.py::test_candidate_identity_fields` | 双技能槽/磁力普通打出候选可区分 |
| P1 | `tests/test_env_coverage.py::TestTripleDiscoverTrinket` | 三连→choice→choose→手牌；饰品 offer 保留→选择→trinkets+金币；任务 offer |
| P1 | `tests/test_env_coverage.py::TestActivateTarget` | Kelp Keeper 激活→choice→choose→战吼生效；0/2 费与每回合一次 |
| P2 | `tests/test_env_observation.py::test_choose_one_label` | label/prompt 出现在观测 |
| P2 | `tests/test_env_coverage.py::TestChoiceOptionMax` | 选项 >5 时编码/候选仍可决策 |
| P2 | `tests/test_env_actions.py::test_trinket_offer_affordability` | 买不起选项过滤或候选带 cost |
| P2 | 审计器：`scripts/audit_env_coverage.py` 增 choice 类门禁 | 20 局内 `triple_reward/trinket_offer/discover_*` 与 targeted activate 计数 >0 |

**回归门槛**（AGENTS §6）：改 `hsbg/env/**` 后 `python -m pytest tests -q` 全绿；
改引擎需 `python -m pytest hsrl2/tests -q` 全绿；改 spec/Choice 语义须升
`Observation.version` 并同步 `docs/ENV_SPEC.md` 与 `hsbg/policy/encoder.py`。

---

## 6. 证据索引（file:line）

**契约/观测**
- `hsbg/env/spec.py:30-39` 槽位上限与 `CHOICE_OPTION_MAX=5`；`:68-86` ActionKind（无换位）；
  `:127-149` EntityToken（无 secondary/label/text）；`:198-206` PendingChoice(prompt 恒空)；
  `:209-235` CandidateAction（无 power_id/flags）；`:251` version=2；
  `:358-384` EnvConfig（`max_steps` 重复 :374/:381）；`:71` 引用不存在的 `hsbg/env/actions.py`。
- `hsbg/env/observation.py:292-323` str/tuple 选项序列化（gift/reward 只进 name）；
  `:395-428` HeroToken 只取 power_ids[0]；`:447-460` `_pending_token`；
  `:508-545` `extra.powers`；`:548-558` `extra.dark_gift`；`:596-618` board_states；
  `:643-769` build_extra_state；`:771-849` build_observation。
- `hsbg/env/driver.py:137-159` Zones；`:191` magnetic 字段；`:209-235` ActionDescriptor→Candidate；
  `:420-422` position 变体；`:425-486` 目标候选求值；`:488-569` play_minion 变体；
  `:573-608` play_spell 变体（无 choice 回退）；`:631-668` 手牌预算；
  `:712` 单来源目标上限 6；`:715-780` 英雄技能枚举；`:818-831` Activate 枚举；
  `:834-846` Dark Gift 枚举；`:849-920` enumerate_actions；`:935-959` choice 枚举/结算；
  `:962-1027` apply_action；`:1046-1089` default_pick_index；`:1092-1192` FIFO/ChoiceQueue。
- `hsbg/env/game_env.py:452-468` 动作后 drain+observe；`:477-503` 动作解析（签名首匹配）；
  `:666-728` `_observe`；`:734-759` drain choices（agent 暴露 vs 全自动）；
  `:808-839` 对手驱动（`:838` drain_all）；`:845-882` end_recruit_phase + ChoiceQueue
  （`:858-861` hold 判据）；`:884-961` `_end_turn_step`。

**引擎**
- `hsrl2/game.py:340-431` 回合开始（任务/饰品 offer、SoT）；`:1068-1154` play_minion
  （choose_one :1126-1135；battlecry_target :1138-1152）；`:1378-1401` 三连奖励 Discover；
  `:1403-1442` summon/位置；`:1491-1544` play_spell（choose_one :1516-1530；target :1531-1544）；
  `:1908-1922` use_activate（无 target）；`:2079-2172` use_hero_power（多目标链 :2137-2172）；
  `:2261-2315` use_dark_gift（(card,gift) :2290-2314）；`:2702-2801` end_recruit_phase
  （EoT :2737-2747；淘汰 :2791；turn+1 :2797；begin recruit :2801）；
  `:3136-3175` eliminations/hero_eliminated；`:3909-3950` quest offer；
  `:4997-5052` trinket offer；`:5115-5126` run_actions/_update_positions（无公开 reorder）。
- `hsrl2/actions/discover.py:118-207` Discover → PendingChoice；
  `hsrl2/scripts/minions.py:278-321` Activate→activate_target（无候选落空）；
  `hsrl2/scripts/batches/batch_misc.py:52-54,1105-1174` choose_one+target 缺口/Scarab 自建；
  `batch_spells4.py:13-17,61-69` 法术 choose_one 自建；`batch_hero_actives.py:156-157,365-366,
  484-485,608-609` 技能目标域 tavern/hand；`batch_hero_combat3.py:1362,1399-1401` Galakrond
  7 选项；`batch_hero_passives2.py:817-884` Bigglesworth 淘汰 Discover；
  `batch_trinkets22.py:300-386` 饰品 SoT dark_gift；`batch_trinkets20.py:426-470` 饰品 on_bind dark_gift。

**测试/审计/文档**
- `tests/test_env_actions.py:72-84` 候选签名唯一（注：双主动技能会破此不变量）；
  `:196-215` 打出位置；`:428-450` FIFO；`:488-503` Dark Gift 动作；`:505-521` 英雄技能。
- `tests/test_env_coverage.py:150-197` 定向法术；`:198-257` 定向战吼；`:258-294` 双目标；
  `:296-354` Choose One；`:355-389` 磁力；`:390-460` 槽位；`:565-701` obs v2 / VecEnv；
  `:702-869` 终止契约；`:870-1018` 覆盖门禁（合成构造，含 activate/dark_gift 出现性）。
- `scripts/audit_env_coverage.py:62-65` GATE_KINDS（不含 choice 类）；`:226-227` choice_kinds 统计。
- `docs/ENV_SPEC.md:38` vs `:55` version 不一致；`:80-95` 动作表（无换位；目标组合语义
  `:97-99`）；`docs/ENV_INTERFACE_GAPS.md:397-413` A7 已记录边界（战斗选择自动、候选无
  power_id/magnetic/note、64 上限）；`docs/LIVE_TO_SIM_GAP.md:52-66`（L04/L05/L06）；
  `docs/LIVE_AUTOMATION_PROTOCOL.md:167-186` 动作矩阵；`docs/ENGINE_API.md:331,1152,1441`。
- 数据：`data/bg_pool_minions.json:1048,3229-3230`（activate 卡）；
  `data/bg_dark_gifts.json`（43 个 Dark Gift）。

---

## 7. 与既有审计的关系 / 刻意不重复

- `docs/ENV_INTERFACE_GAPS.md` 已详述并修复：定向战吼/法术枚举（A1.2/A1.3）、双目标技能
  （A1.4）、Choose One 双分支可达（A1.5）、磁力宿主判定（A1.6）、双 pay 购买（A1.8）、
  obs v2 extra（A2）、CANDIDATE_MAX 裁剪（A3）、终止契约（A4.1）。本文不重复其证据，
  只引用结论并聚焦**真实交互语义**（配对 id、换位、非暂停期决策、choice 测试）。
- 已记录且本文认同的边界（不列为缺口）：战斗内 PendingChoice 自动结算（A7-1）；
  引擎内部实体/隐藏区目标不可寻址（A7-2）；`CandidateAction` 缺 flags（A7-3，本文升级为
  P1-3 因为影响 Dark Gift 之外的技能/磁力可达性）；64 候选上限（A7-4，本文仅 P2-8 裁剪问题）。
- 本文**未做**运行验证（任务要求只读）：所有「支持/不支持」判断来自代码路径与现有测试；
  建议的测试均未执行，需在 Lead 批准后在非只读会话中落地并跑 `pytest tests -q`。
