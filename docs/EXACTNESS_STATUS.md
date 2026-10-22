# 官方一致性状态（EXACTNESS STATUS）

> 快照时间：2026-10-18 21:50 ｜ 数据：官方 **37.0.0.255130** ｜ 引擎：`hsrl2`
> 可复现命令见文末；每项数字均可由脚本重新生成。

## 1. 总览

| 维度 | 状态 | 指标 |
|------|------|------|
| 官方数据 | ✅ 已对齐 | BG 实体 5,787；卡 3,817；池内随从 273 / 法术 76；新种族 ABERRATION |
| 引擎回归 | ✅ | **5,177 passed / 3 skipped / 14 subtests**（`pytest hsrl2/tests tests`） |
| 动态属性迁移 | 🚧 | F-10 8 族 + F-11 7 张 B 类卡已读官方槽位（默认行为不变）；F-11 引擎侧就绪，待 diff-harness 登记 `CONSUMED_SCRIPT_DATA`（安全子集登记可把干净子集 19→24、behavior_mismatch=0） |
| 长尾压测 | ✅ | 600 局随机全对局（2/4/8 人各 200，含异变）**crashes=0 / incomplete=0**；Deity 60/60、Discard 60/60、Activate cost=0 11/11、确定性 20/20（详见 §5） |
| 效果脚本覆盖 | ✅ 99.6% | 池内 implemented/ledgered **279/280**，剩余 **1** 张（BG28_583 Geomagus，触发链证据缺口） |
| 官方轨迹差分 | ✅ 干净子集 100% | 679 场真实 BG 战斗：strict MATCH **72.2%**、确定性 **86.6%**、干净子集 **100%（33/33）**、`behavior_mismatch=0`；context_gap **85**（unmodeled_dynamic_state **73**） |
| 剩余分歧归因 | 全部缺脚本 | 154 条 ENGINE_DIVERGENCE 均为 `missing_script`（历史非池轨迹卡为主） |
| 客户端官方实现 | ❌ 不可得 | 客户端仅消费服务器 `PowerHistory`，无裁决器（126 DLL 全扫描 0 命中） |
| 事件级官方校准 | ⏳ 阻塞 | 需真实 `Power.log`（本机暂无）；解析器/差分已就绪 |

## 2. 已修复的引擎缺陷（详见 docs/ENGINE_NOTES.md）

