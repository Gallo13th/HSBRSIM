# HSRL v2 重构蓝图

> 版本: 1.0 | 日期: 2026-08-21 | 基线: Patch 36.2.2 (Season 14 "Dark Gifts of Dalaran")
> 决策: 全新包重写 (`hsrl2/`)，旧引擎 `hsrl/` 冻结只读，周边系统冻结隔离

---

## 1. 背景与动机

### 1.1 三大驱动力

1. **规则正确性缺陷**（2026-08-21 全面审计确认）:
   - P0: 一方攻击者耗尽即终止战斗→大量假平局；风怒不连续攻击；复生白板复活（丢 buff/金色）；金色战吼不双倍；池泄漏（刷新/淘汰不回池、Discover 不占池）
   - P1: MAX_GOLD 当回合截断收入；Venomous 反击致死仍触发；任务奖励 SoC 死代码；AFTER_ATTACK 先于伤害结算
   - P2: 冻结三重偏差（含 +2/+1 发明效果）；幽灵伤害缺基数；升级费下限 1≠0
   - 卡牌层: 16+ 处脚本硬编码数值与 XML `{0}/{1}` 参数不符（Goldrinn 4→8、Last One Standing 2→12 等）、BG28_601 注册覆盖 bug
   - 根因: 数据管线丢弃模板参数 → 脚本凭记忆硬编码 → 补丁更新后静默过期
2. **专注点收窄**: 只做**自动化、完全精准的对局模拟**。RL 训练栈（policy/rl_env/agents）、HDT 插件（advisor）、CLI/CUI、trajectory 全部冻结隔离——不参与重构、不承诺兼容，通过稳定 API 边界解耦
3. **S14 大更新**（36.2.2）: Dark Gifts 发现系统（43 种）、Activate 关键词、Lockbox（海盗）、Fishbait（野兽）、Venomous 改为每场战斗重置、Chromadrake 移出酒馆池、96 移除/62 新增/31 回归随从、47 张新饰品、2 新英雄

### 1.2 旧架构保留的价值（吸取不抛弃）

- **tags + Action + 事件** 三层模型本身健全，v2 保留其精神
- CardDefs.xml → JSON → CardDB 的数据流方向正确，但管线有缺陷（已修复）
- `@staticmethod` 脚本钩子模式经过 805 张卡验证，v2 延续并强化签名

---

## 2. 新包结构

```
hsrl2/                        # 新模拟核心（唯一活跃开发目标）
├── __init__.py
├── constants.py              # 所有规则常量（单一事实来源，出处标注 RULES §x）
├── tags.py                   # GameTag / CardType / Race / Zone 枚举（与 XML enumID 对齐）
├── defs.py                   # CardDef 不可变蓝图（含 script_data_num_1/2 模板参数）
├── db.py                     # CardDB: 从 data/*.json 加载，含金色版（triple_upgrade_id）
├── rng.py                    # GameRNG: 全随机走 game.rng，可 seed 可回放
├── entity.py                 # Entity 基类: tags + buffs + 脚本钩子分发
├── minion.py                 # Minion（含 Activate/Venomous 状态）
├── hero.py                   # Hero/Player: 金币/护甲/酒馆等级/手牌/棋盘
├── spell.py                  # Spell: 酒馆法术/血宝石/Dark Gift/Lockbox
├── events.py                 # 事件总线 + 监听器生命周期（随实体离场自动注销）
├── queue.py                  # Action 队列: 波次结算 + 防死循环（超限报错非静默）
├── pools.py                  # 共享池: draw/return 严格配对 + 审计接口
├── combat.py                 # 战斗调度器（正确时序，见 §4）
├── game.py                   # Game: 回合状态机 + 招募操作 + 战斗编排 + 伤害/幽灵
├── actions/                  # Action 实现（按域拆分）
│   ├── base.py               # Action ABC + TargetedAction
│   ├── stats.py              # Buff/GainKeyword/LoseKeyword/Transform
│   ├── combat.py             # Hit/Attack/Cleave 结算
│   ├── summon.py             # Summon/Reborn
│   ├── economy.py            # SpendGold/GainGold/Upgrade/Freeze
│   ├── discover.py           # Discover(池感知)/GetRandomMinion/DarkGift
│   └── s14.py                # Activate/OpenLockbox/FishbaitAttack/GiveDarkGift
├── scripts/                  # 卡牌脚本（SOP 驱动、subagent 批量迁移）
│   ├── minions.py
│   ├── heroes.py
│   ├── spells.py
│   ├── trinkets.py
│   └── registry.py           # card_id → script 绑定 + 加载校验
├── audit/                    # 语义审计工具（文本参数 ↔ 脚本常量自动比对）
│   └── param_check.py
└── tests/                    # 不变量测试（每个 P0 修复一个测试）
```

