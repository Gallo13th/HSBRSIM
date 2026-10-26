# FORK.md — HSbg Engine：TavernGym 的 vendored fork

本目录（`rust/`）是 HSBRSIM **第二阶段的主模拟引擎**：把 AutoTavern 的 Rust 引擎
TavernGym（v1.0.0）vendor 进本仓库，重命名为 `hsbg_engine`，作为后续训练/评测的
默认引擎。**公开 API 与行为与上游逐位一致，只改包名/模块名**（例外见 §4、§9，
全部是构建或元数据层面，不改变引擎行为）。

- 架构/安装/用法/基准的中文总览：**[../docs/RUST_ENGINE.md](../docs/RUST_ENGINE.md)**
- 上游只读参照仓库：`/Users/letiangao/HSAgent/repos/AutoTavern`；上游文档
  `docs/ARCHITECTURE.md`、`docs/TAVERNGYM.md` 仍是机制/架构的第一手参考。

---

## 1. 上游来源与许可归因

| 项 | 值 |
|---|---|
| 上游项目 | AutoTavern（TavernGym + TavernBench） |
| 上游仓库 | https://github.com/MCG-NJU/AutoTavern |
| 上游版本 | TavernGym v1.0.0（`Cargo.toml` workspace `version = "1.0.0"`） |
| 上游 commit | `fb61201a557ddd36a411cf44aac51ce4d9b606ce`（`TavernGym and TavernBench v1.0.0`） |
| 引擎数据 | vendor 时：上游 `36.6.3.253932` / server rules `36.6.3`；**2026-10-26 已由 Lead 集成为 `37.0.0.255130`**（见 §5.1） |
| 许可 | **MIT**（Copyright (c) 2026 The AutoTavern Authors） |
| 归因文件 | 本目录 `LICENSE`、`NOTICE`、`CITATION.cff` 均从上游原样复制 |
| vendor 日期 | 2026-10-26 |
| 本 fork 的上游同步基线 | 上面这个 commit（不跟踪上游后续改动，升级流程见 §6） |

`NOTICE` 里包含上游对第三方游戏内容的声明（Hearthstone/炉石传说与 Blizzard
Entertainment 的商标与游戏数据归 Blizzard 所有；本项目是非商业研究项目，不发行
游戏客户端资源，不连接 Blizzard 服务）。本 fork 保留该声明；`cards.json` 中的卡名、
数值、文本仍属 Blizzard，仅用于规则模拟研究。

引用上游时请按 `CITATION.cff` 引用 AutoTavern 论文（见该文件 `preferred-citation`）。

---

## 2. 目录结构

```
rust/
├── Cargo.toml                 # workspace（members 两个 crate；release profile 与上游逐项一致）
├── Cargo.lock                 # 上游 lockfile，重命名 + 版本 pin 保持一致
├── rust-toolchain.toml        # 固定 Rust 1.98.1（上游原样）
├── rustfmt.toml               # 上游原样（max_width=100）
├── pyproject.toml             # maturin 构建配置（project name hsbg-engine）
├── LICENSE / NOTICE / CITATION.cff   # 上游许可与归因（原样）
├── README.md                  # 本 fork 的入口说明
├── FORK.md                    # 本文
├── bench_engine.py            # 可复现基准（裸吞吐/端到端/SoloEnv/BatchEnv）
├── crates/
│   ├── hsbg-engine/           # ← 上游 crates/taverngym（纯 Rust 引擎）
│   │   ├── Cargo.toml         #   package name = "hsbg-engine"，lib name = hsbg_engine
│   │   ├── data/cards.json    #   卡牌数据（编译期 include_str!；当前 37.0.0.255130）
│   │   ├── src/               #   81 个 .rs，约 4.47 万行
│   │   ├── examples/          #   bench / fuzz / play / stress / content_report
│   │   └── tests/             #   35 个 .rs（上游机制/内容回归，858 tests 量级）
│   └── hsbg-engine-py/        # ← 上游 crates/taverngym-py（PyO3 绑定，cdylib _core）
├── python/
│   └── hsbg_engine/           # ← 上游 python/taverngym（numpy 包装层）
│       ├── __init__.py        #   Game/SoloEnv/BatchEnv/action_name/layout/... + data_info()
│       ├── env.py             #   BattlegroundsEnv（Gym 风格单座环境）
│       └── batch.py           #   BatchEnv（多局并行，numpy 数组视图）
└── target/                    # 构建产物（.gitignore 忽略，体积大，勿入库）
```

---

## 3. 重命名映射（rename mapping）

| 上游 | 本 fork | 说明 |
|---|---|---|
| `crates/taverngym/` | `crates/hsbg-engine/` | 目录 |
| crate `taverngym` | crate `hsbg-engine`（lib `hsbg_engine`） | Cargo package `hsbg-engine`，Rust 路径 `hsbg_engine::` |
| `crates/taverngym-py/` | `crates/hsbg-engine-py/` | 目录 |
| crate `taverngym-py` | crate `hsbg-engine-py` | `[lib] name = "_core"` 不变 |
| Python 包 `python/taverngym/` | `python/hsbg_engine/` | 目录 |
| Python 模块 `taverngym` | `hsbg_engine` | import 名 |
| maturin `module-name = "taverngym._core"` | `hsbg_engine._core` | 扩展仍是 `_core.abi3.so` |
| pip 项目名 `taverngym` | `hsbg-engine` | `pyproject.toml [project].name` |
| build 脚本环境变量 `TAVERNGYM_SOURCE_HASH/PROFILE` | `HSBG_ENGINE_SOURCE_HASH/PROFILE` | 仅构建期内部使用 |
| 崩溃保护目录环境变量 `TAVERNGYM_GUARD_DIR` | `HSBG_ENGINE_GUARD_DIR` | 运行时可选开关（`src/guard.rs`） |
| `use taverngym::...` / `taverngym::debug::...` | `use hsbg_engine::...` | 所有 examples/tests/bindings 同步 |
| `cargo run -p taverngym --example X` | `cargo run -p hsbg-engine --example X` | 文档/注释同步 |

**逐位（bit-for-bit）保持不变**（= 公开 API/行为契约，迁移策略/旧脚本只需改 import 名）：

- Rust 公开 API：`Game`、`SoloEnv`、`BatchEnv`、`RulesConfig`、`Action`/`N_ACTIONS`、
  `Observation`/`OBS_FLOATS`/`OBS_CARDS`、`debug`、`bot`、`rules` 及全部模块路径
  （除 crate 根名）；`VERSION == "1.0.0"`。
- PyO3 API：`Game`、`SoloEnv`、`BatchEnv` 的全部方法与签名、`run_bot_games`、
  `action_name`、`card_info`、`card_static`、`catalog_json`、`default_config_json`、
  `layout`、`version`、`game_version`、`server_rules_version`、`build_info`、
  `N_ACTIONS=245`、`OBS_FLOATS=3227`、`OBS_CARDS=124`、`N_CARDS`（=卡数+1）。
