# AGENT_TEAM — HSBRSIM 多 agent 协作规范（间断开发版）

> 解决的问题：**历史记忆保留 + 思路一致性**。多个 agent 在不同时间、不同会话里接手同一个
> 项目，最贵的成本不是写代码，而是「不知道上一轮为什么这么改」→ 重跑已证伪的路线、把
> 单点噪声当结论、杀掉别人在跑的训练。
>
> 本文是 [AGENTS.md](../AGENTS.md) §4「写范围」的**扩展与操作化**，不修改其契约。
> 事实底稿在 [PROJECT_MEMORY.md](PROJECT_MEMORY.md)；决策流水在 [DECISIONS.md](DECISIONS.md)；
> 实验台账在 [EXPERIMENTS.md](EXPERIMENTS.md)。

---

## 1. 角色与写范围

### 1.1 角色表（继承 AGENTS.md §4，补齐评测/数据/归档）

| 角色 | 写范围（**只有这些**） | 禁止 |
|---|---|---|
| **Lead** | `README.md`、`AGENTS.md`、`docs/**`（含本文、PROJECT_MEMORY / DECISIONS / EXPERIMENTS）、`pyproject.toml`、`scripts/verify_all.py`、最终提交与 tag | 直接改 `hsbg/az/**` 的算法逻辑（必须由 az-train 做）；替他人「顺手修一下」 |
| **az-train** | `hsbg/az/train/**`、`scripts/az_*.py`、`scripts/train_az_ppo.py`、`scripts/train_entity_sync.py`、`tests/test_az_*.py`、`tests/test_*train*.py` | 改 `hsbg/az/search/**`（az-search 的）、改 `data/**`、改评测口径 |
| **az-search** | `hsbg/az/{search,belief,puct,env_api,policy,toy_env}.py`、`tests/test_az_search.py` | 把搜索接进训练主环（需 Lead 决策 + DECISIONS 条目） |
| **engine** | `rust/**`（机制/数据）、`rust/FORK.md`、`tests/test_rust_engine.py` | 改 Python 训练侧；跳过 `cargo test --release -p hsbg-engine` |
| **env-profile** | `hsbg/env/action_space_std.py`、`hsbg/env/obs_std.py`、对应测试 | 改 0..244 动作段（**永久冻结**）或 `layout()` 32 项 |
| **data** | `data/**`、`data/p2/**`、`tools/p2_data/**`、`tools/version_sync.py`、`scripts/import_*.py`、`scripts/build_*_library.py`、`scripts/mix_human_libraries.py`、`scripts/fetch_firestone_replays.py`、`scripts/parse_firestone_replay_xml.py` | 改训练 loss/奖励；在没有 `DECISIONS` 条目的情况下换默认训练库 |
| **eval（新增）** | `scripts/human_panel_eval.py`、`scripts/c0_gate.py`、`scripts/quality_monitor.py`、`scripts/exam_paired_eval.py`、`scripts/exam_summary.py`、`hsbg/eval/**`、`runs/exam/**`（只写自己的产物）、`runs/eval/**` | 改训练代码；**改评测器口径而不写 DECISIONS**（这是最隐蔽的作弊面） |
| **archive（新增）** | `runs/**`（归档/清理/`MANIFEST`/`SHA256SUMS`）、`docs/assets/**`、`plots/` 产物 | 删除别人的 run 目录；`git clean`；改 `runs/<run>/model.pt` |

### 1.2 硬规则：**一个文件同一时间只有一个 writer**

1. 写之前 **30 秒内重读**目标文件（`remote_read` 或本地 `read`），确认内容与你的记忆一致。
2. 只做**定点修改**（`edit` / `replace` 单点），不要整文件覆写；覆写 = 宣称自己是当前 writer。
3. 发现文件在你读完之后变了（内容、mtime、`git status` 任一不符）→ **停手**，先告知 Lead
   （在 `DECISIONS.md` 的「冲突」小节或直接消息），不要"覆盖掉看起来是别人的改动"。
