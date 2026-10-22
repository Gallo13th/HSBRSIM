"""批次 hero_rewards_final — 英雄技能 + 任务奖励混合终批（作业单 2026-09-02）。

作业范围（**REGISTRY ∖ 数据自算**，非记忆——探针见文末"范围自算"节）:
  A) 全部未注册的 `CardType.HERO_POWER`（英雄 Tag380 绑定全集 116 中的
     15 张——audit_card_registry_v2 `_hero_power_ids` 同一定义域）
  B) 全部未注册的 `CardType.BACON_QUEST_REWARD`（73 张中的 9 张）
铁律: **CORRECT 或 DEFERRED，没有第三态**（SOP §6b）——语义/时机/载荷
无权威证据的一律撤注册（保持未注册）并在本文档写 Status / Dependency /
Implementation path。

查证方式（2026-09-02）: hsdata/CardDefs.xml（Tag380 绑定 + COST +
TAG_SCRIPT_DATA_NUM_* + ReferencedTag + BACON_* 专用 tag 逐条核对）;
hearthstone.wiki.gg 卡片/英雄页 `?action=raw`（custom_mechanicTags /
custom_refTags / custom_hiddenTags / derived_choiceCardDbfIds /
derived_relatedCardDbfIds / article_notes / Patch changes）;
data/*.json 数据链（evolution_card_id / spellcraft_id）;
RULES §6.20（额外触发）/ §9.5（第二技能槽）/ §11.6（任务难度缺口）。

═══════════════════════════════════════════════════════════════════════
CORRECT（2 张，本批注册）
═══════════════════════════════════════════════════════════════════════
  BG24_Reward_113 Ritual Dagger — "After a friendly **Deathrattle** minion
      dies, give it +5/+5 permanently."
      实现: on_bind 注册 COMBAT_END 监听; 战斗结束（棋盘已复原）时对
      本场 `game.combat_death_log` 中**本方**死亡且带亡语、且已随复原
      回到棋盘的实体逐一 Buff +5/+5（永久）。依据: XML ReferencedTag
      DEATHRATTLE + wiki mechanicTags "Permanent attribute" +
      hiddenTags "Triggered effect - after a friendly minion dies"。
      同族先例: 任务奖励 R138 "After each combat, get a plain copy of
      the last friendly minion that died" 亦走 COMBAT_END +
      combat_death_log（batch_quest_rewards），本批沿用同一数据源。
      数值 +5/+5 为文本字面量（CardDef.num(0..3) 全 None——SOP §3）。
  BG33_Reward_011 Magicfin Relic — "At the start of each turn, get a
      1/1 Murloc. **Discover** a Tavern spell to teach it."
      实现: start_of_turn（引擎对 `hero.quest_rewards` 逐一致
      `run_script_hook(reward, "start_of_turn")`）→ create_minion
      Magicfin Apprentice token（`BG33_890t`，1/1 Murloc，非池不占池）
      → pending_hand_add（"get"= 入手，满手排队 RULES §3.3）→ 真
      Discover 一个 Tavern spell（3 选 1，候选 = 池法术 tier ≤ 酒馆
      等级，预留语义）→ 选定即 `token._taught_spell_id = pick`
      （"teach" 数据通道 = batch_final_unfreeze 已裁定的
      MagicfinApprenticeScript 战吼消费点，2026-08-23 wiki 双页核实）。
      依据: wiki 页 Available（当前在池）+ XML BACON_SUBSET_MURLOC=1 /
      DISCOVER=1 / USE_DISCOVER_VISUALS=1; 同文案的 Magicfin
      Mycologist/Sticker 均生成同一 token（"get a 1/1 Murloc and teach
      it that spell"）。

═══════════════════════════════════════════════════════════════════════
DEFERRED 台账 — 英雄技能 15 张（不注册; Status / Dependency / Path）
═══════════════════════════════════════════════════════════════════════
  1. BG20_HERO_202p Master Nguyen "Power of the Storm" — "At the start of
     every turn, choose from 2 new Hero Powers."
     Status: DEFERRED。
     Dependency: **hero 级技能 rebind/unbind 协议**。候选池已就绪
     （`batch_hero_remaining._draftable_hero_power_ids`，Finley 先例），
     `replace_hero_power` 也能换 `_active_power_id`，但引擎无 hero 级
     **注销**：被替换被动技能的 `on_bind` 监听器与 hero tag 常驻
     （Millhouse 费用覆写 / Patchwerk 血量 / Skilled Bartender 升级费），
     每回合轮换 = 残留被动无限累积（第三态）。
     Path: 主线实现「技能身份 → 监听器（events.unregister_owner 的
     power 变体）+ hero tag 回滚」后，on_bind 注册 TURN_START → rng
     抽 2 个互异候选 → PendingChoice → 选中 `replace_hero_power`。
  2. BG20_HERO_242p Guff Runetotem "Natural Balance" — "After you buy 20
     Tiers' worth of cards, get a Triple Reward. (@ left!)"
     Status: DEFERRED。num(0)=20（XML TAG_SCRIPT_DATA_NUM_1）。
     Dependency: **无来源卡（脱锚）Triple Reward 的档位裁定 + 授予
     原语**。购买 tier 累加可经 MINION_BOUGHT 监听表达（`d.tech_level`
     求和 / 阈值 num(0)），但引擎 `_grant_triple_reward(hero, golden)`
     锚定**金色实体**（tier = 被三连卡 tier+1，RULES §10.3）; 英雄技能
     场景没有来源卡，wiki Triple Reward 页与 patch notes 均未给动态
     tier 规则（`{@}` 无数据权威）→ 实现即猜。
     Path: 主线裁定脱锚 Triple Reward 的档位（疑似 = 当前酒馆等级）并
     提供 `_grant_triple_reward_for_tier(hero, tier)` 后解冻。
  3. BG20_HERO_283p Galewing "Dungar's Gryphon"（+ t1 Westfall /
     t2 Ironforge / t3 Eastern Plaguelands，wiki
     derived_choiceCardDbfIds = 75704/75705/75706 实证三选一）
     Status: DEFERRED。
     Dependency: (a) 航线**完成时点**无权威（"In N turns" 是第 T+N
     回合开始/结束）; (b) 完成后回退到基础技能"可再选"——Galewing 页
     `article_notes` 已证实「Chosen Hero Power triggers at the start of
     the player's turn, then it can be chosen again」，但回退仍需
     hero 级 rebind/unbind（同 Nguyen）; (c) t1 "a random **1-Cost**
     Tavern spell" 的 "1-Cost" 是法术金币费还是 tier 无裁定。
     Path: 时机/成本口径裁定 + rebind 协议（同 1）。
  4. BG21_HERO_000p Cariel Roame "Conviction" — "Give {2} random
     friendly minions +{0}/+{1}. **Passive:** After each combat, choose
     an improvement."
     Status: DEFERRED。num(0)=num(1)=num(2)=1（三段 SCRIPT_DATA）;
     三张 improvement 抉择卡 = BG21_HERO_000p_t1 United Stance /
     BG21_HERO_000_Buddyt Offensive Stance / BG21_HERO_000_Buddyt2
     Defensive Stance（wiki derived_choiceCardDbfIds 104923/101567/
     101575）。
     Dependency: **战后"选择强化"协议**无权威——wiki mechanicTags 标
     "Passive Hero Power" 而文本首句是一次性 give（主动面）; 强化是否
     每场战斗必选、可否重复/叠加、拒绝后如何，均无 Notes。按 SOP §6b
     第 4 步撤注册。
     Path: 官方/实测证据确定战后选择协议后，on_bind 注册 COMBAT_END
     → PendingChoice(3 强化) → 写 hero 级强化计数（+1 攻/+1 血/额外
     一个目标）; 主动面 "Give 1 random friendly +1/+1" 走 hero_power。
  5. BG24_HERO_100p Sire Denathrius "Whodunit?" — "At the start of the
     game, choose one of two **Quests**."
     Status: DEFERRED（SOP §12 第 14 条: 机制就绪 ≠ 载荷可兑现）。
     Dependency: **任务卡数据缺口**——`BG24_Quest_*` 17 张全部
     DEFERRED（任务难度 = 任务基础值 × 种族修正 × 奖励基础值 × 奖励
     种族修正 × 护甲等级; CardDefs 仅 1/66 有奖励基础值），见 RULES
     §11.6。选到的任务永不推进 → 真实对局空转。
     Path: 任务难度权威落地（`docs/agents/ENGINE_BACKLOG.md`）后随
     任务批一起注册（quest_offer 协议已由 `Game._offer_quests` 就绪）。
  6. BG25_HERO_100p Professor Putricide "Build-An-Undead" — "Craft a
     custom Undead. ({0} Creations left!)"
     Status: DEFERRED。num(0)=3（每局次数）/ cost=3。
     Dependency: **Craft 多步合成子系统**未建（两池各三选一、属性与
     文本合并、Reborn 与 Venomous/Poisonous 互斥规则——wiki
     article_notes 已载明规则，但引擎无"拼接实体"原语）。
     Path: 主线实现 Craft 协议（两次 PendingChoice + 属性/文本合并
     + 关键词互斥）后解冻; `uses_per_game=num(0)`。
  7. BG31_HERO_801p Jim Raynor "Lift Off" — "Start the game with a 2/2
     Battlecruiser. Whenever the Tavern is **Refreshed**, add a
     Battlecruiser Upgrade to it."
     Status: DEFERRED（载荷未就绪）。
     Dependency: 10 张 Battlecruiser Upgrade（`BG31_HERO_801pta..j`，
     card_type 42）全部无脚本，且含关键词赋予 / Yamato / Rally 叠加
     语义; 无升级卡脚本 → 每次刷新注入空转卡。
     Path: 先迁移 Upgrade 族（ENGINE_BACKLOG Lightning/星际子系统），
     再实现 on_bind 开局召唤 2/2 Battlecruiser + TAVERN_REFRESH 注入。
  8. BG31_HERO_811p Kerrigan "Spawning Pool"（+ 811p2 Evolution
     Chamber / 811p3 Ultralisk Cavern）— "Unlock Tier 2 Zerg ... Start
     the game with a 2/2 Larva."
     Status: DEFERRED。cost=6 / 8（每回合 -1）。
     Dependency: **Zerg morph 分级解锁子系统**未建——需 Tier 2/3 Zerg
     卡集定义、Larva 每回合变形选择（`BG31_HERO_811t` "choose a Zerg
     minion to morph into"）与"解锁档位"对池的影响。
     Path: Zerg 子系统（数据链 + morph 协议）落地后整族注册; 免费
     Larva 走 inject_tavern/召唤原语。
  9. BG33_HERO_001p_ALT Loh, the Living Legend "Heroic Inspiration" —
     "After {1} friendly minions attack, get a Triple Reward.
     ({0} left!)"
     Status: DEFERRED。num(0)=num(1)=15（XML）; wiki relatedCardDbfIds=
     59604（Triple Reward 法术）。
     Dependency: 与 2 同——**脱锚 Triple Reward 的档位规则**无权威。
     攻击计数本身已就绪（RALLY 事件 / `trigger_friendly_rallies`，
     RULES §6.11 攻击宣告）。
     Path: 同 2 的脱锚授予原语; 计数用 rally 监听（owner=hero）。
 10. BG34_HERO_000p Murozond "Alternate Timeline" / BG34_HERO_004p
     Morchie "Warped Conflux" — "On Turn 8/5, visit the Major/Minor
     **Timewarp**."
     Status: DEFERRED。num(0)=7/4（剩余回合）、num(1)=2; XML
     ReferencedTag BACON_TIMEWARP_TOOLTIP + BACON_TRIGGER_UPBEAT。
     Dependency: **Timewarp 子系统**（Major/Minor Timewarp 商店、
     BG34_BlackMarket_* / BG34_Giant_* 卡集）无引擎实现。
     Path: Timewarp 商店协议落地后 on_bind 注册 TURN_START 计数
     （num(0) 倒计时）→ 开启对应档商店。
 11. BG35_HERO_001p Genn Greymane "King of Duality" — "On Turn 4,
     **Discover** two Hero Powers to replace this. ({0} turns left!)"
     Status: DEFERRED。num(0)=3; XML ReferencedTag DISCOVER; wiki
     mechanicTags = Discover&&Replace Hero Power。
     Dependency: **"两连发现 + 双槽替换"协议**——引擎第二技能槽
     （RULES §9.5）为**单槽**且 `replace_hero_power` 只维护单一
     `_active_power_id`; `target_count=2` 是同一动作依次选两个目标，
     不是两次独立 Discover。wiki 无 Notes 说明两槽映射与"replace
     this"是否保留第二槽 → 读法无权威。
     Path: 主线裁定"Discover two Hero Powers"的槽位映射后，用
     `_draftable_hero_power_ids` 两次 Discover + `replace_hero_power`
     + `set_second_hero_power` 组合（batch_anomalies4 docstring 同款
     记录）。
 12. TB_BaconShop_HP_020 Akazamzarak "Prestidigitation" — "Choose a
     **Secret**. Put it into the battlefield."
     Status: DEFERRED。XML ReferencedTag SECRET。
     Dependency: **Secret 子系统**（BG 无 Secret 区/触发协议/候选集
     数据链）。
     Path: 见 ENGINE_BACKLOG §B（Secrets 子系统）。
 13. TB_BaconShop_HP_101 Silas Darkmoon "Come One, Come All!" —
     "Darkmoon Tickets are in the Tavern! Get 3 to **Discover** a
     minion of your Tier."
     Status: DEFERRED。
     Dependency: **Darkmoon Ticket token + 馆内 Ticket 计数 + 集 3
     发现**子系统; CardDB 内 "Ticket" 相关仅 buddy，无 Ticket token
     定义。
     Path: Ticket token 数据链 + 馆内实体计数 + 集齐 Discover
     （Discover 部分引擎已就绪）。
 14. TB_BaconShop_HP_106 Tickatus "Prize Wall" — "Every 4 turns,
     **Discover** a Darkmoon Prize. (@ turns left!)"
     Status: DEFERRED。num(0)=3（XML TAG_SCRIPT_DATA_NUM_1）;
     BACON_TRIGGER_UPBEAT + DISCOVER。
     Dependency: **Darkmoon Prize 子系统**（CardDB 内 "Darkmoon Prize"
     零卡池定义——无候选集数据权威）。
     Path: Prize 卡池数据落地后 on_bind TURN_START 计数 + Discover
     （kind 复用 discover）。

  （附）未绑定任何英雄的 HERO_POWER token **不在本批范围**:
  BG20_HERO_201p2 Spirit Swap / BG22_HERO_000p Deadeye(+t1..t4) /
  BG22_HERO_001p_t1..t4 Invocation / BG20_HERO_283p_t1..t3 航线 /
  BG26_HERO_102p2 Minor Hymn / BG28_HERO_400p2 Lucky Roll /
  BG31_HERO_811p2..p3 / TB_BaconShop_HP_017 Murloc King。
  它们是已注册主技能/异变的变体面或 token（`batch_hero_remaining2`
  变体台账逐条记录），重复注册 = 第三态; audit 覆盖率仪表亦不计入
  （其定义域 = Tag380 绑定技能）。此处仅台账，供主线索引。
  已迁出（**由其异变授予**，不再是"未绑定"）: `BG27_Anomaly_805t`
  Match Fixing（batch_anomalies_final）、`BG31_Anomaly_117t` Eject!
  （batch_anomalies7——Emergency Landing 第二技能槽）。

═══════════════════════════════════════════════════════════════════════
DEFERRED 台账 — 任务奖励 6 张（不注册; Status / Dependency / Path）
  （2026-09-18 第四十九轮: 362 已迁出至 `batch_quest_rewards8`; 719 早前
   迁出至 `batch_quest_rewards7`）
═══════════════════════════════════════════════════════════════════════
  1. BG24_Reward_135 Yogg-tastic Tasties — "At the start of each turn,
     spin the Wheel of Yogg-Saron."
     Status: DEFERRED。
     Dependency（2026-09-18 第四十九轮复核，权威逐条核实）: 奖励页
     `Battlegrounds/Yogg-tastic_Tasties` oldid=805475 整页 wikitext 89
     字节、**无 `article_notes=`** → 本卡无机制说明。**Wheel of
     Yogg-Saron 没有独立 wiki 页**（`titles=` 三候选全 missing、
     `intitle:` 全 ns 0 命中）; token `BG24_Reward_135t` 在 wiki 与
     hearthstonejson **都不存在**。轮盘 6 结果 + "Rod of Roasting has
     only 5% chance to be cast, while other cards have 19%." 只记在
     **别的卡** 页（`Acolyte_of_Yogg-Saron` oldid=898529 /
     `Yogg-Tastic_Pastry` oldid=921146），wiki **从未声明**本奖励共用该
     轮盘; 且该 6 卡表与"dbf 80436 已移出游戏"（`Patch 31.2.0.212197`）
     及现行数据多出的 `t7`(93390)/`t8`(93391) **直接冲突** → 现行结果
     集合与概率均无权威。另有 3 个结果自身欠定义（Darkmoon Prize 池 /
     Pyrobuff 目标口径 / "another friendly minion" 口径）。
     Path: 官方轮盘结果集与概率表落地后注册（届时同时裁定本奖励是否
     共用 Acolyte 轮盘）。见 ENGINE_BACKLOG §B（Wheel of Yogg）。
  2. BG24_Reward_313 Wondrous Wisdomball — "Occasionally gives helpful
     **Refreshes**."
     Status: DEFERRED。
     Dependency（2026-09-18 第四十九轮复核，权威更明确）: wiki 页
     `Battlegrounds/Wondrous_Wisdomball` oldid=898013 整页 wikitext 145
     字节、**无 `article_notes=`**; 全 wiki `insource:"helpful Refresh"`
     **0 命中**（无机制页）; 唯一提到 roll 内容的是一句补丁说明
     （`Patch 24.6.2.155409` oldid=253820: "…available in one of Wondrous
     Wisdomball's lucky rolls."），另一句（`Patch 33.6.2.229543`
     oldid=874442）只提 'Tier 7' roll 的时点限制 → **"helpful Refresh"
     效果全集不存在、触发频率无任何数字** → 无法精确实现（近似 = 自造
     roll 表 + 自定概率，属卡面明文处简化）。
     Path: 官方概率/类别表落地后注册。
  3. BG24_Reward_362 Essence of Zerus — "At the end of your turn, get a
     Shifter Zerus which transforms into random minions."
     Status: ✅ **已解冻（2026-09-18 第四十九轮，`batch_quest_rewards8`
     注册）**。旧台账两条阻塞**均不成立**（wiki 有详细权威）:
     (a) 变形池: `Battlegrounds` oldid=902245 逐字 "Shifter Zerus can
         transform into any Battlegrounds minion, including Shifter Zerus.
         It doesn't pull from the shared pool." → 池 = 任意 BG 随从
         （含自身）、不占共享池、**无 tier 限制**;
     (b) 时机: `Shifter_Zerus` oldid=810477 Notes "transforms only at the
         start of the possessing player's turn"（Start of Turn Phase）;
     (c) 保留附魔: `Patch 27.6.0.187190` oldid=868288 "will now carry over
         enchantments when it transforms in hand";
     (d) 载荷链: 奖励页 oldid=805429 `derived_relatedCardDbfIds=57742`
         = `BGS_029`（`Shifter_Zerus` oldid=891260 "Card id: `BGS_029`"）。
     实现: `batch_quest_rewards8`（`BG24_Reward_362` on_bind EoT 授予
     `BGS_029` 白板 token; `BGS_029` `on_enter_hand` 接线 → 自己回合
     TURN_START 手牌变形、保留附魔/位次、金色→随机金色）。以下为历史
     台账，保留备查。
  4. BG24_Reward_719 The Golden Hammer — Spellcraft: "Make a friendly
     minion Golden until next turn."
     Status: **已解冻（2026-09-15，`batch_quest_rewards7` 注册）**——
     引擎 `Game.make_golden_until_next_turn` + `Transform(force_golden=)`
     （RULES §7.4.14）补齐"临时金色"; on_bind 经 `grant_spellcraft_spell`
     立即授予 token `BG24_Reward_719t`（定向 on_play → 金色化，下回合
     回滚）。以下为历史台账，保留备查。
     Dependency: **"临时金色"原语**缺失——引擎无临时金色 tag、金色化
     后无卡定义回滚点（clear_temporary_buffs 不处理卡定义回退）。
     Path: 主线提供 temporary-golden（记录原 card_id/基础属性，下一
     招募阶段开始回滚）后，on_bind + SoT 发 Spellcraft 法术（复用
     `spellcraft.grant_spellcraft_spell`）+ token on_play 定向金色化。
  5. BG27_Anomaly_555t No Place Like Holmes — "Guess which minion your
     next opponent had last combat."
     Status: DEFERRED。
     Dependency: 正确答案校验所需快照引擎已有
     （`game.next_opponent(hero).last_combat_board`，RULES §4.8a），
     但 token 文本未载明**答对/答错回报**（回报只出现在异变
     `BG27_Anomaly_555` 页的 "…for a Coin"，本 token 无）; "2 选 1
     提供项 + 结算"协议亦无权威。
     Path: 回报数值/协议信源落地后注册（异变侧已由
     `batch_anomalies3.NoPlaceLikeHolmesAnomaly` 实现同一机制的
     "每回合 + Coin" 变体）。
  6. BG27_Reward_812 Scepter of Guidance — "The Tavern always offers 2
     {0} whenever it is **Refreshed**." num(0)=92=Race.NAGA（XML
     BACON_MINION_TYPE_REWARD=1 证实 {0} 是类型）。
     Status: **已解冻（2026-09-15，`batch_quest_rewards6` 注册）**——
     引擎新增 hero 级 `_tavern_race_guarantee = (race, n)` 读取点
     （RULES §7.4.14）。以下为历史台账，保留备查。
     Dependency: **per-slot 种族保证钩子**缺失——`refresh_tavern`
     只有全量种族白名单（`races=` 过滤掉全部非该种族）与
     `TAVERN_OFFER_MOD`（总数加值）; "保证 2 个展示位为该种族"
     无原语，用注入+替换近似违反"禁止简化实现"。
     Path: refresh_tavern 增 `race_guarantee=(race, n)` 参数（前 n 位
     从该种族池抽，其余走通用池）后 on_bind 写 hero 级 tag。
  7. BG28_Reward_501 Temporal Tampering — "Your Tavern spells cast an
     extra time."
     Status: **已解冻（2026-09-15，`batch_quest_rewards6` 注册）**——
     引擎新增 `hero.extra_triggers["tavern_spell_extra_cast"]` 消费点
     （RULES §7.4.14）。以下为历史台账，保留备查。
     Dependency: **酒馆法术额外施放钩子**缺失——`SPELL_DOUBLER` 只在
     `_finish_play_spell` 扫**棋盘随从**且仅对"定向友方随从"法术生效
     （game.py 施放段），奖励实体不在扫描源且 "Tavern spells" 含非
     定向/非友方法术; `spell_first` 配额是"任意法术的第一个"语义，
     不可复用（会误双施非酒馆法术）。
     Path: 主线在 `_finish_play_spell` 增 `hero.extra_triggers
     ["tavern_spell_extra_cast"]` 消费点（`card_def.is_pool_spell`
     门禁）后 on_bind 写 `hero.extra_triggers[...] = 1`。

═══════════════════════════════════════════════════════════════════════
引擎需求汇总（报告主线）
═══════════════════════════════════════════════════════════════════════
  1. hero 级技能 rebind/unbind（Nguyen 2 / Galewing 3）——监听器随
     技能身份注销 + hero tag 回滚。
  2. 脱锚（无来源卡）Triple Reward 的档位裁定 + 授予原语
     （Guff 2 / Loh 9）。
  3. 战后"选择强化"协议（Conviction 4）。
  4. Craft 合成子系统（Putricide 6）。
  5. Battlecruiser Upgrade 卡脚本（Raynor 7）/ Zerg morph（Kerrigan 8）。
  6. Timewarp 商店子系统（Murozond/Morchie 10）。
  7. "Discover two Hero Powers" 双槽替换裁定（Genn 11）。
  8. Secrets（Akazamzarak 12）/ Darkmoon Ticket（Silas 13）/
     Darkmoon Prize 卡池（Tickatus 14）。
  9. 任务难度数值（Whodunit 5，RULES §11.6）。
 10. Wheel of Yogg（Yogg-tastic Tasties 1）。
 11. temporary-golden 原语（Golden Hammer 4）。
 12. refresh_tavern per-slot 种族保证（Scepter 6）。
 13. 酒馆法术额外施放消费点（Temporal Tampering 7）。
 14. `BGS_029` Shifter Zerus 手牌变形脚本（Essence of Zerus 3）。

═══════════════════════════════════════════════════════════════════════
范围自算（复现命令——禁止凭记忆）
═══════════════════════════════════════════════════════════════════════
    python - <<'PY'
    from hsrl2.db import CardDB
    from hsrl2.scripts.registry import REGISTRY
    from hsrl2.tags import CardType
    db = CardDB.load("data")
    hp = sorted({d.hero_power_id for d in db._by_id.values()
                 if d.card_type == CardType.HERO and d.hero_power_id})
    qr = sorted(d.id for d in db._by_id.values()
                if d.card_type == CardType.BACON_QUEST_REWARD)
    print([i for i in hp if i not in REGISTRY])     # 15
    print([i for i in qr if i not in REGISTRY])     # 9
    PY
（本批注册后分别降为 15 / 7。）
"""

