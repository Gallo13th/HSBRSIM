# 引擎/接口/数据契约审计（task-2）

> 范围：`hsbg_engine`（Rust）↔ `hsbg/env` / `hsbg/az`（Python）↔ `data/p2` + `rust/.../data/cards.json` 数据链路。
> 性质：**只读审计**，未修改任何代码/数据，未启动训练。
> 时间：2026-11-04 00:01–00:3x（CST）；机器：`bicourse-glt`；仓库 HEAD `194fc5b`；Python 3.10.20（`hiermolgen` env，torch 2.6.0+cu124）；审计时 GPU 0/1/2/7 他人占用，测试统一 `CUDA_VISIBLE_DEVICES=6`（空闲卡）。

## 0. 结论速览

- **引擎↔Python 冻结契约全部成立**：动作 245/扩展 274 声明、obs 3227+124、`layout()` 32 项、`legal_mask` 245、`state_json` 往返、同 seed 确定性、8 座 API、`hsbg/az/env_api.py` 决策输入封闭，均实测通过（§2）。
- **245 与 AutoTavern 逐位一致有强源码级证据**：上游 `actions.rs` / `obs.rs` 与 fork **逐字节相同**（`diff` rc=0）；但运行时上游对拍因 `taverngym` 未安装而 **SKIP**（§2.3）。
- **全量 Python 门禁当前为红**：`pytest` 953 collected / 936 passed / **6 failed**（5 项是 `test_az_replication_bc` 与实现漂移、1 项是 `test_process_pool` 时序），rc=1；`verify_all --fast` 同因 `python_tests` 失败而 FAILED（4 gates，208s；§1）。**注意**：审计期间有队友并发新增测试（见 §5），collected 数从 953 漂移到 959，数字以各次运行输出为准。
- **Rust 门禁全绿**：`cargo test --release -p hsbg-engine` 914 passed / 0 failed / 1 ignored（178s）；TavernBench `--check` 26/26 PASS（0.9s）。
- **数据版本链路一致**：raw(37.0.0.255790) → `MANIFEST`(v1.2.0) → `cards_37.json` → Rust `cards.json` 全部同版本且 sha256 对得上；生成器 `--check` 幂等通过（§3）。
- 主要风险：数据门禁**默认路径失效**（缺 `../AutoTavern` 时静默 SKIP）、`verify_all` 的 pytest 超时 600s 余量偏小、`tools/version_sync.py` 已删除但文档仍引用、若接扩展动作 274 与引擎 245 会静默错位（§4）。

## 1. 门禁实测

运行方式：远端后台脚本 `/tmp/hsbaudit/gates.sh`（顺序执行，避免并发抢 `rust/target` 锁），原始日志 `/tmp/hsbaudit/{cargo_test,pytest,tavernbench,verify_fast}.log`，摘要 `/tmp/hsbaudit/summary.txt`。审计期间机器 load average ≈ 80–103（他人 `songwei` 任务占 70+ 核），耗时为**高负载下**数值。上游只读 checkout：`/tmp/AutoTavern`（MCG-NJU/AutoTavern `fb61201`），仅用于源码 diff，不参与构建。

| # | 门禁 | 命令 | 结果 | 耗时 | 失败根因 / 备注 |
|---|---|---|---|---|---|
| 1 | pytest 全量 | `python -m pytest tests -q`（`PYTHONPATH=rust/python:.`，CUDA=6） | **FAILED** rc=1：953 collected，936 passed / **6 failed** / 11 skipped / 0 error | 389.1s | 见 §1.1；另项目 `pyproject.toml` `addopts="-q"` 与 CLI `-q` 叠加成 `-qq`，pytest 不打印最终计数行（计数由 collect 列表+进度字符核出） |
| 2 | Rust 全量 | `cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine` | **PASS** rc=0：41 个测试二进制 + doctests，**914 passed / 0 failed / 1 ignored** | 178.2s | 含首次编译约 2–3min；`FORK.md:61` 写「39 套件」已过时（现 42 条 test result） |
| 3 | TavernBench | `python scripts/run_tavernbench.py --check` | **PASS** rc=0：**26/26** 项 | 0.9s | 含 36 文件 sha256、960/368 任务数、40 场景、12 系统评分复现（golden play 一致） |
| 4 | 汇总门禁 | `python scripts/verify_all.py --fast` | **FAILED** rc=1（4 gates）：`rust_tests` PASS 6.0s / `python_tests` **FAIL** 201.2s / `engine_smoke` PASS 0.2s / `tavernbench` PASS 0.9s | 208.3s | `python_tests` 尾巴：`5 failed, 943 passed, 9 skipped`（此轮 `test_process_pool` 未复现 → 该失败为 flaky）；`data_check` 因缺 `../AutoTavern` 被 **SKIP**；`--fast` 跳过 `az_smoke`；`runs/verify_all.json` 已写出（`ok=false`） |

