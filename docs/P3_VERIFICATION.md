# P3 独立验证与验收门禁（AT 主引擎补完 37 池内内容）

> 生成：`python3 -m tools.p3_verify.run_all` ｜ 2026-10-26T14:37:23 ｜ 耗时 7.58s ｜ 只读审计（未改 `rust/**`/`data/**`/`hsrl2/**`，未 commit）。
> 被审引擎：`rust/` fork（`hsbg_engine`，37.0.0.255130）；参照：冻结的 `hsrl2`（legacy oracle，37 数据）。

## 0. 结论先行

**PASS**：37 单人池脚本覆盖 0 缺失（P1 门禁通过），oracle 差分无 FAIL，验收门禁全绿 → **可进入 RL 阶段**。

| 指标 | 数值 |
|---|---|
| 池内随从覆盖 | 277 → missing **0** |
| 池内酒馆法术覆盖 | 73 → missing **0** |
| 主英雄技能（129） | missing 9（P1 只要求 Azshara，当前 P1 主技能缺失 **0**；其余为 Duos/旧替换技能长尾） |
| P1 18 卡 | missing **0**（Dark Paradox 经 5 形态覆盖：`BG36_360`） |
| oracle 差分 | `{"MATCH": 15, "DEFERRED": 1, "STRUCTURAL_OK": 2}` |
| 门禁 | `{"total": 8, "failed": [], "pass": true, "elapsed_s": 6.04}` |
## 1. 池内脚本覆盖审计（Rust content vs 37 单人池）

数据源：`data/p2/cards_37.json`（37.0.0.255130 + 36.6.3 compat，单人池按 `pools` 标志）；Rust 注册表 = `content/*.rs` 静态扫描 + 已编译 `hsbg_engine.catalog_json()`（运行时真值，golden 由 registry 自动解析）。

| 集合 | 总数 | scripted | keyword-only | **missing** |
|---|---:|---:|---:|---:|
| 池内随从 | 277 | 272 | 5 | **0** |
| 池内酒馆法术 | 73 | 73 | 0 | **0** |
| 英雄主技能（129 唯一） | 129 | 120 | 0 | **9** |

- P1 18 卡缺失：**0**；按 owner：`{}`
- P1 关联主技能（Azshara 变形目标 `BG22_HERO_007p2`）：`BG22_HERO_007p2`=scripted
- Dark Paradox：base `BG36_360` 为 37 数据占位壳（不在池、无脚本）；池内行为由 5 个旧形态承载且全部 scripted：`BG36_360t3`(scripted)、`BG36_360t4`(scripted)、`BG36_360t5`(scripted)、`BG36_360t6`(scripted)、`BG36_360t9`(scripted)
  口径：`BG36_360` 在 37 数据中 `pools=[]`（base 壳），5 形态 `BG36_360t3/t4/t5/t6/t9` 在池且 scripted；worker 决策保持 5 形态机制（`content/p3_systems.rs` 头 + `tests/p3_systems.rs`），按“池内可玩内容覆盖”计为 covered_via_forms，不计 missing。
- 静态注册表：1344 ids / 57 modules；`build_is_current=True`；静态/运行时 normal 形态差集：static_only=36、runtime_only=50（静态解析器只覆盖 `scripts()` 字面量，常量/辅助函数注册以运行时为准）
- **P1 覆盖门禁：PASS**

### 英雄主技能缺失（P1 只要求 Azshara；其余为 P2/P3 长尾）

- `BGDUO_HERO_100p` [x]
- `BGDUO_HERO_101p` Glorious Gloop
- `BGDUO_HERO_104p` Efficient Exchange
- `BGDUO_HERO_222p` Double Trouble
- `BGDUO_HERO_223p` Double Trouble
- `TB_BaconShop_HP_009` Skilled Bartender
- `TB_BaconShop_HP_017` Murloc King
- `TB_BaconShop_HP_043` Nefarious Fire
- `TB_BaconShop_HP_051` Honorable Warband

### P1 18 卡逐卡状态

