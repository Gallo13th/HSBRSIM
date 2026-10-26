# 参考项目评估：HearthstoneLegendArriver

- 仓库：<https://github.com/magicstrangelzb/HearthstoneLegendArriver>
- 评估日期：2026-10-25
- 代码规模：约 30 个 Python 文件 + `cards.json`（约 10MB）+ 截图/OCR/日志样本
- 协议：**GPL-3.0 + 禁止商用附加协议**（`LICENSE` / `ADDITIONAL_LICENSE_INFO`）

## 结论

**没有实现炉石模拟环境/引擎。** 它是一套**真实客户端的天梯脚本**：

```text
屏幕截图 / OCR / Power.log / 炉石盒子推荐面板
        → 解析当前 UI 状态与推荐操作
        → FSM 状态机 + 鼠标点击/拖拽
        → 真实 Hearthstone 客户端
```

没有：

- 游戏状态模型、卡牌/随从实体、回合/战斗结算；
- 动作空间/观测空间/环境 `reset/step`；
- rollout / 搜索 / 对局模拟；
- 酒馆战棋（Battlegrounds）机制或 8 人环境。

## 目录证据

| 路径 | 作用 |
|---|---|
| `FSM_action.py` | 主 FSM：换牌、出牌、点击、结束回合等真实 UI 流程 |
| `click.py` / `manual_controller.py` | 鼠标点击、拖拽、人工接管 |
| `screen_regions.py` / `calibrate_roi.py` / `region_overlay.py` | 1920×1080 的 UI 区域校准与覆盖层 |
| `src/capture/desktop_capture.py` | 桌面截图 |
| `src/ocr/stable_reader.py` / `paddle_adapter.py` | PaddleOCR 识别盒子推荐面板 |
| `src/parser/recommendation_parser.py` | 解析推荐文本 |
| `src/game_state/choose_one.py` / `recommendation_adapter.py` | 真实客户端的选择/推荐适配 |
| `src/safety/hearthstone_liveness.py` | 客户端存活/卡死检测 |
| `log_state.py` / `power_log.py` / `log_op.py` | Power.log 解析/日志 |
| `web_ui.py` / `web/index.html` | Web 控制台、自检、校准 |

源码搜索没有 `Simulator` / `simulate()` / `rollout` / 环境 `step` 等实现；`src/game_state` 下的“状态”是
UI/日志状态，不是可推演的模拟状态。

## 与 HSBRSIM 的关系

- **不能替代** `hsrl2` 引擎或 `hsbg/env`；没有可用的 RL 环境接口。
- 可作为 **live 层/UI 自动化**参考：
  1. 1920×1080 ROI 校准 + 置顶鼠标穿透 overlay；
  2. OCR 稳定读取（连续帧一致才确认）；
  3. 客户端 liveness/卡死检测；
  4. 推荐面板解析 + FSM 流程；
  5. Web 控制台/自检 UX。
- 但它面向**构筑模式天梯**，不是酒馆战棋；`cards.json` 也是构筑卡数据，不能直接用于 BG 引擎。

## 许可注意

GPL-3.0 + 禁止商用附加条款。若参考其代码，需要先确认与 HSBRSIM 的分发/许可兼容；
建议只借鉴协议/交互思路，不直接复制源码。

---

# 参考项目评估：AutoTavern（MCG-NJU）

- 仓库：<https://github.com/MCG-NJU/AutoTavern>
- 拉取：`git clone --depth 1 git@github.com:MCG-NJU/AutoTavern.git`（commit `fb61201`）
- 协议：MIT

## 结论：没有 web 页面

对 `main` 分支完整 tree/README/源码/文档做了检查：

- 没有 `.html/.js/.ts/.tsx/.vue`、`package.json`、`templates/`、`static/`；
- 没有 Flask/FastAPI/Streamlit/Gradio/HTTP server；
- 只有：
  - `crates/taverngym` + `crates/taverngym-py`：Rust 引擎/PyO3；
  - `python/taverngym`：单座/批量环境；
  - `tavernbench/`：数据、评分、文本报告（`tavernbench/report.py` 输出表格/JSON，不是网页）；
  - `docs/`：Markdown 文档。
- 唯一相关的是 `docs/TAVERNBENCH.md` 里的 API 调用说明（模型 API），不是可视化页面。

**因此“AutoTavern 实现简单 web 页面”在当前公开仓库中不成立。** 如果看到的是论文/项目主页的 demo，
需要单独提供 URL；它不在代码仓库里。

## 我们的利用方式

- 已 fork 其 Rust 引擎（`rust/crates/hsbg-engine`）与 vendored TavernBench；
- 新增本地控制台 [WEBUI.md](WEBUI.md)（HSBRSIM 自己的页面）：
  - 状态/版本；
  - 调 `hsbg.rl.evaluate` 评测训练结果；
  - runs/checkpoint 浏览；
  - TavernBench 已发布评分快照 + `--check`。

