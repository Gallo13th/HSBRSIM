# 标准动作空间（ACTION_SPACE_STD）：AutoTavern 245 + 扩展段

> 状态：**P2 标准 profile（新增）**；旧 ``hsbg.env.spec.CandidateAction`` 动态候选
> 接口保留为 **legacy profile**。二者关系与迁移见 §7/§8。
> 代码：`hsbg/env/action_space_std.py`；测试：`tests/test_action_space_std.py`
> （42 项，金标对照上游 `taverngym` + 真实环境候选转换）。
> 上游参照：AutoTavern TavernGym 1.0.0 / 游戏数据 36.6.3.253932
> （`crates/taverngym/src/actions.rs`，GitHub: MCG-NJU/AutoTavern）。
> 实测环境：macOS Apple Silicon / Python 3.12.2 / taverngym 1.0.0
> （`N_ACTIONS=245, OBS_FLOATS=3227, OBS_CARDS=124, N_CARDS=3984`）。

---

## 1. 目标与可比性契约

HSBRSIM 标准动作 profile **直接采用** AutoTavern（AT）TavernGym 的固定 245 维
动作空间：**前 245 项的索引、语义、`action_name` 与上游逐位一致**。

**可比性契约（强条件）**

1. 对任意 ``i ∈ [0, 245)``：``hsbg.env.action_space_std.action_name(i)``
   **逐字等于** ``taverngym.action_name(i)``（金标测试覆盖全部 245 项）；
2. 15 个动作常量 + 6 个规模常量与 ``taverngym.layout()`` 对应项数值相等；
3. 同一动作索引在两边含义相同 ⇒ 同一数据版本下，AT 轨迹里的动作可被
   HSBRSIM 直接复用（反之亦然），可用于跨引擎对拍/行为克隆数据迁移；
4. 扩展段（≥245）**不改变**前 245 项任何语义/索引；AT 侧没有扩展段，
   跨引擎对比时只看 ``[0, 245)``，扩展动作只在 HSBRSIM profile 内使用。

**为什么固定 245？**（相对 legacy 动态候选）

* 固定动作空间 + 精确 mask 是 AT 的 RL 接口形态（245 维 bool mask，见
  [`docs/TAVERNGYM_BACKEND.md`](TAVERNGYM_BACKEND.md) §5）；统一后策略头、
  mask、跨引擎对拍、AT 预训练权重迁移都不再需要"候选列表"这一层；
* legacy 候选与 ``spec.CANDIDATE_MAX=64`` 绑定，天然无法表达"长时间不刷新、
  满手牌/满场"的全部合法动作；245 维空间覆盖 AT 引擎的全部动作槽位。

> 注意：AT 动作空间本身**不是**"全部游戏操作"——它也没有解冻（见 §4）。
> "游戏支持但两引擎动作空间都没实现"的操作放在扩展段，而不是改前 245 项。

---

## 2. 常量表（与 `taverngym.layout()` 逐项一致）

| 常量 | 值 | 含义 |
|---|---:|---|
| `A_END` | 0 | 结束招募阶段 |
| `A_REFRESH` | 1 | 刷新酒馆 |
| `A_FREEZE` | 2 | 冻结酒馆 |
| `A_UPGRADE` | 3 | 升级酒馆 |
| `A_HERO_POWER` | 4 | 英雄技能段起点 |
| `N_POWERS` | 2 | 英雄技能槽数（主槽 + 1 副槽） |
| `A_DARK_GIFT` | 6 | 黑暗赠礼 |
| `A_CANCEL` | 7 | 取消目标选择 |
| `A_BUY` | 8 | 购买段起点（`N_SHOP=8` 槽） |
| `N_SHOP` | 8 | 酒馆槽位数 |
| `A_SELL` | 16 | 出售段起点 |
| `A_ACTIVATE` | 23 | Activate 段起点 |
| `A_CHOOSE` | 30 | 选择段起点（`N_CHOICE=16` 选项） |
| `N_CHOICE` | 16 | 选择选项数 |
| `A_PLAY` | 46 | 打出段起点（`N_HAND=10` × `N_POS=8`） |
| `N_POS` | 8 | 棋盘插入位置数（0..7；`pos==场上随从数` = 追加） |
| `N_HAND` | 10 | 手牌槽位上限 |
| `A_MAGNETIZE` | 126 | 磁力吸附段起点（10 × 7） |
| `N_BOARD` | 7 | 棋盘槽位上限 |
| `A_MOVE` | 196 | 棋盘重排段起点（7 × 7） |
| `N_ACTIONS` / `N_STD_ACTIONS` | 245 | 标准动作总数（= AT `N_ACTIONS`） |

