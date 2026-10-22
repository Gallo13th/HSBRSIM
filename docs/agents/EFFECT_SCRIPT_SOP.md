# SOP: 效果脚本实现 (Effect Script)

> 适用: 为已录入的卡实现行为脚本。作业范围: 仅 `hsrl2/scripts/`。
> 铁律: **CORRECT 或 DEFERRED，没有第三态**。"简化实现"是 bug。

## 1. 脚本类规范

```python
class MyCardScript:
    """
    Natural language: <从 data 复制的官方文本原文，一字不改>

    Formal spec:
      1. <精确操作步骤: 谁、对谁、何时、多少>
      2. <创建/修改了哪些实体>

    Test: <一句话: 测试如何验证 spec>

    Params: {0}=<d.num(0) 值> {1}=<d.num(1) 值>  ← 数值唯一来源
    """

    @staticmethod
    def battlecry(source, game, ctx):
        return SomeAction(...)      # 返回 Action / list[Action] / None
```

## 2. 可用钩子（签名统一 `(source, game, ctx) -> Action|list|None`）

| 钩子 | 触发时机 | ctx 内容 |
|------|---------|---------|
| `battlecry` | 打出时（金色×2、Brann×2 由引擎处理） | `{}` / `{"target":...}` / `{"choose":key}` |
| `deathrattle` | 死亡时（先于复生） | `{}` |
| `start_of_combat` | SoC（顺序: 饰品→奖励→随从→英雄技能） | `{}` |
| `avenge` | 友方死亡计数达标（计数引擎处理） | `{}` |
| `rally` | 攻击宣告时、伤害前 | `{"target": defender}` |
| `start_of_turn` / `end_of_turn` | 回合开始/结束（酒馆内） | `{}` |
| `on_sell` | 被出售时 | `{}` |
| `on_summon` | 进入棋盘时（注册持久监听器） | `{}` |
| `on_play` | 从手牌打出（法术/Spellcraft） | `{"target": ...}` |
| `activate` | S14 Activate 使用时（金币/次数引擎处理） | `{}` |
| `atk` / `health` | 动态属性（返回 int 或 None） | — |

**脚本类声明协议（引擎自动识别）**:
- `needs_target = True` — 定向战吼/法术。引擎先入场/扣费，再产生
  PendingChoice(kind="battlecry_target"/"spell_target")，选定后以
  ctx["target"] 触发钩子; 无候选时战吼落空随从照常入场
- `target_candidates(source, game)` — 可选，自定义目标候选（默认全体友方存活随从）
- `choose_options = [(key, label), ...]` — Choose One 卡。引擎产生
  PendingChoice(kind="choose_one")，选定 key 以 ctx["choose"] 触发 battlecry
- `avenge_threshold = N`（**饰品/任务奖励**用）— 非随从实体无法携带
  `AVENGE` tag，Avenge 类饰品/奖励以类属性声明阈值；引擎在友方死亡
  （含复生死亡）时对 棋盘随从 + `hero.trinkets` + `hero.quest_rewards`
  统一计数，达标调用 `avenge(source, game, ctx)` 并清零计数
  （2026-09-01 扩展，此前只扫棋盘 → 饰品 Avenge 注册即 no-op）

**磁力效果合并**: 宿主触发任何钩子时，其吸附的磁力卡同钩子效果以宿主
为 source 一并触发（吸附顺序）——磁力卡脚本无需感知宿主。

**禁止**: 脚本内 `import random`（用 `game.rng`）、读写引擎私有状态、
直接改 `constants.py`。

## 3. 语义精确性核对表（每张卡过一遍）

历史缺陷皆源于此——逐项打勾:

- [ ] **动词**: Get=进手牌 / Play=立即生效 / Summon=入场 / Give=永久buff /
      Gain=获得资源 / Deal=造成伤害 / Destroy=直接消灭。
      "Get 2 Blood Gems" ≠ "对自身施放 2 颗"（v1 已犯错）
- [ ] **数值**: 一律 `source_def.num(0/1)`。脚本通过
      `game.db.get(source.card_id)` 取回 CardDef。模板参数缺失且文本
      无占位符时可字面量，否则报告 `PARAM_MISSING`
- [ ] **目标范围**: 自己/其他友方/全体/相邻/手牌/酒馆中?"minion in it"
      指酒馆（player.tavern）不是棋盘
- [ ] **时机**: "After X" vs "When X" vs "Start of Combat"；
      Rally 在伤害前（引擎已保证）
- [ ] **属性快照**: 聚合/复制属性用 **max_health**（属性值）而非
      health（当前血量）; 攻击用 atk
- [ ] **金色分支**: 金色版是独立卡定义——脚本通常不用分支，数值差异
      由金色 CardDef 的 num() 自然体现; 行为差异（如"twice"）读金色
      文本判断
- [ ] **满场/满手**: Summon 自动处理满场（MINION_OVERFLOW）；
      生成卡进手牌用 `game.pending_hand_add(hero, entity)` 排队等待，
      禁止直接 append（P6）
- [ ] **占池**: 获取随从必须走 `game.minion_pool.acquire(card_id)`
      （P2）; token（tech_level≤0 或非池卡）不占池

## 4. Action 复用优先级

实现效果时按序寻找，都不匹配才新建 Action（放 `scripts/_actions.py`
并报告主线评审）:

1. `Buff(target, atk=, health=, temporary=)` — 临时 buff 战后清除
2. `GainKeyword(target, GameTag.X)` / `LoseKeyword`
3. `Summon(hero, card_id, position=)` — position=None 最右
4. `Hit(target, amount, source=)` — 走圣盾/剧毒交互
5. `GetRandomMinion(hero, race=, min_tier=, max_tier=)` — 池感知
6. `Discover(hero, candidates, kind=)` — 产生 PendingChoice（队列化）
7. `GainGold(hero, n)` / `SpendGold`
8. `Transform(target, new_card_id)` — 保留 buff/金色
9. `ScheduleNextTurn(hero, action)` — 延迟动作
10. `TriggerBattlecry(target)` — 重触发战吼（广播 BATTLECRY_TRIGGER）
11. `GetBloodGems(hero, count, variant=)` / `PlayBloodGems(target, count)` /
    `ImproveBloodGems(hero, atk, health)` — 血宝石三操作
12. `ConsumeMinion(demon, victim)` / `ConsumeRandomTavernMinion(demon)` —
    吞噬（不触发亡语; 酒馆/手牌来源回池、友方不回池）
13. `TavernBuff` / `ApplyTavernBuff(hero, buff)` / `BuffCurrentTavern(hero, buff)` —
    酒馆持久 Buff（refresh 自动应用新入馆随从）

