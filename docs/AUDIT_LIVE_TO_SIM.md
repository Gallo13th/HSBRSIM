# Live → 模拟器审计（AUDIT_LIVE_TO_SIM）

> 2026-10-22 审计。输入：`runs/live/clickbot_every/` 的 678 个动作 /
> 95 次 no-effect / 42 次密集诊断截图、`data/bg_*.json`、`hsrl2` 脚本注册表、
> `docs/ARCHITECTURE.md` / `docs/ENV_SPEC.md` / `docs/reference_old/*`。
>
> 结论先行：**模拟器已经实现的操作远多于 live bot 已实现的操作**；
> 当前最严重的缺口不是“引擎没有”，而是 **live 识别/动作映射**、
> **Choose One 卡牌脚本覆盖（14/44）**、以及 **目标选择/黑暗之赐/发光/英雄技能的 live 状态机**。

## 1. 架构审计

### 1.1 现有分层

```text
scripts/ + hsbg/train + hsbg/eval
        │
hsbg/env  (spec / driver / observation / game_env / vec_env)
        │
hsrl2     (game / combat / scripts / data)
```

一次决策：`env.step(candidate) → driver.apply_action → PendingChoice 结算
→ observation.build → policy → next candidate`。

**live 层是架构外挂**：

```text
hsbg/live:
  click_bot.py   状态机 + 坐标 + 输入 + 验证
  launcher.py    战网/窗口
  memory_state   只读状态
```

问题：live 层没有复用 `hsbg/env` 的 **动作语义/目标/选择契约**，
而是重新发明了一套“坐标 + note + state 比较”的动作系统；
因此模拟器已支持的 `FREEZE / HERO_POWER / ACTIVATE / USE_DARK_GIFT /
CHOOSE / END_TURN`，live 层完全没有对应实现。

### 1.2 建议的架构边界

```text
真实客户端
  → LiveState（只读快照）
  → LiveActionPlanner（复用 ActionKind + CandidateAction 语义）
  → UI Executor（坐标/拖拽/选择弹层）
  → Verifier（状态签名/截图）
  → LiveGapLogger（缺口表）
```

即：**动作语义以 `hsbg/env/spec.py` 为准**，live 层只负责“如何用鼠标表达
这个动作 + 如何验证”。这样 live 与 env 的动作集合不会再次漂移。

## 2. 文档审计摘要

| 文档 | 价值 | 问题 |
|---|---|---|
| `docs/ARCHITECTURE.md` | 三层结构、决策数据流、回合边界 | 未包含 live 层 |
| `docs/ENV_SPEC.md` | Observation/Action/step 契约 | 需补 live 映射章节 |
| `docs/ENGINE_API.md` | 引擎 API | 需补 choose/activate/dark gift 示例 |
| `docs/reference_old/BATTLEGROUNDS_RULES.md` | 规则权威参考 | 旧项目遗留，版本需标注 |
| `docs/reference_old/MECHANICS_REFERENCE.md` | 机制↔代码映射 | 旧引擎接口，不能照搬 |
| `docs/reference_old/CARD_REGISTRATION_GUIDE.md` | 卡牌录入 | 需补 choose/activate 模板 |
| `docs/DATA_REBUILD.md` | 37.0.0.255130 数据重建 | 已纠正 hsdata 不入库 |

## 3. 卡牌机制覆盖审计

数据：`data/bg_cards.json` 共 3534 张；`data/bg_pool_minions.json` 273；
`data/bg_pool_spells.json` 76；`data/bg_dark_gifts.json` 47。