冻结区（不修改、不承诺兼容）: `hsrl/`、`hsrl/policy/`、`hsrl/rl_env/`、`hsrl/agents/`、`hsrl/advisor/`、`hsrl/cui/`、`hsrl/cli/`、`hsrl/trajectory/`、`hsrl_advisor/`

---

## 3. 数据链路（已修复并重建）

```
hsdata/CardDefs.xml (36.2.2.249896, git 子模块)
  │  tools/generate_bg_data.py (v2)
  │  ✅ 修复: script_data_num_1/2 全量导出（{0}/{1} 模板参数）
  │  ✅ 新增: activate/activate_cost (tag 4089/4090)
  │  ✅ 新增: dark_gift (tag 4855) → bg_dark_gifts.json (43 张)
  │  ✅ 新增: evolution_card_id (2519, Lionfish→Fishbait 等进化链)
  │  ✅ 新增: subset_* 标志 / spell_school / unplayable (Lockbox)
  ▼
data/*.json (已重建, 备份于 data/backup_35.6.0/)
  ▼  hsrl2/defs.py + db.py
CardDB (含金色版本体: triple_upgrade_id 指向独立卡牌定义)
```

**关键设计**: 金色随从不再"数值×2 + 效果×2"近似——CardDefs 中金色版是独立实体
（有自己的文本/数值/参数），v2 直接加载金色本体定义。

**权威信源层级**（冲突时以上层为准）:
1. `hsdata/CardDefs.xml`（Blizzard 官方导出，数值/关键词/模板参数的唯一事实来源）
2. `docs/BATTLEGROUNDS_RULES.md`（流程/时序/交互规则，需更新到 36.2 基线）
3. 官方补丁说明（playhearthstone.com，机制语义的最后裁决）
4. hearthstone.wiki.gg（补充交互细节，Cloudflare 受限时用爬虫存档）

---

## 4. 战斗调度器正确性规范（v2 核心交付）

| # | 不变量 | 旧实现缺陷 |
|---|--------|-----------|
| C1 | 风怒随从**连续**攻击两次，中间不插入对方攻击 | 每次 swap sides，风怒被拆开 |
| C2 | 一方无可用攻击者时**跳过该方**继续轮转；仅当一方无存活随从或双方均无法攻击才结束 | attacker=None 直接 break → 假平局 |
| C3 | 攻击双向伤害**同时结算**: 双方 Hit 都入队执行完 → 死亡波次 → Venomous 存活判定在双向伤害之后 | Venomous 在受击方 Hit 内判定，反击未结算 |
| C4 | `AFTER_ATTACK` 在伤害与死亡结算**之后**广播 | 在 Attack.do() 内同步广播，先于伤害 |
| C5 | 顺劈: 主目标+相邻在 同一伤害窗口 结算（实体引用在宣告时锁定） | 顺序偏差 |
| C6 | 复生: 原位、1 血、**保留 buff/金色/其他关键词**，仅移除 Reborn；亡语先、复生后 | 白板复活 |
| C7 | 剧毒: actual_damage>0 才触发; 圣盾完全抵消则不触发 ✓（保留旧实现正确部分） | — |
| C8 | Venomous (S14): 每场战斗重置——消耗后在下一场战斗开始时恢复 | 旧版永久消耗 |
| C9 | 0 攻随从跳过且不占用攻击轮 ✓ | — |
| C10 | 多嘲讽随机、先攻=多者/平随机、SoC 先于先攻判定 ✓ | — |
| C11 | 伤害 = 胜方酒馆等级 + Σ存活随从 tier（token=T1，金色无加成）; 上限 5/10/15、剩4人解除 | ✓（幽灵战漏 tier 基数，修复） |
| C12 | SoC 触发顺序: 饰品 → 任务奖励 → 随从 → 英雄技能 | 顺序颠倒 + 任务奖励死代码 |

## 5. 池与经济规范

| # | 不变量 | 旧实现缺陷 |
|---|--------|-----------|
| P1 | 每次 draw 配对 return: 刷新丢弃回池、出售回池(金色3份)、淘汰全回池 | 三处泄漏 |
| P2 | Discover/GetRandom 候选**受池剩余量约束**，选中即从池移除 | 不查池不占池 |
| P3 | 金币: 每回合基础收入 min(2+turn,10) **覆盖式重置**（不储蓄），回合内收入叠加，持有上限 99 | MAX_GOLD 设为基础值导致截断 |
| P4 | 升级费: 基础 5/7/8/9/10/11，每回合未升级 -1，**下限 0** | max(...,1) |
| P5 | 冻结: 整馆冻结（随从+法术），手动刷新保留冻结内容，无发明 buff | 粒度错+刷掉+2/+1 |
| P6 | 手牌满 10: 生成卡排队等待（延迟到有空位），不销毁 | 血宝石丢弃 |
| P7 | Spellcraft 随从打出**立即**获得第一张法术 | 下回合才有 |
| P8 | 淘汰玩家全部卡回池 | 未实现 |