## 5. 持久监听器模式（"After you X, ..."）

```python
@staticmethod
def on_summon(source, game, ctx):
    from hsrl2.events import Listener
    game.events.register(Listener(
        event="tavern_spell_cast",       # 事件名见 events.py 常量
        owner=source,                     # 宿主=随从 → 离场自动注销
        callback=lambda g, spell=None, **kw: g.run_actions(
            Buff(source, atk=1, health=1)),
        condition=lambda **kw: True,      # 友方过滤等在此判断
    ))
    return None    # on_summon 的副作用是注册，无 Action 入队
```

## 6. DEFERRED 格式

引擎缺机制时**必须** DEFERRED（返回 None + 显式标注），禁止近似实现:

```python
class MyCardScript:
    """
    Natural language: <原文>

    Status: DEFERRED — requires <机制>
    Dependency: <引擎需先支持什么>
    """
    @staticmethod
    def battlecry(source, game, ctx):
        return None
```

## 6b. 二态铁律（2026-08-22 整改，禁止第三态）

**注册进 REGISTRY = 自称 CORRECT。** 不存在"AMBIGUOUS 但已注册"——
带歧义注记的近似实现是纪律违规（历史上 79 处，已专项整改）。

语义不确定时的处置顺序（**必须按序**）:
1. **查证**: hearthstone.wiki.gg 卡片页（Wiki tags: [Targeted]/[Random]/
   Notes 段落、Related cards）、官方 patch notes、dev comment——
   绝大多数"看似未公布"的交互在 wiki 有记载（先例: Kelp Keeper
   [Targeted]、Deft Deserter [Random]、Robust Evolution "恰好+1"的
   多语言文本、Diremuck "for this combat only"）。
   **禁止以"官方未公布"为由跳过查证自行拍板**。
2. **查证一致** → CORRECT，docstring 的 Params 区记录证据出处
   （如 `Evidence: wiki.gg/wiki/Battlegrounds/X#Notes`）。
3. **查证不一致** → 按官方修正实现。
4. **确实查无证据** → DEFERRED 撤注册（宁缺毋错），docstring 记录
   已查的信源清单与候选读法，等待实测/新信源。

引擎机制层的读法选择（时序/边界/协议）同样适用本条——主线的
"裁定"必须附规则依据（RULES §x / wiki 链接），无依据的选择项
按第 4 步处理（机制缺省不实现，而不是选一边）。

## 7. 作业单返回格式

```
脚本完成: <n>/<n>
- OK: BG36_701 — activate: TriggerBattlecry(随机友方)
- DEFERRED: BGXX_YYY — requires 招募阶段局部攻击(Fishbait)，Dependency: game.fishbait_attack()
- AMBIGUOUS: BGXX_ZZZ — "next turn" 指下回合开始还是结束? 候选A/B
测试/审计: <输出末行>
```

## 8. 经验库（持续追加）

- 2026-08-21: rally 的 ctx["target"] 保证存活（伤害前触发），无需 dead 检查
- 2026-08-21: 死亡触发的脚本（deathrattle）中 source 可能已 zone=GRAVEYARD，
  广播效果以 source.controller 为锚点
- 2026-08-21: "improves after each X this game" 用 on_summon 注册监听 +
  source tag 计数（IMPROVE_COUNTER），"this turn" 用玩家回合计数 tag
- 2026-08-21: **Targeted 效果 → PendingChoice，禁止随机近似**。裁定先例
  Kelp Keeper (BG36_701): 官方 wiki "Wiki tags" 含 [Targeted] → 玩家选择。
  自动化模拟用 `game.pending_choices.append(PendingChoice(hero, 候选,
  kind, resolve_callback))` 建模，由自动化层 choice_policy 决策。
  判别法: wiki 卡片页 Wiki tags 段 / 文本含 "Choose"。无 [Targeted] 且
  无 "Choose" 的 "a friendly minion's X" 才是随机（Play Dead 先例）
- 2026-08-21: **HERO_DAMAGE_TAKEN 时序（2026-08-22 二次修正）**——
  战败伤害施加于**战后棋盘**（恢复之前）; 事件携带 health_before/
  armor_before（Rewind 类逐实例全量回溯，含护甲）。结构性事实:
  战败方棋盘必然全灭 → **随从的 hero_damage_taken 监听器不可能由
  战败伤害触发**（Soul Rewinder/Tichondrius 家族 = 招募期扣血联动:
  健康购买/自伤技能/法术）; 伤害窗口内幸存触发器的增益经增量重放
  跨复活保留。护甲吸收也算受伤（Floating Watcher 语义）
- 2026-08-21: **持久监听器随战斗快照恢复**——随从战斗中战死不注销其
  监听器（战后复活）; 招募期死亡/出售才真正注销。注意: 该恢复发生在
  战败伤害**之后**——战死者的监听器对本次战败伤害缺席（见上条）
- 2026-08-21: 可用事件名（events.py 已全部 fire）: card_played(card=)、
  hero_damage_taken(hero=,amount=)、damage(minion=,amount=,source=)、
  keyword_gained/keyword_lost(minion=,tag=)、minion_sold(minion=)、
  battlecry_trigger(minion=)、deathrattle_trigger(minion=)、
  transform(old=,new=)、combat_end/hero_eliminated
- 2026-08-21: 金色战吼模型 = 金色卡定义文本为**总额**，引擎 play_minion
  对 GOLDEN 随从触发 2 次（每次按金色 CardDef.num() 取值），Brann 再 ×2
- 2026-08-21: **三连系统已就绪**——购买/获取路径自动检查; 3 副本（手牌/
  棋盘混合）合成金色（金色=独立卡定义、buff 并集保留）; 场上合成立即发
  tier+1 发现奖励（T6→T6），手牌合成打出时发放; 脚本层无需关心
- 2026-08-21: **play_spell 定向分流**——法术脚本声明 needs_target=True
  时与随从同构（PendingChoice kind="spell_target"）; TAVERN_SPELLS_CAST
  计数只对 is_pool_spell 法术生效（血宝石/Spellcraft 不计入）
- 2026-08-21: **法术塑造系统已就绪**——spellcraft 随从 on_summon 调
  `hsrl2.spellcraft.grant_spellcraft_spell(minion, game)`（打出立即获得）;
  回合开始自动生成由 generate_for_hero 处理; 金色法术经随从 spellcraft_id
  数据链直指金色定义; "until next turn" 临时效果用 TURN_START once
  Listener 清除（owner=目标随从）

## 9. Wave1-3 沉淀的引擎契约（2026-08-21 批量迁移期）