| id | 名称 | owner | scripted | 静态源码 | hsrl2 参考 |
|---|---|---|---|---|---|
| `BG23_002` | Shell Collector | engine-fixer | scripted | ✓ | 有 |
| `BG26_505` | Zesty Shaker | engine-fixer | scripted | ✓ | 有 |
| `BG27_514` | Sea Witch Zar'jira | engine-fixer | scripted | ✓ | 有 |
| `BG31_035` | Groundbreaker | engine-fixer | scripted | ✓ | 有 |
| `BG31_920` | Darkcrest Strategist | engine-fixer | scripted | ✓ | 有 |
| `BG31_925` | Showy Cyclist | engine-fixer | scripted | ✓ | 有 |
| `BG32_835` | Tranquil Meditative | engine-fixer | scripted | ✓ | 有 |
| `BG32_837` | Fauna Whisperer | engine-fixer | scripted | ✓ | 有 |
| `BG33_319` | Rimescale Priestess | content-delta-analyst | scripted | ✓ | 无（结构检查） |
| `BG34_925` | Seafloor Recruiter | content-delta-analyst | scripted | ✓ | 有 |
| `BG35_921` | Abyssal Bruiser | content-delta-analyst | scripted | ✓ | 有 |
| `BG36_360` | Dark Paradox | rust-engine-forker | covered_via_forms | — | 无（结构检查） |
| `BG36_508` | Cagey Conjurer | content-delta-analyst | scripted | ✓ | 有 |
| `BG36_622` | Torrential Ruiner | content-delta-analyst | scripted | ✓ | 有 |
| `BG36_921` | Fleeing Fugitive | content-delta-analyst | scripted | ✓ | 有 |
| `BG22_HERO_007p` | Azshara's Ambition | rust-engine-forker | scripted | ✓ | 有 |
| `BG32_815` | Shifting Tide | content-delta-analyst | scripted | ✓ | 有 |
| `BG35_922` | Queen's Command | content-delta-analyst | scripted | ✓ | 有 |

## 2. hsrl2 oracle 差分（16 张有参考卡 + 2 张结构检查）

口径：同一卡 id、同一局面（`add_to_board`/`add_to_hand`/出牌/施法/回合结束），比较玩家语义可观察量（棋盘 id/攻/血、手牌 id、金币、酒馆等级、技能）；RNG 流/事件顺序不计。分类：MATCH / CONVENTION_DIFF / FAIL / DEFERRED / STRUCTURAL。

两条 case 的**已声明口径差异**（不是放宽断言，是两侧触发上下文本身不同）：
- `O13` BG31_925 亡语：Rust 取 `CombatPreview{details:false,n:1}` replay frames 的死亡帧前后 Naga 属性差；hsrl2 用公开 `destroy_minion` 在招募期走同一 `_process_single_death` 亡语路径取同差值——比较“效果增量”。
- `O15` BG22_HERO_007p：hsrl2 侧用公开幂等 `wire_hero_power_on_bind(hero, power_id)` 接线 `on_bind`；两侧共享“打出一张随从”检查点，比较 `observe()['powers']` 是否出现 `BG22_HERO_007p2`。

- seeds/构造：`/Users/letiangao/HSAgent/HSBRSIM` 本机 python3；counts：`{"MATCH": 15, "DEFERRED": 1, "STRUCTURAL_OK": 2}`

| ID | 卡 | 机制 | 结果 | 说明 |
|---|---|---|---|---|
| O01 | `BG23_002` | battlecry | **MATCH** |  |
| O02 | `BG26_505` | spellcraft-copy | **MATCH** |  |
| O03 | `BG27_514` | spellcraft-gain | **MATCH** |  |
| O04 | `BG31_035` | play-naga-buff | **MATCH** |  |
| O05 | `BG31_920` | spellcraft-gain | **MATCH** |  |
| O06 | `BG32_835` | spellcraft-gain | **MATCH** |  |
| O07 | `BG32_837` | eot-cast | **MATCH** |  |
| O08 | `BG35_921` | spell-counter | **MATCH** |  |
| O09 | `BG36_622` | spell-on-naga | **MATCH** |  |
| O10 | `BG36_921` | spell-on-self | **MATCH** |  |
| O11 | `BG32_815` | spell | **MATCH** |  |
| O12 | `BG35_922` | spell | **MATCH** |  |
| O18 | `BG36_508` | activate-invariant | **MATCH** |  |
| O13 | `BG31_925` | deathrattle | **MATCH** |  |
| O15 | `BG22_HERO_007p` | hero-power | **MATCH** |  |
| O14 | `BG34_925` | rally | DEFERRED | Rally 只在战斗内触发；Rust CombatPreview 明确不回写持久状态（手牌不可见），hsrl2 战后恢复棋盘/CombatResult 不含手牌——没有对称的持久观察量。需要 Rust debug-only hook 触发命令才能对拍（已按 Lead 裁定维持 DEFERRED，不改引擎）；worker 单测已覆盖右邻/最右落空/金色两次。 |
| O16 | `BG33_319` | structural | STRUCTURAL_OK | data=True scripted=True forms=3 |
| O17 | `BG36_360` | structural | STRUCTURAL_OK | data=True scripted=True forms=11 |

### 未覆盖 / DEFERRED 原因（不伪造 oracle）