### 1.1 `pytest` 6 个失败（均为既有失败，非本次审计引入）

| 测试 | 失败原因 | 归因 |
|---|---|---|
| `tests/test_az_replication_bc.py::test_discover_only_legal_targets`<br>`::test_discover_value_weighting`<br>`::test_buy_pair_triple_weight[1-1.0]`<br>`::test_buy_pair_triple_weight[2-2.0]`<br>`::test_illegal_buy_and_golden_excluded` | `AttributeError: 'types.SimpleNamespace' object has no attribute 'features'`，栈顶 `scripts/train_entity_sync.py:242` | 实现 `_attach_replication_bc_labels` 新增读取 `batch.features`，而测试 fixture（`test_az_replication_bc.py:19-24`）只造了 `cards/masks` → **测试与实现漂移** |
| `tests/test_process_pool.py::test_reload_detects_worker_death_after_ack` | 独立全量跑：`AssertionError: {'w0_acks': 1}; assert 1 >= 2`（`test_process_pool.py:211`）；`verify_all` 重跑时**通过** | ack 后 worker 死亡 → 重发在慢路径才触发，**时序敏感/flaky**；需确认是否 `process_pool.py` resync 漏重发 |

复现：
```bash
cd /home/data/users/gaoletian/projects/HSBRSIM && export PYTHONPATH=rust/python:.
CUDA_VISIBLE_DEVICES=6 python -m pytest tests/test_az_replication_bc.py -q
CUDA_VISIBLE_DEVICES=6 python -m pytest tests/test_process_pool.py::test_reload_detects_worker_death_after_ack -q
```

### 1.2 `verify_all --fast` 子门禁明细

`scripts/verify_all.py:84-107` 的顺序：`rust_tests`(600s) → `python_tests`(600s) → `engine_smoke`(180s) → `tavernbench`(120s) → `data_check`(120s, 仅当 `<HSBRSIM_AT_ROOT>/crates/taverngym/data/cards.json` 存在) → `az_smoke`（`--fast` 跳过）。本次实测（`runs/verify_all.json`，`generated_at=2026-11-04T00:14:50+0800`，总 208.3s）：

| gate | 结果 | 耗时 | 说明 |
|---|---|---|---|
| rust_tests | PASS rc=0 | 6.0s | 复用 cargo 增量构建 |
| python_tests | **FAIL rc=1** | 201.2s | `5 failed, 943 passed, 9 skipped`（`test_az_replication_bc` 5 项；`test_process_pool` 此项此轮通过） |
| engine_smoke | PASS rc=0 | 0.2s | 8 局全 bot 无 crash |
| tavernbench | PASS rc=0 | 0.9s | 26/26 |
| data_check | **SKIP** | — | 默认 `ROOT.parent/AutoTavern` 不存在；见 §3.2 |
| az_smoke | 跳过 | — | `--fast` 行为 |

- 汇总 `FAILED (4 gates)`（`data_check` 未入列）；`verify_all.json` 的 `ok=false`。
- **历史对照**：本次覆盖前该 JSON 为 2026-10-31 15:10 的运行，当时 `python_tests` 为 `536 passed, 8 skipped in 99.69s` 且全绿 —— 6 天内测试从 536→~960，说明门禁已明显变大，但 600s 硬超时未同步调整（§4 P1-3）。

## 2. 契约核对表

