# 固定阵容脚本：完整实现（26 套 + V2 决策树）

> `scripts/comp_scripts.py`（注册表/V2/`view_of`/`comp_keys`）、`scripts/comp_full_probe.py`、`tests/test_comp_scripts_full.py`。
> 纯 CPU、只读、不训练；口径同 `docs/COMP_SCRIPTS.md`（8 席 bot）。2026-11-04。

## 1. 注册表：15 → 28（roles.json 的 26 套 implementable 全覆盖）

| 口径 | 数量 | 说明 |
|---|---|---|
| `roles.json` 27 套 / implementable | **26** | 唯一数据源，未改 |
| 旧 `COMPS` → 现 `COMPS` | 15 → **28** | A–N（14）+ `f_dragon` + 新补 13 套 |
| `UNIMPLEMENTABLE` | **空** | 旧 13 条理由迁 `LEGACY_GAPS`（仅追溯） |

新补（key = roles 的 `ticker`，逐字对齐）：`undead_apm` `murloc_scam` `aberration_discard` `dragon_shield` `undead_butcher` `quilboar_choose_one` `beast_lobster` `aberration_deathrattle` `pirate_discover` `demon_self_damage` `elemental_tempest` `dragon_kalecgos` `pirate_bounty`。
字段：`core/enabler/trinkets` 原样取 roles；`carrier` 取 roles（空则 `core[0]`，12 套空载体）；`cast_on=carrier`；`type_min` 2–3（`demon_self_damage` 4）；`curve=CURVE_MID`。这 13 套的收益在战斗内（亡语/进击/bounty/掉血/Discover），脚本只实现**招募期可执行部分**（组件+保护+补类型）。

## 2. V2 决策树（对所有阵容生效，不再只有 f_dragon）

| 规则 | 实现 |
|---|---|
| 核心窗口退出 | `_v2_maybe_exit`：`t ≥ max(8, EARLIEST_TIER[核心最高 tier])` 且**无任何核心** → `spec=None` 回落通用/bot（`exit_on_miss=False` 可关） |
| 滚动门槛 | `_v2_can_roll`：`hp>20`；`gold ≥ upgrade_price+3`；`t≤7` 无核心也允许；`t≥8` 须握核心（t≥11 仅核心在手，保名次） |
| 升本 | `_v2_can_upgrade`：t2 必升；t3–7 按 `spec.curve`+`EARLIEST_TIER`；t8+ 须核心+`hp>20`+升后余 3 金 |
| 卖牌保护 | `_v2_protected` = 核心 ∪ 载体 ∪ enabler，`_sellable`/置换/`_recruit_f` 共用 |
| t13+ 撤经济位 | `_v2_econ_sell`：卖文本含 `gold/coin` 的非保护位，每回合 ≤2 张 |
| 饰品 | `_pending(kind="trinket")`：`spec.trinkets` +100；28 套均生效 |
| 清理 | `_recruit` 里重复定义的 `better()` 已删（保留 tavern_buy 版） |

**窗口为何按核心 tier 抬高**：`EARLIEST_TIER[6]=10`，6 本核心 t10 前不可能出现在酒馆；一律 t8 退出等于永久判死 A/C/D/E 等 6 本套、退化成纯 bot。故有效窗口 = `max(8, 核心最高 tier 最早回合)`（tier≤5 → t8，tier6 → t10），与 V2 §3「链卡上场中位 t11」一致。

## 3. 实测（`comp_full_probe.py --comps all --games 10`，seed 910000，8 席 bot）

**总账：56 个（阵容, 模式）格子、43,078 决策、非法动作 0（legal_rate = 1.000000）、确定性 28/28 逐字段相同、86.4 s。** 产物 `runs/comp_scripts/full_probe.json`。