- **死亡处理官方顺序**: death 事件 → 离场（让出板位; 满场亡语召唤成立;
  亡语召唤填死者板位——ctx["position"] 或 ZONE_POSITION 残值）→ 亡语
  （含磁力栈叠）→ 招募期回池（亡语**后**——防死亡副本被自身亡语自抽）→
  复生原位回归（跳过亡语新召唤物; Wiki: "Deathrattles are resolved
  before Reborn"）→ Avenge 计数
- **damage 事件全覆盖**: 攻击主/反击/顺劈/招募期攻击/Hit Action 全部
  fire (minion=, amount=实际值, source=)——"Whenever this takes damage"
  直接监听
- **tavern_spell_cast 在法术效果结算后**广播（官方 29.2.2 bugfix 语义）;
  计数 tag 先置供 on_play 读; card_played(法术) 带 target kwarg
- **金卡关键词已修复导出**（G3）: 金色实体 create_minion 正确携带
  DS/Taunt/MAGNETIC 等关键词; CHOOSE_ONE/stealth 一并入 keywords
- **磁力吸附按实体当前属性**（含 buff）并入宿主; 全效果钩子合并
- **种族光环** ApplyRaceAura(hero, race, atk, health) 叠加式，board/hand/
  未来随从全生效且当前血量同步抬升; 新随从 summon 满血初始化
- **声明协议新增**: `hand_soc = True`（手牌 SoC——Flighty Scout 类）;
  `game._active_combat` 战斗对暴露（SoC "all other minions" 含敌方）
- **目标语义裁决库**: 文本 "random" → 随机; "Choose"/wiki [Targeted] →
  PendingChoice; "a different friendly X"（Mummifier 先例）→ 随机;
  其余无证据 → AMBIGUOUS 上报（Kelp Keeper 教训: 主线查 wiki 裁决）
- **池单份法术 "Get N" 语义**: 首份 acquire、余份净增（Mystic Essence/
  Banana 两处复用约定）
- **Improve 家族**: Tasty Lobster/Baller 三兄弟/Lobster 等 "Improve your
  future X" = hero/source 级累积计数 + 未来副本加成递增

## 10. 引擎收口新增原语（2026-08-22 对抗审查后，剩余 36 卡的解冻钥匙）

- **Bounty 卡集**: `constants.BOUNTY_SPELL_IDS`（BG33_811..815 五张，
  数据核实）; `bloodgem.random_bounty_card_id(game)` 生成（非池不占池）
- **立即攻击**: `combat.execute_immediate_attack(game, attacker, defender)`
  （Jailbird "to attack the target first"——完整单次攻击语义）
- **金色打出计数**: hero `GOLDEN_MINIONS_PLAYED` tag（打出路径自动递增，
  Maritime Extortionist/Hooktusk 数据源）
- **死亡簿记**: `hero.deaths_by_card_id`（跨战斗持久，按 card_id——
  Eternal Knight "died this game"）; `game.combat_death_log`（本场按序）
- **发现事件**: `card_discovered(kind=, hero=)`——Discover/triple_reward/
  dark_gift 选择完成时 fire（Hooktusk 监听）
- **法术双施**: 棋盘 `SPELL_DOUBLER` tag（金色 ×3——倍率累加; Balinda）
- **手牌钩子**: `on_enter_hand`（hero.add_to_hand 时触发——Bream
  Counter/Aureate Laureate/Search Through Time 锁定）
- **手牌锁定**: 实体 `LOCKED_IN_HAND` tag（play 路径拒绝; 脚本用
  turn_start once Listener 清除）
- **永久化拦截**: `spell_resolving(spell=, target=, cast_no=)` 事件——
  Lava Lurker 类脚本在其中设 `game._permanence_pending = target.uuid`，
  该次施放的 temporary buff 自动转永久
- **buff_applied 事件**: (target=, buff=)——Scarlet Survivor 阈值监听
- **ENCHANT_IMMUNE tag**: Fishbait "can't gain stats"——正值增益被拒
- **宝石记账**: 所有宝石 buff 带 `gem=True` 标记; per-minion
  `GEMS_PLAYED_ON` tag + `blood_gem_played(target=, player=)` 事件
  （手打/直施两路径统一）; `StealBloodGems(recipient, victim)` 移转
- **健康刷新**: hero `HEALTH_REFRESHES_LEFT` tag（Malchezaar 协议，
  生存守卫: 不足以支付回落金币）
- **替代三连**: BG26_175 全池重扫（2×175+任意元素→金175 /
  2×元素+175→金元素; 与到达顺序无关）
- **三连接线**: pending_hand_add/发现 resolve/打出路径自动检查——
  脚本层无需手动调 check_for_triple
- **PERSIST 倍率**: `PERSIST_COMBAT_CHANGES`=1×（池卡 Tarecgosa）;
  +`PERSIST_DOUBLE`=2×（gift/金 Poet "double stats"）;
  Poet 光环 = `ADJACENT_PERSIST_SOURCE`（金色自动 ×2）
- **Fodder 协议 v2**: `game._fodder_refresh_pending[hero] =
  (剩余刷新次数, 每次附加枚数)`（金色 Trapped Clapper 每刷新 2 枚）
- **CHOOSE_BOTH**: 棋盘光环或实体 tag（Fandral 发现的恒双效卡:
  resolve 时 `picked.set(GameTag.CHOOSE_BOTH, True)` 再入手）
- **上局战斗结果**: `hero._last_combat_result`（"win"/"loss"/"draw"——
  Tortollan Blue Shell 条件）

## 11. 接线审计与"no-op 第三态"（2026-09-01 主线维修沉淀）

`tools/audit_script_wiring.py` 是第四件验收工具，专抓"注册成功、测试
全绿、但引擎从不触发"的脚本。三层检查:

- **W1 死钩子**: 每类卡只有固定钩子被分发——
  异变/任务只有 `on_bind`；饰品/任务奖励 = `on_bind` + `start_of_turn`
  + `end_of_turn` + `start_of_combat`。定义了协议外的钩子（如给异变写
  `hero_power`）即死代码。
- **W2 死监听**: `Listener(event="...")` 的事件名必须真有 `.fire(...)`。
- **W3 空转标记**: 脚本对 `game._x`/`hero._x` 的写入必须被脚本之外的
  引擎代码读取（`getattr(x, "_x")` 也算）；只写不读 = 标记无效。