实测方式：直接 import 引擎 + `hsbg.env`/`hsbg.az.env_api` 跑只读探针（脚本 `/tmp/hsbaudit/contract_probe.py`，0.02s），辅以源码 diff 与既有测试。

| # | 契约项 | 期望 | 实测 | 证据（file:line） | 结论 |
|---|---|---|---|---|---|
| 2.1 | 动作空间（Python 声明） | 245 标准 + 29 扩展 = 274 | `N_ACTIONS=245`、`N_TOTAL_ACTIONS=274`、245..273 编解码自洽（`encode(decode(i))==i` 全过） | `hsbg/env/action_space_std.py:141,164`；导入期 `validate_layout()` :527-568 | PASS |
| 2.2 | 动作空间（引擎） | 245 | `E.N_ACTIONS=245`；每个下标有唯一名（245 个不重复）；`action_name(245)` 抛 `ValueError` | `rust/.../actions.rs:50,401`；`lib.rs:682,933` | PASS |
| 2.3 | 0..244 与 AutoTavern 逐位一致 | 名称/边界逐位相同 | Python 名与引擎名 245 项全等；**上游源码 `actions.rs`/`obs.rs` 与本 fork 逐字节相同**（`diff` rc=0）；AT `layout()` 32 项源码同构 | `hsbg/env/action_space_std.py:454-497`；`tests/test_action_space_std.py:23-37`；`/tmp/AutoTavern` vs `rust/crates/hsbg-engine/src/{actions,obs}.rs` | **源码级 PASS；运行级未验证**（`taverngym` 未安装，`tests/test_rust_engine.py:60-74,298-324` 两条对拍 SKIP） |
| 2.4 | 扩展 245..273 仅 Python 声明 | 引擎未实现：mask 245、`apply_index≥245` 拒绝 | `legal_mask` 245 字节；`g.step(0,245)` 与 `step(0,274)` 均 `ValueError: bad action index`；`hsbg.az`/训练全链路无 274 引用（`grep N_TOTAL_ACTIONS` 仅命中 `action_space_std.py`） | `lib.rs:96-104,754`；探针 | PASS（与 AGENTS §2 一致） |
| 2.5 | 观测 floats | 3227 | `observe(0)` f32=3227，dtype float32；分块宽度与定义一致（53+6+9+217+400+320+640+63+1519=3227） | `hsbg/env/obs_std.py:159-169`；`rust/.../obs.rs:32-40`；探针 | PASS |
| 2.6 | 观测 cards | 124，`cards[i]=CardId+1`，0=空 | i32=124；卡块 1+2+2+1+9+5+7+10+8+16+8+7+49=124 | `obs_std.py:172-185`；`obs.rs:44-55,57-59` | PASS |
| 2.7 | `layout()` 32 项 | 引擎=Python=AT | 引擎 32、Python 32、逐项相等（`layout_equal_py=true`） | `lib.rs:649-686`；`obs_std.py:203-243`；`tests/test_obs_std.py:15-19`；`tests/test_at_layout_contract.py` | PASS |
| 2.8 | `legal_mask` | u8[245]，精确、非空于 `needs_action` | 245 字节；`engine_smoke` 8 局逐一 `needs_action→mask.any()` 通过；`obs_eval_inputs` 返回 (3227,124,245) | `lib.rs:42-45,96-99`；`verify_all` engine_smoke | PASS |
| 2.9 | 同 seed 确定性 | 同 seed+动作序列位一致 | 同一 bot 驱动下 `state_json()` 相等、placements 相等（seed=5）；不同 seed 不同 | 探针；`tests/test_rust_engine.py:332-345` | PASS |
| 2.10 | `state_json` save/restore | 往返字节相等、续跑一致 | `Game.from_json(state_json()).state_json()` 相等；`tests/test_state_restore.py` 2 项（逐回合恢复/终局）在本次 pytest 中通过 | `lib.rs:142-147`；`tests/test_state_restore.py:54-114` | PASS |
| 2.11 | 8 座 API | `num_players=8`、placements=1..8 排列 | 8 座、终局 placements 为 1..8 排列；`BatchEnv(controlled=range(8))` 路径存在 | 探针；`hsbg/az/train/selfplay.py:34-113,170`；`tests/test_rust_engine.py:189-208` | PASS（代码+单测；未跑长自对弈） |
| 2.12 | `hsbg/az/env_api.py` 决策输入封闭 | 只用 `observe(seat)`+`legal_mask`；不调 `view()/state_json()` | `ObsView`=(f32[3227],i32[124],bool[245])；`num_actions=245`；`decode_public` 可解（turn/tier/gold/7 对手）；模块内无 `view(`/`state_json(` 调用 | `hsbg/az/env_api.py:30-34,382-399,469-486`；grep 只有注释命中 | PASS |
| 2.13 | 引擎数据信息 | `game_version=37.0.0.255790`、`data_info` 自洽 | `version=1.0.0`、`game_version=37.0.0.255790`、`server_rules_version=37.0.0`、`cards=3983 / n_cards=3984` | 探针；`lib.rs:568-598`；`tests/test_rust_engine.py:149-157` | PASS |
| 2.14 | Rust 搜索核契约 | `mcts_search` 用 f32[245] 先验/pi、u8[245] mask | 源码校验长度 `N_ACTIONS*4`、mask 由 `legal_mask` 生成；`turn_search` 返回 f32[245] | `lib.rs:752-758,840-875,877-881`；`tests/test_rust_engine.py:378-401` | PASS（本次未跑搜索 benchmark） |