派生关系（模块导入期自检，见 `_validate_constants()` / `validate_layout()`）：

```
A_DARK_GIFT = A_HERO_POWER + N_POWERS = 6
A_CANCEL    = A_DARK_GIFT + 1 = 7
A_BUY       = A_CANCEL + 1 = 8
A_SELL      = A_BUY + N_SHOP = 16
A_ACTIVATE  = A_SELL + N_BOARD = 23
A_CHOOSE    = A_ACTIVATE + N_BOARD = 30
A_PLAY      = A_CHOOSE + N_CHOICE = 46
A_MAGNETIZE = A_PLAY + N_HAND * N_POS = 126
A_MOVE      = A_MAGNETIZE + N_HAND * N_BOARD = 196
N_ACTIONS   = A_MOVE + N_BOARD * N_BOARD = 245
```

---

## 3. 逐段动作表

`action_space_std.SEGMENTS` 是唯一权威分段表（`(name, lo, hi, count, desc)`，
`hi` 为开区间；导入期校验连续覆盖 `0..N_TOTAL_ACTIONS-1`）。

| 索引区间 | 数量 | 动作对象 | 参数 | 语义 | legacy 映射 |
|---|---:|---|---|---|---|
| 0 | 1 | `EndTurn()` | — | 结束招募 → 战斗 | `kind=end_turn` |
| 1 | 1 | `Refresh()` | — | 刷新酒馆 | `kind=reroll` |
| 2 | 1 | `Freeze()` | — | 冻结酒馆 | `kind=freeze` |
| 3 | 1 | `Upgrade()` | — | 升级酒馆 | `kind=upgrade` |
| 4..5 | 2 | `HeroPower(slot)` | `slot∈0..1` | 使用英雄技能槽 | `kind=hero_power`（槽位丢失） |
| 6 | 1 | `DarkGift()` | — | 黑暗赠礼 | `kind=use_dark_gift` |
| 7 | 1 | `Cancel()` | — | 取消目标选择 | legacy 无对应 kind（扩展 `"cancel"`） |
| 8..15 | 8 | `Buy(slot)` | `slot∈0..7` | 购买酒馆槽 `slot` | `kind=buy, src_zone=tavern, src_slot=slot` |
| 16..22 | 7 | `Sell(slot)` | `slot∈0..6` | 出售棋盘槽 `slot` | `kind=sell, src_zone=board` |
| 23..29 | 7 | `Activate(slot)` | `slot∈0..6` | Activate 技能 | `kind=activate, src_zone=board` |
| 30..45 | 16 | `Choose(option)` | `option∈0..15` | 结算待选项 | `kind=choose, option` |
| 46..125 | 80 | `Play{hand,pos}` | `hand∈0..9, pos∈0..7` | 从手牌打出（随从/法术统一） | `kind=play_minion/play_spell` + 位置 |
| 126..195 | 70 | `Magnetize{hand,board}` | `hand∈0..9, board∈0..6` | 磁力吸附 | `kind=play_minion` + `tgt_zone=board, position=-1` |
| 196..244 | 49 | `Move{from,to}` | `from,to∈0..6` | 棋盘重排 | `kind=move_minion, position=to` |
| **245** | 1 | `Unfreeze()` | — | **扩展**：解冻整馆 | 扩展 `kind="unfreeze"` |
| 246..249 | 4 | `HeroPower(slot)` | `slot∈2..5` | **扩展预留**：备用技能槽 | 扩展 `src_slot=slot` |
| 250..265 | 16 | `Choose(option)` | `option∈16..31` | **扩展预留**：更多选择槽位 | 同 `choose` |
| 266..273 | 8 | `FreezeSlot(slot)` | `slot∈0..7` | **扩展**：按槽位冻结/解冻酒馆展示位（toggle；8 槽 = 7 随从 + 1 酒馆法术槽） | 扩展 `kind="freeze_slot"`（`src_zone=tavern, src_slot=slot`） |

