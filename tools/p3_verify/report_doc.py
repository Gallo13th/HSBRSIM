"""从 `runs/p3_verify/report.json` 生成 `docs/P3_VERIFICATION.md`（中文台账）。

人工结论/风险在模板中写死（基于实际观测），数字/命令输出从 report 读取，
保证文档与运行证据一致。重跑：``python3 -m tools.p3_verify.report_doc``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from . import common

DOC = common.ROOT / "docs" / "P3_VERIFICATION.md"


def _fmt_list(items: List[str], limit: int = 40) -> str:
    if not items:
        return "（无）"
    shown = items[:limit]
    tail = f" …共 {len(items)} 项" if len(items) > limit else ""
    return "、".join(f"`{x}`" for x in shown) + tail


def _coverage_section(cov: Dict[str, Any]) -> str:
    g = cov["gate"]
    lines = ["## 1. 池内脚本覆盖审计（Rust content vs 37 单人池）", ""]
    lines.append("数据源：`data/p2/cards_37.json`（37.0.0.255130 + 36.6.3 compat，"
                 "单人池按 `pools` 标志）；Rust 注册表 = `content/*.rs` 静态扫描 + "
                 "已编译 `hsbg_engine.catalog_json()`（运行时真值，golden 由 registry "
                 "自动解析）。")
    lines.append("")
    lines.append("| 集合 | 总数 | scripted | keyword-only | **missing** |")
    lines.append("|---|---:|---:|---:|---:|")
    for key, label, total_key in (
            ("pool_minions", "池内随从", "pool_minions"),
            ("pool_spells", "池内酒馆法术", "pool_spells"),
            ("primary_hero_powers", "英雄主技能（129 唯一）", "primary_hero_powers")):
        item = cov[key]
        lines.append(f"| {label} | {item['total']} | "
                     f"{item['counts'].get('scripted', 0)} | "
                     f"{item['counts'].get('keyword_only', 0)} | "
                     f"**{len(item['missing'])}** |")
    lines.append("")
    lines.append(f"- P1 18 卡缺失：**{g['p1_required_missing']}**"
                 f"；按 owner：`{json.dumps(cov['p1']['missing_by_owner'], ensure_ascii=False)}`")
    assoc = cov.get("p1_associated_hero_powers") or []
    lines.append("- P1 关联主技能（Azshara 变形目标 `BG22_HERO_007p2`）："
                 + "、".join(f"`{r['id']}`={r['status']}" for r in assoc))
    t_forms = [r for r in cov["dark_paradox"]
               if r["id"].startswith("BG36_360t")]
    lines.append("- Dark Paradox：base `BG36_360` 为 37 数据占位壳（不在池、无脚本）；"
                 "池内行为由 5 个旧形态承载且全部 scripted："
                 + "、".join(f"`{r['id']}`({r['status']})" for r in t_forms))
    lines.append("  口径：`BG36_360` 在 37 数据中 `pools=[]`（base 壳），5 形态 "
                 "`BG36_360t3/t4/t5/t6/t9` 在池且 scripted；worker 决策保持 5 形态机制"
                 "（`content/p3_systems.rs` 头 + `tests/p3_systems.rs`），按“池内可玩内容"
                 "覆盖”计为 covered_via_forms，不计 missing。")
    lines.append(f"- 静态注册表：{cov['counts']['static_registered_ids']} ids / "
                 f"{cov['static']['modules_with_registrations']} modules；"
                 f"`build_is_current={g['build_current']}`；"
                 f"静态/运行时 normal 形态差集：static_only={len(cov['static']['static_only_vs_runtime'])}、"
                 f"runtime_only={len(cov['static']['runtime_only_vs_static'])}"
                 "（静态解析器只覆盖 `scripts()` 字面量，常量/辅助函数注册以运行时为准）")
    lines.append(f"- **P1 覆盖门禁：{'PASS' if g['pass'] else 'FAIL'}**")
    lines.append("")
    if cov["pool_minions"]["missing"]:
        lines.append("### 池内随从缺失清单")
        lines.append("")
        lines.append("| id | 名称 | 状态 |")
        lines.append("|---|---|---|")
        for row in cov["pool_minions"]["missing"]:
            lines.append(f"| `{row['id']}` | {row['name']} | {row['status']} |")
        lines.append("")
    if cov["pool_spells"]["missing"]:
        lines.append("### 池内法术缺失清单")
        lines.append("")
        lines.append("| id | 名称 | 状态 |")
        lines.append("|---|---|---|")
        for row in cov["pool_spells"]["missing"]:
            lines.append(f"| `{row['id']}` | {row['name']} | {row['status']} |")
        lines.append("")
    if cov["primary_hero_powers"]["missing"]:
        lines.append("### 英雄主技能缺失（P1 只要求 Azshara；其余为 P2/P3 长尾）")
        lines.append("")
        for row in cov["primary_hero_powers"]["missing"]:
            lines.append(f"- `{row['id']}` {row['name']}")
        lines.append("")
    lines.append("### P1 18 卡逐卡状态")
    lines.append("")
    lines.append("| id | 名称 | owner | scripted | 静态源码 | hsrl2 参考 |")
    lines.append("|---|---|---|---|---|---|")
    for row in cov["p1"]["rows"]:
        ref = "有" if row["has_hsrl2_ref"] else "无（结构检查）"
        lines.append(f"| `{row['id']}` | {row['name']} | {row['batch_owner']} | "
                     f"{row['status']} | {'✓' if row['in_static_source'] else '—'} | {ref} |")
    lines.append("")
    return "\n".join(lines)


def _dark_paradox_base(cov: Dict[str, Any]) -> str:
    for row in cov["dark_paradox"]:
        if row["id"] == "BG36_360":
            return row["status"]
    return "?"


def _oracle_section(oracle: Dict[str, Any]) -> str:
    lines = ["## 2. hsrl2 oracle 差分（16 张有参考卡 + 2 张结构检查）", ""]
    lines.append("口径：同一卡 id、同一局面（`add_to_board`/`add_to_hand`/出牌/"
                 "施法/回合结束），比较玩家语义可观察量（棋盘 id/攻/血、手牌 id、"
                 "金币、酒馆等级、技能）；RNG 流/事件顺序不计。分类：MATCH / "
                 "CONVENTION_DIFF / FAIL / DEFERRED / STRUCTURAL。")
    lines.append("")
    lines.append("两条 case 的**已声明口径差异**（不是放宽断言，是两侧触发上下文"
                 "本身不同）：")
    lines.append("- `O13` BG31_925 亡语：Rust 取 `CombatPreview{details:false,n:1}` "
                 "replay frames 的死亡帧前后 Naga 属性差；hsrl2 用公开 "
                 "`destroy_minion` 在招募期走同一 `_process_single_death` 亡语路径取"
                 "同差值——比较“效果增量”。")
    lines.append("- `O15` BG22_HERO_007p：hsrl2 侧用公开幂等 "
                 "`wire_hero_power_on_bind(hero, power_id)` 接线 `on_bind`；"
                 "两侧共享“打出一张随从”检查点，比较 `observe()['powers']` 是否"
                 "出现 `BG22_HERO_007p2`。")
    lines.append("")
    lines.append(f"- seeds/构造：`{common.ROOT}` 本机 python3；"
                 f"counts：`{json.dumps(oracle['counts'], ensure_ascii=False)}`")
    lines.append("")
    lines.append("| ID | 卡 | 机制 | 结果 | 说明 |")
    lines.append("|---|---|---|---|---|")
    for row in oracle["rows"]:
        reason = (row.get("reason") or "")[:180]
        lines.append(f"| {row['id']} | `{row['card']}` | {row['category']} | "
                     f"**{row['classification']}** | {reason} |")
    for row in oracle["deferred"]:
        lines.append(f"| {row['id']} | `{row['card']}` | {row['category']} | "
                     f"DEFERRED | {row['reason'][:180]} |")
    for row in oracle["structural"]:
        lines.append(f"| {row['id']} | `{row['card']}` | structural | "
                     f"{row['classification']} | data={row['data_present']} "
                     f"scripted={row['rust_scripted']} forms={len(row['forms'])} |")
    lines.append("")
    fails = [r for r in oracle["rows"] if r["classification"] == "FAIL"]
    if fails:
        lines.append("### FAIL 清单（最小复现：`python3 -m tools.p3_verify.oracle`）")
        lines.append("")
        for row in fails:
            lines.append(f"- `{row['id']}` `{row['card']}`（owner: {row['owner']}）"
                         f"：{row.get('reason')}")
            if row.get("diff"):
                lines.append(f"  - diff: `{json.dumps(row['diff'], ensure_ascii=False)[:400]}`")
        lines.append("")
    lines.append("### 未覆盖 / DEFERRED 原因（不伪造 oracle）")
    lines.append("")
    for row in oracle["deferred"]:
        lines.append(f"- `{row['id']}` `{row['card']}`：{row['reason']}")
    lines.append("")
    return "\n".join(lines)


def _gates_section(gates: Dict[str, Any]) -> str:
    lines = ["## 3. 验收门禁", ""]
    lines.append(f"总判定：**{'PASS' if gates['gate_summary']['pass'] else 'FAIL'}**"
                 f"，耗时 {gates['gate_summary']['elapsed_s']}s（本机 python3，"
                 f"Apple Silicon）。")
    lines.append("")
    lines.append("| 门禁 | 结果 | 耗时 | 证据摘要 |")
    lines.append("|---|---|---|---|")
    for gate in gates["gates"]:
        tail = ""
        notes = gate.get("notes") or []
        if notes:
            tail = "；".join(str(n) for n in notes)[:180]
        elif gate.get("exit_code") is not None:
            tail = f"exit={gate['exit_code']}"
        lines.append(f"| {gate['name']} | {'PASS' if gate.get('passed') else 'FAIL'} "
                     f"| {gate.get('elapsed_s')}s | {tail} |")
    smoke = gates["smoke"]
    lines.append(f"| bot_smoke（8 人 × {smoke['seeds']} seeds） | "
                 f"{'PASS' if smoke['passed'] else 'FAIL'} | {smoke['elapsed_s']}s | "
                 f"crashes={len(smoke['crashes'])}，回合 {smoke.get('turn_min')}..{smoke.get('turn_max')} |")
    det = gates["determinism"]
    lines.append(f"| determinism（同 seed 双跑） | "
                 f"{'PASS' if det['passed'] else 'FAIL'} | {det['elapsed_s']}s | "
                 f"checks={len(det.get('checks') or [])} |")
    lines.append("")
    review = gates["worker_tests_review"]
    lines.append("### worker 测试独立复核（不只看绿）")
    lines.append("")
    lines.append("| 测试文件 | 用例数 | P1 卡覆盖 | 无断言用例 | 复核结论 |")
    lines.append("|---|---:|---|---|---|")
    for name, info in review["files"].items():
        missing = info.get("expected_missing") or []
        verdict = "覆盖完整" if not missing else f"缺口 {missing}"
        lines.append(f"| `tests/{name}.rs` | {info.get('test_count')} | "
                     f"{len(info.get('expected_cards') or []) - len(missing)}/"
                     f"{len(info.get('expected_cards') or [])} | "
                     f"{info.get('tests_without_assert') or '无'} | {verdict} |")
    lines.append("")
    lines.append("人工复核要点（逐卡语义 vs 卡面）：batch A/B 每张卡至少 1 个正向 + "
                 "关键负例（他人/非目标/无触发），并覆盖金色差异值；systems 覆盖 "
                 "Azshara 注册/英雄池/30 攻变身/Conquest 1 金 Discover/无金不可用、"
                 "Dark Paradox 数据映射不变量。用例断言强度：均含具体数值/卡 id 断言。")
    lines.append("")
    return "\n".join(lines)


def build_doc(report: Dict[str, Any]) -> str:
    cov = report["coverage"]
    oracle = report["oracle"]
    gates = report["gates"]
    g = cov["gate"]
    oracle_fail = [r for r in oracle["rows"]
                   if r["classification"] == "FAIL"]
    gates_pass = gates["gate_summary"]["pass"]
    if g["pass"] and not oracle_fail and gates_pass:
        status = ("**PASS**：37 单人池脚本覆盖 0 缺失（P1 门禁通过），"
                  "oracle 差分无 FAIL，验收门禁全绿 → **可进入 RL 阶段**。")
    else:
        parts = []
        if not g["pass"]:
            parts.append("池内覆盖未闭环")
        if oracle_fail:
            parts.append(f"oracle FAIL {len(oracle_fail)} 条")
        if not gates_pass:
            parts.append(f"门禁红：{gates['gate_summary']['failed']}")
        status = ("**FAIL / 未闭环**（" + "；".join(parts) + "）：见 §1/§2/§3 的"
                  "缺失与 FAIL 清单；修复前不建议把该引擎用于 RL 训练。")
    head = [
        "# P3 独立验证与验收门禁（AT 主引擎补完 37 池内内容）",
        "",
        f"> 生成：`python3 -m tools.p3_verify.run_all` ｜ "
        f"{report['meta']['generated_at']} ｜ 耗时 {report['meta']['elapsed_s']}s ｜ "
        f"只读审计（未改 `rust/**`/`data/**`/`hsrl2/**`，未 commit）。",
        f"> 被审引擎：`rust/` fork（`hsbg_engine`，37.0.0.255130）；参照：冻结的 "
        f"`hsrl2`（legacy oracle，37 数据）。",
        "",
        "## 0. 结论先行",
        "",
        status,
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 池内随从覆盖 | {cov['pool_minions']['total']} → missing "
        f"**{g['pool_minions_missing']}** |",
        f"| 池内酒馆法术覆盖 | {cov['pool_spells']['total']} → missing "
        f"**{g['pool_spells_missing']}** |",
        f"| 主英雄技能（129） | missing {len(cov['primary_hero_powers']['missing'])}"
        f"（P1 只要求 Azshara，当前 P1 主技能缺失 **{g['p1_required_missing']}**；"
        f"其余为 Duos/旧替换技能长尾） |",
        f"| P1 18 卡 | missing **{g['p1_required_missing']}**"
        f"（Dark Paradox 经 5 形态覆盖：{_fmt_list(cov['p1'].get('covered_via_forms') or [])}） |",
        f"| oracle 差分 | `{json.dumps(oracle['counts'], ensure_ascii=False)}` |",
        f"| 门禁 | `{json.dumps(gates['gate_summary'], ensure_ascii=False)}` |",
        "",
    ]
    risks = [
        "## 4. 风险与剩余缺口（供 Lead 决定是否进入 RL）",
        "",
        "1. **oracle 覆盖边界**：16 张有参考卡中 **15 张**做了逐卡可比场景"
        "（含 deathrattle 的“效果增量”口径、hero-power 的公开接线、activate 的"
        "不变量口径）；仅 `BG34_925` Rally 1 张 DEFERRED；2 张无参考卡"
        "（BG33_319/BG36_360）用结构检查 + worker 用例复核（不影响 P1 内容门禁，"
        "但该 1 张的等价性证据等级较低）。",
        "2. **Spellcraft 发放时点**：hsrl2 在 on_summon 即发、AT 在回合开始发，"
        "属约定差异（oracle 只比“副本/持有”语义）；训练侧以 AT 行为为准。",
        "3. **数据兼容层**：`data/p2/cards_37.json` 含 288 条 36.6.3 compat 条目，"
        "P1 卡的 `script_data_num_*` 在映射后多为 None（37 文本已内联数值）；"
        "Rust content 以文本数值实现，需避免未来数据重生成时数值漂移。",
        "4. **池内主技能长尾**：129 个主技能中仍有 9 个 missing（Azshara 之外为"
        " Duos/旧替换技能，属 P2/P3 可达性缺口，不阻塞 P1）。",
        "5. **本验证不覆盖**：饰品/法术全量（P2）、异变（P3）、完整 679 场真实"
        "战斗回放差分（需 `tools/diff_replay_combat.py` 在 Rust 侧重放，P3 后续）。",
        "6. **seed 基准**：P3 内容入池改变了固定 seed 的大厅/池抽样，既有测试夹具"
        "已按 37 数据重算（未放宽断言）；**全部 P3 内容合入后建议再冻结一次 seed "
        "基准**（rust/FORK §7 已记）。",
        "",
        "## 5. 复现命令",
        "",
        "```bash",
        "cd rust && python3 -m pip install -e . && cd ..   # 重建扩展（content/数据改动后必须）",
        "python3 -m tools.p3_verify.run_all                # coverage + oracle + gates → runs/p3_verify/",
        "python3 -m tools.p3_verify.coverage               # 仅覆盖审计（P1 门禁）",
        "python3 -m tools.p3_verify.oracle                 # 仅 oracle 差分",
        "python3 -m tools.p3_verify.gates                  # 仅门禁（含 cargo build/test/冒烟/确定性）",
        "cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine --test p3_cards_a",
        "cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine --test p3_cards_b",
        "cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine --test p3_systems",
        "```",
        "",
        "产物：`runs/p3_verify/{coverage.json,oracle.json,gates.json,report.json,summary.md}`"
        "（gitignore）。",
        "",
    ]
    return "\n".join(head) + _coverage_section(cov) + "\n" + \
        _oracle_section(oracle) + "\n" + _gates_section(gates) + "\n" + \
        "\n".join(risks)


def main() -> int:
    path = common.RUNS_DIR / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    doc = build_doc(report)
    DOC.write_text(doc, encoding="utf-8")
    print(f"wrote {DOC} ({len(doc.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
