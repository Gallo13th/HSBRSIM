# 固定阵容脚本 × RL：下一轮 20M decisions 的接入方案（T4）

> 写范围：本文 + `scripts/comp_opponent_probe.py`（只读探针，不训练、不占 GPU）。
> 结论基于：`scripts/comp_scripts.py`、`runs/comp_scripts/{roles,supply,*.json}`、
> `scripts/train_entity_sync.py`、`scripts/comp_metrics_probe.py`、`scripts/comp_handover.py`、
> `docs/{COMP_SCRIPTS,COMP_SCRIPTS_V2,DECISIONS,REWARD_SHAPING}.md`，以及本文新增的两组实测
> （30 局脚本探针 11,335 决策 / 模型 96 局 `comp_fit` 相关性检验）。日期 2026-11-03。

## 0. 一页结论

| 问题 | 答案 |
|---|---|
| 今晚开不开 `--comp-fit-coef`？ | **不开**（`0.0`）；`--comp-fit-t9-bonus 0.0`、`--comp-trinket-coef 0.0` 一并保持 0 |
| 为什么不 | `comp_fit` 的四个分量（核心/使能/种族多样性/tier）正是**已被证伪**的那套人类先验；同口径实测 Φ(t9) 与 t15 强度**无正相关**（Pearson −0.079，Spearman −0.196，n=84）；且奖励实际只有 **2 套**候选（不是 help 文本说的 26 套） |
| 主方案 | **脚本 = 评测参照臂 + 只读探针**（0 训练成本、0 数值风险）；先把「谁是强基线」量准，再谈先验 |
| 备选 | **脚本盘面快照对手席位**（board-only，1 席 / p=0.1 / t≥8），走现成 `--mirror-snaps` 通道；不给任何奖励项 |
| 若 Lead 仍要 A/B `comp_fit` | 只允许 `--comp-fit-coef 0.10`、`--comp-fit-t9-bonus 0.0`、`--comp-trinket-coef 0.0`，20M decisions 单变量，面板 ≥384 局；判据见 §5 |
| 回退 | 全部三行置 `0.0`（与当前主线 `runs/next_block.sh` 逐位等价，本来就没有打开） |

**一句话**：脚本的价值不在「教模型」（`docs/COMP_SCRIPTS.md` §6 已判「不值得当 BC 教师」），
也不在「当势函数」（本文 §2.3 相关性检验否定），而在**当一把不会跟着训练漂移的尺子**。

## 1. 证据盘点

### 1.1 脚本实现到什么程度（三个数字别混）

| 口径 | 数量 | 出处 |
|---|---|---|
| 阵容目录（Firestone/ZeroToHeroes 抓取） | 27 套，其中 `implementable=true` **26** | `runs/comp_scripts/roles.json` |
| `comp_scripts.py` 真正写了策略的 | **15** 套（A–N + `f_dragon`） | `scripts/comp_scripts.py:119-296`（`COMPS` 注册表） |
| 供给可达（`core_appear ≥ 5%`，`supply.json.reachable`） | **2** 套：idx 17 Demon Self Damage、idx 6 Murloc Handbuff | `runs/comp_scripts/supply.json` |

### 1.2 脚本强度（本文新增 30 局探针，见 §7；8 bot 席，纯 CPU）

| 脚本 | t15 Σ p50 / p90 / max | mean rank | top4 | Φ(t9) mean / p50 | 核心到手 p50 | 决策 / 非法 |
|---|---|---|---|---|---|---|
| `--comp auto` | 225 / 515 / 1200 | 4.667 | 46.7% | 0.308 / 0.20 | t6（率 80%） | 3,616 / **0** |
| `--comp J`（历史最强） | 195 / 729 / 1105 | 5.067 | 40.0% | 0.292 / 0.20 | t9（率 10%） | 3,539 / **0** |
| `--comp M`（T1 候选之一） | 131 / 426 / 855 | 5.800 | 23.3% | **0.427 / 0.50** | t4（率 67%） | 3,031 / **0** |
| `--comp f_dragon`（纯脚本） | 57 / 219 / 295 | 7.133 | 6.7% | 0.332 / 0.20 | t4（率 47%，退出率 63%） | 1,149 / **0** |

对照（历史，同源文档/产物）：引擎 bot 基线 t15 **252**，模型 **564**（`docs/COMP_SCRIPTS.md` §0/§4.1）；
模型 96 局 p0.9 面板 t15 p50 **425**、mean rank **5.833**（`runs/comp_scripts/baseline_p09_summary.json`）。