**编码公式**（与上游 `Action::encode` 逐位一致）：

```
EndTurn=0, Refresh=1, Freeze=2, Upgrade=3
HeroPower(s)     = 4 + s
DarkGift=6, Cancel=7
Buy(s)           = 8 + s
Sell(s)          = 16 + s
Activate(s)      = 23 + s
Choose(o)        = 30 + o
Play{h,p}        = 46 + h*8 + p
Magnetize{h,b}   = 126 + h*7 + b
Move{f,t}        = 196 + f*7 + t
# 扩展段
Unfreeze         = 245
HeroPower(s>=2)  = 246 + (s-2)      # s∈2..5
Choose(o>=16)    = 250 + (o-16)     # o∈16..31
FreezeSlot(i)    = 266 + i          # i∈0..7（toggle 单槽冻结）
```

**`action_name` 格式**：与上游 Rust `format!("{x:?}")` 逐字一致，例如
`"EndTurn"`、`"HeroPower(0)"`、`"Buy(3)"`、`"Cancel"`、
`"Play { hand: 2, pos: 3 }"`、`"Magnetize { hand: 1, board: 4 }"`、
`"Move { from: 0, to: 5 }"`。金标测试对 0..244 全量比对。

`SEGMENTS` 之外还提供：`decode(index) -> StdAction`（严格校验，越界抛
`ValueError`/`TypeError`）、`encode(action) -> int`（字段越界抛
`ValueError`）、`is_std_index()` / `is_extension_index()` / `segment_of()`。

---

## 4. 扩展动作段（索引 ≥ 245）

规则：**只能追加在 `N_TOTAL_ACTIONS` 之后**（禁止插入/重排/改前 245 项）；
扩展段不参与与 AT 的逐位对比；环境层若尚未实现某扩展动作，该索引置 False
（mask 永不为真）。

**与 P2-C 操作探针结论一致（2026-10-26）**：`runs/p2_delta/ops_probe.json`
17 项核对 `gap_summary.gaps = [OPS-02, OPS-09, OPS-11]`，本 profile 的处置：

| OPS | 缺口 | 处置 |
|---|---|---|
| **OPS-02** | 单槽位冻结/解冻（游戏支持、两引擎均缺） | **本文件新增 `FreezeSlot(0..7)` = 266..273**（§4.4） |
| **OPS-09** | 第 3+ 英雄技能槽（AT 引擎支持、动作空间只到 2 槽） | 预留 `HeroPower(2..5)` = 246..249（§4.2） |
| **OPS-11** | 异变系统/异变选择（HSBRSIM 有、AT 无） | **不新增动作**（配置注入/系统层，P3） |

其余核对项（整馆冻结 OPS-01、酒馆展示位 8 OPS-03、选择选项 OPS-04 等）已覆盖或
由 std 观测迁移处置（见 `docs/PORTING_37_PLAN.md` §6）。

### 4.1 `Unfreeze`（索引 245）——整馆解冻（单向显式动作）

* 真实游戏：冻结是**可点掉**的（再次点击整馆冻结按钮即解冻）；
* AT：`actions.rs` 只有 `Freeze`，但**语义是整馆 toggle**（`recruit.rs:2115-2125`
  `set_frozen(!all)`：未全冻 → 冻结全部，已全冻 → 解冻全部；P2-C §6.4 澄清
  "AT 只有 Freeze 无 Unfreeze"是误读）。因此整馆解冻在 AT 侧**语义上已被
  Freeze 覆盖**；
