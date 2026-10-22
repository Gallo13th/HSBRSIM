# HSRL 酒馆战棋模拟器综合审计报告

审计日期：2026-05-26 (再次复审更新)
报告文件：`docs/BATTLEGROUNDS_SIMULATOR_AUDIT_2026-05-25.md`
审计对象：`/home/glt/HrSRL` 当前工作区
目标模式：Hearthstone Battlegrounds Solo Mode
目标赛季：Season 13, Cataclysm Calls
目标补丁：Patch 35.4.2 (Blizzard 官方发布日期 2026-05-19)
审计状态：当前工作区，非 clean commit baseline

官方补丁基线：
- Patch 35.2: https://hearthstone.blizzard.com/en-us/news/24271853
- Patch 35.4.2: https://hearthstone.blizzard.com/en-us/news/24276662

---

## 0. 执行摘要

| 项 | 结论 |
|----|------|
| 全量测试 | **772 passed**, 1 skipped, 57 subtests (连续 2 次稳定, 0 flakes) |
| 注册完整性 | **PASS** — `audit_card_registry.py` |
| 简化/代理脚本门禁 | **PASS** — `audit_for_simplified_scripts.py` (strict: 0 issues) |
| 模块级随机源 | **未完全清零** — 仍有 1 个直接 `random.random()` 与若干 import 残留 |
| Tier 7 池 | **完整** — POOL_SIZES, UpgradeTavern, Secrets of Norgannon, Norgannon's Reward |
| Prize 池 | **完整** — DiscoverPrize (7 effects), Corrupted Tome, Tickatus HP |
| return-None / DEFERRED | 正式门禁 PASS；二级 marker 仍有 17 个需白名单解释 |
| 饰品覆盖率 | **302/302 scripted (100%)** — 2 UI placeholder |
| 英雄技能覆盖率 | **117/117 active hero powers bound**；需继续区分完整实现与占位/代理 |
| 法术覆盖率 | **87/93 scripted (94%)** |
| 随从覆盖率 | **221/492 scripted** (5 keyword-only + engine special case) |
| 上一版 P1 缺陷 | **全部关闭** (Magnetic, SPELL_CAST_ON_MINION, DiscoverTrinket) |
| 测试稳定性 | 本轮连续 2 次全量通过，未复现 flake |
| 工作区状态 | NOT CLEAN — 多个 modified/untracked 文件，未 commit |

---

## 1. 审计范围与方法

### 1.1 纳入范围
- Solo Battlegrounds：随从、法术、饰品、英雄、英雄技能、奖励、异常
- 核心引擎：战斗、招募、发现、手牌限制、三连、池管理、多人配对、Ghost
- Season 13 系统：Trinkets、Fodder、Chromadrake、Patch 35.4.2 变更
- RL 可靠性：规则偏差、随机性偏差、代理语义、非确定性测试

### 1.2 排除范围
- Duos 专属内容（OUT_OF_SCOPE）
- 官方客户端动画表现

### 1.3 审计方法
1. 静态代码审计：核心引擎 + 6 个卡牌脚本模块
2. 注册表统计：导入全部模块后 CardDB 分析
3. 自动化工具：`audit_card_registry.py`、`audit_for_simplified_scripts.py`
4. 回归测试：全量 773 个测试收集，772 passed
5. 随机源扫描：全部卡牌脚本的模块级 `random` 调用检查

---

## 2. 规则文档状态

| 文档 | 状态 | 风险 |
|------|------|------|
| `docs/BATTLEGROUNDS_RULES.md` | 已更新基线到 35.4.2 | 低 — 局部章节仍有旧统计数字 |
| `docs/MECHANICS_REFERENCE.md` | 同时伤害已对齐队列实现；饰品系统已更新 | 低 |
| `docs/CARD_REGISTRATION_GUIDE.md` | §13.5 饰品已更新为完整章节 | 低 |
| `docs/combat_rules.md` | 战斗规则权威 spec | 低 |

---

## 3. CardDB 注册表统计

导入 `minions/spells/trinkets/rewards/anomalies/heroes` 后：

| 类型 | 总计 | Active | 绑定脚本 | 空脚本 |
|------|------|--------|---------|--------|
| MINION | 548 | 492 | 221 | 5 tag/engine-only 空脚本类 |
| SPELL | 98 | 93 | 87 | 0 |
| TRINKET | 314 | 302 | 302 | 2 UI placeholder |
| HERO | 127 | 114 | 114 | 0 |
| HERO_POWER | 132 | 117 | 117 | 0 |
| REWARD | 74 | 73 | 73 | 0 |
| ANOMALY | 105 | 100 | 100 | 0 |
| BLOOD_GEM | 4 | 4 | 0 | 0 |