from __future__ import annotations

from hsrl2.actions import Buff
from hsrl2.events import COMBAT_END, Listener
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import GameTag

# ── 数据链常量（一律 CardDB 核实; SOP §11 教训 5 禁止凭记忆写 id）──

# Magicfin Apprentice（token）: bg_cards.json 核实为 1/1 Murloc T1、
# is_pool_minion=False、文本 "Battlecry: This casts {0}. (This minion
# can't be tripled.)"——"teach" 的消费端（batch_final_unfreeze 已注册其
# 战吼脚本，2026-08-23 wiki 双页裁定）。
_MAGICFIN_APPRENTICE = "BG33_890t"

# 本批 CORRECT 的奖励 id（register() 与测试共用）
_RITUAL_DAGGER = "BG24_Reward_113"
_MAGICFIN_RELIC = "BG33_Reward_011"

# Discover 展示数（Discover 协议默认三选一; 文本无占位符——SOP §14 第 2 条:
# `Discover.count` 是选项数，不是发现次数）
_DISCOVER_CHOICES = 3


def _hero_from_ctx(source, ctx):
    """任务奖励 on_bind/SoT 的 owner 解析（ctx["hero"] 优先）。"""
    hero = None
    if ctx is not None:
        hero = ctx.get("hero")
    if hero is None:
        hero = getattr(source, "controller", None)
    return hero