```bash
# 契约探针（0.02s，无 GPU）
cd /home/data/users/gaoletian/projects/HSBRSIM && export PYTHONPATH=rust/python:.
CUDA_VISIBLE_DEVICES= python /tmp/hsbaudit/contract_probe.py
```

## 3. 数据版本更新链路

### 3.1 版本一致性（全部实测）

| 层 | 产物 / 入口 | 版本或哈希 | 状态 |
|---|---|---|---|
| 原始官方数据 | `reversed/hsdata_255790/CardDefs.Bacon.xml`、`data/bg_summary.json`（`patch=37.0.0.255790`） | 37.0.0.255790 | ✅ 仅当前版本，无历史备份 |
| 生成器 | `tools/p2_data/gen_carddb_37.py`：`CLIENT_VERSION`=37.0.0.255790(:67)、`GEN_VERSION`=1.2.0(:65) | — | ✅ |
| AT schema 卡表 | `data/p2/cards_37.json` sha256 `26e40386…6ed6a55` | = MANIFEST `outputs_sha256.cards_37.json` | ✅ byte-identical |
| MANIFEST | `data/p2/MANIFEST.json`：`meta.client_version=37.0.0.255790`、`schema=hsbrsim-p2-carddb/1`、`count=3983`（3695 映射+288 compat）、`at_baseline=36.6.3.253932`、`checks.ok=true / problems=[]` | — | ✅；注意 `at_baseline` 表明 289 个 compat/部分字段**继承自 AT 36.6.3**，属混合基线 |
| 引擎卡表 | `rust/crates/hsbg-engine/data/cards.json` sha256 同上（与 `data/p2/cards_37.json` 逐字节相同） | 37.0.0.255790 | ✅ |
| 引擎运行时 | `game_version()=37.0.0.255790`、`server_rules_version=37.0.0`、`data_info().n_cards=3984`（3983+空位） | — | ✅ |
| 代码常量 | `hsbg/az/train/common.py:26 DATA_VERSION="37.0.0.255790"`；`hsbg/env/obs_std.py:195 N_CARDS_REFERENCE=3984` | — | ✅ |
| **version_sync 工具** | `tools/version_sync.py` | **不存在** | ❌ 已于 `c53148c`（AutoTavern-only 重构）删除；`docs/AGENT_TEAM.md:24` 仍把它列为 data 写范围 |

生成器幂等（实测，含上游只读 checkout）：
```bash
cd /home/data/users/gaoletian/projects/HSBRSIM && export PYTHONPATH=rust/python:.
HSBRSIM_AT_ROOT=/tmp/AutoTavern python tools/p2_data/gen_carddb_37.py --check
# -> --check OK: 全部产物与重算结果 byte-identical，meta/计数/脚本 id 校验通过
```

### 3.2 默认路径的坑（实测）