| 编号 | 问题 | 效果 |
|------|------|------|
| F-01 | 战斗快照 deepcopy 实体引用（KILLER） | 整局 7.2×、ERP 11×、内存 98× → 正常 |
| F-02 | Ozumat SoC 召唤 6-7 只 Tentacle（官方 1 只） | 官方轨迹由 diverged 转 MATCH |
| F-03 | 动态 `SCRIPT_DATA_NUM` 通道（官方 enumID 2/3/2889/2919/2920） | Eternal Knight 族动态属性可注入复现；其余 12 族台账 |
| F-04 | 伤害上限外部注入 API（官方 tag 2089/3403） | 默认行为不变；真实日志可注入官方值 |
| F-05 | 剧毒/烈毒、顺劈的「攻击者存活」门槛 | 去掉门槛（官方文本 + BobsBuddy 双源），8 条规则级测试 |
| F-06 | 本回合元素打出计数（`ELEMENTALS_PLAYED_THIS_TURN`） | 解锁 Firelands Fugitive/Conflagration；默认行为不变 |
| F-07 | Deity（旧神隐藏目标）子系统 | Aberration 死亡推进/awaken/Deity 增益通道；7 张 Deity 卡 + Y'Shaarj token；C'Thun split 待证据 |
| F-08 | Discard（弃牌）子系统 + Activate cost=0 修正 | 弃牌 action/事件/on_discard/计数；12 张池卡注册；修复 5 张 cost=0 Activate 卡不可用 |
| F-09 | Sneed's New Shredder 亡语 from-hand 语义 | 旧实现复制留手 → 无限重召（8p 压测 `CombatLoopError`）；改为移出手牌召唤，压测 crashes=0 |
| F-10 | 动态属性脚本家族迁移到 `script_data_or_card(3)` | 8 族（Abyssal/Ancestral/FallingSky/Frostling/Maritime/RotHide/EternalKnight/EternalPortrait）；默认行为不变；受控 diff MATCH +5（394→399），context 未降（harness 消费登记待办） |
| F-11 | B 类动态状态迁移（进度/计时/标记） | 7 张（Patient Scout/Gluttonous Trogg/Rogers/Upbeat Frontdrake+Duo/Zesty/Scarlet）；`Entity.is_script_data_injected` 区分静态/注入；默认行为不变；测试 13 例；待 harness 登记槽位 |
| F-12 | 原语 `minion_gained` + `combat_spell_extra_casts` | 单点入手事件（防重复）；战斗内法术按值额外施放（默认 0 逐位不变）；测试 11 例；Drust/Maelstrom 卡脚本待后续 |
| F-13 | 最后两张 missing_script 收口（Drust/Maelstrom） | `batch_37x_gapfill`：Drust 监听 minion_gained 按 Pirate/金色数值；Maelstrom 战斗内 `_combat_spell_extra_casts`（普通 1/金色 2）；13 例测试；默认行为不变 |
| F-14 | Reborn 复生体恢复卡面基础关键词 | 官方 Power.log：青铜守卫 BGS_034（DS+Reborn）复生实体 FULL_ENTITY 带 DIVINE_SHIELD=1；旧引擎复生体无 DS → 被秒杀判 tie。修复后 C round6 win 90.6%，powerlog3 behavior_mismatch 0；2 例测试 |
| F-15 | Deity 边界快照 / sigil / board token 注入 | `Game.inject_deity_state`（exact atk/health/progress/awakened/sigil/board_tokens）、`inject_deity_sigil`、`inject_deity_board_token`；默认未调用逐位不变；9 例测试；state23 TVD .9844→.8438，剩余为 F-07 C'Thun split DEFERRED |

## 3. 数据与版本

- 官方 XML：`reversed/hsdata_255130/`（`CardDefs.Bacon.xml` 5,787 BG 实体，
  sha256 锁定，来源 URL/哈希见 `source.json`）。
- 引擎数据：`data/`（patch `37.0.0.255130`），旧基线备份 `data/backup_249896/`。
- 版本跟踪：`python tools/version_sync.py --check`（四信号：客户端 `.product.db` /
  项目数据 / hsdata 最新 tag / rizling 参考版本）；`--dry-run` / `--apply --yes`。

## 4. 剩余脚本缺口（1 张池内，DEFERRED 依据）

| 类别 | 数量 | 阻塞原因 | 计划 |
|------|------|----------|------|
| 触发链无权威上限 | 1 | BG28_583 Geomagus Roogug：两只互触发「play a Blood Gem on a different friendly minion」形成无界互触发；官方触发链上限无权威、引擎 ActionQueue 20000 会抛 `CombatLoopError` | 需规则/证据裁定（或引擎触发链配额原语） |

已闭环：F-08 Discard 子系统 + 12 张池卡（`batch_37x_discard`）；
F-07 Deity 子系统 + 7 张（`batch_37x_deity`）；F-06 Firelands/Conflagration
（`batch_37x_firelands`）；载荷 9 + 宿主 8（`batch_37x_payloadgap1`）；
第二批 10（`batch_37x_poolgap2`）；第一批 7（`batch_37x_combatgap`）。

## 5. 长尾压测与确定性（2026-10-18 终测）

工具：`python tools/final_engine_stress.py`（产物 `runs/final_engine_stress.json`）
+ `python tools/smoke_random_games.py`。