**已知教训（本审计首跑命中的真实缺陷）**:
1. **闭包晚绑定**: `for h in game.heroes:` 里定义回调再引用 `h`，循环
   结束后所有闭包共享同一单元 = **最后一个**英雄。2 人局里"互相触发"
   会掩盖 bug。**必须**用默认参数绑定: `def cb(..., _h=h, **kw)`，
   过滤用 `if hero is _h`。
2. **模块级常量覆写**: 异变直接 `C.TAVERN_MAX_TIER = 7` 会跨局污染
   （Game 是短生命周期对象，constants 是进程级）。改为 `game.max_tavern_tier`。
3. **标记无人读**: 写了 `hero._tavern_offer_tier_only` 但引擎没读 →
   效果为 0。**新增任何 `_flag` 必须同时在引擎加读取点并写测试**。
4. **算了不用**: 计算了 most-common race 却调用无参刷新。实现后逐行
   核对"每个中间量都被使用"。
5. **凭记忆的卡 id**: Cap'n Hoggarr 写成 `BG20_203`（实为 Prophet of
   the Boar，正确 `BGS_072`）、Patient Scout 写成 `BG25_001`（实为
   Risen Rider，正确 `BG24_715`）。**一律按名字查 `CardDB` 取 id**，
   禁止凭记忆写 id。
6. **池外卡注入**: `ensure_available` 需支持当前池定义外的随从
   （异变明示 "X is in the pool"），并让 `candidates()` 以池剩余为准
   而非 `db.pool_minions()`。

**新钩子/新标记的验收路径**: 写脚本 → 跑 `audit_script_wiring.py
--strict` 确认无 W1/W3 → 在 `hsrl2/tests/` 写行为测试断言效果真的
发生（不能只断言 flag 被设置）。

## 12. 2026-09-01 主线审计：任务/饰品批的缺陷模式（教训台账）

两个独立 subagent 对 `batch_trinkets1.py`（10 注册）与
`batch_quest_rewards.py`（41 注册）做了逐卡审计（读 data 文本 + 运行时
探针），发现 **11 + 28 处缺陷**，而四件套当时全绿——说明工具只保证
"有脚本/参数一致/接线存在"，**不保证语义正确**。以下是必须引以为戒的
模式（修复进行中，见各 batch 的 docstring 台账）:

1. **恒真/恒假 guard**: `if hero is not hero: return`（参数遮蔽闭包）→
   奖励在别的英雄 SoC 里生效（R109/R111）。**多英雄场景必写 owner
   隔离测试**; 闭包一律 `_h=hero` 默认绑定。
2. **错误 API/不存在的符号**: `hero.max_health` 在 Hero 上恒 0
   （生命存于 `HEALTH2`）; `hero.last_combat_board` 是**自己**的战前板;
   对手板分三种引用（RULES §4.8a，2026-09-02 统一）:
   `game.next_opponent_warband(hero)` = **下一**对手当前战团（Scabbs）、
   `game.last_opponent_warband(hero)` = **上一**对手战前战团
   （Tess / 任务奖励 R806）、`game.next_opponent(hero).last_combat_board`
   = 下一对手上一场战斗的阵容（Murloc Holmes）。
   `from batch_bloodgem import give_gem`（不存在）; `_pool_spell_ids`
   （不存在）; `spell.needs_target`（在 `spell.scripts` 上）。
   **用符号前先 grep 定义; 单元测试必须真正执行到该路径**。
3. **一次性 vs 每回合**: "next turn" 用了常驻 TURN_START 监听
   （R014/R015/R311）; 反之 R311 文本无时机却每回合触发。**"next/once"
   用 `once=True` 监听器**。
4. **时间点错位**: `card_played` 在 `summon` **之后**广播（game.py），
   于是"打出前"的类型集合判断恒真（R810）; `card_discovered` 同时携带
   随从与**法术** id，一律 `create_minion`（R129）。
5. **列表快照失效/池泄漏**: 捕获的候选列表在第二次触发时含已移除项
   （`ValueError`）; 移除酒馆随从未 `minion_pool.release`（R309）。
6. **temporary 惰性**: `entity.Buff(temporary=True)` 目前**无引擎清除
   调用点**——不写脚本侧过期监听就等于永久叠加（R312）。
7. **"plain copy" 语义**: `_plain_copy` 复制了 `_buffs`/金色 → 不是
   plain（R138/R502/R506）。
8. **恒等式/同义反复**: 注册变体到硬编码分支的同一类（321t Odd →
   same class as 321 Even）。
9. **全局 vs 英雄作用域**: 饰品 `T998` 写 `game._tavern_min_tier` →
   污染所有对手的酒馆; 应写 `hero._tavern_min_tier`。
10. **门禁记账粒度**: 饰品 offer 用 `hero in _trinket_offered` 单集合
    → T6 之后 T9 Greater 永不发放（引擎已修为 `(hero, kind)`）。
11. **DEFERRED 理由必须核实**: `BG30_MagicItem_543` 声称 token 不在 db，
    实际授予物是已存在的 `EBG_Spell_032`（Channel the Devourer）。
    **写 DEFERRED 前先按名字在 CardDB 搜索**。

**派发要求（新增）**: 每个作业单除四件套外，必须为所改卡各写**行为
层**测试（多英雄 owner 隔离 / 跨回合一次性 / 满场满手 / 池占返），
并贴出 `pytest hsrl2/tests/test_batch_<name>.py -q` 的通过数。

12. **提供池必须按档位/变体过滤**: 饰品 `_offer_trinkets(kind)` 曾忽略
    `kind` → T6 "Lesser" 混入 Greater、T9 "Greater" 混入 Lesser。
    数据权威: `spell_school` **11=Lesser / 12=Greater**（全 379 张）;
    升级变体（id 尾 `t`/`t2` 且有**同名本体**，51 个中 46 个）不进商店池
    （`CardDB.trinket_offer_pool()`）。**任何"某档位/某子集"的抽取，
    都要先把子集定义落到数据字段并写测试断言被抽项的档位**。
13. **关键词的适用阶段必须显式守卫**: Avenge 是战斗关键词
    （RULES §6.11 "本场战斗中死亡"），但计数函数没有战斗守卫 →
    招募期死亡（自伤/吞噬/健康购买）也会累计并在战斗外触发。
    规则: 任何 keyword 计数器/触发器先查 RULES 确认适用阶段，并加
    `in_combat`/`_active_combat` 守卫 + "阶段外不计数"回归测试。
14. **关键词载荷未就绪的卡不得注册**: `BG24_HERO_100p` Whodunit?
    机制正确但任务卡 0/17（难度数值无权威）→ 选到的任务永不完成，
    真实对局效果为空转。**"引擎机制就绪" ≠ "效果可兑现"**——载荷
    （任务/饰品/token）本身 DEFERRED 时，宿主卡一并 DEFERRED。

