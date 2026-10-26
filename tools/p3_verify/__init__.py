"""P3 独立验证与验收门禁（WS：P3-V）。

只读 `rust/**`、`data/**`、`hsrl2/**`；写 `tools/p3_verify/**`、
`docs/P3_VERIFICATION.md`、`runs/p3_verify/**`（gitignore 产物）。

模块：
    common.py     路径/数据/运行时常量（cards_37、hsbg_engine catalog）
    coverage.py   池内脚本覆盖审计（Rust content 源码注册表 vs 37 池）
    oracle.py     hsrl2 oracle 差分（16 张有参考卡）+ 2 张结构检查
    gates.py      验收门禁（cargo build/test、bot 冒烟、确定性、pytest、worker 测试复核）
    run_all.py    一键跑 coverage/gates/oracle → runs/p3_verify/report.json + summary.md
"""
