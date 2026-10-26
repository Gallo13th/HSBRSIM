# AutoTavern 第三阶段（P3）：AT 唯一主引擎，补完 37.0.0 模拟环境 → 转 RL

> 起点：P2 已完成并推送（Rust fork `hsbg_engine` 以 37.0.0.255130 数据运行，
> 动作/观测标准 profile 已对齐；HEAD `221a079`）。
>
> **用户决策（2026-10-26）**：直接以 AT（AutoTavern fork，`hsbg_engine`）为主引擎，
> **直接修补 AT**；模拟环境补完整后，精力全部转入 RL。
> `hsrl2` 自此**冻结**为 legacy/oracle（只读参考、回归与差分），不再新增功能/内容。

---

## 1. 阶段目标与决策

| 项 | 结论 |
|---|---|
| 唯一主引擎 | `rust/` 内 AT fork `hsbg_engine`（Rust + PyO3，37.0.0.255130 数据） |
| legacy 引擎 | `hsrl2/` **冻结**：只读参考/差分 oracle/真实对局桥；回归必须保持全绿 |
| 本轮目标 | 补完 37.0.0 模拟环境：P1 内容移植 + 系统机制 + 验收门禁 |
| 之后 | 全部精力转 RL：std 245/3227 profile 接入 env/训练/评测、重训 BC/PPO 基线 |

## 2. P1 内容范围（37 池内缺口，18 张；全部 M 级）

| 批次 | 内容 | 数量 | 参考 |
| --- | --- | ---: | --- |
| P3-A | 池内缺失随从 A：`BG23_002, BG26_505, BG27_514, BG31_035, BG31_920, BG31_925, BG32_835, BG32_837` | 8 | 7 张有 hsrl2 参考 |
| P3-B | 池内缺失随从 B：`BG33_319, BG34_925, BG35_921, BG36_508, BG36_622, BG36_921` + 池内法术 `BG32_815, BG35_922` | 8 | 6 张有 hsrl2 参考 |
| P3-C | 主英雄技能 `BG22_HERO_007p`（Queen Azshara）+ `BG36_360` Dark Paradox 37 机制决策 | 2 | hsrl2/herói 参考 + AT 机制评估 |

## 3. 验收门禁（模拟环境“完整”判定）

1. **池内脚本覆盖 0 缺失**：Rust content 注册表 vs 37 单人池（minion 277 / spell 73 /
   主英雄技能）；`docs/P3_VERIFICATION.md` 覆盖审计表。
2. **hsrl2 oracle 差分**：16 张有参考的卡在可比局面下行为一致（MATCH；约定差异需登记）。
3. `cargo build --release -p hsbg-engine` + `cargo test --release -p hsbg-engine`
   **0 failed**（既有 858 项不回退）；8 人 bot 冒烟 ×20 seeds `crashes=0`；
   同 seed 双跑确定性一致。
4. `python3 -m pytest tests -q` / `pytest hsrl2/tests -q`（legacy 不回退）/
   `scripts/verify_all.py` 门禁。
5. 剩余缺口按可达性登记：P2 饰品（37 新增 8 + triage 138 上界）、异变系统（108，
   新系统）——明确不阻塞 P1 验收。

## 4. 交付与证据

### 4.1 内容交付（18 张全部完成）

| 批次 | 文件 | 注册项 | 测试 |
|---|---|---:|---|
| P3-A（8 池内随从） | `rust/crates/hsbg-engine/src/content/p3_batch_a.rs` | 22（含金色/Spellcraft 法术） | `tests/p3_cards_a.rs` **8/8** |
| P3-B（6 随从 + 2 法术） | `.../content/p3_batch_b.rs` | 10（含 2 个 Rimescale Spellcraft 令牌） | `tests/p3_cards_b.rs` **13/13** |
| P3-C（Azshara + Dark Paradox + Naga 大厅） | `.../content/p3_systems.rs` + `src/flow.rs` | Azshara `BG22_HERO_007p`（30 总攻→`BG22_HERO_007p2` Naga Conquest）；`flow.rs` 大厅可选种族 9→10 类（37 Naga 回池） | `tests/p3_systems.rs` **8/8** |