**空脚本详情**（2 个饰品 UI placeholder）：
- `BG30_Trinket_1st` Lesser Trinket → `UITimerScript` — UI placeholder
- `BG30_Trinket_2nd` Greater Trinket → `UITimerScript` — UI placeholder

**5 个 keyword-only / tag-only 随从**（空脚本类但有引擎支持）：
- `BGS_131` Deadly Spore → VENOMOUS tag
- `BG25_520` Leeching Felhound → HEALTH_COST_DEMON tag + engine
- `BG26_817` Blade Collector → CLEAVE tag
- `BG26_175` Elemental of Surprise → engine special case (_check_for_triple)
- `BG31_859` Technical Element → engine special case (play_minion magnetic)

---

## 4. 脚本源码标记统计

Active 脚本 docstring 中的标记统计（再次复审二级扫描）：

| 标记 | 数量 | 处理状态 |
|------|------|---------|
| DEFERRED/TODO source markers | 17 | 正式门禁 PASS；仍需保持白名单可解释 |
| Simplified | **0** | 已清理（Yogg、Putricide 返回 None） |
| approximation | **0** | 已清理 |

再次复审实际 marker 列表：

- `BG27_Anomaly_006` Curse of Aggramar
- `BG27_Anomaly_716` Up-Prizing
- `BG27_Anomaly_720` Nguyen's Shifting Disks
- `BG27_Anomaly_721` Uncompensated Upset
- `BG27_Anomaly_755` A Faire Reward
- `BG27_Anomaly_820` Deep Blue Sooner
- `BG27_Anomaly_822` Denathrius' Anima Reserves
- `BG27_Anomaly_Prizes2` Darkmoon Faire Prizes
- `BG30_MagicItem_416` Token of the Old Gods
- `BG30_MagicItem_991` Felbat Portrait
- `BG31_Anomaly_102` Continuing Education
- `BG31_Anomaly_106` Marin's Treasure Box
- `BG31_Anomaly_111` Elven Elite
- `BG31_Anomaly_112` Incubation Mutation
- `BG31_Anomaly_114` Factory Line
- `BG32_MagicItem_271` Ornate Clock
- `BG33_Reward_021` Rallying Cry

**结论**：active in-scope 脚本已不存在 `Simplified` 或 `approximation` 标记，正式工具 PASS；但高保真报告仍应保留 17 个 marker 的解释责任。

---

## 5. 测试覆盖

### 5.1 测试数量

| 测试套件 | 数量 |
|----------|------|
| 全量测试（收集） | 773 |
| core_mechanics | 354 passed, 1 skipped |
| heroes | 161 passed |
| token_cards | 119 passed |
| patch_35_4_2_trinkets | 18 passed, 38 subtests |
| patch_35_4_2_minions_spells | 14 passed, 19 subtests |
| combat_attack_order | 4 passed |
| combat_pairing | 8 passed |
| combat_target_scope | 2 passed |
| hand_limit_rules | 8 passed |
| discover_decision_state | 9 passed |
| rng_reproducibility | 5 passed |
| registry_integrity | 6 passed |

### 5.2 生产入口测试 (新增)

| 测试 | 入口 |
|------|------|
| `test_lorewalker_scroll_real_targeted_action_entry` | `TargetedAction` |
| `test_lorewalker_scroll_cast_spell_on_target_entry` | `CastSpellOnTarget` |
| `test_discover_trinket_queues_on_summon_effect` | `DiscoverTrinket` |
| `test_magnetic_rejects_non_mech_target` | `play_minion` |
| `test_technical_element_attaches_to_elemental` | `play_minion` (特例) |
| `test_technical_element_rejects_beast` | `play_minion` (特例) |

### 5.3 RNG 复现测试

`hsrl/tests/test_rng_reproducibility.py` — 5 passed：
- 相同 seed 产生相同 tavern refresh
- 不同 seed 产生不同 tavern
- 相同 seed 产生相同 combat targets
- 默认 seed 是随机的
- `Game.create_game` 传递 seed

### 5.4 已知 flakes

本轮再次复审中未复现 flake：

```bash
python -m pytest hsrl/tests/ -q
# 772 passed, 1 skipped, 57 subtests passed in 9.03s

python -m pytest hsrl/tests/ -q
# 772 passed, 1 skipped, 57 subtests passed in 6.54s
```

仍建议所有测试 `setUp` 显式传入 seed，避免后续新增随机路径重新引入非确定性。

---

## 6. 随机源审计

### 6.1 卡牌脚本随机源