* HSBRSIM 引擎：`hsrl2/game.py:2213 Game.unfreeze_tavern(hero) -> bool`
  （F-23 对称 API：清整馆 `FROZEN` tag、广播 `tavern_unfrozen`、不刷新不付费）；
* HSBRSIM 环境层：`hsbg/env/driver.py` 只生成单向 `freeze` 候选
  （`enumerate_actions` 注释：冻结/解冻免费且可无限切换，双向候选会让随机
  策略陷入 freeze 循环拖满 `max_steps`；ENV_SPEC 记录同一决定）；
* 结论：AT 标准动作没有**单向** Unfreeze 索引，HSBRSIM legacy 候选也只生成
  单向 freeze，但整馆解冻在游戏内合法 → std profile 拆成显式单向动作放入
  扩展段，索引 245，`action_name="Unfreeze"`（便于双向 mask）。
  环境层实现（P3）时：``hero.frozen_tavern`` 为真时 mask[245]=True，
  应用路径直接调用 `unfreeze_tavern`（不消耗金币/刷新）。

### 4.2 备用英雄技能槽（索引 246..249，`HeroPower(2..5)`，预留）

* AT：`N_POWERS=2`（`actions.rs:39` 注释"the hero's own and one extra
  (Genn, Reinvigorating Light...)"），即标准段只容纳主槽 + 1 副槽；
* HSBRSIM：`hsbg/env/driver.py:143 zones.power_ids = list(game.hero_power_ids(hero))`
  **是列表**，`_enumerate_hero_powers` 按 slot 逐项枚举（无硬编码上限），
  `docs/ENV_SPEC.md` 亦暴露 `extra["second_power_id"]`；
* 当前英雄池最多 2 个技能槽，但引擎结构不限制 3+；未来英雄/效果继续扩展
  （多技能槽）时，标准段 2 个槽位不够 → 预留 4 个扩展槽（2..5）。
* P3 若需要启用：环境层生成 `HeroPower(slot>=2)` 时 mask[246+(slot-2)]=True。

### 4.3 更多选择槽位（索引 250..265，`Choose(16..31)`，预留）

* AT：`N_CHOICE=16` 是引擎固定上限（发现/三选一/饰品/英雄技能选择等）；
* HSBRSIM：`hsbg/env/spec.py:35 CHOICE_OPTION_MAX=5`（env 当前选项更少），
  但 `PendingChoice.options` 是**任意长度 tuple**（引擎不限制），且
  `docs/ENV_SPEC.md` §2.1 的 `extra["pending_choice_options"]` 同样无上限；
* 若未来大选项池（大发现池/任务 offer 批量/饰品商店改版）超过 16 个选项，
  标准段放不下 → 预留 16 个扩展选择槽（16..31）。
* P3 若需要启用：`Choose(o>=16)` mask[250+(o-16)]=True。

### 4.4 `FreezeSlot(0..7)`（索引 266..273）——按槽位冻结/解冻（P2-C OPS-02）

**证据链**

1. **游戏语义**：酒馆里每张卡有**独立的单卡冻结状态与 UI 雪花**；整馆按钮与
   单卡按钮是两种操作；
2. **37.0.0 卡面**：`BG22_HERO_004p Twice as Nice` ——
   "After the Tavern is Refreshed, copy its highest-Tier minion and
   **Freeze them both**"；另有 `TB_BaconShop_HP_014 Stay Frosty`
   "Freezes at the end of each turn" 等效果指定单卡/指定目标冻结
   → 引擎必须能表达**按随从粒度**的冻结状态；
3. **AT 侧**：动作枚举只有整馆 `Freeze`；`recruit.rs:392 unfreeze_shop(sid)`
   仅内部工具（卡被替换时清标记），不是动作、也不广播事件；
4. **HSBRSIM 引擎**：公开动作 API 只有整馆 `freeze_tavern`/`unfreeze_tavern`
   （F-23），**没有**单槽位公开 API；但引擎内部冻结机制已存在：
   `hsrl2/game.py:623-630` 的刷新窗口会保留带**实体级 `FROZEN` tag** 的酒馆卡
   （"Freeze a minion" 类效果就是直接 set 该 tag），因此单卡冻结状态在引擎内
   可表达、只是没有动作入口；