- 动作空间 245 维布局、观测 3227 floats + 124 card 下标布局、`state_json` schema、
  seed→RNG 的确定性、BatchEnv 并行语义一律不变。
- 本机实测：同数据版本下，两边全 bot 对局的 `state_json` **字节相等**、
  `run_bot_games` 终局回合相同（见 §10）。

重命名是**纯文本替换**（crate 名/目录名/模块名），已核对：除 §4 列出的代码改动、
新增文件和一次 `cargo fmt` 重排（§4 #10，纯空白）外，其余 `.rs`/`.py` 文件在
“把上游文本按上表替换后”与 fork 内容完全相同。

---

## 4. 相对上游的代码改动（除重命名外，全部有据可查）

| # | 文件 | 改动 | 动机 | 行为影响 |
|---|---|---|---|---|
| 1 | `crates/hsbg-engine/src/lib.rs` | `GAME_VERSION`/`SERVER_RULES_VERSION` 常量保留为 **fallback**；新增 `pub fn game_version()` / `server_rules_version()`，从 `cards.json` 的 `meta.client_version` / `meta.server_patch` 读取（数据为空时回落常量）；`#[cfg(test)] versions` 改为与数据 meta 一致性断言 | HSBRSIM 要把 36.6.3 数据替换成 37.0.0.255130，版本上报必须跟随数据而不是代码 | 36.6.3 数据下返回值与上游常量完全相同（无行为差异）；换数据后自动跟随（见 §5） |
| 2 | `crates/hsbg-engine/src/cards.rs` | `RawDb.meta` 与 `RawMeta.{client_version,server_patch}` 加 `#[serde(default)]`（`RawMeta: Default`）；`loads_and_links_golden` 测试改断言与 `game_version()`/`server_rules_version()` 一致 | 数据替换任务可能写出缺 meta 的 JSON；缺字段时应回落常量而不是解析 panic | 36.6.3 数据下无差异；缺 meta 的数据不再 panic |
| 3 | `crates/hsbg-engine/src/debug.rs` | `Game.view()` 调试 JSON 的 `"version"` 字段改用 `crate::game_version()` | 与 #1 一致 | 36.6.3 下字段值不变 |
| 4 | `crates/hsbg-engine-py/src/lib.rs` | `game_version()`/`server_rules_version()` 转发到引擎新函数；新增 fork 专属 `db_info() -> (card_count, client_version, server_patch)` 并注册进 `_core` | 同上；`db_info` 供集成时一行核对“当前二进制里的数据版本/卡数” | Python 侧 `game_version()` API 签名/返回值不变（36.6.3 下同上游）；`db_info` 是**新增**函数，不覆盖/不改变上游任何 API |
| 5 | `crates/hsbg-engine-py/build.rs` | 新增 macOS 专用链接参数 `cargo:rustc-cdylib-link-arg=-undefined` / `dynamic_lookup`（`#[cfg(target_os = "macos")]`） | 上游只通过 maturin 构建，纯 `cargo build --release` 在 macOS 上会因 `_Py*` 未定义符号链接失败。本 fork 要求 `cargo build --release` 可用 | **仅构建期**；maturin 构建时也兼容（参数重复无害）。运行时行为无差异 |
| 6 | `python/hsbg_engine/__init__.py` | 文档字符串改为 fork 说明；新增 `data_info()`（基于 `db_info()`，返回 `cards/game_version/server_rules_version/n_cards`）；新增 `HSBG_ENGINE_DB_INFO=1` 时 import 打印一次数据摘要；`ImportError` 提示改为 `pip install -e . (cd rust)` | 集成核对数据替换；改善可诊断性 | 默认 import 行为不变（不打印）；`__all__` 增加 `data_info`/`db_info`（超集） |
| 7 | `rust/Cargo.toml`、`rust/pyproject.toml`、`rust/README.md`、`rust/FORK.md`、`rust/bench_engine.py` | 新增 workspace 根清单、maturin 配置、fork 说明、基准脚本 | fork 目录布局/文档 | 无运行时影响 |
| 8 | `rust/Cargo.lock` | 上游 lockfile 的包名同步重命名（依赖版本 pin 不变） | 保证依赖版本与上游一致 | 无 |
| 9 | 仓库根 `.gitignore` | 追加 `rust/target/`、`rust/python/**/*.so`、`rust/**/__pycache__/` | `rust/target/` 约数 GB，不能入库 | 无 |
| 10 | 全树（4 个文件） | 跑一次 `cargo fmt`（rename 让 `hsbg_engine::` 比 `taverngym::` 长，个别上游行超过 `max_width=100` 被重排；主要是 `tests/mechanics.rs`、`tests/combat_analytics.rs` 与 §4 #1/#4 新增函数的排版） | 保持 `cargo fmt --check` 干净，后续改动不被格式噪声淹没 | **纯空白**，语义零变化；`cargo fmt --check` 现在通过 |

> 除上表外，**没有任何**规则/数值/动作/观测实现改动。阶段二“机制以 AutoTavern 为基准、
> 有误精修”的后续机制补丁请登记到 §7 的改动台账（并尽量同步上游）。

---

## 5. 数据文件与替换（37.0.0.255130）

### 5.1 位置与加载方式

- 数据文件：**`rust/crates/hsbg-engine/data/cards.json`**（注意不在仓库根 `data/`）。
- 编译期 `include_str!("../data/cards.json")` 嵌入（`src/cards.rs`），首次使用时
  `OnceLock` 解析成静态 `CardDb`；`CardId` 是卡表稠密下标，`CardDb.fingerprint`
  标识卡表（`state_json` 存档只对同一卡表有效）。
- **当前内容 = 37.0.0.255130 最终数据**（`gen_carddb_37.py` **v1.1.0**，2026-10-26
  由数据层修复任务产出并集成：源为 `data/p2/cards_37.json`，SHA-256
  `c482612727c2618e547479d743d40dad6ab4763cf1368e9742eb312ec4886dae`，
  1,741,330 字节；`meta.client_version=37.0.0.255130`、`meta.server_patch=37.0.0`）。
  v1.1.0 相对首版（v1.0.0，sha `4ba9cdf7…`）的关键修复：**AT 机制元数据继承**
  （`pool_tag`/`pools`/`reachable`/`lobby_req` 等按 36.6.3 AT 语义回填）+
  **Dark Paradox 5 形态映射**（`BG36_360t3/t4/t5/t6/t9` ↔ `BG36_360*` 单卡形态，
  修复 aberration/lobby 相关断言口径）。
  它是“37 官方映射 + 36.6.3 compat 条目”的并集，`data/p2/MANIFEST.json` 记录了
  映射/池计数（3695 mapped + 288 compat，单人池计数 **minion 277 / hero 118 /
  spell 73 / trinket 236**；277 含 Dark Paradox 5 个旧形态 compat 条目）。
- vendor 时的原始内容 = 上游 36.6.3 数据原样（SHA-256
  `429305fb9dd53e6c5240bf5219a747602e96d7a0e4bbd19a0d65b8b044ed6168`），已不再使用；
  逐位对拍证据见 §10.3（历史）。