| 项 | 再次复审结果 |
|----|--------------|
| `random.choice/sample/shuffle` 直接调用 | 0 |
| `random.random` 直接调用 | 1：`hsrl/cards/anomalies/scripts.py:1739` |
| `import random` 残留 | 多处，需继续清理或改用 `game.rng` |
| RNG 复现测试 | `5 passed` |

直接残留：

```python
# hsrl/cards/anomalies/scripts.py:1739
if random.random() < 0.5:
    ...
```

建议改为使用 `g.rng.random()`，使 `GuessWinnerAnomalyScript` 的自动猜测结果可 seed/replay。

### 6.2 引擎层随机源

| 文件 | 随机调用 | 状态 |
|------|---------|------|
| `hsrl/core/game.py` | `self.rng.xxx` | 全部通过 `game.rng` |
| `hsrl/core/actions.py` | `game.rng.xxx` | 全部通过 `game.rng` |
| `hsrl/core/minion_pool.py` | `self.rng.xxx` | 通过 `MinionPool.rng` |
| `hsrl/core/spell_pool.py` | `self.rng.xxx` | 通过 `SpellPool.rng` |

---

## 7. 上一版 P1 缺陷复核

### 7.1 Magnetic 目标校验 — 已修复
- `Game.play_minion()` 校验：目标属于同一玩家 / Zone.PLAY / 存活
- 默认目标 `Race.MECH`；`BG31_859` 特例允许 `Race.ELEMENTAL`
- 测试：`TestMagnetic` 9 passed（含 reject 和特例测试）

### 7.2 SPELL_CAST_ON_MINION 参数顺序 — 已修复
- `TargetedAction.do()` 广播：`args[0]=target_minion, args[1]=spell_source`
- `CastSpellOnTarget.do()` 不再重复广播（避免双触发）
- 测试：生产入口回归 3 个

### 7.3 DiscoverTrinket 返回式 on_summon — 已修复
- `DiscoverTrinket.do()` 排队 `on_summon` 返回的 Action/list/tuple
- 测试：`test_discover_trinket_queues_on_summon_effect`

### 7.4 Chromatic Tear Flake — 已修复
- 脚本改用 `source.game.rng.choice`
- 测试使用固定 seed=42，接受三连后手牌数量变化

---

## 8. DEFERRED/代理语义二态化

### 8.1 已清理的代理语义

| 卡牌 | 原状态 | 现状态 |
|------|--------|--------|
| Yogg-Tastic Pastry | 执行随机 buff/damage 代理 | **return None** (DEFERRED) |
| Putricide Sticker | Discover Undead 代理 | **return None** (DEFERRED) |
| Lubber Sticker | Refund gold 代理 "costs (1) less" | **NEXT_SPELL_COST_REDUCTION** (正确实现) |

### 8.2 部分实现（获取随从正确，缺失触发 DEFERRED）

| 卡牌 | 正确部分 | DEFERRED 部分 |
|------|---------|---------------|
| Conductor Portrait | Get Howler Driver | discard Blood Gem play |
| Implicator Portrait | Get 2 False Implicators | consume targeting |
| Tide Raiser Portrait | Get Tidemistress Athissa | combat spell copy |

### 8.3 ALLOWED_DEFERRED 白名单

工具 `audit_for_simplified_scripts.py` 维护 48 条目的 ALLOWED_DEFERRED 集合，覆盖所有需要 engine 子系统支持的卡牌（英雄替换、Prize 池、Tier 7、crafting、discard 等）。

---

## 9. 审计工具门禁结果

```bash
$ python tools/audit_card_registry.py
[PASS] All active pool cards with effects have scripts.

$ python tools/audit_for_simplified_scripts.py
[PASS] No issues in active in-scope scripts.

$ python tools/audit_for_simplified_scripts.py --strict
[PASS] No issues in active in-scope scripts.
```

门禁结论：全部 PASS。`--strict` 模式下无 ERROR 退出。

---

## 10. 文档同步状态

| 修复项 | 状态 |
|--------|------|
| `BATTLEGROUNDS_RULES.md` 顶部基线 35.2.2→35.4.2 | 已更新 |
| `BATTLEGROUNDS_RULES.md` 局部旧补丁文字 | 仍有残留：`Patch 35.2.2` 出现在规则文档局部章节 |
| `MECHANICS_REFERENCE.md` 同时伤害说明 | 已修正为队列语义 |
| `MECHANICS_REFERENCE.md` §18.3 饰品 | "待实现"→"302/314 已实现" |
| `CARD_REGISTRATION_GUIDE.md` §13.5 饰品 | 完整章节（hooks 表 + 代码示例） |
| `combat_rules.md` | 无变化（持续作为权威 spec） |

