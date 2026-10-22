# 酒馆战棋战斗结算规则

完整规范酒馆战棋战斗阶段的结算规则。本文件是 `hsrhl/engine/combat.py` 的设计文档，也是卡牌效果实现的参考基准。

## 1. 战斗流程总览

```
战斗开始
  │
  ├─ 1. Start of Combat 效果 (原始场面，clone 前)
  │     attacker_board → defender_board (依次触发)
  │
  ├─ 2. 深拷贝双方场面 (clone)
  │
  ├─ 3. 应用 Aura 光环效果
  │
  ├─ 4. 判定先手 (多者先攻; 相等 50/50)
  │
  ├─ 5. 交替攻击循环 ─────────────────────┐
  │     ├─ 选择攻击者 (最左存活未攻)        │
  │     ├─ 选择目标 (嘲讽优先, 否则随机)      │
  │     ├─ 进击效果触发 (Rally: 攻击时触发)  │
  │     ├─ 执行单次攻击结算                 │
  │     │   ├─ 顺劈: 相邻目标等量伤害        │
  │     │   ├─ 主目标伤害 (圣盾/剧毒处理)    │
  │     │   └─ 目标反击 (若存活)            │
  │     ├─ 代际队列死亡结算                 │
  │     │   ├─ 收集死亡随从                │
  │     │   ├─ 复生处理                    │
  │     │   ├─ 亡语触发 (攻击方→防守方)     │
  │     │   ├─ 复仇触发                    │
  │     │   └─ 死亡随从移除                │
  │     └─ 风怒判定 / 攻守交替             │
  │     └────────────────────────────────┘
  │
  └─ 6. 判定结果
        ├─ 一方存活随从 (atk>0) > 0 → 胜出
        └─ 双方都无存活 → 平局
```

## 2. 先手判定

```
if attacker_count > defender_count → attacker 先手
if defender_count > attacker_count → defender 先手
if equal → 50% 概率随机
```

随从数量按 `alive=True` 计数。仅判定一次，后续按交替攻击循环执行。

## 3. 攻击者选择

从己方场面按从左到右顺序选择**第一个**满足条件的存活随从：

1. 风怒且 `windfury_used=False` → 可再次攻击
2. 未攻击 (`has_attacked_this_turn=False`) 且 `attack > 0`

`attack == 0` 的随从**永不攻击**（但可被攻击/反击/产生效果）。

## 4. 目标选择

从敌方场面选择：

```
if 存在存活嘲讽随从:
    从所有嘲讽随从中随机选择
else:
    从所有存活随从中随机选择
```

## 5. 单次攻击结算

```
atk_damage = attacker.attack
def_damage = target.attack

# 顺劈: 攻击者攻击力同时作用于目标相邻随从
if attacker.cleave:
    for adj in adjacent(defender_side, target):
        deal_damage(attacker, adj, atk_damage)

# 主目标伤害
deal_damage(attacker, target, atk_damage)

# 目标反击 (若存活)
if target.alive and def_damage > 0:
    deal_damage(target, attacker, def_damage)
```

### 5.1 伤害结算 (deal_damage)

```
if target.divine_shield:
    target.divine_shield = False    # 圣盾抵消全部伤害，不触发剧毒
    return

target.health -= damage
target.damage_taken_this_combat += damage

if source.poisonous:               # 剧毒: 造成伤害后目标立即死亡
    target.health = 0

if target.health <= 0:
    target.health = 0
```

**关键规则**：
- 圣盾在剧毒判定之前检测 → 圣盾挡剧毒
- 剧毒在反击时同样生效（攻守双方）
- 顺劈的伤害具有相同的来源属性（剧毒顺劈击杀相邻目标）

### 5.2 顺劈相邻计算

从**存活随从列表**（非原始位置）中定位目标，取其前后各一个存活随从：

```
alive = [m for m in board if m.alive]
idx = alive.index(target)
adj = []
if idx > 0: adj.append(alive[idx-1])
if idx < len(alive)-1: adj.append(alive[idx+1])
```

## 6. 代际队列 (Generation Queue)

战斗死亡结算的核心规则。同一代内所有亡语和复仇触发完成后，才执行死亡检查和场面清理。