| 机制 | 数据量 | 引擎/环境支持 | 脚本/协议覆盖 | 结论 |
|---|---:|---|---:|---|
| Choose One（抉择） | 44 个 `choose_one` 标记 | 引擎 `PendingChoice("choose_one")`；env `PLAY→CHOOSE` | 池内 **12** 个真实实体均有结算；协议分裂：引擎 14 / 自建 5 / 10 base 无脚本；数据标记 9 误报/3 漏报 | **部分实现**：组合/双效 P0 |
| Activate（发动） | 52 标记 / 池内 23 | 引擎 `use_activate`；env `ACTIVATE` | 23/23 池卡有钩子；2 张 test 卡无 registry | 基本完整；live 未实现 |
| Dark Gift（黑暗之赐） | 47 张 | 引擎 `use_dark_gift` + 42 handler | 47/47 有数据；5 张 DEFERRED | live/env 有 P0 观测缺口 |
| Battlecry（战吼） | 324 张 | 引擎/脚本 `needs_target` / target | 123/324 有 registry；99 个 `needs_target` | 需按池/效果细分审计 |
| 目标选择 | 99 个 `needs_target` / 46 `target_candidates` | driver 生成 target variants | 依赖脚本；数据层无 target 元数据 | live 识别不稳；env 有裁剪缺口 |
| 英雄技能 | 165 个 power def / 118 英雄 | 引擎 `use_hero_power`；env `HERO_POWER` | 129/165 有脚本；101/118 英雄可用 | **17 英雄死技能 P0** |
| 三连/发现/饰品 | 多个 PendingChoice | 引擎 `choose` | 三连/饰品流程完备；offer 池未过滤脚本 | live 仅部分 |
| 随从换位 | — | 引擎有 `position`；env 无显式 move | — | **env/live 都缺** |

### 3.1 Choose One 的真实覆盖（修正）

`data/bg_cards.json` 里 `choose_one=True` 的 44 个 def 不是 44 张可玩卡：

- 9 个是**文本误报**（卡牌文本提到 Choose One/获取卡）；
- 3 个是**漏报**（真实抉择但字段没标）；
- 池内真实 Choose One 实体约 12 个（7 随从 + 5 法术），**都有选择结算**；
- 但实现分三套协议：
  - 引擎 `choose_options`：14 个 def；
  - 脚本自建选择：5 张池法术（含 **BG31_880/881/886/890**，BG31_892 由
    `batch_unfreeze` 特判）；
  - 其余 10 个 base 卡无脚本（多为非池/旧赛季）。

因此之前“14/44，直接缺 30”过于粗糙；准确结论是：
**池内机制可用，但协议三分裂，组合/双效/数据字段有 P0/P1 缺口。**

### 3.2 其它覆盖

- `bg_pool_minions` 273 张中 13 张无 registry（部分为白板/特殊 token，需逐张确认）；
- `bg_pool_spells` 76 张中 4 张无 registry；
- Activate 仅缺 `BGMinionAbilityTest` / `BGMinionAbilityTestCost` 测试卡；
- Dark Gift 47 张由通用 `apply_dark_gift` 处理，无需逐卡脚本，但需补三选一
  的 live UI（购买黑暗之赐随从时弹出）。

### 3.3 环境层补充审计（详见 [AUDIT_ENV_ACTIONS.md](AUDIT_ENV_ACTIONS.md)）

`hsbg/env` 主路径支持 buy/sell/play/reroll/upgrade/freeze/hero_power/activate/
use_dark_gift/choose/end_turn，但发现这些 P0/P1 缺口：

| 缺口 | 影响 | 优先级 |
|---|---|---|
| 随从换位/重排完全不支持 | live 可调整站位，env 无法表达 | P0 |
| Dark Gift 选项 `(card_id,gift_id)` 的 gift_id 只拼进 `name` 调试字段，不可观测 | 策略看不到选的是哪个黑暗之赐 | P0 |
| EoT/淘汰/对手招募期的选择被自动结算（`default_pick_index`） | 例 Bigglesworth 淘汰 Discover、任务奖励被默认选 0 | P0 |
| 定向法术目标被裁剪/不可寻址时无 `target=None → choice` 回退 | 目标集合与 live 不一致 | P1 |
| 英雄技能单目标硬上限 6（Maiev 7 酒馆 / 手牌 10 目标丢失） | 目标不可选 | P1 |
| `CandidateAction` 缺 `power_id`/`magnetic` 身份；双技能槽同签名不可区分 | 策略/复现无法区分动作 | P1 |
| Choose One 选项 label/prompt 未进观测，仅 key | 跨卡同 key 无法区分分支语义 | P1 |
| 三连/发现/饰品/任务 choice 零 env 回归测试 | 易回归 | P1 |
| ACTIVATE 定向目标链路无测试 | 目标型发动可能先扣费落空 | P2 |
| `CHOICE_OPTION_MAX=5` 与 Galakrond 7 选项不符 | 选项被截断 | P2 |

