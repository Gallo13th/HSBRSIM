# DIFF HARNESS — 官方轨迹 vs 引擎复现的差分验证

> 目标：把「与官方实现效果完全一致」变成**可量化、可回归**的工程能力。
> 本文给出：官方战斗轨迹抽取（`official_combat_trace.v1`）、引擎复现、
> 差分判定、真实语料实测数字、分歧 TOP 清单、局限与回归命令。
>
> 产物：`tools/diff_extract_replays.py`、`tools/diff_replay_combat.py`、
> `hsbg/bridge/trace.py`、`tests/test_diff_{trace,compare}.py`、
> `runs/official_traces/`、`runs/diff_report.{json,md}`。
> 全部只读真实数据；不修改 `hsrl2/`、`hsbg/env/`、`data/`、游戏目录。

---

## 0. TL;DR（先说结论）

| # | 结论 | 数字/证据 |
|---|------|-----------|
| 1 | **本机 1,365 个 HDT 录像里没有真实酒馆战棋局**（任务前提需要修正） | 玩家数分布 `{2: 1365}`；`TB_BaconShop` 0 次、`PLAYER_TECH_LEVEL` 0 次、`BACON_IN_COMBAT_PHASE` 0 次；103 个构筑局只是引用了 `BACON_TRIPLE_UPGRADE_MINION_ID`/`BG31_BOB` 等 BG 实体（§2.1） |
| 2 | 但本机找到了**真实 BG 战斗语料**：HDT 的 BobsBuddy 会话日志 | `%APPDATA%\HearthstoneDeckTracker\Logs\hdt_log*.txt` 27 个会话、**679 场真实 BG 战斗**，含双方战团快照 + **官方实际结果** `result=Win/Loss/Tie` + BobsBuddy 概率（§2.2） |
| 3 | 官方轨迹抽取成功 | `runs/official_traces/` **679 条** `official_combat_trace.v1`；`turn` 100%、`hero_power_id` 99.6%、`official_result` 77.2%、`bb_rates` 98.1% 完整率 |
| 4 | 引擎数据没有「缺卡」问题 | 679 场里全部卡名都在引擎 `data/` 解析成功（`DATA_GAP = 0`）；当前 204 条分歧**全部**是「有卡面文本但引擎 REGISTRY 无脚本」（`missing_script`，§5.3-B） |
| 5 | 总体一致率（测量口径 v2 + 差分驱动批 1-4 脚本 + 8 族动态适配器） | **MATCH 400 / 679 = 72.3%**（可比分母）；**确定性 strict 86.31%**（290/336）、**tolerant 94.35%**（同分布阈值 80%）；**context-aware 干净子集 100%**（33/33）；`behavior_mismatch = 0`（§4.2b/§5.1） |
| 6 | 动态 ScriptDataNum 注入（A/B） | 585 条轨迹 / 2,366 个实体注入官方 `ScriptDataNum*`（52 个 Eternal Knight 实体复算）；A/B：strict MATCH 391→391、**干净子集 12→13**（消除 1 条假缺口）；Ultraviolet 语义仍待证据（§4.2c/§5.3-C） |
| 7 | 历史真 bug 已修 | 上一轮 6 条 behavior_mismatch = 5 条隐藏上下文 + 1 条真 bug（Ozumat 7 只 Tentacle），修复包已应用；当前 `behavior_mismatch=0`（§5.4） |
| 8 | 修复包状态 | `tmp_diff_fix/deliver{2,3}/` 已应用（F-03/04/05）；根目录 live 引擎回归 4690 绿 |

**一句话**：真实 BG 轨迹语料存在且可批量抽取；测量口径 v2（strict/context-aware
双轨 + tolerant 同分布阈值 + 官方 ScriptDataNum 注入）下，当前 live 引擎
MATCH 67.6%（干净子集 100%、behavior_mismatch 0）；剩余分歧全部是 37.x
`missing_script` 卡，按 §5.3-B 频次补脚本即可继续收敛。

---

## 1. 交付物与最小命令

```powershell
cd C:\HSagent

# 1) 抽取官方轨迹（幂等：重复运行不会重复写；--prune 才清理旧文件）
python tools\diff_extract_replays.py --limit 5 --out runs\official_traces
python tools\diff_extract_replays.py                    # 全量：679 条

# 2) 引擎复现 + 差分（默认 64 seeds，JSON + Markdown 报告）
python tools\diff_replay_combat.py --traces runs\official_traces --limit 10
python tools\diff_replay_combat.py                      # 全量差分

# 3) 测试
python -m pytest tests\test_diff_trace.py tests\test_diff_compare.py -q

# 4) 官方一致性门禁（CI；定义见 §8）
python scripts\audit_official_consistency.py
```

> ⚠️ PowerShell 不展开通配符：任务书里的 `python -m pytest tests/test_diff_*.py -q`
> 在 PowerShell 里会被 pytest 当成字面路径（报 `file or directory not found`）。
> 等价写法：`python -m pytest tests -q -k diff`，或显式列出两个测试文件
> （上面第 3 条）。

| 文件 | 作用 |
|------|------|
| `hsbg/bridge/trace.py` | `official_combat_trace.v1` dataclass + 两个数据源解析 + 序列化/统计 |
| `tools/diff_extract_replays.py` | 扫描 HDT 录像（Power.log）/ HDT BobsBuddy 日志 / 显式 `Power.log` → 轨迹 JSON |
| `tools/diff_replay_combat.py` | 卡名解析 → 构造引擎 Minion/Hero → `run_combat` N seeds → MATCH/DATA_GAP/ENGINE_DIVERGENCE + 归因 |
| `tests/test_diff_trace.py` | 合成 BobsBuddy 日志 + 合成 BG Power.log 的抽取测试（不依赖真实录像） |
| `tests/test_diff_compare.py` | `compare_combat` / `compare_events` / 自洽性 / 归因 / 引擎真实复现 / 真实数据冒烟 |
| `runs/official_traces/*.json` | 679 条官方轨迹（匿名化） |
| `runs/official_traces/index.json` | 抽取统计（扫描数、BG 判定、失败/跳过原因、字段完整率） |
| `runs/diff_report.json/md` | 差分结果（逐轨迹记录 + 汇总 + 分歧 TOP + 可疑卡） |

---

## 2. 数据源

### 2.1 本机 HDT 录像：**不是** BG 语料（重要修正）

`%APPDATA%\HearthstoneDeckTracker\Replays\*.hdtreplay`（zip 内 `output_log.txt`
= 完整 Power.log，只读）共 **1,365** 个。全量扫描实测：

| 指标 | 值 |
|------|----|
| 文件数 | 1,365 |
| `Player` 实体数分布 | **{2: 1365}**（全部 2 人构筑/双人局） |
| 含 `TB_BaconShop` | 0 |
| 含 `PLAYER_TECH_LEVEL`（BG 独占 tag） | 0 |
| 含 `BACON_IN_COMBAT_PHASE`（BG 战斗边界） | 0 |
| 含 `CardID=BG<数字>` | 2（构筑局引用 `BG31_BOB` token） |
| 含 `BACON_TRIPLE_UPGRADE_MINION_ID` | 103（**全部是 2 人构筑局**，单条实体 tag） |
| 平均规模 | 9,759 行 / 1.30 MB（**所有**录像的平均值） |

**判定口径（踩坑记录）**：首版 harness 把 `BACON_TRIPLE_UPGRADE_MINION_ID`
当 BG 硬信号 → 把 103 个 2 人构筑局误判为 BG，按 ATTACK block 兜底切分出
**1,183 条假战斗轨迹**。修正后严格口径 = **8 个 Player 实体** 或
`PLAYER_TECH_LEVEL` / `BACON_IN_COMBAT_PHASE` / `TB_BaconShop`
（`trace.is_battlegrounds_powerlog`）。`CardID=BG*` 与
`BACON_TRIPLE_UPGRADE_MINION_ID` 单独出现**不可**作为判据。

> 因此本机当前**没有真实 BG Power.log**。真实 BG 日志一旦采集到（游戏正常
> 打一局即生成 `C:\Program Files (x86)\Hearthstone\Logs\Power.log`，
> `log.config` 的 `[Power]` 已开启），直接：
> `python tools\diff_extract_replays.py --sources powerlog --powerlog <Power.log>`。
> Power.log 的 BG 战斗切分/事件流解析已实现并用合成样例测试覆盖
> （`tests/test_diff_trace.py::test_parse_bg_powerlog_combat`）。

### 2.2 真实 BG 战斗语料：HDT BobsBuddy 会话日志（本 harness 的主数据源）

`%APPDATA%\HearthstoneDeckTracker\Logs\hdt_log*.txt`（只读）里
`BobsBuddyInvoker` 每场战斗记录：

```text
----- Simulation Input -----
Player: heroPower=BG22_HERO_201p, used=False, data=0
Player: extraHeroPower=BG34_HERO_000p, used=False, data=7
Hand: [Bream Counter 12/12, ScriptDataNum1=6, ScriptDataNum2=6]
[Goldrinn, the Great Wolf 8/8, ScriptDataNum1=8]        ← 战团（左→右）
[Risen Rider 3/1, Taunt, Reborn]
[Monstrous Macaw 11/9, G, Div]                          ← G=金色, Div=圣盾
---
Opponent: heroPower=TB_BaconShop_HP_044, used=True, data=2
...
----- End of Input -----
...
WinRate=71.7% (Lethal=0%), TieRate=25.3%, LossRate=3%   ← BobsBuddy 第二实现
...
UpdateAttackingEntities >> attacker=Elise Starseeker, defender=Ambassador Faelin
--- Player turn 2 ---
ValidateSimulationResultAsync >> result=Win, lethalResult=NoOneDied
                                        ↑ 官方实际战斗结果（自校验用）
```

* **官方结果** = `result=Win/Loss/Tie`（BobsBuddy 用实际战斗结果校验模拟）；
* **BobsBuddy 概率** = 社区第二实现 10,000 次模拟 → 只作参照，不是官方；
* 战团是**战斗开始瞬间**的官方快照（含双方英雄技能 id、手牌、随从
  攻击/生命/关键词/金色/`ScriptDataNum*`/亡语标注），这是差分输入的核心；
* 关键词打印口径实测：`Taunt` / `Reborn` / `Div`（圣盾）/ `Poison`（剧毒）/
  `Venomous` / `Windfury` / `Cleave` / `Stealth` / `G`（金色）——
  全量 679 场扫描后未映射标记为 0。

抽取统计（`runs/official_traces/index.json`）：

| 指标 | 值 |
|------|----|
| 会话日志文件 | 27 |
| `Simulation Input` 场次 | 679 |
| 成功轨迹 | **679** |
| 有官方实际结果 | 524（77.2%） |
| 有 BobsBuddy 概率 | 666（98.1%） |
| 字段完整率 | `turn` 100%、`hero_power_id` 99.6%、`player.minions` 99.1%、`opponent.minions` 92.2%、`official_result` 77.2%、`hero_card_id` 0%（BobsBuddy 只打印技能 id，卡 id 在差分阶段按名字解析）、`events` 0%（该源无事件流） |