4. 跨范围修改（例如 az-train 想改评测器）：**写请求**，不写代码。
5. 收工时 `git status --short` 必须只出现你范围内的文件；出现别人的文件 = 你越界了。

### 1.3 禁止的清场命令（AGENTS.md §4 同款，重复是因为代价太高）

`git reset --hard` / `git checkout -- .` / `git clean` / 全仓格式化 / `rm -rf runs/`。
**任何人执行前必须 Lead 明确同意，并在 DECISIONS 记录。**

---

## 2. 决策记录规范（`docs/DECISIONS.md`）

**只要是「改变训练语义」的动作，就必须有一条条目**。包括但不限于：奖励/惩罚项、对手分布
（库、seats、p、fidelity、分位）、优化器/超参、aux loss（BC/DPO/seq/archetype）、动作 mask、
评测口径、默认 checkpoint、数据默认库。

### 2.1 必填字段（缺一不可）

```markdown
## D-YYYYMMDD-NN · <一句话标题>

- **日期**：2026-10-31
- **状态**：生效 / 已回退 / 观察中 / 不采纳
- **动机**：要解决的具体现象（带数字与来源，例如「t15 tier p50 恒为 4」）
- **改动**：改了哪个文件/哪个 CLI 参数；**旧值 → 新值**；默认是否开启
- **A/B**：臂数、预算（iter × games ≈ decisions）、起点 checkpoint+sha、seed、唯一变量
- **数字**：主指标 Δ[95%CI]、次要指标、硬约束（illegal/truncated）、吞吐变化
- **结论**：采纳 / 不采纳 / 证据不足（**「证据不足」是合法结论，不许写成「有效」**）
- **是否回退**：回退命令或「不回退，原因」
- **链接**：设计文档、`runs/<ab_run>/`、台账行
```

### 2.2 写法约束

- **一次只改一个变量**；改两个就必须拆成两条条目（否则 A/B 无法归因）。
- **先写预注册，再看结果**：判据（含容差、样本量、停止规则）必须在跑之前写好；
  跑完只补「数字/结论」两栏。事后改判据 = 记录作废。
- **失败也写**。`状态: 不采纳` 的条目和采纳的条目**同等重要**——它阻止下一个人重跑。
- 数字必须带：**局数**、**面板**（human 512 / 256、bot、quality 96、exam 2048）、**CI**。
  「6.34 比 6.44 好」这种句子不许出现（除非同时给 CI 说明它不比噪声大）。
- 每条不超过 40 行；长分析放 `docs/<TOPIC>.md`，条目只放结论 + 链接。

---

## 3. 实验台账（`docs/EXPERIMENTS.md`）

所有**占过 GPU/CPU 的 run**（含失败、含 40 iter 的 A/B）都进表；不训练的评测/审计/数据构建
放在台账 §3「评测 / 审计（不训练，不占 GPU）」小节。

| 列 | 必填 | 说明 |
|---|---|---|
| `run` | ✅ | 目录名（`runs/<run>`），必须与 `latest.json` 的 out 一致 |
| `配方摘要` | ✅ | 与「当前配方」的差异（**只写差异**，见 §6.2 命名规则） |
| `预算` | ✅ | `iter × games ≈ decisions`，墙钟，GPU 数 |
| `human 面板` | ✅ | 面板点数（512/256 局）+ 最好值 + 最终值；无则写 `—（无 human 面板）` |
| `tier` | ✅ | t9/t12/t15 tier p50；无则 `—` |
| `强度比` | ✅ | t9/t12/t15 强度比；无则 `—` |
| `结论` | ✅ | 采纳 / 否决 / 证据不足 / 进行中 |
| `链接` | ✅ | `docs/<TOPIC>.md` §节 + `runs/<run>/` |

**硬要求**：任何进入 DECISIONS 的「采纳」条目，台账里必须有对应行；反之台账里「否决」的行
必须能在 DECISIONS 找到原因（否则视为「没人知道为什么停的孤儿实验」）。

---

## 4. 交接清单（新 agent 接手必做）

### 4.1 必读的 5 个文件（按顺序，约 20 分钟）

