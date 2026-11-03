"""人类 replay 自动入库（纯 CPU、幂等）：吃鸡局→BC + 价值数据集。

用法：python scripts/ingest_human_play.py [--dry-run]
幂等键：(filename, mtime) 记在 runs/human_play/.ingested.json。
输出：
  - runs/human_play/demo_index.json（全量索引，原子写）
  - data/human_bc/win_games.jsonl.gz（placement==1 的动作，Firestone BC 格式）
  - data/scaling_value/dataset.npz（新文件的逐决策特征 + 该局最终 Σ 标签）
"""
from __future__ import annotations
import argparse, gzip, json, os, sys, time
from typing import Any, Dict, List

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "rust", "python")):
    if p not in sys.path:
        sys.path.insert(0, p)

import hsbg.env.obs_std as O
import hsbg_engine as E

PLAY_DIR = os.path.join(ROOT, "runs/human_play")
STATE_FILE = os.path.join(PLAY_DIR, ".ingested.json")
DEMO_INDEX = os.path.join(PLAY_DIR, "demo_index.json")
BC_PATH = os.path.join(ROOT, "data/human_bc/win_games.jsonl.gz")
DS_PATH = os.path.join(ROOT, "data/scaling_value/dataset.npz")
BOARD0, NB, MF = 68, 7, 31
CHAIN = {"BG21_015": "tareg", "BG29_813": "poet", "BG36_245": "arcanist", "BG36_640": "amalgam"}


def _cid2id() -> Dict[int, str]:
    return {int(c["cid"]): str(c["id"]) for c in json.loads(E.catalog_json())}


def _cards_db() -> Dict[str, Dict[str, Any]]:
    d = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
    if isinstance(d, dict):
        d = d.get("cards") or d.get("data") or list(d.values())
    return {str(c["id"]): c for c in d if isinstance(c, dict) and c.get("id")}


def _retention_ids(cards: Dict[str, Dict[str, Any]]) -> set:
    out = set()
    for cid, c in cards.items():
        t = int(c.get("tier") or 0)
        tx = str(c.get("text") or "").lower()
        if 4 <= t <= 6 and (cid in CHAIN or "permanently keep" in tx or "double" in tx or "twice" in tx):
            out.add(cid)
    return out


def _a2t(a: int) -> Any:
    if a == 1: return "reroll"
    if 16 <= a < 24: return "sell"
    if 8 <= a < 16: return "buy_minion"
    if a == 3: return "upgrade"
    if a == 4: return "hero_power"
    if a == 0: return "end_turn"
    if 46 <= a < 110: return "play_minion"
    return None