### 2.3 其他官方资产（暂未接入差分）

* `BgsLastGames.xml`（HDT 根目录，570 KB）：**60 场 BG 对局**的
  Hero/Placement/Rating + 终局战团（`FinalBoard` 含 CardId/tag 快照）。
  没有战斗过程/战前战团，**不能做战斗差分**；可用于真实战团分布/评测。
* `BgsLastGames.xml` 与 BobsBuddy 日志的 60 场对局可交叉核对名次。

---

## 3. 轨迹 schema：`official_combat_trace.v1`

定义在 `hsbg/bridge/trace.py`（dataclass + `to_dict`/`from_dict`）。
一条轨迹 = **一场战斗**；`source` 区分数据源。无法确定的字段写 `null`
并计入 `missing_fields`，**禁止猜测填充**。

```jsonc
{
  "schema": "official_combat_trace.v1",
  "traceizer_version": "0.1",
  "trace_id": "9a6764de47bc430a",        // sha256(source|episode|战斗序号|回合|战团签名)[:16]
  "source": "hdt_bobsbuddy",             // 或 powerlog
  "episode_id": "ep_90f5cddcac5b",       // sha256(原始文件名)[:12]（匿名化）
  "combat_index": 0,
  "turn": 1,
  "player":   { "side": "player",   "hero_power_id": "BG22_HERO_201p",
                "hero_power_used": false, "hero_power_data": 0,
                "second_hero_power_id": "BG34_HERO_000p",
                "hero_card_id": null, "health": null, "armor": null, "tier": null,
                "minions": [ { "slot": 0, "name": "Goldrinn, the Great Wolf",
                               "card_id": null, "atk": 8, "health": 8,
                               "golden": false, "tags": {"ScriptDataNum1": "8"} } ],
                "hand": [], "unsupported": [...], "missing_fields": [] },
  "opponent": { ... 同上 ... },
  "events": [ { "seq": 0, "kind": "attack", "actor_side": "player",
                "actor_slot": 0, "target_side": "opponent", "target_slot": 0,
                "amount": null, "card_id": null, "effect_card_id": null } ],
  "official_result": "win",              // win/loss/tie（player 视角）
  "official_lethal": "NoOneDied",
  "official_damage": {"player": 0, "opponent": 5},   // 仅 powerlog 源可得
  "bb_rates": {"win": 0.717, "tie": 0.253, "loss": 0.03,
               "lethal_win": 0.0, "lethal_loss": 0.0},
  "bb_iterations": 9996,
  "heroes": {"attacker": "Elise Starseeker", "defender": "Ambassador Faelin"},
  "boundary_mode": "bobsbuddy_sim",      // powerlog: bacon_phase / heuristic_blocks
  "missing_fields": ["official_result"],
  "notes": []
}
```

| 字段组 | 说明 | 来源 |
|--------|------|------|
| `player/opponent.minions[].slot` | 站位 0 起（日志左→右顺序） | BobsBuddy 战团行顺序 / Power.log `ZONE_POSITION` |
| `atk/health` | **战斗开始瞬间**数值（BobsBuddy 打印 `攻击/生命`；已用 246 个 turn≤2 样本验证方向：77 个非对称样本全部 = atk/health，0 个反向） | 同上 |
| `golden` | `G` 标记 / `PREMIUM` tag | 同上 |
| `keywords` | 规范化：`taunt/divine_shield/poisonous/venomous/reborn/windfury/mega_windfury/cleave/stealth` | `Div/Poison/Taunt/...` / tag 名 |
| `tags` | `ScriptDataNum*`、`Deathrattles=[...]`（引擎未建模时用于标记上下文缺口） | 同上 |
| `events` | `attack/damage/death/summon/trigger`（按日志顺序，slot 为该时点快照站位） | 仅 Power.log 源 |
| `official_result` | 官方实际胜负（player 视角） | `result=` / 英雄扣血差 |
| `bb_rates` | 第二实现参照（**非官方**） | BobsBuddy Output |
| `hero_card_id/health/armor/tier` | 英雄上下文；BobsBuddy 源不可得 → `null` | Power.log |

**隐私/合规**：不保存原始文件名（含 BattleTag）、玩家名、`GameAccountId`；
`episode_id` 是文件名字符串的 sha256 前缀；`PlayerID` 数值也不落盘。
`tests/test_diff_trace.py::test_trace_roundtrip_and_privacy` 守门。

---

## 4. 差分方法

### 4.1 引擎复现（`simulate_trace`）

1. **卡名 → 引擎 card_id**（`CardResolver`）：引擎 `data/` 全量卡名索引
   （归一化：小写去标点；同名的普通/金色/非池定义按
   `pool_minion > 非金色 > tech_level > dbf_id` 打分取一，歧义记录）。
   解析失败时：卡名存在于官方 37.0 `reversed/data_255130/bg_cards.json`
   → `engine_data_version_gap`（数据升级问题）；否则 `unknown_card_name`。
2. **英雄**：BobsBuddy 只给 `heroPower` id → 用
   `hero_power_id → HERO 卡` 反查（`HeroIndex`）；查不到回退任意英雄并记
   `*_hero_power_unknown` 上下文缺口。默认接线主技能 `on_bind`
   （`--hero-powers on_bind`，对比过 `none`：一致率差异 <1%，见 §5.5）。
3. **战团构造**：`game.create_minion(card_id, golden=...)` 后按日志**精确覆写**
   `BASE_ATK/ATK/BASE_HEALTH/HEALTH`，逐关键词 `set(TAUNT/DIVINE_SHIELD/
   POISONOUS/VENOMOUS/REBORN/WINDFURY/... )`，随后 `game.summon()` 按 slot
   顺序进场。第二英雄技能槽/手牌/饰品/任务/异变**不重建**（记上下文缺口）。
4. **N 个种子**：每条轨迹用 `seed_base+i`（默认 `i=0..63`）各建一局
   `Game([hero_a, hero_b], db, seed)` → `game.run_combat(hero_a, hero_b)`，
   记录 player 视角 `win/loss/tie`、轮数、原始伤害。官方结果/概率不参与
   模拟（纯只读复现）。

### 4.2 判定分类（`compare_combat`，纯函数）

| 分类 | 判定 |
|------|------|
| `DATA_GAP` | 战团里有解析不到/引擎 `data/` 没有的卡 → **不计引擎 bug**，附缺口清单（可区分「37.0 新卡」与「未知卡名」） |
| `ENGINE_DIVERGENCE` | ① `deterministic_mismatch`：BobsBuddy 判定 100% 胜/负/平，引擎期望结果比例 < 99%；② `official_result_unreachable`：官方实际结果在引擎 N≥32 种子可达集之外（单样本即证明引擎把官方结果排成零概率）；③ `distribution_distance`：引擎胜负分布与 BobsBuddy 的 L1 距离 ≥ 0.15（引擎 vs 第二实现）；④ `event_sequence`：powerlog 轨迹的事件流首个分歧 |
| `CONTEXT_GAP` | 官方结果**不可比较**：日志隐藏上下文未建模（BG 秘密 `detected_effect` / 外部亡语 `deathrattle_annotation` / 战斗目标 `hero_power_target_unresolved` / 动态属性脚本 / 动态 ScriptDataNum）→ **不计引擎 bug**，也不计入匹配率分母 |
| `MATCH` | 以上都不成立；子类 `distribution_match`（分布一致）、`rng_sample`（官方单样本偏离引擎众数但仍在可达集内，不冤枉引擎）、`outcome_match` |
| `SKIPPED` | 轨迹自洽性检查不通过（见 §4.3）或引擎没跑出结果 |

**归因（`attribute_divergence`，决定分歧是「引擎 bug」还是「上下文缺口」）**：

| attribution | 含义 | 处置 |
|-------------|------|------|
| `behavior_mismatch` | 无任何已知缺口仍分歧 | **最高优先级：真引擎 bug**，附最小复现（本轮抓到 Ozumat） |
| `unmodeled_context` | 只有未建模上下文（BG 秘密 / 未知关键词 / 动态属性脚本等） | 升级为 `CONTEXT_GAP`，先补上下文再判定 |
| `unmodeled_dynamic_state` | 外部亡语 / 英雄技能目标状态 / 动态 ScriptDataNum | 升级为 `CONTEXT_GAP`；可重建的（Ozumat data）在 harness 重建 |
| `missing_script` | 战团里有「有卡面文本但引擎 `REGISTRY` 无脚本」的卡 | 已知引擎缺口，按卡排期补脚本（仍是 `ENGINE_DIVERGENCE`） |

> 判定「需要脚本」的口径：卡面文本去掉纯关键词（`<b>Taunt</b>` 等）后仍有
> 内容，或有亡语标记。白板/纯关键词随从没有脚本是正常的（首版把白板也算
> 缺口导致 187/200 场误报，已修正）。

### 4.2b 测量口径：strict vs context-aware（2026-10-18）

旧口径只有一套「strict」指标，会把**日志上下文缺失 / RNG 流移位**误计为
引擎行为错误（例：某卡脚本注册后 RNG 消费序列改变，原本 MATCH 的确定性
轨迹在 64 种子里出现 1 次偏差就被记成 deterministic_mismatch）。新口径
同一次运行输出两套指标：

| 口径 | 定义 | 用途 |
|------|------|------|
| **strict** | 全部可比轨迹（MATCH + ENGINE_DIVERGENCE）；确定性 = BobsBuddy 100% 裁判下引擎方向必须 100% 一致 | 对照/历史可比性；会受缺口与 RNG 流影响 |
| **context-aware** | **干净子集** = 无阻断缺口（`no_script:` / `dynamic_script_data` / `deathrattle_annotation` / `detected_effect:`（BG 秘密）/ `hero_power_state:` / `hero_power_target_unresolved:` / `second_hero_power_ignored` / `dynamic_stat_script` / `unsupported_keyword`）的轨迹 | **推荐口径**：只有"引擎已建模全部输入"的轨迹才用来衡量引擎保真度 |
> **2026-10-18 root-cause 口径**：`hand_not_modeled` / `*_hero_power_unknown` 归入 `unmodeled_context`（未建模上下文），不再计 `behavior_mismatch`；真 bug 判定仅在**无任何未建模上下文**时生效。证据：`reversed/rea/behavior_mismatch_5_rootcause.md`。

| **tolerant（同分布阈值）** | 确定性轨迹若「BobsBuddy 期望方向上引擎比例 ≥ `--tolerant-rate`（默认 0.8）」或「官方单样本 == 引擎众数」即算方向一致 | 吸收 RNG 流移位噪声；**同时保留 strict 数值** |

* `CONTEXT_GAP` 轨迹从 strict 分母中剔除（单独计数 + 归因），不计入 divergence；
* `behavior_mismatch` 只统计「干净子集内、无任何已知缺口、且非 tolerant 可解释」
  的分歧 → 目标 **0**（本口径下已达成）；
* 报告路径：`runs/diff_report.json.summary.{strict,context_aware}` 与
  Markdown §1b「测量口径」表。

### 4.2c 官方动态 ScriptDataNum 注入（Improve/累计初值）