| 项目 | 规模 | 结果 |
|------|------|------|
| 随机全对局 smoke（含异变） | 2/4/8 人各 200 局 = **600 局** | crashes=0、incomplete=0（耗时 7.6s / 18.8s / 43.1s） |
| Deity 专项 | 60 例（2/4/8 英雄、随机 Aberration 死亡 0..6、满场分支、每场重置、Y'Shaarj 复活） | **60/60 通过、0 崩溃** |
| Discard 专项 | 60 例（空手牌 Activate/成对弃置/on_discard 战斗内外/计数与 Improve/EoT 弃置） | **60/60 通过、0 崩溃** |
| Activate cost=0 | 11 个定义逐个真实 `use_activate` | **11/11 通过** |
| 确定性抽检 | 20 个 seed × 两遍同动作序列（覆盖 Deity/Discard 局面） | **20/20 指纹一致**；跨进程 digest 一致（`391a91b…`） |

> 终测期间发现并修复 **F-09**（Sneed's New Shredder 亡语复制留手 → 无限重召，
> 8p seed=6180 `CombatLoopError`）；修复后 600 局 smoke 全绿。

## 6. 差分口径（docs/DIFF_HARNESS.md）

- **strict**：全部可比轨迹 + BobsBuddy 100% 硬裁判；对 RNG 流位移敏感。
- **context-aware**：仅干净子集（无 no_script / dynamic_script_data /
  deathrattle_annotation / detected_effect / hero_power_state 等阻断缺口）。
- **tolerant**：确定性轨迹按 BobsBuddy 期望方向 ≥80% 即算方向一致。
- 硬门禁：`behavior_mismatch == 0`、`DATA_GAP == 0`、干净子集 100%。

## 7. 关键复现命令

```powershell
cd C:\HSagent
python -m pytest hsrl2/tests tests -q            # 5,090 passed
python tools/audit_card_registry_v2.py --strict  # 覆盖率（剩余 1 张已知缺口）
python tools/final_engine_stress.py              # 长尾压测/确定性（runs/final_engine_stress.json）
python tools/smoke_random_games.py --games 200 --players 8 --seed 6000
python tools/diff_replay_combat.py               # 679 场差分（strict/context-aware/tolerant）
python tools/version_sync.py --check             # 版本四信号
python scripts/audit_env_coverage.py --games 20  # 环境动作/观测覆盖门禁
python scripts/verify_all.py                     # 全量门禁（7 gates）
```

## 8. 下一步（按优先级）

1. **F-11 收尾（B 类动态状态）**：diff-harness 按 `reversed/rea/
   dynamic_gap_audit.md` §7 登记 `CONSUMED_SCRIPT_DATA`；5 条暴露的
   behavior_mismatch 根因已定位为残留 hand / unknown hero power 上下文
   被误判为非 blocking（详见 `reversed/rea/behavior_mismatch_5_rootcause.md`）：
   将 `attribute_divergence` 的 `hand_not_modeled`、`*_hero_power_unknown`
   归入 unmodeled_context 后，登记全部 B 卡可保持 behavior_mismatch=0、
   干净子集 33/33（100%）。派生值 4 张（Forest Rover/Buzzing Vermin/
   Felemental/Catacomb Crasher）由 harness 比较引擎计算值，不接脚本。
2. **F-10 收尾（动态属性）**：diff-harness 侧把已迁移卡登记进
   `DYNAMIC_STAT_SCRIPT_IDS`/`CONSUMED_SCRIPT_DATA`（trace 多只带
   NUM_1/2 打印值 → 需适配器反推 count 注入 NUM_3）；随后排查
   `context_gap` 主导的**其它已注册卡**（Forest Rover `BG31_801`、
   Wrath Weaver `BGS_004`、Patient Scout `BG24_715`、Gluttonous Trogg
   `BG35_801`、Scarlet Survivor `BG35_814`、Sky Admiral Rogers
   `BG33_823` 等）与缺失脚本（Moonsteel Juggernaut `BG31_171`）的
   动态 ScriptDataNum 语义（逐卡证据，禁止"有 tag 就注入"近似）。
