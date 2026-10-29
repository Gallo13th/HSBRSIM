"""Phase0 价值网数据审计（只读；不训练、不改数据/引擎）。

用法：
  python scripts/audit_value_data.py \
    --bc-pkl runs/bc_data/heuristic_320_official.pkl \
    --jsonl "runs/rl/*.jsonl" \
    --live "runs/live/*/records.jsonl" \
    --out-json runs/value_data_audit.json \
    --out-md docs/VALUE_DATA_AUDIT.md \
    --split runs/value_split.json

输出：
- 总样本/有效 rank 样本、rank 分布、rank=-1 比例、episode 数/每局步数、可见性、重复/截断；
- 按 episode 70/15/15 固定切分（同局不跨集）；
- 质量判据 + 缺口/补采建议；
- `runs/value_split.json`（episode→split、种子、各集样本/rank 分布）。
"""

from __future__ import annotations

import argparse
import glob
import json
import random
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from hsbg.env.spec import Observation


# ── 通用统计 ──
def _rank_dist(ranks: Iterable[int]) -> Dict[str, int]:
    c = Counter(int(r) for r in ranks)
    return {str(k): int(c[k]) for k in sorted(c)}


def _pct(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    arr = sorted(float(v) for v in values)
    idx = max(0, min(len(arr) - 1, int(round(q * (len(arr) - 1)))))
    return float(arr[idx])


def _valid_rank(r: Any) -> bool:
    try:
        return 1 <= int(r) <= 8
    except Exception:  # noqa: BLE001
        return False


# ── BC 主数据 ──
def audit_bc(path: str) -> Dict[str, Any]:
    from hsbg.train.bc import BCDataset

    t0 = time.perf_counter()
    ds = BCDataset.load(path)
    n = len(ds.samples)
    ranks = [int(x) for x in ds.ranks]
    episode_ids = [int(x) for x in ds.episode_ids]
    obs_versions = Counter()
    cand_counts: List[int] = []
    step_counts: Counter = Counter()
    ep_ranks: Dict[int, set] = defaultdict(set)
    obs_keys: Counter = Counter()
    dup_hashes = set()
    dup = 0
    for (obs, _action), rank, ep in zip(ds.samples, ranks, episode_ids):
        try:
            obs_versions[int(getattr(obs, "version", 0))] += 1
            cand_counts.append(len(obs.candidates))
            obs_keys.update(obs.__dict__.keys())
        except Exception:  # noqa: BLE001
            pass
        step_counts[int(ep)] += 1
        ep_ranks[int(ep)].add(int(rank))
        # 近似重复：同一 episode + turn + phase + 候选/手牌/棋盘卡 id
        try:
            key = (int(ep), int(obs.turn), str(obs.phase),
                   tuple((c.kind, c.src_zone, c.src_slot, c.tgt_zone,
                          c.tgt_slot, c.option) for c in obs.candidates),
                   tuple(c.card_id for c in obs.board),
                   tuple(c.card_id for c in obs.hand))
            if key in dup_hashes:
                dup += 1
            else:
                dup_hashes.add(key)
        except Exception:  # noqa: BLE001
            pass
    valid_ranks = [r for r in ranks if _valid_rank(r)]
    complete_eps = sum(1 for ep, rs in ep_ranks.items()
                       if len(rs) == 1 and _valid_rank(next(iter(rs))))
    incomplete_eps = len(ep_ranks) - complete_eps
    steps = list(step_counts.values())
    return {
        "source": path,
        "n_samples": n,
        "n_episodes": len(set(episode_ids)),
        "valid_rank_samples": len(valid_ranks),
        "rank_minus1_samples": n - len(valid_ranks),
        "rank_minus1_frac": round((n - len(valid_ranks)) / max(1, n), 4),
        "rank_distribution": _rank_dist(ranks),
        "episodes_complete_label": complete_eps,
        "episodes_incomplete_label": incomplete_eps,
        "steps_per_episode": {
            "mean": round(statistics.fmean(steps), 2) if steps else 0.0,
            "p50": _pct(steps, 0.5), "p90": _pct(steps, 0.9),
            "max": int(max(steps)) if steps else 0,
        },
        "obs_versions": {str(k): int(v) for k, v in obs_versions.items()},
        "obs_fields": sorted(obs_keys),
        "full_observation": bool(
            {"board", "hand", "tavern", "candidates", "hero", "lobby"}
            .issubset(set(obs_keys))),
        "candidate_count_mean": round(statistics.fmean(cand_counts), 2)
        if cand_counts else 0.0,
        "duplicate_samples_approx": dup,
        "duplicate_frac_approx": round(dup / max(1, n), 4),
        "load_s": round(time.perf_counter() - t0, 2),
    }


# ── RL JSONL ──
def audit_jsonl(paths: Sequence[str]) -> Dict[str, Any]:
    eps_total = 0
    step_total = 0
    files: List[Dict[str, Any]] = []
    obs_key_sets: Counter = Counter()
    ep_steps: Counter = Counter()
    ep_ranks: Dict[str, int] = {}
    rank_minus1 = 0
    truncated = 0
    invalid = 0
    n_candidates: List[int] = []
    all_episode_ids: Counter = Counter()
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                header = json.loads(f.readline() or "{}")
                steps = 0
                eps: Counter = Counter()
                ranks: Dict[str, int] = {}
                files_trunc = 0
                files_invalid = 0
                file_cand: List[int] = []
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    typ = row.get("type")
                    if typ == "episode":
                        eid = str(row.get("episode_id", "?"))
                        if "rank" in row:
                            ranks[eid] = int(row.get("rank") or -1)
                        if row.get("truncated"):
                            files_trunc += 1
                        if row.get("invalid_actions"):
                            files_invalid += 1
                        continue
                    # step
                    steps += 1
                    eid = str(row.get("episode_id", "?"))
                    eps[eid] += 1
                    all_episode_ids[eid] += 1
                    if row.get("truncated"):
                        files_trunc += 1
                    if row.get("invalid"):
                        files_invalid += 1
                    obs = row.get("obs") or {}
                    if isinstance(obs, dict):
                        obs_key_sets.update(obs.keys())
                    if "n_candidates" in row:
                        file_cand.append(int(row.get("n_candidates") or 0))
                step_total += steps
                eps_total += len(eps)
                ep_steps.update(eps)
                ep_ranks.update(ranks)
                rank_minus1 += sum(1 for r in ranks.values() if not _valid_rank(r))
                truncated += files_trunc
                invalid += files_invalid
                n_candidates.extend(file_cand)
                files.append({
                    "path": p, "header_episodes": header.get("episodes"),
                    "header_obs_version": header.get("obs_version"),
                    "header_num_players": header.get("num_players"),
                    "steps": steps, "episodes": len(eps),
                    "rank_minus1": sum(1 for r in ranks.values()
                                       if not _valid_rank(r)),
                    "truncated_flags": files_trunc,
                    "invalid_flags": files_invalid,
                })
        except Exception as exc:  # noqa: BLE001
            files.append({"path": p, "error": f"{type(exc).__name__}: {exc}"})
    ep_step_list = list(ep_steps.values())
    full_obs = {
        "board", "hand", "tavern", "candidates", "hero", "lobby",
    }.issubset(set(obs_key_sets))
    known = len(ep_ranks)
    eps_all = eps_total
    return {
        "files": files,
        "n_files": len(files),
        "n_episodes": eps_total,
        "n_steps": step_total,
        "episode_rank_known": known,
        "episode_rank_coverage": round(known / max(1, eps_all), 4),
        "episodes_missing_rank": max(0, eps_all - known),
        "rank_minus1_frac_known": round(rank_minus1 / max(1, known), 4),
        "rank_missing_or_invalid_frac": round(
            (rank_minus1 + max(0, eps_all - known)) / max(1, eps_all), 4),
        "episodes_with_invalid_rank": rank_minus1,
        "truncated_flags": truncated,
        "invalid_flags": invalid,
        "obs_keys": sorted(obs_key_sets),
        "full_observation": full_obs,
        "observation_note": (
            "完整 Observation" if full_obs
            else "仅 step 摘要字段（缺完整实体 token/stats）；训练 value 需重新生成 obs"),
        "steps_per_episode": {
            "mean": round(statistics.fmean(ep_step_list), 2)
            if ep_step_list else 0.0,
            "p50": _pct(ep_step_list, 0.5),
            "p90": _pct(ep_step_list, 0.9),
            "max": int(max(ep_step_list)) if ep_step_list else 0,
        },
        "candidate_count_mean": round(statistics.fmean(n_candidates), 2)
        if n_candidates else 0.0,
    }


# ── 真实轨迹 / live ──
def audit_real(live_globs: Sequence[str], diff_globs: Sequence[str],
               powerlog: str) -> Dict[str, Any]:
    live_rows: List[Dict[str, Any]] = []
    for pat in live_globs:
        for p in glob.glob(pat):
            try:
                for line in open(p, encoding="utf-8"):
                    if line.strip():
                        live_rows.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    live_ranks = [r for r in (x.get("placement") for x in live_rows)
                  if _valid_rank(r)]
    power_exists = Path(powerlog).exists()
    diff_files = []
    for pat in diff_globs:
        for p in glob.glob(pat):
            try:
                d = json.loads(Path(p).read_text(encoding="utf-8"))
                s = d.get("summary", {})
                diff_files.append({
                    "path": p, "traces": s.get("traces"),
                    "match": s.get("match"),
                    "behavior_mismatch": s.get("behavior_mismatch"),
                })
            except Exception:  # noqa: BLE001
                diff_files.append({"path": p, "error": "parse_failed"})
    return {
        "live_records": len(live_rows),
        "live_valid_placement": len(live_ranks),
        "live_unique_games": len({(x.get("session_id"), x.get("game_no"))
                                  for x in live_rows}),
        "live_power_log_present": sum(1 for x in live_rows
                                      if x.get("power_log")),
        "local_powerlog": {
            "path": powerlog, "exists": power_exists,
            "bytes": Path(powerlog).stat().st_size if power_exists else 0,
        },
        "diff_trace_files": diff_files,
        "note": ("本地真实轨迹主要可作战斗/引擎校准辅助；live 记录目前仅少量有 "
                 "placement；价值网主训练仍用 BC 完整 obs 数据"),
    }


# ── 切分 ──
def make_split(bc: Dict[str, Any], bc_path: str, rl: Dict[str, Any],
               seed: int = 0) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from hsbg.train.bc import BCDataset

    ds = BCDataset.load(bc_path)
    eps = sorted(set(int(e) for e in ds.episode_ids))
    rng = random.Random(int(seed))
    rng.shuffle(eps)
    n = len(eps)
    n_train = int(round(0.70 * n))
    n_val = int(round(0.15 * n))
    train = eps[:n_train]
    val = eps[n_train:n_train + n_val]
    test = eps[n_train + n_val:]
    split_of = {e: "train" for e in train}
    split_of.update({e: "val" for e in val})
    split_of.update({e: "test" for e in test})
    per: Dict[str, Dict[str, Any]] = {}
    for name, ids in (("train", train), ("val", val), ("test", test)):
        idx = [i for i, e in enumerate(ds.episode_ids) if int(e) in set(ids)]
        ranks = [int(ds.ranks[i]) for i in idx]
        per[name] = {
            "episodes": len(ids),
            "samples": len(idx),
            "rank_distribution": _rank_dist(ranks),
            "valid_rank_samples": sum(1 for r in ranks if _valid_rank(r)),
        }
    overlaps = {
        "train_val": len(set(train) & set(val)),
        "train_test": len(set(train) & set(test)),
        "val_test": len(set(val) & set(test)),
    }
    split_json = {
        "seed": int(seed),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "bc": {
            "dataset": bc_path, "episodes": n,
            "episode_to_split": split_of,
            "splits": {"train": train, "val": val, "test": test},
            "stats": per,
        },
        "rl": {"episodes": rl.get("n_episodes", 0),
               "note": "RL JSONL 无完整 obs，切分仅作辅助/未来重生成用"},
        "leak_check": {"overlaps": overlaps, "no_leak": all(v == 0 for v in overlaps.values())},
    }
    return split_json, per


# ── 质量判据 ──
def quality(bc: Dict[str, Any], rl: Dict[str, Any], split: Dict[str, Any]
            ) -> Dict[str, Any]:
    checks = {
        "valid_rank_samples_ge_20k": bc["valid_rank_samples"] >= 20000,
        "rank_minus1_lt_5pct": bc["rank_minus1_frac"] < 0.05,
        "episode_split_no_leak": bool(split["leak_check"]["no_leak"]),
        "full_observation_visible": bool(bc["full_observation"]),
        "episode_label_completeness_ge_95pct": (
            bc["episodes_complete_label"] /
            max(1, bc["episodes_complete_label"] + bc["episodes_incomplete_label"])
            >= 0.95),
    }
    gaps = []
    if not checks["valid_rank_samples_ge_20k"]:
        need = 20000 - bc["valid_rank_samples"]
        gaps.append(f"有效 rank 样本不足，需至少再补 {need} 个（约 {need // 70 + 1} 局 teacher/BC 轨迹）")
    if not checks["rank_minus1_lt_5pct"]:
        gaps.append("rank=-1 比例过高，需检查采集器终局 rank 回填")
    if not checks["full_observation_visible"]:
        gaps.append("缺少完整 Observation（只有 JSONL 摘要）；需用 env 重新生成完整 obs")
    if not checks["episode_split_no_leak"]:
        gaps.append("episode split 存在泄漏，必须修切分")
    if not checks["episode_label_completeness_ge_95pct"]:
        gaps.append("部分 episode 终局 rank 缺失/不一致，需补采或剔除")
    return {"checks": checks, "passed": all(checks.values()),
            "gaps": gaps}


def _write_md(path: str, audit: Dict[str, Any]) -> None:
    bc = audit["bc"]
    rl = audit["rl"]
    split = audit["split"]
    q = audit["quality"]
    lines = ["# 价值网 Phase0 数据审计（只读，不训练）", "",
             f"- 生成时间：{audit['meta']['created_at']}",
             f"- BC 主数据：`{bc['source']}`", "",
             "## 1. 规模与标签", "",
             "| 数据 | episodes | samples/steps | 有效 rank | rank=-1 | 完整 obs |",
             "|---|---:|---:|---:|---:|---|",
             f"| BC pkl | {bc['n_episodes']} | {bc['n_samples']} | "
             f"{bc['valid_rank_samples']} | {bc['rank_minus1_frac']*100:.1f}% | "
             f"{bc['full_observation']} |",
             f"| RL JSONL | {rl['n_episodes']} | {rl['n_steps']} | "
             f"{rl['episode_rank_known']} ({rl['episode_rank_coverage']*100:.0f}%) | "
             f"missing {rl['episodes_missing_rank']} | "
             f"{rl['full_observation']} |", "",
             "**BC rank 分布**：", "```", json.dumps(bc["rank_distribution"], ensure_ascii=False), "```",
             f"BC 每局步数：mean {bc['steps_per_episode']['mean']} / p50 "
             f"{bc['steps_per_episode']['p50']} / p90 {bc['steps_per_episode']['p90']} / max "
             f"{bc['steps_per_episode']['max']}；candidate mean {bc['candidate_count_mean']}；"
             f"obs version {bc['obs_versions']}。", "",
             "**RL JSONL**：", f"- {rl['observation_note']}",
             f"- files {rl['n_files']}；steps {rl['n_steps']}；episodes {rl['n_episodes']}；"
             f"有终局 rank 的 episode {rl['episode_rank_known']} "
             f"（coverage {rl['episode_rank_coverage']*100:.0f}%）；"
             f"candidate mean {rl['candidate_count_mean']}；truncated flags {rl['truncated_flags']}；"
             f"invalid flags {rl['invalid_flags']}。",
             "- **RL JSONL 不能直接作为 value 训练主数据**（obs 仅摘要、rank coverage 不全）；"
             "需用 env/replay 重新生成完整 Observation，或只作辅助。", "",
             "## 2. 按 episode 70/15/15 切分（`runs/value_split.json`）", "",
             f"- seed={split['seed']}；BC episodes={split['bc']['episodes']}；"
             f"no_leak={split['leak_check']['no_leak']} {split['leak_check']['overlaps']}", "",
             "| split | episodes | samples | 有效 rank 样本 |", "|---|---:|---:|---:|"]
    for name in ("train", "val", "test"):
        s = split["bc"]["stats"][name]
        lines.append(f"| {name} | {s['episodes']} | {s['samples']} | {s['valid_rank_samples']} |")
    lines += ["", "## 3. 质量判据", ""]
    for k, v in q["checks"].items():
        lines.append(f"- [{'x' if v else ' '}] `{k}`")
    lines += [f"- **passed: {q['passed']}**", ""]
    if q["gaps"]:
        lines += ["**缺口/补采建议**："] + [f"- {g}" for g in q["gaps"]]
    else:
        lines += ["无阻塞缺口；可进入 Phase1（冻结 encoder 只训 value head）。"]
    lines += ["", "## 4. 真实轨迹/live 辅助数据", "",
              f"- live records {audit['real']['live_records']}；有 placement "
              f"{audit['real']['live_valid_placement']}；Power.log 存在 "
              f"{audit['real']['local_powerlog']['exists']} "
              f"({audit['real']['local_powerlog']['bytes']} bytes)。",
              "- 真实轨迹主要作战斗/引擎校准辅助；价值网主训练用 BC 完整 obs 数据。", "",
              "> 数据盘点对齐：仓库内未发现 data-upgrade 产出的独立盘点文件；本审计即当前 canonical "
              "盘点，若其后续产出需合并。", "",
              "> 只读审计：未修改数据/引擎、未训练、未写 checkpoint。"]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase0 value data audit (read-only)")
    parser.add_argument("--bc-pkl", default="runs/bc_data/heuristic_320_official.pkl")
    parser.add_argument("--jsonl", default="runs/rl/*.jsonl")
    parser.add_argument("--live", default="runs/live/*/records.jsonl")
    parser.add_argument("--diff", default="runs/diff_powerlog*.json")
    parser.add_argument("--powerlog", default="runs/powerlog/Power.log")
    parser.add_argument("--out-json", default="runs/value_data_audit.json")
    parser.add_argument("--out-md", default="docs/VALUE_DATA_AUDIT.md")
    parser.add_argument("--split", default="runs/value_split.json")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    bc = audit_bc(args.bc_pkl)
    rl = audit_jsonl(sorted(glob.glob(args.jsonl)))
    real = audit_real([args.live], [args.diff], args.powerlog)
    split, _ = make_split(bc, args.bc_pkl, rl, seed=args.seed)
    q = quality(bc, rl, split)
    audit = {
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "read_only": True, "training": False, "gpu": False,
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "note": "Phase0 value data audit；只读、不训练、不改数据/引擎",
            "data_upgrade_inventory": "not_found",
            "inventory_note": (
                "未发现 data-upgrade 产出的盘点文件；本审计作为当前 canonical 盘点。"
                "若其后续产出，需合并 rank/live/trace 计数。"),
        },
        "bc": bc, "rl": rl, "real": real,
        "split": split, "quality": q,
    }
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(audit, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    Path(args.split).parent.mkdir(parents=True, exist_ok=True)
    Path(args.split).write_text(json.dumps(split, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    _write_md(args.out_md, audit)
    print(json.dumps({
        "bc_samples": bc["n_samples"], "bc_episodes": bc["n_episodes"],
        "valid_rank": bc["valid_rank_samples"],
        "rank_minus1_frac": bc["rank_minus1_frac"],
        "slit_train_val_test": [split["bc"]["stats"][k]["samples"]
                                for k in ("train", "val", "test")],
        "quality_passed": q["passed"], "gaps": q["gaps"],
        "elapsed_s": audit["meta"]["elapsed_s"],
    }, ensure_ascii=False, indent=2))
    return 0 if q["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
