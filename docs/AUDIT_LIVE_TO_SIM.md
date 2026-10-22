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

| 机制 | 数据量 | 引擎/环境支持 | 脚本覆盖 | 结论 |
|---|---:|---|---:|---|
| Choose One（抉择） | 44 张 | 引擎 `PendingChoice("choose_one")`；env `PLAY_SPELL/PLAY_MINION → CHOOSE` | **14 / 44** | **严重缺口** |
| Activate（发动） | 52 张 | 引擎 `use_activate`；env `ACTIVATE` | 50 / 52（缺 2 张 test 卡） | 基本完整；live 未实现 |
| Dark Gift（黑暗之赐） | 47 张 | 引擎 `use_dark_gift` + 通用 apply | 通用实现 | live 未实现；env 已支持 |
| Battlecry（战吼） | 324 张 | 引擎/脚本 `needs_target` / target | 123 / 324 有 registry | 需按池/效果细分审计 |
| 目标选择 | 14 个 battlecry `needs_target` + 法术/英雄技能 | driver 生成 target variants | 依赖脚本 | live 识别不稳 |
| 英雄技能 | 165 | 引擎 `use_hero_power`；env `HERO_POWER` | 按英雄脚本 | live 未实现 |
| 三连/发现/饰品 | 多个 PendingChoice | 引擎 `choose` | 部分 | live 仅部分 |
| 随从换位 | — | 引擎有 `position`；env 无显式 move | — | **env/live 都缺** |

### 3.1 Choose One 缺失清单（30 张）

以下卡 `choose_one=true`，但 `REGISTRY` 脚本没有 `choose_options`
（因此引擎无法挂起 `choose_one`，只能退化为普通牌/无选择）：

```text
BG26_355 BG26_355_G
BG30_110 BG30_110_G
BG30_117 BG30_117_G
BG30_128 BG30_128_G
BG31_144 BG31_144_G
BG31_323 BG31_323_G
BG31_325 BG31_325_G
BG31_327 BG31_327_G
BG31_329 BG31_329_G
BG31_825 BG31_825_G
BG31_842 BG31_842_G
BG31_880 BG31_881 BG31_884 BG31_886 BG31_890 BG31_892
BG36_331 BG36_331_G
```

其中 **BG31_880（Alliance Flag）** 正是 live 截图里反复尝试施放/选择的
抉择法术；引擎没有脚本，模拟环境无法正确模拟它的二选一，属于“引擎/脚本缺失”
实锤。

### 3.2 其它覆盖

- `bg_pool_minions` 273 张中 13 张无 registry（部分为白板/特殊 token，需逐张确认）；
- `bg_pool_spells` 76 张中 4 张无 registry；
- Activate 仅缺 `BGMinionAbilityTest` / `BGMinionAbilityTestCost` 测试卡；
- Dark Gift 47 张由通用 `apply_dark_gift` 处理，无需逐卡脚本，但需补三选一
  的 live UI（购买黑暗之赐随从时弹出）。

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

1. Choose One 脚本补全（30 张，尤其 BG31_880/BG31_881/BG31_884 等 live 出现）；
2. live 英雄选择/确认页状态机（已热修，待回归）；
3. live 目标选择：目标选中高亮 + 敌方/友方/手牌/酒馆目标区分；
4. live 黑暗之赐购买/三选一；
5. live 英雄技能（含目标）。

### P1

1. live 冻结、主动结束回合；
2. live Activate（发动）；
3. 饰品商店/三连奖励统一 `choice` 状态机；
4. env 补 `move/reorder` 动作；
5. 观测补 `frozen/choices/choice_options/targets` 字段。

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
| 补 30 张 Choose One 脚本 | `hsrl2/scripts/batches/*` | 44/44 有 `choose_options`，引擎测试通过 |
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
  1. **卡牌脚本**：Choose One 44 张只实现 14 张（30 张缺失，含 live 出现过的 BG31_880）；
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