3. ✅ **F-13 卡脚本收口**：`BG32_234 Dastardly Drust`（minion_gained
   按 Pirate/金色过滤）+ `BG34_922 Maelstrom Emergent`（战斗内
   `_combat_spell_extra_casts`，普通 1/金色 2）已注册；13 例测试。
4. **BG28_583 Geomagus Roogug**：唯一剩余池内缺口——需触发链配额原语
   （或官方双 Roogug 行为证据），否则会撞 ActionQueue 上限。
5. **F-07b**：C'Thun awaken "split" 规则（等真实 Power.log/官方实现证据）；
   Deity 饰品交互（Golden/Reborn/Worship/Makeshift Master）留饰品批次。
6. 采集真实 `Power.log`（用户可用时）→ 事件级差分；校准伤害上限 5/10 档位、
   复生属性、死亡波次/SoC 顺序（当前均为 NO EVIDENCE，暂不改）。
7. 剩余 153 条 missing_script 分歧按历史非池轨迹 TOP 卡继续补齐
   （BG30_129 / BG31_171 / BG26_199 / BG35_701…）。

## 9. 真实 Power.log 事件级验证（2026-10-18）

真实 8 人 BG `Power.log`（77,372 行）已接入并完成事件级差分；`e057` 伪
summon 已按 engine-analyst 裁定修复（战团 SETASIDE 副本还原不是召唤）。

| 指标 | 结果 |
|---|---|
| 抽取 | **6/6 场**（0 skip） |
| 官方结果 | win 3 / tie 1 / loss 1 / null 1（最后一段截断，不猜） |
| 事件级差分 | **MATCH 5**（4 条 RNG_ORDER + 截断场） / ENGINE_DIVERGENCE 1（turn2 空场） / behavior_mismatch **0** / DATA_GAP 0 |
| RNG_ORDER（首分歧=攻击先手/顺序） | **4**（不计 behavior_mismatch；结果已一致） |
| 事件级 strict（结果一致且事件序列完全一致） | **1** |
| GAME_SEED | 已入 trace 可选字段 + 报告 `first_event`；用官方 seed 额外跑一局 6/6 尝试均未对齐事件流 → **仅元数据，不做 strict 等价** |
| 伤害上限脚本 | `damage_cap_extract.py` 兼容真实格式（自测全 PASS）；真实日志 cap `{2:4,5:2,10:2}` |

详见 `docs/DIFF_HARNESS.md` §9；报告 `runs/diff_report_powerlog.json/.md`；
轨迹 `runs/official_traces_powerlog/`。修复：`_is_restored_warboard()`
（`SETASIDE→PLAY` 带 `COPIED_FROM_ENTITY_ID`/`BACON_DIED_LAST_COMBAT` 不记
summon），守护测试 `test_powerlog_setaside_copy_restore_is_not_summon` +
`test_real_powerlog_pseudo_summon_regression`。

### 第二/三局同局交叉验证（2026-10-18）

完整局 B（22:14–22:32，Place 5，10 场）与 C（22:35–22:52，Place 7，10 场）：
* B：Power.log vs HDT **10/10 官方结果一致**（loss 5 / tie 2 / win 3）；
* C：Power C 10 场 + HDT3 切片 C 10 场 —— **10/10 一致**（round10 HDT
  游戏结束前无 Validate，BB 预测 Loss 与 Power loss 一致）。其中 round3/4/5
  原为 tie，已由 `official_result` 修复（存活为主 + 仅平局时英雄掉血纠偏；
  战后延迟伤害归入刚结束战斗）。
