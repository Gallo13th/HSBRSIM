#!/usr/bin/env python
"""空转测试审计 — 把脚本钩子换成 no-op 后仍通过的测试（"测试有没有信息量"）。

背景（2026-09-02 三连对抗审查沉淀，见 EFFECT_SCRIPT_SOP §16 末段）:
四件套只验证"有脚本 / 参数一致 / 接线存在"，**不验证测试本身是否真的
观察到了效果**。把被测脚本类的全部钩子替换成 `pass` 后仍然通过的测试，
对"效果是否存在"零信息量——最典型的是纯负面断言（"空板落空"）、
战后回滚断言（不加战斗内探针就分不清"加了又回滚"与"从没加过"）、
以及只重读输入值的断言（"T6 上限还是 T6"）。

本工具对每个 `batch_*.py` + 同名 `test_batch_*.py` 配对:
  1. 基线跑一次（不注入）→ 记录通过的 nodeid 集合
  2. 把该批全部脚本类的钩子换成 no-op 再跑一次
  3. 报告"两次都通过"的测试（存活者 = 空转测试候选）

判定口径:
  - **结构性测试**（注册表 / 卡定义 / 数据表一致性 / `needs_target`
    声明）本就与钩子无关，允许存活——按 nodeid 关键词白名单标注。
  - `--strict`: 任意一个测试类**全部**通过的测试都是存活者 → 该类零
    信息量 → 退出码 1（"类级全空转"是最坏第三态的下限门禁）。
  - 默认: 仅报告（退出码 0），供主线逐条判断要不要补正对照。

用法:
  python tools/audit_vacuous_tests.py                 # 报告
  python tools/audit_vacuous_tests.py --strict        # 类级全空转 → exit 1
  python tools/audit_vacuous_tests.py --batch trinkets3 --verbose
退出码: 0=通过/仅报告, 1=strict 下有类级全空转
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.audit_script_wiring import CHECKED_HOOK_NAMES  # noqa: E402

BATCH_DIR = ROOT / "hsrl2" / "scripts" / "batches"
TEST_DIR = ROOT / "hsrl2" / "tests"

# 不打成 no-op 的协议方法: 它们是"效果能不能发生"的门禁，改掉会让测试
# 失败在错误的原因上（本工具要隔离的是**效果体**是否空转）
_KEEP = {"available", "target_candidates"}

# 结构性测试白名单（与钩子无关，存活属预期）:
#   注册表/卡定义/数据表一致性 + DEFERRED·AMBIGUOUS 台账守卫 +
#   引擎级契约（不经过本批脚本钩子）
_STRUCTURAL = re.compile(
    r"(registry|registered|card_definition|is_targeted|tier_table|"
    r"token_lookup|all_ids|all_registered|thresholds_match|"
    r"defines_registered|is_in_offer_pool|pool_membership|"
    r"carddef|num_matches_text|deferred|ambiguous|param_integrity|"
    r"data_drift|datadrift|pure_keyword|keyword_card|not_actively|"
    r"engine|opponentreference|card_text_matches)", re.IGNORECASE)


def _noop(*_args, **_kwargs):
    return None


class _OutcomeCollector:
    """pytest 插件: 收集每个 nodeid 的最终结果。"""

    def __init__(self):
        self.outcomes: dict[str, str] = {}

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or (report.when == "setup" and report.failed):
            prev = self.outcomes.get(report.nodeid)
            if prev != "failed":
                self.outcomes[report.nodeid] = report.outcome


class _Mutator:
    """pytest 插件: 收集完成后把脚本类钩子换成 no-op，结束时还原。"""

    def __init__(self, module_name: str, enabled: bool = True):
        self.module_name = module_name
        self.enabled = enabled
        self.patched: list[tuple[object, str, object]] = []

    def pytest_collection_finish(self, session):  # noqa: ARG002
        if not self.enabled:
            return
        module = importlib.import_module(self.module_name)
        for name, obj in vars(module).items():
            if not isinstance(obj, type):
                continue
            if getattr(obj, "__module__", None) != module.__name__:
                continue
            for hook in sorted(CHECKED_HOOK_NAMES - _KEEP):
                if not hasattr(obj, hook):
                    continue
                original = obj.__dict__.get(hook)
                if original is None:
                    continue
                self.patched.append((obj, hook, original))
                setattr(obj, hook, staticmethod(_noop))

    def pytest_sessionfinish(self, session, exitstatus):  # noqa: ARG002
        for cls, hook, original in self.patched:
            setattr(cls, hook, original)
        self.patched.clear()


def _engine_only_classes(test_path: Path) -> set[str]:
    """测试类 docstring 显式标注 `@engine-only` 的类。

    这类测试验证的是**引擎数据通道/关键词声明**（纯关键词卡、磁力目标
    扩展、数值占位符一致性），本批脚本类没有钩子可注入——存活属预期。
    用显式标注代替关键词白名单，避免误放行真正空转的行为测试。
    """
    module_name = f"hsrl2.tests.{test_path.stem}"
    try:
        module = importlib.import_module(module_name)
    except Exception:            # noqa: BLE001 — 导入失败交给 pytest 报
        return set()
    out = set()
    for name, obj in vars(module).items():
        if isinstance(obj, type) and "@engine-only" in (obj.__doc__ or ""):
            out.add(f"{test_path.name}::{name}")
    return out


def _run_pytest(test_path: Path, plugin) -> dict[str, str]:
    collector = _OutcomeCollector()
    args = [str(test_path), "-q", "--no-header", "-p", "no:cacheprovider",
            "--tb=no"]
    with contextlib.redirect_stdout(io.StringIO()):
        pytest.main(args, plugins=[collector, plugin])
    return collector.outcomes


def _passing(outcomes: dict[str, str]) -> set[str]:
    return {n for n, o in outcomes.items() if o == "passed"}


def _test_classes(nodeids) -> dict[str, set[str]]:
    classes: dict[str, set[str]] = defaultdict(set)
    for n in nodeids:
        # hsrl2/tests/test_x.py::TestFoo::test_bar
        parts = n.split("::")
        if len(parts) >= 3:
            classes[f"{Path(parts[0]).name}::{parts[1]}"].add(n)
        else:
            classes[f"{Path(parts[0]).name}::<module>"].add(n)
    return classes


def audit_batch(stem: str, verbose: bool) -> dict:
    """返回 {batch, test_file, total, survivors, vacuous_classes}。"""
    from hsrl2.scripts.batches import __name__ as _pkg  # noqa: F401
    test_path = TEST_DIR / f"test_{stem}.py"
    if not test_path.exists():
        return {"batch": stem, "test_file": None}
    module_name = f"hsrl2.scripts.batches.{stem}"
    baseline = _passing(_run_pytest(test_path, _Mutator("", enabled=False)))
    mutated = _passing(_run_pytest(test_path, _Mutator(module_name)))
    survivors = sorted(baseline & mutated)
    engine_only = _engine_only_classes(test_path)
    vacuous_classes = []
    for cls, members in _test_classes(baseline).items():
        if cls in engine_only:
            continue
        members_baseline = {m for m in members if m in baseline}
        if not members_baseline or not members_baseline <= set(mutated):
            continue
        # 全是结构性测试（注册表/卡定义）→ 与钩子无关，不算发现
        if all(_STRUCTURAL.search(m) for m in members_baseline):
            continue
        vacuous_classes.append(cls)
    if verbose:
        pass
    return {
        "batch": stem, "test_file": test_path.name,
        "total": len(baseline), "survivors": survivors,
        "vacuous_classes": sorted(vacuous_classes),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="类级全空转 → 退出码 1")
    ap.add_argument("--batch", default=None,
                    help="只审计该批次（如 trinkets3 → batch_trinkets3.py）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    stems = sorted(p.stem for p in BATCH_DIR.glob("batch_*.py"))
    if args.batch:
        want = args.batch if args.batch.startswith("batch_") \
            else f"batch_{args.batch}"
        stems = [s for s in stems if s == want]
        if not stems:
            print(f"未找到批次 {args.batch}", file=sys.stderr)
            return 2

    findings = 0
    reported = 0
    for stem in stems:
        res = audit_batch(stem, args.verbose)
        if res.get("test_file") is None:
            continue
        reported += 1
        surv = res["survivors"]
        structural = [s for s in surv if _STRUCTURAL.search(s)]
        behavioral = [s for s in surv if not _STRUCTURAL.search(s)]
        status = "OK" if not behavioral and not res["vacuous_classes"] \
            else "WARN"
        print(f"[{status}] {res['batch']}: {res['total']} passed, "
              f"{len(surv)} survived mutation "
              f"({len(structural)} structural / {len(behavioral)} behavioral)")
        for n in behavioral:
            print(f"        - {n.split('::', 1)[-1]}")
        for cls in res["vacuous_classes"]:
            print(f"        !! 类级全空转: {cls}")
        findings += len(res["vacuous_classes"])

    print(f"\n扫描 {reported} 个批次; 类级全空转测试类 {findings} 个")
    if args.strict and findings:
        print("FAIL: 存在类级全空转的测试类（该批测试对效果零信息量）")
        return 1
    print("PASS: 无类级全空转" if not findings else
          "WARN: 有类级全空转（strict 下失败）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