5. **结论**：AT 与 HSBRSIM 的动作空间都没有它 → 扩展段 `FreezeSlot(slot)`
   = **toggle**（对第 slot 张酒馆卡切换单卡冻结），8 槽 = 7 随从 + 1 酒馆法术槽
   （与 `N_SHOP=8` 对齐）。

**与整馆 `Freeze(2)` / `Unfreeze(245)` 的区别**

| | `Freeze(2)` / `Unfreeze(245)` | `FreezeSlot(i)`(266..273) |
|---|---|---|
| 粒度 | 整馆（所有展示位一起） | 单个展示位（第 i 张） |
| 语义 | `Freeze` = 整馆 toggle（AT）；`Unfreeze` = 单向解冻 | 单卡 toggle（冻/解冻同一动作） |
| 掩码 | 整馆未冻/已冻 | 仅当 `i < 酒馆展示卡数` 时置位 |
| 状态载体 | `hero.frozen_tavern`（整馆 tag） | 单卡实体级 `FROZEN` tag |

**P3 环境接入说明（限制）**

* 两引擎都**没有**单槽位公开动作 API：
  * HSBRSIM：可在 env 层直接 toggle `hero.tavern[i]` 的实体级 `GameTag.FROZEN`
    （引擎刷新窗口已消费该 tag，`game.py:623-630`）——属"映射到现有机制"，
    需注明：触碰内部 tag、无事件广播、不受整馆 `freeze_presses` 预算约束；
  * 更稳做法：在引擎补原子 API（如 `freeze_shop_slot(hero, idx)` /
    `toggle_shop_slot_frozen`），由效果与动作共用并广播事件；
  * AT/Rust 主引擎：P2-C 建议 `recruit.rs` 加 `freeze_slot(p, idx)`
    （`players[p].shop[idx].frozen ^= true` + `can_freeze` 计数 + 事件，
    mask 仅 `idx < shop.len()` 置位）——Rust 侧属 P3/P2 内容移植工作；
* 在环境接入前：`FreezeSlot` 只有编码/解码/名称定义，mask 恒 False；
  解码出的动作**不得**直接喂给现有引擎动作 API（无对应入口）。

### 4.5 扩展段自检

* `N_EXT_ACTIONS = 1 + 4 + 16 + 8 = 29`；`N_TOTAL_ACTIONS = 274`；
* 扩展索引与标准索引**无交集**（`is_std_index` XOR `is_extension_index`）；
* 扩展动作的 `encode/decode` 与 `action_name` 已实现并测试（含全量
  `decode→encode` 恒等，0..273）。

---

## 5. 与 `CandidateAction`（legacy profile）的转换

```python
from hsbg.env import action_space_std as std

idx = std.candidate_to_std(candidate, context)          # CandidateAction → StdAction|None
candidate = std.std_to_candidate(idx, obs_or_context)   # 索引/StdAction → CandidateAction|None
seq = std.candidate_to_std_sequence(candidate, context) # → (Play, Choose) 等
```

`context` 可为 ``None``、``CandidateContext`` 或 ``hsbg.env.spec.Observation``
（鸭子类型：用 ``obs.board`` 的长度与 ``obs.hand[].card_type`` 自动填充）：

| 字段 | 默认 | 用途 |
|---|---|---|
| `board_size` | 0 | legacy `position=-1`（追加）→ `pos=board_size` |
| `hand_card_types` | `()` | `Play{hand,pos}` 反解成 `play_spell`（否则按 `play_minion`） |
| `hero_power_slot` | 0 | `hero_power` 候选 → `HeroPower(slot)`（legacy 候选不含槽位） |
| `target_option` | -1 | 定向动作 → `(Play, Choose(target_option))` |

### 5.1 语义差异（**不是**一一对应）