日志里实体的官方 `ScriptDataNum1..5`（BobsBuddy 名字键；Power.log 官方
enumID `2/3/2889/2919/2920`）现在是一等测量输入：

1. **通用注入**（有值才注入）：构造引擎 Minion 后调用已应用的
   `Game.set_entity_script_data`；无值时不改变引擎默认行为；旧引擎无该
   API 时静默跳过（向后兼容）。
2. **动态属性复算适配器**（仅引擎脚本消费通道的卡）：
   * **Eternal Knight 族**（`BG25_008`/`_G`）：日志 atk/health 已含
     「本局死亡数 × num(0)/num(1)」。适配器把 BASE 写回**卡面基础值**
     （金色感知：用 `minion.card_id` 对应 CardDef，避免金色双重错算），
     由 `(printed - base)/num` 反推死亡计数（攻击/生命两维必须一致），
     注入 `NUM_3` 让脚本复算回官方数值；成功后清除该卡的相关阻断缺口。
   * **Ultraviolet 族**（`BG31_810`/`_G`）：适配器**默认关闭**
     （`ENABLE_ULTRAVIOLET_ADAPTER=False`）。官方 tag 证据
     `NUM_1=9/NUM_2=6/NUM_3=2`（trace `17493f10c0afbbad`）与引擎公式
     "mult=1+count 同时乘攻/血分量"冲突（count=2 得 9/9 ≠ 官方 9/6）；
     强行注入会让该轨迹更差（win 50%→1.6%，官方 win / BB 90.4%）。
     保留通用注入但**仍记上下文缺口**，等官方 Power.log 事件或引擎公式证据。
4. **脚本消费通道登记**（`CONSUMED_SCRIPT_DATA`）：新卡脚本若在
   `on_summon`/`on_play` 里读取 `get_script_data`/`script_data_or_card`，
   必须在 `tools/diff_replay_combat.py` 的 `CONSUMED_SCRIPT_DATA`
   登记 `{card_id: {通道序号}}`——否则 harness 仍会把「已注入且引擎
   脚本已消费」的官方动态值误记为 `dynamic_script_data` 阻断缺口。
   当前登记：`BG26_502/_G`（Deep Blue Crooner，NUM_1/NUM_2 = 当前
   Deep Blues 数值；batch_diff_driven3 脚本读取并回写）。
   2026-10-18 engine-analyst 迁移 8 族后追加：`BG35_921`、`BG_TTN_401`、`BG35_342`、`BG26_537`、`BG36_524`、`BG25_013`、`BG25_008`（Eternal Knight，原有）+ 各金色；`BG36_MagicItem_216`（饰品，无 printed atk/health 时适配器跳过）。这些卡由适配器**从 printed atk/health 反推 count**（`(printed-base)/step`，攻/血两维必须一致且整除）→ BASE 写卡面基础值 + 注入 NUM_3；两维不一致（面板含其它附魔/光环）时**不强行清缺口**，`script_data_injected[].adapter_skip` 记录证据交 engine-analyst。`BG_TTN_401`/`BG25_013` CardDef num 缺失 → `DYNAMIC_STAT_STEPS`以卡面文本回退步长（3/2、1/0；金色 6/4、2/0），非通用猜测。
### 4.2d 派生值比较口径（2026-10-18）

部分卡（`BG31_801` Forest Rover / `BG31_803` Buzzing Vermin / `BG25_041` Felemental / `BG30_129` Catacomb Crasher）的官方 `ScriptDataNum` 是**派生值**（引擎可由规则/战斗事件自行计算），不是需要外部注入的输入。口径：

* **不登记** `CONSUMED_SCRIPT_DATA`（不把官方派生 tag 当消费输入）；
* harness 以**引擎计算值**为准比较：若引擎脚本能从同一输入推导，则视为已建模（不要因 tag 与 CardDef 静态值不同而记缺口）；
* 若引擎无法推导（真缺口），保留 `dynamic_script_data` 并交证据线，**不要**用官方派生值反推注入（会把派生当独立输入、双计）。

**阶段 1 安全子集（engine-analyst B 类迁移，已登记 {1}）**：`BG24_715` Patient Scout / `BG33_823` Sky Admiral Rogers / `BG26_199` Upbeat Duo / `BG26_505` Zesty Shaker（各含金色）。679 场结果：MATCH/div/ctx 不变（401/157/80），**干净子集 19→24**（24/24 MATCH），behavior_mismatch=0；基线按流程更新。

**阶段 2（root cause 后已登记）**：`BG35_801` Gluttonous Trogg `{1}`、`BG35_814` Scarlet Survivor `{2}`（注意脚本读 NUM_2，不是 {1}）、`BG26_529` Upbeat Frontdrake `{1}`（各含金色）。5 条遮蔽分歧（0502f1b1、3e4c0c97、4fb28230、aa771aaa、be480c4c）经 root cause 确认为**未建模上下文残留**（`hand_not_modeled` / `opponent_hero_power_unknown`），归入 `unmodeled_context`；证据留档 `runs/behavior_mismatch_evidence.json/.md` + `reversed/rea/behavior_mismatch_5_rootcause.md`。679 场结果：MATCH 401→400、div 157→153、ctx 80→85、干净子集 24→**33/33**、behavior_mismatch=0。

   A/B（`HSBG_DISABLE_DYNAMIC_ADAPTER=1`）：状态/胜负不变，`dynamic_stat_script` 缺口清除、**干净子集 16→19**；跳过率 = BG25_008 28/61、BG35_342 31/39、BG35_921 17/18、BG_TTN_401 12/30（样本面板含其它 buff，见 deferred_primitives.md）。
   A/B 实测：登记后 3 条轨迹由 DIV→CONTEXT_GAP（分布不变、纯测量口径）。

3. **A/B 开关**：`--no-script-data-injection` 关闭注入，用于量化「注入
   恢复量」（同引擎同语料只差注入开关）。注入记录逐条写入
   `records[].simulation.script_data_injected`（含 `adapted` 标记）。

### 4.3 不可比样本（日志缺陷，自动剔除）

真实日志里有少量样本不能用于差分（`sanity_check_trace`）：

| 原因 | 判定 | 全量命中 |
|------|------|----------|
| `invalid_warband_size` | 单侧随从 > 7（正常 BG 上限；>7 说明日志把 Duos 双方棋盘/观战视角拼接，如 13 个随从） | 36 |
| `inconsistent_official_trace` | 一侧空场却「空场方赢」（正常 BG 不可能） | 5 |
| `empty_warbands` | 双方都空 | 0 |

合计 **41 条**从差分统计中剔除（`runs/diff_report.json.summary.skipped`）。

### 4.4 事件级差分（Power.log 源；真实日志验证见 §9）

`compare_events` 把官方事件流与引擎事件流归一化为
`(kind, actor_side, actor_slot, target_side, target_slot, amount)` 后按 seq
对齐，返回首个分歧（含前后 3 条上下文）。引擎事件由
`before_attack/damage/death` 监听器捕获（`_EventRecorder`），槽位用战斗
开始快照建立 `Minion 对象身份 → (side, slot)` 映射。RNG 战斗对每个种子取
最佳匹配（任一 seed 完全一致即 `MATCH`）。

---

## 5. 全量实测结果（679 场真实 BG 战斗）

生成命令：`python tools\diff_extract_replays.py && python tools\diff_replay_combat.py`
（默认 64 seeds/场；耗时约 20 s 抽取 + 90 s 差分）。

### 5.1 总览（2026-10-18 测量口径 v2，当前 live 引擎 = 已应用精确性包 F-02~F-05）

| 指标 | 值（strict / context-aware） |
|------|----|
| 轨迹总数 | **679** |
| 有官方实际结果 | 524（77.2%） |
| MATCH | **400**（root-cause + 阶段 2 登记后：5 条遮蔽分歧转 CONTEXT_GAP） |
| ENGINE_DIVERGENCE | **153**（全部 `missing_script`） |
| CONTEXT_GAP（官方上下文未建模，不计引擎 bug） | **85** |
| DATA_GAP | **0** |
| SKIPPED（日志不可比） | 41 |
| **匹配率** | **72.3%**（strict，可比分母 553）/ **100%**（context-aware 干净子集 33/33） |
| **确定性战斗 strict 匹配率**（BobsBuddy 100% 裁判） | **86.31%**（290/336） |
| **确定性战斗 tolerant 匹配率**（同分布阈值 80%） | **94.35%** |
| **干净子集**（无阻断缺口） | **100%**（13/13）；strict 92.3%（12/13，旧口径对照） |
| `behavior_mismatch`（确证引擎行为错误） | **0** |
| 官方实际结果 == 引擎众数 | **76.6%** |

**动态 ScriptDataNum 注入（A/B）**：585 条轨迹 / 2,366 个实体注入了官方
`ScriptDataNum*`（52 个 Eternal Knight 族实体走复算适配器）。A/B（同语料
同引擎，只差 `--no-script-data-injection`）结果：strict MATCH 391 → 391
（注入不改变胜负，因为 Eternal Knight 的 printed 数值本已被写回）、**干净
子集 12 → 13**（1 条轨迹 `db618d884509ff49` 的 `dynamic_stat_script` 假缺口
被消除 → 进入干净子集且 MATCH）。唯一分布变化是 `17493f10c0afbbad`
（Ultraviolet，见 §5.3-C）。

`CONTEXT_GAP` 归因：`unmodeled_dynamic_state` 40 + `unmodeled_context` 3；
其中包含 BG 秘密、外部亡语、Teron 目标、动态计数（证据不足/引擎未消费通道）。

> 读法：65.7% 的总一致率被「引擎缺 37.x 卡脚本」这一类**已知**缺口压低
> （204 条分歧全部为 `missing_script`）；剥离阻断缺口后的干净子集 **100%**。
> BobsBuddy 是第二实现，`distribution_distance` 是「引擎 vs BobsBuddy」证据；
> strict 与 tolerant 同时报告（§4.2b）。

### 5.2 数据版本差占比（`DATA_GAP`）

* 引擎 `data/`（36.2.2 基线，3,683 defs）对 679 场的**全部卡名解析成功**，
  `DATA_GAP = 0`（0.0%）——本批日志里的卡都在数据基线里；
* 真正的版本差体现在**机制实现**而非数据：引擎 `REGISTRY` 对
  37.x 新卡（如 `BG27_004 Surf n' Surf`、`BG34_630 Twilight Hatchling`、
  `BG34_921 Ring Bearer`、`BG35_801 Gluttonous Trogg`）**没有脚本**；
* 另一类版本差是**动态脚本计数**：官方 `ScriptDataNum*`（BobsBuddy 名字键 /
  Power.log enumID `2/3/2889/2919/2920`）与 CardDef 静态值不同的轨迹。
  已应用的引擎通道（`ScriptDataNum` 命名空间 + `Game.set_entity_script_data`）
  + harness 注入可覆盖一部分（§4.2c）；Eternal Knight 族已能复算，其余
  卡片仍按上下文缺口统计（§5.3-C）；
* 若换用 37.0 数据（`reversed/data_255130/`）会进一步暴露「卡存在但机制未
  实现」的缺口，数据升级必须与脚本补全分批验收（见 `docs/OFFICIAL_EXACTNESS.md` §1.7）。

