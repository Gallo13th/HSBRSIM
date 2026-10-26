# tools/p2_delta —— 37.0.0 内容移植缺口分析（P2-C）

> 目标：量化「AutoTavern（TavernGym 1.0.0，客户端 36.6.3.253932）内容脚本 →
> HSBRSIM 37.0.0.255130 数据」的移植缺口，并给出“游戏支持但两引擎都未实现”的
> 操作清单（动作空间 245+ 扩展依据）。
> 全程**只读**：输入为上游仓库 `repos/AutoTavern`（只读）与 `data/bg_*.json`、
> `hsrl2/scripts/**`；输出只写 `runs/p2_delta/`（gitignore）。

## 一键复现

```bash
cd <HSBRSIM 仓库根>
python3 tools/p2_delta/run_all.py
```

分步（等价）：

```bash
python3 tools/p2_delta/extract_at_content.py   # -> runs/p2_delta/at_content.json
python3 tools/p2_delta/compare_37.py           # -> coverage_matrix.json / summary.md / missing_pool_minions.md
python3 tools/p2_delta/probe_ops.py            # -> ops_probe.json
```

产物（全部确定性，重复运行逐字节一致）：

| 文件 | 内容 |
| --- | --- |
| `runs/p2_delta/at_content.json` | AT content 注册表：1301 个 card id（按 58 个 .rs 文件归类）+ 每脚本 hook/flag/TargetSpec + 上游 `content_report` 口径分 kind 覆盖（与 `docs/CONTENT.md` 交叉校验） |
| `runs/p2_delta/coverage_matrix.json` | 分 kind 覆盖矩阵：AT 已实现 vs 37 数据（missing/extra/changed/new/难度/参考脚本/P1 must-have/池子变化/数据伪影） |
| `runs/p2_delta/summary.md` | 上者的 markdown 摘要（文档引用来源） |
| `runs/p2_delta/missing_pool_minions.md` | 池内缺失随从 15 张逐条表（id/名/tier/种族/攻血/hooks/难度/hsrl2 参考/AT 最近脚本） |
| `runs/p2_delta/ops_probe.json` | 17 项操作探针：每项 AT 源码 file:line、HSBRSIM 位置、37 卡面证据、是否缺口、建议扩展编号 |

## 文件说明

| 文件 | 职责 |
| --- | --- |
| `common.py` | 只读装载（AT cards.json / 37 data/bg_*.json / hsrl2 REGISTRY + AST 文件映射）、文本规范化（`@` 占位符/Duos 变体、`{i}`→`script_data_num`、`|4()` 复数标记、动态计数器）、卡面能力 flag 推断 |
| `extract_at_content.py` | 静态解析 `crates/taverngym/src/content/*.rs` 的 `scripts()`/`scripts_p1()`/动态注册 loop，抽取注册表与 hook 签名；复刻上游 `examples/content_report.rs` 口径并与 `docs/CONTENT.md` 交叉校验 |
| `compare_37.py` | 覆盖矩阵计算：分 kind 集合对拍、changed/unverified 判定、S/M/L 难度、hsrl2 参考脚本、AT 最近可复用脚本（文本 Jaccard+hook/tier 启发）、P1 must-have、池子成员变化、数据伪影 |
| `probe_ops.py` | 操作缺口探针：从两侧源码 grep 出 file:line 证据 + 37 卡面统计，输出 17 项核对结论与建议动作编号 |
| `run_all.py` | 顺序执行三脚本并汇总返回码 |

## 口径要点（详见 `docs/PORTING_37_PLAN.md` §2）

1. AT 侧“已实现” = content 注册表（scripted）∪ keyword-only（复刻上游
   `crates/taverngym/src/script.rs::implemented_uncached`），金色沿 `normal` 链归一。
2. 37 侧集合一律用数据标志（`is_pool_minion` / `is_pool_spell` / `trinket` /
   `dark_gift` / 各 `bg_*.json`），不按 id 前缀猜。
3. 37 数据 `text` 里的 `@` 有两种用途：动态数值占位符（拼回文本）与 Duos 文本变体
   分隔符（取第一段）；`{0}..{4}` 用 `script_data_num_1..5` 还原，无法还原时该卡
   进 `unverified_cards` 而非 `changed_cards`。
4. changed 判定忽略 AT 数据约定差异：池内随从 AT `cost=0`（BG 购买价固定 3 金）不参与
   cost 比较；动态计数器 `(N left!)`、`|4(sing,plur)` 复数标记、`left- most` 断词先归一。
5. 难度是**文本/数据规则**的可复算标签（不是人天估计）：S=纯关键词/无触发 hook；
   M=单触发 hook；L=≥2 触发 hook 或 AT 无对应原语。人天估算在文档里单独标注为“估算”。

## 限制

- 37 数据不导出「当前轮换池」标志（饰品/异变/任务只有全量定义）；饰品缺口给出
  `全部 409` 与 `hsrl2 db.trinket_offer_pool() 357` 两档，需人工按 37 轮换裁减。
- AT 侧 `cards.json` 是 36.6.3 客户端数据（3983 卡），37 数据（bg_cards 3534 + 分表）
  是无 UI 按钮/token 的导出：37 侧“新增 id”122 = 异变 108 + UI 按钮/token 14。
- “AT 最近可复用脚本”是文本相似度启发（`similarity` 字段），仅作选路提示；
  权威参考是 hsrl2 的 Python 脚本路径（移植时以数值/语义骨架为准）。