- **Dark Paradox 决策**：保持 AT 5 形态机制（`BG36_360t3/t4/t5/t6/t9` 每局随机 1 个，base
  `BG36_360` 为不在池占位壳）；37 可观察玩法等价，单卡 id 动态化需 per-game CardDef
  override 贯穿 pool/shop/triple/obs/state_json，高风险 → 列入 P3 后续项（`rust/FORK.md` §7）。
- **9 个既有测试收口**（37 Naga 大厅 + P3 内容入池导致固定 seed 漂移）：`tests/mechanics.rs`
  7 例按 37 数据重算/稳健构造、`buddies_a/c` fixture 补 `skipping=false`；**不放宽断言、
  无 skip/xfail**，清单写入 `rust/FORK.md` §7。

### 4.2 独立验证（`tools/p3_verify/`，`python3 -m tools.p3_verify.run_all --skip-rebuild`）

| 门禁 | 结果 |
|---|---|
| 池内随从覆盖（277） | scripted **272** + keyword-only 5，**missing 0** |
| 池内酒馆法术覆盖（73，3 Duos 已剔除） | scripted **73**，**missing 0** |
| P1 18 卡覆盖 | **missing 0**（Azshara 变形目标 `BG22_HERO_007p2` 已 scripted） |
| hsrl2 oracle 差分（16 有参考 + 2 结构检查） | **15 MATCH / 1 DEFERRED / 2 STRUCTURAL_OK / 0 FAIL** |
| 全量 Rust 测试 | **39 套件 887 passed / 0 failed / 0 ignored** |
| 8 人 bot 冒烟 ×20 seeds | **crashes=0**；同 seed 双跑确定性 PASS |
| `verify_all` | **12/12 gates PASS**（新增 rust_engine_build + rust_engine_test） |

- DEFERRED：`BG34_925` Rally（仅战斗内触发、无对称持久观察量；worker 单测覆盖右邻/最右/金色）。
- STRUCTURAL_OK：`BG33_319`（无 hsrl2 参考，按卡面新写）、`BG36_360`（5 形态决策）。
- 详见 `docs/P3_VERIFICATION.md`（覆盖审计表/oracle 矩阵/门禁证据/风险）。

## 5. 限制与转 RL 的下一步

### 5.1 残余缺口（不阻塞 RL）

1. 主英雄技能长尾 9 个（Duos/旧替换技能；P1 不要求）；P2 饰品（37 新增 8 张 +
   triage 138 上界）、非池法术、P3 异变/任务/伙伴等按 `docs/PORTING_37_PLAN.md` 分批。
2. 679 场真实战斗轨迹尚未在 Rust 侧重放（hsrl2 侧差分基线保留）；Rally oracle 需
   debug-only hook seam（P3.x 可选）。
3. **seed 基准冻结**：P3 内容入池改变固定 seed 的大厅/池抽样，进入 RL 前需按
   `rust/FORK.md` §7 checklist 重新冻结一次 seed 基准（并用 `tools/p3_verify/run_all`
   确认 0 回归）。
4. Dark Paradox 单卡 id 动态化 / 异变系统 = P3 后续（需新系统/数据形态）。

### 5.2 转入 RL（下一阶段建议）

1. **环境接入**：在 `hsbg/` 增加 `hsbg_engine` 后端的标准 profile 环境（245+扩展动作
   精确 mask、3227+124 观测），`make_env` 默认切到 `hsbg_engine`；hsrl2 仅 oracle/对照。
2. **策略/训练**：固定 245 动作空间策略头 + 3227+124 观测编码；BC（heuristic teacher
   on hsbg_engine）→ PPO；旧 checkpoint 标 legacy。
3. **评测**：同动作空间/观测/seed 协议下的 baseline（random/heuristic/BC/PPO），
   与 AutoTavern 论文口径注明数据版本差异；TavernBench 保持独立（36.6.3 LLM 基准）。
4. **门禁**：RL 阶段保留 `cargo test`（引擎）+ `tools/p3_verify`（内容回归）+ 新 env/训练测试；
   每次内容补丁后重跑 `run_all` 并重冻结 seed 基准。
