#!/usr/bin/env python3
"""流派（archetype）分类器可行性探针：Firestone 149k 动作 -> 局级特征 -> 线性分类。

目的
====

回答「用 ``data/firestone_replays/firestone_recent_actions.jsonl.gz``（149,166 条逐动作
样本、500 局）训练流派分类器是否可行、最小实现长什么样」。**不产出上线模型**，只给：

1. 标签分布（``library_firestone_recent.jsonl`` 每局的 ``archetype`` 字段，28 类 + 14.6%
   未标注）；
2. 局级特征（动作直方图 / 逐回合节奏 / 战团与买牌的种族构成 / tier 里程碑）；
3. 分组交叉验证的 top-1 / top-3 / macro-F1 与 majority 基线（``LogisticRegression``，
   标准的最小实现）；
4. 按「先种族（11 类）再流派」的两段式可行性建议所需的分层数字。

用法::

    python scripts/archetype_probe.py                # 默认数据 + 5 折 CV
    python scripts/archetype_probe.py --min-games 8  # 只保留样本数 >= 8 的流派
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_ACTIONS = "data/firestone_replays/firestone_recent_actions.jsonl.gz"
DEFAULT_LIBRARY = "data/real_library/library_firestone_recent.jsonl"
DEFAULT_CARDS = "rust/crates/hsbg-engine/data/cards.json"

#: 动作类型（与 ``docs/FIRESTONE_REPLAY_INGEST.md §3.4`` 一致）。
ACTION_TYPES = ("buy_minion", "buy_spell", "play_minion", "play_spell", "sell",
                "reroll", "freeze", "upgrade", "hero_power", "triple", "dark_gift",
                "end_turn")
#: 逐回合节奏统计的动作（回合 1..15；``end_turn`` 恒定，不进节奏特征）。
RHYTHM_TYPES = ("buy_minion", "play_minion", "sell", "reroll", "upgrade", "hero_power")
RHYTHM_TURNS = tuple(range(1, 16))
#: 战团/买牌的种族位（引擎 ``cards.json`` 的 ``races``）。
TRIBES = ("BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL", "MURLOC",
          "NAGA", "PIRATE", "QUILBOAR", "UNDEAD", "ABERRATION")


def _load_labels(path: str) -> Dict[str, List[str]]:
    """``game_id -> [archetype, ...]``（每局的流派标签；None 跳过）。"""
    out: Dict[str, List[str]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gid = str(row.get("game_id") or "")
            arch = row.get("archetype")
            if not gid or not arch:
                continue
            out.setdefault(gid, [])
            if arch not in out[gid]:
                out[gid].append(str(arch))
    return out


def _load_card_races(path: str) -> Dict[str, Tuple[str, ...]]:
    """``card_id -> races``（小写 id 兼容大小写差异）。"""
    data = json.load(open(path, encoding="utf-8"))
    cards = data.get("cards") if isinstance(data, dict) else data
    out: Dict[str, Tuple[str, ...]] = {}
    for c in cards or []:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        out[cid] = tuple(str(x) for x in (c.get("races") or []))
    return out


def _tribe_label(archetype: str) -> str:
    """流派名第一段 = 种族（``mech_apm`` -> ``mech``，``neutral_tea_set`` -> ``neutral``）。"""
    return str(archetype).split("_", 1)[0]


def build_features(actions_path: str, labels: Dict[str, List[str]],
                   races: Dict[str, Tuple[str, ...]]) -> Tuple[List[str], List[List[float]],
                                                               List[str]]:
    """流式聚合动作 -> 局级特征向量。

    返回 ``(game_ids, features, tribe_labels)``；只保留有流派标签的局。
    """
    per_game: Dict[str, Dict[str, Any]] = {}
    with gzip.open(actions_path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            a = json.loads(line)
            gid = str(a.get("game_id") or "")
            if gid not in labels:
                continue
            st = per_game.setdefault(gid, {
                "n": 0, "types": collections.Counter(), "rhythm": collections.Counter(),
                "flow_tribe": collections.Counter(), "board_tribe": collections.Counter(),
                "tier_at": {}, "max_tier": 0, "gold_sum": 0.0, "gold_n": 0,
                "triples": 0})
            st["n"] += 1
            at = str(a.get("action_type") or "")
            st["types"][at] += 1
            turn = int(a.get("turn") or 0)
            if at in RHYTHM_TYPES and turn in RHYTHM_TURNS:
                st["rhythm"][(at, turn)] += 1
            tier = a.get("tier")
            if tier is not None:
                st["tier_at"][turn] = int(tier)
                st["max_tier"] = max(int(st["max_tier"]), int(tier))
            g = a.get("gold")
            if g is not None:
                st["gold_sum"] += float(g)
                st["gold_n"] += 1
            if at == "triple":
                st["triples"] += 1
            for field, bucket in (("card_id", "flow_tribe"), ("target_card_id", "flow_tribe")):
                cid = a.get(field)
                if at in ("buy_minion", "play_minion") and isinstance(cid, str):
                    for r in races.get(cid, ()):
                        st[bucket][r] += 1
            board = a.get("board_cards")
            if isinstance(board, list):
                for cid in board:
                    if isinstance(cid, str):
                        for r in races.get(cid, ()):
                            st["board_tribe"][r] += 1
    game_ids: List[str] = []
    feats: List[List[float]] = []
    for gid in sorted(per_game):
        st = per_game[gid]
        vec: List[float] = []
        n = max(1, int(st["n"]))
        for t in ACTION_TYPES:
            vec.append(st["types"].get(t, 0) / n)
        for t in RHYTHM_TYPES:
            for turn in RHYTHM_TURNS:
                vec.append(float(st["rhythm"].get((t, turn), 0)))
        flow_total = max(1, sum(st["flow_tribe"].values()))
        board_total = max(1, sum(st["board_tribe"].values()))
        vec.extend(st["flow_tribe"].get(r, 0) / flow_total for r in TRIBES)
        vec.extend(st["board_tribe"].get(r, 0) / board_total for r in TRIBES)
        for turn in (5, 8, 10, 12, 15):
            vec.append(float(st["tier_at"].get(turn, 0)))
        vec.extend([float(st["max_tier"]), float(n),
                    float(st["types"].get("buy_minion", 0)),
                    float(st["types"].get("play_minion", 0)),
                    float(st["triples"]),
                    (st["gold_sum"] / st["gold_n"]) if st["gold_n"] else 0.0])
        game_ids.append(gid)
        feats.append(vec)
    # 标签必须与 ``feats`` 同一顺序（sorted(per_game)），否则 CV 全错。
    return game_ids, feats, [labels[g][0] for g in sorted(per_game)]


def _evaluate(X, y, *, task: str, seed: int = 0, top_k: int = 1) -> Dict[str, Any]:
    """5 折分层 CV（按局划分，同局只有一个样本，无泄漏）。"""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, f1_score, top_k_accuracy_score
    from sklearn.model_selection import StratifiedKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X = np.asarray(X, dtype=np.float64)
    classes, y_idx = np.unique(y, return_inverse=True)
    if len(classes) < 2:
        return {"task": task, "error": "类别不足", "classes": len(classes)}
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=int(seed))
    pred = np.zeros_like(y_idx)
    proba = np.zeros((len(y_idx), len(classes)), dtype=np.float64)
    for tr, te in skf.split(X, y_idx):
        clf = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced",
                               multi_class="auto"))
        clf.fit(X[tr], y_idx[tr])
        pred[te] = clf.predict(X[te])
        p = clf.predict_proba(X[te])
        if p.shape[1] != len(classes):
            full = np.zeros((p.shape[0], len(classes)))
            full[:, clf.classes_] = p
            p = full
        proba[te] = p
    maj = collections.Counter(y).most_common(1)[0]
    out = {
        "task": task, "games": int(len(y)), "classes": int(len(classes)),
        "top1": round(float(accuracy_score(y_idx, pred)), 4),
        "macro_f1": round(float(f1_score(y_idx, pred, average="macro")), 4),
        "weighted_f1": round(float(f1_score(y_idx, pred, average="weighted")), 4),
        "majority_class": str(maj[0]),
        "majority_acc": round(float(maj[1] / len(y)), 4),
    }
    if top_k > 1 and len(classes) > top_k:
        out[f"top{top_k}"] = round(float(top_k_accuracy_score(
            y_idx, proba, k=top_k, labels=np.arange(len(classes)))), 4)
    per_class = collections.Counter(y)
    out["class_support"] = {str(c): int(per_class[c]) for c in classes}
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="流派分类器可行性探针（动作 -> 局级流派）")
    ap.add_argument("--actions", default=os.path.join(ROOT, DEFAULT_ACTIONS))
    ap.add_argument("--library", default=os.path.join(ROOT, DEFAULT_LIBRARY))
    ap.add_argument("--cards", default=os.path.join(ROOT, DEFAULT_CARDS))
    ap.add_argument("--min-games", type=int, default=10,
                    help="流派任务只保留样本数 >= 该值的类（默认 10）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="", help="把结果 JSON 写到该路径")
    args = ap.parse_args(argv)

    labels = _load_labels(args.library)
    races = _load_card_races(args.cards)
    game_ids, feats, arch_labels = build_features(args.actions, labels, races)
    games = len(game_ids)
    dist = collections.Counter(arch_labels)
    print(f"[data] 有标签局={games} 无标签局={len(labels) - games if False else '?'} "
          f"特征维={len(feats[0]) if feats else 0}")
    print(f"[labels] archetype 类数={len(dist)}")
    for name, cnt in dist.most_common():
        print(f"    {name:<40s} {cnt}")

    results: Dict[str, Any] = {"games": games, "features": len(feats[0]) if feats else 0,
                               "archetype_dist": {str(k): int(v)
                                                  for k, v in dist.most_common()}}
    # 任务 1：种族（11 类，样本最多，最可行）
    tribe = [_tribe_label(a) for a in arch_labels]
    results["tribe"] = _evaluate(feats, tribe, task="tribe", seed=args.seed, top_k=3)
    # 任务 2：流派（只保留 >= min_games 的类）
    keep = {a for a, c in dist.items() if c >= int(args.min_games)}
    idx = [i for i, a in enumerate(arch_labels) if a in keep]
    if len(keep) >= 2 and len(idx) >= 20:
        results["archetype"] = _evaluate([feats[i] for i in idx],
                                         [arch_labels[i] for i in idx],
                                         task=f"archetype(min_games={args.min_games})",
                                         seed=args.seed, top_k=3)
        results["archetype_games_used"] = len(idx)
    else:
        results["archetype"] = {"error": "可用样本/类别不足"}
    print("\n[result] " + json.dumps(results, ensure_ascii=False, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        json.dump(results, open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
