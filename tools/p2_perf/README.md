# tools/p2_perf — P2 性能基准（Rust / Python / C）

一键复跑三组基准，数据写 `runs/p2_perf/`（gitignore），结论见
[`docs/PERF_ROUTE.md`](../../docs/PERF_ROUTE.md)。

```bash
cd /Users/letiangao/HSAgent/HSBRSIM
PYTHONPATH=. python3 tools/p2_perf/run_all.py
```

| 脚本 | 内容 | 产物 |
|---|---|---|
| `bench_engine.py` | TavernGym（Rust）裸引擎 / BatchEnv vs hsrl2（Python）整局吞吐 | `runs/p2_perf/engine.json` |
| `bench_e2e.py` | 同一 harness 下 `TavernGymEnv` vs `BattlegroundsEnv` 的 step 环节分解（obs/枚举/apply/对手驱动/奖励） | `runs/p2_perf/e2e_breakdown.json` |
| `bench_c_accel.py` | 3 个真实热函数 纯 Python vs Cython 纯 Python 模式（1000 次 median/p99）+ mypyc 尝试 + Amdahl | `runs/p2_perf/c_accel.json` |

说明：

* 不修改 `hsr2/**` / `hsbg/**` / 根配置；Cython 以 `pip install --target /tmp`
  临时安装，不写项目依赖；编译产物在 `/tmp/p2_perf_cbuild`。
* 数字随机器负载波动；每次结果 JSON 内含硬件/口径字段，便于横向对比。
* 本机为 Apple M1 Pro / Python 3.12.2；TavernGym 1.0.0（release）。
