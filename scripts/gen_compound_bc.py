#!/usr/bin/env python3
"""BC 标签数据集生成器：``CompoundPolicy`` 当「复利教师」（teacher distillation 数据侧）。

为什么需要教师
--------------
``runs/compound_script/amps_spell.json``（24 局，spell 脚本基线）：当前模型/脚本
「任意放大器 ≥1 张」的局只 **20.8%**、平均 **0.375 张/局**；同沙盒口镜下
``CompoundPolicy`` 买 **8.8–15.4 张/局**（出现率 96–100%，见
``docs/COMPOUND_SCRIPT.md`` §2–§4）。差距在**策略**（不买放大器/不舍得叠载体），
不在可购买性。所以把教师脚本的动作蒸馏成 BC 标签，是直接修复这条差距的最小闭环。

本脚本做的事
------------
在**无对战沙盒**（``hsbg.az.train.economy_sandbox``，15 回合、只 recruit、无血量/
无排名）里用 :class:`compound_script.CompoundPolicy` 跑 3 组环境配置：

===============  =====================================================  ==========
配置             环境                                               期望
===============  =====================================================  ==========
``s0_fixed30``   fixed 30 金/回合，action_cap 40（现状环境）          t15 Σ p50 ≈1.8k
``s1_growth_carrier``  growth 0.15 + 2 金/载体（S1）                 t15 Σ p50 ≈1.7k
``s3_growth_buff3``    S1 + action_cap_per_gold 3 + tavern_buff×3（S3） t15 Σ p50 ≈4.2k
===============  =====================================================  ==========

逐决策记录 ``obs``（3227 floats + 124 cards）、``mask``、``action``、``turn/tier/gold``、
动作类别（放大器/载体/法术/…），**只保留** ``sigma_t15 >= --keep-sigma``（默认 1500）
的高质量局（教师筛选）；每局另记整局标签 ``sigma_t12/t15``、``r12_15``、放大器购买数、
金色数、施法数、载体数、tavern_buff、金币收入。

产出（默认 ``data/scaling/compound_bc/``）
-----------------------------------------
- ``s0_fixed30.npz`` / ``s1_growth_carrier.npz`` / ``s3_growth_buff3.npz``：SoA 数组
- ``meta_<name>.json``：该组配置 + 局数/分布/动作类别统计
- ``meta.json``：总表（局数、放大器均值、t15 Σ 分布、字段说明、加载示例）

npz 字段（详见 :func:`field_doc`）
----------------------------------
每决策：``features[N,3227]``（默认 float16）、``cards[N,124] int16``、``mask[N,245] bool``、
``action[N] uint8``、``turn/tier uint8``、``gold int16``、``episode_id int32``、
``action_kind uint8``、``is_amp_buy/is_carrier_buy/is_spell_action bool``。
每局：``ep_seed int64``、``ep_sigma_t12/ep_sigma_t15 int32``、``ep_r12_15 float32``、
``ep_amp_total int16``、``ep_amp_any bool``、``ep_goldens_t15/ep_carriers_t15 int16``、
``ep_spells_t15/ep_tavern_buff_t15/ep_gold_total_income/ep_decisions int32``、
``ep_split uint8``（0=train，1=val；合并后按 episode 顺序确定性留出 10%）。

用法::

    # 小样本验证管线（3 组各 24 局，12 workers）
    python scripts/gen_compound_bc.py --games 24 --workers 12 --out-dir /tmp/cbc_smoke

    # 正式数据集（3 组各 200 局；S0/S1 会再筛掉 ~45% 低质量局）
    python scripts/gen_compound_bc.py --games 240 --workers 12 \
        --keep-sigma 1500 --out-dir data/scaling/compound_bc

    # 无金币上限（S3 想跑指数段时；输出用 --tag 另存，避免覆盖正式数据）
    python scripts/gen_compound_bc.py --games 160 --workers 12 --gold-cap 0 \
        --configs s3_growth_buff3 --tag cap0

    # 实验变体：三连/攒对子优先（另存 s3_growth_buff3_triple_first.npz）
    python scripts/gen_compound_bc.py --games 120 --workers 12 --triple-first 1 \
        --configs s3_growth_buff3 --tag triple_first

接口约定：``obs`` 走 ``hsbg.az.train.economy_sandbox`` 的同一套编码
（``hsbg.env.obs_std`` 3227+124），动作空间 245 与训练完全一致，所以 student
的 BC 损失可以直接用 ``mask`` 做 masked CE，无需任何适配层。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "scripts"))

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    END_TURN, N_ACTIONS, OBS_CARDS, OBS_FLOATS, SandboxConfig, VectorEconomySandbox)
from compound_script import (  # noqa: E402
    A_BUY, A_CHOOSE, A_PLAY, A_REFRESH, A_SELL, A_UPGRADE, AMP_BY_ID, AMP_SHORT,
    N_CHOICE, N_POS, N_SHOP, CompoundPolicy, _is_carrier, group_configs)

from dataclasses import replace  # noqa: E402

# ── 数据集字段 ──────────────────────────────────────────────────────────────
DEC_FIELDS: Tuple[str, ...] = (
    "features", "cards", "mask", "action", "turn", "tier", "gold", "episode_id",
    "action_kind", "is_amp_buy", "is_carrier_buy", "is_spell_action")
EP_FIELDS: Tuple[str, ...] = (
    "ep_seed", "ep_sigma_t12", "ep_sigma_t15", "ep_r12_15", "ep_amp_total",
    "ep_amp_any", "ep_goldens_t15", "ep_carriers_t15", "ep_spells_t15",
    "ep_tavern_buff_t15", "ep_gold_total_income", "ep_decisions")

ACTION_KINDS: Tuple[str, ...] = (
    "other", "buy_amp", "buy_carrier", "buy_spell", "buy_minion",
    "play_spell", "play_minion", "sell", "upgrade", "refresh", "end_turn",
    "pending")
K_OTHER, K_BUY_AMP, K_BUY_CARRIER, K_BUY_SPELL, K_BUY_MINION = 0, 1, 2, 3, 4
K_PLAY_SPELL, K_PLAY_MINION, K_SELL, K_UPGRADE = 5, 6, 7, 8
K_REFRESH, K_END, K_PENDING = 9, 10, 11

#: 3 组配置：名 → ``compound_script.group_configs()`` 的 key + 输出文件名
GROUP_SPEC: Dict[str, Dict[str, str]] = {
    "s0_fixed30": {"group": "S0", "label": "fixed 30 gold/turn, action_cap 40"},
    "s1_growth_carrier": {"group": "S1", "label": "growth 0.15 + 2 gold/carrier"},
    "s3_growth_buff3": {"group": "S3",
                        "label": "S1 + action_cap_per_gold 3 + tavern_buff x3"},
}


# ── 动作分类（记录「是否放大器/载体/法术」）───────────────────────────────────
def classify_action(a: int, view: Dict[str, Any]) -> Tuple[int, bool, bool, bool, str]:
    """动作 → ``(kind, is_amp, is_carrier, is_spell, card_id)``。

    ``is_amp``：买的是放大器（``AMP_BY_ID``，含放大器法术/饰品）；
    ``is_carrier``：买的是载体（``data/scaling/carriers.json`` 的 primary + 金色 + 施法协同）；
    ``is_spell``：买/打出的是非 minion（法术/饰品等）。
    """
    a = int(a)
    me = view.get("me") or {}
    shop = me.get("shop") or []
    hand = me.get("hand") or []
    if A_BUY <= a < A_BUY + N_SHOP:
        i = a - A_BUY
        if 0 <= i < len(shop):
            it = shop[i]
            cid = str(it.get("id") or "")
            is_spell = it.get("type") != "minion"
            is_amp = cid in AMP_BY_ID
            is_car = bool(_is_carrier(it))
            if is_amp:
                kind = K_BUY_AMP
            elif is_car:
                kind = K_BUY_CARRIER
            elif is_spell:
                kind = K_BUY_SPELL
            else:
                kind = K_BUY_MINION
            return kind, is_amp, is_car, bool(is_spell), cid
    if A_PLAY <= a < A_PLAY + 10 * N_POS:
        h = (a - A_PLAY) // N_POS
        if 0 <= h < len(hand):
            it = hand[h]
            cid = str(it.get("id") or "")
            is_spell = it.get("type") != "minion"
            return (K_PLAY_SPELL if is_spell else K_PLAY_MINION), False, False, \
                bool(is_spell), cid
    if A_SELL <= a < A_SELL + 7:
        return K_SELL, False, False, False, ""
    if a == A_UPGRADE:
        return K_UPGRADE, False, False, False, ""
    if a == A_REFRESH:
        return K_REFRESH, False, False, False, ""
    if A_CHOOSE <= a < A_CHOOSE + N_CHOICE:
        return K_PENDING, False, False, False, ""
    if a == END_TURN:
        return K_END, False, False, False, ""
    return K_OTHER, False, False, False, ""


# ── 一局/分片驱动 ───────────────────────────────────────────────────────────
def _empty_kept() -> Dict[str, List[Any]]:
    out: Dict[str, List[Any]] = {f: [] for f in DEC_FIELDS}
    for f in EP_FIELDS:
        out[f] = []
    return out


def _run_shard(payload: Dict[str, Any]) -> Dict[str, Any]:
    """跑 ``games`` 局，按阈值筛局，把**保留局**的逐决策样本写成 shard npz。"""
    t0 = time.time()
    cfg = payload["cfg"]
    games = int(payload["games"])
    n_envs = max(1, min(int(payload["n_envs"]), games))
    seed0 = int(payload["seed0"])
    keep_sigma = int(payload["keep_sigma"])
    max_seconds = float(payload["max_seconds"])
    fdt = str(payload["feature_dtype"])

    vec = VectorEconomySandbox(cfg, n_envs=n_envs, seed0=seed0)
    obs = vec.reset()
    if bool(payload.get("spell_spam")):
        # spell_spam 教师 = sandbox-econ 的 SpellSpamPolicy（CompoundPolicy 子类：
        # 优先买法术→立刻施放，优先对载体；见 scripts/spell_spam_probe.py）
        from spell_spam_probe import SpellSpamPolicy  # noqa: PLC0415
        pol_cls = SpellSpamPolicy
        pol_kw = dict(max_refresh=int(payload["max_refresh"]),
                      spell_hold=int(payload["spell_hold"]))
    else:
        pol_cls = CompoundPolicy
        pol_kw = dict(max_refresh=int(payload["max_refresh"]),
                      spell_hold=int(payload["spell_hold"]),
                      triple_first=bool(payload.get("triple_first")),
                      efficient=bool(payload.get("efficient")))
    pols = [pol_cls(seed=seed0 + i, **pol_kw) for i in range(n_envs)]

    cur: List[List[tuple]] = [[] for _ in range(n_envs)]
    cur_amp_total = [0] * n_envs
    kept = _empty_kept()
    amp_hist: Counter = Counter()
    eps_all: List[Dict[str, Any]] = []
    done_games = 0
    steps = 0
    max_steps = max(2000, 60 * games)

    while done_games < games and steps < max_steps:
        acts: List[int] = []
        for i, env in enumerate(vec.envs):
            v = json.loads(env.g.view(0))
            me = v.get("me") or {}
            a = pols[i].act(v, obs[i].mask)
            kind, is_amp, is_car, is_spell, cid = classify_action(a, v)
            cur[i].append((obs[i].features, obs[i].cards, obs[i].mask, int(a),
                           int(v.get("turn") or 0), int(me.get("tier") or 0),
                           int(me.get("gold") or 0), kind, is_amp, is_car,
                           is_spell, cid))
            if is_amp:
                cur_amp_total[i] += 1
            acts.append(int(a))
        obs, _rew, dones, infos = vec.step(acts)
        steps += 1
        for i, d in enumerate(dones):
            if not d:
                continue
            ep = infos[i].get("episode") or vec.envs[i].episode_summary()
            done_games += 1
            s12 = int(ep.get("sigma_t12") or 0)
            s15 = int(ep.get("sigma_t15") or 0)
            rec = {
                "seed": int(ep.get("seed") or 0),
                "sigma_t12": s12, "sigma_t15": s15,
                "amp_total": int(cur_amp_total[i]),
                "goldens": int(ep.get("goldens_t15") or 0),
                "spells": int(ep.get("spells_t15") or 0),
                "carriers": int(ep.get("carriers_t15") or 0),
                "tavern_buff": int(ep.get("tavern_buff_t15") or 0),
                "gold_income": int(ep.get("gold_total_income") or 0),
                "decisions": len(cur[i]),
            }
            eps_all.append(rec)
            if s15 >= keep_sigma and s12 > 0 and len(cur[i]) > 0:
                eid = len(kept["ep_seed"])
                kept["ep_seed"].append(rec["seed"])
                kept["ep_sigma_t12"].append(s12)
                kept["ep_sigma_t15"].append(s15)
                kept["ep_r12_15"].append(float(s15) / float(s12))
                kept["ep_amp_total"].append(rec["amp_total"])
                kept["ep_amp_any"].append(rec["amp_total"] > 0)
                kept["ep_goldens_t15"].append(rec["goldens"])
                kept["ep_carriers_t15"].append(rec["carriers"])
                kept["ep_spells_t15"].append(rec["spells"])
                kept["ep_tavern_buff_t15"].append(rec["tavern_buff"])
                kept["ep_gold_total_income"].append(rec["gold_income"])
                kept["ep_decisions"].append(rec["decisions"])
                for (f, c, m, a, turn, tier, gold, kind, is_amp, is_car,
                     is_spell, cid) in cur[i]:
                    kept["features"].append(f)
                    kept["cards"].append(c)
                    kept["mask"].append(m)
                    kept["action"].append(a)
                    kept["turn"].append(turn)
                    kept["tier"].append(tier)
                    kept["gold"].append(gold)
                    kept["episode_id"].append(eid)
                    kept["action_kind"].append(kind)
                    kept["is_amp_buy"].append(bool(is_amp))
                    kept["is_carrier_buy"].append(bool(is_car))
                    kept["is_spell_action"].append(bool(is_spell))
                    if is_amp:
                        amp_hist[AMP_SHORT[AMP_BY_ID[cid]]] += 1
            cur[i] = []
            cur_amp_total[i] = 0
            pols[i].turn = -1
        if time.time() - t0 > max_seconds:
            break

    n_dec = len(kept["action"])
    fdt = "float16" if fdt in ("float16", "fp16", "half") else "float32"
    arrays: Dict[str, np.ndarray] = {}
    if n_dec:
        arrays["features"] = np.asarray(kept["features"], dtype=fdt)
        arrays["cards"] = np.asarray(kept["cards"], dtype=np.int16)
        arrays["mask"] = np.asarray(kept["mask"], dtype=bool)
        arrays["action"] = np.asarray(kept["action"], dtype=np.uint8)
        arrays["turn"] = np.asarray(kept["turn"], dtype=np.uint8)
        arrays["tier"] = np.asarray(kept["tier"], dtype=np.uint8)
        arrays["gold"] = np.asarray(kept["gold"], dtype=np.int16)
        arrays["episode_id"] = np.asarray(kept["episode_id"], dtype=np.int32)
        arrays["action_kind"] = np.asarray(kept["action_kind"], dtype=np.uint8)
        arrays["is_amp_buy"] = np.asarray(kept["is_amp_buy"], dtype=bool)
        arrays["is_carrier_buy"] = np.asarray(kept["is_carrier_buy"], dtype=bool)
        arrays["is_spell_action"] = np.asarray(kept["is_spell_action"], dtype=bool)
        arrays["ep_seed"] = np.asarray(kept["ep_seed"], dtype=np.int64)
        arrays["ep_sigma_t12"] = np.asarray(kept["ep_sigma_t12"], dtype=np.int32)
        arrays["ep_sigma_t15"] = np.asarray(kept["ep_sigma_t15"], dtype=np.int32)
        arrays["ep_r12_15"] = np.asarray(kept["ep_r12_15"], dtype=np.float32)
        arrays["ep_amp_total"] = np.asarray(kept["ep_amp_total"], dtype=np.int16)
        arrays["ep_amp_any"] = np.asarray(kept["ep_amp_any"], dtype=bool)
        arrays["ep_goldens_t15"] = np.asarray(kept["ep_goldens_t15"], dtype=np.int16)
        arrays["ep_carriers_t15"] = np.asarray(kept["ep_carriers_t15"], dtype=np.int16)
        arrays["ep_spells_t15"] = np.asarray(kept["ep_spells_t15"], dtype=np.int32)
        arrays["ep_tavern_buff_t15"] = np.asarray(kept["ep_tavern_buff_t15"],
                                                  dtype=np.int32)
        arrays["ep_gold_total_income"] = np.asarray(kept["ep_gold_total_income"],
                                                    dtype=np.int32)
        arrays["ep_decisions"] = np.asarray(kept["ep_decisions"], dtype=np.int32)

    shard = str(payload["out_shard"])
    os.makedirs(os.path.dirname(os.path.abspath(shard)) or ".", exist_ok=True)
    np.savez(shard, **arrays)
    return {
        "shard": shard,
        "games_run": len(eps_all),
        "games_kept": int(len(kept["ep_seed"])),
        "decisions": int(n_dec),
        "bytes": int(os.path.getsize(shard)) if os.path.exists(shard) else 0,
        "episodes": eps_all,
        "amp_hist": dict(amp_hist),
        "seconds": time.time() - t0,
        "steps": steps,
        "timed_out": bool(done_games < games),
    }


# ── 合并 / 统计 ────────────────────────────────────────────────────────────
def _pct(vals: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(vals, dtype=np.float64), q)) if len(vals) else 0.0


def _dist(vals: Sequence[float]) -> Dict[str, float]:
    if not len(vals):
        return {"n": 0}
    return {"n": int(len(vals)), "mean": float(np.mean(vals)),
            "p50": _pct(vals, 50), "p90": _pct(vals, 90),
            "max": float(np.max(vals))}


def merge_shards(shards: Sequence[Dict[str, Any]]) -> Dict[str, np.ndarray]:
    """把各 worker 的 shard npz 合并成最终 SoA 数组（episode_id 全局重编号）。"""
    merged: Dict[str, List[np.ndarray]] = {f: [] for f in DEC_FIELDS + EP_FIELDS}
    offset = 0
    for sh in shards:
        data = np.load(str(sh["shard"]))
        n_ep = int(data["ep_seed"].shape[0]) if "ep_seed" in data.files else 0
        if n_ep == 0:
            continue
        for f in DEC_FIELDS:
            arr = data[f]
            if f == "episode_id":
                arr = np.asarray(arr, dtype=np.int32) + np.int32(offset)
            merged[f].append(arr)
        for f in EP_FIELDS:
            merged[f].append(data[f])
        offset += n_ep
        data.close()
    if not merged["action"]:
        return {f: np.zeros((0,), dtype=np.float32 if f == "features"
                            else np.int32) for f in DEC_FIELDS + EP_FIELDS}
    out = {f: np.concatenate(v, axis=0) for f, v in merged.items() if v}
    # 验证集：按**合并后 episode 顺序**确定性留出 10%（seed%10 会因 worker 只跑少数连续
    # seed 而退化成 ~50%，所以不能按 seed 切）。
    if "ep_seed" in out:
        out["ep_split"] = (np.arange(out["ep_seed"].shape[0]) % 10 == 0).astype(np.uint8)
    return out


def validate_arrays(arrays: Dict[str, np.ndarray], name: str) -> Dict[str, float]:
    """数据自检：每条动作在记录时刻的 mask 上必须合法（教师脚本 100% 合法）。"""
    n = int(arrays["action"].shape[0])
    if n == 0:
        return {"decisions": 0, "legal_rate": 1.0}
    act = arrays["action"].astype(np.int64)
    ok = arrays["mask"][np.arange(n), act]
    illegal = int(np.count_nonzero(~ok))
    n_ep = int(arrays["ep_seed"].shape[0])
    eid = arrays["episode_id"].astype(np.int64)
    assert eid.min() >= 0 and eid.max() < n_ep, f"{name}: episode_id 越界"
    per_ep = np.bincount(eid, minlength=n_ep)
    assert np.array_equal(per_ep, arrays["ep_decisions"]), \
        f"{name}: ep_decisions 与逐决策计数不一致"
    assert act.min() >= 0 and act.max() < N_ACTIONS, f"{name}: action 越界"
    if illegal:
        raise RuntimeError(f"{name}: {illegal}/{n} 条动作在 mask 上非法（应恒为 0）")
    return {"decisions": n, "episodes": n_ep, "legal_rate": 1.0,
            "mask_legal_mean": float(arrays["mask"].sum(axis=1).mean())}


def _summary(shards: Sequence[Dict[str, Any]], arrays: Dict[str, np.ndarray],
             spec: Dict[str, str], cfg, gold_cap: int, keep_sigma: int,
             seconds: float) -> Dict[str, Any]:
    eps_all = [e for sh in shards for e in sh["episodes"]]
    kept = arrays["ep_sigma_t15"]
    s15 = [float(x) for x in kept]
    s12 = [float(x) for x in arrays["ep_sigma_t12"]]
    amp = [int(x) for x in arrays["ep_amp_total"]]
    r = [float(x) for x in arrays["ep_r12_15"]]
    kind_counts = {k: int(np.count_nonzero(arrays["action_kind"] == i))
                   for i, k in enumerate(ACTION_KINDS)}
    amp_hist = Counter()
    for sh in shards:
        amp_hist.update(sh.get("amp_hist") or {})
    n_run = len(eps_all)
    n_kept = int(kept.shape[0])
    return {
        "name": spec["group"],
        "label": spec["label"],
        "games_run": n_run,
        "games_kept": n_kept,
        "keep_rate": (n_kept / n_run) if n_run else 0.0,
        "keep_sigma": int(keep_sigma),
        "decisions": int(arrays["action"].shape[0]),
        "decisions_per_game": (float(arrays["action"].shape[0]) / n_kept) if n_kept else 0.0,
        "train_val_games": [int(np.count_nonzero(arrays["ep_split"] == 0)),
                            int(np.count_nonzero(arrays["ep_split"] == 1))],
        "amp_total_mean": float(np.mean(amp)) if amp else 0.0,
        "amp_any_rate": float(np.mean([1.0 if a > 0 else 0.0 for a in amp])) if amp else 0.0,
        "amp_by_card_mean": {k: float(v) / max(1, n_kept) for k, v in
                             sorted(amp_hist.items(), key=lambda kv: -kv[1])},
        "goldens_mean": float(np.mean([int(x) for x in arrays["ep_goldens_t15"]]))
        if n_kept else 0.0,
        "spells_mean": float(np.mean([int(x) for x in arrays["ep_spells_t15"]]))
        if n_kept else 0.0,
        "carriers_mean": float(np.mean([int(x) for x in arrays["ep_carriers_t15"]]))
        if n_kept else 0.0,
        "tavern_buff_mean": float(np.mean([int(x) for x in arrays["ep_tavern_buff_t15"]]))
        if n_kept else 0.0,
        "t15_sigma": _dist(s15),
        "t15_sigma_all_run": _dist([float(e["sigma_t15"]) for e in eps_all]),
        "r12_15": _dist(r),
        "gold_total_income_p50": _pct([float(x) for x in
                                       arrays["ep_gold_total_income"]], 50) if n_kept else 0.0,
        # Σ/金（COMPOUND_INCOME 口径）：t15 Σ ÷ 整局金币收入，保留局 p50
        "sigma15_per_gold_p50": _pct(
            [a / b for a, b in zip(s15, [float(x) for x in
                                         arrays["ep_gold_total_income"]]) if b > 0], 50)
        if n_kept else 0.0,
        # buff 实例/局：spells_t15 = 施法次数（每次施法 = 1 个 buff 实例；完整
        # 「法术+战吼+亡语+EOT」口径见 scripts/spell_spam_probe.py 的 buff_instances）
        "buff_spells_mean": float(np.mean([int(x) for x in arrays["ep_spells_t15"]]))
        if n_kept else 0.0,
        "decisions_ge_10000": int(np.count_nonzero(np.asarray(s15) >= 10000)) if s15 else 0,
        "action_kind": kind_counts,
        "feature_dtype": str(arrays["features"].dtype),
        "gold_cap": int(gold_cap),
        "config": cfg.engine_config() if cfg is not None else {},
        "seconds": float(seconds),
    }


def field_doc() -> Dict[str, str]:
    return {
        "features": "float16[N,3227]（obs_std 3227 floats；--feature-dtype float32 可换）",
        "cards": "int16[N,124]（obs_std 124 cards）",
        "mask": "bool[N,245]（引擎合法动作 mask，含沙盒 action_cap 掩码）",
        "action": "uint8[N]（0..244，与训练动作段逐位一致）",
        "turn": "uint8[N]（1..15）",
        "tier": "uint8[N]（决策时玩家 tier）",
        "gold": "int16[N]（决策时剩余金币）",
        "episode_id": "int32[N]（→ ep_* 行号；同一局的所有决策共享）",
        "action_kind": "uint8[N]（0=other,1=buy_amp,2=buy_carrier,3=buy_spell,"
                       "4=buy_minion,5=play_spell,6=play_minion,7=sell,8=upgrade,"
                       "9=refresh,10=end_turn,11=pending）",
        "is_amp_buy": "bool[N]（该决策买的是放大器：Brann/Titus/Drakkari/Ashen/"
                      "Gatekeeper 及其法术/饰品）",
        "is_carrier_buy": "bool[N]（该决策买的是载体）",
        "is_spell_action": "bool[N]（该决策买/打的是法术等非 minion）",
        "ep_seed": "int64[E]（沙盒 seed）",
        "ep_sigma_t12": "int32[E]（t12 战团 Σ=Σ(atk+hp)）",
        "ep_sigma_t15": "int32[E]（t15 战团 Σ；教师筛选阈值 >= --keep-sigma）",
        "ep_r12_15": "float32[E]（sigma_t15 / sigma_t12，复利形状）",
        "ep_amp_total": "int16[E]（整局放大器购买数）",
        "ep_amp_any": "bool[E]（>=1 张放大器）",
        "ep_goldens_t15": "int16[E]（t15 场上金色随从数）",
        "ep_carriers_t15": "int16[E]（t15 场上载体数）",
        "ep_spells_t15": "int32[E]（t15 累计施法数）",
        "ep_tavern_buff_t15": "int32[E]（t15 酒馆永久 buff 总量）",
        "ep_gold_total_income": "int32[E]（整局金币收入，Σ/金 的分母）",
        "ep_decisions": "int32[E]（该局样本数）",
        "ep_split": "uint8[E]（0=train，1=val；合并后按 episode 顺序确定性留出 10%）",
    }


def loading_example() -> str:
    return (
        "import numpy as np\n"
        "d = np.load('data/scaling/compound_bc/s3_growth_buff3.npz')\n"
        "f, c, m = d['features'], d['cards'], d['mask']          # [N,3227] [N,124] [N,245]\n"
        "a = d['action'].astype(np.int64)                         # [N]\n"
        "ep = d['episode_id']                                     # [N] -> 每局标签\n"
        "s15, r12 = d['ep_sigma_t15'][ep], d['ep_r12_15'][ep]      # [N] 逐决策可用\n"
        "is_val = d['ep_split'][ep] == 1\n"
        "w = (s15 / 1500.0).clip(max=8.0)                         # 可选：按终局 Σ 加权采样\n"
        "# masked CE: loss = CE(logits, a); 非法动作已在训练侧用 m 掩掉\n"
    )


# ── CLI ────────────────────────────────────────────────────────────────────
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CompoundPolicy → BC 标签数据集")
    ap.add_argument("--games", type=int, default=24, help="每组跑的局数（筛前）")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=880000)
    ap.add_argument("--keep-sigma", type=int, default=1500,
                    help="只保留 sigma_t15 >= 该值的局（教师筛选）")
    ap.add_argument("--gold-cap", type=int, default=99, help="0 = 不封顶（沙子盒上限 99）")
    ap.add_argument("--gold-mode", default="", choices=["", "fixed", "add", "growth"],
                    help="覆盖环境收入口径（空 = 用组配置；fixed+--gold-per-turn 做现实收入臂）")
    ap.add_argument("--gold-per-turn", type=int, default=0,
                    help="覆盖每回合金币（0 = 用组配置；现实收入臂用 15/20）")
    ap.add_argument("--feature-dtype", default="float16",
                    choices=["float16", "float32"])
    ap.add_argument("--max-refresh", type=int, default=4)
    ap.add_argument("--spell-hold", type=int, default=1)
    ap.add_argument("--triple-first", type=int, default=0,
                    help="1 = 实验变体：三连/攒对子优先于载体（放大器仍最优先）")
    ap.add_argument("--efficient", type=int, default=0,
                    help="1 = 实验变体：动作效率（无载体也早施法、放开买法术）")
    ap.add_argument("--spell-spam", type=int, default=0,
                    help="1 = spell_spam 教师（sandbox-econ SpellSpamPolicy：金币优先买法术→立刻施放）")
    ap.add_argument("--env", default="group", choices=["group", "base"],
                    help="环境：group=用组配置；base=基础沙盒(15 回合/action_cap 40/无闸门，"
                         "配合 --gold-mode/--gold-per-turn/--gold-growth-rate 使用)")
    ap.add_argument("--gold-growth-rate", type=float, default=0.0,
                    help="growth 模式复利率（0 = 用组配置）")
    ap.add_argument("--gold-per-carrier", type=int, default=0,
                    help="growth 模式每载体额外金币（0 = 用组配置）")
    ap.add_argument("--out-name", default="",
                    help="单配置输出文件名（不含 .npz），如 s20_spellspam")
    ap.add_argument("--tag", default="",
                    help="输出文件名后缀（如 cap0 / triple_first），避免覆盖正式数据")
    ap.add_argument("--max-seconds", type=float, default=1200.0,
                    help="单 worker 墙钟上限（防跑飞；正常 240 局/组约 1-2 分钟）")
    ap.add_argument("--configs", default="s0_fixed30,s1_growth_carrier,s3_growth_buff3",
                    help="逗号分隔；默认三组")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "data", "scaling",
                                                      "compound_bc"))
    args = ap.parse_args(argv)

    t_start = time.time()
    cfgs = group_configs(gold_cap=int(args.gold_cap))
    names = [s.strip() for s in str(args.configs).split(",") if s.strip()]
    for nm in names:
        if nm not in GROUP_SPEC:
            raise SystemExit(f"未知配置 {nm}；可选 {sorted(GROUP_SPEC)}")
    os.makedirs(args.out_dir, exist_ok=True)
    suffix = f"_{args.tag}" if args.tag else ""
    shard_dir = os.path.join(args.out_dir, "_shards")
    os.makedirs(shard_dir, exist_ok=True)

    import multiprocessing as mp

    summary_all: Dict[str, Any] = {}
    for ci, nm in enumerate(names):
        spec = GROUP_SPEC[nm]
        if args.env == "base":
            # 基础沙盒（与 scripts/spell_spam_probe.py 同口径：15 回合 / action_cap 40 / 无闸门）
            cfg = SandboxConfig(turns=15, gold_mode="fixed", gold_per_turn=30,
                                action_cap=40, num_players=8, trinkets=True,
                                gold_cap=int(args.gold_cap), lobby_types=())
        else:
            cfg = cfgs[spec["group"]]
        over: Dict[str, Any] = {}
        if args.gold_mode:
            over["gold_mode"] = str(args.gold_mode)
        if int(args.gold_per_turn) > 0:
            over["gold_per_turn"] = int(args.gold_per_turn)
        if float(args.gold_growth_rate) > 0:
            over["gold_growth_rate"] = float(args.gold_growth_rate)
        if int(args.gold_per_carrier) > 0:
            over["gold_per_carrier"] = int(args.gold_per_carrier)
        if over:
            cfg = replace(cfg, **over)
            print(f"[{nm}] 环境覆盖 env={args.env} {over}", flush=True)
        games = int(args.games)
        n_w = max(1, min(int(args.workers), games))
        chunks = [(games + i) // n_w for i in range(n_w)]
        chunks = [c for c in chunks if c > 0]
        payloads = [{
            "cfg": cfg, "games": c,
            "n_envs": c,
            "seed0": int(args.seed0) + 100000 * ci + 1000 * si,
            "keep_sigma": int(args.keep_sigma),
            "max_seconds": float(args.max_seconds),
            "feature_dtype": str(args.feature_dtype),
            "max_refresh": int(args.max_refresh),
            "spell_hold": int(args.spell_hold),
            "triple_first": int(args.triple_first),
            "efficient": int(args.efficient),
            "spell_spam": int(args.spell_spam),
            "out_shard": os.path.join(shard_dir, f"{nm}{suffix}_{si:03d}.npz"),
        } for si, c in enumerate(chunks)]
        t0 = time.time()
        with mp.get_context("fork").Pool(len(payloads)) as pool:
            shards = pool.map(_run_shard, payloads)
        arrays = merge_shards(shards)
        validation = validate_arrays(arrays, nm)
        if args.out_name and len(names) > 1:
            raise SystemExit("--out-name 只能用于单配置")
        stem = str(args.out_name) if args.out_name else f"{nm}{suffix}"
        out_npz = os.path.join(args.out_dir, f"{stem}.npz")
        np.savez(out_npz, **arrays)
        summary = _summary(shards, arrays, spec, cfg, int(args.gold_cap),
                           int(args.keep_sigma), time.time() - t0)
        summary["validation"] = validation
        summary["path"] = os.path.abspath(out_npz)
        summary["bytes"] = int(os.path.getsize(out_npz))
        summary["arrays"] = {k: list(v.shape) for k, v in arrays.items()}
        summary["teacher_kind"] = "spell_spam" if int(args.spell_spam) else "compound"
        summary["teacher"] = ("scripts/spell_spam_probe.py::SpellSpamPolicy"
                              if int(args.spell_spam)
                              else "scripts/compound_script.py::CompoundPolicy")
        summary["env"] = str(args.env)
        summary["gold_mode"] = str(cfg.gold_mode if cfg is not None else "?")
        summary["gold_per_turn"] = int(cfg.gold_per_turn if cfg is not None else 0)
        summary["expr"] = {
            "out_name": str(args.out_name), "tag": str(args.tag),
            "gold_cap": int(args.gold_cap),
            "gold_growth_rate": float(cfg.gold_growth_rate if cfg is not None else 0.0),
            "gold_per_carrier": int(cfg.gold_per_carrier if cfg is not None else 0),
        }
        summary_all[nm] = summary
        for sh in shards:
            try:
                os.unlink(str(sh["shard"]))
            except OSError:
                pass
        meta_path = os.path.join(args.out_dir, f"meta_{stem}.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1, default=float)
        print(f"[{nm}] run={summary['games_run']} kept={summary['games_kept']} "
              f"({summary['keep_rate']:.0%}) dec={summary['decisions']} "
              f"amp={summary['amp_total_mean']:.2f} "
              f"goldens={summary['goldens_mean']:.2f} "
              f"t15 p50/p90/max={summary['t15_sigma']['p50']:.0f}/"
              f"{summary['t15_sigma']['p90']:.0f}/{summary['t15_sigma']['max']:.0f} "
              f"r12_15 p50={summary['r12_15']['p50']:.2f} "
              f"{summary['bytes'] / 1e6:.0f}MB {time.time() - t0:.0f}s", flush=True)
    try:
        os.rmdir(shard_dir)
    except OSError:
        pass

    meta = {
        "kind": "compound_bc_dataset",
        "version": 1,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "teacher": ("scripts/spell_spam_probe.py::SpellSpamPolicy（spell_spam：金币优先"
                    "买法术→立刻施放，优先对载体）" if int(args.spell_spam)
                    else "scripts/compound_script.py::CompoundPolicy"),
        "teacher_kind": "spell_spam" if int(args.spell_spam) else "compound",
        "sandbox": "hsbg.az.train.economy_sandbox（无对战 / 15 回合 / 无血量）",
        "keep_sigma": int(args.keep_sigma),
        "gold_cap": int(args.gold_cap),
        "env": str(args.env),
        "gold_mode_override": str(args.gold_mode),
        "gold_per_turn_override": int(args.gold_per_turn),
        "gold_growth_rate_override": float(args.gold_growth_rate),
        "gold_per_carrier_override": int(args.gold_per_carrier),
        "seed0": int(args.seed0),
        "games_per_config": int(args.games),
        "feature_dtype": str(args.feature_dtype),
        "triple_first": int(args.triple_first),
        "efficient": int(args.efficient),
        "spell_spam": int(args.spell_spam),
        "out_name": str(args.out_name),
        "tag": str(args.tag),
        "configs": {nm: {k: summary_all[nm][k] for k in
                         ("path", "games_run", "games_kept", "decisions",
                          "amp_total_mean", "amp_any_rate", "goldens_mean",
                          "spells_mean", "sigma15_per_gold_p50",
                          "decisions_ge_10000", "train_val_games", "bytes")}
                    for nm in names},
        "fields": field_doc(),
        "loading_example": loading_example(),
        "notes": [
            "obs 与训练同一套编码（3227+124），动作 245；BC 直接用 mask 做 masked CE。",
            "只保留 sigma_t15 >= keep_sigma 的局；S0/S1 保留率约 5-6 成，S3 约 9 成。",
            "ep_split=1 的局（合并后每 10 局取 1 局）留作验证集，不参与蒸馏训练。",
            "教师对照：现有模型/脚本 0.375 张放大器/局、出现率 20.8%"
            "（runs/compound_script/amps_spell.json）。",
        ],
        "seconds": time.time() - t_start,
    }
    meta_name = f"meta_{args.out_name}_all.json" if args.out_name else f"meta{suffix}.json"
    with open(os.path.join(args.out_dir, meta_name), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1, default=float)
    print(f"[gen_compound_bc] 写出 {args.out_dir}/{{*{suffix}.npz,meta*.json}} "
          f"总耗时 {time.time() - t_start:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