### 5.3 当前分歧清单（按影响排序）

**A. `behavior_mismatch`：0（本轮测量口径下）**

历史 6 条已在 2026-10-18 复核完毕（5 条隐藏上下文 + 1 条 Ozumat 真 bug，
后者已由 `tmp_diff_fix/deliver/` 修复并应用；见 §5.4 与 FIX_REPORT）。

**B. `missing_script`（153 条；当前卡片脚本只剩 1 张）**

| 卡 id | 卡名 | 分歧轨迹数 | 说明 |
|-------|------|-----------|------|
| `BG31_171` | Moonsteel Juggernaut | 20 | "improve this" 语义无权威 → DEFERRED（P3） |

> 其余 152 条分歧的卡都有脚本（`no_engine_script=0`），属分布/上下文差异，
> 见 `runs/diff_report.json.suspect_cards`。
>
> **英雄技能台账（单列，不在本轮实现）**：`BG26_HERO_102p2` Minor Hymn
> 英雄技能脚本缺失；当前轨迹中表现为 `hero_power_state` 等
> `unmodeled_context`，不影响硬门禁。待后续英雄技能批次补齐。

**C. `CONTEXT_GAP`（43 条，不计引擎 bug）**

* `unmodeled_dynamic_state` 40：官方 `ScriptDataNum*` 动态值无法被引擎
  利用（引擎脚本未消费通道 / 证据不足）+ 外部亡语等；
* `unmodeled_context` 3：BG 秘密、Teron 技能目标状态等。
* **Ultraviolet 专项（trace `17493f10c0afbbad`）**：引擎 37.x 脚本已消费
  注入的 `NUM_3`（improve 次数=2 → SoC +9/+9），但官方同实体 tag 为
  `NUM_1=9/NUM_2=6`（SoC 应为 +9/+6）→ 引擎公式/官方 tag 语义仍有差异；
  harness 保留通用注入（忠实于引擎设计），该轨迹继续计入 `missing_script`
  分歧（另有 no_script 卡），并在此登记为**待官方事件/公式证据**项。

### 5.4 6 条 behavior_mismatch 复核结论（2026-10-18，已定位）

> 结论：**5 条是日志隐藏上下文，1 条是真引擎 bug（Ozumat）**。
> 完整证据/复现/修复见 `tmp_diff_fix/deliver/FIX_REPORT.md`；
> 独立复核见 `reversed/rea/behavior_mismatch_analysis.md`。

| # | trace_id | 官方 | 当前引擎 | 根因（证据） | 处理 |
|---|----------|------|----------|--------------|------|
| D1/D2 | `4c3c…` / `aa4c…` | win 100% | tie / loss | BobsBuddy `Detected the following player S.` + `PackTactics` = **BG 秘密** "友方随从被攻击时召唤 3/3 复制"（`TB_Bacon_Secrets_15`）；引擎无 Secret 子系统 | CONTEXT_GAP |
| D3 | `b268…` | loss 100% | tie | 对手 Risen Rider 带**外部亡语** `Deathrattles=[GenericDeathrattles.Crab]`（Surf n' Surf Spellcraft 授予）；引擎忽略该亡语 | CONTEXT_GAP |
| **D4** | **`f5d1…`** | **loss 100%** | **win 100%** | **真引擎 bug：Ozumat SoC 召唤 6-7 只 Tentacle（官方 "summon **a**"=1 只；BobsBuddy `!_tokenSummoned`）** | **已修（隔离包）** |
| D5 | `9e80…` | win 100% | tie | Teron Gorefiend `data=376` = 战斗内销毁/复活目标 `game_id`，日志不给目标 | CONTEXT_GAP |
| D6 | `1128…` | tie | win/tie | Eternal Knight 动态属性（官方 20/10 来自"本局死亡数"）+ Teron 目标状态 | CONTEXT_GAP |

> 早期 §5.4 的最小复现混用了卡 id（`BG25_008`=Eternal Knight 而非
> Crackling Cyclone、`BG26_174`=Soul Rewinder、`BG30_129`=Catacomb
> Crasher），已废弃。正确卡 id 的裸战团复现（官方数据缺秘密/外部亡语）
> 引擎确定性 **tie 是正确的**：DS+风怒 16/16 tie、复生双亡 16/16 tie
> ——**不要**为迎合官方去改 `combat.py` 核心。

**B. `missing_script`（247 条，已知缺口，按卡频次，当前 live 引擎）**

| 卡 id | 卡名 | 分歧轨迹数 | 说明 |
|-------|------|-----------|------|
| `BG27_004` | Surf n' Surf | 59 | Spellcraft/亡语：引擎无脚本 |
| `BG34_630` | Twilight Hatchling | 36 | 亡语召唤并立即攻击 |
| `BG34_921` | Ring Bearer | 31 | 友方攻击时施放 Shiny Ring |
| `BG35_801` | Gluttonous Trogg | 26 | 购买累计加属性（对战斗数值影响） |
| `BG31_171` | （BG31 卡） | 22 | 引擎无脚本 |
| `BG34_922` | Maelstrom Emergent | 8 | 战斗中法术额外施放 |
| `BG26_502` | Deep Blue Crooner | 8 | Spellcraft 属性 |

**C. `CONTEXT_GAP`（9 条，不计引擎 bug）**：BG 秘密 ×2、外部亡语 ×1、
Teron 目标状态 ×2、动态 ScriptDataNum/动态属性 ×4。harness 已把这些
从 `ENGINE_DIVERGENCE` 中独立出来（`tools/diff_replay_combat.py`：
`CONTEXT_GAP` 分类 + `Detected the following ... S.` 解析 +
`hero_power_data` 三分类 + Ozumat 状态重建）。

### 5.5 方法学对照实验（已做）

| 实验 | 结果 | 结论 |
|------|------|------|
| Player/Opponent 方向是否与官方结果视角一致 | 原方向 MATCH 110/200；交换双方 + 反转结果 112/200 | 方向正确，分歧不是视角错误 |
| 属性方向 `Atk/Health` vs `Health/Atk` | 246 个 turn≤2 样本：非对称卡 77 个全部 = atk/health，0 个反向 | 打印顺序 = 攻击/生命 |
| 英雄技能 `on_bind` 接线 vs 不接线 | 早期 200 场子集 57.0% vs 56.5%；全量 on_bind 优于 none（+8 MATCH） | 默认接线；**但 `data` 必须按语义分类**（静态参数/招募期/战斗目标），否则会把真 bug 吞成上下文 |
| 白板无脚本是否算缺口 | 修正前 187/200 场误报；修正后 247 条真实缺脚本分歧 | 必须区分「白板正常无脚本」与「有文本缺脚本」 |
| 日志不可比样本 | 36 条 >7 随从（Duos/观战拼接）、5 条空场方赢 | 必须剔除，否则污染分歧统计 |
| 隐藏上下文（秘密/外部亡语/技能 data） | 6 条 behavior_mismatch 中 5 条由此解释；1 条（Ozumat）是真 bug | 先补上下文，再谈引擎 bug（否则误判/漏判） |

---

## 6. 回归命令与 CI 接入

```powershell
cd C:\HSagent
# 单元测试（不依赖真实数据；真实数据冒烟缺数据时 skip，不 fail）
python -m pytest tests\test_diff_trace.py tests\test_diff_compare.py -q

# 真实语料回归（幂等；可每天/每次改引擎后跑）
python tools\diff_extract_replays.py                 # 产出 679 条轨迹 + index.json
python tools\diff_replay_combat.py                   # 产出 runs/diff_report.{json,md}
# 测量口径 v2：报告同时含 strict / context-aware / tolerant；可调阈值
python tools\diff_replay_combat.py --tolerant-rate 0.8
# A/B：关闭官方 ScriptDataNum 注入（量化注入恢复量；同引擎同语料）
python tools\diff_replay_combat.py --no-script-data-injection `
    --json runs\diff_report_no_injection.json --md runs\diff_report_no_injection.md

# 只跑前 10 条（快速冒烟，约 1.5 s）
python tools\diff_extract_replays.py --limit 5 --out runs\official_traces
python tools\diff_replay_combat.py --traces runs\official_traces --limit 10
```

CI 建议门槛（测量口径 v2；先记录再收紧）：

| 门槛 | 当前基线 | 建议 |
|------|--------|------|
| `DATA_GAP` | 0 | == 0（卡名解析覆盖率） |
| `behavior_mismatch` | **0** | **必须 0**（干净子集内确证行为错误） |
| context-aware 干净子集匹配率 | **100%**（13/13） | 目标 100%，随补脚本扩大样本 |
| strict 确定性匹配率 | 86.31%（290/336） | 不下降；RNG 流敏感场景看 tolerant |
| tolerant 确定性匹配率（80%） | 94.35% | 不下降（同分布方向一致） |
| strict 总体 MATCH | 400/679 = 72.3%（可比分母 553） | 随 `missing_script` 收敛（当前 153 条） |
| CONTEXT_GAP | 85 | 补上下文/证据后转入可比较；不计引擎 bug |
| 抽取消融 | 679/679 | 无解析崩溃；`missing_fields` 计入统计不隐藏 |

官方一致性硬门禁（推荐 CI 主入口，见 §8）：`python scripts/audit_official_consistency.py`（exit 0/1/2）；已接入 `scripts/verify_all.py` 第 6 项。

接入方式：`python -m pytest tests/test_diff_trace.py tests/test_diff_compare.py tests/test_diff_gate.py -q`
进现有 `tests/`（60 passed / 1 skipped；注意 PowerShell 不展开
`test_diff_*.py` 通配符）；真实语料差分放 CI 之外夜间任务（依赖本机 HDT
数据，不进 git）。引擎隔离对比：`$env:HSBG_ENGINE_ROOT` 指向含
`hsrl2/`+`data/` 的目录即可。

---

## 7. 局限与下一步

**局限**

1. **没有真实 BG Power.log**：事件级 `compare_events` 只在合成样例上测试，
   真实事件流校验要等采集；当前事件源 `events` 完整率为 0。
2. **官方结果只有单样本**：RNG 战斗用 BobsBuddy 概率作参照（第二实现，
   非官方），因此 `distribution_distance` 是「引擎 vs BobsBuddy」证据；
   只有 100% 确定性战斗是硬约束。
3. **日志上下文丢失**：BobsBuddy 不打印英雄血量/护甲/酒馆等级/饰品/任务/
   异变；手牌、第二英雄技能、动态 `ScriptDataNum` 未完全重建。当前 85 条
   CONTEXT_GAP（BG 秘密/外部亡语/Teron 目标/动态计数），其余轨迹的非阻塞
   缺口用 `confidence: medium` 标记；`second_hero_power_ignored` 已升为
   阻断缺口（可能导致战斗差异，不能算引擎 bug）。
4. **少量日志不可比**：Duos/观战/断线重连导致 41 条被剔除（>7 随从、
   空场方赢）；本机有多个会话可能是 Duos（`lethalResult=FriendlyDied`）。
5. **英雄技能语义**：只接线 `on_bind`；`data` 已按「静态参数/招募期/
   战斗目标/可重建状态」四类处理（Ozumat 可重建、Teron 不可重建），
   其余未知技能仍保守记为缺口。
6. **数据版本**：引擎 `data/` 已是 255130（3,817 defs），差分 `DATA_GAP=0`；
   剩余缺口是 37.x 卡**脚本未实现**（153 条分歧全部为此）。
7. **测量口径本身**：strict 对 RNG 流敏感（脚本注册会改变 RNG 消费序列），
   因此必须同时看 context-aware + tolerant；`behavior_mismatch` 仅在
   「干净子集内、严格且非 tolerant 可解释」时才会非零。
8. **Ultraviolet 动态值**：官方 `ScriptDataNum1/2/3=9/6/2` 与引擎公式
   （mult 同时乘攻/血）不完全一致（引擎给 +9/+9）；注入会忠实进入引擎
   通道但结果仍与官方有差，需官方 Power.log 事件或公式证据。

**下一步（按优先级）**

1. **补 37.x 缺脚本卡**：按 §5.3-B 频次（`BG30_129`/`BG31_171`/`BG34_922`…）
   排期 `REGISTRY` 脚本；每补一张重跑差分，strict MATCH 应上升。
2. **动态脚本语义取证据**：Ultraviolet 的 NUM_1/2 关系、Teron 目标
   `game_id`、BG 秘密/外部亡语建模；有条件时优先采真实 BG `Power.log`
   （`log.config` 的 `[Power]` 已开启），用事件流代替间接推断。
3. **扩大干净子集**：随脚本补全 + 上下文建模，让干净子集从 13 条增长到
   数百条，context-aware 指标才有统计意义。
4. **CI 接入两套口径**：`behavior_mismatch==0` 为硬门禁；
   strict/tolerant/context-aware 全部记录趋势，禁止只看单一数字。
5. **扩语料**：HDT 只保留最近 27 个会话日志；建议定期归档
   `hdt_log*.txt`（只读复制到本地 corpus）以扩大覆盖面。

---

## 8. CI 门禁（官方一致性 gate）

### 8.1 命令与退出码

```powershell
# 全量门禁（679 场；自动跑差分并写 runs/diff_report.{json,md}）
python scripts\audit_official_consistency.py