- **换数据必须重新编译**：`cd rust && python3 -m pip install -e .`（或
  `maturin develop --release`），否则二进制里还是旧数据。

### 5.2 数据更新/替换步骤（模板；37.0.0.255130 已于 2026-10-26 执行完毕）

> 37.0.0.255130 的替换已经完成（见 §5.1/§5.5、`docs/DATA_37_MIGRATION.md`）。
> 下面是产线换数据的**固定步骤**（再换版本或重生成数据时照做）：

```bash
# 1) 用数据任务生成的 cards.json 覆盖（不要手改 JSON；生成器：tools/p2_data/gen_carddb_37.py）
cp data/p2/cards_37.json rust/crates/hsbg-engine/data/cards.json

# 2) 重建并重装（编译期 include，必须重建）
cd rust
cargo build --release                 # 可选：先确认 Rust 侧构建
python3 -m pip install -e .           # 重建 hsbg_engine 扩展

# 3) 核对版本/卡数（应显示 37.0.0.255130；当前已是）
HSBG_ENGINE_DB_INFO=1 python3 -c "import hsbg_engine"
python3 -c "import hsbg_engine; print(hsbg_engine.data_info())"

# 4) 冒烟 + 回归
python3 -c "import hsbg_engine; print(hsbg_engine.run_bot_games(2, seed=0))"
cd .. && python3 -m pytest tests/test_rust_engine.py -q

# 5) 跑 Rust 测试（注意：仍有一批 36.6.3 内容断言待按 37 数据重算，见 5.4/§10.2）
cd rust && cargo test --release -p hsbg-engine --lib
```

`meta` 结构要求（与上游一致，且现在对缺字段容错）：

```json
{"meta": {"client_version": "37.0.0.255130", "server_patch": "<37.x>"}, "cards": [ ... ]}
```

`game_version()`/`server_rules_version()`/`describe_db`（`db_info`/`data_info`）都读
这两个字段；任缺字段或为空时回落到源码常量 `36.6.3.253932` / `36.6.3`（fallback，
见 §4 #1/#2）。

### 5.3 ⚠ 缺失 card id 会在首次使用引擎时 panic（数据替换的硬约束）

上游 `src/script.rs::registry()` 对每个注册脚本执行 `db().id(id)`，而
`CardDb::id`（`src/cards.rs`）在卡表中找不到 id 时**直接 panic**：

```rust
pub fn id(&self, id: &str) -> CardId {
    self.find(id).expect(...)   // 实际实现：panic!("card id not in database: {id}")
}
```

`registry()` 是惰性 `OnceLock`，在**第一次用到脚本钩子**（第一局游戏 / 第一次
`observe`/`legal_mask`/`catalog_json` 等）时初始化；此外 `cardid!` 宏、`content/`
里的静态 id 表、`script::implemented` 等也大量使用 `db().id`。因此：

- **替换数据后若卡表缺少任何一个被脚本/内容代码引用的 card id，第一次使用引擎就会
  panic**（不是跑几局后才出问题）；
- 37.0.0.255130 数据必须生成 **“37 映射 + 36.6.3 compat 条目”的并集**（数据任务的
  职责），保证所有脚本引用的 id 都能解析；
- 快速自检：`HSBG_ENGINE_DB_INFO=1 python3 -c "import hsbg_engine"` +
  `run_bot_games(1)`；更严格的自检是 `cargo test --release -p hsbg-engine --lib`
  （`script.rs`/`cards.rs` 的 registry 测试会命中大量 id）。

### 5.4 数据相关的 Rust 测试（37 集成后已全部重算，0 failed）

上游 `cargo test` 的相当一部分用例是对 **36.6.3 卡池内容**的断言（池计数、卡面文本、
轮换出/回池等）。集成 37.0.0.255130 数据后，这些断言按 37 数据重算（**只改断言与注释，
不改引擎语义**）：

- **lib 单测**：`src/cards.rs::pool_counts_match_bundle` 更新为 37 口径
  **minion 277 / hero 118 / spell 73 / trinket 236**（`cargo test --lib` 15 passed）；
- **集成测试**（37 数据重算的 3 处，依据见 §10.2 与数据 MANIFEST）：
  1. `tests/mechanics.rs::pool_tag_rule_excludes_rot_hide_gnoll_by_default`：
     `eligible 244 → 276`（37 单人池 277，唯一 `pool_tag=2` 的是 BG25_013
     Rot Hide Gnoll；pool_tag 继承语义不变）；
  2. `tests/shown_minions_b.rs::gold_counters_show_the_gold_left`：
     卡面文本 `1 turns sooner → 1 turn sooner`（37 英文卡面修正了 36.6.3 的单复数；
     文本来自数据，引擎 `with_numbers` 只归一化括号内计数器）；
  3. `tests/validation.rs::t19_*`：由“Naga-only 全部出池（36.6.3）”改为
     “Naga 回池（37）”——断言池内 races 恰为 NAGA 的 20 张 + 双种族含 NAGA 的 2 张，
     依据 37 轮换与 `docs/PORTING_37_PLAN.md` §3.4/§4.1；
- 结果：全量 `cargo test --release -p hsbg-engine` = **36 套件 858 passed / 0 failed /
  0 ignored**（与 36.6.3 上游基线同数）；
- **不要**为了让测试变绿去改引擎行为或删测试（见仓库 AGENTS.md 门禁纪律）；
- `tests/test_rust_engine.py`（HSBRSIM 侧）只断言布局/确定性/往返/对局完整性，
  **不写死卡池内容**，37 数据下继续全绿（10 passed + 1 设计性 skip，见 §10.2）。

### 5.5 37 数据集成记录（2026-10-26，已完成）

37 数据分两步集成（均由 Lead/数据层完成，本 fork 侧只负责重建+验证）：

1. **首版**（12:55，`gen_carddb_37.py` v1.0.0，sha `4ba9cdf7…`）：37 映射 + compat 并集，
   引擎零改动即可跑（预演 + 正式验证见下）——但池计数为 minion 273（`pool_tag` 等
   AT 机制元数据未继承），导致 6 个内容断言失败。
2. **最终版**（v1.1.0，sha **`c4826127…`**）：补齐 **AT 机制元数据继承**
   （`pool_tag`/`pools`/`reachable`/`lobby_req`）与 **Dark Paradox 5 形态映射**，
   单人池计数变为 **minion 277 / hero 118 / spell 73 / trinket 236**。
   `src/cards.rs` 期望值随之为 277/118/73/236；剩余 3 个内容断言由 task-19 按 37
   数据重算（§5.4），全量 Rust 测试回到 **858 passed / 0 failed**。

**预演**：在 `/tmp` 隔离副本里先做过只读验证（37 数据替换 + 重建，未改仓库数据），
确认引擎代码无需改动即可跑 37 数据：