### 3.4 引擎层补充审计（详见 [AUDIT_ENGINE_MECHANICS.md](AUDIT_ENGINE_MECHANICS.md)）

引擎对 Choose One/Activate/Dark Gift/英雄技能/三连/饰品的主链路**都很强**，
真正的 P0 是“组合协议/覆盖/数据”：

| 缺口 | 证据 | 优先级 |
|---|---|---|
| 饰品 offer 池未过 `REGISTRY`：41/357 无脚本饰品可被提供并购买，扣金后空转 | `game.py:5015-5017/5050-5052` | P0 |
| 17/118 英雄主技能无脚本（含 37.0 新英雄），env 却全量抽英雄 → 死技能 | `game.py:2110-2115`；env 英雄池 | P0 |
| `choose_options` 与 `needs_target` 互斥：抉择+定向组合永远到不了目标分支 | `game.py:1126-1135` vs `1137-1154` | P0 |
| 旧 Choose One 脚本不处理 `choose="both"`，光环双效静默零效果 | `batch_misc.py:1142-1150/1216-1220` | P0 |
| 法术实体 `CHOOSE_BOTH` 未读（只读英雄/棋盘光环） | `game.py:1517-1518` vs `1123-1125` | P1 |
| Dark Gift 5 张 37.0 新 gift 仍 DEFERRED | `darkgifts.py:159-160` | P1 |
| `choose_one` 数据字段文本兜底：9 误报/3 漏报 | `generate_bg_data.py:387-389` | P1 |
| `PendingChoice.choose()` 不出队、无幂等/回滚 | `game.py:138-171` | P1 |
| 三连后随从发现完备，但法术/卡牌 Discover 由脚本自定义 Action 顶替 | `actions/discover.py` | P2 |

## 4. Live 截图证据与识别缺口

### 4.1 英雄选择页

截图：`runs/live/clickbot_every/screenshots/actions/215643_a0663_click_start_combat.png`

- 画面：`选择一个英雄`，4 张英雄卡，部分锁定；底部有确认/取消条；
- bot 日志：`start_combat` 连续 90 次；
- 根因：`do_hero` 在 `choices<4` 时错误跳到 `start_combat` 坐标 `(0.81,0.46)`，
  而不是点英雄确认条；已改为 `HERO_CONFIRM=(0.544,0.622)` 并移除该 fallback。

### 4.2 抉择/饰品/选择

截图：`215929_a0684_click_choose_one.png`、`220017_a0690_click_choice_0__BG36_345.png`

- 抉择/饰品 UI 不总是出现在内存 `choices` 中；
- 饰品商店需要“选卡 → 确认”，bot 已补；抉择法术仍需按脚本 `choose_options`
  识别选项数量/位置；
- 需要把 UI 弹层类型写入 state（或 gap 日志），不能只靠坐标乱试。

### 4.3 目标选择

截图：`220022_a0692_drag_play_BG36_345.png`、`215820_a0676_drag_dragcast_BG28_503-_board_0_.png`

- bot 已能发出 `select/target/dragcast`，但目标坐标和“目标已选中”高亮未验证；
- 模拟器侧 `_play_spell_variants` 在目标不可寻址时返回空候选（宁缺勿错），
  与 live 可点的目标集合不一致；
- 需要在 gap 表记录：哪些目标类型（敌方/手牌/酒馆/英雄）env 不暴露。

### 4.4 发动/黑暗之赐/英雄技能

本轮 678 动作中 `activate=0`、`dark_gift=0`、`hero_power=0`、`freeze=0`；
截图可见右下英雄技能按钮、顶部冻结按钮、黑暗之赐购买入口，但 bot 没有动作。
说明 live 识别/执行层缺失，不是模拟器引擎缺失。

## 5. 缺陷分级

### P0