* C 局 round6 的真实引擎分歧已定位（注：diff-harness 报的 98.4% tie 实际
  属于 `a07dc079cf3bd8d9`，不是消息中误写的 `be819...`；`be819` 当前
  引擎 64 seeds win 100%，diff 已 MATCH）——**F-14**：BGS_034 青铜守卫
  Reborn 复生体丢失卡面 Divine Shield；官方 Power.log 复生实体
  `FULL_ENTITY` 明确 `DIVINE_SHIELD=1`。修复后 `a07dc` 引擎 win **90.6%**
  / tie 9.4%（官方 win）；`runs/diff_powerlog3_after_f14.json`：
  MATCH 6/10、**behavior_mismatch 0**（修前 5/10、1）。

**累计真实 Power.log 战斗 26 场（A6+B10+C10）；抽取层 official_result 修复后 B/C 交叉 10/10；C round6 经 F-14 修复后 behavior_mismatch 0**。
HDT 1.59.3 卡名→card_id 补齐（`resolve_trace_card_ids`）已用于 HDT 战团签名
交叉；伤害上限 `runs/damage_cap_powerlog_session3.json` 确认
**2→5→10→15 三档**（B/C 玩家名次 5/7，均未进前四；解除上限仍未观测）。

**采集结论**：用户已停止人类采集（三局名次 5/5/7，边际收益低）；后续按
`reversed/rea/real_game_validation_status.md` 执行离线验证：客户端无官方
实现 → **全量等价不可达**，验证口径固定为“结果级/事件级/分布级”；可替代
证据 = 679/677 场 BobsBuddy 语料 + 合成战团 fuzz（BobsBuddy 本地 oracle）。

### 第二局同局交叉验证（2026-10-18 22:14–22:32）

完整一局（Power.log 232k 行无截断）10 场 + HDT BobsBuddy 10 场：
**按 round 对齐 10/10 官方结果一致**（loss 5 / tie 2 / win 3）。
Power.log 事件级 MATCH 5 / ENGINE_DIVERGENCE 5（战前/开局效果伤害事件）/
**behavior_mismatch 0** / RNG_ORDER 5；HDT 侧 MATCH 5 / CONTEXT_GAP 4 /
SKIPPED 1 / behavior 0。**累计真实 Power.log 战斗 16 场（首局 6 + 第二局 10），
behavior_mismatch 累计 0**。

HDT 1.59.3 格式：BobsBuddy 战团行无 `cardId=` → 新增
`resolve_trace_card_ids()`（卡名索引补齐，95 minions/10 hand/14 heroes，
0 unresolved）并使 `signature()` 优先 card_id；fixture 测试
`test_hdt_159_card_ids_resolved_from_names`。伤害上限
`runs/damage_cap_powerlog_session2.json` 确认 **2→5→10→15 三档**（用户本局
第 5 名，剩 4 人，解除上限仍未观测）。

### 下一步（事件级）
1. turn2 空场战斗事件流口径（官方 hero attack vs 引擎 0 事件）；
1b. HDT 就绪：`--sources hdt --hdt-logs "%APPDATA%\HearthstoneDeckTracker\Logs"` 已验证（27 文件→677 轨迹；新会话文件命名 `hdt_log.txt` 可消费）；需用户启用 HDT 的 BobsBuddy 插件，否则新局只有 Power.log 无 BB 期望分布；
2. 用户补采完整一局/多局 Power.log + HDT BobsBuddy 同局交叉验证；
3. 事件级 gate 语料足量后再接入 CI（不足 SKIP）。
4. **离线批量差分**：`tools/diff_bulk_fuzz.py` 骨架 + smoke 已完成（100 状态 × 引擎 64 seeds；stub oracle 仅验证管线）。待 engine-analyst 接入 BobsBuddy oracle 后扩到 1k+ 合成状态，取代人类采集；BB 为第三方参照，非官方实现级等价。

## 10. 当前补充（2026-10-19，真实对局 / 离线 BB）