| 检查 | 结果 |
|---|---|
| `game_version()` / `server_rules_version()` | **37.0.0.255130 / 37.0.0**（meta 驱动生效） |
| `data_info()` | `cards=3983, n_cards=3984`（37 映射 3695 + 36.6.3 compat 288） |
| 动作/观测维度 | 245 / 3227 / 124 **不变** |
| `run_bot_games` / 8 人全 bot 对局 | 正常跑完、placements = 1..8 排列（**无 registry panic** → compat 覆盖脚本 id） |
| `state_json` 往返 / `BattlegroundsEnv` / `BatchEnv` | 全部正常（存档字节相等、0 rejected） |

**最终 37 数据下的池计数**（`pool_counts_match_bundle` 现期望值）：

| 池 | 36.6.3（vendor 基线，历史） | 37.0.0（当前，v1.1.0） |
|---|---:|---:|
| minion | 245 | **277**（含 Dark Paradox 5 个旧形态 compat 条目） |
| hero | 116 | **118** |
| spell | 70 | **73** |
| trinket | 236 | 236（不变） |

> 结论：**37 数据可直接替换**（引擎代码零改动，只有内容断言按新数据重算）；
> 换数据后必须重建（`cd rust && pip install -e .`），旧二进制/旧 `state_json` 存档
> 不能继续用（`CardDb.fingerprint` 校验）。最终数据下：pytest **10 passed + 1 skip**、
> Rust **858 passed / 0 failed**、基准见 §10.4。

---

## 6. 与上游同步（fork 策略）

**策略：pinned vendor + 最小 diff + 可重放重命名。**

- 不跟踪上游 master：fork 基线固定在 §1 的 commit；上游新版本由人工/任务显式升级。
- 优先把 fork 改动做成“可上游化”的小补丁（§4 #1/#2/#3/#5 都是候选），
  减少长期分叉成本；机制精修（有误精修）尽量附规则依据与测试，便于上游合并。
- 数据替换与上游同步**解耦**：数据只换 `data/cards.json`，引擎代码不动。

### 升级到新上游版本的步骤

```bash
# 1) 取上游新 commit（只读参照仓库）
cd /Users/letiangao/HSAgent/repos/AutoTavern && git fetch && git log --oneline -5

# 2) 重新 vendor 两个 crate + python 包（排除构建产物 __pycache__/*.so）
#    rsync/cp -R 后按 §3 映射做文本替换（也可用 git mv + sed）；保持 Cargo.lock 同步

# 3) 重放 §4 的 4 个代码改动（版本 meta 化、meta serde 容错、debug.version、
#    py 转发 + db_info、build.rs macOS link args、python 包装层 data_info）

# 4) 更新本文 §1（commit/版本/日期）、§5.1（数据 SHA-256）与 §10 验证记录
# 5) 重建 + 全量验证
cd rust && cargo build --release && python3 -m pip install -e .
cargo test --release -p hsbg-engine            # 上游测试量级 858+，见 §9
cd .. && python3 -m pytest tests/test_rust_engine.py -q
python3 rust/bench_engine.py --games 1000     # 与 §10 基准对比，确认性能没有回归
```

> 上游 `tests/` 与 `examples/` 也一并 vendor（含 `common/mod.rs`），保证 `cargo test`
> 可直接验证机制；`docs/` 没有 vendor，上游 `docs/ARCHITECTURE.md` / `TAVERNGYM.md` /
> `CONTENT.md` 继续在只读参照仓库里查阅。

---

## 7. HSBRSIM 改动台账（机制精修占位，“有误精修”从这里开始）

阶段二原则：**机制以 AutoTavern 为基准；发现错误/缺失时在本 fork 精修**。所有偏离
上游的机制改动必须登记下表（文件、改动、规则依据/证据等级、回归测试、是否已反馈上游），
并同步到 `docs/CONFORMANCE_AUTOTAVERN.md` 的 AC 台账（HSBRSIM 侧已有 57 场景对拍）。