`gen_carddb_37.py:60` 的默认上游根是 `ROOT.parent/"AutoTavern"`，本机**不存在**；`verify_all.py:98-103` 于是把 `data_check` **静默 SKIP**。直接跑默认命令会失败：
```bash
python tools/p2_data/gen_carddb_37.py --check
# stderr: 找不到上游 AutoTavern 数据: /home/data/users/gaoletian/projects/AutoTavern/crates/taverngym/data/cards.json  (rc=1)
```
→ 「`verify_all --fast` 全绿」并不代表数据门禁被执行。

### 3.3 新版本数据接入步骤（以 37.0.0.255790 为模板）

1. `python tools/rea_fetch_hsdata.py --tag <new_tag>` → `reversed/hsdata_<tag>/CardDefs.Bacon.xml`。
2. `python tools/generate_bg_data.py`（Bacon-only）→ 重建 `data/bg_*.json`、`card_zhcn.json`。
3. 在只读上游 AutoTavern checkout 上：`HSBRSIM_AT_ROOT=<repo> python tools/p2_data/gen_carddb_37.py --out /tmp/p2_new`；人工核对 `meta/checks/problems`。
4. 备份现网两处卡表后，将 `/tmp/p2_new/{cards_37.json,MANIFEST.json,new_cards_37.json,at_scripted_ids.json}` 覆盖到 `data/p2/`，并把 `cards_37.json` **逐字节复制**到 `rust/crates/hsbg-engine/data/cards.json`。
5. `cd rust && python -m pip install -e .`（`include_str!` 编译期嵌入，**必须重装**）；必要时同步 `hsbg/env/obs_std.py:195 N_CARDS_REFERENCE` 与 `hsbg/az/train/common.py:26 DATA_VERSION`。
6. 门禁：`gen_carddb_37.py --check` → `cargo test --release -p hsbg-engine` → `python -m pytest tests -q` → `verify_all --fast`；`FORK.md` 登记数据变更。
7. 归档旧 `runs/` checkpoint 并在新数据上**重训**（见 3.4）。

### 3.4 卡牌下标不可复用风险（P1）

- 引擎 `cards` 是**稠密数组，下标即 `CardId`**（`obs.rs:57-59`：`cards[i]=cid.idx()+1`），`N_CARDS=3984` 由构建卡表大小决定。
- 两版卡表总数可以相同（36.6.3 与 37.0.0 都是 3984），但**顺序/内容不同**（`obs_std.py:196-200`；`MANIFEST.diff_vs_at_36_6_3`：删除 288 条、kind/changed 等字段变更 1989 条 cost 等）。⇒ `checkpoint` 里的 card embedding 行（尺寸相同）会**静默错位**，不会报 shape 错。
- `MANIFEST` 的 `checks.script_ids` 只保证卡 id 能被脚本解析，不保证旧下标映射；旧轨迹/BC 样本也必须按 card id 重新映射（`docs/DATA.md` 约束：跨版本不可复用）。
- 复现证据：`python - <<'PY'` 比较 `data/p2/cards_37.json` 与上游 36.6.3 `cards.json` 的 `cards[i].id` 序列即可；TavernBench 36.6.3 states 也被 fingerprint 拒绝（`docs/DATA.md`）。

## 4. 风险清单（P0/P1/P2 + 复现）

### P0（阻断，当前无）
未发现引擎机制/数值/契约层面的 P0 错误。唯一「硬性验收不达标」见 P1-1。

### P1
1. **全量 Python 门禁红（6/5 failed），`verify_all --fast` FAILED** — 阻断 AGENTS §5「0 failed」验收。
   复现：`cd /home/data/users/gaoletian/projects/HSBRSIM && PYTHONPATH=rust/python:. CUDA_VISIBLE_DEVICES=6 python -m pytest tests -q`（独立跑 389s → 6 failed；`verify_all` 内 201s → 5 failed，差异见 §1.1）。修复点在 `tests/test_az_replication_bc.py` fixture 缺 `features`，与 `scripts/train_entity_sync.py:242` 对齐；另单独复核 `test_reload_detects_worker_death_after_ack` 时序。