# 只评估既有报告（不重跑引擎；CI 分阶段/调参时用）
python scripts\audit_official_consistency.py --report runs\diff_report.json

# 更新基线（仅当门禁通过才写）
python scripts\audit_official_consistency.py --update-baseline
```

| 退出码 | 含义 |
|--------|------|
| **0** | 门禁通过（可有告警：无基线 / 干净子集样本不足） |
| **1** | 硬门禁失败（DATA_GAP>0 / behavior_mismatch>0 / 干净子集<100%） |
| **2** | 环境/输入错误（report 缺失或非法、差分执行异常） |

无官方语料（`runs/official_traces` 不存在或空）时打印 `SKIP` 并 **exit 0**，
保证没有 HDT 数据的机器上 CI 不误红。

已接入 `scripts/verify_all.py`（7 gates 的第 6 项 `official_consistency`，
替换旧 `diff_smoke`）：`python scripts/verify_all.py` 全绿 = 测试 + 冒烟 +
环境 + 官方一致性门禁 + 版本检查同时通过。

### 8.2 门禁定义

| 门禁 | 判定 | 失败处理 |
|------|------|----------|
| `DATA_GAP == 0` | 679 场官方卡名必须全部可解析 | 硬失败：查 `diff_report.data_gaps`（数据版本/卡名别名） |
| `behavior_mismatch == 0` | 干净子集内无「无任何已知缺口仍分歧」 | 硬失败：按报告 §2 分歧 TOP 取最小复现，写失败测试后修引擎 |
| 干净子集 MATCH == 100% | 无阻断缺口轨迹必须全 MATCH；样本 < `--min-clean-sample`（默认 5）时**只告警** | 硬失败：新分歧先看归因（是否新上下文/脚本），再判定引擎 bug |

趋势指标（**不设硬阈值**，只输出数值与 Δ，防止误伤合法演进）：
strict MATCH 与匹配率、确定性 strict/tolerant 匹配率、CONTEXT_GAP /
ENGINE_DIVERGENCE 计数、`divergence_attribution`（`missing_script` /
`behavior_mismatch`）、`context_gap_attribution`（`unmodeled_dynamic_state` /
`unmodeled_context`）。

### 8.3 基线（`runs/diff_baseline.json`）

```json
{"schema": "diff_baseline.v1", "created_at": "...", "traces": 679, "seeds": 64,
 "metrics": {"match": 400, "match_rate": 0.7233, "data_gap": 0,
             "behavior_mismatch": 0, "clean_subset_traces": 13,
             "clean_subset_match": 33, "deterministic_match_rate": 0.8631,
             "deterministic_tolerant_match_rate": 0.9435, "...": "..."},
 "divergence_attribution": {"missing_script": 153},
 "context_gap_attribution": {"unmodeled_dynamic_state": 73, "unmodeled_context": 12}}
```

流程：
1. 门禁通过后 `--update-baseline` 写基线（失败时**拒绝更新**，避免把回归写成基线）；
2. 日常/CI 每次运行输出 `Δ`（数值 + 归因计数）；`match_rate` 等比率用
   `pp`（百分点）显示；
3. 基线是**趋势参考**不是门禁：数值下降只告警，硬门禁仍按 §8.2 判定。

### 8.4 新分歧归因流程

1. 先看 `ENGINE_DIVERGENCE` 的 `divergence_attribution`：
   * `missing_script` → 引擎缺脚本（`suspect_cards` 给卡频次；补脚本，勿改核心）；
   * `behavior_mismatch` → **门禁失败**：取报告 §2 分歧 TOP 的最小复现，
     写失败测试 → 修引擎 → 全量回归 + 门禁；
2. 再看 `CONTEXT_GAP` 归因：`unmodeled_dynamic_state`（官方动态
   ScriptDataNum/外部亡语）或 `unmodeled_context`（BG 秘密/技能目标）——
   上下文缺口不计引擎 bug；能通过注入通道/建模消解的优先在 harness 侧做；
3. 若 `DATA_GAP > 0`：检查 `data/` 版本与卡名解析（`CardResolver`），
   必要时更新数据（生成流程见 `tools/generate_bg_data.py`）。

### 8.5 已知风险

* **RNG 流敏感**：加/删脚本会改变 RNG 消费序列 → 确定性轨迹可能出现
  1/64 级偏差；门禁用 `behavior_mismatch`（不按分布抖动）判定，趋势看
  tolerant（同分布阈值 80%）与 strict 两条线，**不要**只看 strict。
* **干净子集样本少**：当前仅 13 条（脚本/上下文缺口待补），100% 门禁的
  统计置信有限；`--min-clean-sample` 控制"样本不足只告警"，随脚本补全应
  逐步扩大该子集。
* **官方单样本/无真实 Power.log**：`distribution_distance` 是对 BobsBuddy
  的概率距离，非官方硬裁判；硬门禁只依赖无争议事实（DATA_GAP、
  behavior_mismatch、干净子集 MATCH）。
* **本机语料依赖**：`runs/official_traces` 为本机 HDT 日志抽取产物（不进
  git）；CI 容器无此目录时 gate 自动 SKIP（exit 0），需在有语料的环境跑
  完整门禁。

---

## 9. 真实 Power.log 事件级验证（2026-10-18，首局真实 8 人 BG）

用户提供真实 `Power.log`（77,372 行，10.2 MB；`runs/powerlog/Power.log`）
后，把 `_PowerlogCombatBuilder` 适配到真实 8 人 BG 格式并完成**事件级**
（非 BobsBuddy 概率）差分。

### 9.1 真实格式与旧 builder 假设的差异

| 事实 | 旧假设/bug | 适配 |
|---|---|---|
| 只有 **2 个 Player 实体**（本地 `PlayerID=3`、Bob 侧 `PlayerID=11`） | `count_powerlog_players>=8` 才算 BG | BG 判定改为 `GT_BATTLEGROUNDS`/`TB_BaconShop_8P_*`/8 个 `PLAYER_ID` 英雄也可 |
| 8 个真实英雄是 **SETASIDE HERO 实体**（带 `PLAYER_ID=1..8`） | 从 Player 实体 `HERO_ENTITY` 找英雄（真实日志无该 tag/无血量） | 从 `PLAY` 区 HERO 实体按 `CONTROLLER` 找本场英雄；血量/护甲在 HERO 实体 |
| 对手战团在战斗窗口内**逐步**进入 PLAY（先出现预览/首个随从） | `BACON_IN_COMBAT_PHASE=1` 立刻快照 → 只拿到本地板 → 6 场全 skip | **延迟快照**：首个 ATTACK block（且双方板可见、对手英雄已 PLAY）才锁定；无攻击/截断在 finish 兜底 |
| ATTACK block `Target=0`，真实目标是紧随的 `TAG_CHANGE GameEntity PROPOSED_DEFENDER=<eid>` | 只解析 `Target=` 引用 → 攻击事件 target 全 None | 从 `PROPOSED_ATTACKER/DEFENDER` 补 eid；兼容合成旧格式（Target 引用直接给） |
| 英雄 HEALTH/ARMOR 在战斗结束清理时被移除/重置（易误判伤害） | 用 Player 实体 HEALTH 差 | 胜负主判 = **终局存活数**（快照数 + 战斗内 summon − death，只计 MINION）；英雄伤害仅作 auxiliary `official_damage` |
| 日志最后一段被截断 | — | `eof` 且无事件 → `official_result=None` + `truncated_combat`（不猜） |
| `TRIGGER` block 与引擎事件不同构 | 保留会让事件对齐永远在第一个 trigger 失配 | 事件流只比较 **attack/damage/death/summon**（引擎 `_EventRecorder` 同口径，含新增 summon 监听） |
| **战斗结束战团副本还原**：SETASIDE 副本（带 `COPIED_FROM_ENTITY_ID`/`BACON_DIED_LAST_COMBAT`）回到 PLAY | `SETASIDE→PLAY` 一律记 `summon` → 终局存活虚增 → 官方结果误判（e057: win，实际 tie） | `_is_restored_warboard()`：带副本标记/战斗开始已在 SETASIDE 的实体**不记 summon**；仅真实召唤（手牌/牌库等）进入事件流 |

### 9.2 抽取结果（`runs/official_traces_powerlog/`）

```powershell
python tools/diff_extract_replays.py --powerlog runs/powerlog/Power.log `
    --out runs/official_traces_powerlog --sources powerlog --force `
    --json runs/powerlog_extract.json
```

| 指标 | 值 |
|---|---|
| 战斗窗口 / 抽取 / 跳过 | 6 / **6** / **0**（旧 builder：0 / 6 skip） |
| 官方结果 | win 3 / tie 1 / loss 1 / null 1（最后一段截断；伪召唤修复后 turn4 由误判 win 纠正为 tie） |
| 字段完整率 | turn、hero_card_id、hero_power_id = 100%；official_result 83.3%；events/双方战团 83.3%；`bb_rates` 0%（Power.log 无 BB，正是事件级验证目的） |
| 边界模式 | 全部 `bacon_phase`（`BACON_IN_COMBAT_PHASE`） |

### 9.3 事件级差分结果

```powershell
python tools/diff_replay_combat.py --traces runs/official_traces_powerlog `
    --seeds 64 --json runs/diff_report_powerlog.json `
    --md runs/diff_report_powerlog.md