| 日期 | 文件 | 改动 | 规则依据 / 证据 (E0–E4) | 回归测试 | 上游状态 |
|---|---|---|---|---|---|
| 2026-10-26 | `src/cards.rs::tests::pool_counts_match_bundle` | 断言期望值随 37 数据更新：245/116/70/236 → **277/118/73/236** | 数据内容（非机制）；依据 `data/p2/MANIFEST.json` 单人池口径（`gen_carddb_37.py` v1.1.0） | `cargo test --release -p hsbg-engine --lib`（15 passed） | 不适用（数据相关测试） |
| 2026-10-26 | `tests/mechanics.rs::pool_tag_rule_excludes_rot_hide_gnoll_by_default` | `eligible` 断言 244 → **276** | 37 数据口径：单人池 277，唯一 `pool_tag=2` 为 BG25_013（pool_tag 继承语义未变） | mechanics 套件 415 passed | 不适用（数据断言） |
| 2026-10-26 | `tests/shown_minions_b.rs::gold_counters_show_the_gold_left` | 文本 `1 turns sooner` → **`1 turn sooner`** | 37 卡面文本（数据驱动；引擎只归一化括号内计数器） | shown_minions_b 10 passed | 不适用（数据断言） |
| 2026-10-26 | `tests/validation.rs::t19_*` | 由“Naga-only 全部出池（36.6.3）”改为“Naga 回池（37）”：断言池内 NAGA-only 20 张 + 双种族 2 张 | 37 轮换（Naga 回池）；`docs/PORTING_37_PLAN.md` §3.4/§4.1 | validation 14 passed | 不适用（数据断言） |
| 2026-10-26（P3） | `src/flow.rs` 大厅类型 `optional` 列表 | 加入 **`Races::NAGA`**：36.6.3 轮换把 Naga 移出大厅类型（AT 原版只有 9 种），37.0.0 Naga 回池 → 恢复官方“10 种类型随机 5 种” | 证据：37 数据单人池 minion 277 含 20 张 Naga-only 与 2 张双种族含 Naga（`data/p2/MANIFEST.json` pools diff，32 张回池）；`docs/PORTING_37_PLAN.md` §3.4“Naga 回池”；37 官方大厅 10 种族；hsrl2 冻结参照同样有 Naga 大厅（E1：数据 + 官方轮换说明） | `tests/p3_systems.rs::naga_lobby_gates_naga_pool` + 全量 cargo test（见 §10.2） | 上游 36.6.3 未支持（版本差异，非 AT bug；可反馈） |
| 2026-10-26（P3） | `src/content/p3_systems.rs`（新增） | 37 内容移植：`BG22_HERO_007p` Queen Azshara 主技能（30 总攻 → 替换为 `BG22_HERO_007p2` Naga Conquest：池感知 Discover a Naga，1 费/每回合 1 次）；`warband_attack` 用 `Ctx::boards[side]`（与 `content::check_total_attack` 同口径） | 37 卡面文本（30 total Attack / Discover a Naga / cost 1）+ hsrl2 `batch_hero_combat3.py::AzsharaScript/NagaConquestScript` 数据链（E1：数据 + 参照实现） | `tests/p3_systems.rs` 6 个 Azshara 用例 | 新增内容（37 专属），上游无 |
| 2026-10-26（P3） | （**决策，不改代码**）`BG36_360` Dark Paradox | **保持 AT 5 形态机制**：`flow.rs::PARADOX_VARIANTS` 每局随机 1 个 `BG36_360t*` 入池。37 的“单卡每局随机 Dark Gift/属性/Tier”在可观察玩法上已被等价覆盖；单卡 id 动态化需 per-game `CardDef` override 贯穿 pool/shop/triple/obs/state_json，属高风险，P3 不做 | 证据：37 数据 base `BG36_360` = tier1/1/1 占位壳、`pools=[]`、无脚本；5 token 覆盖 Tier2..6 且各有脚本/golden（`tests/p3_systems.rs::dark_paradox_37_data_and_mapping_invariants` 固化）。差异仅为**表征**（token id vs base id）与“37 可能存在的更多形态数据缺失” | `tests/p3_systems.rs::dark_paradox_37_data_and_mapping_invariants`（200 seeds 不变式） | 决策记录；P3 后续项见下 |
| 2026-10-26（P3） | `tests/mechanics.rs` 7 例 + `tests/buddies_a.rs`/`tests/buddies_c.rs` fixtures 2 例 | 37 大厅（+NAGA）与 P3 内容入池导致固定 seed 的期望/夹具漂移：**不放宽断言**，按 37 数据重算期望或用与抽取无关的构造/夹具：①`extra_offers_apply...` seed 选择改用 fixture 同款 `aberration_forced` 配置 + Dragon 大厅；②`denathrius_quest...` 选含 MURLOC 大厅 seed（Reward 111 的 120% 类型修正）；③`trinket_avenge...` 选含 MECH 大厅 seed（随机 Magnetic 来自本局 universe）；④`boon_of_light...` 显式构造酒馆随从；⑤`a_reborn_creation...` 手工构造 Creation（避免随机抽卡的 Reborn 触发增益污染）；⑥`master_nguyen...` 对出现的 offer 严格断言排除项 + 要求至少一次（个别 seed 空 offer）；⑦`quest_reward_rules` 对手改为 1 攻/50 血靶子（不依赖战斗先手）；⑧buddies_a/c fixture 补 `skipping=false`（对齐 `tests/common/mod.rs`） | 37.0.0 数据 + 10 类大厅（Naga 回池）+ P3 内容入池（data/内容事实，非机制回退） | `cargo test --release -p hsbg-engine --no-fail-fast` → **39 套件 887 passed / 0 failed**（详见 §10.2） | 不适用（37 数据适配） |
| 2026-10-26（P4-M1） | 新增 `src/search.rs`（`lib.rs` 注册 `pub mod search;`）+ PyO3 `mcts_search`（`hsbg-engine-py/src/lib.rs`）+ `python/hsbg_engine/__init__.py` 导出 + `tests/search.rs` | **逐步 MCTS 搜索核（新增能力，默认行为不变）**：PUCT、节点持 `Game` clone、`apply_index`+`bot::play_turn` 推进对手、终局 `placement_utility=1-2*(placement-1)/(n-1)`、根 Dirichlet（自带 SplitMix64/Marsaglia-Tsang，seeded）、π=counts^(1/τ)、seeded 采样；`eval` 每节点首扩调用一次（总 ≤ sims+1）；Python `eval_fn(features,cards,mask,seat)->(policy,value)`，`None`=uniform+value0 fallback | 用户 P4 指令“搜索换成 Rust”（`docs/AZ_MCTS_SELFPLAY_DESIGN.md` D2/D10）；动作严格 245 | `--test search` **5 passed**、`--lib` **19 passed**、全量 **40 套件 896 passed / 0 failed**；Python stub 1 局 8 座（sims=1）：0.31 s/局、2241 次 search、0.105 ms/search 均值、evals/search=2.00 | 新增能力（AT 原版无搜索核；可反馈业务上游） |
| （占位，待阶段二机制精修任务填写） | | | | | |

**P3 大厅类型语义（`flow.rs::optional` / `RulesConfig`）**：

- 37.0.0 = **10 种类型**（Beast/Demon/Dragon/Elemental/Mech/Murloc/Naga/Pirate/
  Quilboar/Undead）随机 5 种；36.6.3 AT 原版 9 种（Naga 轮换出池）。
- `RulesConfig::lobby_types`：强制入大厅的类型名（`Races::NAMES`，含 `NAGA`）——测试
  可用 `lobby_types=["NAGA"]` 定向 Naga 大厅；语义不变（先占 `lobby_races` 名额、去重）。
- Aberration 仍是特殊位：`aberration_forced` 时先占 1 席；`optional` 末尾追加
  `Races::ABERRATION` 只在剩余名额 k>0 时参与抽样——Naga 加入 `optional` 不影响该逻辑。
- `lobby_races` 默认仍 5；`hero_fits` 的类型过滤（`assoc`/`lobby_req`）随大厅自然生效：
  Naga assoc 英雄（Azshara `BG22_HERO_007`、Lady Vashj `BG23_HERO_304`）只在含 Naga 的
  大厅进入英雄池。
- **回归影响**：固定 seed 的既有测试（`tests/mechanics.rs` 7 个、`tests/buddies_a/c`
  2 个 fixtures）因大厅抽样/池内容变化出现期望漂移；已按 37 数据重算/对齐（见 §10.2），
  未放宽断言。
- **全部 P3 内容合入后重新冻结 seed 基准（checklist）**——P3 会改变 `ContentMode::
  Implemented` 下的 pool/universe 抽样，任何“固定 seed + 绝对期望”的测试/评测都会漂移：
  1. **37 Naga 回池**：`flow.rs::optional` 大厅类型 9→10 类（本文件 §7 首行，已记）；
  2. **P3 内容入池**：批次 A 9 张（`p3_batch_a.rs`）+ 批次 B 8 张（`p3_batch_b.rs`：
     6 池内随从 `BG33_319/BG34_925/BG35_921/BG36_508/BG36_622/BG36_921` + 2 池内法术
     `BG32_815/BG35_922`）+ 系统项（Azshara/Dark Paradox）——新注册脚本的池卡进入
     universe/全池抽样；
  3. 重冻结时同步重跑 `python3 tools/p3_verify/run_all.py`（oracle/coverage/gates 的池
     统计与卡清单会随入池变化），并重跑 `cargo test --release -p hsbg-engine
     --no-fail-fast` 与 `pytest tests/test_rust_engine.py`；
  4. 评测/训练侧的 seed 基准（e.g. 固定 seed 的基线 rollout）同样需要重跑冻结记录。

**Dark Paradox P3 后续项（本次决策 = 保持 5 形态，不做单卡动态 id）**：

1. **数据层**：需要 37.0.0 单卡形态表（每局可抽的 Dark Gift/属性/Tier 列表）。
   当前 `data/p2/cards_37.json` 只有 base 占位壳 + 36.6.3 的 5 个 token，没有 37
   官方形态表，无法凭空实现“37 版形态集合”。
