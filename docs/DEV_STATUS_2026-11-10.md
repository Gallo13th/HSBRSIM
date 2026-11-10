# 开发进度快照（2026-11-10 16:10）

> 本文件是交接用的**事实记录**：做了什么、验证到什么程度、哪里坏了、下一步该干什么。
> 不含推测；所有数字均可在文中给出的命令/文件里复核。

## 1. 训练（B13）已完结

| 项 | 值 |
|---|---|
| run | `runs/az_stage300m_b13` |
| 最终累计 | **303.21M**（预设 300M；`--stop-at-decisions` 传参有 bug，多跑 3.2M 后手动停） |
| 终评 | 768 局 bot 面板 + human 96：`runs/eval_panel/b13_300M_bot768.json`、`b13_300M_human96.json` |
| 体面收尾 | `/tmp/watchdog_b13.pause` 已写；trainer/watchdog 均已停 |
| 巡检定时任务 | **已暂停**（`schedule-66e4386a…`，训练停止期间不再空转） |

B13 终评数字（768 局，强制升本 + ban 加重护手）：

| 指标 | B13 | B12 | B11(384g) | B08 |
|---|---:|---:|---:|---:|
| rank | 1.594 | 1.589 | 1.617 | **1.484** |
| top4 | 99.9% | 99.5% | 99.2% | — |
| win | 50.9% | 52.3% | 54.2% | **61.3%** |
| 长强局 n / win | 62 / 9.7% | 64 / 18.8% | 27 / 25.9% | — |
| tier≥5 @t12/@t15 | 86.8% / 100% | 86.2% / 99.8% | 85.7% / 100% | 7.7% |
| 死亡强度 p50 | 740 | 718.5 | 765 | — |
| human 96 局 rank | **5.802** | — | ~6.0 | — |

前二阵容（36/48 局进前二，252 卡位）：放大器 **18 张 = 7.14%**（人类 7.02%），
其中提图斯 7 / 达卡莱 6 / 布莱恩 5；T5+ 卡位 21.4%。

**结论**：规则层（买+留）成功；协同层未涌现（长强局胜率 9.7%、rank 与 B12 同级）。
明细见 `docs/B13_DESIGN.md`。

## 2. 本轮修掉的真实 bug（都已提交）

| # | Bug | 影响 | 提交 |
|---|---|---|---|
| 1 | `ceiling_head` 扩到 4 输出后，旧 2 维 checkpoint 加载 size mismatch | B12 终评 / B13 起训直接失败 | `ef7d983` |
| 2 | 路线 2 的两个目标（has_amp / growth）在 3 处字段传递点全漏 | ceiling 头后 3 维**从未受训**（权重恒 0） | `f82cb02` |
| 3 | `library.py` 卡 id 少 +1 | build_bot_library 取到错卡 | `b65fd9b` |
| 4 | `selfplay.py` 漏传 `config_json` | selfplay 模式下 ban 饰品/降费失效 | `b65fd9b` |
| 5 | monitor 续训记账口径错（cum-offset / dev-offset / relabel offset） | 200M–300M 点位静默丢失 | 见 `/tmp/fix_mon_offset.sh` 与 B13 文档 |
| 6 | relabel 双重偏移（已 relabel 的全局名被再 +offset） | 出现 `ckpt_466267875` 之类假快照 | 手工清理 + 账本登记 |
| 7 | watchdog hist_len 把 header 行算进去、SNAPSHOT_EVERY=100 漂移 | 续训 DONE 少算 3.6M | `tools/watchdog_b13.py` |
| 8 | `run_stage300m_*.sh` 的 STOP 换算 | 训练跑到 303.2M 才停 | **未修**（见 §5） |

## 3. 攻略形式化（本轮主要工作）

### 3.1 已落地文件

| 文件 | 内容 | 状态 |
|---|---|---|
| `docs/HSBG.md` | 攻略原文（440 行，31 套） | ✓ 入库 |
| `data/comp_plans.json` | 我按原文拆的 31 套：econ/start/pay/amp/syn/flex/pivot + window + position + loop 摘要 | ✓ 已提交 `e0e13ac` |
| `data/comp_exec.json` | **子智能体产出**的 31 套可执行规格：beneficiary(+why)/loops(keep,buy,play_then_sell,phase)/position/start_window/checklist | ✓ 新增（未提交） |
| `scripts/check_comp_exec.py` | 上述规格的自检（卡名可解析/in_pool/受益者命中/min_count） | ✓ 自检 31/31 通过，负面测试有效 |
| `runs/comp_exec_check.md` | 逐套自检表 | ✓ |

