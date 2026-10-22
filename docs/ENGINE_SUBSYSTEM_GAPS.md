# 引擎子系统缺口台账（G-H1 剩余 blocker）

> 来源：`docs/AUDIT_ENGINE_MECHANICS.md` G-H1（P0：17/118 英雄主技能无脚本）。
> 本文件记录 2026-10-22 批次 `batch_hero_powers_37x` 落地后的**剩余缺口**：
> 已实现并注册 6 个主技能，11 个主技能保持未注册（二态铁律：CORRECT 或
> DEFERRED，禁止"注册但空转"）。
>
> 维护者：card-script-builder（task-3）。下游读者：Lead（排期）、
> engine 侧（最小原语）、audit（覆盖率分母）。

## 1. 已收口（2026-10-22）

| 英雄 | 主技能 | 实现要点 |
|---|---|---|
| Drest'agath | `BG36_HERO_000p` Incubate | 主动（cost 1）：弃手牌 1 张 → 随机 Aberration 入手；`needs_target + target_candidates=hand` |
| Kith'ix | `BG36_HERO_002p` Dark Ritual | 主动（cost 2）：随机 2 随从入手 + 配对监听 `card_played` → 打出一张弃另一张 |
| Loh | `BG33_HERO_001p_ALT` Heroic Inspiration | 被动：`BEFORE_ATTACK` 友方计数 15 → 无来源 Triple Reward |
| Guff Runetotem | `BG20_HERO_242p` Natural Balance | 被动：购买 Tier 累计 20 → 无来源 Triple Reward |
| Genn | `BG35_HERO_001p` King of Duality | 被动：第 4 回合连续两次 `discover_hero_power`，替换主槽 + 写入第二槽 |
| Sire Denathrius | `BG24_HERO_100p` Whodunit? | 被动：开局 `quest_offer` 二选一（池门禁 `quest_offer_pool()` + 抑制第 4 回合标准 offer） |

**无来源 Triple Reward 档位裁定（记录边界）**：wiki 卡页无 Notes；Triple
Reward 法术文本为动态 `Tier @`。本项目按自然语言解读取**本人当前酒馆
等级**（封顶 `max_tavern_tier`），复用引擎 `Discover(kind="triple_reward")`
的池语义。若官方后续明确其他规则，只需改
`batch_hero_powers_37x._detached_triple_reward` 一处。

## 2. 剩余 11 个主技能 blocker（按优先级）