2. **引擎层**（若做）：per-game `CardDef` override（或 `Game::paradox_form` 表），
   在 universe / pool 记账 / shop 摆位与价格 / 三连与 golden / 观测卡牌 embedding /
   `state_json` 读取处统一用“本局形态”替换 tier/stats/script；属跨系统改动，需全量
   回归 + 观测/存档兼容方案（AT 的 `CardId` = CardDef 稠密下标，单卡动态化会破坏
   “卡表指纹 → 存档”的既有不变量）。
3. **验收**：与 37 真实对局 / 官方文本对拍（E1–E2），并保证与 AT 5 形态机制的差异
   仅限**表征**（card id 暴露），玩法等价。

规则依据的证据等级口径见仓库 `docs/AUDIT_PROTOCOL.md`（E0–E4）；对拍分类口径见
`docs/CONFORMANCE_AUTOTAVERN.md`。

---

## 8. 构建步骤（macOS / Linux / Windows）

### 8.1 前置依赖

- Python ≥ 3.10（本机 `/opt/anaconda3/bin/python3` 3.12.2）+ `numpy`；
- Rust：`rustup`（本机 `~/.cargo/bin`），`rust-toolchain.toml` 固定 **1.98.1**
  （`cd rust` 后 rustup 自动使用/安装；本机同时有 1.98.0 与 1.98.1）；
- `maturin >= 1.15`（本机 1.15.0；`pip install -e .` 会用它构建 PyO3 扩展）。

### 8.2 macOS（本机已验证）

```bash
cd rust
cargo build --release                 # 纯 Rust 构建（含 PyO3 扩展；build.rs 已处理 macOS 链接参数）
python3 -m pip install -e .           # maturin 构建并安装 editable 包 hsbg-engine
python3 -c "import hsbg_engine; print(hsbg_engine.version(), hsbg_engine.game_version(), hsbg_engine.data_info())"
```

- Apple Silicon 实测（2026-10-26，`cargo clean` 后）：纯 cargo 冷构建 **113 s**
  （含依赖 + thin-LTO release）；`pip install -e .` 从干净 `target/` 起 **约 121 s**
  （maturin 构建时自带 macOS `RUSTFLAGS`，与纯 `cargo build` 的指纹不同、会各自构建一次，
  因此两者不要串着算时间；日常换数据/改代码只需跑 `pip install -e .`）。
  增量重建实测约 **60–100 s**（touch 一个源文件后 `pip install -e .` = 99 s；
  release thin-LTO + `codegen-units=1` 的重链接是主要开销）。`target/` 体积见 §9。
- 若没装 `maturin`：`python3 -m pip install "maturin>=1.15,<2"`。
- `pip install -e .` 的 editable 安装把扩展直接放在 `rust/python/hsbg_engine/_core.abi3.so`
  （已被 `.gitignore` 忽略），源码改动后重跑该命令即可。

### 8.3 Linux

```bash
cd rust && python3 -m pip install -e .
python3 -c "import hsbg_engine; print(hsbg_engine.version())"
```

- gcc/clang 即可；共享库默认允许未定义符号，无需额外链接参数；
- 若用 venv：先 `source .venv/bin/activate` 再 `pip install -e .`。

### 8.4 Windows

```powershell
# 需 MSVC Build Tools（rustup 的 stable-x86_64-pc-windows-msvc）
cd rust
py -3 -m pip install -e .
py -3 -c "import hsbg_engine; print(hsbg_engine.version())"
```

- Windows 上用 **maturin 构建**是上游支持路径（maturin 会处理 Python import lib）；
  纯 `cargo build --release` 的 Windows 行为未在本机验证（见 §9）。
- 产物是 `_core.pyd`。

### 8.5 常用验证/测试命令

```bash
cd rust
cargo build --release                          # Rust 构建
cargo test --release -p hsbg-engine            # 全量 Rust 测试（上游 858 tests 量级）
cargo test --release -p hsbg-engine --lib      # 只跑库内单测（快）
cargo run --release -p hsbg-engine --example bench -- 2000     # 上游自带裸吞吐示例
cd ..
python3 -m pytest tests/test_rust_engine.py -q # HSBRSIM 侧 fork 回归（11 tests）
python3 rust/bench_engine.py                   # 本 fork 的对比基准（vs 上游 taverngym）
```

常见问题：`ld: symbol(s) not found ... _Py*`（macOS，`cargo build` 时）说明
`crates/hsbg-engine-py/build.rs` 里的 macOS 链接参数被删掉了（§4 #5）；恢复即可。

---

## 9. 已知差异、限制与未验证项

1. **数据版本**：已集成 **37.0.0.255130**（2026-10-26，见 §5.1/§5.5/§11）；
   `game_version()`=37.0.0.255130、`server_rules_version()`=37.0.0，与上游参照包
   （仍是 36.6.3 数据）不同——这是预期：同引擎不同数据，只能比 action/observation
   布局与行为自洽性，不能与上游逐位对拍（逐位对拍证据是替换前的历史记录，见 §10.3）。
2. **版本常量语义变化**：`GAME_VERSION`/`SERVER_RULES_VERSION` 常量保留但降级为
   fallback；权威值来自数据 meta（§4 #1）。依赖这些常量的外部 Rust 代码应改用
   `game_version()`/`server_rules_version()` 函数。
3. **fork 新增 API（超集，不改变上游 API）**：Python `db_info()` / `data_info()`；
   Rust `game_version()` / `server_rules_version()` 函数。上游同名 API 签名/行为不变。
4. **环境变量重命名**：`TAVERNGYM_GUARD_DIR` → `HSBG_ENGINE_GUARD_DIR`（崩溃保护目录，
   默认当前目录）；`TAVERNGYM_SOURCE_HASH/PROFILE` → `HSBG_ENGINE_*`（构建期）。
   依赖旧变量名的脚本需同步改。
5. **构建脚本差异**：`crates/hsbg-engine-py/build.rs` 增加 macOS 链接参数（§4 #5），
   使裸 `cargo build --release` 可用；maturin 构建路径同样正常。
6. **未验证项**：
   - Windows 构建/测试（本次只在 macOS 实测；Windows 请按 §8.4 用 maturin）；
   - Linux 构建/测试（预期与 macOS 相同，但本机未实测）；
   - 上游 `examples/` 的可视化/报告类示例未逐一跑（`bench` 示例与 `bench_engine.py` 已跑）。
7. **数据相关测试**：见 §5.4——37 最终数据（v1.1.0）下内容断言已全部重算，
   `cargo test --release -p hsbg-engine` = 36 套件 **858 passed / 0 failed / 0 ignored**
   （36.6.3 替换前基线同为 858/0）。重算的 3 处断言见 §5.4/§10.2，均未改引擎语义。
8. **上游 docs 未 vendor**：`docs/ARCHITECTURE.md`/`TAVERNGYM.md`/`CONTENT.md` 在只读
   参照仓库；本 fork 的文档是 `rust/FORK.md` + `docs/RUST_ENGINE.md`。