`comp_exec.json` 的关键价值：**每条写明"谁是受益者、为什么"**（例如
"卡雷苟斯：每触发一次战吼，使你的龙 +2/+2 → 受益者是龙，不是元素"），
并区分 `keep`（留场）与 `play_then_sell`（买→打出→卖掉）的循环件。

### 3.2 沙盒执行器（三版并存，尚未收敛）

| 脚本 | 做法 | 状态 |
|---|---|---|
| `scripts/comp_lab.py` | 6本/10金/999血，注入商店，按角色优先级 | 早期版本，已被后两版取代 |
| `scripts/comp_exec.py` | 从 `comp_plans.json` **自动推导** keep/cycle/受益者 | 可用，但会误判（例：把"钢铁场地管理员"并入 keep；`野兽-美味龙虾` 曾因"龙虾"含"龙"被判成龙，已修） |
| `scripts/comp_run.py` | 用**自动推导**的 keep/cycle 跑沙盒（带卖卡+循环） | 31 套首轮：仅 1 套 OK |
| `scripts/comp_run2.py` | 用**子智能体规格** `comp_exec.json` 跑沙盒 | 31 套首轮：**4/31 OK**（见 §4） |

### 3.3 已确认的对照事实（comp 30 龙-战吼）

| 版本 | 场上龙数 | 卖卡/循环 | 终局强度 |
|---|---:|---:|---:|
| 最初（无卖卡、无受益者概念） | **2** | **0** | 167 |
| `comp_run.py`（自动推导 + 卖卡循环） | **7** | 5 | 324 |
| 规格驱动 `comp_run2.py` | 4/4 达标 | 7 | 240 |

## 4. 31 套规格驱动测试结果（`comp_run2.py --all --turns 10`）

汇总：**4/31 OK**（判定 = 受益者数 ≥ min_count 且 终局强度 ≥ 2× 首回合）。

已知问题（**这是当前最大的未完成项**）：

| 现象 | 例子 | 根因判断 |
|---|---|---|
| 强度逐回合恒定 | 02=87 恒定、03=102、28=62、30=240、31=66 | 每回合没有真正进入下一回合的招募（用 `needs_action` 判回合，而不是 `state_json.turn` 变化）→ 同一个盘面被重复记录 |
| 强度曲线错位跳变 | 01: [70,1940,70,3792,70,5651…] | 记录时机在"战斗后/招募初"之间错位 |
| 循环次数失真 | 28 套循环 2307 次、29 套 1668 次 | "卖出→再注入→再打出"没有按 `loops[].phase` 与每回合上限限流 |

## 5. 未完成 / 已知待修（按优先级）

1. **修 `comp_run2.py` 的回合推进**：以 `state_json()["turn"]` 变化判定新回合；每回合只记录一次盘面。
2. **循环限流**：按 `comp_exec.json` 的 `loops[].phase` 与"每回合最多 N 次"执行，杜绝 2307 次刷循环。
3. **重跑 31 套**，输出三态判定（正确 / 实现有误 / 卡池不可得）+ 强度曲线，逐套定位"实现有误"。
4. **`STOP` 换算 bug**：`scripts/run_stage300m_*.sh` → `train_block_clean.sh` 链路里
   `--stop-at-decisions` 实际拿到的是小值（B13 时是 2,230,794），必须核对
   `/proc/<pid>/cmdline` 的真实值再起训。
5. **收尾守卫重建**：B13 的 `finish_guard` 在重启中被清掉；每次起训必须重新拉起，
   否则到 300M 不会自动写 PAUSE / 造 `ckpt_300000000.pt`。
6. **路线 2 真正验证**：B13 因早于修复启动而未生效；下一次训练必须验证
   ceiling 头第 1/2/3 行权重非零、`has_amp` 预测可用（脚本 `scripts/ceiling_hasamp_auc.py`）。
7. `comp_exec.json` 里 13 张 `unavailable` 卡（极性B-Box、惧之煞、微光机器人、
   三支尖利箭矢、飞行专家、霜咒者、潮汐召唤者等）需按当前卡池决定是否换替代卡；
   11/16 两套的"受益者不足"需决定是否允许把 token/生成物写进 buy 列表。

## 6. 可复核的命令

```bash
# 规格自检
PYTHONPATH=rust/python:. python scripts/check_comp_exec.py
# 单套沙盒（规格驱动）
PYTHONPATH=rust/python:. python scripts/comp_run2.py --plan 30 --turns 10
# 全量沙盒
PYTHONPATH=rust/python:. python scripts/comp_run2.py --all --turns 10 --out runs/comp_run2.json
# B13 终评复核
python -c "import json;d=json.load(open('runs/eval_panel/b13_300M_bot768.json'));print(d['mean_rank'],d['win'])"
```
