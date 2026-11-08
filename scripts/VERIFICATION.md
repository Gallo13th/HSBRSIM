# 验收（VERIFICATION）

## 一键门禁

```bash
python scripts/verify_all.py --fast    # Rust/Python 测试 + 8 局 smoke + TavernBench
python scripts/verify_all.py           # 再加 AZ 自对弈/PPO smoke
```

门禁：

| gate | 命令 | 预期 |
|---|---|---|
| rust_tests | `cargo test --release -p hsbg-engine` | 0 failed（当前 39 套件 / 899 项量级） |
| python_tests | `pytest tests` | 0 failed |
| engine_smoke | `hsbg_engine` 8 局全 bot | crashes=0 |
| tavernbench | `scripts/run_tavernbench.py --check` | 26/26 PASS |
| data_check | `tools/p2_data/gen_carddb_37.py --check` | 与 `data/p2/` 一致（缺上游 checkout 时 SKIP） |
| az_smoke | `scripts/az_selfplay_smoke.py --games 1 --epochs 1` | 0 illegal / 0 truncated；报告落 `runs/` |

## 关键专项

```bash
python -m pytest tests/test_rust_engine.py -q
python -m pytest tests/test_p2_data.py -q     # 需 HSBRSIM_AT_ROOT
python -m pytest tests/test_az_search.py tests/test_az_train.py tests/test_az_entity_model.py -q
python scripts/run_tavernbench.py --check
```

## 数据版本

```bash
python -c "import hsbg_engine as E; print(E.game_version(), E.data_info())"
# 37.0.0.255790 {'cards': 3983, 'game_version': '37.0.0.255790', ...}
```

## 硬标准

- 0 failed / 0 crash / 0 invalid；非法动作不推进状态。
- 同 seed 轨迹逐位一致；`state_json` save→load→save 字节相等。
- 观测只含公开信息；动作 mask 精确。
- 纯文档改动只做链接/路径自检；不得为变绿删测试/放宽断言。