def analyze(path: str, cid2id: Dict[int, str], cards: Dict[str, Dict[str, Any]],
            retention: set) -> Dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        recs = [json.loads(l) for l in f]
    meta = recs[0]
    dec = [r for r in recs if r.get("type") == "decision" and r.get("phase") == "recruit"]
    summ = [r for r in recs if r.get("type") == "summary"]
    seed = int(meta.get("seed") or 0)
    placement = summ[0].get("placement") if summ else None
    turns = summ[0].get("turns") if summ else (max((int(r.get("turn") or 0) for r in dec), default=0))
    per: Dict[int, float] = {}
    chain_first: Dict[str, int] = {}
    steps: List[Dict[str, Any]] = []
    ds_rows: List[List[float]] = []
    final_sig = 0.0
    tier9 = tier_final = None
    for r in dec:
        t = int(r.get("turn") or 0)
        fl = np.asarray(r["features"], dtype=np.float32)
        b = fl[BOARD0:BOARD0 + NB * MF].reshape(NB, MF)
        pres = b[:, 0] > 0.5
        sig = float((np.where(pres, (b[:, 1] + b[:, 2]) * 10.0, 0.0)).sum())
        per[t] = max(per.get(t, 0.0), sig)
        tier = int(r.get("tier") or 0)
        if t == 9:
            tier9 = tier
        tier_final = tier
        final_sig = sig
        ca = np.asarray(r["cards"], dtype=np.int64)
        sl = O.CARD_BLOCK_SLICES["card_board"]
        board = [cid2id.get(int(x) - 1, "") for x in ca[sl.start:sl.stop] if int(x) > 0]
        norm = [c[:-2] if c.endswith("_G") else c for c in board if c]
        for c in norm:
            if c in CHAIN and c not in chain_first:
                chain_first[c] = t
        if 7 <= t <= 12:
            tt = _a2t(int(r.get("action") or -1))
            if tt:
                steps.append({"t": t, "a": int(r.get("action") or -1), "tier": tier,
                              "sig": round(sig, 0),
                              "shop": [cid2id.get(int(x) - 1, "") for x in
                                       ca[O.CARD_BLOCK_SLICES["card_shop"].start:
                                          O.CARD_BLOCK_SLICES["card_shop"].stop] if int(x) > 0]})
        # 价值数据集：10 维特征
        golds = int(np.where(pres, b[:, 5] > 0.5, False).sum())
        races = int(((b[:, 20:31] > 0.5).any(axis=0)).sum()) if pres.any() else 0
        ret = sum(1 for c in norm if c in retention)
        hand_n = int((ca[O.CARD_BLOCK_SLICES["card_hand"].start:O.CARD_BLOCK_SLICES["card_hand"].stop] > 0).sum())
        health = int(round(float(fl[O.GLOBAL_FIELD_INDEX["health"]]) * 40))
        ds_rows.append([float(t), float(int(r.get("gold") or 0)), float(tier), float(np.log1p(sig)),
                        float(int(pres.sum())), float(golds), float(races), float(ret),
                        float(hand_n), float(health)])
    peak = max(per.values()) if per else 0.0
    t15 = per.get(15) or (per[max(per)] if per else 0.0)
    return {"file": os.path.basename(path), "seed": seed, "placement": placement,
            "turns": turns, "peak": round(peak, 0), "t15": round(t15, 0),
            "t9_tier": tier9, "final_tier": tier_final,
            "chain_first": chain_first, "steps": steps, "ds_rows": ds_rows,
            "label": int(peak)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cid2id = _cid2id()
    cards = _cards_db()
    retention = _retention_ids(cards)
    state: Dict[str, Any] = {"files": {}}
    if os.path.isfile(STATE_FILE):
        try:
            state = json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            pass
    files = sorted(f for f in os.listdir(PLAY_DIR) if f.startswith("human_") and f.endswith(".jsonl.gz"))
    new = []
    for fn in files:
        p = os.path.join(PLAY_DIR, fn)
        key = f"{fn}:{int(os.path.getmtime(p))}"
        if key in state.get("files", {}):
            continue
        new.append((fn, key, p))
    print(f"[ingest] 扫描 {len(files)} 个 replay，新文件 {len(new)} 个", flush=True)
    demo: List[Dict[str, Any]] = []
    wins = 0
    seeds_w = set()
    all_rows: List[Dict[str, Any]] = []
    ds_new: List[List[float]] = []
    for fn, key, p in new:
        try:
            r = analyze(p, cid2id, cards, retention)
        except Exception as e:  # noqa: BLE001
            print(f"[ingest] skip {fn}: {e!r}", flush=True)
            continue
        _ds = r.pop("ds_rows")
        _lab = int(r.get("label") or 0)
        ds_new.extend([[d, _lab] for d in _ds])
        demo.append(r)
        if r.get("placement") == 1:
            wins += 1
            seeds_w.add(r["seed"])
            for st in r.get("steps") or []:
                all_rows.append(st)  # 保留到 BC 用
        state.setdefault("files", {})[key] = {"seed": r["seed"],
                                             "placement": r.get("placement"),
                                             "label": r["label"]}
    # 加载旧 demo_index（全量）并合并
    old_demo: List[Dict[str, Any]] = []
    if os.path.isfile(DEMO_INDEX):
        try:
            old_demo = json.load(open(DEMO_INDEX, encoding="utf-8"))
        except Exception:
            old_demo = []
    _by_file = {d.get("file"): d for d in old_demo}
    for d in demo:
        _by_file[d.get("file")] = d
    merged = list(_by_file.values())
    if not args.dry_run:
        json.dump(merged, open(DEMO_INDEX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        # BC：从 state 里所有吃鸡局重建（幂等，不追加）
        _win_files = [fn for fn, meta in (state.get("files") or {}).items()
                      if int(meta.get("placement") or 0) == 1]
        _rows = []
        for _k in _win_files:
            _fn = _k.split(":")[0]
            _p = os.path.join(PLAY_DIR, _fn)
            if not os.path.isfile(_p):
                continue
            try:
                _r = analyze(_p, cid2id, cards, retention)
            except Exception:  # noqa: BLE001
                continue
            for st in _r.get("steps") or []:
                _rows.append(st)
        if _rows:
            os.makedirs(os.path.dirname(BC_PATH), exist_ok=True)
            with gzip.open(BC_PATH, "wt", encoding="utf-8") as f:
                for st in _rows:
                    d = {"action_type": _a2t(st["a"]), "action_index": st["a"],
                         "turn": st["t"], "tier": st["tier"], "gold": 0, "health": 30,
                         "mmr": 9999, "shop_cards": st.get("shop") or [],
                         "hand_cards": [], "board_cards": []}
                    if d["action_type"]:
                        f.write(json.dumps(d, ensure_ascii=False) + "\n")
        # 价值数据集：追加新样本
        if ds_new:
            _Xnew = np.asarray([d for d, _ in ds_new], dtype=np.float32)
            _Ynew = np.asarray([y for _, y in ds_new], dtype=np.float64)
            if os.path.isfile(DS_PATH):
                _old = np.load(DS_PATH, allow_pickle=True)
                _X = np.concatenate([_old["X"], _Xnew], axis=0)
                _Y = np.concatenate([_old["Y"], _Ynew], axis=0)
            else:
                _X, _Y = _Xnew, _Ynew
            np.savez_compressed(DS_PATH, X=_X, Y=_Y)
            print(f"[ingest] dataset 追加 {len(_Xnew)} 行（标签已带）-> {DS_PATH} 总样本 {len(_X)}", flush=True)
    print(f"[ingest] 新发现 {len(demo)} 局，其中吃鸡 {wins} 局（seed {sorted(seeds_w)}）", flush=True)
    print(f"[ingest] 累计吃鸡局 {sum(1 for d in merged if d.get('placement') == 1)} / 累计索引 {len(merged)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
