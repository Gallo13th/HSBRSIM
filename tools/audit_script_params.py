#!/usr/bin/env python
"""语义参数审计 — 防止脚本硬编码数值与 CardDefs 模板参数漂移。

背景（2026-08-21 审计确认的系统性 bug 根因）:
  旧引擎 16+ 张卡的脚本硬编码 Buff(atk=X, health=Y) 与卡牌文本 {0}/{1}
  参数不符（如 Goldrinn 文本 +8/+8、脚本写 4/4），因数据管线丢弃模板
  参数而静默过期。

本工具做两件事:
  1. 静态扫描 hsrl2/scripts/ 中的数值字面量（Buff/Hit 等调用的
     atk=/health=/amount= 位置参数）
  2. 与对应脚本类 docstring "Params:" 行声明的期望值比对;
     无 Params: 声明但存在数值字面量的脚本 → 报警（必须声明）

用法: python tools/audit_script_params.py [--strict]
退出码: 0=通过, 1=有违规（--strict 时 WARNING 也计入）
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "hsrl2" / "scripts"

# 数值型 kwargs（Buff/Hit 类）与位置参数位置
NUMERIC_KWARGS = {"atk", "health", "amount", "count", "damage"}

# 0 值忽略: 生成器不导出 0 值模板参数（`if n != 0`），kwarg 传 0 是
# 结构性占位（如 ApplyRaceAura(health=0)）而非效果数值，无漂移可能
_IGNORE_VALUE = 0


def script_classes(path: Path):
    """Yield (class_name, tree) for each top-level class in a script file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            yield node


def numeric_literals_in(node: ast.FunctionDef) -> list[tuple[int, str, int]]:
    """Find numeric literals passed to atk=/health=/amount=... kwargs."""
    found = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            for kw in sub.keywords:
                if kw.arg in NUMERIC_KWARGS and isinstance(kw.value, ast.Constant):
                    val = kw.value.value
                    if isinstance(val, int) and not isinstance(val, bool) \
                            and val != _IGNORE_VALUE:
                        found.append((kw.lineno, kw.arg, val))
    return found


def params_from_docstring(doc: str | None) -> dict[str, int]:
    """Parse declarations: '{0}=8 {1}=8' 或 'count=4 atk=2'（命名声明）。

    模板式声明的值域用于比对任意 kwarg; 命名式只豁免同名 kwarg 的值。
    返回 {key: value}，模板式键为 '0'/'1' 字符串，命名式为 kwarg 名。
    """
    if not doc:
        return {}
    result = {}
    for m in re.finditer(r"\{(\d)\}\s*=\s*(\d+)", doc):
        result[m.group(1)] = int(m.group(2))
    for m in re.finditer(r"\b([a-zA-Z_]\w*)\s*=\s*(\d+)", doc):
        result[m.group(1)] = int(m.group(2))
    return result


def main() -> int:
    strict = "--strict" in sys.argv
    violations: list[str] = []
    warnings: list[str] = []

    for py in sorted(SCRIPTS_DIR.rglob("*.py")):
        rel = py.relative_to(SCRIPTS_DIR)
        if py.name in ("__init__.py", "registry.py"):
            continue
        if "batches" in rel.parts and py.name == "__init__.py":
            continue
        try:
            classes = list(script_classes(py))
        except SyntaxError as e:
            violations.append(f"{py.name}: SYNTAX ERROR {e}")
            continue
        for cls in classes:
            doc = ast.get_docstring(cls)
            declared = params_from_docstring(doc)
            for fn in cls.body:
                if not isinstance(fn, ast.FunctionDef):
                    continue
                lits = numeric_literals_in(fn)
                if not lits:
                    continue
                if not declared:
                    warnings.append(
                        f"{py.name}:{cls.name}.{fn.name}: numeric literals "
                        f"{[(k, v) for _, k, v in lits]} without 'Params:' "
                        f"declaration in docstring")
                    continue
                # 比对: 字面量值必须在声明值集合内（模板式任意匹配、
                # 命名式仅匹配同名 kwarg）
                declared_values = set(declared.values())
                for lineno, kw, val in lits:
                    named_ok = declared.get(kw) == val
                    if val not in declared_values and not named_ok \
                            and declared_values:
                        violations.append(
                            f"{py.name}:{cls.name}.{fn.name}:{lineno}: "
                            f"{kw}={val} not in declared Params {declared}")

    print(f"Scanned {len(list(SCRIPTS_DIR.glob('*.py')))} script files")
    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  [WARN] {w}")
    if violations:
        print(f"\nVIOLATIONS ({len(violations)}):")
        for v in violations:
            print(f"  [FAIL] {v}")
        return 1
    if strict and warnings:
        return 1
    print("PASS: no parameter drift detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