1. [AGENTS.md](../AGENTS.md) — 契约、命令、写范围、验收。
2. [PROJECT_MEMORY.md](PROJECT_MEMORY.md) — 目标/主指标/当前配方/已证伪路线/数据资产。
3. [AGENT_TEAM.md](AGENT_TEAM.md)（本文）§4–§6 — 禁止事项 + 门禁 + 一致性守则。
4. [DECISIONS.md](DECISIONS.md) **最近 3 条** — 上一阶段为什么这么改；再看 `状态: 观察中` 的条目。
5. 当前 run 的**现场**：`ps -eo pid,etime,cmd | grep train_entity_sync | grep -v grep` +
   `cat runs/<run>/latest.json` + `tail -1 runs/<run>/history.jsonl`。
   （PDF 文档会过期，`ps` 不会。）

辅助：`docs/EVAL_PANELS.md`（评测口径）、`docs/PERF_COLLECT.md`（吞吐与提速开关）。

### 4.2 必须核对的 3 个数字

| # | 数字 | 怎么核 | 为什么必须核 |
|---|---|---|---|
| 1 | **当前最强固定 checkpoint 的 human 面板值**（及局数） | `python -c "import json;h=json.load(open('runs/az_entity_s13/eval/history.json'))['evals'];print([(r['decisions'],r.get('human_mean_rank')) for r in h if r.get('panel')=='human'])"` | 所有「是否变好」的判断都以它为参照；写错会让整份报告结论反转 |
| 2 | **最新一次 exam/配对的 Δ 与 n** | `jq '.effects' runs/exam/summary.json` 或读 `runs/exam/SUMMARY.md` §3 | 决定「0.1 名次」是真实还是选点偏差；n=2048 的 MDE 是 0.0898 |
| 3 | **当前 run 的预算完成度**（decisions / stop-at-decisions） | `tail -1 runs/<run>/history.jsonl \| jq '.seconds'` + 累加 `collect.decisions` | 判断「曲线是否已可解读」；20M/120M 的结论和 110M 的结论不同 |

> 三个数字必须来自**文件/命令输出**，不许来自本文或任何人的转述。

### 4.3 禁止事项（**硬红线**）

1. **不许重启正在跑的训练**（含「先 kill 再拉起来」）；要改配方 → 起**新 run**（新 `--out`）。
2. **不许 kill 别人的进程**；不准 `nvidia-smi` 看到显存就去清别人的卡。
   本项目自己的进程也只在 Lead 明确要求时才能停。
3. **不许在同一个 checkpoint 上「边看显著性边改配方」**：看一眼面板 → 改一版 → 再看一眼，
   这是选点偏差（winner's curse）的教科书场景，会让 0.1 名次完全不可解释。
   一个 A/B 只允许一个预注册判据、一次检验。
4. **不许用 64 局 human 面板下结论**（SE ≈ 0.35，能"证明"任何东西）；256 局只用于**监控**，
   正式判定要 512 局或 exam 2,048 配对。
5. **不许把开发面板 420000 当封存 exam**；它已被反复查看（[REVIEW_PLATEAU.md](REVIEW_PLATEAU.md) §1）。
   封存判定用 730001/730513/731025/731537，且同一 checkpoint 不得在 exam 上选了再看。
6. **不许把 `--human-board-fidelity full` 说成「真实完整状态」**：它是「准完整可得字段」，
   仍是 board+hand+部分 counters（gold/gems/attachments/player counters/shop 不可得）。
7. **不许跨面板比较绝对值**（bot 1.7 vs human 6.4 不是同一把尺子），也不许跨分位（p50 vs p90）。
8. **不许把「没有显著恶化」写成「有效」**：A/B 的合法结论只有三种——
   显著更好 / 显著更差 / 证据不足。
9. **不许在 `runs/` 里覆盖别人的 `model.pt` / `latest.json`**；冻结用副本 + sha256。
10. **不许把「推算」当「实测」**：配置级暴露率、理论收益必须标「推算/配置级」
    （例：PROJECT_MEMORY §2.4）。

