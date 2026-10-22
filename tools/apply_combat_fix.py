"""应用/校验 combat 修复包（Lead 审批后使用）。

修复包布局（``tmp_diff_fix/deliver/``）::

    deliver/
      manifest.json        # {"files": ["hsrl2/combat.py", ...], "reason": ...}
      hsrl2/combat.py      # 镜像仓库结构的**完整文件**
      FIX_REPORT.md

本脚本提供：

* ``--check``（默认）：列出包内文件、与当前根目录差异、manifest 校验；
* ``--apply``：备份根目录对应文件（到 ``<package>/backup_<时间戳>/``）→
  复制包内完整文件 → 跑引擎回归 + 差分冒烟；
* ``--revert --backup <dir>``：从备份还原。

安全约定：只写 manifest 列出的文件；绝不整体覆盖 ``hsrl2/``；应用前
必须存在 ``--yes``（非交互环境下的明确确认）。

用法::

    python tools/apply_combat_fix.py --check
    python tools/apply_combat_fix.py --apply --yes
    python tools/apply_combat_fix.py --revert --backup tmp_diff_fix/deliver/backup_...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKAGE = ROOT / "tmp_diff_fix" / "deliver"
ALLOWED_PREFIXES = ("hsrl2/", "hsbg/", "tools/", "tests/")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(package: Path) -> Dict[str, Any]:
    manifest_path = package / "manifest.json"
    if not manifest_path.exists():
        return {"files": [], "reason": "missing manifest"}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def package_files(package: Path, manifest: Dict[str, Any]) -> List[str]:
    """manifest 声明的文件 + 包内实际存在的镜像文件（后者兜底）。"""
    declared = [str(f) for f in manifest.get("files") or []]
    actual = []
    for path in package.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(package).as_posix()
        if rel.startswith(tuple(p + "/" for p in ("backup", "logs"))) or \
                rel in ("manifest.json", "FIX_REPORT.md", "README.md"):
            continue
        if not rel.startswith(ALLOWED_PREFIXES):
            continue
        actual.append(rel)
    return sorted(set(declared) | set(actual))


def check(package: Path) -> int:
    manifest = load_manifest(package)
    files = package_files(package, manifest)
    print(f"[fix] package: {package}")
    print(f"[fix] reason : {manifest.get('reason', '')}")
    if manifest.get("engine_patch") is False:
        print("[fix] 该修复包**不含引擎代码改动**（engine_patch=false）："
              "根因是日志隐藏上下文，修复在 hsbg/tools 层，已直接落地根目录。")
    if not files:
        print("[fix] patch files: 0")
        return 0
    print(f"[fix] patch files: {len(files)}")
    drift = 0
    for rel in files:
        source = package / rel
        target = ROOT / rel
        if not source.exists():
            print(f"  ! missing in package: {rel}")
            drift += 1
            continue
        if target.exists():
            same = sha256(source) == sha256(target)
            print(f"  {'=' if same else 'M'} {rel}"
                  f"{'（与根目录一致）' if same else '（待应用）'}")
            drift += int(not same)
        else:
            print(f"  + {rel}（根目录不存在）")
            drift += 1
    return 0 if drift == 0 else 1


def backup_files(package: Path, files: List[str]) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = package / f"backup_{stamp}"
    for rel in files:
        target = ROOT / rel
        if not target.exists():
            continue
        destination = backup_dir / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, destination)
    meta = {"created_at": stamp,
            "files": {rel: sha256(ROOT / rel) for rel in files
                      if (ROOT / rel).exists()}}
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "backup.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return backup_dir


def apply(package: Path, *, yes: bool) -> int:
    manifest = load_manifest(package)
    files = package_files(package, manifest)
    if manifest.get("engine_patch") is False or not files:
        print("[fix] 没有可应用的引擎文件；该包是**验证/证据包**。")
        print("[fix] harness 侧修复（hsbg/bridge/trace.py、tools/diff_*.py）"
              "已在根目录生效；如需回滚请用 git 或备份。")
        return 0
    if not yes:
        print("[fix] 拒绝应用：需要显式 --yes 确认（会覆盖根目录文件，先备份）")
        return 2
    backup_dir = backup_files(package, files)
    print(f"[fix] backup -> {backup_dir}")
    for rel in files:
        source = package / rel
        target = ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(f"[fix] applied {rel}")
    return run_regression()


def revert(package: Path, backup: Path) -> int:
    meta_path = backup / "backup.json"
    if not meta_path.exists():
        print(f"[fix] 备份清单不存在: {meta_path}")
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for rel in meta.get("files", {}):
        source = backup / rel
        target = ROOT / rel
        if source.exists():
            shutil.copy2(source, target)
            print(f"[fix] reverted {rel}")
    return 0


def run_regression() -> int:
    commands = [
        [sys.executable, "-m", "pytest", "hsrl2/tests", "-q"],
        [sys.executable, "tools/diff_replay_combat.py",
         "--traces", "runs/official_traces", "--limit", "20",
         "--json", "runs/diff_apply_smoke.json",
         "--md", "runs/diff_apply_smoke.md", "--quiet"],
    ]
    failures = 0
    for command in commands:
        print("[fix] run:", " ".join(command))
        result = subprocess.run(command, cwd=ROOT)  # noqa: S603
        if result.returncode != 0:
            failures += 1
            print(f"[fix] FAILED rc={result.returncode}")
    print("[fix] regression: " + ("OK" if failures == 0 else f"{failures} failed"))
    return 0 if failures == 0 else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="应用/校验 combat 修复包")
    parser.add_argument("--package", default=str(DEFAULT_PACKAGE))
    parser.add_argument("--check", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--backup", default=None,
                        help="--revert 时使用的备份目录")
    parser.add_argument("--yes", action="store_true",
                        help="--apply 的明确确认")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    package = Path(args.package).resolve()
    if not package.exists():
        print(f"[fix] package 不存在: {package}")
        return 2
    if args.revert:
        if not args.backup:
            print("[fix] --revert 需要 --backup <dir>")
            return 2
        return revert(package, Path(args.backup))
    if args.apply:
        return apply(package, yes=args.yes)
    return check(package)


if __name__ == "__main__":
    raise SystemExit(main())