- `O14` `BG34_925`：Rally 只在战斗内触发；Rust CombatPreview 明确不回写持久状态（手牌不可见），hsrl2 战后恢复棋盘/CombatResult 不含手牌——没有对称的持久观察量。需要 Rust debug-only hook 触发命令才能对拍（已按 Lead 裁定维持 DEFERRED，不改引擎）；worker 单测已覆盖右邻/最右落空/金色两次。

## 3. 验收门禁

总判定：**PASS**，耗时 6.04s（本机 python3，Apple Silicon）。

| 门禁 | 结果 | 耗时 | 证据摘要 |
|---|---|---|---|
| cargo_build_release | PASS | 0.15s | exit=0 |
| cargo_test_p3_cards_a | PASS | 0.09s | passed=8；failed=0；suites=1；failed_tests=[] |
| cargo_test_p3_cards_b | PASS | 0.12s | passed=13；failed=0；suites=1；failed_tests=[] |
| cargo_test_p3_systems | PASS | 0.09s | passed=8；failed=0；suites=1；failed_tests=[] |
| cargo_test_all | PASS | 3.94s | passed=887；failed=0；suites=39；failed_tests=[] |
| pytest_test_rust_engine | PASS | 1.5s | ........s..                                                              [100%] |
| bot_smoke（8 人 × 20 seeds） | PASS | 0.08s | crashes=0，回合 13..20 |
| determinism（同 seed 双跑） | PASS | 0.07s | checks=4 |

### worker 测试独立复核（不只看绿）

| 测试文件 | 用例数 | P1 卡覆盖 | 无断言用例 | 复核结论 |
|---|---:|---|---|---|
| `tests/p3_cards_a.rs` | 8 | 8/8 | 无 | 覆盖完整 |
| `tests/p3_cards_b.rs` | 13 | 8/8 | 无 | 覆盖完整 |
| `tests/p3_systems.rs` | 8 | 2/2 | 无 | 覆盖完整 |

人工复核要点（逐卡语义 vs 卡面）：batch A/B 每张卡至少 1 个正向 + 关键负例（他人/非目标/无触发），并覆盖金色差异值；systems 覆盖 Azshara 注册/英雄池/30 攻变身/Conquest 1 金 Discover/无金不可用、Dark Paradox 数据映射不变量。用例断言强度：均含具体数值/卡 id 断言。

## 4. 风险与剩余缺口（供 Lead 决定是否进入 RL）

1. **oracle 覆盖边界**：16 张有参考卡中 **15 张**做了逐卡可比场景（含 deathrattle 的“效果增量”口径、hero-power 的公开接线、activate 的不变量口径）；仅 `BG34_925` Rally 1 张 DEFERRED；2 张无参考卡（BG33_319/BG36_360）用结构检查 + worker 用例复核（不影响 P1 内容门禁，但该 1 张的等价性证据等级较低）。
2. **Spellcraft 发放时点**：hsrl2 在 on_summon 即发、AT 在回合开始发，属约定差异（oracle 只比“副本/持有”语义）；训练侧以 AT 行为为准。
3. **数据兼容层**：`data/p2/cards_37.json` 含 288 条 36.6.3 compat 条目，P1 卡的 `script_data_num_*` 在映射后多为 None（37 文本已内联数值）；Rust content 以文本数值实现，需避免未来数据重生成时数值漂移。
4. **池内主技能长尾**：129 个主技能中仍有 9 个 missing（Azshara 之外为 Duos/旧替换技能，属 P2/P3 可达性缺口，不阻塞 P1）。
5. **本验证不覆盖**：饰品/法术全量（P2）、异变（P3）、完整 679 场真实战斗回放差分（需 `tools/diff_replay_combat.py` 在 Rust 侧重放，P3 后续）。
6. **seed 基准**：P3 内容入池改变了固定 seed 的大厅/池抽样，既有测试夹具已按 37 数据重算（未放宽断言）；**全部 P3 内容合入后建议再冻结一次 seed 基准**（rust/FORK §7 已记）。

## 5. 复现命令

```bash
cd rust && python3 -m pip install -e . && cd ..   # 重建扩展（content/数据改动后必须）
python3 -m tools.p3_verify.run_all                # coverage + oracle + gates → runs/p3_verify/
python3 -m tools.p3_verify.coverage               # 仅覆盖审计（P1 门禁）
python3 -m tools.p3_verify.oracle                 # 仅 oracle 差分
python3 -m tools.p3_verify.gates                  # 仅门禁（含 cargo build/test/冒烟/确定性）
cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine --test p3_cards_a
cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine --test p3_cards_b
cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine --test p3_systems
```

产物：`runs/p3_verify/{coverage.json,oracle.json,gates.json,report.json,summary.md}`（gitignore）。
