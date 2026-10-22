"""应用/校验「战斗语义 P1 修复包」（tmp_diff_fix/deliver3/）。

修复包布局（镜像仓库结构）::

    deliver3/
      manifest.json
      hsrl2/combat.py                          # 剧毒/烈毒 + 顺劈门槛修复
      hsrl2/tests/test_combat_semantics_p1.py  # 8 个回归测试
      FIX_REPORT3.md
      harness_changes/                         # 审查参考（不覆盖根目录）

安全约定：只写 manifest 列出的文件；应用前备份；``--apply`` 需 ``--yes``；
应用后自动跑引擎回归 + 差分 20 场冒烟。

用法::

    python tools/apply_combat_semantics_fix.py --check
    python tools/apply_combat_semantics_fix.py --apply --yes
    python tools/apply_combat_semantics_fix.py --revert --backup tmp_diff_fix/deliver3/backup_...
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
DEFAULT_PACKAGE = ROOT / "tmp_diff_fix" / "deliver3"
ALLOWED_PREFIXES = ("hsrl2/", "hsbg/", "tools/", "tests/", "docs/")
SKIP_NAMES = ("manifest.json", "FIX_REPORT3.md", "README.md")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(package: Path) -> Dict[str, Any]:
    path = package / "manifest.json"
    if not path.exists():
        return {"files": [], "reason": "missing manifest"}
    return json.loads(path.read_text(encoding="utf-8"))


def package_files(package: Path, manifest: Dict[str, Any]) -> List[str]:
    declared = [str(f) for f in manifest.get("files") or []]
    actual: List[str] = []
    for path in package.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(package).as_posix()
        if any(rel == name for name in SKIP_NAMES):
            continue
        if rel.startswith(("backup/", "logs/", "harness_changes/")):
            continue
        if not rel.startswith(ALLOWED_PREFIXES):
            continue
        actual.append(rel)
    return sorted(set(declared) | set(actual))


def check(package: Path, verbose: bool = True) -> int:
    manifest = load_manifest(package)
    files = package_files(package, manifest)
    if verbose:
        print(f"[fix3] package: {package}")
        print(f"[fix3] reason : {manifest.get('reason', '')}")
        print(f"[fix3] patch files: {len(files)}")
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
            if verbose:
                print(f"  {'=' if same else 'M'} {rel}"
                      f"{'（已应用）' if same else '（待应用）'}")
            drift += int(not same)
        else:
            if verbose:
                print(f"  + {rel}（根目录不存在）")
            drift += 1
    return 0 if drift == 0 else 1


def backup_files(package: Path, files: List[str]) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = package / f"backup_{stamp}"
    meta: Dict[str, str] = {}
    for rel in files:
        target = ROOT / rel
        if not target.exists():
            continue
        destination = backup / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, destination)
        meta[rel] = sha256(target)
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "backup.json").write_text(
        json.dumps({"created_at": stamp, "files": meta},
                   ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return backup


def apply(package: Path, *, yes: bool) -> int:
    files = package_files(package, load_manifest(package))
    if not files:
        print("[fix3] 没有可应用文件")
        return 0
    if not yes:
        print("[fix3] 拒绝应用：需要显式 --yes（会覆盖根目录文件，先备份）")
        return 2
    backup = backup_files(package, files)
    print(f"[fix3] backup -> {backup}")
    for rel in files:
        target = ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package / rel, target)
        print(f"[fix3] applied {rel}")
    return run_regression()


def revert(backup: Path) -> int:
    meta_path = backup / "backup.json"
    if not meta_path.exists():
        print(f"[fix3] 备份清单不存在: {meta_path}")
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for rel in meta.get("files", {}):
        source = backup / rel
        if source.exists():
            shutil.copy2(source, ROOT / rel)
            print(f"[fix3] reverted {rel}")
    return 0


def run_regression() -> int:
    commands = [
        [sys.executable, "-m", "pytest", "hsrl2/tests", "tests", "-q"],
        [sys.executable, "tools/diff_replay_combat.py",
         "--traces", "runs/official_traces", "--limit", "20",
         "--json", "runs/diff_semantics_smoke.json",
         "--md", "runs/diff_semantics_smoke.md", "--quiet"],
    ]
    failures = 0
    for command in commands:
        print("[fix3] run:", " ".join(command))
        result = subprocess.run(command, cwd=ROOT)  # noqa: S603
        if result.returncode != 0:
            failures += 1
            print(f"[fix3] FAILED rc={result.returncode}")
    print("[fix3] regression: " + ("OK" if failures == 0 else f"{failures} failed"))
    return 0 if failures == 0 else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="应用/校验战斗语义 P1 修复包")
    parser.add_argument("--package", default=str(DEFAULT_PACKAGE))
    parser.add_argument("--check", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--backup", default=None, help="--revert 的备份目录")
    parser.add_argument("--yes", action="store_true", help="--apply 的明确确认")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    package = Path(args.package).resolve()
    if not package.exists():
        print(f"[fix3] package 不存在: {package}")
        return 2
    if args.revert:
        if not args.backup:
            print("[fix3] --revert 需要 --backup <dir>")
            return 2
        return revert(Path(args.backup))
    if args.apply:
        return apply(package, yes=args.yes)
    return check(package)


if __name__ == "__main__":
    raise SystemExit(main())
