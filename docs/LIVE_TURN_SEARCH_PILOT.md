# Live turn-search pilot（2026-10-20）

## 结论
- **代码链路已打通**：`read_live_state()` → 回合内枚举（buy/play/end_turn）→ 引擎 `run_combat`
  pairwise → UI 点击/拖拽 → 重新读状态（receding horizon）。
- **真机 1 局 partial**：跑到 **turn 7**；97 次决策、25 个 UI 动作，其中 **17 次 board/hand
  实际变化**、8 次未变化；搜索 p50 9ms / p90 169ms / max 300ms；0 异常。
- 游戏在 turn7 后进程退出；重启客户端报 **Battle.net 登录失败**，且本机
  `C:\Program Files (x86)\Hearthstone\Logs\Power.log` 不存在 → **未能结算/未归档 Power.log**。
  因此 pilot 只能算“动作执行/board 变化已验证”，结算与 Power.log 待网络/日志修复后重跑。

## 关键修复
- 首次点击/拖拽 no-op：原因是游戏窗口未前台。执行前 `ensure_foreground()` + 0.35s 等待，
  并使用 **shop→hand drag**（而非 click）后，购买/出牌动作可稳定改变 board/hand。
- live state 的 `board` 包含英雄 token（如 `BG21_HERO_030t`），会高估棋盘占位；下一轮需过滤
  非随从/英雄 token。
- 可作为参考：env-builder 已交付 `hsbg/planning/live_warband.py`（精确 warband/战斗裁决）；
  当前 pilot 用合成 MinionSpec + `run_combat`，下一轮应改用它 + `predict_after_action` 做预测枚举。

## 产物
- `hsbg/live/turn_search_live.py`：live 回合内搜索（MinionSpec 枚举、pairwise 战斗、选择动作）
- `scripts/live_pilot.py`：live 决策循环/UI 执行/记录（`--live` 才发送输入）
- `runs/live/turn_search_pilot_live4/records.jsonl` + `summary_partial.json`
- 截图：`runs/live/screenshots/pilot_buy_check.png`、`restart_check.png`

## 下一轮
1. 恢复 Battle.net/游戏登录；开启 Hearthstone Power.log（`[Log.Level]` / `Power.log` 配置）。
2. 过滤 hero token，接入 `live_warband`/`predict_after_action`，补 choice 回退。
3. 仍先 1 局 full pilot：验证结算 placement、Power.log 归档、records sidecar 完整。
4. 通过后再 5–10 局连续采集；失败自动截图/停止，不盲点。