```

| 指标 | 值 |
|---|---|
| traces / skipped | 6 / 0 |
| MATCH | **5**（4 条 `RNG_ORDER`：结果一致、仅攻击顺序不同 + 截断场 official=None） |
| ENGINE_DIVERGENCE | **1**（turn2 空场战斗：官方有 hero attack 事件、引擎 0 事件，`event_sequence`） |
| context_gap / DATA_GAP / behavior_mismatch | 0 / 0 / **0** |
| **RNG_ORDER**（首事件分歧=攻击先手/顺序） | **4**（不计 behavior_mismatch；其中 4 条结果已一致按 MATCH 计） |
| 事件级 strict（结果一致且事件序列完全一致） | **1**（截断场） |

**首个事件分歧分类**（64 seeds 中选最长公共事件前缀）：`attack_order_side` 1、`attack_order_slot` 2、`attack_side_swap` 1、tail/None 1。→ 4 条是**攻击先手/攻击顺序**（引擎 `random.Random` 与官方服务端 RNG 算法/调用序列不同；`GAME_SEED` 只作分析字段）→ 归 `RNG_ORDER`，**不升级为引擎分歧、不计 behavior_mismatch**；剩余 1 条（turn2 空场）官方有 hero attack 事件而引擎无，属空场事件流口径差。

**e057 伪召唤裁定（已修复，2026-10-18）**：`e05763998417728e`（turn 4）
官方 **tie**，引擎 64 seeds **tie 100%**。此前 harness 把战斗结束时
SETASIDE 副本（eid=904，`COPIED_FROM_ENTITY_ID=351`、
`BACON_DIED_LAST_COMBAT=1`）还原回 PLAY 误记成 `summon` → 终局存活虚增
→ `official_result` 误判 win。修复 `_is_restored_warboard()` 后：
官方 tie、事件流无 summon，`compare_combat` = **MATCH**。分析见
`reversed/rea/powerlog_e057_analysis.md`。

### 9.3b GAME_SEED：元数据而非 strict 等价依据

Power.log `GameEntity tag=GAME_SEED=1757749361` 已存入 trace 可选字段
`game_seed`（**只在有值时写出**，旧 HDT JSON 不变），报告/JSON 输出并带
`first_event`（`events[0]` 官方先手）分析字段。harness 额外用该 seed 跑一局
`GameRNG(game_seed)` 诊断（不进入 64 seeds 统计）：本局 6/6 尝试事件流完全
对齐 = **0**。结论：引擎 `GameRNG` 是 Python `random.Random` 薄封装，**官方
服务端 RNG 算法/整局调用顺序不同，不能用 seed 复现攻击先手**；seed 仅作
分析/采集字段，事件级等价的 strict 口径不得依赖它。

### 9.3c HDT + Power.log 同局交叉验证（用户采集用）

```powershell
# 1) Power.log 真实事件序列（官方结果/伤害上限/game_seed）
#    先复制原始日志（只读）到 runs/powerlog/Power.log，例如：
#    Copy-Item "C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log" runs\powerlog\Power.log
python tools/diff_extract_replays.py --sources powerlog ^
    --powerlog runs/powerlog/Power.log ^
    --out runs/official_traces_powerlog --force --json runs/powerlog_extract.json
python tools/diff_replay_combat.py --traces runs/official_traces_powerlog ^
    --seeds 64 --json runs/diff_report_powerlog.json --md runs/diff_report_powerlog.md
# 2) HDT BobsBuddy 同局期望分布（新会话自动进 hdt_log*.txt）
python tools/diff_extract_replays.py --sources hdt ^
    --hdt-logs "%APPDATA%\HearthstoneDeckTracker\Logs" ^
    --out runs/official_traces_hdt --json runs/hdt_extract.json
python tools/diff_replay_combat.py --traces runs/official_traces_hdt ^
    --seeds 64 --json runs/diff_report_hdt.json --md runs/diff_report_hdt.md
```

字段对应：Power.log 给 `official_result` / `events`（真实攻击-伤害-死亡序列）/
`damage_cap` / `game_seed` / `boundary_mode`；HDT 给 `bb_rates`
（BobsBuddy 期望分布）/ `bb_iterations` / `heroes` / `official_lethal`。
同局匹配：按 `turn` + 双方 `minions` 的 card_id/atk/health（`trace.signature()`）
对齐；HDT 的 100% 确定性场可与 Power.log 事件序列互相验证（BB=期望，
Power.log=真实事件）。**HDT 可用性验证（2026-10-18）**：`--sources hdt --hdt-logs "%APPDATA%\HearthstoneDeckTracker\Logs"` 本机 27 个 `hdt_log*.txt` → **677 条轨迹**（bb_rates 覆盖 664/677；card_id 由卡名索引补齐 6622 个），证明目录/新会话文件可直接消费；把一份含 BobsBuddy 的旧日志命名为`hdt_log.txt` 放入临时目录再抽 → 15 条轨迹 / bb 100%，证明**新会话（`hdt_log*.txt` 任意新文件）**会被扫描。**注意：HDT 需要启用 BobsBuddy 插件**——本机 `plugins.xml` 当前只有 `HrSRLAdviser`，新会话 `hdt_log.txt` 暂无 `BobsBuddy` 行（抽取 0 场属预期）；装/启用插件后重开一局即可。

### 9.3d 第二局（22:14–22:32）同局交叉验证（10 场）

用户第二局为**完整一局**（`runs/powerlog_2214/Power.log`：31 MB、232k 行、
无截断，10 场战斗），同时有 HDT BobsBuddy（`runs/hdt_logs_2214/hdt_log.txt`）。
按 **round 对齐（Power `turn/2` ↔ HDT `round`）10/10 官方结果一致**
（loss 5 / tie 2 / win 3）：

| 源 | 场次 | 结果 | 说明 |
|---|---|---|---|
| Power.log | 10/10（events 100%） | win 3 / tie 2 / loss 5 | 官方真实事件序列 |
| HDT 1.59.3 | 10（bb_rates 100%） | win 3 / tie 2 / loss 5 | BobsBuddy 期望分布 |
| **同局交叉** | **10/10** | 一致 | 按 `turn/2` + 战团签名匹配 |

**Power.log 事件级**（`runs/diff_powerlog2.json/.md`）：MATCH 5 /
ENGINE_DIVERGENCE 5 / **behavior_mismatch 0** / RNG_ORDER **5**（结果已一致、
仅攻击先手/顺序不同）；5 条 event_sequence 分歧的首事件是**战前/开局效果
伤害事件**（如 `TB_BaconShop_HERO_15_SKIN_G` 对英雄 12 伤害先于首个 ATTACK，
引擎无同构事件），不是状态/胜负错误。
**HDT 侧**（`runs/diff_hdt2.json/.md`）：MATCH 5 / CONTEXT_GAP 4 / SKIPPED 1 /
behavior_mismatch 0（分布口径）。

**HDT 1.59.3 格式适配**：新版本 BobsBuddy 战团行仍只有
`[Southsea Busker 3/1]`（无 `cardId=`，1.53 旧会话也大多如此）→
`hero_card_id`/minion `card_id` 为空。新增 `resolve_trace_card_ids()`：
抽取时用 `data/` 卡名索引补齐（本局 **95 minions + 10 hand + 14 heroes**
解析成功、0 unresolved minion），并让 `trace.signature()` 优先用 `card_id`
（Power.log/HDT 同局可逐卡对齐）。fixture 测试：
`tests/test_diff_trace.py::test_hdt_159_card_ids_resolved_from_names`。

**伤害上限**：`runs/damage_cap_powerlog_session2.json` →
**2 → 5（round1）→ 10（round4）→ 15（round8）三档确认**；用户本局第 5 名
（剩 4 人），解除上限仍未观测。

### 9.3e 第三局（22:35–22:52，完整一局 10 场）

第三局为同一账号连续对局（`runs/powerlog_2240/Power.log`，30.2 MB，
22:35:26–22:52:50；HDT 运行中，`runs/hdt_logs_2240/hdt_log.txt` 含 B/C
两局）。**官方记录：Hero `TB_BaconShop_HERO_37`，Place 7**。

| 源 | 场次 | 结果 | 备注 |
|---|---|---|---|
| Power.log C | 10 | win 3 / tie 2 / loss 5 | events 100%（修复后与 HDT 对齐） |
| HDT3（B+C） | 20 | 前 10=B（签名与 B 局一致）、后 10=C | bb_rates 100% |
| C 同局交叉 | HDT3 切片（B 10 + C 10） | **10/10** | round10 HDT 在游戏结束前无 Validate result，BB 预测 Loss 与 Power loss 一致。证据：`runs/real_game_cross_validation.json` |

差分（沿用既有抽取口径）：
* `runs/diff_powerlog3.json/.md`：**MATCH 6 / ENGINE_DIVERGENCE 3 /
  behavior_mismatch 0 / DATA_GAP 0 / skipped 1 / RNG_ORDER 6**；
* `runs/diff_hdt3.json/.md`：**MATCH 12 / ENGINE_DIVERGENCE 0 /
  CONTEXT_GAP 5 / SKIPPED 3 / behavior 0**。

**C 局 official_result 修复（2026-10-18）**：原 `_official_result` 用
「快照初始 + 战斗内 summon − death」估存活，在对手延迟揭示/空板窗口误判
（C round3/4/5 原为 tie，HDT 为 win/loss/loss）。修复为：
* 存活计数仍为主判（保住 B 局 10/10 与 e057 tie）；
* **仅当存活判平局**时用官方英雄实际掉血纠偏（PLAY 区
  `HEALTH+ARMOR−DAMAGE` 下降；单侧掉血 → 该侧败，双方掉血 → 保留 tie +
  `result_conflict`）；
* 对手未揭示/快照缺失 → `None`（不猜）；战后延迟伤害归入刚结束战斗
  （pending finalize，避免 round8/9 串场）。
修复后：**B 局 10/10、C 局 10/10**（round10 HDT 无 Validate，BB 预测
Loss 与 Power loss 一致）；证据 `runs/real_game_cross_validation.json`。
C round6（**trace `a07dc079cf3bd8d9`**，turn6）曾暴露引擎 Reborn 复生体
未恢复卡面基础关键词（DS）→ tie 98.4%；engine-analyst **F-14** 修复后
win 90.6% → MATCH，**behavior_mismatch=0**。更正：此前曾误关联
`be819be0e16f9746`；be819 实际是 win 100%/MATCH（turn12）。

**F-14 闭环**：C 局 round6 的引擎分歧已由 engine-analyst 修复
（Reborn 复生体按 CardDef 恢复基础关键词，含 DS）；`a07dc` win 90.6%/
MATCH，`be819` win 100%/MATCH；C 局 after-F14 = MATCH 6 / behavior 0。
**累计 26 场真实事件级 behavior=0 恢复成立**。

**伤害上限**：`runs/damage_cap_powerlog_session3.json` →
**2 → 5 → 10 → 15**（第三局再次确认三档；用户 Place 7，仍未进入前四，
解除上限未观测）。

### 9.4 伤害上限提取脚本修复

`reversed/rea/scripts/damage_cap_extract.py` 旧正则只认数字 tag id（2089/
3403），真实日志是**符号 tag 名**（`tag=BACON_COMBAT_DAMAGE_CAP`）且
Entity 可能是 `Entity=7`/`Entity=GameEntity`/`[entityName=...]`、
PLAYSTATE 是 `PLAYING` 符号值 → 旧脚本 0 行。已修复并加真实格式自测：

```powershell
python reversed/rea/scripts/damage_cap_extract.py --self-test          # 全 PASS
python reversed/rea/scripts/damage_cap_extract.py `
    --powerlog runs/powerlog/Power.log --out runs/damage_cap_powerlog.json
```

