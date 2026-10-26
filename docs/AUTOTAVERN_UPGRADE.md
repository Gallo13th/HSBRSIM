# AutoTavern 借鉴升级报告（AUTOTAVERN UPGRADE）

> 本文件是「借助 [MCG-NJU/AutoTavern](https://github.com/MCG-NJU/AutoTavern)
> 对 HSBRSIM 做全面更新升级」的总报告：审计口径、两仓库对比、升级设计、
> 逐项变更、实测证据、使用指南与限制。
>
> - 升级对象：`HSBRSIM`（本仓库，`master`）
> - 参照仓库：`MCG-NJU/AutoTavern`（commit `fb61201`，TavernGym v1.0.0 +
>   TavernBench，patch 36.6.3.253932，MIT）
> - 执行环境：macOS（Apple Silicon），Python 3.12（`/opt/anaconda3/bin/python3`），
>   Rust 1.98 + maturin（用于构建 TavernGym Python 绑定）
> - 数据基线：HSBRSIM 保持官方 **37.0.0.255130**，不因本次升级回退版本

---

## 1. 摘要

HSBRSIM 的模拟环境（`hsrl2` Python 引擎 + `hsbg/env` RL 环境）存在
「机制覆盖广但可靠性/工程性参差、缺少与可靠实现的可复现对拍、缺少标准
决策评测、环境级存档/不变量能力缺失」等问题。AutoTavern 的 TavernGym
（Rust 引擎 + 精确合法动作掩码 + 确定性存档 + BatchEnv）与 TavernBench
（960 任务决策基准）为此提供了**可执行的可靠参照**。

本次升级采用 **双引擎路线**（保持 hsrl2 为默认引擎与 37.0.0 数据基线）：

1. **接入 TavernGym**：新增 `hsbg/backends/taverngym_env.py`，把 TavernGym
   包装成 HSBRSIM `EnvLike` 协议的可选/参照后端，并提供两后端吞吐基准；
2. **跨引擎一致性审计**：新增 `tests/conformance/` 与
   `docs/CONFORMANCE_AUTOTAVERN.md`，以 AutoTavern 实现与 mechanics 测试为
   参照，对 hsrl2 做机制级与卡牌级对拍，形成 `AC-xx` 差异台账；
3. **按证据修复 hsrl2**：只对「有失败测试 + AutoTavern/官方证据」的分歧做
   最小修复（`docs/ENGINE_NOTES.md` F-20 起），并补齐引擎只读查询/名次/
   解冻/阶段等 API 硬化；
4. **环境层升级**：精确存档/恢复（`hsbg/env/snapshot.py`）、结构不变量
   （`hsbg/env/invariants.py`，移植自 AutoTavern `invariants.rs`）、
   「候选动作 = 全部合法且可执行」的掩码精确性验收；
5. **引入 TavernBench**：`benchmarks/tavernbench/` + `scripts/run_tavernbench.py`，
   可离线复现 368 任务评测集的评分；
6. **工程可移植性**：修复 macOS/Linux 上项目测试的收集与 checkpoint
   缺失失败（Windows 行为不变），并更新 README/AGENTS/REPO_STATUS 等文档。

**升级过程中由新门禁直接抓到的真实缺陷**：

- **F-36（跨进程确定性）**：`frozenset` 迭代顺序被直接喂给 `game.rng` 的 3 条脚本
  路径（Bramble Tunneler / Fandral's Fortune / SkyAdmiral Rogers）→ 不同
  `PYTHONHASHSEED` 进程轨迹分裂；已 `sorted()` 修复并加双哈希子进程回归。
- **F-37（Reborn 棋盘溢出）**：新增的 `validate_env --check-invariants` 不变量门禁
  抓到「带 Reborn 随从被 Activate 摧毁、亡语召唤填满棋盘后 Reborn 仍直插 →
  board=8」；对照 AutoTavern 的 `reborn` 走 `summon` 且满盘不返回后修复
  （官方 Reborn 受 7 上限）。该案例说明「参照实现 + 结构不变量」组合能在常规
  回归测试之外发现真实机制错误。

**不做什么**：不把 HSBRSIM 迁移到 36.6.3、不替换默认引擎、不引入训练期对
Rust 的硬依赖、不把 AutoTavern 的 245 动作空间强加给现有策略网络
（策略迁移边界见 §7）。

---

## 2. 审计方法与基线

### 2.1 仓库抓取

| 仓库 | 抓取方式 | commit | 说明 |
|------|----------|--------|------|
| `MCG-NJU/AutoTavern` | `git clone https://github.com/MCG-NJU/AutoTavern.git` | `fb61201` (`TavernGym and TavernBench v1.0.0`) | 参照实现，只读 |
| `gallo13th/HSBRSIM` | `git clone https://github.com/gallo13th/HSBRSIM.git` | `e84294f` | 升级对象 |

### 2.2 TavernGym 构建与自测（本机实测）

```bash
# 参考仓库
git clone https://github.com/MCG-NJU/AutoTavern.git
cd AutoTavern
python -m pip install -e .          # maturin 构建 Rust 扩展
python -m pytest tests -q           # 46 passed
cargo test --release                # Rust 引擎自测（本机实测）
```

本机实测结果（macOS arm64，Rust 1.98.1，`cargo test --release`）：
**858 passed / 0 failed**，其中 `mechanics.rs` **415** 项、`complex_interactions`
47 项、heroes 24 项、cards_content 24 项、timewarp/cards/validation 等其余套件
全绿。该套件是第 5 节「参照实现」可信度的直接证据。

TavernGym 冒烟（本机）：

```python
import taverngym
g = taverngym.Game(seed=1)
while not g.is_over():
    for p in range(g.num_players):
        if g.needs_action(p):
            g.step(p, g.bot_action(p))
print(list(g.placements()))   # [2, 4, 6, 8, 7, 1, 3, 5]；整局约 16 ms
```

`taverngym.Game` 公开 API 探针（本机）：`observe(seat)`（3227 float + 124 card）、
`legal_mask()`（245 bool）、`state_json()/from_json()`（精确存档 ~100–300KB/局）、
`view(seat)`（调试 JSON）、`bot_action/step/placements` 等，见
`docs/TAVERNGYM_BACKEND.md`。

### 2.3 HSBRSIM 基线（本机 macOS）

| 检查 | 命令 | 结果（升级前） |
|------|------|----------------|
| 引擎回归 | `python3 -m pytest hsrl2/tests -q` | **4816 passed / 6 skipped**（28.7s） |
| 项目测试 | `python3 -m pytest tests -q` | 572 passed / 54 skipped / **6 failed** |
| 失败原因 | — | 5 项依赖已清理的 `runs/` checkpoint；1 项 Windows 路径假设；另有 `tests/test_live_clickbot.py` 在 macOS 收集失败（`ctypes.windll`） |

> 这些失败是「开发机数据被清理 + 平台假设」造成的工程问题，不是机制回归；
> 本次升级一并修复（见 §6.5）。

---

## 3. 两仓库能力对比

### 3.1 定位与形态

| 维度 | AutoTavern / TavernGym | HSBRSIM / hsrl2 |
|------|------------------------|-----------------|
| 定位 | 酒馆战棋模拟器 + 决策基准（研究发布） | 可训练/可评测/可复现的 RL 智能体项目（持续开发） |
| 引擎语言 | Rust（PyO3 绑定） | Python（vendored 引擎 + 自研 RL 层） |
| 引擎规模 | 约 72.5K 行 Rust（123 文件） | 约 181.8K 行 Python（298 文件） |
| 数据版本 | client 36.6.3.253932 / server 36.6.3 | 官方 37.0.0.255130 |
| Python 版本 | ≥3.10（maturin 构建） | ≥3.10（纯 Python + numpy，torch 可选） |
| 安装成本 | 需 Rust 工具链（或预编译 wheel） | `pip install -e .` 即用 |

### 3.2 内容与机制

| 维度 | AutoTavern | HSBRSIM |
|------|------------|---------|
| 池内随从 | 244（239 有脚本 + 关键词卡） | 273（脚本覆盖 99.6%，279/280） |
| 英雄 | 116（技能脚本化） | 全英雄（37.0.0 数据） |
| 酒馆法术 | 70 | 76 |
| 饰品/黑暗赠礼 | 236 / 47 | 数据驱动（REGISTRY 闸） |
| 时空扭曲 | 253 | 37.x 不支持（版本差异） |
| 池子/三连/等级 | `RulesConfig` 全字段可配 | 数据 + 常量 |
| 真实对局校准 | 无 | Power.log/HDT/BobsBuddy 差分（679 场战斗） |
| 官方一致性 | 仅机制测试 + 内容报告 | strict MATCH 72.3%、干净子集 100%、behavior_mismatch=0 |

### 3.3 接口与可靠性工程

| 维度 | AutoTavern | HSBRSIM（升级前） |
|------|------------|-------------------|
| 观测 | 3227 维浮点 + 124 张卡索引（块布局 `layout()`） | 实体 token 槽位 + 全局标量（`Observation` v3） |
| 动作 | **245 个固定离散动作 + 精确 legal mask** | 动态候选动作（≤64，masked argmax） |
| 环境 API | `Game` / `BattlegroundsEnv` / `BatchEnv` | `BattlegroundsEnv` / `EnvLike` / `SyncVecEnv` |
| 存档/恢复 | serde JSON 精确存档（`state_json()/from_json()`） | 仅搜索层 `planning.clone()`；**无环境级快照** |
| 并行 | Rust 线程 BatchEnv（释放 GIL） | multiprocessing VecEnv（进程隔离） |
| 不变量/模糊测试 | `invariants::check` + `--example fuzz` + 池守恒 | `validate_env.py` 行为验收；**无结构不变量** |
| RNG | 内置 xoshiro256**（依赖升级不影响重放） | `GameRNG`（seed 决定，可重放） |
| 测试规模 | Rust 多套件（mechanics 14K 行等）+ 46 Python | 4816 引擎 + 572 项目（本次升级前） |
| 吞吐（本机） | 整局 bot 对局约 **16 ms** | 见 §8 实测（约 0.3–0.5 s/局量级） |

### 3.4 结论：为什么是「双引擎」而不是「整体替换」

1. **版本倒退**：TavernGym 为 36.6.3，HSBRSIM 为 37.0.0（新种族 ABERRATION、
   37.x 卡池、饰品/任务等）。整体替换会让现有数据/脚本/训练资产失效。
2. **接口范式不同**：固定 245 动作 vs 动态候选；现有策略/训练/搜索代码
   按候选动作设计，短期替换会打断现有产物。
3. **TavernGym 的可借鉴价值是「可靠参照 + 参照实现 + 评测基准」**，
   而不是唯一实现：机制级对拍、精确存档/不变量设计、BatchEnv 思路、
   TavernBench 都与引擎版本无关，可直接吸收。
4. **成本可控**：TavernGym 只在安装后作为可选后端；CI/主流程不依赖 Rust。

因此：**默认仍用 hsrl2（37.0.0）+ 双后端可切换 + 以 AutoTavern 为对拍
参照**，既拿到可靠性证据，也不破坏现有路线。

---

## 4. 升级总体设计

```
                      ┌─────────────────────────────┐
                      │        策略 / 训练 / 评测     │
                      │  hsbg.policy / train / eval  │
                      └──────────────┬──────────────┘
                                     │ EnvLike 协议
                     ┌───────────────┴────────────────┐
                     │                                │
        ┌────────────▼────────────┐      ┌────────────▼────────────┐
        │  hsrl2 后端（默认）       │      │  taverngym 后端（可选）   │
        │  BattlegroundsEnv        │      │  TavernGymEnv           │
        │  obs/候选动作/37.0.0      │      │  3227+124 obs / 245 动作 │
        └────────────┬────────────┘      └────────────┬────────────┘
                     │ 快照/不变量/掩码验收              │ state_json 精确存档
        ┌────────────▼────────────┐      ┌────────────▼────────────┐
        │ hsbg.env.snapshot        │      │ taverngym (Rust 引擎)     │
        │ hsbg.env.invariants      │      │ BatchEnv / CombatPreview  │
        └──────────────────────────┘      └─────────────────────────┘
                     │                                │
                     └──────────┬─────────────────────┘
                                ▼
                  tests/conformance/（跨引擎对拍）
                  → docs/CONFORMANCE_AUTOTAVERN.md（AC 台账）
                  → hsrl2 修复（F-20+，有失败测试+证据）
```

双引擎共享 `hsbg.rl.api.EnvLike` 协议；`hsbg.env.spec.Observation` 仍是
唯一观测契约（TavernGym 后端把 245 动作映射为候选动作，权重/策略不直接
迁移，见 §7）。

---

## 5. 变更清单

> 本节的每项在对应文档/测试中有可复现证据；状态在升级完成时更新。

### 5.1 WS1 TavernGym 后端接入

**文件**：`hsbg/backends/{__init__,taverngym_env,benchmark}.py`（约 2.8K 行）、
`hsbg/rl/{envs,collector,evaluate}.py`（工厂/CLI 注册，默认行为不变）、
`tests/test_backend_taverngym.py`（42 项）、`docs/TAVERNGYM_BACKEND.md`、
`docs/RL_INTERFACE.md` §11。

**能力**：

- `TavernGymEnv` 实现 `hsbg.rl.api.EnvLike`，返回 `hsbg.env.spec.Observation`；
  双观测源：`features`（官方 3227 floats + 124 cards 解码，公开信息、~0.17ms/步，
  默认）与 `view`（`Game.view(seat)` JSON，字段最全但 2–12ms/步）；
- 245 维精确 legal mask 展开为 `CandidateAction`，`extra["taverngym"]` 给出
  候选↔flat 动作下标映射（"固定动作空间 + 精确掩码"参照实现）；
- `save_state()/load_state()`（`Game.state_json()/from_json()`，save→load→save
  字节相等）、确定性、终局 rank、非法动作不推进；
- `make_env(backend="taverngym")` 注册进 RL 工厂（惰性导入，默认 `hsrl2` 不变），
  `collector`/`evaluate` 支持 `--backend taverngym`，teacher 类策略明确拒绝；
- 同一 harness 双后端基准（见 §3.4 / README）。

**验证**：`pytest tests/test_backend_taverngym.py` **42 passed**（0.9s）；
与上游 `taverngym.SoloEnv` 同 seed/动作序列逐步 `state_json()` 完全相等；
mask 内每个动作独立存档后执行全部被引擎接受；`collector --backend taverngym`
JSONL 逐行 `validate_record` 通过。

### 5.2 WS2 跨引擎一致性审计

**文件**：`tests/conformance/`（3 文件 / 14 tests）、`tools/ac_conformance/`
（9 模块：双引擎构造/驱动、57 场景、判定口径、runner、`repro.py`、`data_diff.py`、
`gen_doc.py`）、`docs/CONFORMANCE_AUTOTAVERN.md`（458 行台账）。

**场景矩阵（最终 58 个，seeds=48）**：

| 分类 | 修复前 | 修复后 |
|---|---:|---:|
| MATCH | 52 | **55** |
| ENGINE_BUG | 4 | **0** |
| CONVENTION_DIFF | 0 | **2**（AC-01 先攻平局；AC-04 参照侧脚本） |
| UNSUPPORTED | 1 | 1（C18 伤害上限解除，AT Python API 无法注入 alive=4） |

覆盖：战斗核心 26 场景（先攻/嘲讽/潜行目标、圣盾、顺劈、剧毒/烈毒、风怒/超级风怒、
复生、亡语与死亡结算顺序、复仇、伤害上限、平局；含 AC-04 白板对照 C26）、卡牌 16、
经济/规则常量 14、流程 2。数据层：共享卡 3412/3983、共享随从 2393
（攻/血/tier/种族差异 0）、规则常量 18 项中 2 项不一致（AC-02/AC-03，均已修复，现 0 diff）。

**AC 台账**（详见 `docs/CONFORMANCE_AUTOTAVERN.md` §5）：

| 编号 | 问题 | 证据等级 | 状态 |
|---|---|---|---|
| AC-01 | 先攻平局：参照实现按酒馆等级，wiki 现行文本为随机 | E2（二源冲突） | **CONVENTION_DIFF**，保持现状（不改 combat.py） |
| AC-02 | T1 池份数 16 vs 官方 15 | E3（wiki.gg + 参照 config） | **FIXED**（`POOL_COPIES_BY_TIER[1]=15`，F-32） |
| AC-03 | 升级费 T5/T6 9/10 vs 官方 11/11 | E3（wiki.gg + 参照 config + 真实扣费） | **FIXED**（`BASE_UPGRADE_COSTS` 5/7/8/11/11/10，F-33） |
| AC-04 | BG34_405 Relentless Deflector 可达伤害集合不同 | E1→E3（控制实验） | **CONVENTION_DIFF**：白板对照证明异常在参照侧带脚本卡，非 hsrl2 bug（F-35；不改引擎） |

**验证**：`pytest tests/conformance` **13 passed**（3.8s）；`tools.ac_conformance.run
--seeds 48` → 58 场景 **MATCH 55 / CONVENTION_DIFF 2 / ENGINE_BUG 0 / UNSUPPORTED 1**
（4.3s）；`repro` 三条 verdict 与台账一致；未安装 `taverngym` 时套件自动 skip
（不破坏 Windows 默认测试）。

### 5.3 WS3 hsrl2 可靠性升级

**引擎 API 硬化（阶段 A，默认行为逐位不变；`hsrl2/tests/test_engine_api_hardening.py` 57 项）**：

| 编号 | READINESS | 改动 | 价值 |
|---|---|---|---|
| F-22 | D-9 | `sell_minion` 非 Minion（Spell/None）→ False + 零状态改动 | 旧行为先加钱/移手牌再 AttributeError |
| F-23 | D-2 | `Game.unfreeze_tavern(hero)` + `tavern_frozen/unfrozen` 事件 | 环境可表达"解冻"动作 |
| F-24 | D-5 | `Game.elimination_order` / `rank_of()` / `final_ranking()` | 名次不再靠环境自建监听 |
| F-25 | D-3 | `quote_buy_cost` / `can_buy` / `can_use_hero_power` / `next_tavern_tier` / `magnetic_targets` / `can_refresh`（**与真实动作同源**，杜绝镜像漂移；免费额度 peek/consume 拆分） | 环境候选枚举不再复制引擎私有逻辑 |
| F-26 | D-14 | `Game.phase`（game_over > combat > choice > recruit） | 状态机可查询 |
| F-27 | D-8 | `CardDB.defs()/iter_defs()/hero_defs()` | 去掉对 `db._by_id` 的依赖 |
| F-28 | D-6 | `GameRNG(seed, audit=True)` + `clear_decisions()` | RL 大批量可关闭审计（随机流不变） |
| F-29 | D-15 | 抑制深度改 `ContextVar`（线程隔离，语义不变） | 同进程多线程向量化不再被模块级状态排除 |
| F-30 | D-4/7/10/13 | 只补文档不改行为（错误风格契约/死字段/clone 外部解决/Hero id 由环境层防护） | 避免无证据行为改动 |

**规则修正（阶段 B；AutoTavern + 官方 wiki 双证据）**：

- **F-32 / AC-02**：`POOL_COPIES_BY_TIER[1]` 16→15（T2..T7 不变），新增
  `test_rules_constants_ac02_ac03.py`；影响三连/刷新概率。
- **F-33 / AC-03**：`BASE_UPGRADE_COSTS` → T2..T6 = 5/7/8/**11/11**、T7=10，
  行为级对拍（真实 upgrade 扣费）一致；影响中后期节奏。
- 回归适配：AC-02 改变随机抽取流后暴露 2 个**测试辅助**缺陷（MinionBait 用主
  `CardDef.race` 判纳迦漏计双类型；`test_consume_tavern` 固定 seed 依赖），
  已按类型身份集合语义/跨 seed 语义修正，断言语义不变（非脚本 bug）。

**调查裁定（不改行为）**：

- **F-34 / AC-01**：先攻平局规则（参照实现=高等级优先；wiki 现行=随机；
  中文攻略=高等级优先）二源冲突 → **CONVENTION_DIFF**；本地语料
  （`data/trajectories*`）无对手战团/先手字段，无决定性证据，保持现状。
- **F-35 / AC-04**：BG34_405 Relentless Deflector 可达伤害集合差异 → 400 局
  逐帧 + 白板控制实验证明**异常在 AT 侧带脚本卡**（替换为同属性白板后两引擎
  一致；HS 带卡/不带卡一致），非 hsrl2 引擎 bug → **DEFERRED（改判）**。

**引擎缺陷修复**：

- **F-31**：Red Volumizer（`BG34_170t`）`health > max_health`（aura 只抬当前
  血量、Red 的 health 钩子未叠加）→ 修复 + 6 例测试；结构不变量恢复。
- **F-36 / KNOWN-DET-1**：跨进程确定性缺陷——`pool_choose_one_{minion,spell}_ids()`
  返回 `frozenset[str]`，Bramble Tunneler / Fandral's Fortune 把迭代顺序直接
  喂 `rng.choice/sample`，不同 `PYTHONHASHSEED` 抽到不同卡（seed 4001 第
  129 步后分裂）。修复：候选喂 RNG 前 `sorted()`（均匀性不变）；新增
  **子进程 + 不同 PYTHONHASHSEED** 的回归测试；seed 4001–4006 双进程 trace
  完全一致。

**新门禁发现的真实缺陷（F-37）**：

- 新增的 `validate_env --check-invariants`（移植 AutoTavern `invariants.rs`）在
  8 人局扫描中发现 `hero[P*]: board=8 > 上限 7`（seed 5019 等，60 局复现 5 处，
  系统性缺陷）。
- 根因：`hsrl2/game.py::_process_death_inner` 的 Reborn 分支直接
  `hero.board.insert(...)`，未检查棋盘容量；Activate 摧毁带 Reborn 随从后，
  亡语召唤把空位填满（7），Reborn 仍插入 → 8。
- 参照证据：AutoTavern `engine.rs::reborn` 通过 `self.summon(side, pos, m)`
  返回复生体（满盘召唤失败 → 不返回、不 emit Reborn，非战斗回池），且
  `invariants.rs` 硬约束 board≤7。
- 修复：Reborn 满盘不返回（不 fire `reborn`、REBORN tag 清理/进墓地/监听器注销/
  非战斗回池），未满局面行为逐位不变；新增
  `hsrl2/tests/test_reborn_board_cap_f37.py`（3 例，先红后绿）。
- 验证：`validate_env --games 60 --check-invariants` → 0 违反；
  engine **4890 passed / 6 skipped / 0 failed**；project **667 passed /
  62 skipped / 0 failed**（最终冻结树）；smoke crashes=0；确定性 20/20
  （仅满盘异常路径改变）。

**验证（引擎/项目）**：`pytest hsrl2/tests -q` → **4890 passed / 6 skipped /
0 failed**（基线 4816 + 74 新增）；`pytest tests -q` 0 failed；smoke 8 局
crashes=0；`final_engine_stress` 确定性 20/20；`grep -rn "import random"
hsrl2/` 仍仅 `rng.py` 本体。

### 5.4 WS4 TavernBench 接入与工程可移植性

**TavernBench**：

- `benchmarks/tavernbench/`（39 文件 / 13MB，vendored 自 AutoTavern commit
  `fb61201`，MIT）：960 任务 / 40 场景 / 8 类别 / 720 状态 / 288 评测子集，
  12+5 个已发布系统答案、评分代码与 golden 报告；`diff -r` 与上游无差异；
- `scripts/run_tavernbench.py`（692 行）：`--check` 完整性+评分复现、
  `--systems/--set/--runs/--json/--upstream/--list-systems`，根目录可跑；
- `tests/test_tavernbench.py`（11 项）：960/368/40/8 统计、labels/答案覆盖、
  golden 逐项复现、`--check` 正/负路径、CLI、可选上游现场对拍；
- `docs/TAVERNBENCH.md`：数据结构/评分口径/复现/自定义答案提交/与 RL 边界。

**验证**：`python3 scripts/run_tavernbench.py --check` → **26/26 PASS**（0.87s）；
`--upstream <AutoTavern>` → 27/27，输出表与上游逐字节一致。

**工程可移植性**：

- `tests/conftest.py`：按精确 node id 对「缺失 `runs/` checkpoint」5 条与
  「WindowsPath 语义」1 条先决条件 skip（Windows 上恒不触发）；
- `tests/test_live_clickbot.py`：非 Windows 模块级 skip（修复 collection error）；
- `docs/PORTABILITY.md`：修复前后基线 + skip 登记 + Windows 不变性论证。

**验证**：macOS 修复前 `pytest tests` 收集中断（`ctypes.windll`）+ 6 failed；
修复后 0 failed（升级过程中 638 passed / 62 skipped；最终冻结树
**667 passed / 62 skipped / 0 failed**，见 §8）。

### 5.5 WS5 环境层升级

**文件**：`hsbg/env/snapshot.py`（1546 行）、`hsbg/env/invariants.py`（1105 行）、
`tests/test_env_snapshot.py`（12 项）、`tests/test_env_invariants.py`（7 项）、
`tests/test_env_determinism_hashseed.py`（7 项，WS7 环境级跨进程回归）、
`docs/ENV_SNAPSHOT.md`（412 行）、`scripts/validate_env.py --check-invariants`。

**环境精确存档/恢复（`hsbg.env.snapshot`）**：

- `snapshot(env)` / `restore(env, snap, verify=True)` / `clone_env(env)` /
  `canonical_observation(obs)`；
- 覆盖：引擎全状态（`planning.clone`，含 RNG/PendingChoice 闭包重绑/
  pending_hand_queue/deferred_actions/池/战斗记忆）、名次账本（按 hero uuid
  重建）、大厅视图与 `game.heroes` 的**别名关系**、env 事件监听重绑（含
  "幽灵 env" 扫描双保险）、全部计数器/统计/选择留痕，并重建 obs/候选；
- 语义验收：`restore` 后与不 snapshot 的原轨迹**逐步观测/奖励/info 一致**
  （12 项测试，覆盖 T1/T5/T10 与淘汰/终局边界）；快照不改变原 env；同一
  快照可重复恢复；终止/非稳态/跨构造配置明确抛 `SnapshotError`；
- 实测开销：snapshot/restore = T1 4.2/6.1ms、T5 10.5/15.1ms、
  T10 17.7/24.2ms（`verify=True`；`verify=False` 全回合 <20ms；T10 的
  verify 开销主要来自两次 `state_digest`）。

**结构不变量（`hsbg.env.invariants`，移植 AutoTavern `invariants.rs`）**：

- `check_game` / `check_env` / `state_digest`：棋盘/手牌/酒馆容量、tier/
  金币/血量、随从属性（atk≥0、hp≤max_hp）、实体唯一性、名次合法性、
  候选/观测一致性；只读、不消耗 RNG、不触发事件、不崩；
- **不移植池守恒**（HSBRSIM 规则允许效果生成副本不占池；改为池簿记合法性
  弱检查，理由写入模块文档）；已知偏差用 `strict_tavern_slots` /
  `strict_unique_ranks` 显式开关（默认不误报）；
- 实测：20 局随机/启发式对局 0 违反（F-31 修复后）；接入
  `python scripts/validate_env.py --games 20 --check-invariants`。

**精确动作掩码验收**：新增测试证明 `env.legal_actions()` 的每个候选都能被
引擎接受并推进状态（clone 隔离尝试，不污染主局）、`action_mask()` 与候选
长度/顺序一致，与 AutoTavern「mask 内动作都被 apply 接受」契约等价。

**跨进程确定性（WS7）**：`tests/test_env_determinism_hashseed.py` 用子进程
（PYTHONHASHSEED=0/1）跑固定 rollout 比指纹；修复前 seed=2/3 + random 对手
稳定分裂，F-36 三处 `sorted()` 修复后 **7 passed（7s）**；该 gate 已纳入
`verify_all --fast`（`hashseed_determinism`）。

---

## 6. 使用指南

### 6.1 安装 TavernGym（可选后端）

TavernGym 未发布到 PyPI，需要从 AutoTavern 源码构建（Rust 1.98 + maturin，
`pyproject.toml` 已声明 `build-backend = "maturin"`；PyO3 构建 abi3 wheel）：

```bash
# 1) 安装 Rust 工具链（一次即可；rust-toolchain.toml 会自动装 1.98.x）
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"          # Windows: %USERPROFILE%\.cargo\bin 加入 PATH

# 2) 构建并安装 Python 绑定（在 AutoTavern 仓库根目录）
git clone https://github.com/MCG-NJU/AutoTavern.git
cd AutoTavern
python -m pip install -e .         # maturin 构建 Rust 扩展（首次约 3-6 分钟）

# 3) 校验
python -c "import taverngym; print(taverngym.version(), taverngym.game_version())"
# 期望: 1.0.0 36.6.3.253932
```

**验证基线（本机 macOS Apple Silicon / Python 3.12 实测）**：
`python -m pytest tests -q` → 46 passed；`cargo test --release` → **858 passed**
（含 `mechanics.rs` 415 项）；单局 8 人 bot 对局约 **16 ms**。
Windows 上用 `rustup-init.exe` 或在 Git Bash 执行同一脚本；若公司网络限制
Rust 下载，可先在能联网的机器 `maturin build --release` 出 wheel 后拷贝安装。
不安装时 HSBRSIM 默认流程完全不受影响（`taverngym` 相关测试自动 skip）。

### 6.2 切换后端

```python
from hsbg.rl.envs import make_env
from hsbg.backends import TavernGymEnv      # 直接构造亦可

# 默认（HSBRSIM hsrl2 引擎，37.0.0）
env = make_env(backend="hsrl2", seed=42, num_players=8)
# 等价历史默认：make_env() / make_env(backend="real") / make_env(backend="auto")

# 参照后端（AutoTavern TavernGym，36.6.3；需已安装 taverngym）
env = make_env(backend="taverngym", seed=42,
               env_kwargs={"obs_source": "features"})   # 或 "view"
obs = env.reset(seed=42)
obs, reward, terminated, truncated, info = env.step(obs.candidates[0])

# 采样/评测 CLI
# python -m hsbg.rl.collector --policy random --envs 1 --episodes 2 \
#     --backend taverngym --out runs/rl/tg.jsonl
# python -m hsbg.rl.evaluate --policy random --episodes 1 --backend taverngym
```

注意：TavernGym 后端返回的 `info` 含 `backend="taverngym"`、`rank`、`invalid`、
原始 245 维 mask；候选数可能超过 `spec.CANDIDATE_MAX=64`，**不要**与 hsrl2
数据混训/直接对比（版本 36.6.3 vs 37.0.0）。`teacher` 类引擎感知策略对该后端
明确报错。详见 `docs/TAVERNGYM_BACKEND.md` + `docs/RL_INTERFACE.md` §11。

### 6.3 跨引擎对拍

```bash
# 全量套件（pytest；需 taverngym，缺失自动 skip）
python -m pytest tests/conformance -q

# 分类报告（JSON 落 runs/conformance/report.json；57 场景）
python -m tools.ac_conformance.run --seeds 48
# 单项最小复现
python -m tools.ac_conformance.repro AC-02

# 数据差异（卡牌/池/规则常量）
python -m tools.ac_conformance.data_diff
```

台账与口径见 `docs/CONFORMANCE_AUTOTAVERN.md`；分类：MATCH /
CONVENTION_DIFF（约定差异，如 RNG 顺序、先攻平局规则冲突）/ ENGINE_BUG /
DATA_GAP / UNSUPPORTED。改动引擎机制后，若套件与台账 expected 不一致，必须
复核台账并按证据更新（不是放宽断言）。

### 6.4 TavernBench 评测

```bash
# 数据完整性 + 已发布答案评分复现（离线，纯标准库；26 项检查）
python scripts/run_tavernbench.py --check

# 评分主表（12 个已发布系统 × 40 场景；可 --systems 过滤、--json 落盘）
python scripts/run_tavernbench.py --systems tavernagent,gpt-6-astra,claude-opus-5.5,jev

# 可选：与 AutoTavern 原仓库现场对拍
python scripts/run_tavernbench.py --check --upstream /path/to/AutoTavern/tavernbench
```

主表关键值（与上游一致）：tavernagent play 0.91 / rule 1.00；gpt-6-astra
0.63 / 0.95；claude-opus-5.5 0.52 / 0.925；jev 0.37 / 0.35。
TavernBench 是 **LLM/agent 单步决策基准**，与 HSBRSIM 的 self-play 名次评测
互补但不互相替代（边界见 `docs/TAVERNBENCH.md` §7）。

### 6.5 环境快照/恢复与不变量

```python
from hsbg.env import BattlegroundsEnv
from hsbg.env.snapshot import snapshot, restore, clone_env
from hsbg.env.invariants import check_env, check_game, state_digest

env = BattlegroundsEnv(seed=42); obs = env.reset(seed=42)
snap = snapshot(env)                 # 保存（不改变 env）
for _ in range(10):                  # 任意推进
    obs, r, term, trunc, info = env.step(obs.candidates[0])
    if term: break
restore(env, snap)                   # 原地恢复：obs/候选/RNG/统计逐位一致
twin = clone_env(env)                # 独立副本（搜索/分支用）

violations = check_env(env)          # 结构不变量（只读；空列表=通过）
print(state_digest(env.game))        # 跨进程稳定的状态摘要（对拍用）
```

验收/复现：

```bash
python -m pytest tests/test_env_snapshot.py tests/test_env_invariants.py -q
python scripts/validate_env.py --games 20 --check-invariants   # 默认关闭的抽查开关
```

限制：快照仅对决策步稳态、未终止、同构造配置有效；对手策略内部状态/策略
外部 RNG 不在快照内；酒馆展示位可超过 `spec.TAVERN_MAX`、同回合多名淘汰者
名次并列属已登记偏差（详见 `docs/ENV_SNAPSHOT.md`）。

---

## 7. 版本差异、迁移边界与不可比项

| 项目 | 36.6.3（AutoTavern） | 37.0.0（HSBRSIM） | 影响 |
|------|---------------------|-------------------|------|
| 卡池 | 244 池内随从 | 273 池内随从 | 逐卡对拍只对「两版本都存在且文本/数值未变」的卡有效 |
| 新种族 | — | ABERRATION(126) | TavernGym 无 Deity/Aberration 机制 |
| 时空扭曲 | 253 卡实现 | 无 | 该机制不可比 |
| 动作空间 | 245 固定动作 | 动态候选 | 策略/价值网络**不可直接迁移**；后端适配仅用于数据/评测/对照 |
| 观测编码 | 3227+124 | 实体 token | 同上 |
| 数据源 | content pack（未分发） | 官方 CardDefs 37.0.0 | 数值差异需按版本区分 |

**对拍口径**：优先机制级（与卡池无关的规则），其次对共享且未变化的卡；
两引擎 RNG/事件顺序属约定差异，不作为 bug。

---

## 8. 验收证据

> 全部命令在本机 macOS（Apple Silicon，Python 3.12.2，taverngym 1.0.0 release）
> 实际执行；测试通过数不写死在代码/docstring 中，以最后一轮实测为准。

**最终冻结工作树的一键门禁**（`python3 scripts/verify_all.py`，
2026-10-26 11:55，macOS / Python 3.12.2；JSON 产物 `runs/verify_all_final3.json`）：
**10/10 gates PASS，118.0s，0 failed**：

| gate | 实测 |
|---|---|
| engine_tests | **4890 passed / 6 skipped / 0 failed**（26.8s） |
| project_tests | **667 passed / 62 skipped / 0 failed**（55.5s） |
| smoke_8p | games=8 completed=8 incomplete=0 **crashes=0** |
| env_validation | **ok=true，failures=[]**（含 `--check-invariants`，20 局 0 违反） |
| env_bench | 0 errors / 0 invalid（20 seeds） |
| hashseed_determinism | **7 passed**（双 PYTHONHASHSEED 子进程，6.9s） |
| official_consistency | 无语料机器自动 SKIP（本机 0.0s；不误红） |
| version_check | 四信号成功（数据仍 37.0.0.255130） |
| taverngym_conformance | **13 passed**（58 场景，2.5s） |
| tavernbench_check | **CHECK PASSED 26/26** |

**专项证据**：

| # | 命令 | 结果 |
|---|---|---|
| 1 | `python3 -m pytest tests/conformance -q` | 13 passed（MATCH 55 / CONVENTION_DIFF 2 / ENGINE_BUG 0 / UNSUPPORTED 1） |
| 2 | `python3 -m tools.ac_conformance.run --seeds 48` | 58 场景；`repro` AC-01 CONVENTION_DIFF / AC-02/03 MATCH / AC-04 CONVENTION_DIFF（含白板对照） |
| 3 | `python3 scripts/run_tavernbench.py --check` | **26/26 PASS**（0.87s）；`--upstream` 27/27，输出与上游逐字节一致 |
| 4 | `python3 -m pytest tests/test_backend_taverngym.py -q` | 42 passed（0.9s） |
| 5 | `python3 -m pytest tests/test_env_snapshot.py tests/test_env_invariants.py -q` | **23 passed**（3.8s） |
| 6 | `python3 tools/smoke_random_games.py --games 8 --seed 2000` | crashes=0 |
| 7 | `python3 tools/final_engine_stress.py --det-cases 20` | determinism identical=20/20（digest 稳定） |
| 8 | `PYTHONHASHSEED=0/1` 双进程 rollout（seed 4001–4006） | trace_sha256 完全一致（F-36） |
| 9 | `python3 scripts/validate_env.py --games 20/60 --check-invariants` | ok=true，0 违反（F-37 修复后） |
| 10 | AutoTavern 侧：`cargo test --release` | **858 passed / 0 failed**（参照实现自证） |
| 11 | AutoTavern 侧：`python3 -m pytest tests -q` | 46 passed |

双后端吞吐（同一 harness，本机）：hsrl2 6.52 games/s、3.89 ms/步；
TavernGym（features）33.88 games/s、0.356 ms/步（5.2× / 10.9×）；
TavernGym 引擎裸吞吐 275.5 games/s（§3.4）。

---

## 9. 限制与后续路线

### 9.1 本次升级不消除的边界

1. **版本差异（36.6.3 vs 37.0.0）**：TavernGym 是 36.6.3，HSBRSIM 是 37.0.0。
   跨引擎对拍只对「两版本都存在且行为未变」的卡/机制有效；TavernGym 后端
   定位为**参照/评测**，不与 hsrl2 产出的训练数据混用，策略/观测/动作空间
   不可直接迁移（详见 §7）。
2. **AC-01（先攻平局）未决**：参照实现=高等级优先，官方 wiki 现行文本=随机，
   中文攻略=高等级优先；本批在本地真实语料（`data/trajectories*` 等）中未找到
   「同数量不同等级且可判定先手」的样本 → 保持 hsrl2 现状并登记
   CONVENTION_DIFF。决定性证据需要 Power.log/HDT 原始战斗事件。
3. **AC-04（BG34_405）改判 DEFERRED**：控制实验证据指向**参照引擎侧脚本行为
   异常**（同属性白板替换后两引擎一致；AT 带脚本 405 时分布改变），非 hsrl2
   引擎 bug；如需与 AT 逐位对齐，需其维护者确认该卡 flags/DS 行为。
4. **OBS-GAP-1（酒馆展示位 > 7）**：合法机制可出现 8 槽酒馆（7 随从+1 法术或
   额外展示位），而 `spec.TAVERN_MAX=7` 且策略 encoder 的 slot=7 返回 -1 →
   第 8 槽在策略输入中静默丢失（obs 不截断、动作仍可选）。修复需 obs v4 +
   更新 checkpoint/重训，本批只登记（`docs/ENV_SNAPSHOT.md` §5.1，附构造性复现）。
5. **OBS-DET-1（观测含随机 uuid 派生字段）**：引擎 `Entity.uuid = uuid.uuid4()`
   （不来自 `game.rng`），观测 `EntityToken.entity_id`、`extra["minion_flags"]`
   键与部分 `PendingChoice.kind` 内嵌该 uuid → 同 seed 两次 rollout / 快照恢复后
   的**原始 obs 不可逐位比较**（新建实体不同）；动作/奖励不受影响（引擎决策与
   策略 encoder 不读 uuid）。`hsbg.env.snapshot.canonical_observation` 提供归一化
   （快照测试使用）；根治需 obs v4 + 引擎确定性 uuid，本批不改（§5.4）。
6. **名次并列**：环境口径 `rank = 淘汰时存活人数+1` 会让同回合多名淘汰者并列
   （AutoTavern 约定为按 Health+Armor 再按座位唯一化，但未找到官方裁决文本）；
   本批保持现状并在不变量里用 `strict_unique_ranks` 开关登记，不擅自改奖励口径。
7. **F-36 修复三条实测路径**（最终版）：其它脚本若把 `frozenset`/`set` 迭代结果直接喂
   RNG 仍有同类风险；建议把「子进程 + 双 PYTHONHASHSEED 跑多 seed 完整 rollout」
   纳入慢速 CI/发版检查（`runs/env_snapshot/hashseed_repro.py` 可复用）。
8. **环境快照限制**：对手策略实例内部状态不重建（默认启发式按 turn 懒重置，
   无跨回合状态；自定义有状态对手不在契约内）；仅决策步稳态、未终止、同构造
   配置有效；策略外部 RNG/采样器状态由调用方管理。
9. **TavernGym 观测是 Python 侧解码**（features ~175µs/步），是端到端吞吐瓶颈；
   若要把它用作训练级后端，需把编码下沉 Rust 或改用 `BatchEnv`（本批未做）。
10. **TavernBench 是 LLM/agent 单步决策基准**，不替代 self-play 名次/胜率评测；
   states 为 taverngym 36.6.3 JSON，与 hsrl2 37.0.0 不通用。

### 9.2 既有已知缺口（非本次升级引入，沿用原台账）

- 37 张 37.x 新池随从无效果脚本（官方差分分歧主因）；4 个 DEFERRED Dark Gift；
  动态 `SCRIPT_DATA_NUM` tag 撞号待建模（见 `docs/EXACTNESS_STATUS.md`）。
- `tools/probe_api.py` 中 A5（F-21 PendingChoice 一次性语义导致的既有 probe
  崩溃）与 A7（金色本体既有数据期值）为本次之前既有过期项。
- 开发机 `runs/` checkpoint 未入库导致 5 条搜索/价值测试自动 skip（Windows
  开发机有 checkpoint 时照常执行）；PPO 在稀疏奖励下未稳定超过 BC（训练暂停）。
- 价值网络训练分布未对齐真实对局（见 `docs/WARBAND_VALUE_NETWORK.md`）。

### 9.3 后续路线（建议优先级）

1. **真实对局语料补证**：用 Power.log/HDT 补 AC-01（先攻平局）、AC-04
   （405 卡）与观测缺口（OBS-GAP-1）的决定性证据；数据允许时把 TavernGym
   自身升级到 37.x 后重跑 conformance（预期出现新的 DATA_GAP/机制差异）。
2. **obs v4 + 固定动作空间 profile**：借鉴 TavernGym 的 245 动作 + 精确 mask
   与块布局观测，作为与现有候选动作接口并存的「训练 profile」；解决 OBS-GAP-1
   并评估策略迁移收益（需重训）。
3. **TavernGym BatchEnv 封装**（GIL 释放/多线程）作为可选训练/搜索后端，
   把小规模自对弈与搜索吞吐提升一个量级。
4. **对拍 CI 化**：`tests/conformance` + F-36 双哈希进程慢检纳入可选 CI job
   （无 taverngym 的机器自动 SKIP）。
5. **引擎 API 迁移**：把 `hsbg/env/driver.py` 的镜像逻辑迁移到 F-25 只读 API
   （消除双实现漂移风险；需在 env 用例全绿前提下分步做）。

---

## 10. 参考

- AutoTavern 仓库：<https://github.com/MCG-NJU/AutoTavern>
  - `docs/ARCHITECTURE.md`（引擎结构/确定性/存档/不变量）
  - `docs/TAVERNGYM.md`（Python API/动作空间/观测/速度）
  - `docs/CONTENT.md`（内容覆盖）
  - `crates/taverngym/src/invariants.rs`（结构不变量）
  - `crates/taverngym/tests/mechanics.rs`（机制测试，对拍参照）
- AutoTavern 论文：*Build, Don't Play: Self-Improving LLM Research Agents
  Develop a Hearthstone Battlegrounds AI That Rivals Top Players*（2026）
- 官方规则证据（AC-02/03 的独立来源，2026-10-26 抓取）：
  [Hearthstone Wiki — Battlegrounds](https://hearthstone.wiki.gg/wiki/Battlegrounds)
  （副本表 T1=15；升级费 T2..T6 = 5/7/8/11/11；Combat Phase 先攻描述）
- 第三方攻略（AC-01 的冲突来源，2020）：
  [炉石传说酒馆战棋先攻判定](https://www.gamedog.cn/ls/gl2901130.html)
  （“随从一样多则酒馆等级高的先攻击”，与 wiki 现行文本冲突，故未采纳）
- HSBRSIM 内部文档：`docs/ENGINE_API.md`、`docs/ENGINE_RL_READINESS.md`、
  `docs/EXACTNESS_STATUS.md`、`docs/DIFF_HARNESS.md`