**换手实验（handover，同一 96 局 p0.9 面板，`runs/comp_scripts/handover_summary.json`）**：
脚本打全场 48（rank 7.896）< 脚本 t0–7 + 模型 t8–15 **62** < 模型 t0–7 + 脚本 t8–15 **218** < 全模型 **454**（rank 5.833）。
→ **任何形式的「让脚本接管一部分回合」都掉分**；这不是「脚本不够强」，是脚本的经济/升本分支比策略差。

### 1.3 训练脚本里四个「comp」开关，只有两个是同族

| 开关 | 位置 | 语义 | 是否「固定阵容脚本」接入点 |
|---|---|---|---|
| `--comp-fit-coef` | `train_entity_sync.py:2282`，实现 `738-788` | T1：t≤9 逐决策 `c·ΔΦ`，`Φ = max over 候选套` | ✅ 是（但见 §2 的四个缺陷） |
| `--comp-fit-t9-bonus` | `:2284`，实现 `785-786` | 同 Φ，在 t≤9 最后一个决策一次性 `bonus·Φ` | ⚠️ 与上者**同一目标**，信用分配退化（§2.2） |
| `--comp-trinket-coef` | `:2286`，实现 `789-809` | 饰品 3 选 1 选中「best-fit 套的关键饰品」时 +c | ⚠️ 非势函数、非稠密（96 局里命中 0 次，见 `baseline_p09_summary.json`） |
| `--compound-prior-coef` | `scripts/train_economy_sandbox.py:643`、`scripts/compound_prior_eval.py:54` | **复利（compound）卡先验**，沙盒/评测专用 | ❌ 不同概念，与阵容脚本无关 |
| `--archetype-bias-coef` | `:1744`，`docs/ARCHETYPE_BIAS.md` | 流派**推理期 logit 偏置**（只加不减、不屏蔽） | ⭕ 另一条通道（§3.2 的下一站） |

## 2. `comp_fit` 势函数：数学是否成立

### 2.1 公式（`train_entity_sync.py:762-786`）

`Φ(s) = 0.30·min(1,核心数) + 0.25·min(1,使能数/2) + 0.20·min(1,种族数/type_min) + 0.25·[tier ≥ curve(turn)]`，
`Φ ∈ [0, 1.0]`；`F_t = c·(Φ(s_t) − Φ(s_{t-1}))`（**只在 t ≤ 9 累计**），外加 `bonus·Φ(t9)`。

### 2.2 四个可验证事实（前三个是缺陷）

1. **候选只有 2 套，不是 26 套。** help 文本写「对 26 套取 max」，实现是
   `implementable ∧ supply.reachable`（`:334-343`）。实跑 `_comp_fit_tables()`：`n_fit_comps 2`
   → `Murloc Handbuff`、`Demon Self Damage`。后者按 `docs/COMP_SCRIPTS.md` §5 是**无法脚本化**的
   （成长在战斗/掉血触发器里），但它 `roles.json.implementable=true` —— 于是奖励的「核心卡」里
   有一半指向一个策略根本抓不住的套。
2. **`type_min` 永远回落到 4。** `:344-353` 用 `importlib` 加载 `comp_scripts.py` 时没写
   `sys.modules`，dataclass 解析直接抛 `AttributeError: 'NoneType' object has no attribute '__dict__'`，
   被 `except BaseException` 吞掉 → `type_min_map={}`。实测：`Murloc Handbuff` 在
   `comp_scripts.COMPS` 里 `type_min=3`，`_comp_fit_tables()` 里是 **4** → 种族项被系统性压低。
   同一指标更糟的一点：离线 `comp_metrics_probe.py`（正常 `import`，`type_min=3`）与训练内 T1
   （`4`）**是两个口径**，`history.jsonl` 的 `comp_fit9_mean` 不能直接和 `baseline_*_summary.json` 比。
3. **不是 policy-invariant 的 PBRS。** 望远镜要求 Φ(terminal)=0（`docs/REWARD_SHAPING.md:63`）。
   这里 (a) 只累计到 t≤9，(b) 终局盘面非空 ⇒ Φ(T)≠0。因此整局塑形和 = `(c+bonus)·Φ(t9)`：
   **它就是一个有界的 t9 终局奖励**，会改最优策略（幅度小而已），不能声称「数学中性」。
   `--comp-fit-t9-bonus` 与 `--comp-fit-coef` 目标完全相同，区别只是把信用压到 1 个决策上
   —— 正是 D-20261030-03 已经失败的形态（「通路通、收益无」，根因是信用分配）。