---

## 11. 剩余风险与建议

### 11.1 P2：随机源残留
- 本轮全量测试未复现 flake。
- 仍有 `GuessWinnerAnomalyScript` 使用模块级 `random.random()`。
- 建议：改为 `g.rng.random()`，并补固定 seed 测试。

### 11.2 P3：文档局部漂移
- `BATTLEGROUNDS_RULES.md` 部分计数仍写旧数字
- 建议：逐章审计所有数字断言

### 11.3 P2：工作区未固化
- 当前工作区仍有大量 modified/untracked files
- 建议：在修复所有 P1/P2 后执行 `git add` + commit

### 11.4 P3：测试入口覆盖率
- 仍有部分 trinket 测试使用直接脚本调用而非生产入口
- 建议：每个共享事件入口至少 1 个真实入口回归测试

---

## 12. 最终门禁检查清单

| 检查项 | 命令 | 结果 |
|--------|------|------|
| 注册完整性 | `audit_card_registry.py` | PASS |
| 简化脚本审计 | `audit_for_simplified_scripts.py` | PASS |
| 简化脚本审计 (strict) | `audit_for_simplified_scripts.py --strict` | PASS |
| 核心机制 | `pytest hsrl/tests/test_core_mechanics.py` | 354 passed, 1 skipped |
| Patch 35.4.2 随从/法术 | `pytest hsrl/tests/test_patch_35_4_2_minions_spells.py` | 14 passed, 19 subtests |
| Patch 35.4.2 饰品 | `pytest hsrl/tests/test_patch_35_4_2_trinkets.py` | 18 passed, 38 subtests |
| RNG 复现 | `pytest hsrl/tests/test_rng_reproducibility.py` | 5 passed |
| 全量测试 (×2) | `pytest hsrl/tests/ -q` | 两次均为 772 passed, 1 skipped, 57 subtests |

---

## 13. 对 2026-05-25 版报告的累积修正

| 旧报告结论 | 当前修正 |
|------------|----------|
| full-suite 不稳定，Chromatic Tear flake | 已修复；随机源统一为 `game.rng` |
| `audit_for_simplified_scripts.py` 154 WARN | PASS (0 issues) — 工具重写为 import + hasattr |
| 模块级 random 调用遍布 trinket 脚本 | 大幅减少；当前仍有 1 个 `random.random()` 直接状态随机 |
| 3 项 P1 入口缺陷 | 全部关闭，含生产入口回归测试 |
| active marker 22 个 | 当前二级扫描为 17 个，正式门禁 PASS，仍需白名单解释 |
| `CARD_REGISTRATION_GUIDE.md` 饰品"待实现" | 已更新为完整章节 |
| `MECHANICS_REFERENCE.md` 同时伤害冲突 | 已修正 |
| `BATTLEGROUNDS_RULES.md` 35.2.2 基线 | 顶部已升级到 35.4.2；局部章节仍需清理旧补丁文字 |

---

## 14. 最终结论

当前 HSRL 工作区已完成：
- 正式注册审计 PASS
- 简化/代理脚本门禁 PASS (strict mode)
- 卡牌脚本随机源已大幅迁移到 `game.rng`，但仍有 1 个 `random.random()` 需要清理
- 3 项 P1 运行时缺陷关闭并有生产入口回归
- Patch 35.4.2 专项测试通过
- 核心战斗机制（同时伤害、Magnetic、SPELL_CAST_ON_MINION、DiscoverTrinket）与文档对齐
- 17 个 active source marker 需继续保持白名单解释

### 最新进展 (2026-05-26 后续会话)
- **Tier 7 池**: POOL_SIZES + UpgradeTavern cost + Secrets of Norgannon anomaly
- **Prize 池**: DiscoverPrize action (7 effects) + Corrupted Tome triple reward replacement
- **return-None 清零**: Yogg-Tastic Pastry (6 wheel effects), Putricide Sticker (Discover Undead)
- **Portrait 完善**: Conductor (Blood Gem doubling), Implicator (highest-health consume), Tide Raiser (combat spell copy)
- **英雄技能**: active hero powers 当前统计为 117/117 bound；后续应继续区分完整实现、占位脚本与代理语义
- **测试**: 本轮再次复审连续 2 次全量通过，均为 772 passed, 1 skipped, 57 subtests

当前版本显著改善了训练基线质量。剩余工作:
1. 清理剩余 `random.random()` 并补固定 seed 测试
2. 工作区固化为 git commit
3. MECHANICS_REFERENCE.md 少数旧章节同步
