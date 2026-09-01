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