1. Choose One 协议统一 + 组合/双效补全（池内 12 实体已有结算，但引擎 14 / 自建 5 / 无脚本 10 base 三分裂；BG31_880 等 live 出现卡在自建协议里）；
2. live 英雄选择/确认页状态机（已热修，待回归）；
3. live 目标选择：目标选中高亮 + 敌方/友方/手牌/酒馆目标区分；
4. live 黑暗之赐购买/三选一；
5. live 英雄技能（含目标）；
6. env 补 `move/reorder` 动作；
7. Dark Gift 选项 `gift_id` 进观测（P0-2）；
8. EoT/淘汰/对手期选择不要默认 auto-pick（Bigglesworth 等）。

### P1

1. live 冻结、主动结束回合；
2. live Activate（发动）；
3. 饰品商店/三连奖励统一 `choice` 状态机；
4. 定向法术 no-target choice 回退、英雄技能目标 >6；
5. 观测补 `frozen/choices/choice_options/targets/power_id` 字段；
6. choice 类 env 回归测试。

### P2

1. battlecry 324 张逐池审计（按是否白板/特殊 token 分类）；
2. 13 张池随从无脚本逐张确认；
3. 旧规则文档版本标注/迁移。

## 6. 反哺模拟器的流程

1. 截图/`actions.jsonl` 找到 live 需要但 env 没有的动作；
2. 写入 `docs/LIVE_TO_SIM_GAP.md`（ID、证据、期望/实际、优先级）；
3. 先在 `hsrl2/tests` / `tests/test_env_*.py` 写失败测试；
4. 引擎改动 → `docs/ENGINE_NOTES.md`；env 改动 → 升 `ENV_SPEC` version；
5. live 复跑同一局面，确认动作不再 no-effect；
6. gap 标记 `verified` 并记录 commit。

## 7. 本次审计可直接执行的任务

| 任务 | 文件 | 验收 |
|---|---|---|
| 统一 Choose One 协议 | `hsrl2/game.py` + 5 张自建脚本 | 池内 12 实体全走 `choose_options`/统一状态机；组合/双效测试通过 |
| 补 10 个 base Choose One 脚本 | `hsrl2/scripts/batches/*` | 按池/旧赛季实际需求逐张补，不追求 44/44 标记 |
| 修英雄确认/开始战斗状态机 | `hsbg/live/click_bot.py` | 英雄选择 1 次通过，无 start_combat 误点 |
| 加 live `USE_DARK_GIFT` | `hsbg/live/click_bot.py` | 购买黑暗之赐随从后出现三选一并选择 |
| 加 live `HERO_POWER` | `hsbg/live/click_bot.py` | 有 `legal.powers` 时点击并验证 |
| 加 live `ACTIVATE` | `hsbg/live/click_bot.py` | 有 `legal.activate` 时点击并验证 |
| 补 env `move` 动作 | `hsbg/env/spec.py/driver.py` | 换位后环境状态改变 |
| 目标选择一致性 | `hsbg/env/driver.py` + live | env/live 目标集合 diff 为 0 |

## 8. 结论

- **模拟器不是“缺所有机制”**：Choose One/Activate/Dark Gift/英雄技能在引擎和
  env 都有骨架；
- 真正缺失分三类：
  1. **卡牌脚本/协议**：Choose One 标记 44 个（9 误报/3 漏报），池内 12 实体虽有结算但协议三分裂（引擎 14 / 自建 5 / 无脚本 10 base），组合/双效有 P0 缺口；
  2. **live 动作层**：Activate/Dark Gift/英雄技能/冻结/结束回合未实现；
  3. **目标/换位**：live 目标 UI 识别不稳，env 无 move 动作。
- 先把这三类按 P0 补齐，再继续真实对局自动化；否则 live 采集会持续暴露
  同类 no-effect，而不是产生新的训练信号。

## 9. 可复现审计

```powershell
python scripts/audit_mechanism_coverage.py --out runs/audit/mechanism_coverage.json
```

输出包含：`choose_one` 覆盖/缺失列表、`activate` 注册/hook、`battlecry` registry/
needs_target、池随从/法术无脚本列表等；用于后续每次数据/脚本更新后复跑。

---

相关：
[LIVE_AUTOMATION_PROTOCOL.md](LIVE_AUTOMATION_PROTOCOL.md)、
[LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)、
[ARCHITECTURE.md](ARCHITECTURE.md)、
[ENV_SPEC.md](ENV_SPEC.md)