4. **饰品项基本不触发。** `baseline_p09_summary.json`：96 局里 `trinket_t6_match_rate=0.0`、
   `t9_match_rate=0.0`（`trinket_offered_n=1`）→ 该项在近期策略上是纯噪声开关。

### 2.3 决定性检验：Φ(t9) 与强度无正相关

用 `runs/comp_scripts/baseline_p09.jsonl.gz`（模型 s27d，96 局 p0.9 面板，逐回合 Φ 与 t15 强度）：

| 量 | 值 |
|---|---|
| Φ(t9) mean / p50（n=84，12 局 t9 前死亡） | **0.434 / 0.400** |
| Φ(max t≤9) mean | 0.512（96 局都 < 0.75） |
| Pearson(Φ(t9), t15 Σ) | **−0.079** |
| Spearman(Φ(t9), t15 Σ) | **−0.196** |
| Pearson(Φ(t9), 名次) | −0.014 |

再叠上 §1.2 的脚本 M：**同口径 Φ(t9)=0.427（p50 0.50）与模型持平，但 t15 强度 131 vs 425（p0.9）/252（bot）**。
即：**Φ 高 ≠ 强**，而且把 Φ 当奖励去最大化的那个方向上，历史最强手写脚本的落点就是 bot 水平
（249 ≈ 252 ≪ 564）。这不是系数问题，是目标问题。

### 2.4 系数标定（若仍要开，这是上限）

- Φ 有界 [0,1]，实测天花板 0.75 ⇒ 整局塑形 ≤ `c`，占名次效用全距（2.0，`REWARD_SHAPING.md:107`）的
  `c/2`。`c=0.10` → ≤5%，实测 ~2.2%；单次 ΔΦ 最大 0.30 → 单决策奖励 ≤0.03。
  **这是 `comp_fit` 唯一优于旧 shaping 的地方**（旧 Φ 可到 10³，|F| p50 是效用全距的 7.5×）。
- 但 D-20261030-01 的教训不是量级：两批各 1.6M decisions 的 A/B，Δ 的 95% CI 宽 ≈**0.2 名次**
  → `c=0.1` 能产生的最大效应（≤0.1 名次）在**当前面板功率下不可测**。要测 0.1 需 ≥384 局配对面板
  或 ≥4× 预算。所以「开小系数去测」是拿 20M 买一个统计上测不到的东西。

## 3. 主方案（今晚）：脚本转为「评测参照 + 只读探针」

| 项 | 内容 |
|---|---|
| CLI | `--comp-fit-coef 0.0 --comp-fit-t9-bonus 0.0 --comp-trinket-coef 0.0`（与 `runs/next_block.sh` 一致，逐位等价） |
| 训练改动 | 无。20M 的唯一变量留给 Lead 已定的主线改动，不被 comp 混叠 |
| 脚本接入 | ①`scripts/comp_opponent_probe.py`：上线前 30 局合法率/强度体检（§7，~25 s，CPU）；②评测臂 `scripts/comp_handover.py --arm all_script`：把「脚本水平」作为固定参照写进 eval 报告 |
| 预期效应 | 训练侧 0（不变）；**测量侧 +**：多一把不随训练漂移的尺子，能立刻发现「模型掉到脚本以下」这类回归 |
| 失败判据 | 若评测臂显示 `all_model` 落在 `all_script` 的 ±1σ 内（即模型 ≈ bot 水平），说明问题在采集/奖励而不在先验 → 应先查主线，不是加 comp 先验 |
| 回退 | 无（本来关闭）；探针 0 训练耦合，随时删 |

## 4. 备选：脚本盘面快照「对手席位」

**首个要否掉的形式**：不要新增 Python 策略座位。`--opponent` 只有 `bot/self/weak`（`:1760`），
非 learner 座位只有三条现成通道：`--frozen-opponent`(checkpoint)、`--mirror-snaps`(回合末盘面)、
`--human-boards`(人类战团 board-only)。`scripts/comp_handover.py` 的 `ScriptAdapter` 只是**评测**侧适配器。

**最小可行接入**（若 Lead 要「更硬的对手多样性」）：
用 `comp_scripts` 跑 30 局、把每回合盘面 dump 成 `snap_*.json.gz`，走镜像通道：
`--mirror-seats 1 --mirror-p 0.1 --mirror-sample p50`（t≥8 才注入，加在注入侧过滤）。
预期：脚本盘面比人类战团**弱**（225 vs 425），只会降低压力 → 预期**负效应**。
失败判据：human 面板 mean rank Δ > +0.03 或 top4 −1pp → 立刻 `--mirror-seats 0 --mirror-p 0.0`。
回退：两行置 0。