def _has_deathrattle(m) -> bool:
    """实体是否带亡语（关键词 tag 或脚本钩子双通道——batch_trinkets8 口径）。"""
    if m.has(GameTag.DEATHRATTLE):
        return True
    script = getattr(m, "scripts", None)
    return script is not None and getattr(script, "deathrattle", None) is not None


def _tavern_spell_candidates(game, hero) -> list:
    """"a Tavern spell" 候选口径 = 池法术且 tier ≤ 酒馆等级（RULES §3.6.1
    note，与 `SpellPool.draw_tavern` / Mystic Essence / Book of Medivh 全仓
    统一），经 `Game.tavern_spell_candidates` 施加**存在档白名单**
    （异变 101/102 非存在档法术不可达）。"""
    return game.tavern_spell_candidates(min_tier=1,
                                        max_tier=hero.tavern_tier)


# ══════════════════ BG24_Reward_113 Ritual Dagger ══════════════════


class RitualDaggerScript:
    """
    Natural language: [x]After a friendly
    <b>Deathrattle</b> minion dies,
    give it +5/+5 permanently.

    Evidence（2026-09-02 查证）: hsdata/CardDefs.xml `ReferencedTag`
    DEATHRATTLE; wiki Battlegrounds/Ritual_Dagger——custom_mechanicTags =
    "Reward&&Increment attack&&Increment health&&**Permanent attribute**"，
    custom_refTags = "Triggered effect&&Deathrattle-related"，
    custom_hiddenTags = "Triggered effect - after a friendly minion dies";
    Patch changes（28.6.2）确认 "+5/+5"（旧 +4/+4）。CardDef.num(0..3)
    全 None → "+5/+5" 按 SOP §3 为文本字面量。

    Formal spec:
      1. on_bind(source, game, ctx): hero = ctx["hero"]（奖励只作用于
         获得它的英雄——owner 隔离）。
      2. 注册 COMBAT_END 常驻监听（owner=source）: 只结算本英雄参战的
         战斗（hero ∈ {hero_a, hero_b}）; 幽灵战同样广播（RULES §4.8）。
      3. 命中: 遍历 `game.combat_death_log`（run_combat 入口清空，
         combat_end 时点恰为本场全集）取 controller is hero、
         带亡语（`_has_deathrattle`）且已随棋盘复原回到 hero.board、
         非死亡的实体 → `Buff(m, atk=5, health=5)`（永久附魔; 战斗外
         施加故不被战后快照回滚——棋盘在 combat_end 前已复原）。
      4. 每个死亡事件各触发一次（复生后再次死亡亦计——引擎死亡簿记
         按次记录，RULES §6.11 同口径）。
      5. 招募期死亡不结算: 实体已离场（zone=GRAVEYARD）且不回棋盘，
         对已离场实体施 buff 无可观测语义; 本脚本只处理可观测的
         战斗死亡（正是 "give it +5/+5 **permanently**" 的可观测面）。

    Test: test_batch_hero_rewards_final.py::TestRitualDagger — 真实
    `run_combat` + `combat_end`: 亡语随从战死后回棋盘 +5/+5（同方法
    负/正对照: 无亡语随从战死不变、亡语随从存活不变）; 对手亡语随从
    战死不沾（owner 隔离）; 第二场战斗再 +5（累计 +10）; 未参战的
    combat_end 不触发; 未获奖励的英雄不触发。

    Params: atk=5 health=5（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero_from_ctx(source, ctx)
        if hero is None:
            return None

        def on_combat_end(g, hero_a=None, hero_b=None, _h=hero, **kw):
            if hero_a is not _h and hero_b is not _h:
                return None   # 只结算本英雄参战的战斗
            targets = []
            for m in g.combat_death_log:
                if getattr(m, "controller", None) is not _h:
                    continue
                if not isinstance(m, Minion) or m.dead:
                    continue
                if not _has_deathrattle(m):
                    continue
                if m not in _h.board:
                    continue   # 战斗召唤物/未复原实体 → 无可观测面
                targets.append(m)
            if not targets:
                return None
            # 监听器回调返回值不被 EventBus 执行（events.fire 忽略返回值）
            # → 显式经 ActionQueue 施加永久附魔
            g.run_actions([Buff(m, atk=5, health=5) for m in targets])
            return None

        game.events.register(Listener(
            event=COMBAT_END, owner=source, callback=on_combat_end))
        return None


# ══════════════════ BG33_Reward_011 Magicfin Relic ══════════════════


class MagicfinRelicScript:
    """
    Natural language: At the start of each turn, get a 1/1 Murloc.
    <b>Discover</b> a Tavern spell to teach it.

    Evidence（2026-09-02 查证）: hsdata/CardDefs.xml 逐 tag 核对——
    `BG33_Reward_011` 带 `USE_DISCOVER_VISUALS=1` + `BACON_SUBSET_MURLOC=1`
    + `ReferencedTag DISCOVER=1`; 生成物数据链
    `BACON_EVOLUTION_CARD_ID=122285` 在两张同文案同族卡
    （Magicfin Mycologist `BG33_891`、Magicfin Sticker
    `BG35_MagicItem_750`）上均指向 `BG33_890t` Magicfin Apprentice
    （1/1 Murloc，战吼 "This casts {0}."）——"teach" 消费端已由
    `batch_final_unfreeze`（2026-08-23 wiki 双页裁定）注册，
    `token._taught_spell_id` 为其数据通道。"Discover a Tavern spell"
    无 "Tier N" → 口径 = 池法术 tier ≤ 酒馆等级（RULES §3.6.1）。

    Formal spec:
      1. start_of_turn(source, game, ctx)（引擎对 hero.quest_rewards 逐
         个分发）: hero = source.controller。
      2. "get a 1/1 Murloc": `create_minion("BG33_890t")`（非池卡 →
         零池操作、不参与三连——`check_for_triple` 对非 is_pool_minion
         天然跳过）→ `pending_hand_add`（满手排队 RULES §3.3）。
      3. "Discover a Tavern spell to teach it": 候选 = `db.pool_spells()`
         中 tier ≤ hero.tavern_tier 且池有剩余（per-tier 副本池，
         RULES §3.6.1）; 无候选 → 该次落空（Murloc 照常入手——文本先
         get 后 Discover）; 否则 rng.sample 3 个互异 → 预留语义（选项
         生成即 acquire）→ PendingChoice(kind="discover_tavern_spell")。
      4. resolve(pick): 非法/陈旧选项 → 落空（槽不变）; 否则释放未选
         项、选中项**保留占池**（Discover 获取语义：该法术随 token 进入
         手中，池净 -1）并写 `token._taught_spell_id = pick`（teach）。
      5. 每次 start_of_turn 各结算一次（"At the start of each turn"）。

    Test: test_batch_hero_rewards_final.py::TestMagicfinRelic — 真实
    回合路径 `_begin_recruit_for`（token/选择计数）+ 真实分发原语
    `run_script_hook(reward, "start_of_turn")`（池记账精确断言）:
    入手恰 1 张 `BG33_890t` 且零池记账;
    恰 1 个本人 kind=discover_tavern_spell 选择且 `len(options)==3`、
    选项互异/均为池法术且 tier ≤ 酒馆等级/均已预留; resolve 后 token
    `_taught_spell_id == pick`、选中占池未释放、未选项回池; 被教 Shiny
    Ring 的 token 打出时全体随从 +num(0)/+num(1)（teach 端到端）;
    对手无奖励不触发（owner 隔离）; 第二回合再入手一张（每回合）;
    法术池耗尽仍入手 token 且无选择（落空不消耗）; 同 seed 确定性。

    Params: 无模板参数（token id 走 CardDB 数据链; choices=3 Discover
            默认展示数）
    """

    @staticmethod
    def start_of_turn(source, game, ctx):
        hero = _hero_from_ctx(source, ctx)
        if hero is None:
            return None
        token = game.create_minion(_MAGICFIN_APPRENTICE, controller=hero)
        if token is None:
            return None
        game.pending_hand_add(hero, token)

        cands = _tavern_spell_candidates(game, hero)
        if not cands:
            return None   # 池耗尽 → Discover 落空（Murloc 已入手）
        k = min(_DISCOVER_CHOICES, len(cands))
        drawn = game.rng.sample(cands, k, label="magicfin_relic_spell")
        options = [cid for cid in drawn if game.spell_pool.acquire(cid)]
        if not options:
            return None

        resolved = [False]

        def resolve(pick_id):
            # 幂等闸: `PendingChoice.choose` 无重复结算守卫（SOP §13 契约
            # 为"先 pop 再 choose"）——重复 resolve 不得二次释放未选项，
            # 否则每次多出幻影副本（2026-09-13 对抗验证实测池 +1/次）。
            if resolved[0]:
                return
            resolved[0] = True
            if pick_id not in options:
                # 陈旧/非法选择: **释放全部预留**并 fail-loud（与引擎
                # `Discover.resolve` 同口径）——旧实现静默 return，3 份
                # 预留永久泄漏（2026-09-13 对抗验证证伪）。
                for cid in options:
                    game.spell_pool.release(cid)
                raise GameStateError(
                    f"{source.card_id}: stale Discover pick {pick_id!r} "
                    f"(options={options})")
            for cid in options:
                if cid != pick_id:
                    game.spell_pool.release(cid)
            # 选中项保留占池（Discover 获取语义）; "teach" = 写 token 的
            # 被教法术槽（batch_final_unfreeze.MagicfinApprenticeScript
            # 战吼消费点）
            token._taught_spell_id = pick_id

        game.pending_choices.append(PendingChoice(
            hero, list(options), "discover_tavern_spell",
            resolve_callback=resolve))
        return None


def register() -> list[str]:
    """注册本批 2 张 CORRECT 任务奖励。

    DEFERRED 台账（英雄技能 15 张 + 任务奖励 7 张）见模块 docstring——
    依赖逐条列出，全部保持未注册（SOP §6b 二态铁律）。
    """
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for card_id, script in (
        (_RITUAL_DAGGER, RitualDaggerScript),
        (_MAGICFIN_RELIC, MagicfinRelicScript),
    ):
        reg(card_id, script)
        registered.append(card_id)
    return registered