| 优先级 | 英雄 / 主技能 | 缺的子系统 / 最小原语 | 说明 |
|---|---|---|---|
| P0 | Master Nguyen `BG20_HERO_202p` Power of the Storm | **hero 级技能 rebind/unbind**：监听器随技能身份注销 + hero tag 回滚 | 每回合从 2 个新技能中选 1；引擎 `replace_hero_power` 可换 `_active_power_id`，但被替换被动技能的 `on_bind` 监听器/英雄 tag 常驻 → 轮换即残留（Millhouse 费用覆写 / Patchwerk 血量等）。候选池 helper 已就绪（`batch_hero_remaining._draftable_hero_power_ids`）。最小原语：`Game.unwire_hero_power(hero, power_id)`（按身份注销 listener + 恢复 hero tag 快照）+ `wire_hero_power_on_bind` 的对称清理。 |
| P1 | Jim Raynor `BG31_HERO_801p` Lift Off | **Battlecruiser Upgrade 子系统**：10 张 upgrade（`BG31_HERO_801pta..j`，card_type 42）无脚本 + 馆内注入/附着协议 | token `BG31_HERO_801pt`（2/2）在库；"Start the game with a 2/2 Battlecruiser" 可用 `create_minion + summon`；"Whenever the Tavern is Refreshed, add a Bonus Upgrade **to it**" 需要：① 馆内注入 spell 实体（`Game.add_tavern_entity` 类入口可否容纳 card_type 42？）② Upgrade 卡脚本与"购买即附着到 Battlecruiser"协议。最小原语：`Game.inject_tavern_card(hero, card_id)` + upgrade 脚本批（可解析文本的 9 类效果）。 |
| P1 | Kerrigan `BG31_HERO_811p` Spawning Pool（+811p2/p3） | **Zerg 分级解锁 + Larva morph 子系统** | "Unlock Tier 2 Zerg. Costs (1) less each turn." 的解锁状态模型 + `BG31_HERO_811t` Larva "At the start of each turn, choose a Zerg minion to morph into. It keeps stats and enchantments." 的 morph 协议（保持属性/附魔/变形池 = 已解锁档 Zerg）；数据侧 Zerg 全家 22 张已入库但无池/档位字段。 |
| P1 | Murozond `BG34_HERO_000p` / Morchie `BG34_HERO_004p` | **Timewarp 子系统**（Major/Minor 商店 + Chronum 账本） | 数据 373 项提到 Timewarp，但无 Major/Minor 成员标记与 Chronum 字段；引擎无 Timewarp 商店/回合钩子。最小原语：生成器导出 timewarp 成员/档位字段 + `Game.open_timewarp(hero, kind)`。 |
| P1 | Akazamzarak `TB_BaconShop_HP_020` Prestidigitation | **Secrets 子系统**（BG 无 Secret 区/触发协议） | 16 张 `TB_Bacon_Secrets_*` 在库，无英雄区接线；"Choose a Secret. Put it into the battlefield." 需要秘密区 + 触发读取点（攻击宣言 / 随从死亡 / 回合开始 / 致命伤害预防等）。 |
| P2 | Silas Darkmoon `TB_BaconShop_HP_101` Come One, Come All! | **Darkmoon Ticket token + 馆内 Ticket 计数 + 集 3 发现** | CardDB 内无 Ticket token 定义（仅 buddy 引用）；需 token 数据 + 馆内实体计数 + 集齐触发 Discover。 |
| P2 | Tickatus `TB_BaconShop_HP_106` Prize Wall | **Darkmoon Prize 卡池 + Tier 映射** | CardDB 无 "Darkmoon Prize" 候选池数据（`BGS_Treasures_*` 无 Tier N 字段）；"Every 4 turns Discover a Darkmoon Prize" 的候选/档位无权威。 |
| P2 | Cariel Roame `BG21_HERO_000p` Conviction | **战后"选择强化"协议**的官方枚举/叠加规则 | 主动面（1 个随机友方 +1/+1）可精确实现；被动面"After each combat, choose an improvement"的改进选项集与叠加规则无官方 Notes（wiki `derived_choiceCardDbfIds` 给 3 张 token：United Stance / Offensive Stance / Defensive Stance，但无每战必选/可否重复的说明）。 |
| P2 | Galewing `BG20_HERO_283p` Dungar's Gryphon | **flightpath 完成时点/回退协议** | 三条航线 token（`BG20_HERO_283p_t1..t3`：Westfall/Ironforge/Eastern Plaguelands，延迟 1/2/3 回合奖励）文本清晰；缺 "Complete it" 时点（第 T+N 回合开始/结束）与完成后回退可选（同 rebind 依赖）的官方 Notes。 |
| P3 | Professor Putricide `BG25_HERO_100p` Build-An-Undead | **Craft 多步合成子系统** | 两池各三选一（种族 + 关键词/属性）+ 属性/文本合并 + Reborn 与 Venomous/Poisonous 互斥；引擎无"拼接实体"原语。 |

## 3. 其他同轮暴露的脚本/引擎缺口（非 G-H1）

1. **`Game.cast_spell_effect` 无 choose 通道**（P2）：效果施法（"Cast X"/
   复制再施放）调用脚本 `on_play` 时只传 `{"target": ...}`，不传
   `choose`——Choose One 法术迁移到引擎 `choose_options` 后，走效果施法
   路径会丢分支。已在 Lovely Locket（`batch_trinkets20`）以脚本层补
   `choose_one` 窗绕过；通用解 = `cast_spell_effect(..., choose=...)` 或
   对 `choose_options` 脚本自动挂选择窗。
2. **`Cast X` 通用入口不处理 `needs_target` 的 choose 时序**：与上一条同族；
   建议引擎抽"效果施法 + 抉择/目标两阶段"统一入口（G-C1 已覆盖手牌路径）。
3. **数据生成器未导出 `choose_one` 权威字段**（G-C5 数据方案 b）：本批以
   统一判定函数收口（`hsrl2/scripts/choose_one_authority.py`），数据
   `choose_one` 标志仍是文本兜底（9 误报 + 3 漏报，audit 输出可见）。
   若未来改 `tools/generate_bg_data.py`（需 Lead 批准），应改为导出
   CardDefs `CHOOSE_ONE` tag 或标题正则字段。
4. **`hsebg/live` 无英雄技能执行**（`docs/LIVE_TO_SIM_GAP.md` L02）：
   sim 侧覆盖率提升后，live 侧仍需实现 HERO_POWER 操作（live-automator scope）。

## 4. 复现

```powershell
# 覆盖率审计（choose_one 权威口径 + 池卡/饰品脚本缺口）
python scripts/audit_mechanism_coverage.py --out runs/audit/mechanism_coverage.json

# 本批行为测试
python -m pytest hsrl2/tests/test_batch_hero_powers_37x.py -o addopts="" -q
python -m pytest hsrl2/tests/test_batch_choose_one_base.py -o addopts="" -q
python -m pytest hsrl2/tests -o addopts="" -q
```
