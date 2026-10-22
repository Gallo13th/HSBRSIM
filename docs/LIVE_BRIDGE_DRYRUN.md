# Live bridge dry-run（2026-10-20）

## 代码
- `hsbg/live/bridge_client.py`：TCP JSON 客户端（ping/state/option/choices/select，3s 超时 + 重连）。
- `hsbg/live/bridge_action.py`：live eid ↔ bridge `state.options` 映射（BUY/PLAY/SELL/END_TURN）；
  找不到时记录 `mapping_failed`，**不发送**。
- `scripts/live_bridge_pilot.py`：只读 live state + bridge 动作；默认 dry-run，`--live` 才发送；
  无 UI 点击/拖拽（旧 `live_pilot.py` UI 路线仅留紧急 fallback）。
- `turn_search_live.py`：过滤 `*_HERO_*` token；战斗优先用 `hsbg.planning.live_warband`
  `build_warband`/`simulate_combat_warbands`，失败才回退合成盘面。

## Dry-run（bridge 当前不可达，使用 mock bridge state）
- `python scripts/live_bridge_pilot.py --dry-run --state-file runs/live/state_buy.json --mock-bridge`
  → 2 decisions、0 errors/invalid；日志 `runs/live/bridge_dryrun2/records.jsonl`。
- 映射校验 `runs/live/bridge_dryrun_mapping.json`：`buy[0]→BUY main=308`、
  `buy[1]→BUY main=310`、`end_turn→END_TURN`、合成 `play→PLAY main=900`、
  `sell→SELL main=901`，**invalid=0**。
- 关键修复：`index=0` 曾被 `or -1` 错判为 -1；已修正。

## 当前阻塞
- 游戏登录失败（Battle.net “无法通过暴雪战网服务进行登录”），BepInEx 插件未加载：
  TCP `127.0.0.1:17890` 无监听（`ping False`）。
- 需要 Battle.net/游戏恢复后：
  1. 验证 bridge `state`；确认真实 `OptionType` 名称与 entity `main/target/pos` 语义；
  2. 跑 `--live` 1 局：目标结算 rank + `Power.log` 归档 + `invalid=0`。
- 本 dry-run 只验证协议/映射，未发送任何 option/choices。

## 文件
- `runs/live/bridge_dryrun_mapping.json`
- `runs/live/bridge_dryrun2/records.jsonl`
- `hsbg/live/bridge_client.py`, `hsbg/live/bridge_action.py`, `scripts/live_bridge_pilot.py`