9. **`target/` 体积大**：纯 `cargo build --release` 后约 **304 MB**；跑完
   `cargo test --release -p hsbg-engine`（35 个测试二进制 × thin-LTO）后约 **2.3 GB**
   （与上游 `target/` 同量级）。已 gitignore；清理用 `cargo clean`（会触发下次全量重建）。
10. **存档兼容性**：`state_json` 只对同一张卡表有效（`CardDb.fingerprint` 校验，
    `Game::check_loaded`）；换数据后旧存档/旧 checkpoint 不能复用（与用户决策
    “旧 checkpoint legacy、接受重训”一致）。

---

## 10. 本机验证记录（macOS Apple Silicon，2026-10-26，37 最终数据）

环境：`macOS-15.2-arm64-arm-64bit` / Apple Silicon / 10 CPU；Python 3.12.2
（`/opt/anaconda3/bin/python3`）；Rust 1.98.1（rustup，`cd rust` 自动选中）+
cargo 1.98.0；maturin 1.15.0。**当前数据 37.0.0.255130 最终版**（`gen_carddb_37.py`
v1.1.0，sha `c4826127…`；minion 277 / hero 118 / spell 73 / trinket 236）。
上游 `taverngym` 参照包已安装但仍是 36.6.3 数据（逐位对拍只能在替换前做，见 §10.3）。

### 10.1 构建 / 安装

| 场景 | 命令 | 实测耗时 |
|---|---|---:|
| 首次冷构建（纯 Rust） | `cargo clean && cargo build --release` | **113 s** |
| 首次安装（干净 `target/`） | `python3 -m pip install -e .` | **约 121 s** |
| 数据替换后重建（空载） | `python3 -m pip install -e .` | **约 57 s** |
| 数据替换后重建（37 v1.1.0，当时机器有并发负载） | `python3 -m pip install -e .` | 约 310 s（同一类变更空载约 60 s） |
| 无源码/数据变化的重装 | `python3 -m pip install -e .` | ~10 s（仅打包安装） |

```text
$ python3 -m pip install -e .
Building editable for hsbg-engine (pyproject.toml): finished with status 'done'
Successfully installed hsbg-engine-1.0.0

$ python3 -c "import hsbg_engine as h; print(h.version(), h.game_version(), h.build_info(), h.data_info())"
1.0.0 37.0.0.255130
{'source_hash': '20376190c73352d1', 'profile': 'release',
 'file': '/Users/letiangao/HSAgent/HSBRSIM/rust/python/hsbg_engine/_core.abi3.so'}
{'cards': 3983, 'game_version': '37.0.0.255130', 'server_rules_version': '37.0.0', 'n_cards': 3984}

$ python3 -c "import hsbg_engine as h; print(h.build_is_current(), h.action_name(0))"
True EndTurn        # editable 安装且未改源码/数据；改后为 False，需重建
```

> 并发安装提示：两个进程同时 `pip install` 同一个包会互相 uninstall 而报
> `No such file or directory: .../hsbg_engine-1.0.0.dist-info/`；串行重跑即可。

### 10.2 测试（最终：全绿）

```text
$ python3 -m pytest tests/test_rust_engine.py
10 passed, 1 skipped in 0.28s
# skip = 与上游逐位对拍（上游仍是 36.6.3 数据，设计性 skip；见 10.3）

$ cargo test --release -p hsbg-engine --lib
15 passed; 0 failed

$ cargo test --release -p hsbg-engine --no-fail-fast
36 个测试套件: 858 passed; 0 failed; 0 ignored
# 与 36.6.3 上游基线同数；36.6.3 替换前本 fork 也是 858/0
```

37 数据集成时曾出现的 **6 个 36.6.3 内容断言**已全部按 37 数据重算（只改断言/注释，
不改引擎语义；逐条依据登记在 §5.4 与 §7 台账）：

| 套件 | 用例 | 37 数据重算内容 |
|---|---|---|
| `tests/mechanics.rs` | `pool_tag_rule_excludes_rot_hide_gnoll_by_default` | `eligible 244 → 276`（单人池 277，唯一 `pool_tag=2` 为 BG25_013；pool_tag 继承语义不变） |
| `tests/mechanics.rs` | `aberration_subset_needs_aberrations_in_the_lobby` | v1.1.0 数据修复 Dark Paradox 5 形态映射后**自动恢复**，无需改断言 |
| `tests/mechanics.rs` | `lobby_without_forced_aberrations` | 同上（AT 机制元数据继承） |
| `tests/shown_minions_b.rs` | `gold_counters_show_the_gold_left` | 卡面文本 `1 turns sooner → 1 turn sooner`（37 英文卡面修正单复数；文本来自数据） |
| `tests/validation.rs` | `t19_naga_only_minions_are_out_of_the_pool` | 改为 `t19_naga_only_minions_are_back_in_the_37_pool`：37 池内 races 恰为 NAGA 的 20 张 + 双种族含 NAGA 的 2 张（Naga 回池，`docs/PORTING_37_PLAN.md` §3.4/§4.1） |
| `tests/validation.rs` | `t20_yshaarj_lobby_bans` | v1.1.0 数据修复 Dark Paradox 5 形态映射后**自动恢复** |

> **没有** `#[ignore]` 项、没有剩余失败；全部内容断言与 37 数据自洽。若后续数据再换版本，
> 按 §5.4 流程重算断言，不要改引擎迎合旧断言（见仓库 AGENTS.md 门禁纪律）。

**P3 收尾（2026-10-26，task-22）**：37 Naga 大厅（`flow.rs::optional` + NAGA）+ P3 内容
入池后，固定 seed 的 9 个既有测试漂移：已按 37 数据/37 内容**重算期望或改成与抽取无关
的构造**（清单与逐条依据见 §7 台账最后一行；不删测试、不放宽断言、无 skip/xfail）。
最终全量：

```text
$ cargo test --release -p hsbg-engine --no-fail-fast
39 个测试套件: 887 passed; 0 failed; 0 ignored      # 含 P3 新套件 p3_systems(8)/p3_cards_a/b
$ cargo test --release -p hsbg-engine --test p3_systems
8 passed; 0 failed
$ python3 -m pytest tests/test_rust_engine.py
10 passed, 1 skipped

# P4-M1（2026-10-26，MCTS 搜索核新增后）
$ cargo test --release -p hsbg-engine --no-fail-fast
40 个测试套件: 896 passed; 0 failed; 0 ignored
$ cargo test --release -p hsbg-engine --test search        # 5 passed
$ cargo test --release -p hsbg-engine --lib                # 19 passed
```

### 10.3 与上游逐位一致（36.6.3 数据，替换前历史证据）

以下在 36.6.3 数据 + 同 commit 上游 `taverngym` 下实测，证明 fork 只是改名、行为逐位一致：