## 13. 全对局随机压测（integration smoke）——每轮必跑

四件套 + 单元测试都发现不了引擎级/集成级缺陷。**每批脚本或引擎改动
后必须跑一次随机 8 人对局压测**（随机买/打/刷/升/技能/Activate/Dark
Gift/饰品选择，FIFO 解析 PendingChoice，含随机异变），40 局应 0 崩溃。
本轮压测（2026-09-01）命中的引擎缺陷:

1. **`run_combat` finally 未初始化**: `poet_persist/persist_totals/
   dmg_deltas` 在 try 内赋值 —— 战斗异常时 finally 抛
   `UnboundLocalError` 掩盖真实错误（已在 try 前初始化）。
2. **`IMMUNE = 49` 与 `ZONE = 49` 同值**（IntEnum 别名化）→
   `m.has(GameTag.IMMUNE)` 恒真（探针被误导）。XML 权威 `enumID=240`。
   **新增标签必须核对 XML enumID 唯一性**。
3. **`AFTER_ATTACK` 循环补位 → 无限战斗**: Ozumat Tentacular 与
   Drek'Thar/Vanndar "When you have space in combat" 被按**文本字面**
   实现为"每次攻击后补满"。双方同类英雄时"死一只→补一只"永不终止
   （2001 轮 `CombatLoopError`，双方各 ~1990 次重生）。
   依据: CardDefs.xml / wiki XML tags **只有 `START_OF_COMBAT=1`**。
   教训: **文本措辞不构成触发时机权威——以 XML 标签为准**;
   任何"whenever/when you have space" 触发器都要问"是否可能每回合
   无限次"，并写"战斗必须终止"的回归测试。
4. **定向技能目标在挂起期间离场**: Cookie "Stir the Pot" 的目标被
   `gold_spent` 监听器在扣费瞬间移除 → 脚本抛 `GameStateError`。
   引擎已在 `_finish_hero_power` 复查目标可见性（任意英雄棋盘/手牌/
   酒馆），失效则本次作废（不扣费/不计数）。**注意目标域不限友方棋盘**。
5. **提供项未预留 → 并发取走崩溃**: 旧的 `Discover` / Dark Gift /
   Thorim 都是"生成选项不占池、resolve 才 acquire"，同回合两个发现/
   商店会取走彼此选项 → `GameStateError`。统一为**预留语义**: 选项
   生成即 `acquire`，resolve 保留选中、`release` 其余。新增任何
   "n 选 1" 协议必须遵此（含测试: 并发选项不重叠、未选项回池）。
6. **标准局可升到 Tavern Tier 7**: `next_tier > MAX + 1` 差一错误
   → 改为每局 `game.max_tavern_tier`。
7. **饰品 offer 单集合记账**: T6 lesser 后 T9 greater 永不发放
   → 改为 `(hero, kind)`。
8. **`Hero.max_health` 恒 0**: Hero 只设 `HEALTH2`，`BASE_HEALTH`
   未设 → "regain X Health" 类效果封顶失效（已补）。

**压测命令（已入库）**:
```bash
python tools/smoke_random_games.py --games 40      # 必跑; 退出码非 0 = 有崩溃
python tools/smoke_random_games.py --games 150 --seed 3000   # 大批量
python tools/smoke_random_games.py --no-anomaly    # 标准局对照
```
工具内部: 随机 8 人（随机英雄/随机异变），循环
`use_hero_power/use_activate/use_dark_gift/buy_from_tavern/play_minion/
play_spell/upgrade_tavern/refresh_tavern/sell_minion`，每步后 FIFO
解析 PendingChoice，`end_recruit_phase()` 推进，`--turn-cap` 截止；
打印崩溃 seed/异变 + traceback（含 `--seed` 可精确复现）。

**压测脚手架契约（务必遵守）**: `PendingChoice.choose()` **只结算、
不出队**（TEST_SOP §8）。解析循环必须
`choice = game.pending_choices.pop(0); choice.choose(...)`。不 pop 会把
同一个选择反复结算（2026-09-01 教训: 曾因此把一次 Dark Gift 结算
数百次 → 18k 待入手队列 + `_begin_recruit_for` 假死，并一度误判为
引擎的"无界队列"缺陷）。**任何 harness 都要先核对引擎的队列契约**。

## 14. 对抗审计（adversarial verification）——修复后必做

修复工作单必须由一个**独立的**复核作业用运行时探针逐条证伪（不能看
docstring/测试名）。2026-09-01 首次对抗复核 20/22 条通过、2 条被证伪，
两条都是四件套与压测都发现不了的类型:

1. **"有读取方但读取方从不被调用" = 假接线**（W3 盲区）:
   `BG32_MagicItem_802` 写入 `ELEMENTAL_EXTRA_ATK/HEALTH`，读取方
   `batch_consume.elemental_buff()` 存在（W3 因此通过）却**没有任何
   生产调用点**——真实元素 give-效果数值不变。教训: 断言"某某原语
   已接线"时，必须证明**调用链从真实卡牌路径可达**（写 probe 用真实卡
   触发），并可用 AST 测试守住"消费点存在"这一前提。
   规则: **tag 类原语（EXTRA_*/倍率）必须有生产消费点，否则对应的
   卡一律 DEFERRED，不得注册。**
2. **`Discover.count` 是选项数，不是发现次数**: `Discover(hero,
   count=1)` 产出**单选**发现（退化）。文本 "Discover a minion" 恒为
   引擎默认 3 选项; 需要多次发现就实例化多个 `Discover`。审计时搜索
   所有 `Discover(..., count=` 实参。
3. 复核还要检查**测试是否在断言 bug**（如 `len(options)==num(0)==1`）
   与**弱断言**（`>=1`、`assertGreaterEqual(count, N)` 永不钉死）——
   这类测试让"绿"失去意义。

**复核作业返回**: `FALSIFIED / NEW_ISSUES / VACUOUS_TESTS / VERIFIED_OK`
四段，逐条附复现探针与数值。

## 15. 2026-09-01 新增引擎原语（第三/四轮）

- **`Discover(golden=True)`**: 发现并授予**金色本体**（独立卡定义，
  `create_minion(golden=True)`）；预留语义与普通发现一致。用于
  "Discover a Golden Tier N minion" 族（异变 Treasure Hoard 5 张）。
- **实体级 `FROZEN`**: `refresh_tavern` 在无整馆冻结时保留带
  `FROZEN` tag 的酒馆实体，并在保留后清除（冻结只保留一轮）——
  "Freeze a minion" 类效果（整馆冻结仍是 hero 级 `hero.frozen_tavern`）。