## 6. S14 新机制实现规范

### 6.1 Activate（tag 4089/4090）
- 招募阶段点击棋盘上的 Activate 随从 → 花费 activate_cost 金币 → 触发其 `activate` 脚本钩子
- 每随从每回合 1 次（`ACTIVATE_USED_THIS_TURN` tag，回合开始清零）
- 金色版数值由金色卡定义决定

### 6.2 Dark Gifts（tag 4855，43 张 `BG36_MidGameEffect_000t*`）
- 第 3 回合起: Dark Gift 按钮，3 金，Discover 三选一（每张随从绑定一个**不同** Dark Gift）
- 每回合 1 次，每局最多 3 次；奖励随回合数提升（tier 随 turn 上升: Tier ~ turn 曲线按官方 `#EXPANDLIST(@3,@4)` 语义）
- 选中随从 + 绑定的 Dark Gift（一个持久 enchantment，效果各异: +10攻/双倍/每场保留关键词/Immune 攻击时…）
- 交互: Gilding（金色但无三连奖励）、Persisting Horror（复生满血+关键词）等需要引擎级标志

### 6.3 Lockbox（`BG36_520t`，ct=5 不可打出手牌牌）
- 获得 Lockbox → 进手牌，5 回合后自动开启 → 随机金色有种族随从
- Bilgewater Breakout 等卡可使其提前 1 回合开启
- 引擎: 手牌内倒计时实体，回合开始检查

### 6.4 Fishbait（`BG36_205`，1 血 token 随从进酒馆）
- 效果将酒馆中一张卡替换为 Fishbait → 最左侧野兽**在招募阶段攻击它**
- Fishbait 死亡 → 亡语: 击杀者 +5/+5（"can't gain stats"）
- 引擎: 招募阶段局部战斗（single attack + deathrattle），Venomous 消耗在此适用且每场战斗重置

### 6.5 其他 36.2 全局改动
- **Venomous 重构**: "Destroy the first minion this deals damage to **each combat**" — 消耗制 + 战斗开始重置
- **Chromadrake**: 移出可购池（subset_dragon 过滤），仅由生成效果出现
- 新英雄: BG36_HERO_101 Tras'tath / BG36_HERO_105 Xavius
- 英雄改动: Cariel 0费、Edwin 4张、Saurfang 3随从、Ragnaros 12张、Rakanishu 每3回合、Tae'thelan 每3法术、Enhance-o 双倍（详见 docs/S14_DIFF_REPORT.md）

---

## 7. 迁移路线（里程碑）

| 阶段 | 内容 | 验收 |
|------|------|------|
| M0 ✅ | hsdata→36.2.2、生成器 v2、数据重建、S14 差异报告 | 本文 §3 |
| M1 | hsrl2 骨架: tags/defs/db/rng/entity/events/queue/pools + 战斗调度器 | C1-C12 不变量测试全绿 |
| M2 | game.py 回合状态机 + 经济 + 池生命周期 + Discover 队列化 | P1-P8 不变量测试全绿 |
| M3 | S14 机制: Activate/DarkGift/Lockbox/Fishbait/Venomous 重置 | §6 专项测试 |
| M4 | 脚本迁移（subagent 批量）: 247 池随从 → 75 法术 → 116 英雄 → 379 饰品 → 108 异变 → 73 奖励 | audit/param_check 全绿 + 每卡语义测试 |
| M5 | 8 人完整对局模拟 + 种族禁用 + 幽灵/配对 + 种子回放 | 端到端对局 + 回放一致 |
| M6 | 文档收敛: RULES 更新至 36.2、废弃旧审计文档归档 | 文档间零矛盾 |

## 8. Subagent 作业体系（核心工作流资产）

见 `docs/agents/` 三份 SOP:
- `CARD_ENTRY_SOP.md` — 卡牌录入（数据→注册→金色绑定）
- `EFFECT_SCRIPT_SOP.md` — 效果脚本（语义规格→实现→参数校验）
- `TEST_SOP.md` — 语义测试（三段式 docstring 对应断言）

原则: subagent 只做**机械可验证**的重复工作；引擎机制改动、时序语义裁决必须主线完成。
每次 subagent 任务必须以 `python -m pytest hsrl2/tests/ && python tools/audit_card_registry_v2.py` 绿灯收尾。

---

*本文件是重构期唯一活跃的架构权威。旧文档（MECHANICS_REFERENCE/MAINTENANCE_GUIDE/combat_rules 等）描述旧引擎，仅作历史参考。*