---

## 5. A/B 与晋级门禁

### 5.1 采纳门禁（**照抄现行约定，不得自行放宽**）

| 判据 | 阈值 | 说明 |
|---|---|---|
| **主指标** | **Δhuman ≤ −0.10** | 候选 − 对照，配对差（负=更好） |
| **统计** | **95% CI 上界 < +0.05** | 不是「CI 跨 0 就说不显著」，而是上界必须低于 +0.05 |
| **bot 面板非劣** | Δ ≤ **+0.10**（点估计；CI 上界不强制） | 回归线，不许倒退 |
| **top4** | **≥ 95%**（bot 面板）/ human 面板不得显著下降 | 硬指标 |
| **采集吞吐** | collect 回退 **< +15%** | 用 `history.jsonl` 的 `collect.wall_s` 中位对比，不看单 iter |
| **硬约束** | **零硬错**：0 illegal / 0 truncated / 0 truncated_combats / 0 injection_errors / 0 pool_unbalanced | 任一项非 0 → 实验无效，不是「再跑一次」 |

> **不追 0.1 名次的统计裁决**：512 局的单模型 SE 是 0.09–0.17，n=2048 的 MDE 是 0.0898。
> 所以「+0.10」这个量级的判定必须靠**工程判据**（点估计 + CI 上界 + 机制指标 + 硬约束），
> 不要指望 p 值，也不要用更多局数去换一个「显著」（[REVIEW_PLATEAU.md](REVIEW_PLATEAU.md) §3、§6）。

### 5.2 A/B 的最低工艺

1. **起点冻结**：`cp runs/<parent>/model.pt runs/ab_<name>/start_model.pt`，记 sha256；
   两臂**同一份**起点（否则差异不可归因；在跑的 `model.pt` 每 iter 都在变——
   [PERF_COLLECT.md](PERF_COLLECT.md) §1 踩过这个坑）。
2. **同 seed、同数据、同引擎/数据版本**；唯一变量写进目录名。
3. **预算**：配方类 A/B 至少 **40 iter ≈ 1.1M decisions**；小于 1M 的只算 smoke；
   ≥10M 才能谈「趋势」。40 iter 能判「大退化」，判不了「小改善」——这是**已知限制**，
   报告里必须写。
4. **评测**：两臂同 seed 配对（同 game/seat），报配对 Δ + 95% bootstrap CI + 逐局方向
   （better/tie/worse），并给「leave-one-panel-out」稳健性（若有多面板）。
5. **停止规则**：不看中途显著性；跑满预算再一次检验（预注册）。
6. **产物**：`runs/ab_<name>/{A,B}/`、`runs/ab_<name>/eval/*.json`、`logs/`、
   `start_model.pt` + `SHA256SUMS.txt`。**台账行 + DECISIONS 条目同时写。**

### 5.3 晋级（从 A/B 到主线）

只有同时满足：门禁通过 + 机制可解释（不是"不知道为什么好了"）+ 有回退开关（默认关闭且
逐位等价）+ 单测覆盖 → 才能进下一个 run 的默认配方，并在 DECISIONS 标 `状态: 生效`。

---

## 6. 间断开发的一致性守则

### 6.1 每阶段开场（3 分钟，写进当天记录）

```
1. 读 PROJECT_MEMORY.md（§1–§4）+ DECISIONS.md 最近 3 条
2. ps 确认在跑什么、GPU 谁在用
3. 写「本阶段要回答的一个问题」+「判据」+「预算」——预注册，不许边跑边改
4. 在 DECISIONS 建一条 状态: 观察中 的空条目（动机/改动/判据先写）
```

### 6.2 实验命名规则（**看到名字就知道是什么**）

