#!/usr/bin/env python3
"""重算 `docs/agents/TRINKET_LEDGER.md`（饰品迁移台账）。

口径（与历史手工版一致）:
  - 商店可提供集 = `CardDB.trinket_offer_pool()`
  - 已注册 = 该集合 ∩ `hsrl2.scripts.REGISTRY`
  - 未注册明细按 20 张一片，列出 id / 档位（spell_school 11=Lesser、
    12=Greater）/ 关联卡（`CardDef.evolution_card_id` → `db.by_dbf`）/
    名称 / 文本（换行压成空格，`|` 转义）
  - 全域（含 token / 升级变体）= 饰品类（card_type 44）全量

用法:
    python tools/generate_trinket_ledger.py            # 写回台账
    python tools/generate_trinket_ledger.py --check     # 只校验是否最新
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
LEDGER = ROOT / "docs" / "agents" / "TRINKET_LEDGER.md"


def _text(defn) -> str:
    raw = (defn.text or "").replace("\n", " ").replace("|", "\\|")
    return " ".join(raw.split())


def build() -> str:
    from hsrl2.db import CardDB
    import hsrl2.scripts  # noqa: F401  （注册全部批次）
    from hsrl2.scripts import REGISTRY
    from hsrl2.tags import CardType

    db = CardDB.load(DATA_DIR)
    pool = db.trinket_offer_pool()
    unreg = [d for d in pool if d.id not in REGISTRY]
    registered = len(pool) - len(unreg)
    coverage = round(100 * registered / len(pool)) if pool else 0
    all_trinkets = [d for d in db._by_id.values()  # noqa: SLF001
                    if d.card_type == CardType.BACON_TRINKET]
    all_registered = sum(1 for d in all_trinkets if d.id in REGISTRY)

    out = []
    out.append("# 饰品迁移台账 — 基线 36.2.2 (S14)\n")
    out.append("来源: `CardDB.trinket_offer_pool()`（商店可提供集，排除 "
               "BG30_Trinket_* 内部 token\n与有同名本体的 t/t2 升级变体）"
               "∩/∖ `hsrl2.scripts.REGISTRY`。\n（自动生成: "
               "`python tools/generate_trinket_ledger.py`）\n")
    out.append(f"商店可提供: {len(pool)}；已注册: **{registered}**；"
               f"未注册: **{len(unreg)}**；商店池覆盖率 {coverage}%\n")
    out.append(f"全域（含 token/升级变体）: 饰品类 {len(all_trinkets)} 张，"
               f"已注册 {all_registered} 张\n")
    out.append("档位: spell_school 11 = Lesser (T6 档)，12 = Greater (T9 档)。\n"
               "数值一律 `CardDef.num(i)`；金色 = `db.golden_version(def)`；"
               "随机走 `game.rng`；\n二态铁律: CORRECT 或 DEFERRED 撤注册"
               "（SOP §6b）。\n")
    out.append("## 未注册明细（派发源；每 20 张一片）\n")
    if not unreg:
        out.append("（无未注册饰品——商店池 100% 覆盖）\n")
    for idx in range(0, len(unreg), 20):
        chunk = unreg[idx:idx + 20]
        out.append(f"### 片 {idx // 20 + 1}: {chunk[0].id} … "
                   f"{chunk[-1].id}（{len(chunk)} 张）\n")
        out.append("| id | 档 | 关联卡 | 名称 | 文本 |")
        out.append("|----|----|--------|------|------|")
        for d in chunk:
            rel = db.by_dbf(d.evolution_card_id) \
                if d.evolution_card_id else None
            rel_name = rel.name if rel is not None else "—"
            school = d.spell_school if d.spell_school else "—"
            out.append(f"| `{d.id}` | {school} | {rel_name} | {d.name} | "
                       f"{_text(d)} |")
        out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只检查台账是否为最新（不写回）")
    args = ap.parse_args()
    content = build()
    if args.check:
        old = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else ""
        if old != content:
            print("FAIL: TRINKET_LEDGER.md 不是最新——请运行 "
                  "python tools/generate_trinket_ledger.py", file=sys.stderr)
            return 1
        print("PASS: TRINKET_LEDGER.md 已是最新")
        return 0
    LEDGER.write_text(content, encoding="utf-8")
    print(f"wrote {LEDGER.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
