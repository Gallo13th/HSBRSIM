"""P3 验证公共设施：路径、37 数据、Rust content 源码扫描、运行时 catalog。

口径说明见 `docs/P3_VERIFICATION.md` §1：

* **37 池数据** = `data/p2/cards_37.json`（AutoTavern schema，37.0.0.255130 +
  36.6.3 compat）。池标志用数据字段 `pools`，不按 id 前缀猜；
* **Rust content 注册表** = `rust/crates/hsbg-engine/src/content/*.rs` 的
  `scripts()` / `scripts_pN()` 函数体字面量 + `content/mod.rs::all_scripts()`
  的模块拼接顺序（静态）；**运行时真值** = 已编译 `hsbg_engine.catalog_json()`
  的 `scripted` / `implemented` 字段（registry 展开 golden 后的结果）；
* **keyword-only 卡**（AT `script::implemented` 口径）= 卡面去掉关键词/标点
  后为空，不需要脚本；缺失=既无脚本又非 keyword-only。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
RUST = ROOT / "rust"
ENGINE_CRATE = RUST / "crates" / "hsbg-engine"
CONTENT_DIR = ENGINE_CRATE / "src" / "content"
CARDS_37 = ROOT / "data" / "p2" / "cards_37.json"
RUNS_DIR = ROOT / "runs" / "p3_verify"
HSRL2_SCRIPTS = ROOT / "hsrl2" / "scripts"

#: P1 必须集合（docs/PORTING_37_PLAN.md §5.2）：15 池内随从 + 1 主英雄技能 + 2 池内法术。
P1_MINIONS = [
    "BG23_002", "BG26_505", "BG27_514", "BG31_035", "BG31_920",
    "BG31_925", "BG32_835", "BG32_837", "BG33_319", "BG34_925",
    "BG35_921", "BG36_360", "BG36_508", "BG36_622", "BG36_921",
]
P1_HERO_POWERS = ["BG22_HERO_007p"]
P1_SPELLS = ["BG32_815", "BG35_922"]

#: 有 hsrl2 Python 参考实现的 P1 卡（16 = 13 随从 + 1 主技能 + 2 法术）；
#: 无参考：BG33_319 / BG36_360（结构检查，不伪造 oracle）。
P1_WITH_HSRL2_REF = [
    "BG23_002", "BG26_505", "BG27_514", "BG31_035", "BG31_920",
    "BG31_925", "BG32_835", "BG32_837", "BG34_925", "BG35_921",
    "BG36_508", "BG36_622", "BG36_921",
    "BG22_HERO_007p", "BG32_815", "BG35_922",
]
P1_NO_REF = ["BG33_319", "BG36_360"]

#: 批次归属（用于把缺失项路由给 worker）
P1_BATCH = {
    "engine-fixer": ["BG23_002", "BG26_505", "BG27_514", "BG31_035",
                     "BG31_920", "BG31_925", "BG32_835", "BG32_837"],
    "content-delta-analyst": ["BG33_319", "BG34_925", "BG35_921",
                              "BG36_508", "BG36_622", "BG36_921",
                              "BG32_815", "BG35_922"],
    "rust-engine-forker": ["BG22_HERO_007p", "BG36_360"],
}


def load_cards_37() -> Dict[str, Dict[str, Any]]:
    data = json.loads(CARDS_37.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data["cards"]}


def cards_37_meta() -> Dict[str, Any]:
    return json.loads(CARDS_37.read_text(encoding="utf-8"))["meta"]


def pool_minions(cards: Dict[str, Dict[str, Any]]) -> List[str]:
    """单人池随从：kind=minion 且 pools 含 'minion'（277，含 5 个 Dark Paradox 形态）。"""
    return sorted(cid for cid, c in cards.items()
                  if c.get("kind") == "minion" and "minion" in (c.get("pools") or []))


def pool_spells(cards: Dict[str, Dict[str, Any]]) -> List[str]:
    """单人池酒馆法术：kind=tavern_spell 且 pools 含 'spell'（73；Duos 已被数据管线剔除）。"""
    return sorted(cid for cid, c in cards.items()
                  if c.get("kind") == "tavern_spell"
                  and "spell" in (c.get("pools") or []))


def hero_primary_powers(cards: Dict[str, Dict[str, Any]]) -> List[str]:
    """所有英雄记录的主技能 id（唯一化；37 数据 129 个）。"""
    return sorted({c["hero_power"] for c in cards.values()
                   if c.get("kind") == "hero" and c.get("hero_power")})


# ══════════════════════════════════════════════════════════════════════
# Rust content 源码静态扫描
# ══════════════════════════════════════════════════════════════════════

#: `pub fn scripts()` / `pub fn scripts_p1()` …；返回类型固定 `Vec<(&'static str, Script)>`
_FN_RE = re.compile(
    r"pub\s+fn\s+(scripts(?:_p\d+)?)\s*\(\s*\)\s*->\s*"
    r"Vec\s*<\s*\(\s*&\s*'static\s+str\s*,\s*Script\s*\)\s*>\s*\{")
_STR_RE = re.compile(r'"([A-Za-z][A-Za-z0-9_]*)"')


def _balanced_body(text: str, open_brace: int) -> str:
    """从 `{` 起做花括号配平（跳过字符串/字符/行注释/块注释）。"""
    depth = 0
    i = open_brace
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
        elif ch == "'":  # 字符字面量或生命周期；粗粒度跳过
            i += 1
            while i < n and text[i] != "'":
                i += 2 if text[i] == "\\" else 1
        elif ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1:i]
        i += 1
    raise ValueError("unbalanced braces in scripts() body")


def static_registrations(content_dir: Path = CONTENT_DIR) -> Dict[str, Any]:
    """静态解析 content/*.rs 的脚本注册表。

    返回 ``{"by_id": {id: [module...]}, "by_module": {module: [id...]},
    "functions": [...], "files": n}``。
    """
    by_id: Dict[str, List[str]] = {}
    by_module: Dict[str, List[str]] = {}
    functions: List[Dict[str, Any]] = []
    files = sorted(content_dir.glob("*.rs"))
    for path in files:
        if path.name == "mod.rs":
            continue
        text = path.read_text(encoding="utf-8")
        module = path.stem
        ids: List[str] = []
        for m in _FN_RE.finditer(text):
            body = _balanced_body(text, m.end() - 1)
            fn_ids = _STR_RE.findall(body)
            ids.extend(fn_ids)
            functions.append({"module": module, "fn": m.group(1),
                              "ids": len(fn_ids)})
        if ids:
            by_module[module] = sorted(set(ids))
            for cid in set(ids):
                by_id.setdefault(cid, []).append(module)
    return {
        "by_id": {k: sorted(v) for k, v in sorted(by_id.items())},
        "by_module": by_module,
        "functions": functions,
        "files": len(files),
        "module_count": len(by_module),
        "id_count": len(by_id),
    }


# ══════════════════════════════════════════════════════════════════════
# 运行时真值（已编译 hsbg_engine.catalog_json）
# ══════════════════════════════════════════════════════════════════════

def runtime_catalog() -> Optional[Dict[str, Dict[str, Any]]]:
    """已安装 hsbg_engine 的 catalog（id -> 记录）；未安装/未构建返回 None。"""
    try:
        import hsbg_engine  # type: ignore
    except Exception:  # noqa: BLE001 - 未安装属预期
        return None
    records = json.loads(hsbg_engine.catalog_json())
    return {rec["id"]: rec for rec in records}


def engine_build_status() -> Dict[str, Any]:
    """已编译扩展是否为当前源码构建（改 content 后必须 rebuild 才生效）。"""
    try:
        import hsbg_engine  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"installed": False, "error": f"{type(exc).__name__}: {exc}"}
    info = hsbg_engine.build_info()
    try:
        current = bool(hsbg_engine.build_is_current())
    except Exception:  # noqa: BLE001
        current = None
    try:
        data = hsbg_engine.data_info()
    except Exception:  # noqa: BLE001
        data = None
    return {
        "installed": True,
        "build_info": info,
        "build_is_current": current,
        "data_info": data,
        "n_actions": int(hsbg_engine.N_ACTIONS),
    }


# ══════════════════════════════════════════════════════════════════════
# 其它
# ══════════════════════════════════════════════════════════════════════

def run(cmd: List[str], *, cwd: Optional[Path] = None, timeout: int = 900,
        env_extra: Optional[Dict[str, str]] = None,
        tail_limit: int = 4000) -> Dict[str, Any]:
    """执行命令并记录输出/耗时/退出码（不抛异常，便于门禁报告）。"""
    import time
    env = dict(os.environ)
    env.setdefault("PATH", "")
    cargo_bin = str(Path.home() / ".cargo" / "bin")
    if cargo_bin not in env["PATH"].split(os.pathsep):
        env["PATH"] = cargo_bin + os.pathsep + env["PATH"]
    if env_extra:
        env.update(env_extra)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd or ROOT), env=env,
                              capture_output=True, text=True, timeout=timeout)
        return {
            "cmd": cmd,
            "exit_code": proc.returncode,
            "elapsed_s": round(time.time() - t0, 2),
            "stdout_tail": proc.stdout[-tail_limit:],
            "stderr_tail": proc.stderr[-tail_limit:],
        }
    except FileNotFoundError as exc:
        return {"cmd": cmd, "exit_code": 127,
                "elapsed_s": round(time.time() - t0, 2),
                "error": str(exc)}
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "exit_code": 124,
                "elapsed_s": round(time.time() - t0, 2),
                "error": f"timeout after {timeout}s"}


def hsrl2_reference_files(ids: Iterable[str]) -> Dict[str, List[str]]:
    """在 hsrl2/scripts 中定位每个卡 id 出现的文件（相对路径），用于核对参考存在性。"""
    files = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
             for p in HSRL2_SCRIPTS.rglob("*.py")}
    out: Dict[str, List[str]] = {}
    for cid in ids:
        hits = [name for name, text in files.items() if f'"{cid}"' in text
                or f"'{cid}'" in text]
        out[cid] = sorted(hits)
    return out


def write_json(name: str, payload: Any) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def main() -> int:  # pragma: no cover - 调试入口
    print("ROOT", ROOT)
    cards = load_cards_37()
    print("pool minions", len(pool_minions(cards)))
    print("pool spells", len(pool_spells(cards)))
    print("primary powers", len(hero_primary_powers(cards)))
    reg = static_registrations()
    print("static registry:", reg["id_count"], "ids /",
          reg["module_count"], "modules")
    print("runtime:", json.dumps(engine_build_status(), ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