## 5. 若 Lead 仍要 A/B `comp_fit`：单变量实验设计

| 项 | 设定 |
|---|---|
| 唯一变量 | `--comp-fit-coef 0.0`（A）vs `0.10`（B）；其余 100% 复制 `runs/next_block.sh` |
| 预算 | 各 20M decisions（= 现链一段），同起点 checkpoint、同 seed、同面板 seed |
| 面板 | human 配对 **≥384 局**（96 局的 CI 半宽 ≈0.2，测不到 0.1），外加 bot 128 局 |
| 主判据 | human 配对 Δ(B−A) mean rank ≤ −0.08 且 95% CI 不含 0 → 才继续；否则停 |
| 次判据 | t15 Σ p50 +5% 以上、top4 +1pp 以上、`comp_fit9_mean` 上升（确认通路通） |
| 失败判据（任一命中即关） | Δ mean rank > +0.05；top4 −1pp；`adv_std` 放大 >1.5×；`comp_fit9_mean` 上升但 t15 不涨（= 代理失效复现） |
| 预算纪律 | 若 8M decisions 时 `comp_fit9_mean` 已 ↑ 而 t15 Σ 不 ↑，提前停（省 12M） |
| 回退 | 三行置 0 |

## 6. 今晚最小配置（直接可粘）

```bash
# A. 推荐：不开 comp_fit，其余照 runs/next_block.sh
--comp-fit-coef 0.0 --comp-fit-t9-bonus 0.0 --comp-trinket-coef 0.0
#    （这三行在 next_block.sh 里本来就是 0.0，显式写出只为在 meta/history 留痕）

# B. 脚本体检（训练前/后各一次，只读，CPU，~25 s）
python scripts/comp_opponent_probe.py --comp auto  --games 30 --json-out /tmp/probe_auto.json
python scripts/comp_opponent_probe.py --comp M     --games 30 --json-out /tmp/probe_M.json   # T1 候选套
python scripts/comp_opponent_probe.py --comp auto  --games 30 --mode p09                    # 同 baseline_p09 口径

# C. 若真要 A/B（§5）
--comp-fit-coef 0.10 --comp-fit-t9-bonus 0.0 --comp-trinket-coef 0.0
```

## 7. 探针：`scripts/comp_opponent_probe.py`

只读、纯 CPU、不写 checkpoint。复现 `comp_scripts.play_one` 的 hybrid 协议（阵容动作优先、
其余引擎 bot 兜底），但**逐动作复核 legal mask**（非法计数），并按 `comp_metrics_probe` 的 T1 口径
逐回合算 Φ，输出合法率 / t15 Σ / 名次 / Φ(t9)。
本文 §1.2 的 4×30 局即由它产出：合计 **11,335 决策、0 非法（合法率 1.000）**，
`--games 30` 单套 3.5–24 s（`auto` 最慢，因为 roster 里 `f_dragon` 走纯脚本分支）。

## 8. 复现

```bash
export PYTHONPATH=rust/python:.
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
$PY scripts/comp_opponent_probe.py --comp auto --games 30            # §1.2 探针
$PY -c "import sys;sys.path.insert(0,'scripts');import train_entity_sync as T;print(len(T._comp_fit_tables()['comps']))"  # → 2
$PY scripts/comp_metrics_probe.py --checkpoint runs/az_entity_s27d/model.pt --games 96 \
    --mode p09 --device cuda:4 --out /tmp/base_p09.jsonl.gz          # Φ(t9) 基线（需空闲 GPU）
$PY scripts/comp_handover.py --arm all_script --games 96 --mode p09 --comp M --device cuda:4
```

## 9. 风险 / 待验证

1. **口径混用**：`comp_fit9_mean`（训练内，type_min=4）≠ `fit_max9`（离线，type_min=3）。修 `:344`
   的 `sys.modules` 注册可让两者一致——但修完会让「已验证的 0 收益」变成「未知收益」，所以本文建议
   **修 bug 与开关分离**：先修、再重新跑离线相关性（§2.3 的 −0.08 很可能因此更差，不会更好）。
2. **探针对手口径**：§1.2 的 30 局是 8 bot 席；`§2.3` 的模型是 5 席人类 p0.9。两者都报 p50，
   但绝对强度不可直接相减（bot 席 ≈252 vs 人类席 ≈425 的历史差）。跨口径只作「同量级」判断。
3. 脚本的下一步真正有价值的方向是 `docs/COMP_SCRIPTS_V2.md` §6 的「缺风险状态 / 缺 enabler 链」，
   而不是加系数；那条路要改脚本本身（新 `CompSpec` 字段），与训练开关无关。