| 检查 | 结果 |
|---|---|
| `layout()` 32 项 | 与上游逐项相等 |
| `action_name(0..244)` 245 项 | 与上游逐项相等（0 mismatches） |
| `run_bot_games(3, seed=0/7/12345)` | 终局回合完全相同 |
| 全 bot 8 人局 `Game.state_json()` | **字节相等**（含 245 项布局/卡表/事件状态） |
| `SoloEnv` 同 seed 同动作序列 | 轨迹 + `state_json` 逐字节相等 |
| `BatchEnv` 同 seed 同动作序列 | 观测 bytes/`save(i)` JSON 逐字节相等 |

37 数据下仍保持的是**布局/API 逐项一致**（`tests/test_rust_engine.py`
`test_layout_and_action_names_match_upstream` 照跑通过）；引擎内部状态因两边数据不同
不再做逐位对拍（对应用例按设计 skip）。

### 10.4 基准（37 最终数据，2026-10-26；口径与复现见 `docs/RUST_ENGINE.md` §7）

命令：`python3 rust/bench_engine.py --games 1000 --e2e-games 20 --solo-games 100
--batch-steps 100 --repeats 3`（warmup + 3 次取中位；上游 `taverngym` 仍是 36.6.3 数据，
故“上游”列只作同代码/harness 的量级对照）。

| 项 | hsbg_engine（37 最终数据） | 上游 taverngym（36.6.3） | 说明 |
|---|---:|---:|---|
| 裸引擎 `run_bot_games`（8 座全 bot，1000 局） | **274.1 games/s / 3.65 ms/局** | 272.8 games/s / 3.67 ms/局 | 平均 15.4 回合；机器负载波动 ±10%（多次实测 257–282 games/s） |
| 端到端 8 人局（Python `Game`+bot 驱动） | 3.57 ms/局（279.9 games/s） | 3.79 ms/局（263.8 games/s） | 含 Python 调用开销 |
| SoloEnv 观测+决策循环（1 座 vs 7 bot） | 792.9 games/s / 1.26 ms/局 | 793.2 games/s / 1.26 ms/局 | 含观测 bytes；9.7 步/局 |
| BatchEnv（64 局、threads=8、100 步） | 925.9 episodes/s / 9406 slot-steps/s | 951.6 episodes/s / 9667 slot-steps/s | 并行采样；差异在噪声内 |

> 36.6.3 替换前基线：282.3 games/s / 3.54 ms/局（裸引擎）——37 数据下吞吐基本不变。
> 首版 37 数据（v1.0.0）下 Lead 另跑过一次（261.4 games/s / 3.83 ms/局、端到端
> 3.47 ms/局、SoloEnv 773.2 games/s、BatchEnv 822.4 episodes/s，见 §12），差异来自
> 机器负载，**量级与结论一致**。
>
> `hsrl2`（纯 Python 后端，`hsbg.backends.benchmark` 口径）本机同日实测
> 6.81 games/s / 146.81 ms/局；现在两边数据版本一致（37.0.0.255130），但引擎/动作/
> 观测/harness 不同，见 `docs/RUST_ENGINE.md` §7.3。

---

## 11. 许可与再分发注意事项

- 本 fork 沿用上游 **MIT** 许可（`LICENSE` 原样保留）；再分发时请保留
  `LICENSE`/`NOTICE`/`CITATION.cff` 与本文件。
- `data/cards.json` 中的卡名/文本/数值属 Blizzard Entertainment，仅作为模拟研究数据；
  不要把游戏客户端文件/美术/音频等资源加入仓库（上游 NOTICE 已声明）。
- 本项目是非商业研究项目，与 Blizzard 无关联、未获其背书。

---

## 12. HSBRSIM P2 集成记录（2026-10-26，Lead）

- **数据已替换为最新 37.0.0.255130**（用户 P2 决策“数值按最新版本”；数据层 v1.1.0 最终版）：
  - 文件：`crates/hsbg-engine/data/cards.json`（编译期 `include_str!`）；
  - 来源：`data/p2/cards_37.json`（`tools/p2_data/gen_carddb_37.py` **v1.1.0** 生成，3983 = 3695 映射 + 288 compat；v1.1.0 修复 = AT 机制元数据继承 + Dark Paradox 5 形态映射）；
  - sha256：**`c482612727c2618e547479d743d40dad6ab4763cf1368e9742eb312ec4886dae`**（首版 v1.0.0 的 `4ba9cdf7…` 已被其取代）；
  - meta：`client_version=37.0.0.255130`、`server_patch=37.0.0`；
  - 单人池计数：minion **277**（含 Dark Paradox 5 个旧形态 compat 条目）/ hero **118** / spell **73** / trinket 236（T2 继承）。
- **随数据替换的 fork 改动**（§7 台账补充）：
  - `src/cards.rs::tests::pool_counts_match_bundle` 断言更新为 **277/118/73/236**
    （数据驱动，非机制改动；v1.1.0 数据层修复后由 273 → 277）；
  - 版本常量仍为 fallback，实际上报由数据 `meta` 驱动（§4 改动 #1/#2/#4）；
  - 36.6.3 内容脚本对 compat 条目（288 张 37 已不在 CardDefs 的旧卡）保持可解析：
    `registry()` 的 `db().id()` 0 panic（`data/p2` 已校验 1290 个脚本引用 id 0 missing）。
- **构建/安装**：`cd rust && python3 -m pip install -e .`（maturin，重建后
  `hsbg_engine.game_version()=="37.0.0.255130"`、`db_info()==(3983, "37.0.0.255130", "37.0.0")`）。
- **测试收尾**（task-19）：37 最终数据下全量 `cargo test --release -p hsbg-engine` =
  **36 套件 858 passed / 0 failed / 0 ignored**、`--lib` 15 passed、pytest 10 passed + 1 skip；
  重算的 3 处内容断言见 `rust/FORK.md` §5.4/§10.2（无 ignore 项）。
- **37 数据基准复跑**（首版 v1.0.0 数据，Apple M1 Pro，`rust/bench_engine.py`；最终
  v1.1.0 数据的本机复跑见 §10.4：裸引擎 274.1 games/s / 3.65 ms/局，与上游 272.8/3.67
  同量级）：
  - 裸引擎 `run_bot_games`：**261.4 games/s / 3.83 ms/局**（上游同数据同 harness 264.2/3.78；
    比值 0.99，符合“代码一致、数据不同”预期；36.6.3 数据下为 256.9/3.89）；
  - 端到端 Python 驱动：3.47 ms/局（288.5 games/s）；SoloEnv 观测+决策循环：
    773.2 games/s；BatchEnv(64 局, threads=8)：822.4 episodes/s。
- **P1 内容移植**：37.x 缺口清单见 `docs/PORTING_37_PLAN.md`（P1 must-have 18 卡）；
  未移植前，37 新增/轮换进池的缺失脚本卡由“compat 卡表 + 现有脚本覆盖”保证引擎
  可运行，但这些卡的机制行为按 AT 36.6.3 脚本/无脚本处理，需在 P1 补齐。