### 10.1 真实 Power.log 事件级
* 累计真实战斗 **26 场**（A6+B10+C10），抽取层 official_result 修复后
  **B/C 交叉 10/10**；C round6 的引擎分歧经 **F-14**（Reborn 复生体恢复
  卡面基础关键词 DS）修复：07dc079cf3bd8d9 win 90.6% → MATCH；
  e819be0e16f9746 实为 turn12 win 100% MATCH（更正此前误关联）。
  after-F14 C 局：MATCH 6 / DIV 3 / **behavior_mismatch 0**；
  **26 场真实事件级 behavior=0**。
* 
uns/diff_powerlog3_after_f14.json/.md；
uns/real_game_cross_validation.json。
* cap 2→5→10→15 三档确认；三局名次 5/5/7，解除上限未观测；用户已停止
  人类采集，验证口径=结果/事件/分布级（客户端无官方裁决器）。

### 10.2 离线 BobsBuddy 批量差分
* 真实 BB oracle 接入（	ools/bb_oracle，第三方参照非官方）：
  300 states × 引擎 64 seeds × BB 1000 sims。
* F-14 后：
uns/diff_bulk_bb_after_f14.* → agree **261/300 (87.0%)**、
  mean TVD **0.0664**。
* Deity 六字段已入 state_corpus（bridge，7/746 状态）；BB oracle 接受
  is_deity/riendly_deity_sigil；harness 用 engine
  select_deity/give_deity_stats 注入：
uns/diff_bulk_bb_after_deity_inject.*
  → state23 TVD **0.9844→0.8438**、state268 突变体 **0.0**；全 300
  agree **260/300**、mean TVD **0.0644**。**F-15 已补 sigil/board token/awakened 注入 API**（见 §10.3）；state23 剩余 TVD 归因 C'Thun split（F-07 DEFERRED），diff-harness 应标 unsupported:deity_split_c_thun，不要求收敛。
* enchantment_derived（Crab/AutoAssembler 等）样本统一 unsupported，
  不进 TVD；长期再议 generic external deathrattle 通道。

### 10.3 已知 gap 分类与 F-15 收尾（2026-10-19）

* **F-15 已交付**：Deity 边界六字段 / sigil / board token 注入 API
  （`Game.inject_deity_state` / `inject_deity_sigil` /
  `inject_deity_board_token`）；默认未调用逐位不变；9 例测试。
  `runs/diff_bulk_bb_after_f15b`：state23 TVD **0.9844→0.8438**、
  state268 **0.0**；全 300 agree **261/300**、mean TVD **0.0651**。
* **state23/268 剩余 TVD（F-16 后）**：C'Thun awaken split 已由真实
  Power.log 证据实现（floor/N、余数丢弃），不再 known gap；F-19 后
  bulk 复跑 state23 TVD **0.8438→0.7344**、state268 **0.0**。
  `BG34_320` 仍只 partial evidence（待更多官方样本），维持观察、不猜。
* **BB 是第三方参照，不是官方实现**：不用 BB 行为反推 C'Thun split；
  F-16 只采用 raw Power.log（172605/174028/108099）。
* **BG34_320**（Rally + ALL 多次选取）待官方/日志证据，维持观察、不猜。
* 回归：**`pytest hsrl2/tests` 4,718 passed / 2 skipped / 14 subtests；
  `pytest hsrl2/tests tests` 5,240 passed / 1 个非本 scope 失败
  （tests/test_search_bench.py，policy/search）**；审计三件套 PASS；
  smoke 8 局 0 crash。

### 10.3 F-15 Deity 注入 + gap-aware 最终指标（2026-10-19 00:14）

inject_deity_state/sigil/board_token 已接入（F-15）。历史 gap-aware
指标（`after_f15_gapaware`：evaluated 291/300、known gap 9、agree 253/291）
是在 **C'Thun split 尚未实现**时把 state23 移出分母得到的；**F-16 后
该 known gap 已解除**，diff-harness 应把 state23/268 重新纳入并复跑：
F-19 后本地 bulk state23 TVD **0.8438→0.7344**、state268 0.0。
**TVD 是采样指标；C'Thun split 已不是 known gap。**