2. **数据门禁默认不执行** — `verify_all` 因缺 `../AutoTavern` 静默 SKIP `data_check`；默认 `gen_carddb_37.py --check` rc=1。数据漂移风险只在显式设 `HSBRSIM_AT_ROOT` 时才暴露。
   复现：`python scripts/verify_all.py --fast`（看 `[SKIP] data_check`）；`python tools/p2_data/gen_carddb_37.py --check`（rc=1）。
3. **`verify_all` 的 pytest 超时余量不足** — `verify_all.py:85` 硬编码 `timeout=600`，本次全量 pytest 独立跑 389s、gate 内 201s（机器 load≈100 时），测试数已从 10/31 的 536 涨到 ~960；高负载/再加测试即有 TIMEOUT 风险（超时被记为 gate FAIL，与真实失败难区分）。
   复现：`python -m pytest tests -q` 计时；或在更高负载下跑 `verify_all --fast`。
4. **扩展动作 274 与引擎 245 的错位风险** — `action_space_std.decode(245..273)` 合法，但引擎 `step()` 直接 `ValueError`；若有新代码从 274 维分布/随机采样后未切片到 245，会在运行期报错或（若截断）静默丢扩展。当前 `hsbg.az`/训练链路全部 245，无实际触发。
   复现：`python -c "import hsbg_engine as E; E.Game(0).step(0,245)"` → `ValueError: bad action index`。
5. **换数据时的卡牌下标静默错位** — 见 §3.4：卡表总数可不变（36.6.3/37.0.0 均 3984）但顺序/内容不同，旧 checkpoint 的 card embedding 行会静默错位（不报 shape 错）。当前 37.0.0.255790 内部自洽，风险只在**下一次换数据**时兑现。

### P2
1. **5 项 `test_az_replication_bc` 测试陈旧**（fixture `SimpleNamespace` 缺 `features`；`scripts/train_entity_sync.py:242` 已依赖）→ 门禁噪声，掩盖真实回归。
2. **`test_process_pool` ack-death 重发测试时序敏感**（本次 `w0_acks=1<2`）→ 需确认是 flake 还是 `process_pool.py` resync 逻辑漏重发。
3. **文档漂移**：
   - `docs/AGENT_TEAM.md:24` 仍把 `tools/version_sync.py` 列为 data 写范围，但该文件已随 `c53148c` 删除。
   - `docs/AT_LAYOUT_CONTRACT.md:28-37` 的动作区间与槽位范围写错（如 `4..6 HeroPower(0..1)`、`8..16 Buy(0..8)`、`16..23 Sell(0..7)`、`46..126 Play(hand 0..10,pos 0..8)`）；同文件 :44-48 的边界常量是对的。正确版本见 `docs/ACTION_OBS.md:3-25`。
   - `hsbg/az/env_api.py:30` 引用不存在的 `docs/OBS_STD.md`（文档已并入 `docs/ACTION_OBS.md`）；`docs/ACTION_SPACE_STD.md` 同样不存在。
4. **`env_api.num_actions()` 依赖隐式回退**：`Game` 实例没有 `N_ACTIONS` 属性（探针 `engine_has_N_ACTIONS_attr=false`），`num_actions()` 落到模块常量 245（`env_api.py:339-345`）；未来若引擎真接入扩展段而 mask 仍 245，`observe()` 的 `mask.shape[0]!=num_actions` 校验会变成新的隐式约束。建议引擎暴露 `Game.N_ACTIONS` 并保持 mask 长度一致性测试。
5. **`rust/FORK.md:61` 过时**（「Rust 39 套件」；实测 42 条 test result 行/41 个测试二进制）。

## 5. 未验证项（如实标注）

