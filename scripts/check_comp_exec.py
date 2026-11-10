#!/usr/bin/env python3
"""自检 data/comp_exec.json（31 套酒馆战棋阵容的可执行操作规格）。

校验项：
  1. 所有卡名（loops.buy/keep、econ、amplifiers、position、beneficiary=card）都能在
     hsbg_engine.catalog_json() 里解析，且 in_pool=True；失败时报出套号与卡名。
  2. beneficiary.kind=race 时，统计所有 loop 的 keep+buy 里 races 含该种族的卡数；
     < min_count 时必须在 deficit_note 里显式写“额外补 X”，否则报错。
  3. beneficiary.kind=mechanic 时，统计 keep+buy 里 text_zh 含该机制的卡数（同上）。
  4. beneficiary.kind=card 时，该卡必须在某个 loop.keep 里，且 in_pool。
  5. 结构校验：31 条、id 唯一、loop 字段/phase、keep ≤ keep_max_slots、
     start_window、checklist、evidence 行号、unavailable 不与卡池冲突且正文有引用。
  6. 输出 runs/comp_exec_check.md 自检表（无论成败都写）。

用法：
    PYTHONPATH=rust/python:. /home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python \
        scripts/check_comp_exec.py
    python scripts/check_comp_exec.py --json data/comp_exec.json --out runs/comp_exec_check.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "rust", "python"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import hsbg_engine  # noqa: E402

MECHANICS = ("亡语", "战吼", "回合结束", "磁力", "进击", "酒馆法术")
RACE_ZH = {
    "DRAGON": "龙", "UNDEAD": "亡灵", "DEMON": "恶魔", "BEAST": "野兽",
    "MURLOC": "鱼人", "MECHANICAL": "机械", "ELEMENTAL": "元素",
    "QUILBOAR": "野猪人", "PIRATE": "海盗", "ABERRATION": "畸变怪", "ALL": "全类型",
}
REQUIRED_TOP = (
    "id", "name", "beneficiary", "loops", "keep_max_slots", "position",
    "start_window", "econ", "amplifiers", "checklist", "evidence",
)
CARD_LIST_FIELDS = ("econ", "amplifiers")
LOOP_REQUIRED = ("name", "phase", "buy", "play_then_sell", "keep", "note")


class Checker:
    def __init__(self, comps, catalog):
        self.comps = comps
        self.catalog = catalog
        self.by_name = {}
        for c in catalog:
            nm = c.get("name_zh")
            if nm:
                self.by_name.setdefault(nm, []).append(c)
        self.errors = []
        self.warnings = []
        self.rows = []

    # ---------- helpers ----------
    def err(self, cid, msg):
        self.errors.append(f"套号 {cid}：{msg}")

    def warn(self, cid, msg):
        self.warnings.append(f"套号 {cid}：{msg}")

    def resolve(self, name):
        """卡名 → (cid, card)；只接受 in_pool。返回 (None, None) 表示不可解析。"""
        cs = self.by_name.get(name) or []
        for c in cs:
            if c.get("in_pool"):
                return int(c["cid"]), c
        return None, None

    def card_races(self, name):
        _cid, c = self.resolve(name)
        return set(c.get("races") or []) if c else set()

    def card_text(self, name):
        _cid, c = self.resolve(name)
        return (c.get("text_zh") or "") if c else ""

    def narrative(self, e):
        parts = [e["beneficiary"].get("why", "")]
        for lp in e.get("loops") or []:
            parts.append(str(lp.get("note", "")))
        parts.append(str(e.get("evidence", "")))
        parts.extend(str(x) for x in (e.get("checklist") or []))
        sw = e.get("start_window")
        if isinstance(sw, dict):
            parts.append(str(sw.get("why", "")))
        parts.append(str(e.get("deficit_note", "")))
        return "\n".join(parts)

    # ---------- per-entry ----------
    def check_entry(self, e, idx):
        cid = str(e.get("id") or f"#{idx}")
        name = str(e.get("name") or "?")
        for k in REQUIRED_TOP:
            if k not in e:
                self.err(cid, f"{name} 缺字段 {k}")
                return
        if not re.fullmatch(r"\d{2}", cid):
            self.err(cid, f"id 必须是两位数字字符串，实际 {cid!r}")

        # ---- beneficiary ----
        ben = e["beneficiary"]
        if not isinstance(ben, dict):
            self.err(cid, "beneficiary 必须是对象")
            return
        kind = ben.get("kind")
        value = ben.get("value")
        min_count = ben.get("min_count")
        why = str(ben.get("why") or "")
        if kind not in ("race", "card", "mechanic"):
            self.err(cid, f"beneficiary.kind={kind!r} 非法（应为 race/card/mechanic）")
        if not isinstance(value, str) or not value:
            self.err(cid, "beneficiary.value 必须是非空字符串")
        if not isinstance(min_count, int) or min_count < 1:
            self.err(cid, "beneficiary.min_count 必须是 ≥1 的整数")
        if len(why) < 15:
            self.err(cid, "beneficiary.why 太短，必须解释“为什么需要这个受益者”")

        # ---- loops ----
        loops = e.get("loops")
        if not isinstance(loops, list) or not loops:
            self.err(cid, "loops 必须是非空数组")
            loops = []
        all_names = []          # (角色, 卡名)
        for li, lp in enumerate(loops):
            tag = f"loops[{li}]({lp.get('name', '?')})"
            if not isinstance(lp, dict):
                self.err(cid, f"{tag} 必须是对象")
                continue
            for k in LOOP_REQUIRED:
                if k not in lp:
                    self.err(cid, f"{tag} 缺字段 {k}")
            ph = lp.get("phase")
            if not (isinstance(ph, list) and len(ph) == 2
                    and all(isinstance(x, int) for x in ph) and 1 <= ph[0] <= ph[1]):
                self.err(cid, f"{tag}.phase 必须是 [起回合, 止回合] 且 1≤起≤止")
            pts = lp.get("play_then_sell")
            if not isinstance(pts, bool):
                self.err(cid, f"{tag}.play_then_sell 必须是布尔值")
            buy = lp.get("buy")
            keep = lp.get("keep")
            if not isinstance(buy, list) or not buy:
                self.err(cid, f"{tag}.buy 必须是非空数组")
                buy = []
            if not isinstance(keep, list) or not keep:
                self.err(cid, f"{tag}.keep 必须是非空数组")
                keep = []
            if not str(lp.get("note") or "").strip():
                self.err(cid, f"{tag}.note 不能为空")
            for role, arr in (("buy", buy), ("keep", keep)):
                for nm in arr:
                    all_names.append((f"{tag}.{role}", nm))

        # ---- top-level card lists / position ----
        for f in CARD_LIST_FIELDS:
            v = e.get(f)
            if not isinstance(v, list):
                self.err(cid, f"{f} 必须是数组")
                continue
            for nm in v:
                all_names.append((f, nm))
        pos = e.get("position")
        if not isinstance(pos, list):
            self.err(cid, "position 必须是数组")
            pos = []
        for pi, p in enumerate(pos):
            tag = f"position[{pi}]"
            if not isinstance(p, dict):
                self.err(cid, f"{tag} 必须是对象")
                continue
            for k in ("card", "adjacent_to", "why"):
                if k not in p:
                    self.err(cid, f"{tag} 缺字段 {k}")
            if isinstance(p.get("card"), str):
                all_names.append((tag + ".card", p["card"]))
            adj = p.get("adjacent_to")
            if not isinstance(adj, list) or not adj:
                self.err(cid, f"{tag}.adjacent_to 必须是非空数组")
            else:
                for nm in adj:
                    all_names.append((tag + ".adjacent_to", nm))
            if len(str(p.get("why") or "")) < 10:
                self.err(cid, f"{tag}.why 太短")
        if kind == "card" and isinstance(value, str):
            all_names.append(("beneficiary.value", value))

        # ---- name resolution ----
        bad = []
        for role, nm in all_names:
            if not isinstance(nm, str) or not nm:
                self.err(cid, f"{role} 里有非法卡名 {nm!r}")
                continue
            cid_of, _c = self.resolve(nm)
            if cid_of is None:
                bad.append((role, nm))
                self.err(cid, f"卡名 {nm!r}（{role}）无法解析为 in_pool 卡")
        # 去重后作为“命中池”
        names = sorted({nm for _r, nm in all_names if isinstance(nm, str) and self.resolve(nm)[0] is not None})

        # ---- beneficiary 判定 + 命中数 ----
        hit, need, hit_names, deficit = 0, int(min_count or 1), [], False
        if kind == "race":
            race = value
            if race not in RACE_ZH:
                self.err(cid, f"beneficiary.value={race!r} 不是已知种族（{sorted(RACE_ZH)}）")
            hit_names = [nm for nm in names if race in self.card_races(nm)]
            hit = len(hit_names)
            if hit < need:
                deficit = True
        elif kind == "mechanic":
            if value not in MECHANICS:
                self.err(cid, f"beneficiary.value={value!r} 不是已知机制（{MECHANICS}）")
            hit_names = [nm for nm in names if value in self.card_text(nm)]
            hit = len(hit_names)
            if hit < need:
                deficit = True
        elif kind == "card":
            hit_names = [nm for nm in names if nm == value]
            hit = len(hit_names)
            in_keep = any(value in (lp.get("keep") or []) for lp in loops)
            if not in_keep:
                self.err(cid, f"beneficiary=card 的 {value!r} 必须出现在某个 loop.keep 里")
            need = 1
            if hit < 1:
                deficit = True
        if deficit:
            dn = str(e.get("deficit_note") or "")
            if "额外补" not in dn:
                self.err(cid, f"受益者命中 {hit} < min_count {need}，但缺少含“额外补”的 deficit_note")
            else:
                self.warn(cid, f"受益者命中 {hit} < min_count {need}（已用 deficit_note 说明）")

        # ---- keep_max_slots ----
        kms = e.get("keep_max_slots")
        if not isinstance(kms, int) or not (1 <= kms <= 7):
            self.err(cid, "keep_max_slots 必须是 1..7 的整数")
        else:
            for li, lp in enumerate(loops):
                if len(lp.get("keep") or []) > kms:
                    self.err(cid, f"loops[{li}].keep 有 {len(lp['keep'])} 张 > keep_max_slots={kms}")

        # ---- start_window ----
        sw = e.get("start_window")
        if sw is not None:
            if not isinstance(sw, dict):
                self.err(cid, "start_window 必须是 null 或对象")
            else:
                dt = sw.get("deadline_turn")
                if not isinstance(dt, int) or not (1 <= dt <= 20):
                    self.err(cid, "start_window.deadline_turn 必须是 1..20 的整数")
                if len(str(sw.get("why") or "")) < 8:
                    self.err(cid, "start_window.why 太短")

        # ---- checklist ----
        ck = e.get("checklist")
        if not isinstance(ck, list) or len(ck) < 3:
            self.err(cid, "checklist 至少 3 条")
        else:
            if not all(isinstance(x, str) and x.strip() for x in ck):
                self.err(cid, "checklist 里必须都是非空字符串")
            if not any(any(ch.isdigit() for ch in str(x)) for x in ck):
                self.err(cid, "checklist 至少要有 1 条带数字阈值")

        # ---- evidence ----
        ev = str(e.get("evidence") or "")
        if not re.search(r"docs/HSBG\.md L\d+-L\d+", ev):
            self.err(cid, "evidence 必须包含 docs/HSBG.md L起-L止 行号引用")
        if len(ev) < 20:
            self.err(cid, "evidence 太短")

        # ---- unavailable ----
        un = e.get("unavailable") or []
        if not isinstance(un, list):
            self.err(cid, "unavailable 必须是数组")
            un = []
        for ui, item in enumerate(un):
            if not isinstance(item, dict) or "name" not in item or "reason" not in item:
                self.err(cid, f"unavailable[{ui}] 必须含 name/reason")
                continue
            unm = item["name"]
            _cid, c = self.resolve(unm)
            if c is not None:
                self.err(cid, f"unavailable 里的 {unm!r} 其实 in_pool=True，不能算不可用")
            if any(unm == nm for _r, nm in all_names):
                self.err(cid, f"unavailable 里的 {unm!r} 同时出现在卡牌列表里（自相矛盾）")
            if unm not in self.narrative(e):
                self.err(cid, f"unavailable 里的 {unm!r} 没有在 why/note/evidence/checklist 里被引用说明")
            if len(str(item.get("reason") or "")) < 10:
                self.err(cid, f"unavailable[{ui}].reason 太短")

        status = "FAIL" if bad else ("DEFICIT" if deficit else "PASS")
        self.rows.append({
            "id": cid, "name": name, "kind": kind, "value": value,
            "hit": hit, "need": need, "hit_names": hit_names,
            "status": status, "bad": bad, "un": [x.get("name") for x in un if isinstance(x, dict)],
            "deficit_note": str(e.get("deficit_note") or ""),
        })

    # ---------- top-level ----------
    def run(self):
        if not isinstance(self.comps, list):
            self.errors.append("data/comp_exec.json 顶层必须是 31 条数组")
            return
        if len(self.comps) != 31:
            self.errors.append(f"comp_exec 条数 = {len(self.comps)}，应为 31")
        ids, names = [], set()
        for idx, e in enumerate(self.comps):
            if not isinstance(e, dict):
                self.errors.append(f"第 {idx + 1} 条不是对象")
                continue
            cid = str(e.get("id") or f"#{idx}")
            if cid in ids:
                self.errors.append(f"套号 {cid} 重复")
            ids.append(cid)
            nm = str(e.get("name") or "")
            if nm in names:
                self.errors.append(f"套号 {cid} 阵容名 {nm!r} 重复")
            names.add(nm)
            self.check_entry(e, idx)
        want = {f"{i:02d}" for i in range(1, 32)}
        missing = sorted(want - set(ids))
        extra = sorted(set(ids) - want)
        if missing:
            self.errors.append(f"缺少套号：{missing}")
        if extra:
            self.errors.append(f"多余套号：{extra}")

    # ---------- report ----------
    def write_md(self, path, json_path):
        total = len(self.rows)
        passed = sum(1 for r in self.rows if r["status"] == "PASS")
        deficits = [r for r in self.rows if r["status"] == "DEFICIT"]
        fails = [r for r in self.rows if r["status"] == "FAIL"]
        lines = [
            "# comp_exec 自检表（31 套阵容）",
            "",
            f"- 数据：`{os.path.relpath(json_path, ROOT)}`",
            "- 自检命令：",
            "",
            "```bash",
            "PYTHONPATH=rust/python:. /home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python \\",
            "    scripts/check_comp_exec.py",
            "```",
            "",
            f"- 结果：**{passed + len(deficits)}/{total} 通过**（{passed} 条严格命中；"
            f"{len(deficits)} 条受益者数量不足但已按规则在 deficit_note 说明需额外补位），"
            f"{len(fails)} 条失败，{len(self.errors)} 个错误 / {len(self.warnings)} 个警告。",
            "",
            "## 逐套结果",
            "",
            "| 套号 | 阵容 | 受益者 | 判定 | 命中/需求 | 结果 | 不可用卡 | 备注 |",
            "|---:|---|---|---:|---:|:---:|---|---|",
        ]
        for r in self.rows:
            if r["kind"] == "race":
                who = f"race:{r['value']}（{RACE_ZH.get(r['value'], '?')}）"
            elif r["kind"] == "mechanic":
                who = f"mechanic:{r['value']}"
            else:
                who = f"card:{r['value']}"
            judge = "keep+buy 命中" if r["kind"] in ("race", "mechanic") else "keep 命中"
            un = "、".join(r["un"]) if r["un"] else "—"
            note = r["deficit_note"] if r["status"] == "DEFICIT" else ""
            mark = {"PASS": "✅", "DEFICIT": "⚠️", "FAIL": "❌"}[r["status"]]
            lines.append(
                f"| {r['id']} | {r['name']} | {who} | {judge} | "
                f"{r['hit']}/{r['need']} | {mark} {r['status']} | {un} | {note} |"
            )
        lines += [
            "",
            "## 受益者命中明细",
            "",
            "| 套号 | 受益者 | 命中的卡（keep/buy 去重） |",
            "|---:|---|---|",
        ]
        for r in self.rows:
            lines.append(f"| {r['id']} | {r['value']} | {'、'.join(r['hit_names']) or '（无）'} |")
        if deficits:
            lines += ["", "## 受益者数量不足（已显式说明需额外补位）", ""]
            for r in deficits:
                lines.append(f"- **{r['id']} {r['name']}**：{r['deficit_note']}")
        if self.warnings:
            lines += ["", "## 警告", ""]
            lines += [f"- {w}" for w in self.warnings]
        if self.errors:
            lines += ["", "## 失败明细", ""]
            lines += [f"- {x}" for x in self.errors]
        else:
            lines += ["", "## 失败明细", "", "（无）"]
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return passed, total, len(deficits), len(fails)


def main():
    ap = argparse.ArgumentParser(description="自检 data/comp_exec.json")
    ap.add_argument("--json", default=os.path.join(ROOT, "data", "comp_exec.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "runs", "comp_exec_check.md"))
    args = ap.parse_args()

    with open(args.json, encoding="utf-8") as f:
        comps = json.load(f)
    catalog = json.loads(hsbg_engine.catalog_json())
    ck = Checker(comps, catalog)
    ck.run()
    passed, total, ndef, nfail = ck.write_md(os.path.abspath(args.out), os.path.abspath(args.json))

    print(f"[check_comp_exec] {passed + ndef}/{total} 通过（{passed} 严格命中 + {ndef} 受益者不足已说明），"
          f"{nfail} FAIL, {len(ck.errors)} errors, {len(ck.warnings)} warnings")
    print(f"[check_comp_exec] report -> {os.path.relpath(os.path.abspath(args.out), ROOT)}")
    for x in ck.errors:
        print("  ERROR " + x)
    for x in ck.warnings:
        print("  WARN  " + x)
    return 1 if ck.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
