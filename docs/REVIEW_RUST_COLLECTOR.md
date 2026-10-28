# PPAI GPT-6 Astra 终审：Rust 全采集器 spike（2026-10-28）

> 评审模型 `ppai/gpt-6-astra`（只读，未占 GPU）。评审快照 `62b305e`；下列修复在其后提交。

## 结论：**不通过（就 62b305e 而言）** → 已修（`6d2760e`/`8b31863` + 最后一批）

| 评审项 | 状态 |
|---|---|
| P0 rank 串局污染（Rust + batchenv） | ✅ 按 `game_ids == slot` 精确回填；回归测试 `test_rust_collector_rank_backfill_not_cross_game` |
| P1 single 路径漏 `game_id_offset` | ✅ 已加 |
| P1 `max_steps` 被丢弃、无截断上界 | ✅ Rust 记录每 slot 步数，超限即 finish（rank 保持 -1） |
| P1 非法兜底进入 policy loss | ✅ 兜底动作置 `forced=true`（只参与 value） |
| P1 `batch_mode` 入队后才设置 | ✅ 改为 `submit(batch_mode=...)`，入队前完成 |
| P1 混合单/批请求行错位 | ✅ 混合时回退逐行路径 |
| P1 RNG 契约（整批用首请求 seed） | ⚠️ 已在代码注释与文档明确：批级 seed、同一次运行请求顺序固定 → 可复现；不保证逐行 `seed+j` 等价 |
| P1 mask 全 False / 温度非法 | ✅ 显式拒绝（`ValueError`），与 `masked_log_softmax_np` 语义一致 |
| P2 重复 `pending()`、`k=0` 仍 step | ✅ `k=0` 直接返回不推进；重复 pending 仍为「重观测」契约（文档化了） |

## 对「2 s 不可达」的裁决

评审**同意**「单纯 Python→Rust 搬运未实现 2 s」，但**反对**把它写成严格证明，并要求：
1. 算术修正（400–900 轮 × 5 ms = 2–4.5 s，不是 3–7 s）；
2. 分别报告轮数/每轮延迟/GPU 分摊/额外开销，不能把多卡总服务时间当关键路径；
3. 解释 `docs/RUST_COLLECTOR.md` §4 曾预测「共享推理 1.5–2 s」为何失效；
4. `batch_sizes` 记的是请求数不是行数，`batch_p50` 不能直接当 ready 行数；
5. 未做全量性能数据认证。

→ 最终文档已按此把表述降级为「本轮实现未达 2 s」，并把「不可达」改为「需要观测降维/持久 GPU 缓冲/CUDA graphs 才能继续逼近」。

## 建议的下一步（评审给出）

1. 先修正确性与计量，再做固定 checkpoint + 固定 seed 的成对基准（隔离策略漂移）；
2. 降低前向调用固定成本：持久 GPU 输入缓冲、融合采样、减少 CPU/GPU 往返，再评估 CUDA graphs；
3. 减少 bot 席位会改变任务，不算等价优化。