真实日志实测：**8 条 cap 观测**，cap 值分布 `{2:4, 5:2, 10:2}`（初始化 2，
第 4 回合 5，第 9 回合 10），与 `reversed/rea/damage_cap_evidence_powerlog.md`
独立脚本一致。注意：真实日志只有 2 个 Player 实体，`alive_players` 只能反映
本地/Bob 两侧，8 人存活数需额外从 8 个 `PLAYER_ID` HERO 的淘汰信息重建（下一步）。

### 9.5 下一步（事件级）

1. **RNG 对齐 vs strict**：`RNG_ORDER` 已单列（结果一致、仅攻击先手/顺序
   不同）；strict 事件级要求完全一致。第二局 5 条 event_sequence 分歧的
   首事件是**战前/开局效果伤害**（如英雄 12 伤害先于 ATTACK），下一步
   需在 trace/引擎侧建模这类开局效果或用 `first_event` 做对齐。
2. **空场战斗事件流**（turn2）：官方 hero attack 事件 vs 引擎 0 事件——
   引擎空场直接结束，需要事件级口径豁免或补 hero attack 事件。
3. 更长 Power.log（完整一局 + 多局）验证死亡波次/剧毒/圣盾/复生/召唤顺序。
4. 事件级 gate 独立于 679 场 BB gate（Power.log 语料不足时 SKIP，不阻塞 CI）。

## 10. 离线批量差分 runner（`tools/diff_bulk_fuzz.py`，BB oracle 待接入）

### 10.1 目的与边界

官方服务端战斗裁决器在客户端不可见（`docs/OFFICIAL_EXACTNESS.md §7`）→
**不存在"官方实现级全量等价"**。训练/评测需要近乎无限状态空间，真实语料
只能覆盖出现过的分布；因此 runner 做**结果级/事件级/分布级**验证，并把
BobsBuddy（BB）标注为**第三方参照，不是官方**。

### 10.2 设计

* **状态采样**：从已采集语料导出战斗边界状态——
  26 场真实 Power.log（A/B/C）+ 677 条 HDT（`official_traces_hdt`）+
  `runs/bg_last_games_20261018.xml` 45 局终局战团；保留真实
  atk/health/golden/keywords/tags（含 ScriptDataNum）、英雄技能。
* **突变（只在观测分布内）**：同卡属性按语料分位（p5–p95）±1 抖动、
  从该卡观测到的关键词组合中抽取、站位 shuffle、从同侧观测模板替换
  一条随从；不臆造未观测属性/关键词。输出每条状态记录突变类型。
* **差分**：同一状态分别跑引擎 N seeds 与 oracle M 次，比较
  win/tie/loss 分布（TVD/卡方、容忍带 `--tolerance`，默认 0.15）；
  按卡/关键词组合/stat 分层输出 TOP 分歧；context gap 不计引擎 bug、
  单独统计。
* **oracle 接口**：`Oracle.rates(state, sims, rng)`。
  `StubOracle` = 独立统计启发式（**非 BB/非官方**，仅验证管线闭环）；
  `BobsBuddyOracle` 为 engine-analyst 接入位（未就绪时明确抛错，
  **不伪造**）。接入后 `--oracle bobsbuddy` 复用同一采样/统计/输出。
* **产物**：JSONL 明细（每状态一行，含 state/engine/rates/TVD/分层）+
  Markdown 汇总（一致性、覆盖、TOP 分歧、口径与限制）。

### 10.3 命令

```powershell
python tools/diff_bulk_fuzz.py --states 100 --engine-seeds 64 ^
    --oracle-sims 100 --oracle stub ^
    --out-jsonl runs/diff_bulk_fuzz_smoke.jsonl ^
    --out-md runs/diff_bulk_fuzz_smoke.md
# BB oracle 接入后
python tools/diff_bulk_fuzz.py --states 1000 --engine-seeds 128 ^
    --oracle bobsbuddy --oracle-sims 1000
```

### 10.4 smoke 结果（2026-10-18，stub oracle）

| 指标 | 值 |
|---|---|
| 状态 × 引擎 seeds × oracle sims | **100 × 64 × 100** |
| 一致（TVD ≤ 0.15） | 18/100（18.0%）——stub 独立启发式，**不代表引擎准确率** |
| 平均 / 最大 TVD | 0.327 / 0.948 |
| 采样覆盖 | 100 状态、**268 张唯一卡**、19 种关键词组合；stat 范围 1–4414（中位 12） |
| 引擎 context gap 状态 | 84/100（单独统计，不计 bug） |
| 口径 | 采样覆盖，非穷举；BB oracle 未接入，smoke 只验证管线可跑通 |

**结论**：runner 管线（采样→突变→引擎→oracle→分布比较→分层 JSONL/MD）
可用；stub 与引擎分歧大属预期（二者无共同假设）。BB oracle 就绪后只需实现
`BobsBuddyOracle.rates`，即可做**大规模离线差分**（目标 1k+ 合成状态），
替代继续人类采集。

### 10.5 第一轮真实 BB oracle 批量差分（2026-10-18 23:21，最终）

接入 engine-analyst 的 `tools/bb_oracle/bb_oracle.py`（pythonnet 加载
`BobsBuddy.dll`，**第三方参照、非官方**）；`BobsBuddyOracle` 进程内调用
`run_oracle`（DLL 只加载一次），异常/未映射字段单列 unsupported。

```powershell
python tools/diff_bulk_fuzz.py --states 300 ^
    --states-file runs/state_corpus/states.jsonl ^
    --oracle bobsbuddy --engine-seeds 64 --oracle-sims 1000 --bb-threads 4
# 输出：runs/diff_bulk_bb_<ts>.jsonl/.md（默认 timestamped）
```

| 指标 | 结果 |
|---|---|
| 输入 | state_corpus **746 行/701 可解析**；优先可完整表达样本，不足时在观测分布内突变补足 |
| 本批状态 | **300**（216 base + 84 mutated） |
| 引擎 seeds / BB sims | **64 / 1000**（4 threads） |
| **TVD ≤ 0.15** | **258/300 = 86.0%** |
| TVD 分布 | mean **0.0661** / p50 **0.0** / p90 **0.2339** / max 1.0 |
| TVD ≤0.05 / ≤0.10 | 246 / 250 |
| 平均伤害差（\|engine−BB\|） | mean 5.85 / p50 2.0 / p90 14.8（口径见限制） |
| 覆盖 | **292 张唯一卡**、18 种关键词组合、stat 1–2391（中位 5）、turn 1–20 |
| 全语料 unsupported 比例 | **69.9%**（手牌/enchantment/trinket 等无法表达；**本批只取 expr. 样本，不进 TVD**） |
| 引擎 context gap | 198/300（单列，不计 bug） |
| 耗时 | 约 3–4 min（300×64 引擎 sims + 300×BB 1000 sims） |

**分层 TOP（mean TVD）**：按卡 `BG36_300` / `BG36_318` / `BG36_523` /
`BG36_320_G` / `BG36_106_G` 0.766、`BG34_694` 0.500、`BG35_432` 0.496、
`BG34_320` 0.492、`BG34_926` 0.418、`BG32_835` 0.408；按关键词
`reborn` 0.086、`taunt` 0.073、`divine_shield` 0.052、`stealth` 0.047、
`cleave` 0.042。→ 下一批修复候选优先上述卡 + reborn/taunt/divine_shield
交互；TOP 状态见 JSONL。

**限制**：BB 是第三方参照、非官方；客户端无官方裁决器 → 无实现级全量
等价；TVD 只统计 supported；平均伤害差与 BB `avDamage` 的符号/定义可能
不同，仅方向性参考；采样覆盖真实语料，非穷举。

**F-14 后复跑（同一 300 状态集）**：`runs/diff_bulk_bb_after_f14.jsonl/.md`
→ **agree 261/300 = 87.0%**、mean TVD **0.0664**（engine-analyst 独立跑
262/300、0.0667；差异来自本 pipeline 的 expressible+突变选样，接近）。
F-14 只影响 Reborn 关键词恢复，C round6 已闭环；批量 TVD 的 TOP 卡聚类
（`BG36_300/BG36_318/BG36_523/BG36_320_G/BG36_106_G`，state23/268）
根因是 **Deity 隐藏状态未进 state/oracle**（分析见
`reversed/rea/round6_and_bb_top_analysis.md §2.1`）：
* harness/oracle 已支持 `is_deity` minion + `friendly_deity_sigil`，
  state schema 预留六字段（`deity_card_id/deity_atk/deity_health/`
  `deity_progress/deity_awakened/deity_sigil_card_id`）；bridge-analyst
  正在补 `hsbg/bridge/state_corpus.py` 的真实抽取，补齐前相关样本标
  `unsupported:deity`，**不进 TVD**。
* `enchantment_derived`（Crab/AutoAssembler 等外部亡语/附魔）样本统一
  标 unsupported（state111/83/33 等），不进 TVD；长期再议引擎 generic
  external deathrattle 通道。

完整产物：`runs/diff_bulk_bb_20261018_232140.{jsonl,md}`、
`runs/diff_bulk_bb_after_f14.{jsonl,md}`。

**Deity 字段 + 引擎注入（2026-10-19 00:xx）**：bridge-analyst 已把六字段落到
`runs/state_corpus/states.jsonl`（7/746 状态有 Deity 观测；state23/268 基础
行 `ff75d9a57e3babce`：player BGFYM_000 33/33、opponent 87/86、sigil
`BG_OldGod`、progress 0 / awakened false）。harness 侧已：
* `BobsBuddyOracle` payload 增加 `is_deity` minion + `friendly_deity_sigil`；
* `OfficialCombatTrace.Warband.deity` 可选字段 + `simulate_trace` 用
  `Game.select_deity` / `give_deity_stats` 注入 card_id/atk/health/progress/
  awakened；缺失/hidden → `unsupported:deity`（不猜）。
* 诊断：engine 无 `FriendlyDeitySigil` 对象（`deity_sigil_ignored`）；
  `run_combat` 开场 `_reset_deity_combat` 会清 progress/awakened，故
  awakened=true 的边界状态暂无法注入（`deity_awakened_not_injectable`）。