- **Avenge 计数覆盖饰品/任务奖励**: 非随从实体以类属性
  `avenge_threshold = N` 声明阈值；引擎对 棋盘随从 + `hero.trinkets` +
  `hero.quest_rewards` 统一计数，**仅战斗内**（RULES §6.11），每场战斗
  开始清零。
- **饰品商店档位池**: `db.trinket_offer_pool()`（排除 token 与升级变体）
  + `CardDef.spell_school`（11=Lesser / 12=Greater）；`_offer_trinkets`
  按 kind 过滤。
- **`CardType.BACON_SPELL = 42`**（酒馆法术，此前解析为 INVALID）。
- **`game.inject_tavern_minion(hero, card_id, *, position=None,
  golden=None)`（2026-09-02）**: 向酒馆展示区注入随从的**唯一入口**——
  自动套用 The Golden Arena 金色化（+`GILDED_NOT_TRIPLED`）与
  `hero.tavern_buffs` 持久面。**禁止**脚本自行
  `create_minion + tavern.append`（对抗审查实测 Ysera 额外龙在金馆下
  非金、Elven Elite 下越档; 此类旁路曾有 8 处）。池记账仍由调用方
  负责（抽卡 acquire / 复制体不占池）。
- **额外触发配额（2026-09-02 第六件引擎原语，RULES §6.20）**:
  `hero.extra_triggers[key] = N` 声明永久额度，引擎在对应触发点消费
  `hero.extra_trigger_used`（每回合/每场战斗自动重置）: `eot_extra` /
  `soc_extra` / `soc_first` / `dr_first` / `dr_extra` / `rally_extra` /
  `spell_first` / `spellcraft_first` / `hp_uses` / `bc_times`（±`bc_race`，
  单独声明 = 全种族）。覆盖
  "Your (first) X effects trigger an extra time" 全族——禁止在卡脚本里
  自己写计数器重放效果。

## 16. 2026-09-02 对抗审查轮：英雄主动技能 / 异变·奖励批 2 / 饰品批 3

三个独立 subagent 用运行时探针逐卡证伪（方法见 §14），命中 3+3+1 处
语义缺陷、2 处引擎缺陷、37 条空转测试。**全部修复后四件套 + 压测复绿**。
新增的缺陷模式（继续追加，勿删）:

15. **"随机施放法术"必须处理无合法目标**: 被动/随机施法（Yogg
    "Puzzle Box"）在空板时曾以 `ctx={"target": None}` 硬施放定向池法术
    → fail-loud 脚本抛 `GameStateError` 穿出 `_begin_recruit_for`，
    **整个招募回合中断**（压测 2/146 空板回合命中）。规则: 随机施法前
    按 `scripts.target_candidates`（未声明则友方棋盘）取候选，
    **无候选 → 该次落空并回滚池记账**（acquire 后必须 release）。
16. **"until next turn" = 下一个招募阶段开始（单 tick）**: 两级 once
    链会让效果多活一整个回合（Lich King "Reborn until next turn" 实为
    "After 2 turns" 语义）。同文件里 "After 2 turns" 才用 2 tick
    （Maiev）。**写"持续到某时点"前先对照 `scripts/spells.py::
    _expire_at_next_turn` 与 RULES §6.13**。
17. **金色化实体的回池必须走 `TRIPLE_BASE_CARD_ID`**: 异变 The Golden
    Arena 下馆内实体 `card_id` 是金卡 def（`is_pool_minion=False`），
    `minion_pool.release(e.card_id, 1)` 静默 no-op → 基础副本泄漏
    （Toki/Tess 实测）。**任何"移出酒馆/棋盘后回池"的脚本先取
    `e.get(GameTag.TRIPLE_BASE_CARD_ID, None) or e.card_id`**。
18. **保留下手前先采集冻结集**: `refresh_tavern` 会把保留项的实体级
    `FROZEN` tag 清掉（"只保留一轮"），脚本若在 refresh **之后**才判定
    哪些是保留项，就会把单卡冻结随从当"新抽"移出（Toki/Tess）。
19. **"扣 N 返 M" 必须配平**: 金色产物若只从池扣到 <3 份却按三连金回池
    3 份 → 每次净 +2（`Discover(golden=True)` / Accelerator / Lockbox /
    Robust Evolution 实测）。规则: 非完整三连金一律打
    `GILDED_NOT_TRIPLED`（回池 1 份）; `Transform` 用
    `gilded_not_tripled=True` 传该语义。
20. **副本共享可变 Buff 对象**: `for b in src._buffs: dst.add_buff(b)`
    让双方共用同一 Buff 实例 → 一侧过期/移除会连带清掉另一侧
    （Zerek / 三连金 / 多次"精确副本"）。**统一用
    `Entity.copy_buffs_to(dst)`**（独立复制）。
21. **"下次购买便宜 X" 只在成交时消耗**: `buy_from_tavern` 曾在金币
    检查前清零 `NEXT_SPELL_COST_REDUCTION` → 一次**失败购买**白烧折扣
    （Primordial Terrarium）。**折扣只在支付成功后清零**。
22. **EoT 翻倍光环覆盖全部己方 EoT 效果**: 文本 "Your end of turn
    effects trigger twice" 包含**饰品/任务奖励**，不只棋盘随从
    （Charging Staff / Gilded Anchor / Aggem Sticker / Exquisite
    Dishware / Enigmatic Headstone 曾少数一次）。
23. **"highest-Health" = 当前生命**: 英文 "Health" 是当前值，
    "maximum Health" 才指上限（多语言佐证 deDE "höchsten Leben" /
    jaJP "最も体力が高い" / koKR "생명력이 가장 높은"）。选键用
    `m.health`，不是 `m.max_health`（Boom Squad 实测证伪）。
24. **失败购买/陈旧引用的熔断**: 同一回合可对同一目标连打两张同类法术
    （Timeline Acceleration 每回合给 2 张 Accelerator）——第一张已把目标
    Transform 掉，第二张必须 `target not in hero.board` 落空，否则
    `Transform` 抛 `GameStateError` 中断回合。**定向脚本一律先查
    `isinstance(target, Minion) and not target.dead and target in
    hero.board`**。
25. **`Hero.last_combat_board` 必须在 `__init__` 定义**: 招募期可读的
    对手 API（Holmes）在第 1 回合就会访问它，而 `end_recruit_phase`
    要到首次战斗前才赋值 → `AttributeError` 崩溃（压测实测）。
    **新增 hero 级状态一律在 `Hero.__init__` 给安全缺省**。