| 项 | 状态 | 原因 / 影响 |
|---|---|---|
| 与上游 `taverngym` 的**运行级**逐位对拍（`test_rust_engine.py` `requires_upstream` 2 项） | SKIPPED | 当前 `hiermolgen` 环境未安装 `taverngym`（`find_spec→MISSING`）；已用 `actions.rs`/`obs.rs` 源码逐字节 diff 替代，但缺运行时 golden |
| `test_p2_data.py` 的「重算产物」用例 | SKIPPED | 未设 `HSBRSIM_AT_ROOT`（默认 `../AutoTavern` 不存在）；单独 `gen_carddb_37.py --check` 已 PASS（显式指向 `/tmp/AutoTavern`） |
| `verify_all` 的 `az_smoke`（MCTS 搜索+1 局自对弈+1 epoch） | 未跑 | `--fast` 明确跳过；短跑仍会占 CPU/GPU，遵守「不训练」约束 |
| `run_tavernbench.py --check --upstream /tmp/AutoTavern` 现场对拍 | 未跑 | 需要上游 tavernbench 目录可执行；本次仅跑 vendored 26/26 |
| 其余 11 个 skip（独立全量跑口径；`verify_all` 内为 9，差异来自并发新增/环境） | 未逐项采集 | 均为 `skipif`：上游 taverngym/`HSBRSIM_AT_ROOT`/`AUTOTAVERN_ROOT` 缺失、`COMPOUND_BC_SLOW` 未开、真实人类库/准完整库文件缺失等；`-rs` 明细未采集 |
| 8 座长自对弈/训练契约（GPU、seed、eval panel） | 未验证 | 任务禁止启动训练；仅做代码/单测级核对 |
| 审计期间并发新增的测试 `tests/test_resume_contract.py`(4 项)、`tests/test_truncation_not_terminal.py`(2 项) | 未审计内容 | 由队友在审计窗口内写入；`collected` 从 953 漂到 959，故三次运行的 pytest 计数略有差异（953/957/959） |

## 6. 复现命令集

```bash
# 0) 环境
ssh bicourse-glt
cd /home/data/users/gaoletian/projects/HSBRSIM
export PYTHONPATH=rust/python:.        # 审计用 python=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export CUDA_VISIBLE_DEVICES=6          # GPU 0/1/2/7 他人占用；CPU-only 用 ""

# 1) 四个门禁
python -m pytest tests -q                                                   # 953–959 collected（审计期间并发新增）；rc=1
cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine          # rc=0; 914 passed
python scripts/run_tavernbench.py --check                                   # rc=0; 26/26
python scripts/verify_all.py --fast                                         # rc=1; python_tests 红

# 2) 契约探针
CUDA_VISIBLE_DEVICES= /home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python /tmp/hsbaudit/contract_probe.py

# 3) 数据链路
HSBRSIM_AT_ROOT=/tmp/AutoTavern python tools/p2_data/gen_carddb_37.py --check
ls tools/version_sync.py                    # 不存在（已随 c53148c 删除；docs/AGENT_TEAM.md:24 仍引用）
git log --oneline -- tools/version_sync.py  # c53148c（删除）/ 488fa48（引入）
md5sum data/p2/cards_37.json rust/crates/hsbg-engine/data/cards.json        # 逐字节相同
sha256sum data/p2/cards_37.json   # 26e40386c923b90515d8c9b26ae211be02c0741e64798e8b6e46addfa6ed6a55

# 4) 上游一致性（源码级）
diff /tmp/AutoTavern/crates/taverngym/src/actions.rs rust/crates/hsbg-engine/src/actions.rs
diff /tmp/AutoTavern/crates/taverngym/src/obs.rs     rust/crates/hsbg-engine/src/obs.rs
```

## 7. 给 Lead 的三条建议（不改代码）

1. **先修门禁红**：`tests/test_az_replication_bc.py` fixture 补 `features`（或在 `_attach_replication_bc_labels` 中容错），并确认 `test_reload_detects_worker_death_after_ack` 是 flake 还是真 bug；否则任何「verify_all 全绿」声明都不成立。
2. **把数据门禁变成硬门禁**：为 `verify_all` 显式传入/文档化 `HSBRSIM_AT_ROOT`（或把 `/tmp/AutoTavern` 固定为 CI 只读依赖）；`data_check` 缺失时应 FAIL 而非 SKIP。
3. **换数据前冻结一次映射哈希**：在 `MANIFEST` 已有 `outputs_sha256` 基础上，增加 `cards[i].id` 序列 sha256 写入 checkpoint meta，训练入口加载时比对；可把「下标静默错位」变成显式拒绝。