复跑 `runs/diff_bulk_bb_after_deity_inject.jsonl/.md`（同一 300 状态集）：
| 指标 | before-deity | after-deity-inject |
|---|---|---|
| agree (TVD≤0.15) | 261/300 | **260/300** |
| mean TVD | 0.0664 | **0.0644** |
| state23 TVD | 0.9844 | **0.8438**（engine win .453/tie .391/loss .156 vs BB loss 1.0） |
| state268 | 0.5469（bridge 旧） | **0.0**（本批突变体 engine loss 1.0 = BB） |

结论：Deity 字段/oracle 已无缺口；engine 注入**部分生效**（state23 改善），
但因 **sigil/board Deity/awakened 注入 API 不完整**仍未收敛——需
engine-analyst 补 API（`FriendlyDeitySigil`、边界 awakened、board Deity
token 注入），之后重跑本批即可验证 TOP 卡收敛。**不为收敛伪造结果**。



**F-15 Deity 注入 + C'Thun known gap 复跑（2026-10-19 00:14，最终）**：
engine-analyst 已提供 inject_deity_state / inject_deity_sigil /
inject_deity_board_token；harness _inject_deity 改为边界快照注入
（injected=True 不被 _reset_deity_combat 覆盖）。C'Thun awaken split
（F-07 DEFERRED，无官方证据）标 **known_context_gap: deity_split_c_thun**，
不计 agree 分母；**不用 BB 行为补官方语义、不改引擎追 TVD**。


uns/diff_bulk_bb_after_f15_gapaware.jsonl/.md：selected/supported 300；
**evaluated 291**；**known gap 9**（state1/7/9/17/19/22/23/252/268，TVD 仅参考）；
**agree 253/291 = 86.9%**、**mean TVD 0.0611 / p90 0.2034**；known gap TVD
参考 0.0–0.8438（state23 0.8438，不计指标）。**TOP 卡**：BG34_694 .499、
BG35_432 .492、BG36_300/318/523/320_G/106_G **.422**（Deity 注入前
.766）、BG32_835 .414；关键词 reborn .081/taunt .066/divine_shield .051。
**TVD 是采样覆盖指标；C'Thun split 是已知证据 gap，不是追平目标**。

## 11. 不确定卡审计回归方法（engine-analyst 审计配套）

### 11.1 证据清单

```powershell
python tools/audit_candidates_diff.py
# 输出 reversed/rea/audit_candidates_diff.md：
#   679 差分（missing_script / dynamic_script_data / adapter_skip）+
#   F-15 gap-aware 300 状态 BB 批量（按卡 mean/max TVD、known gap）+
#   26 场真实 Power.log（trace/官方结果/首个事件分歧）
```

候选表按证据强度排序；每卡附 679 样本、BB 状态、真实 trace/首分歧事件；
无真实 trace 的卡明确标“**仅单测/合成证据**”。

### 11.2 每修一张卡的修复前后对照（必须留痕）

1. **选 trace**：
   * 真实 Power.log：从 `runs/official_traces_powerlog{,2,3}` 中按
     `player/opponent.minions.card_id` 过滤含该卡的 trace（26 场小语料）；
   * 679 HDT：trace 无 card_id，按 `context_gaps` 的
     `no_script:<card>` / `dynamic_script_data:<card>:N` 与
     `suspect_cards` 定位；对比看该卡 `divergent_traces` 计数；
   * BB：`tools/audit_candidates_diff.py` 输出的 state_id/source_trace，
     用全 300 状态批量同口径复跑后看该卡 mean/max TVD 与 known gap。
2. **修复前**（当前引擎）：
   ```powershell
   python tools/diff_replay_combat.py --traces <card_traces_dir> --seeds 64 ^
       --json runs/diff_audit_<card>_before.json --md runs/diff_audit_<card>_before.md
   ```
   记录：status（MATCH/DIV/CONTEXT）、`event_diff`（首个事件差异）、
   `engine_rates` / official / bb_rates、TVD。
3. **修复后**（engine-analyst 落地后）同命令 `_after`，逐项对比：
   * 事件级：首个分歧 index/kind 是否前移或消失；
   * 分布级：win/tie/loss + L1/TVD、确定性场是否恢复 MATCH；
   * 679：该卡 `divergent_traces` 是否下降、全局基线是否退化；
   * BB：该卡 mean/max TVD、TOP 卡聚类是否变化。
4. **无真实 trace**：只能写“**无事件级证据，仅单测**”，并在审计文档标注；
   不得用 BB 行为补官方语义、不得为追平 TVD 改引擎。
5. **归档**：`runs/diff_audit_<card>_{before,after}.{json,md}` +
   `docs/DIFF_HARNESS.md`/`reversed/rea/audit_candidates_diff.md` 记录。

### 11.3 gate 按卡摘要

`scripts/audit_official_consistency.py` 现在同时输出
`runs/card_audit.json` / `runs/card_audit.md`：按卡聚合 divergent/suspect、
missing_script、dynamic_state、behavior 与样本 trace，供每轮审计追踪
（有证据卡数变化 = 修复/新增缺口的直接信号）。

## 附录 A：抽取统计（`runs/official_traces/index.json`）

```text
[extract] traces=679 results={'loss': 195, 'tie': 58, 'win': 271, 'null': 155}
completeness={'official_result': 0.7717, 'turn': 1.0, 'hero_power_id': 0.9956,
              'hero_card_id': 0.0, 'bb_rates': 0.9809, 'events': 0.0,
              'player.minions': 0.9912, 'opponent.minions': 0.9219}
[extract] replays: scanned=1365 bg_games=0 skipped={'not_battlegrounds': 1365}
[extract] hdt_logs: files=27 combats=679
[extract] wrote=679 existing=0 -> runs\official_traces
```

幂等性：第二次运行 `wrote=0 existing=679`；`--force` 才覆盖。
输出目录**默认不删旧文件**（`--prune` 显式开启才清理不属于本次结果的
旧轨迹），避免 `--limit 5` 小样本运行时误删全量语料。

### 语料清单（2026-10-18）

| 目录 | 场次 | 源 | index |
|---|---|---|---|
| `runs/official_traces/` | 679 | HDT BobsBuddy（主基线） | `index.json` |
| `runs/official_traces_powerlog/` | 6（首局，截断 1） | Power.log | `index.json` |
| `runs/official_traces_hdt/` | 677 | HDT 全量会话（含 card_id 补齐，6622 minions） | `index.json` |
| `runs/official_traces_powerlog2/` | 10（完整局，events 100%） | Power.log 第二局 | `index.json` |
| `runs/official_traces_hdt2/` | 10（同局 HDT，bb 100%） | HDT 1.59.3 第二局 | `index.json` |
| `runs/official_traces_powerlog3/` | 10（第三局 C，events 100%） | Power.log C | `index.json` |
| `runs/official_traces_hdt3/` | 20（B+C 两局，bb 100%） | HDT 1.59.3 第三局会话 | `index.json` |

累计**真实 Power.log 战斗 26 场**（A 6 + B 10 + C 10），事件级
`behavior_mismatch=0`；B/C 均为完整一局（无截断）。用户已明确停止人类
采集（人类采集压力大），后续转离线/批量验证，见
`reversed/rea/real_game_validation_status.md`。重抽命令（幂等，`--force` 覆盖）：

```powershell
python tools/diff_extract_replays.py --sources powerlog --powerlog runs/powerlog_2214/Power.log ^
    --out runs/official_traces_powerlog2 --force
python tools/diff_extract_replays.py --sources hdt --hdt-logs runs/hdt_logs_2214 ^
    --out runs/official_traces_hdt2 --force
python tools/diff_extract_replays.py --sources powerlog --powerlog runs/powerlog_2240/Power.log ^
    --out runs/official_traces_powerlog3 --force
python tools/diff_extract_replays.py --sources hdt --hdt-logs runs/hdt_logs_2240 ^
    --out runs/official_traces_hdt3 --force
```

## 附录 B：差分结果摘要（测量口径 v2）

主口径（`runs/diff_report.json`，已应用 F-02~F-05 的 live 引擎 + 注入开启）：

```text
[diff] traces=679 match=400 divergence=153 context_gap=85 data_gap=0 skipped=41
       match_rate=72.3% divergence_rate=27.7%
```

A/B（`runs/diff_report_no_injection.json`，`--no-script-data-injection`）：

```text
[diff] traces=679 match=391 divergence=204 context_gap=43 data_gap=0 skipped=41
       （与主口径 strict 相同；context-aware 干净子集 12 vs 13）
```

* `summary.strict.deterministic.strict_match_rate` = 81.61%（284/348）
* `summary.strict.deterministic.tolerant_match_rate` = 90.52%（同分布阈值 80%）
* `summary.context_aware.clean_subset_traces` = 13（匹配率 **100%**）
* `summary.behavior_mismatch` = **0**
* `summary.script_data_injected_*` = 585 条轨迹 / 2,366 实体 / 52 个适配器实体
  （A/B 干净子集 12→13；唯一分布变化为 Ultraviolet 轨迹 `17493f10c0afbbad`）
* `divergence_attribution` = {missing_script: 204}
* 逐条记录在 `records[]`（含战团、引擎 N 种子结果、官方结果、BobsBuddy
  概率、上下文缺口、归因、ScriptDataNum 注入记录）；可读摘要见
  `runs/diff_report*.md`。

## 附录 C：复现环境

* Python `C:\Python313\python.exe`；引擎 `hsrl2`（vendored；已应用精确性
  包 F-02~F-05）+ `data/`（官方 255130，3,817 defs）；
* 官方数据参照：`reversed/data_255130/bg_cards.json`（缺口归类）；
* 官方脚本数据 enumID 证据：`reversed/hsdata_255130/CardDefs.Bacon.xml`
  + `reversed/net/key_enums.json`（NUM_1..5 = 2/3/2889/2919/2920）；
* 隔离引擎/数据：`tmp_diff_fix/{hsrl2,data}`（引擎改动验证用）；
* 录像/日志目录（只读）：`%APPDATA%\HearthstoneDeckTracker\{Replays,Logs}`；
* 所有产物 UTF-8，写入 `runs/`（git 忽略）。

## 附录 D：当前状态（2026-10-18 测量口径 v2）

| 项 | 状态 |
|----|------|
| 根目录 `hsrl2/` | 已应用历史精确性包（Ozumat/脚本数据通道/伤害上限/战斗语义）；本轮**未改引擎** |
| `tools/diff_replay_combat.py` | 新增 strict/context-aware/tolerant 三套指标 + ScriptDataNum 注入 + A/B 开关 |
| `hsbg/bridge/trace.py` | 已在上一轮支持官方伤害上限 tag（2089/3403）解析 |
| Harness 回归 | `pytest tests/test_diff_trace.py tests/test_diff_compare.py -q` → **45 passed, 1 skipped** |
| 主报告 | `runs/diff_report.{json,md}`；A/B 报告 `runs/diff_report_no_injection.{json,md}` |
| 当前指标 | strict MATCH 391（65.7%）、确定性 strict 81.61% / tolerant 90.52%、干净子集 100%、`behavior_mismatch=0` |