### 16b. 2026-09-02 第十一轮对抗审查新证伪的模式（26–32）

26. **事件有监听、无生产点（死监听）**: 脚本注册 `divine_shield_lost` /
    `keyword_lost` 期望"关键词失去"，但真实伤害路径直接 `clear(tag)` 不
    广播 → 该卡 100% 空转（Divine Signet / Mechagon Adapter 实测）。
    **判定法**: 对监听的事件名全仓 grep `fire(...)` 生产点；没有生产点
    就是死监听（引擎补齐前不得注册）。**反例（真生产点）**:
    `KEYWORD_LOST` 只有 `LoseKeyword` action，而真实战斗走
    `Minion.take_damage` —— 两者都算"存在"但覆盖不到主路径。
27. **广播事件被无关方消费**: `Listener(once=True)` 且 **无 condition** 时
    `EventBus.fire` 一律纳入分发集并消费——对手的同类购买会烧掉本卡的
    once 监听器（Trip Vouchers 实测：券被对手的 Greater 购买消费；放弃
    offer 后残留监听器还被之后无关的 T9 购买销毁）。**规则**: 跨玩家事件
    的监听器必须带 `condition`（`hero is <owner>` + 事件字段判定）;
    更稳的做法是**包装本次动作的 resolve_callback**（只对自己的那次结算
    生效，天然自我清理）。
28. **多来源共用同一份状态（配额/限定 tag 互相覆盖）**: 免费随从购买的
    单 counter + 种族/关键词 tag 模型让"海盗免费"与"战吼免费"退化成
    "海盗战吼才免费"（两份额度一并作废）。**规则**: 多来源叠加的状态一律
    用 `{source: {...}}` 独立记账（`game.set_free_minion_buys(hero, n,
    source=, race=, keyword=)` 为范例），并给独立的失效条件（如 turn 戳）。
29. **一次性资源用覆盖式写入**: `set(NEXT_SPELL_COST_REDUCTION, 1)` 抹掉
    同 tag 上其它来源的累计折扣（Lubber Sticker 实测每回合净丢 2 金）。
    **规则**: 一次性折扣/额度用 `max(现有, N)` 或显式消费点; 且只在
    **成交**时消费（失败购买不烧）。
30. **"我的"对象用全局并集记账**: 饰品"你已经拥有的"应为 per-player
    （`hero.trinkets_granted`），旧实现读全桌并集 → 对手拿到的饰品从我的
    候选池永久消失。**规则**: "you/your" 语义的状态一律挂在英雄/实体上;
    game 级聚合只用于观察。
31. **候选集的隐含边界**: 随机/发现获取必须封顶 `game.max_tavern_tier`
    （标准局 6；显式 `min_tier=7` 才越档）——旧的 `max_tier=None` 会给出
    T7 随从（实测 8.7% 采样）。同时确认**关联卡的类型**：文本 "Get a
    Butchering" 的关联卡是 `card_type=42` 的**池法术**，用
    `create_minion` 会造出 0 血死随从且池永不扣减（`grant_card_copy_to_hand`
    按类型分派）。
32. **光环用"入场即 buff"近似会漏路径**: 任何不经 `game.summon` 的入板
    路径（`Transform`、Jandice 直接 `board[idx]=`）都拿不到 buff。
    **规则**: "Your minions (from Tier N or lower / of type X) have +X/+Y"
    用真光环读取点（`hero.race_auras` / `game.add_tier_aura`），不要用
    一次性 buff + SUMMON 监听。

33. **测试自身的全局状态卫生**: 测试里 `REGISTRY[id] = 桩类` 后必须
    **保存/还原**（`del` 会让同文件后续依赖该真实脚本的测试失效——
    `test_engine_gaps` 实测）。引擎/脚本状态（REGISTRY、模块级常量、
    `game.` 单例）在测试中一律"改了要还原"。

34. **被重放/被转移的钩子不得读宿主卡定义**: Roadboar 收集亡语后在自己
    死亡时重放（`fn(source=宿主, ...)`）→ 被重放脚本若读
    `db.get(source.card_id).num(0)`，宿主卡没有该字段 → `None` 参与运算
    崩溃（Locked-up Mutineer 压测实测）。**规则**: 重放方在 `ctx` 里携带
    `deathrattle_card_id`（或同类来源标识），被重放脚本优先读 ctx、再回落
    宿主，缺数据则**落空**而不是抛错; 引擎侧对 API 参数做 None 防御
    （`open_lockbox_early(turns=None)` → 至少 1 回合）。

35. **多实例共用 kind 级事件归属**: 同一英雄持有两张同款饰品（副本条款）
    时，若脚本用**全局 kind 常量**过滤 `card_discovered`/自定义事件，每份
    副本的监听器都会认领同一次结算 → 状态互相覆盖（Portable Factory 实测:
    两份副本的 pick 都变成最后一次、手牌三张同名误合成金色）。**规则**:
    实例私有状态用**实例级 kind**（`f"{KIND}:{source.uuid}"`）或把值写进
    自建 `PendingChoice.resolve_callback` 闭包；测试必须覆盖"两份副本"
    场景（`grant_trinket(..., duplicate=True)`）。

### 16c. 2026-09-02 第十二/十三轮对抗审查新证伪的模式（36–43）

这批的共性: **五件套全绿仍漏**——缺陷都在"事件选择/返回语义/事件顺序/
被动重接线"这类契约层，静态审计看不见。派发新批次时必须对每张卡做运行时
探针，且探针要覆盖下面的边角路径（双施 / 满手 / Titus / Transform）。

36. **per-play 事件用于 per-cast 文本**: `card_played` 与
    `spellcraft_cast` 每次**打出**只广播一次 → 双施（`SPELL_DOUBLER` /
    `spell_first` / `spellcraft_first`）与效果施法（`cast_spell_effect`）
    全部漏算。**规则**: "After/Whenever **you cast** a spell" 必须监听
    `spell_resolving`（含 `SPELLCRAFT` tag 过滤判别法术塑造）; "play a
    card / play a Naga / play a Blood Gem from hand" 才用 `card_played`。
    证伪: Bloodbound Earrings / Coral Spear `BG35_MagicItem_925` /
    Lovely Locket `BG36_MagicItem_211`（后者还需**重入闸**，见 §7.4.10）。

