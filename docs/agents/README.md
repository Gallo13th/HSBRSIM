# Subagent 作业体系 — 总纲

> 目标: 把重复性工作（卡牌录入 / 效果脚本 / 语义测试）标准化为 subagent
> 可独立执行的作业单。每份 SOP 是自包含的: subagent 只需读 SOP + 指定的
> 数据文件即可工作，不依赖会话上下文。

## 作业文件

| SOP | 适用任务 | 输入 | 产出 |
|-----|---------|------|------|
| `CARD_ENTRY_SOP.md` | 新卡/改动卡录入 | `docs/S14_DIFF_REPORT.md` 条目 | `hsrl2/scripts/*.py` 注册代码 |
| `EFFECT_SCRIPT_SOP.md` | 效果脚本实现 | 卡牌文本 + CardDef | 脚本类 + registry 绑定 |
| `TEST_SOP.md` | 语义测试 | 三段式 docstring | `hsrl2/tests/test_cards_*.py` |

## 派发规则（给编排者）

1. **批量切分**: 每个作业单 5-15 张卡（同种族/同机制分组），太小浪费
   上下文，太大质量下降
2. **验收门槛**: 每个作业单结束时 subagent 必须自跑并贴出:
   ```bash
   python -m pytest hsrl2/tests/ -q          # 全绿
   python tools/audit_card_registry_v2.py    # 无缺口
   python tools/audit_script_params.py       # 参数一致
   ```
3. **禁止事项**: subagent 不得修改 `hsrl2/core`（引擎）、`constants.py`、
   `tags.py`。需要新机制时**停止作业**并在结果中报告"需要引擎支持: <描述>"，
   由主线裁决实现后重新派发
4. **冲突升级**: 卡牌文本语义有歧义（多解、交互不明）时，标记
   `AMBIGUOUS` 并给出候选解释，不要猜

## 经验积累机制

每次 subagent 作业返回后，编排者把新发现的坑（数据字段缺失、语义边界、
测试技巧）追加到对应 SOP 的 "经验库" 章节。SOP 是活文档。

## 权威信源优先级（冲突时上层胜出）

1. `data/*.json` 的 `script_data_num_1/2`（来自 CardDefs.xml 的模板参数）
2. `docs/BATTLEGROUNDS_RULES.md`（时序/交互）
3. 官方补丁说明 / hearthstone.wiki.gg（语义澄清）
4. `docs/S14_DIFF_REPORT.md`（变更清单，仅用于定位，不作为语义来源）