```
generation = 0
while generation < 10:
    generation++

    # 收集本代死亡: alive=True, health<=0, reborn_used=False
    newly_dead = [m for m in board if m.alive and m.health <= 0 and not m.reborn_used]

    if empty:
        # 清理之前已确认死亡的 (health<=0, reborn_used=True)
        for m: if m.alive and m.health <= 0: m.alive = False
        break

    # 1. 复生处理
    for m in newly_dead:
        if m.reborn and not m.reborn_used:
            m.reborn_used = True
            m.alive = True
            m.health = m.max_health    # 满血复活
            m.divine_shield = False    # 复生不带圣盾

    # 2. 亡语触发: 攻击方从左到右先触发，防守方后触发
    for m in newly_dead_a:
        trigger(DEATHRATTLE, m, a_board)
    for m in newly_dead_d:
        trigger(DEATHRATTLE, m, d_board)

    # 3. 复仇触发: 累计友方死亡数
    for m in board:
        m.avenge_deaths_seen += dead_on_this_side
        trigger(AVENGE, m, board)
        if triggered: m.avenge_deaths_seen = 0

    # 4. 死亡清理: health<=0 的标记为 alive=False
    for m in newly_dead:
        if m.health <= 0:
            m.alive = False
```

### 6.1 关键约束

- **最大代际数**: 10 (防止无限循环)
- **复生仅一次**: `reborn_used` 标记防止重复复生
- **复生与亡语的交互**: 复生后的随从 `reborn_used=True`，不会被再次收集为 "newly_dead"，因此不会在同一代内重复触发亡语
- **亡语中召唤的随从**: 直接加入当前场面 (`board.append()`)，可在后续代际参与战斗
- **复仇计数器**: 触发后清零；同一代内可触发多次（如需要 3 死 → 代内累积达 3 即触发）

## 7. 风怒攻击

```
if attacker.windfury and not attacker.windfury_used and attacker.alive:
    attacker.windfury_used = True   # 同一位玩家再次攻击
else:
    attacker.has_attacked_this_turn = True
    切换到对方攻击
```

风怒提供同一随从的**连续两次攻击机会**，两次攻击之间会触发一次代际队列结算。

## 8. 关键词交互矩阵

| 攻击方 \ 防御方 | 圣盾 | 剧毒 | 复生 | 嘲讽 | 顺劈 |
|---------------|------|------|------|------|------|
| 圣盾 | 互碰 | 圣盾挡剧毒 | — | — | — |
| 剧毒 | 圣盾挡 | 互毒 | 毒杀不触发复生* | — | — |
| 风怒 | — | — | — | — | — |
| 顺劈 | 仅主目标 | 仅主目标 | — | 不影响顺劈 | — |

*注: 当前实现中，剧毒将 health 设为 0 后，复生检查发生在代际队列的 "newly_dead" 收集阶段，此时若 `reborn_used=False` 且 `reborn=True`，随从将复生。

## 9. 伤害计算

战胜方对败方英雄造成的伤害：

```
damage = winner_tavern_tier + sum(minion_tier for surviving minions)
```

其中：
- `winner_tavern_tier`: 胜方酒馆等级 (1-6)
- `minion_tier`: 存活随从的星级，token 固定计为 T1
- 平局: damage = 0

## 10. 战斗边界条件

| 情况 | 处理 |
|------|------|
| 双方无攻击者 | 平局 |
| 攻击者 attack=0 | 永不选择为攻击者 |
| 防御方无人可打 | 攻击方跳过 |
| 战斗超过 100 回合 | 强制平局 |
| Monte Carlo 模拟 | 独立结算 N 次，统计胜率/平率/均伤 |

## 11. 效果集成点

战斗引擎通过以下钩子集成卡牌效果系统 (`EffectExecutor`)：

| 时机 | 代码位置 | 目标上下文 |
|------|---------|-----------|
| START_OF_COMBAT | `resolve_battle()` — clone 前 | 原始场面上的随从 |
| AURA | `_apply_aura_buffs()` — clone 后 | 除自身外的友方随从 |
| DEATHRATTLE | `_resolve_deaths_gen_queue()` | 死亡随从自身，board=本方场面 |
| AVENGE | `_resolve_deaths_gen_queue()` | 存活友方随从，累计死亡数达标 |

**注意**: C++ 原生引擎 (`_combat_native`) 不执行效果相关的 START_OF_COMBAT/DEATHRATTLE/AVENGE/AURA，这些在 Python 层的 `resolve_battle()` 总控中处理。