1. **目标选择**：AT 把"法术/战吼/技能目标"建模成 **Play/技能之后的
   `Choose` 决策步**；legacy 候选把目标**折叠**进
   `play_spell`/`play_minion`/`hero_power` 的 `tgt_zone/tgt_slot`。
   因此：
   * `candidate_to_std` 对定向候选只返回动作本体（目标丢失）；
   * `candidate_to_std_sequence` 在提供 `target_option` 时返回
     `(Play, Choose(target_option))`，还原 AT 的两步语义；
   * 反向 `std_to_candidate(Play)` 得到**无目标**的候选；
     若目标是战吼，P3 环境需要在 `Play` 后再暴露选择步。
2. **磁力吸附**：legacy 约定 `tgt_zone="board"` + `position=-1` 表示吸附
   （`driver._play_minion_variants` 的 magnetic 变体）；转成
   `Magnetize{hand,board}`。反向一致。
3. **`position=-1`（追加到最右）**：legacy 动态候选（`driver._position_variants`）
   用 `-1` 表示"最右/追加"，磁力吸附也用它；标准 ``Play.pos`` 是 0..7 的显式
   位置（``pos == 场上随从数`` = 追加）。`candidate_to_std` 用
   `context.board_size` 换算（缺上下文时保守取 0）。反向转换得到**显式**
   ``position=board_size``：与 `-1` 语义等价、签名不同（转换是一对多的投影，
   已由真实环境测试按语义断言）。
4. **英雄技能槽**：legacy `CandidateAction` 不含槽位（`ActionDescriptor.power_id`
   在 `to_candidate()` 时被丢弃），所以 `candidate→std` 需要
   `context.hero_power_slot`；`std→candidate` 主槽按 legacy 约定不带
   `src_zone/src_slot`，扩展槽带 `src_zone="power", src_slot=slot`
   （与 `hsbg/backends/taverngym_env.py` 的约定一致）。
5. **`Cancel`**：AT 标准动作（7），legacy `ActionKind` 无对应 → 用扩展
   kind `"cancel"`（`CandidateAction.kind` 允许任意字符串；`ACTION_KIND_INDEX`
   会落到 0，训练侧需单独处理，文档见 `docs/TAVERNGYM_BACKEND.md` §5 同类说明）。
   `FreezeSlot` 同理用扩展 kind `"freeze_slot"`（约定 `src_zone="tavern",
   src_slot=槽位`；`Unfreeze` 用 `"unfreeze"`）。
6. **`Freeze` vs `Unfreeze`**：标准段 2 是 AT 的"冻结按钮"（切换语义）；
   HSBRSIM legacy 只生成单向"未冻结 → 冻结"。解冻 = 扩展 245。
7. **非法输入**：`candidate_to_std` 对未知 kind/槽位越界返回 `None`（批量转换
   不抛异常）；`std_to_candidate` 对非法索引/字段返回 `None`；
   `decode()` 严格抛 `ValueError`/`TypeError`（金标测试用）。

### 5.2 覆盖范围自检

`tests/test_action_space_std.py::TestCandidateConversion` 覆盖全部 13 种 legacy
`ActionKind` + 扩展 `cancel/unfreeze` 的双向转换、往返守恒（非有损项）、
非法输入、Observation 上下文，并与 `hsbg/backends/taverngym_env.py` 的
245 维映射约定交叉比对。

---

## 6. 金标测试与复现

```bash
cd /Users/letiangao/HSAgent/HSBRSIM

# 标准动作空间金标（44 passed；需要 taverngym，未安装自动 skip）
python3 -m pytest tests/test_action_space_std.py -q

# 金标内容：
# 1) 0..244 action_name 与 taverngym.action_name(i) 完全相等（245/245）
# 2) 常量与 taverngym.layout() 逐项相等
# 3) decode→encode 全量恒等（0..273）
# 4) 扩展段/UNFREEZE/FreezeSlot/预留槽位/非法输入
# 5) CandidateAction 双向转换与语义差异（含 13 种 ActionKind 全覆盖）
# 6) 与 hsbg/backends/taverngym_env.py 映射约定交叉一致
# 7) 真实对局候选转换：全部可转标准动作；仅"目标被折叠/追加哨兵"有损（按语义断言）
```