| 类别 | 格式 | 例 |
|---|---|---|
| 主线 run | `runs/az_entity_s<N>`（`s<N>b` 为同代重跑） | `az_entity_s14` |
| A/B | `runs/ab_<topic>_<variant>` 或 `runs/ab_<topic>/{A,B,C}` | `ab_move_guard/{A,B,C}`、`ab_firestone_mix` |
| 数据构建 | `runs/<lib>_ab`、`data/real_library/library_<source>.jsonl` | `lib_ab` |
| 评测 | `runs/eval/<面板>_<ckpt>_<局数>_<seed>.json` | `runs/eval/human_s13_512_420000.json` |
| exam | `runs/exam/<ckpt>_p<panel>.json` | `runs/exam/s13_10M_p1.json` |
| 审计（不训练） | `runs/audit/<topic>.json` + `docs/<TOPIC>.md` | `runs/audit/pressure_audit.json` |

**配方摘要只写差异**：例如「s13 + DPO 0.02/every1」而不是把 40 个参数抄一遍；
完整命令行放 `runs/<run>/cmd.txt`（新 run 必须落盘，这是唯一能 100% 复现的东西）。

### 6.3 失败也要记录（**这一条决定项目能不能积累**）

失败记录的最小格式（进 DECISIONS，状态=不采纳）：

```
动机现象 → 假设 → 改动（旧值→新值）→ 预算 → 数字（含 CI/局数）→
为什么失败（机制解释，若未知就写"机制未知"）→ 是否值得再用更大预算重试（是/否 + 理由）
```

反面教材（必须避免）：只留一句「试过，没用」。半年后没人知道「没用」是**效应不存在**
还是**预算不够**——这两者的后续动作完全相反。

### 6.4 阶段收场（写进 DECISIONS 最后一条）

```
1. 更新 EXPERIMENTS.md（含失败行）
2. 更新 PROJECT_MEMORY.md 的：基线表 / 当前配方 / 已证伪表 / 数据清单（哪几行变了要写）
3. 冻结：把本阶段判据用的 checkpoint 复制到 runs/exam/ckpts/ 或 runs/ab_*/ 并记 sha256
4. 写「下一阶段的唯一问题」（一句话）——不要留一堆并列想法
```

---

## 7. 冲突与升级

| 情况 | 处理 |
|---|---|
| 两个 agent 要改同一文件 | 先到先得（以最后成功写入为准），后到者改设计或等；**不允许"合并冲突了直接覆盖"** |
| 对门禁/口径有分歧 | 提 Lead 裁决；裁决结果进 DECISIONS（含「为什么这样定」） |
| 发现别人在跑的训练有问题 | **不要动手**，记录证据（命令/日志片段）并报告 Lead |
| 发现历史结论有错 | 新开一条 DECISIONS（状态=更正），**保留旧条目**并链接过去；不要静默改旧文档的数字 |
| 任务板 | `team_task_*` claim/complete，带 revision 与证据（沿用 AGENTS.md §4） |

---

## 8. 最容易被搞错的 10 个点（给下一个 agent 的提醒）

1. **把「配置级暴露率」当实测**（§2.4 的 ≈41–64% 是推算；审计值只有 4.59%）。
2. **把 `fidelity=full` 当真实完整状态**（gold/gems/attachments/player counters/shop 全缺）。
3. **用 64/96 局的 tier 或强度比下结论**（64 局 1 个百分点 = 0.64 局，
   [DPO_UPGRADE.md](DPO_UPGRADE.md) §6.4 有明确噪声说明）。
4. **拿开发面板 420000 当封存 exam**（已被反复查看，最小值有选点偏差）。
5. **在在跑的 run 上「看一眼再改」**（同一 checkpoint 边看边改 = 显著性失效）。
6. **忘了 run 的 `model.pt` 每 iter 都在重写**（跨时间对比必须用快照副本）。
7. **把 bot 面板 1.7 和 human 面板 6.4 放同一张表比较**（不是一把尺子）。
8. **以为 tier 上去 = 强度上去**（DPO 把 t15 tier 4→5，强度比 0.0357→0.0361 几乎不动）。
9. **以为「CI 跨 0」= 证明无效**（n=2048 的 MDE 0.0898；只能说明「没测出来」）。
10. **杀了进程/删了 run 目录当清理**（`runs/` 是唯一的历史证据；归档走 archive 角色）。
