"""AutoTavern × hsrl2 跨引擎一致性审计脚手架（WS2）。

只读两个引擎，不改 `hsrl2/**` / 第三方仓库；所有观察结果写入
`runs/conformance/`（gitignore）。入口::

    python -m tools.ac_conformance.run --seeds 48

文件职责::

    paths.py       仓库/参照仓库路径与版本常量
    data_diff.py   卡牌/规则常量数据差异（36.6.3 vs 37.0.0）
    tavern_api.py  AutoTavern（taverngym）侧构造/驱动
    hsrl2_api.py   hsrl2 侧构造/驱动
    scenarios.py   场景矩阵（机制级 + 卡牌级 + 经济 + 流程）
    compare.py     分类口径（MATCH/CONVENTION_DIFF/ENGINE_BUG/DATA_GAP/UNSUPPORTED）
    run.py         CLI：跑全部场景 → runs/conformance/report.json
"""

__all__ = ["paths"]