37. **"已授予"返回值把"已排队"当"落空"**: 满手时副本进
    `pending_hand_queue`（必然交付），但额度类脚本据返回值扣额度 → 满手
    可以无限白拿（Funeral Wreath `BG36_MagicItem_217` 6 次复生全排队、
    `_wreath_left` 仍 3; Transcribing Typewriter `BG35_MagicItem_931`）。
    **规则**: `grant_card_copy_to_hand` 的 True 语义 = "副本已产生"（含
    入队）; "是否已持有 X" 类分支判定必须**手牌 + 排队双查**（Lockbox
    Portrait `BG36_MagicItem_301`）。测试必须加"满手"用例。

38. **在事件里给实体打标 + 依赖注册顺序**: 酒馆 Buff 类效果在
    `tavern_refresh` 监听里遍历当前酒馆打标 → 同一事件内**更晚注册**的
    监听器（Laboratory Assistant `BG35_150` 的 Fodder）append 的实体恒
    漏（Cursed Crystal `BG35_MagicItem_150` / Defiler Portrait
    `BG35_MagicItem_151`，实测同一 setup 下"饰品先绑 → Fodder 2/2、随从
    先打 → 6/6"）。**规则**: 走 `game.add_tavern_entity` /
    `tavern_entity_added` 入馆观察点（RULES §7.4.9），或改为读取时求值
    的光环面; 禁止依赖监听器顺序。

39. **"Trigger a Deathrattle" 直调 `run_script_hook`**: 绕开
    `dr_times` 链（Titus / `dr_extra` / `dr_first` / 计数 / 事件）→
    Titus 在场与不在场结果相同。**规则**: 一律走
    `game.trigger_deathrattle`（RULES §6.20）。

40. **Transform 之后的被动失效**: 换卡面只替换实体、不重跑被动初始化 →
    变身成 Titus/Drakkari/Groundbreaker 家族完全空转（`BG35_MagicItem_924`
    实测: 变身本体 6/4 不变、只有镜像饰品给左邻增益）。**规则**: 在
    `on_summon` 里注册监听器/设被动 tag 的卡必须同时实现 `on_transform`
    （引擎在 `transform` 后派发，RULES §6.21）。

41. **额度型 `Discover` 的选项数退化**: "Discover N" 的候选配对算法遇到
    "某候选无合法搭配"时直接少给一个选项（`BG36_MagicItem_309` Wax Lance
    的 T7 三人组只给 2 个 Dark Gift 选项）。**规则**: 复用引擎的配对 +
    **换候选重抽**语义（`Game._pair_gifts`）; 测试断言 `len(options) == N`
    而不是 `>= 1`（后者正是掩盖本缺陷的弱断言）。

42. **针对"每次"字样的自造去重**: 卡面写 "After the Tavern is Refreshed,
    give its minions +X/+Y this turn" 却在脚本里加"同回合同一实体只 buff
    一次"的私有去重 → 冻结 + 反复刷新时少叠加（Cursed Crystal 实测 4 次
    刷新只有 1 个 (3,3)）。**规则**: 无官方 Notes 支持的去重就是近似实现;
    "this turn" 类限制由**回合过期**表达，不由去重表达。

43. **一次性配额的"落空不消耗"与"已排队算成功"必须区分**: 池空/无合法
    目标 → 不扣额度（Primordial Terrarium 口径）; 已入等待队列 → **扣
    额度**。两者在旧的 bool 返回值里同形，必须按语义拆（见模式 37）。

**空转测试的判定法（新增验收工具）**: `python tools/audit_vacuous_tests.py
[--strict]` —— 对每个 `batch_*.py` + 同名测试文件，把该批全部脚本类的
钩子替换成 no-op 后重跑，报告"两次都通过"的测试（存活者）。`--strict`
的门禁口径: **任意测试类的全部通过测试都是存活者 = 类级全空转 → exit 1**
（类级全空转是最坏第三态的下限）。结构性测试（注册表/卡定义/数值一致性/
DEFERRED 台账守卫/引擎数据通道）允许存活，可用类 docstring 里的
`@engine-only` 显式标注。

手工版判定法（无工具时）: 把被测脚本类的全部 hook
（`on_bind`/`hero_power`/`start_of_combat`/`end_of_turn`/`avenge`…）
替换成 `pass` 后重跑测试；**仍然通过的测试对"效果是否存在"零信息量**。
常见重灾区:
  - 纯负面断言（"空板落空"/"对手不触发"）——必须补**正对照**（同
    setup 下有效果路径确实发生）;
  - 战后回滚断言——必须在战斗内插探针（监听 `start_of_combat`，且
    注意该事件每英雄各广播一次，探针要按 `hero is` 过滤）;
  - 只重读输入值的断言（"T6 上限还是 T6"）——必须断言**产物身份/池变化**。

## 17. 项目所有者裁定的权威序（2026-09-18）

> 本节由**项目所有者直接裁定**（第四十九轮任务族落地时下达），属政策记录，
> 不是从既有文档推导出的结论。

**权威序**:

1. **wiki 详细说明 > 卡面自然语言理解**。hearthstone.wiki.gg 有详细说明处
   → **wiki 权威**: 必须记录页面 URL + oldid/修订号 + 逐字引文（含所依赖
   的每个数值）。
2. wiki 无详细说明处 → 实现**卡面文字的自然语言解读**（含边界），并把
   解读及其边界写进脚本的类/模块 docstring。
3. **仍禁止**（铁律不变）: 注册但空转、静默第三态、卡面明确处简化实现、
   真实路径测试缺失、非变异敏感的负对照、三段式 docstring 缺失、以文档
   改写洗白近似。
   - 文档只记录现实。本节（政策本身）**只能**作为"项目所有者裁定"记录，
     不得被援引去合法化任何别的近似实现。

**与既有条款的关系**: 本节**不削弱** §3（语义精确性核对表）、§6b（二态
铁律）、§11（接线审计与 no-op 第三态）、§13/§14（压测与对抗审计）与
「空转测试的判定法」。当旧 DEFERRED 理由与本节冲突时，按本节重写理由，
但**必须**同时满足: (a) 记录新的权威来源（wiki URL/oldid + 逐字引文，或
自然语言解读及其边界）; (b) 不删除任何仍然成立的阻塞，只把失效的那一条
替换为"已由 XXX 解决"并保留可追溯的旧记录摘要; (c) 对被替换的近似边界
（如不模拟逐局 ±修正、`buff_applied` 的复制/重放旁路）**显式记档**为
已知近似，而不是声称完全精确。

**首例**: 任务族（`docs/agents/QUEST_DEFERRED_SPEC.md` 2026-09-18 重写）
——旧「四因子缩放无数据源 → 整族 DEFERRED」被"wiki 各卡页 baseline
requirement 当前值"取代; 1 张真权威缺口（`BG24_Quest_328` "Win the
game."）与 2 张公告 token 仍保持未注册。