| 阵容 | hy t15 | hy 核心t | hy 名次 | hy 退出 | pu t15 | 阵容 | hy t15 | hy 核心t | hy 名次 | hy 退出 | pu t15 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 158 | 10.0 | 5.40 | .90 | 51 | undead_apm | 130 | — | 5.90 | .80 | 56 |
| B | 112 | — | 6.70 | .60 | 51 | murloc_scam | 136 | 6.5 | 5.50 | 1.00 | 82 |
| C | 130 | 9.5 | 6.40 | .50 | 54 | aberration_discard | 203 | — | 5.40 | .60 | 49 |
| D | **314** | 10.0 | 4.70 | .50 | 76 | dragon_shield | 235 | 10.0 | 4.90 | .70 | 62 |
| E | 225 | 9.0 | 5.20 | .40 | 60 | undead_butcher | 130 | — | 5.90 | .70 | 56 |
| F | 232 | 9.5 | 5.20 | .60 | 62 | quilboar_choose_one | 118 | — | 6.50 | .60 | 58 |
| G | 206 | 9.0 | 4.90 | .60 | 53 | beast_lobster | 226 | 8.5 | **4.10** | .50 | 53 |
| H | 313 | — | 5.00 | .70 | 75 | aberration_deathrattle | 192 | — | 5.30 | 1.00 | 86 |
| I | 156 | 10.0 | 5.50 | .70 | 54 | pirate_discover | 180 | 10.0 | 5.90 | .60 | 52 |
| J | 156 | — | 6.00 | .80 | 54 | demon_self_damage | 139 | 4.0 | 6.10 | .20 | 56 |
| K | 227 | 9.0 | 5.00 | 1.00 | 53 | elemental_tempest | 182 | — | 5.30 | .70 | 70 |
| L | 118 | 9.5 | 6.70 | .20 | 52 | dragon_kalecgos | 235 | — | 4.90 | 1.00 | 62 |
| M | 97 | 5.0 | 6.10 | .40 | 60 | pirate_bounty | 180 | — | 5.90 | .70 | 52 |
| N | 121 | 5.0 | 5.90 | .80 | 56 | f_dragon | 62 | 3.0 | 6.70 | .20 | 62 |

读法：① **hybrid vs pure 差 2–4 倍**（97–314 vs 49–86），纯手写经济仍打不过 bot 兜底，复现 `COMP_SCRIPTS.md` §4.3；② 新补 13 套 hybrid 落在旧 14 套区间内（118–235），强度几乎全部来自 bot 兜底，印证「收益在战斗内、招募期抓不到」；③ 退出率高的正是 6 本核心套（A/K/aberration_deathrattle/dragon_kalecgos/murloc_scam），与「核心到手 p50 = 9–12」一致。

## 4. 与旧 15 套的差异

- 注册表 15→28、`UNIMPLEMENTABLE` 清空、`comp_keys()` 稳定排序。
- 所有套受 V2 门槛约束 ⇒ 旧 14 套绝对值会变（A 在 10 局口径 158；旧文档 30 局 116，**seed/局数不同不可直接相减**）。
- 新接口：`view_of(game, seat=0)`、`comp_keys()`、`CompPolicy.reset()`、`play_one/run_comp(..., exit_on_miss=)`；`observe/comp_action/act` 签名未变，`--comp auto|all|BOT|key[,key]` 兼容。
- 同 10 局 A/B（hybrid，`exit_on_miss` True vs False）：t15 Σ 差 **中位 0 / 均值 +6.5**（最大 +87 `beast_lobster`、−34 `F`）⇒ 窗口退出在 hybrid 下基本是噪声，但让 `auto` 明确「t10 前抓不到核心就转通用」。两臂非法动作都是 0。

## 5. 复现

```bash
export PYTHONPATH=rust/python:.
$PY -m pytest tests/test_comp_scripts_full.py -q        # 35 passed，22 s
$PY scripts/comp_full_probe.py --comps all --games 10   # 86 s → runs/comp_scripts/full_probe.json
$PY scripts/comp_scripts.py --list                      # 28 套一览
```

## 6. 已知边界

- 13 套新阵容的成长在战斗内，脚本只能攒组件——引擎给招募期策略的信息上限，非实现缺陷。
- hybrid 天花板 = bot：`comp_action` 只接管核心/载体/类型/经济位四类动作，升本时机/站位/三连仍靠 bot。
- 仅改脚本与探针；**未改训练脚本/奖励，未删改 runs/ 既有产物**（新增 `full_probe.json`）。