本机实测（2026-10-26，macOS Apple Silicon / python3 3.12.2 / taverngym 1.0.0）：
`44 passed in 1.0s`；`action_name` 差异 **0/245**、`layout()` 差异 **0/32**、
`decode→encode` 274/274 恒等；与标准观测联跑 `57 passed in 1.23s`。

---

## 7. 迁移指南：旧 candidate profile → 标准 profile

旧 checkpoint / 旧数据一律视为 **legacy**（用户已确认接受重训）。

### 7.1 环境/数据侧

| 旧（legacy） | 新（std profile） |
|---|---|
| `Observation.candidates` 动态候选（≤64） | 245 维固定动作 + `bool[245]` 精确 mask |
| `env.action_mask()` 长度 = 候选数 | mask 恒为 245；`mask[i] = i in legal` |
| `CandidateAction.signature()` 作为动作键 | `StdAction` / 整数索引（0..244） |
| `candidate_to_std`/`std_to_candidate` 转换（本模块 §5） | 新旧共存期使用；新轨迹只用 std |
| 旧 ``Observation`` 实体 token 观测 | AT 观测 profile（`hsbg/env/obs_std.py`，3227+124） |

### 7.2 训练/策略侧

1. **策略头**：旧"候选打分 + masked argmax" → 固定 245 维 logits +
   masked softmax（`logits[~mask] = -inf`）；扩展段（245..273）默认 mask=False
   （环境未实现时），策略头可先输出 245 维、扩展段按需扩到 274；
2. **checkpoint**：旧 checkpoint（实体 token 观测 + 动态候选策略）与 std
   profile **不兼容** → 标记 legacy、不再用于评测/训练（重训）；
3. **数据**：旧 JSONL 轨迹的观测/动作用 §5 转换器可近似重放（有损项见 §5.1）；
   新采集一律落 std profile（Lead 的环境集成 PR 会切换观测/动作编码）；
4. **确定性**：std 动作索引是纯函数，无随机；同 seed + 同索引序列可复现
   （与 `docs/ENV_SPEC.md` 的确定性要求一致）。

### 7.3 跨引擎数据迁移

同一**数据版本**下（AT 36.6.3 或 HSBRSIM 37.0.0 各自对齐后）：
`action index` 可直接互认；卡 id/观测卡牌下标需按卡 id 重映射
（见 [`docs/OBS_STD.md`](OBS_STD.md) §8）。当前 AT=36.6.3 与 HSBRSIM=37.0.0
数据不同，**动作语义可比、状态分布不可比**（策略不能直接迁移，需重训；
详见 `docs/TAVERNGYM_BACKEND.md` §7）。

---

## 8. 已知限制 / 契约边界

1. **AT 版本固定**：本 profile 对应 taverngym 1.0.0 / 36.6.3.253932 的
   `N_ACTIONS=245`。上游若升版本改动作空间，必须同步本模块 + 文档 + 测试
   （`validate_layout()` 导入期会拦截派生关系错误，但外部版本漂移需金标测试）。
2. **扩展段尚无环境实现**：`Unfreeze`/备用槽位/`FreezeSlot` 目前只有
   编码/解码/Mask 位定义；环境层（`hsbg/env/driver.py`/`game_env.py`）接入是
   P3 工作，未启用时这些索引 mask 恒 False。`FreezeSlot` 还缺两引擎的**公开
   单槽位动作 API**（见 §4.4 的 P3 接入说明）。
3. **target 分裂**：标准 profile 中目标选择是 `Choose` 决策步；legacy 候选的
   折叠目标只在转换器里近似（`candidate_to_std_sequence` 需调用方提供
   `target_option`）。
4. **`hero_power` 槽位不可表示于 legacy**：转换是投影（见 §5.1-4）。
5. **动作空间 ≠ 全部游戏操作**：std 只覆盖两引擎已建模的招募期动作；
   扩展段只登记有证据的"游戏支持但双方未实现"项（§4），不预造语义不明的动作。
