#!/usr/bin/env python3
"""Entity PPO 训练入口（持久 trainer + 进程级 actor pool + 可选 double-buffer 流水线）。

三条执行模式：

1. **串行**（默认）：collect → update → 快照/日志，语义最简单；
2. **流水线**（`--pipeline 1`，需要 `--processes > 1`）：`collect(B_{k+1})` 与 `update(B_k)`
   并行；actor 用**版本化权重文件**（任务开始时按 `weights_version` 懒加载），因此一批数据
   始终由同一个版本采集 → 滞后恒为 1，可断言；
3. 多线程采集（`--workers > 1 --processes 1`）：老路径，保留兼容。

评测：`--eval-every-decisions N` 到点做评测；`--eval-async 1` 时评测交给独立子进程
（默认 `--eval-device cuda:4`），主循环不等待，结果由轻量线程追加到
`eval/history.json`；`--eval-async 0` 保持旧的同步阻塞行为。`--eval-panel {bot,human,both}`
决定跑哪个面板（默认 both；human=人类战团对手面板，新主指标，见 `docs/EVAL_PANELS.md`），
两个 panel 各起一个子进程、串行排队（并发上限仍为 1）。

日志：`history.jsonl`（逐 iteration 追加，O(1)；不再全量重写 `history.json`），
`summary.json` 只存聚合信息；`--trainer-state` 可精确续训。

超参照 `docs/MULTISTAGE_TRAINING.md` §12（AutoTavern 论文 Table 7 对齐）：
sims=0 / clip 0.2 / target KL 0.05 / λ=0.995 / entropy 0.002 / grad-clip 1.0 /
lr 6e-6→5e-6 / 有效 minibatch = minibatch × grad_accum（8192）/ KL anchor β=0.1 前 100 iter。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available, engine_info, to_jsonable  # noqa: E402
from hsbg.az.train.mirror_snapshots import ramp_p  # noqa: E402
from hsbg.az.train.reward_shaping import (parse_tier_bonus,  # noqa: E402
                                          shaping_gamma_warning)
from hsbg.az.train.tier_target import parse_tier_target_table  # noqa: E402
from hsbg.az.train.model import (  # noqa: E402
    attach_bc_card_head,
    attach_move_head_split,
    attach_process_head,
    attach_strength_head,
    bc_card_head_dim,
    build_net,
    load_checkpoint,
    save_checkpoint,
)
from hsbg.az.train.curriculum import (  # noqa: E402
    anneal_progress,
    curriculum_schedule,
    gold_mult_at,
)
from hsbg.az.train.ppo import (  # noqa: E402
    BoardRampController,
    CollectConfig,
    PPOConfig,
    PPOEvaluator,
    board_ramp_history,
    collect_ppo_batch,
    forward_model,
    masked_log_softmax_torch,
    parse_decisions,
    ramp_progress_metrics,
    split_model_outputs,
    torch_available,
    value_from_rank_logits_torch,
)
from hsbg.az.train.ppo_trainer import PPOTrainer  # noqa: E402
from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator  # noqa: E402
from hsbg.az.train.parallel_collect import collect_ppo_batch_parallel  # noqa: E402
from hsbg.az.train.process_pool import ProcessActorPool  # noqa: E402
from hsbg.az.train.runlog import (append_record, read_run, slim_collect,  # noqa: E402
                                  write_header, write_summary)
from hsbg.az.train.seq_aux import SeqCoefSchedule  # noqa: E402
from hsbg.az.train.bc_aux import (  # noqa: E402
    bc_pool_summary,
    load_bc_samples,
    parse_bc_class_weights,
)
from hsbg.az.train.dpo_upgrade import (  # noqa: E402
    UpgradeSamples,
    dpo_pair_loss,
    load_upgrade_samples,
)
from scripts.async_eval import (AsyncEvalRunner, build_c0_cmd,  # noqa: E402
                                build_human_cmd, panels_from_spec,
                                parse_panel_result, write_json_atomic)


#: 期望梯度占比的参考量级：PPO total loss（value 项主导）。本 run 无历史时用 s9d 实测均值。
DPO_REF_TOTAL_LOSS = 0.77


def _load_comp_scripts() -> Any:
    """运行时加载 ``scripts/comp_scripts.py``（importlib；与 T1 的 ``_comp_fit_tables`` 同做法）。

    只在 ``--script-seats>0`` 的启动校验里调用，避免无引擎机器 import 训练脚本时被拖慢。
    """
    from hsbg.az.train.comp_offline_policy import load_comp_module
    return load_comp_module()


def _ppo_total_ref(out_dir: str) -> tuple:
    """本 run 最近一次 PPO ``total`` loss（无历史时退回 s9d 量级常数）；返回 (值, 来源)。"""
    path = os.path.join(str(out_dir), "history.jsonl")
    try:
        last = None
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        if last:
            rec = json.loads(last)
            for e in reversed((rec.get("ppo") or {}).get("epochs") or []):
                if "total" in e:
                    return float(e["total"]), "本 run history"
    except Exception:  # noqa: BLE001 - 只是启动打印的参考值
        pass
    return float(DPO_REF_TOTAL_LOSS), "s9d 量级常数"


def _dpo_startup_probe(model, pool: "UpgradeSamples", *, beta: float,
                       device: str, n: int = 512) -> Dict[str, float]:
    """启动诊断：当前策略在 upgrade 池上的 DPO 初值/接受率（no_grad，不改权重）。"""
    import torch

    sel = np.arange(min(int(n), len(pool)), dtype=np.int64)
    sub = pool.take(sel)
    was_training = bool(model.training)
    model.eval()
    try:
        with torch.no_grad():
            loss, rate = dpo_pair_loss(model, sub, float(beta), device=str(device))
        return {"n": float(len(sub)), "loss": float(loss),
                "accept_rate": float(rate)}
    finally:
        model.train(was_training)


def _dpo_grad_ref(path: str = "runs/dpo_grad_probe.json"):
    """读离线梯度占比探针结果（``scripts/dpo_grad_probe.py``）；没有则 None。"""
    try:
        with open(str(path), encoding="utf-8") as f:
            data = json.load(f)
        share = float(data["share_per_coef"])       # coef=1 时 ‖g_dpo‖/‖g_ppo‖
        if not np.isfinite(share) or share <= 0.0:
            return None
        return {"path": str(path), "share_per_coef": share,
                "checkpoint": data.get("checkpoint")}
    except Exception:  # noqa: BLE001 - 诊断文件缺失/损坏不影响训练
        return None


def _gpu_used_mib() -> Dict[int, int]:
    """``nvidia-smi`` 查询每张 GPU 已用显存（MiB）；查询失败返回 {}（=不做剔除）。"""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,memory.used",
             "--format=csv,noheader,nounits"],
            text=True, timeout=10, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001
        return {}
    used: Dict[int, int] = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            used[int(parts[0])] = int(float(parts[1]))
        except ValueError:
            continue
    return used


def _read_quality_json(path: str) -> Dict[str, Any]:
    """读离线质量统计 JSON（空路径/读失败 -> ``{}``，绝不打断训练）。

    只用于 ``--ramp-adaptive 1`` 的门控指标：给了 ``--ramp-quality-json`` 就优先用它
    的 ``survive_t12_ratio`` / ``tier_ge4_ratio``（真实 tier 观测），否则退回采集轨迹代理。
    每个 iteration 现读（文件可被外部脚本更新），失败静默退化。
    """
    if not str(path or "").strip():
        return {}
    try:
        with open(str(path), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except BaseException:  # noqa: BLE001 - 门控指标退化为轨迹代理
        return {}


def _atomic_torch_save(obj: Any, path: str) -> None:
    import torch
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


def _net_size_kwargs(args: Any) -> Dict[str, int]:
    """entity 尺寸参数（值为 0 = 未指定）。只用于**从零构建**；checkpoint 路径以 meta 为准。

    默认全 0 ⇒ 返回空 dict ⇒ ``build_net`` 行为与历史完全相同（逐位等价）。
    """
    if str(getattr(args, "arch", "")) not in ("entity", "entity18m"):
        return {}
    out: Dict[str, int] = {}
    for key in ("d_model", "n_layers", "n_heads"):
        val = int(getattr(args, key, 0) or 0)
        if val > 0:
            out[key] = val
    return out


_REWARD_CARD_META_CACHE: Optional[Dict[str, Any]] = None


def _attach_replication_bc_labels(batch: Any, *, want_upgrade: bool = False,
                                  upgrade_turns: str = "2,5,7,9") -> Dict[str, Any]:
    """从 **obs 卡牌块**给 batch 写两条辅助 BC 标签（纯 numpy；不读 player_json）。

    - ``discover_bc_idx/w``：``card_choices`` 里含放大器/引擎卡 ⇒ 这些 ``choose`` 位为教师，
      多选项按 tier×放大器优先级加权（只标**合法**位）；
    - ``triple_bc_action/w``：商店 slot 里的同名卡已持 2 张 ⇒ 该 ``buy`` 位权重 2.0；
      已持 1 张 ⇒ 权重 1.0（只标合法位）。
    """
    from collections import Counter

    from hsbg.az.train.ppo import _rep_card_flags  # 同一份卡牌元数据（金/星级/目标卡）
    from hsbg.env.action_space_std import (A_BUY, A_CHOOSE, N_CHOICE, N_SHOP)
    from hsbg.env.obs_std import (SLICE_CARD_BOARD, SLICE_CARD_CHOICES,
                                  SLICE_CARD_HAND, SLICE_CARD_SHOP)
    flags = _rep_card_flags()
    carr = np.asarray(batch.cards)
    if carr.ndim == 1:
        carr = carr.reshape(-1, 124)
    masks = np.asarray(batch.masks, dtype=bool)
    n = int(carr.shape[0])
    feat = np.asarray(batch.features, dtype=np.float32)
    _turns = np.asarray(batch.turns, dtype=np.float64)
    _tier_p = feat[:, 10] * 6.0
    _gold_p = feat[:, 7] * 10.0
    _price_p = feat[:, 11] * 10.0
    u_act = np.full(n, -1, dtype=np.int64)
    u_w = np.zeros(n, dtype=np.float32)
    n_up = 0
    d_idx = np.full((n, int(N_CHOICE)), -1, dtype=np.int64)
    d_w = np.zeros((n, int(N_CHOICE)), dtype=np.float32)
    t_act = np.full(n, -1, dtype=np.int64)
    t_w = np.zeros(n, dtype=np.float32)
    n_disc = n_trip = n_pair = 0
    for i in range(n):
        row = carr[i]
        mk = masks[i]
        # Discover
        ch = row[SLICE_CARD_CHOICES].astype(np.int64) - 1
        hits = [j for j in range(int(N_CHOICE))
                if ch[j] >= 0 and flags.get(int(ch[j]), (0, 0, 0))[2]
                and bool(mk[int(A_CHOOSE) + j])]
        if hits:
            # 目标标志 2 表示放大器，1 表示引擎；按星级×放大器 2 倍估值。
            values = {j: max(1, flags[int(ch[j])][1]) *
                      (2.0 if flags[int(ch[j])][2] == 2 else 1.0) for j in hits}
            denom = sum(values.values())
            for j in hits:
                d_idx[i, j] = int(A_CHOOSE) + j
                d_w[i, j] = values[j] / denom
            n_disc += 1
        # Triple / pair
        own: Counter = Counter()
        for sl in (SLICE_CARD_BOARD, SLICE_CARD_HAND):
            for j in range(sl.start, min(sl.stop, row.size)):
                cid = int(row[j]) - 1
                if cid >= 0 and not flags.get(cid, (0, 0, 0))[0]:
                    own[cid] += 1
        best: Optional[tuple] = None
        for slot in range(int(N_SHOP)):
            a = int(A_BUY) + slot
            if not bool(mk[a]):
                continue
            cid = int(row[SLICE_CARD_SHOP.start + slot]) - 1
            if cid < 0:
                continue
            cnt = own.get(cid, 0)
            if cnt >= 2:
                best = (a, 2.0)
                break
            if cnt == 1 and best is None:
                best = (a, 1.0)
        if best is not None:
            t_act[i], t_w[i] = int(best[0]), float(best[1])
            if float(best[1]) >= 2.0:
                n_trip += 1
            else:
                n_pair += 1
        # 升级曲线 BC（教师=脚本曲线）：t∈{2,5,7,9}、tier<curve、金币够、upgrade 合法
        _tt = float(_turns[i])
        _turns_set = {float(x) for x in str(upgrade_turns).split(",") if x.strip()}
        if want_upgrade and _tt in _turns_set and bool(mk[3]) \
                and float(_gold_p[i]) >= float(_price_p[i]):
            _tg = (2.0 if _tt <= 4.0 else 3.0 if _tt <= 6.0
                   else 4.0 if _tt <= 8.0 else 5.0 if _tt <= 11.0 else 6.0)
            if float(_tier_p[i]) < _tg - 1e-6:
                u_act[i] = 3
                u_w[i] = 1.0
                n_up += 1
    batch.discover_bc_idx = d_idx
    batch.discover_bc_w = d_w
    batch.triple_bc_action = t_act
    batch.triple_bc_w = t_w
    batch.upgrade_bc_action = u_act
    batch.upgrade_bc_w = u_w
    return {"discover_states": n_disc, "triple_states": n_trip, "pair_states": n_pair,
            "upgrade_states": n_up}


_COMP_FIT_CACHE: Dict[str, Any] = {}


def _comp_fit_tables() -> Dict[str, Any]:
    """T1 阵容适配度表：26 套可实现的 core/enabler/trinkets/type_min（懒加载）。"""
    if _COMP_FIT_CACHE:
        return _COMP_FIT_CACHE
    import hsbg.env.obs_std as O  # noqa: PLC0415
    roles_path = os.path.join(ROOT, "runs/comp_scripts/roles.json")
    comps = []
    if os.path.isfile(roles_path):
        raw = json.load(open(roles_path, encoding="utf-8")).get("comps") or []
        comps = [c for c in raw if c.get("implementable")]
    # 供给可达性：core_appear>=5% 的套才进 T1 候选（runs/comp_scripts/supply.json）
    _supply = os.path.join(ROOT, "runs/comp_scripts/supply.json")
    if os.path.isfile(_supply) and comps:
        try:
            _reach = set(int(x) for x in json.load(
                open(_supply, encoding="utf-8")).get("reachable") or [])
            _sel = [c for c in comps if int(c.get("idx", -1)) in _reach]
            if _sel:
                comps = _sel
        except BaseException:  # noqa: BLE001
            pass
    type_min_map: Dict[str, int] = {}
    try:
        import importlib.util as _iu  # noqa: PLC0415
        _spec = _iu.spec_from_file_location(
            "comp_scripts_t1", os.path.join(ROOT, "scripts", "comp_scripts.py"))
        _cs = _iu.module_from_spec(_spec)
        _spec.loader.exec_module(_cs)  # type: ignore[union-attr]
        type_min_map = {str(sp.name): int(sp.type_min) for sp in _cs.COMPS.values()}
    except BaseException:  # noqa: BLE001
        type_min_map = {}
    cards = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
    if isinstance(cards, dict):
        cards = cards.get("cards") or cards.get("data") or list(cards.values())
    by_id = {str(c["id"]): c for c in cards if isinstance(c, dict) and c.get("id")}
    import hsbg_engine as _E  # noqa: PLC0415
    cid2id = {int(c["cid"]): str(c["id"]) for c in json.loads(_E.catalog_json())}
    id2cid = {v: k for k, v in cid2id.items()}

    def _cid_set(items) -> np.ndarray:
        out = set()
        for x in items or []:
            if isinstance(x, (list, tuple)) and x:
                x = x[0]
            if not isinstance(x, str):
                continue
            for cand in (x, x[:-2] if x.endswith("_G") else x + "_G"):
                c = id2cid.get(cand)
                if c is not None:
                    out.add(int(c))
        return np.asarray(sorted(out), dtype=np.int64)

    races = list(O.RACE_NAMES)
    race_bit = {r: (1 << i) for i, r in enumerate(races)}
    max_cid = max(cid2id) + 2 if cid2id else 0
    race_lut = np.zeros(max_cid + 1, dtype=np.int64)
    for cid, sid in cid2id.items():
        c = by_id.get(sid) or {}
        rr = c.get("races") or []
        m = 0
        if isinstance(rr, list):
            for r in rr:
                m |= race_bit.get(str(r), 0)
        race_lut[int(cid)] = m
    pop = np.zeros(64, dtype=np.int64)
    for i in range(64):
        pop[i] = i
    pc = np.array([bin(int(v)).count("1") for v in range(1 << len(races))], dtype=np.int64)
    _COMP_FIT_CACHE.update({
        "comps": [{
            "name": str(c.get("name")),
            "core": _cid_set(c.get("core")),
            "enabler": _cid_set(c.get("enabler")),
            "trinkets": set(str(t) for t in (c.get("trinkets") or [])),
            "type_min": max(1, int(type_min_map.get(str(c.get("name")), 4))),
        } for c in comps],
        "race_lut": race_lut,
        "pc": pc,
        "trinket_kind": int(O.PENDING_KIND_NAMES.index("trinket")),
        "slice_pending": int(O.SLICE_PENDING.start),
        "slice_card_choices": O.SLICE_CARD_CHOICES,
        "exp_tier": np.asarray([max([k for k, t0 in
                                     ((1, 1), (2, 3), (3, 5), (4, 6), (5, 8), (6, 10))
                                     if t >= t0] or [1]) for t in range(0, 30)],
                               dtype=np.float64),
    })
    return _COMP_FIT_CACHE


def _reward_card_meta() -> Dict[str, Any]:
    """卡片元数据缓存：引擎 cid → 「金卡 / 金卡且 tier≥5 / 放大器 / 引擎卡」打分函数。"""
    global _REWARD_CARD_META_CACHE
    if _REWARD_CARD_META_CACHE is not None:
        return _REWARD_CARD_META_CACHE
    cards = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
    if isinstance(cards, dict):
        cards = cards.get("cards") or cards.get("data") or list(cards.values())
    tier = {str(c.get("id")): int(c.get("tier") or 0)
            for c in cards if isinstance(c, dict) and c.get("id")}
    import hsbg_engine as _E  # noqa: PLC0415
    cid2id = {int(c["cid"]): str(c["id"]) for c in json.loads(_E.catalog_json())}
    amp = {"BG25_354", "BG25_354_G", "BG26_ICC_901", "BG26_ICC_901_G",
           "BG36_640", "BG36_640_G"}
    eng = {"BG36_762", "BG36_762_G", "BG28_633", "BG28_633_G",
           "BG36_704", "BG36_704_G", "BG_LOE_077", "BG_LOE_077_G"}

    def score(cid: int, kind: str) -> float:
        sid = cid2id.get(int(cid), "")
        if not sid:
            return 0.0
        golden = sid.endswith("_G")
        if kind == "golden":
            return 1.0 if golden else 0.0
        if kind == "golden_t5":
            return 1.0 if (golden and tier.get(sid, 0) >= 5) else 0.0
        if kind == "amp":
            return 1.0 if sid in amp else 0.0
        if kind == "engine":
            return 1.0 if sid in eng else 0.0
        return 0.0

    _base_stats = {}
    for c in cards:
        if isinstance(c, dict) and c.get("id") and c.get("atk") is not None:
            _base_stats[str(c["id"])] = (float(c["atk"]), float(c["hp"]))
    _REWARD_CARD_META_CACHE = {
        "score": score,
        "tier_of": lambda cid: int(tier.get(cid2id.get(int(cid), ""), 0)),
        "base_of": lambda cid: _base_stats.get(cid2id.get(int(cid), ""), (0.0, 0.0)),
    }
    return _REWARD_CARD_META_CACHE


def _apply_custom_rewards(batch: Any, *, upgrade_w: float = 0.0,
                          win_w: float = 0.0, strength_c: float = 0.0,
                          strength_from_turn: float = 0.0,
                          golden_w: float = 0.0, golden_t5_w: float = 0.0,
                          amp_board_w: float = 0.0, engine_board_w: float = 0.0,
                          survive_t12_w: float = 0.0,
                          t5plus_stat_w: float = 0.0,
                          tier_timing_w: float = 0.0,
                          cheap_buy_p: float = 0.0,
                          t5plus_buff_w: float = 0.0,
                          tier_mix_w: float = 0.0,
                          lowtier_stat_p: float = 0.0,
                          comp_fit_c: float = 0.0,
                          comp_fit_t9_bonus: float = 0.0,
                          comp_trinket_c: float = 0.0,
                          t1p_coef: float = 0.0,
                          t1s_coef: float = 0.0,
                          save_up_w: float = 0.0,
                          late_growth_coef: float = 0.0,
                          late_shadow_coef: float = 0.0,
                          late_log_ratio_coef: float = 0.0,
                          late_alive_bonus: float = 0.0,
                          late_death_penalty: float = 0.0,
                          late_shadow_ratio: float = 3.15,
                          churn_w: float = 0.0,
                          hightier_w: float = 0.0,
                          hero_power_w: float = 0.0,
                          early_upgrade_w: float = 0.0,
                          churn_sell_cap: float = 12.0,
                          churn_roll_cap: float = 8.0,
                          churn_pair_w: float = 0.0,
                          roll_pair_w: float = 0.0,
                          tier_early_w: float = 0.0,
                          chain_w: float = 0.0,
                          chain_complete_bonus: float = 0.5,
                          chain2_w: float = 0.0,
                          late_rel_growth_coef: float = 0.0,
                          final_20k_w: float = 0.0,
                          chain_early_w: float = 0.0,
                          t9_chain_target_w: float = 0.0,
                          roll_bonus_t8t9: float = 0.0,
                          final_3500_w: float = 0.0,
                          scaling_value_w: float = 0.0,
                          scaling_value_model: str = "data/scaling_value/logit.npz",
                          chain_any_w: float = 0.0,
                          retain_growth_coef: float = 0.0,
                          gamma: float, lam: float) -> Optional[Dict[str, Any]]:
    """**默认全部关闭**的奖励改造；一次改 rewards 后**整批重算 GAE**。

    1. ``upgrade_w``：``upgrade`` 动作（A_UPGRADE=3）即时 +w。
    2. ``win_w``：终局只有第 1 名 +w。
    3. ``strength_c``：每回合 ΔL(Σ) 密集项（L = log1p(Σ)/log1p(30000)）。
    4. ``golden_w`` / ``golden_t5_w``：**金卡数量**的密集增量（全部金卡 / 其中 tier≥5）；
       观测量取自 obs 卡牌块（board 19:26 + hand 26:36，``cards[i]=cid+1``）。
    5. ``amp_board_w`` / ``engine_board_w``：**放大器家族 / 引擎卡在场上**的数量增量。
    6. ``survive_t12_w``：**活到 t12** 的终局奖励（该 episode 末回合 ≥12 才给）。
    全部为 0（默认）时**不调用** ⇒ 逐位等价旧路径。
    """
    from hsbg.az.train.ppo import compute_gae, log_strength_from_features  # noqa: PLC0415
    n = len(batch.actions)
    if n <= 0:
        return None
    delta = np.zeros(n, dtype=np.float64)
    n_up = n_win = 0
    if float(upgrade_w) > 0.0:
        a_upgrade = 3  # hsbg/env/action_space_std.py: A_UPGRADE
        hit = (np.asarray(batch.actions) == a_upgrade) & (~np.asarray(batch.forced, dtype=bool))
        delta[hit] += float(upgrade_w)
        n_up = int(hit.sum())
    if float(win_w) > 0.0:
        dones = np.asarray(batch.dones, dtype=np.float32) > 0.5
        ranks = np.asarray(batch.ranks)
        win_hit = dones & (ranks == 1)
        delta[win_hit] += float(win_w)
        n_win = int(win_hit.sum())
    if float(strength_c) > 0.0:
        L = np.asarray(log_strength_from_features(batch.features), dtype=np.float64)
        turns = np.asarray(batch.turns)
        eps = np.asarray(batch.episode_ids)
        # episode 连续（collect 侧保证），逐 episode 找「每回合最后一个决策」
        bounds = np.flatnonzero(np.diff(eps) != 0) + 1
        starts = np.concatenate(([0], bounds))
        ends = np.concatenate((bounds, [n]))
        for s, e in zip(starts.tolist(), ends.tolist()):
            t = turns[s:e]
            if t.size == 0:
                continue
            change = np.flatnonzero(np.diff(t) != 0) + s + 1  # 每回合第一个决策
            turn_starts = np.concatenate(([s], change))
            turn_ends = np.concatenate((change - 1, [e - 1]))
            prev_L = 0.0
            for ts, te in zip(turn_starts.tolist(), turn_ends.tolist()):
                cur_L = float(L[te])
                if float(turns[te]) >= float(strength_from_turn) - 1e-6:
                    delta[te] += float(strength_c) * (cur_L - prev_L)
                prev_L = cur_L
    # ── 金卡 / 放大器 / 引擎卡 / 存活到 t12（全部默认 0）─────────────────
    n_gold = n_gold5 = n_ampb = n_engb = n_surv = 0
    if (float(golden_w) > 0.0 or float(golden_t5_w) > 0.0
            or float(amp_board_w) > 0.0 or float(engine_board_w) > 0.0):
        try:
            from hsbg.env.obs_std import SLICE_CARD_BOARD, SLICE_CARD_HAND
            meta = _reward_card_meta()
            carr = np.asarray(batch.cards)
            if carr.ndim == 1:
                carr = carr.reshape(-1, 124)
            board_c = carr[:, SLICE_CARD_BOARD].astype(np.int64) - 1
            hand_c = carr[:, SLICE_CARD_HAND].astype(np.int64) - 1
            def _cnt(sel):
                out = np.zeros(n, dtype=np.float64)
                for j in range(sel.shape[1]):
                    cid = sel[:, j]
                    for i in np.flatnonzero(cid >= 0):
                        out[i] += float(meta["score"](int(cid[i]), kind))
                return out
            for kind, w in (("golden", float(golden_w)), ("golden_t5", float(golden_t5_w)),
                            ("amp", float(amp_board_w)), ("engine", float(engine_board_w))):
                if w <= 0.0:
                    continue
                cnt = _cnt(board_c) + (_cnt(hand_c) if kind.startswith("golden") else 0.0)
                eps = np.asarray(batch.episode_ids)
                bounds = np.flatnonzero(np.diff(eps) != 0) + 1
                starts = np.concatenate(([0], bounds))
                ends = np.concatenate((bounds, [n]))
                for s, e in zip(starts.tolist(), ends.tolist()):
                    prev = 0.0
                    for i in range(s, e):
                        cur = float(cnt[i])
                        delta[i] += w * (cur - prev)
                        prev = cur
                if kind == "golden":
                    n_gold = int(cnt[[e - 1 for e in ends]].sum())
                elif kind == "golden_t5":
                    n_gold5 = int(cnt[[e - 1 for e in ends]].sum())
                elif kind == "amp":
                    n_ampb = int(cnt[[e - 1 for e in ends]].sum())
                else:
                    n_engb = int(cnt[[e - 1 for e in ends]].sum())
        except BaseException:  # noqa: BLE001 - 奖励改造失败不能中断训练
            pass
    if float(survive_t12_w) > 0.0:
        dones = np.asarray(batch.dones, dtype=np.float32) > 0.5
        turns = np.asarray(batch.turns)
        surv_hit = dones & (turns >= 12)
        delta[surv_hit] += float(survive_t12_w)
        n_surv = int(surv_hit.sum())
    # 终局「t5+ 身材占比」直接奖励（默认 0）：obs board 块 tier/6 编码，atk/hp ×10 还原
    n_t5stat = 0
    _t5_share_mean = 0.0
    if float(t5plus_stat_w) > 0.0:
        try:
            arr = np.asarray(batch.features, dtype=np.float32)
            b = arr[:, 68:285].reshape(arr.shape[0], 7, 31)
            present = b[:, :, 0] > 0.5
            val = np.where(present, b[:, :, 1] + b[:, :, 2], 0.0) * 10.0
            tot = val.sum(axis=1)
            t5val = np.where(present & (b[:, :, 4] * 6.0 >= 5.0 - 1e-4), val, 0.0).sum(axis=1)
            share = np.where(tot > 1e-6, t5val / np.maximum(tot, 1e-6), 0.0)
            dones = np.asarray(batch.dones, dtype=np.float32) > 0.5
            delta[dones] += float(t5plus_stat_w) * share[dones]
            n_t5stat = int(dones.sum())
            if n_t5stat:
                _t5_share_mean = float(np.mean(share[dones]))
        except BaseException:  # noqa: BLE001
            pass
    # 升星时点奖励（默认 0）：t<=10 首次达到 tier>=5、t<=12 首次达到 tier>=6，按回合折扣
    n_t5tim = n_t6tim = 0
    if float(tier_timing_w) > 0.0:
        try:
            arr = np.asarray(batch.features, dtype=np.float32)
            tier_raw = arr[:, 10] * 6.0          # global['tier'] = tier/6
            turns_arr = np.asarray(batch.turns, dtype=np.float64)
            eps = np.asarray(batch.episode_ids)
            bounds = np.flatnonzero(np.diff(eps) != 0) + 1
            starts = np.concatenate(([0], bounds))
            ends = np.concatenate((bounds, [n]))
            for s_, e_ in zip(starts.tolist(), ends.tolist()):
                t = turns_arr[s_:e_]
                for thr, tmax in ((5.0, 10.0), (6.0, 12.0)):
                    hit = np.flatnonzero((tier_raw[s_:e_] >= thr - 0.01) & (t <= tmax))
                    if hit.size:
                        i0 = s_ + int(hit[0])
                        tt = float(turns_arr[i0])
                        disc = max(0.20, 1.0 - (tt - 1.0) / 15.0)
                        delta[i0] += float(tier_timing_w) * disc
                        if thr < 5.5:
                            n_t5tim += 1
                        else:
                            n_t6tim += 1
        except BaseException:  # noqa: BLE001
            pass
    # 便宜牌惩罚（默认 0）：buy tier<=3 随从时 -P
    n_cheap = 0
    if float(cheap_buy_p) > 0.0:
        try:
            acts = np.asarray(batch.actions, dtype=np.int64)
            carr2 = np.asarray(batch.cards)
            if carr2.ndim == 1:
                carr2 = carr2.reshape(-1, 124)
            shop_cid = carr2[:, 36:44].astype(np.int64) - 1
            meta2 = _reward_card_meta()
            buy = (acts >= 8) & (acts < 16)
            for i in np.flatnonzero(buy):
                slot = int(acts[i]) - 8
                if 0 <= slot < shop_cid.shape[1]:
                    cid = int(shop_cid[i, slot])
                    if cid >= 0 and meta2["tier_of"](cid) <= 3:
                        delta[i] -= float(cheap_buy_p)
                        n_cheap += 1
        except BaseException:  # noqa: BLE001
            pass
    # 终局「落在 tier>=5 随从身上的永久 buff 量」奖励（默认 0）：
    # buff = Σ(实际 atk+hp − 卡面基础 atk/hp)，仅统计 present 且 tier>=5 的随从；
    # 归一化 buff/200（clamp 3.0）后 × W，只在 episode 末决策给。
    n_t5buff = 0
    _t5buff_mean = 0.0
    if float(t5plus_buff_w) > 0.0:
        try:
            from hsbg.env.obs_std import SLICE_CARD_BOARD  # noqa: PLC0415
            arr2 = np.asarray(batch.features, dtype=np.float32)
            b2 = arr2[:, 68:285].reshape(arr2.shape[0], 7, 31)
            carr3 = np.asarray(batch.cards, dtype=np.int64)
            if carr3.ndim == 1:
                carr3 = carr3.reshape(-1, 124)
            bcids = carr3[:, SLICE_CARD_BOARD] - 1
            meta3 = _reward_card_meta()
            dones = np.asarray(batch.dones, dtype=np.float32) > 0.5
            _bufs = []
            for i in np.flatnonzero(dones):
                s_buf = 0.0
                for j in range(b2.shape[1]):
                    if b2[i, j, 0] <= 0.5:           # not present
                        continue
                    if b2[i, j, 4] * 6.0 < 5.0 - 1e-4:  # tier < 5
                        continue
                    cid = int(bcids[i, j])
                    if cid < 0:
                        continue
                    ba, bh = meta3["base_of"](cid)
                    s_buf += (b2[i, j, 1] * 10.0 - ba) + (b2[i, j, 2] * 10.0 - bh)
                norm = min(max(s_buf, 0.0) / 200.0, 3.0)
                if s_buf > 0.0:
                    delta[i] += float(t5plus_buff_w) * norm
                    n_t5buff += 1
                _bufs.append(s_buf)
            if _bufs:
                _t5buff_mean = float(np.mean(_bufs))
        except BaseException:  # noqa: BLE001
            pass
    # 盘面构成奖励（默认 0）：终局 tier>=5 占 7 槽位比例 ×W；tier<=3 身材占比 ×P 扣分
    n_mix = n_lowstat = 0
    _mix_mean = 0.0
    _lowstat_mean = 0.0
    if float(tier_mix_w) > 0.0 or float(lowtier_stat_p) > 0.0:
        try:
            arr4 = np.asarray(batch.features, dtype=np.float32)
            b4 = arr4[:, 68:285].reshape(arr4.shape[0], 7, 31)
            dones4 = np.asarray(batch.dones, dtype=np.float32) > 0.5
            mixes = []
            lows = []
            for i in np.flatnonzero(dones4):
                present = b4[i, :, 0] > 0.5
                tiers = b4[i, :, 4] * 6.0
                stats = np.where(present, (b4[i, :, 1] + b4[i, :, 2]) * 10.0, 0.0)
                n_t5 = int(np.sum(present & (tiers >= 5.0 - 1e-4)))
                tot = float(stats.sum())
                low = float(np.where(present & (tiers <= 3.0 + 1e-4), stats, 0.0).sum())
                mix = n_t5 / 7.0
                lowshare = low / max(tot, 1e-9)
                if float(tier_mix_w) > 0.0:
                    delta[i] += float(tier_mix_w) * mix
                    n_mix += 1
                if float(lowtier_stat_p) > 0.0:
                    delta[i] -= float(lowtier_stat_p) * lowshare
                    n_lowstat += 1
                mixes.append(mix); lows.append(lowshare)
            if mixes:
                _mix_mean = float(np.mean(mixes))
            if lows:
                _lowstat_mean = float(np.mean(lows))
        except BaseException:  # noqa: BLE001
            pass
    # T1：阵容适配度（comp_fit）。默认 0 = 不计算、逐位等价。
    n_cf = 0
    _cf_fit9_mean = 0.0
    _cf_trinket_hits = 0
    if float(comp_fit_c) > 0.0 or float(comp_fit_t9_bonus) > 0.0 or float(comp_trinket_c) > 0.0:
        try:
            import hsbg.env.obs_std as _O  # noqa: PLC0415
            _T = _comp_fit_tables()
            _feat = np.asarray(batch.features, dtype=np.float32)
            _n = _feat.shape[0]
            _carr = np.asarray(batch.cards, dtype=np.int64)
            if _carr.ndim == 1:
                _carr = _carr.reshape(-1, 124)
            _board = np.maximum(_carr[:, _O.SLICE_CARD_BOARD] - 1, -1)
            _hand = np.maximum(_carr[:, _O.SLICE_CARD_HAND] - 1, -1)
            _tier = _feat[:, _O.GLOBAL_FIELD_INDEX["tier"]] * 6.0
            _turns = np.asarray(batch.turns, dtype=np.float64)
            _eps = np.asarray(batch.episode_ids)
            _lut = _T["race_lut"]
            _bm = _lut[np.clip(_board, 0, len(_lut) - 1)]
            _bm = np.where(_board >= 0, _bm, 0)
            _race_or = np.bitwise_or.reduce(_bm, axis=1)
            _nraces = _T["pc"][np.clip(_race_or, 0, len(_T["pc"]) - 1)]
            _exp_t = _T["exp_tier"][np.clip(_turns.astype(np.int64), 0, len(_T["exp_tier"]) - 1)]
            _fit = np.zeros((_n, len(_T["comps"])), dtype=np.float64)
            for _ci, _c in enumerate(_T["comps"]):
                _nc = np.isin(_board, _c["core"]).sum(1) + np.isin(_hand, _c["core"]).sum(1)
                _ne = np.isin(_board, _c["enabler"]).sum(1) + np.isin(_hand, _c["enabler"]).sum(1)
                _fit[:, _ci] = (0.30 * np.minimum(1.0, _nc)
                                + 0.25 * np.minimum(1.0, _ne / 2.0)
                                + 0.20 * np.minimum(1.0, _nraces / float(_c["type_min"]))
                                + 0.25 * (_tier >= _exp_t))
            _fitmax = _fit.max(axis=1)
            _best = _fit.argmax(axis=1)
            # 逐 episode：t<=9 的 Δfit 密集项 + t9 终局项
            _bounds = np.flatnonzero(np.diff(_eps) != 0) + 1
            _starts = np.concatenate(([0], _bounds))
            _ends = np.concatenate((_bounds, [_n]))
            for _s, _e in zip(_starts.tolist(), _ends.tolist()):
                _prev = 0.0
                _last_le9 = None
                for _i in range(_s, _e):
                    if _turns[_i] <= 9.0:
                        if float(comp_fit_c) > 0.0:
                            delta[_i] += float(comp_fit_c) * (float(_fitmax[_i]) - _prev)
                        _prev = float(_fitmax[_i])
                        _last_le9 = _i
                if float(comp_fit_t9_bonus) > 0.0 and _last_le9 is not None:
                    delta[_last_le9] += float(comp_fit_t9_bonus) * float(_fitmax[_last_le9])
                    n_cf += 1
                    _cf_fit9_mean += float(_fitmax[_last_le9])
            # 饰品项：t6/t9 的 trinket pending 里，选中项 ∈ 当时 best-fit 套的关键饰品
            if float(comp_trinket_c) > 0.0:
                _acts = np.asarray(batch.actions, dtype=np.int64)
                _pend = _feat[:, _T["slice_pending"] + _T["trinket_kind"]]
                _ch = _carr[:, _T["slice_card_choices"]]
                for _i in np.flatnonzero((_pend > 0.5) & (_acts >= 30) & (_acts < 46)):
                    _idx = int(_acts[_i]) - 30
                    if 0 <= _idx < _ch.shape[1]:
                        _cid = int(_ch[_i, _idx]) - 1
                        from hsbg_engine import catalog_json as _cj  # noqa: PLC0415
                        _key = _T["comps"][int(_best[_i])]["trinkets"]
                        # cid -> id 用懒映射（只在这条分支上做）
                        _m = _COMP_FIT_CACHE.get("cid2id")
                        if _m is None:
                            _m = {int(c["cid"]): str(c["id"])
                                  for c in json.loads(_cj())}
                            _COMP_FIT_CACHE["cid2id"] = _m
                        _sid = _m.get(_cid)
                        if _sid is not None and _sid in _key:
                            delta[_i] += float(comp_trinket_c)
                            _cf_trinket_hits += 1
            if n_cf:
                _cf_fit9_mean /= float(n_cf)
        except BaseException:  # noqa: BLE001 - 奖励改造失败不能中断训练
            pass
    # T1s：每回合密集 shaping（tier 曲线 0.30 / 金币>=3 0.10 / 种族收敛 0.10 / t>=10 存活 0.20）
    n_t1s = 0
    _t1s = {"tier_ok": 0, "gold_ok": 0, "races_ok": 0, "alive_late": 0,
            "t9_tier": [], "t9_sig": [], "death": [], "upg_elig": 0, "upg_hit": 0,
            "upg_games": 0, "upg_per_game": 0.0, "buy_per_game": 0.0,
            "t9_gold_mean": None, "gold_after_upg_mean": None,
            "buys_upg_turn_mean": None}
    if float(t1s_coef) > 0.0:
        try:
            import hsbg.env.obs_std as _O3  # noqa: PLC0415
            _f3 = np.asarray(batch.features, dtype=np.float32)
            _n3 = _f3.shape[0]
            _bb3 = _f3[:, _O3.SLICE_BOARD].reshape(_n3, _O3.N_BOARD, _O3.MINION_F)
            _pres3 = _bb3[:, :, _O3.MINION_PRESENT] > 0.5
            _sig3 = np.where(_pres3, (_bb3[:, :, _O3.MINION_ATK]
                                      + _bb3[:, :, _O3.MINION_HP]) * 10.0, 0.0).sum(axis=1)
            _tier3 = _f3[:, _O3.GLOBAL_FIELD_INDEX["tier"]] * 6.0
            _gold3 = _f3[:, _O3.GLOBAL_FIELD_INDEX["gold"]] * 10.0
            _alive3 = _f3[:, _O3.GLOBAL_FIELD_INDEX["alive"]] * 8.0 >= 1.0
            _race_start = int(_O3.MINION_RACES)
            _races_bits = np.where(_pres3[:, :, None],
                                   _bb3[:, :, _race_start:_race_start + 11] > 0.5, False)
            _race_or = np.zeros((_n3, 11), dtype=bool)
            for _k in range(11):
                _race_or[:, _k] = _races_bits[:, :, _k].any(axis=1)
            _nraces3 = _race_or.sum(axis=1)
            _turns3 = np.asarray(batch.turns, dtype=np.float64)
            _eps3 = np.asarray(batch.episode_ids)
            _b3 = np.flatnonzero(np.diff(_eps3) != 0) + 1
            _s3 = np.concatenate(([0], _b3))
            _e3 = np.concatenate((_b3, [_n3]))
            _curve3 = np.asarray([1, 1, 2, 2, 2, 3, 3, 4, 4, 5, 5, 5, 6], dtype=np.float64)
            _acts3 = np.asarray(batch.actions, dtype=np.int64)
            _mask3 = np.asarray(batch.masks, dtype=bool)
            _price_g = _gold3 * 0.0 + _f3[:, _O3.GLOBAL_FIELD_INDEX["upgrade_price"]] * 10.0

            def _tgt(ti: float) -> float:
                k = int(min(max(int(ti), 0), len(_curve3) - 1))
                return float(_curve3[k])
            for _st, _en in zip(_s3.tolist(), _e3.tolist()):
                _prev_races = None
                _last = _en - 1
                for _tt in sorted({int(x) for x in _turns3[_st:_en].tolist()}):
                    _idxs = np.flatnonzero(_turns3[_st:_en] == float(_tt))
                    if not _idxs.size:
                        continue
                    _ix = _st + int(_idxs[-1])
                    _rew = 0.0
                    if float(_tier3[_ix]) >= _tgt(_tt) - 1e-6:
                        _rew += 0.30
                        _t1s["tier_ok"] += 1
                    if float(_gold3[_ix]) >= 3.0:
                        _rew += 0.10
                        _t1s["gold_ok"] += 1
                    if _prev_races is not None and int(_nraces3[_ix]) <= int(_prev_races):
                        _rew += 0.10
                        _t1s["races_ok"] += 1
                    if bool(_alive3[_ix]) and _tt >= 10:
                        _rew += 0.20
                        _t1s["alive_late"] += 1
                    if _rew:
                        delta[_ix] += float(t1s_coef) * _rew
                    _prev_races = int(_nraces3[_ix])
                    if _tt == 9:
                        _t1s["t9_tier"].append(float(_tier3[_ix]))
                        _t1s["t9_sig"].append(float(_sig3[_ix]))
                _t1s["death"].append(float(_turns3[_last]))
                n_t1s += 1
            _tgt_all = _curve3[np.clip(_turns3.astype(np.int64), 0, len(_curve3) - 1)]
            _elig = np.isin(_turns3, (2.0, 5.0, 7.0, 9.0)) & _mask3[:, 3] \
                & (_gold3 >= _price_g) & (_tier3 < _tgt_all - 1e-6)
            _t1s["upg_elig"] = int(_elig.sum())
            _t1s["upg_hit"] = int((_elig & (_acts3 == 3)).sum())
            # 分支 2 观测：每局升级数/买牌数、t9 gold、升级后金币、升级回合买牌数
            _upg_mask = (_acts3 == 3)
            _buy_mask = (_acts3 >= 8) & (_acts3 < 16)
            _gold_after, _buys_upg_turn, _t9golds = [], [], []
            _upg_counts, _buy_counts = [], []
            for _st, _en in zip(_s3.tolist(), _e3.tolist()):
                _upg_counts.append(int(_upg_mask[_st:_en].sum()))
                _buy_counts.append(int(_buy_mask[_st:_en].sum()))
                _t9g = None
                _idxs9 = np.flatnonzero(_turns3[_st:_en] == 9.0)
                if _idxs9.size:
                    _t9g = float(_gold3[_st + int(_idxs9[-1])])
                    _t9golds.append(_t9g)
                for _iu in np.flatnonzero(_upg_mask[_st:_en]):
                    _gi = _st + int(_iu)
                    if _gi + 1 < _en and float(_turns3[_gi + 1]) == float(_turns3[_gi]):
                        _gold_after.append(float(_gold3[_gi + 1]))
                    _same = _buy_mask[_st:_en] & (_turns3[_st:_en] == float(_turns3[_gi]))
                    _buys_upg_turn.append(int(_same.sum()))
            _t1s["upg_games"] = int(sum(1 for x in _upg_counts if x > 0))
            _t1s["upg_per_game"] = float(np.mean(_upg_counts)) if _upg_counts else 0.0
            _t1s["buy_per_game"] = float(np.mean(_buy_counts)) if _buy_counts else 0.0
            _t1s["t9_gold_mean"] = float(np.mean(_t9golds)) if _t9golds else None
            _t1s["gold_after_upg_mean"] = float(np.mean(_gold_after)) if _gold_after else None
            _t1s["buys_upg_turn_mean"] = float(np.mean(_buys_upg_turn)) if _buys_upg_turn else None
        except BaseException:  # noqa: BLE001
            pass
    # s29：攒钱纪律（t7/t8/t9 回合末金币 >= 8 → +w；只奖励"攒得住"，不给钱）
    n_su = 0
    _su = {"g7": [], "g8": [], "g9": [], "t9_upg": 0, "save8": 0, "save8_upg": 0}
    if float(save_up_w) > 0.0:
        try:
            import hsbg.env.obs_std as _O5  # noqa: PLC0415
            _f5 = np.asarray(batch.features, dtype=np.float32)
            _n5 = _f5.shape[0]
            _gold5 = _f5[:, _O5.GLOBAL_FIELD_INDEX["gold"]] * 10.0
            _acts5 = np.asarray(batch.actions, dtype=np.int64)
            _turns5 = np.asarray(batch.turns, dtype=np.float64)
            _eps5 = np.asarray(batch.episode_ids)
            _b5 = np.flatnonzero(np.diff(_eps5) != 0) + 1
            _s5 = np.concatenate(([0], _b5))
            _e5 = np.concatenate((_b5, [_n5]))
            for _st5, _en5 in zip(_s5.tolist(), _e5.tolist()):
                _g = {}
                for _tt in (7, 8, 9):
                    _idxs = np.flatnonzero(_turns5[_st5:_en5] == float(_tt))
                    if _idxs.size:
                        _ix = _st5 + int(_idxs[-1])
                        _g[_tt] = float(_gold5[_ix])
                        if float(_gold5[_ix]) >= 8.0:
                            delta[_ix] += float(save_up_w)
                if 7 in _g:
                    _su["g7"].append(_g[7])
                if 8 in _g:
                    _su["g8"].append(_g[8])
                if 9 in _g:
                    _su["g9"].append(_g[9])
                _t9upg = bool(((_acts5[_st5:_en5] == 3)
                               & (_turns5[_st5:_en5] == 9.0)).any())
                if _t9upg:
                    _su["t9_upg"] += 1
                if 8 in _g and _g[8] >= 8.0:
                    _su["save8"] += 1
                    if _t9upg:
                        _su["save8_upg"] += 1
                n_su += 1
        except BaseException:  # noqa: BLE001
            pass
    # s35 人类行为三件套：卖牌/刷新周转 + 高 tier 买牌 + 英雄技能
    n_ch = 0
    _ch = {"sells": 0, "rolls": 0, "h4": 0, "h5": 0, "h6": 0, "hp": 0, "early_upg": 0, "buf": 0.0}
    if float(churn_w) > 0.0 or float(hightier_w) > 0.0 or float(hero_power_w) > 0.0:
        try:
            import hsbg.env.obs_std as _O8  # noqa: PLC0415
            _acts8 = np.asarray(batch.actions, dtype=np.int64)
            _carr8 = np.asarray(batch.cards, dtype=np.int64)
            if _carr8.ndim == 1:
                _carr8 = _carr8.reshape(-1, 124)
            _cid2id8 = _COMP_FIT_CACHE.get("cid2id")
            if _cid2id8 is None:
                import hsbg_engine as _E8  # noqa: PLC0415
                _cid2id8 = {int(c["cid"]): str(c["id"]) for c in json.loads(_E8.catalog_json())}
                _COMP_FIT_CACHE["cid2id"] = _cid2id8
            _cards8 = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
            if isinstance(_cards8, dict):
                _cards8 = _cards8.get("cards") or _cards8.get("data") or list(_cards8.values())
            _tier8 = {str(c["id"]): int(c.get("tier") or 0)
                      for c in _cards8 if isinstance(c, dict) and c.get("id")}
            _shop = _carr8[:, _O8.SLICE_CARD_SHOP]
            _turns8 = np.asarray(batch.turns, dtype=np.float64)
            _eps8 = np.asarray(batch.episode_ids)
            _sell_k = {}
            _roll_k = {}
            from hsbg.az.train.action_counts import classify as _classify
            for _i in range(_acts8.shape[0]):
                _a = int(_acts8[_i])
                _ep = int(_eps8[_i])
                _tt = float(_turns8[_i])
                _k8 = _classify(_a)
                if _k8 == "sell":
                    _ch["sells"] += 1
                    _k = _sell_k.get(_ep, 0) + 1
                    _sell_k[_ep] = _k
                    if float(churn_w) > 0.0 and _k <= int(churn_sell_cap):
                        _mw = 1.0 if _k <= 8 else 0.5
                        delta[_i] += float(churn_w) * _mw
                        _ch["buf"] += float(churn_w) * _mw
                elif _k8 == "roll":
                    _ch["rolls"] += 1
                    _k = _roll_k.get(_ep, 0) + 1
                    _roll_k[_ep] = _k
                    if float(churn_w) > 0.0 and _k <= int(churn_roll_cap):
                        _mw = 1.0 if _k <= 4 else 0.5 if _k <= 8 else 0.0
                        delta[_i] += float(churn_w) * 0.667 * _mw
                        _ch["buf"] += float(churn_w) * 0.667 * _mw
                elif _k8 == "hero_power":
                    _ch["hp"] += 1
                    if float(hero_power_w) > 0.0:
                        delta[_i] += float(hero_power_w)
                        _ch["buf"] += float(hero_power_w)
                elif _k8 == "upgrade" and float(early_upgrade_w) > 0.0 and 2.0 <= _tt <= 5.0:
                    _ch["early_upg"] = _ch.get("early_upg", 0) + 1
                    delta[_i] += float(early_upgrade_w)
                    _ch["buf"] += float(early_upgrade_w)
                elif _k8 == "buy" and float(hightier_w) > 0.0:
                    _slot = _a - 8
                    _cid = int(_shop[_i, _slot]) - 1 if _slot < _shop.shape[1] else -1
                    _tid = _cid2id8.get(_cid, "") if _cid >= 0 else ""
                    _tr = int(_tier8.get(_tid, 0))
                    if _tr >= 4:
                        _rw8 = float(hightier_w) * (0.5 if _tr == 4 else 1.0 if _tr == 5 else 1.5)
                        delta[_i] += _rw8
                        _ch["buf"] += _rw8
                        _ch["h4" if _tr == 4 else "h5" if _tr == 5 else "h6"] += 1
            n_ch = 1
            # s37 卖→买 / 刷→买 配对（按 episode 时间序；每 sell/roll 至多配一个 buy）
            if float(churn_pair_w) > 0.0 or float(roll_pair_w) > 0.0:
                _pair = {"n_sell": 0, "n_sell_pair": 0, "n_roll": 0, "n_roll_pair": 0}
                _b_eps = np.flatnonzero(np.diff(_eps8) != 0) + 1
                _ep_starts = np.concatenate(([0], _b_eps))
                _ep_ends = np.concatenate((_b_eps, [_acts8.shape[0]]))
                for _a2, _b2 in zip(_ep_starts.tolist(), _ep_ends.tolist()):
                    _pend_s = []
                    _pend_r = []
                    for _i2 in range(_a2, _b2):
                        _k2 = _classify(int(_acts8[_i2]))
                        _t2 = float(_turns8[_i2])
                        if _k2 == "sell":
                            _pend_s.append(_t2)
                            _pair["n_sell"] += 1
                        elif _k2 == "roll":
                            _pend_r.append(_t2)
                            _pair["n_roll"] += 1
                        elif _k2 == "buy":
                            _hit = None
                            for _j, _st in enumerate(_pend_s):
                                if 0.0 <= _t2 - _st <= 2.0:
                                    _hit = _j
                                    break
                            if _hit is not None:
                                _pend_s.pop(_hit)
                                _pair["n_sell_pair"] += 1
                                delta[_i2] += float(churn_pair_w)
                                _ch["buf"] += float(churn_pair_w)
                            _hitr = None
                            for _j, _rt in enumerate(_pend_r):
                                if 0.0 <= _t2 - _rt <= 1.0:
                                    _hitr = _j
                                    break
                            if _hitr is not None:
                                _pend_r.pop(_hitr)
                                _pair["n_roll_pair"] += 1
                                delta[_i2] += float(roll_pair_w)
                                _ch["buf"] += float(roll_pair_w)
                _ch["pair"] = _pair
            if os.environ.get("HSBG_CHURN_DEBUG"):
                _seats8 = np.asarray(batch.seats, dtype=np.int64)
                _eps8b = np.asarray(batch.episode_ids, dtype=np.int64)
                _turns8b = np.asarray(batch.turns, dtype=np.int64)
                print(f"[churn-dbg] rows={len(_acts8)} seats={np.bincount(_seats8).tolist()} "
                      f"episodes={len(set(_eps8b.tolist()))} sells={_ch['sells']} rolls={_ch['rolls']} "
                      f"turn_min={int(_turns8b.min())} turn_max={int(_turns8b.max())} "
                      f"turn_mean={float(_turns8b.mean()):.1f}", flush=True)
        except BaseException:  # noqa: BLE001
            pass
    # s39 tier-timing（非门控、一次性）：t<=9 到达 tier4/tier5 各 +w
    _te = {"t4": 0, "t5": 0}
    if float(tier_early_w) > 0.0:
        try:
            import hsbg.env.obs_std as _O9  # noqa: PLC0415
            _f9 = np.asarray(batch.features, dtype=np.float32)
            _tier9 = _f9[:, _O9.GLOBAL_FIELD_INDEX["tier"]] * 6.0
            _turns9 = np.asarray(batch.turns, dtype=np.float64)
            _eps9 = np.asarray(batch.episode_ids)
            _b9 = np.flatnonzero(np.diff(_eps9) != 0) + 1
            _s9 = np.concatenate(([0], _b9))
            _e9 = np.concatenate((_b9, [_f9.shape[0]]))
            for _a9, _b9e in zip(_s9.tolist(), _e9.tolist()):
                _got4 = _got5 = False
                for _i9 in range(_a9, _b9e):
                    if float(_turns9[_i9]) > 9.0:
                        break
                    _tr9 = int(float(_tier9[_i9]))
                    if not _got4 and _tr9 >= 4:
                        delta[_i9] += float(tier_early_w)
                        _got4 = True
                        _te["t4"] += 1
                    if not _got5 and _tr9 >= 5:
                        delta[_i9] += float(tier_early_w)
                        _got5 = True
                        _te["t5"] += 1
        except BaseException:  # noqa: BLE001
            pass
    # s50：scaling 潜力价值 Δp 密集奖励（logistic p(Σ15>=3.5k) 的逐回合增量）
    n_sv = 0
    _dp_turns = 0
    _sv = {"p_mean": 0.0, "dp_sum": 0.0}
    if float(scaling_value_w) > 0.0:
        try:
            import hsbg.env.obs_std as _OS  # noqa: PLC0415
            _d = np.load(str(scaling_value_model))
            _w, _b = _d["w"].astype(np.float64), float(_d["b"])
            _mu, _sd = _d["mu"].astype(np.float64), _d["sd"].astype(np.float64)
            _fs = np.asarray(batch.features, dtype=np.float32)
            _ns = _fs.shape[0]
            _bbS = _fs[:, _OS.SLICE_BOARD].reshape(_ns, _OS.N_BOARD, _OS.MINION_F)
            _presS = _bbS[:, :, _OS.MINION_PRESENT] > 0.5
            _sigS = np.where(_presS, (_bbS[:, :, _OS.MINION_ATK]
                                      + _bbS[:, :, _OS.MINION_HP]) * 10.0, 0.0).sum(axis=1)
            _cntS = _presS.sum(axis=1).astype(np.float64)
            _gldS = np.where(_presS, _bbS[:, :, _OS.MINION_GOLDEN] > 0.5, False).sum(axis=1)
            _race_start = int(_OS.MINION_RACES)
            _rbS = np.where(_presS[:, :, None], _bbS[:, :, _race_start:_race_start + 11] > 0.5, False)
            _rorS = np.zeros((_ns, 11), dtype=bool)
            for _k in range(11):
                _rorS[:, _k] = _rbS[:, :, _k].any(axis=1)
            _nracS = _rorS.sum(axis=1).astype(np.float64)
            _tierS = _fs[:, _OS.GLOBAL_FIELD_INDEX["tier"]] * 6.0
            _goldS = _fs[:, _OS.GLOBAL_FIELD_INDEX["gold"]] * 10.0
            _healthS = _fs[:, _OS.GLOBAL_FIELD_INDEX["health"]] * 40.0
            _handS = (_fs[:, _OS.SLICE_CARD_HAND] > 0).sum(axis=1) if hasattr(_OS, "SLICE_CARD_HAND") else np.zeros(_ns)
            _carrS = np.asarray(batch.cards, dtype=np.int64)
            if _carrS.ndim == 1:
                _carrS = _carrS.reshape(-1, 124)
            _cid2idS = _COMP_FIT_CACHE.get("cid2id")
            if _cid2idS is None:
                import hsbg_engine as _ES  # noqa: PLC0415
                _cid2idS = {int(c["cid"]): str(c["id"]) for c in json.loads(_ES.catalog_json())}
                _COMP_FIT_CACHE["cid2id"] = _cid2idS
            _retS = _COMP_FIT_CACHE.get("retention_ids")
            if _retS is None:
                _cardsS = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
                if isinstance(_cardsS, dict):
                    _cardsS = _cardsS.get("cards") or _cardsS.get("data") or list(_cardsS.values())
                _retS = set()
                for _c in _cardsS:
                    if not isinstance(_c, dict):
                        continue
                    _id = str(_c.get("id") or "")
                    _tr = int(_c.get("tier") or 0)
                    _tx = str(_c.get("text") or "").lower()
                    if 4 <= _tr <= 6 and (_id in ("BG21_015", "BG29_813", "BG36_245", "BG36_640")
                                          or "permanently keep" in _tx or "double" in _tx or "twice" in _tx):
                        _retS.add(_id)
                _COMP_FIT_CACHE["retention_ids"] = _retS
            _retS = _COMP_FIT_CACHE["retention_ids"]
            _slB = _OS.CARD_BLOCK_SLICES["card_board"]
            _retcnt = np.zeros(_ns, dtype=np.float64)
            for _iS in range(_ns):
                _bb = 0
                for _x in _carrS[_iS, _slB.start:_slB.stop]:
                    _cid = int(_x) - 1
                    if _cid >= 0:
                        _id = _cid2idS.get(_cid, "")
                        if _id and ((_id[:-2] if _id.endswith("_G") else _id) in _retS):
                            _bb += 1
                _retcnt[_iS] = _bb
            _X = np.stack([batch.turns.astype(np.float64), _goldS, _tierS,
                           np.log1p(_sigS), _cntS, _gldS, _nracS, _retcnt,
                           _handS, _healthS], axis=1)
            _p = 1.0 / (1.0 + np.exp(-(((_X - _mu) / _sd) @ _w + _b)))
            _turnsS = np.asarray(batch.turns, dtype=np.float64)
            _epsS = np.asarray(batch.episode_ids)
            _bS = np.flatnonzero(np.diff(_epsS) != 0) + 1
            _sS = np.concatenate(([0], _bS))
            _eS = np.concatenate((_bS, [_ns]))
            _p_sum = 0.0
            _p_ps = []
            _p_last = []
            _sig_last = []
            _dp_turns = 0
            for _aS, _eS2 in zip(_sS.tolist(), _eS.tolist()):
                _prev_p = None
                for _tt in sorted({float(x) for x in _turnsS[_aS:_eS2].tolist()}):
                    _idxS = np.flatnonzero(_turnsS[_aS:_eS2] == _tt)
                    if not _idxS.size:
                        continue
                    _ixS = _aS + int(_idxS[-1])
                    _pv = float(_p[_ixS])
                    if _prev_p is not None:
                        _dpv = max(0.0, _pv - _prev_p)
                        delta[_ixS] += float(scaling_value_w) * _dpv
                        _sv["dp_sum"] += _dpv
                    _prev_p = _pv
                    _p_sum += _pv
                _p_ps.extend(float(x) for x in _p[_aS:_eS2].tolist())
                _p_last.append(float(_p[_eS2 - 1]))
                _sig_last.append(float(_sigS[_eS2 - 1]))
                _dp_turns += 1
                n_sv += 1
            _sv["p_mean"] = _p_sum / max(1.0, float(_ns))
            if _p_ps:
                _sv["p50"] = float(np.percentile(_p_ps, 50))
                _sv["p90"] = float(np.percentile(_p_ps, 90))
            if _p_last:
                import math as _m
                _pl = np.asarray(_p_last, dtype=np.float64)
                _sl = np.asarray(_sig_last, dtype=np.float64)
                if _pl.size >= 3 and _pl.std() > 1e-9 and _sl.std() > 1e-9:
                    _rp = np.argsort(np.argsort(_pl)); _rs = np.argsort(np.argsort(_sl))
                    _sv["spearman"] = float(np.corrcoef(_rp, _rs)[0, 1])
        except BaseException:  # noqa: BLE001
            pass
    # s49：t8-9 刷新压力（本回合已 roll>=2 后，每次再 roll +w）
    if float(roll_bonus_t8t9) > 0.0:
        try:
            from hsbg.az.train.action_counts import classify as _cB  # noqa: PLC0415
            _actsB = np.asarray(batch.actions, dtype=np.int64)
            _turnsB = np.asarray(batch.turns, dtype=np.float64)
            _epsB = np.asarray(batch.episode_ids)
            _bB = np.flatnonzero(np.diff(_epsB) != 0) + 1
            _sB = np.concatenate(([0], _bB))
            _eB = np.concatenate((_bB, [_actsB.shape[0]]))
            for _aB, _eB2 in zip(_sB.tolist(), _eB.tolist()):
                _roll_cnt = {}
                for _iB in range(_aB, _eB2):
                    if _cB(int(_actsB[_iB])) != "roll":
                        continue
                    _tB = float(_turnsB[_iB])
                    if _tB not in (8.0, 9.0):
                        continue
                    _k = _roll_cnt.get(_tB, 0) + 1
                    _roll_cnt[_tB] = _k
                    if _k >= 2:
                        delta[_iB] += float(roll_bonus_t8t9)
        except BaseException:  # noqa: BLE001
            pass
    # s41 链定向（塔蕾苟萨/坚韧诗人/符文奥术师/守门融合怪）+ 保留型成长
    _ch2 = {"n_turns": 0, "chain_sum": 0, "chain4_turns": 0, "chain2_turns": 0,
            "retain_sum": 0.0}
    if (float(chain_w) > 0.0 or float(chain_complete_bonus) > 0.0
            or float(retain_growth_coef) > 0.0):
        try:
            import hsbg.env.obs_std as _OA  # noqa: PLC0415
            _fA = np.asarray(batch.features, dtype=np.float32)
            _nA = _fA.shape[0]
            _bbA = _fA[:, _OA.SLICE_BOARD].reshape(_nA, _OA.N_BOARD, _OA.MINION_F)
            _presA = _bbA[:, :, _OA.MINION_PRESENT] > 0.5
            _sigA = np.where(_presA, (_bbA[:, :, _OA.MINION_ATK]
                                      + _bbA[:, :, _OA.MINION_HP]) * 10.0, 0.0).sum(axis=1)
            _carrA = np.asarray(batch.cards, dtype=np.int64)
            if _carrA.ndim == 1:
                _carrA = _carrA.reshape(-1, 124)
            _cid2idA = _COMP_FIT_CACHE.get("cid2id")
            if _cid2idA is None:
                import hsbg_engine as _EA  # noqa: PLC0415
                _cid2idA = {int(c["cid"]): str(c["id"]) for c in json.loads(_EA.catalog_json())}
                _COMP_FIT_CACHE["cid2id"] = _cid2idA
            _CHAIN = ("BG21_015", "BG29_813", "BG36_245", "BG36_640")
            _turnsA = np.asarray(batch.turns, dtype=np.float64)
            _epsA = np.asarray(batch.episode_ids)
            _bA = np.flatnonzero(np.diff(_epsA) != 0) + 1
            _sA = np.concatenate(([0], _bA))
            _eA = np.concatenate((_bA, [_nA]))
            for _aA, _bAe in zip(_sA.tolist(), _eA.tolist()):
                _start_sig = float(_sigA[_aA])
                _end_sig0 = float(_sigA[_bAe - 1])
                if float(final_3500_w) > 0.0 and _end_sig0 >= 3500.0:
                    delta[_bAe - 1] += float(final_3500_w)
                if float(final_20k_w) > 0.0 and _end_sig0 >= 20000.0:
                    delta[_bAe - 1] += float(final_20k_w)
                if float(late_rel_growth_coef) > 0.0 and _start_sig > 0.0:
                    _end_sig = _end_sig0
                    delta[_bAe - 1] += float(late_rel_growth_coef) * float(
                        np.log1p(max(0.0, _end_sig / _start_sig - 1.0)))
                _last_sig = None
                for _tA in sorted({float(x) for x in _turnsA[_aA:_bAe].tolist()}):
                    _idxsA = np.flatnonzero(_turnsA[_aA:_bAe] == _tA)
                    if not _idxsA.size:
                        continue
                    _ixA = _aA + int(_idxsA[-1])
                    _sig_now = float(_sigA[_ixA])
                    # 链四卡：盘面上出现任意 N 张
                    _cards_now = [str(_cid2idA.get(int(x) - 1, "")) for x in _carrA[_ixA, _OA.SLICE_CARD_BOARD] if int(x) > 0]
                    _norm = {c[:-2] if c.endswith("_G") else c for c in _cards_now if c}
                    _N = sum(1 for c in _CHAIN if c in _norm)
                    if _tA == 9.0 and float(t9_chain_target_w) > 0.0:
                        _tierA = int(float(_fA[_ixA, _OA.GLOBAL_FIELD_INDEX["tier"]]) * 6.0)
                        _compA = sum(1 for _c in ("BG21_015", "BG29_813", "BG36_245", "BG36_640")
                                     if _c in _norm)
                        if _tierA >= 4 and _compA >= 1:
                            _w9 = 0.3 if _compA == 1 else (0.6 if _compA == 2 else 1.0)
                            delta[_ixA] += float(t9_chain_target_w) * (_w9 / 0.5)
                    if _tA <= 10.0 and float(chain_early_w) > 0.0 and (
                            "BG21_015" in _norm or "BG29_813" in _norm or "BG36_245" in _norm):
                        delta[_ixA] += float(chain_early_w)
                    if _N >= 1 and float(chain_any_w) > 0.0:
                        delta[_ixA] += float(chain_any_w)
                    if _N >= 2 and "BG21_015" in _norm and float(chain2_w) > 0.0:
                        delta[_ixA] += float(chain2_w)
                        _ch2["chain2_turns"] = _ch2.get("chain2_turns", 0) + 1
                    if _N:
                        delta[_ixA] += float(chain_w) * _N
                        _ch2["chain_sum"] += _N
                        if _N == 4:
                            delta[_ixA] += float(chain_complete_bonus)
                            _ch2["chain4_turns"] += 1
                    if _last_sig is not None and float(retain_growth_coef) > 0.0:
                        _g = max(0.0, _sig_now - _last_sig)
                        if _g > 0.0:
                            delta[_ixA] += float(retain_growth_coef) * float(np.log1p(_g))
                            _ch2["retain_sum"] += float(np.log1p(_g))
                    _last_sig = _sig_now
                    _ch2["n_turns"] += 1
        except BaseException:  # noqa: BLE001
            pass
    # 后段增长（late-game curriculum）：log1p(Σ15)−log1p(Σ8) + shadow·(Σ15 − 283)
    n_lg = 0
    _lg = {"s8": [], "s15": [], "mult": []}
    if (float(late_growth_coef) > 0.0 or float(late_shadow_coef) > 0.0
            or float(late_log_ratio_coef) > 0.0 or float(late_alive_bonus) > 0.0
            or float(late_death_penalty) > 0.0):
        try:
            import hsbg.env.obs_std as _O7  # noqa: PLC0415
            _f7 = np.asarray(batch.features, dtype=np.float32)
            _n7 = _f7.shape[0]
            _bb7 = _f7[:, _O7.SLICE_BOARD].reshape(_n7, _O7.N_BOARD, _O7.MINION_F)
            _pres7 = _bb7[:, :, _O7.MINION_PRESENT] > 0.5
            _sig7 = np.where(_pres7, (_bb7[:, :, _O7.MINION_ATK]
                                      + _bb7[:, :, _O7.MINION_HP]) * 10.0, 0.0).sum(axis=1)
            _turns7 = np.asarray(batch.turns, dtype=np.float64)
            _eps7 = np.asarray(batch.episode_ids)
            _b7 = np.flatnonzero(np.diff(_eps7) != 0) + 1
            _s7 = np.concatenate(([0], _b7))
            _e7 = np.concatenate((_b7, [_n7]))
            for _a, _b in zip(_s7.tolist(), _e7.tolist()):
                _i0 = _a
                _i1 = _b - 1
                _s8 = float(_sig7[_i0])
                _s15 = float(_sig7[_i1])
                _r = float(late_growth_coef) * (float(np.log1p(_s15)) - float(np.log1p(_s8)))
                _r += float(late_shadow_coef) * (_s15 - 283.0)
                if float(late_log_ratio_coef) > 0.0:
                    _shadow = float(late_shadow_ratio) * _s8
                    _r += float(late_log_ratio_coef) * (
                        float(np.log1p(_s15)) - float(np.log1p(_shadow)))
                if float(late_alive_bonus) > 0.0 or float(late_death_penalty) > 0.0:
                    _last_turn = float(_turns7[_i1])
                    if _last_turn >= 15.0:
                        _r += float(late_alive_bonus)
                    else:
                        _r -= float(late_death_penalty)
                delta[_i1] += _r
                _lg["s8"].append(_s8)
                _lg["s15"].append(_s15)
                _lg["mult"].append(_s15 / max(1.0, _s8))
                n_lg += 1
        except BaseException:  # noqa: BLE001
            pass
    # 金探针（始终记录、不进奖励）：t9 回合末金币 → 能付得起 tier5 的局比例
    n_gp = 0
    _gp_g8 = _gp_g9 = 0
    _gp_sum = 0.0
    if True:
        try:
            import hsbg.env.obs_std as _O6  # noqa: PLC0415
            _fg = np.asarray(batch.features, dtype=np.float32)
            _gold6 = _fg[:, _O6.GLOBAL_FIELD_INDEX["gold"]] * 10.0
            _turns6 = np.asarray(batch.turns, dtype=np.float64)
            _eps6 = np.asarray(batch.episode_ids)
            _bg = np.flatnonzero(np.diff(_eps6) != 0) + 1
            _sg = np.concatenate(([0], _bg))
            _eg = np.concatenate((_bg, [_fg.shape[0]]))
            for _a, _b in zip(_sg.tolist(), _eg.tolist()):
                _i9 = np.flatnonzero(_turns6[_a:_b] == 9.0)
                if not _i9.size:
                    continue
                _gi = _a + int(_i9[-1])
                _g = float(_gold6[_gi])
                _gp_sum += _g
                n_gp += 1
                if _g >= 8.0:
                    _gp_g8 += 1
                if _g >= 9.0:
                    _gp_g9 += 1
        except BaseException:  # noqa: BLE001
            pass
    # T1'：t1-9 经济与存活里程碑（二值 +1/-1，权重 tier .4 / sigma .3 / survive .2 / races .1）
    n_t1p = 0
    _t1p = {"tier8": 0, "tier9": 0, "sig7": 0, "sig9": 0, "surv": 0, "races": 0,
            "t9_tier": [], "t9_sig": [], "death": [], "races9": []}
    if float(t1p_coef) > 0.0:
        try:
            import hsbg.env.obs_std as _O2  # noqa: PLC0415
            _f = np.asarray(batch.features, dtype=np.float32)
            _n2 = _f.shape[0]
            _bb = _f[:, _O2.SLICE_BOARD].reshape(_n2, _O2.N_BOARD, _O2.MINION_F)
            _present = _bb[:, :, _O2.MINION_PRESENT] > 0.5
            _sig = np.where(_present, (_bb[:, :, _O2.MINION_ATK]
                                       + _bb[:, :, _O2.MINION_HP]) * 10.0, 0.0).sum(axis=1)
            _tier_p = _f[:, _O2.GLOBAL_FIELD_INDEX["tier"]] * 6.0
            _carr2 = np.asarray(batch.cards, dtype=np.int64)
            if _carr2.ndim == 1:
                _carr2 = _carr2.reshape(-1, 124)
            _bcids = _carr2[:, _O2.SLICE_CARD_BOARD]
            _T2 = _comp_fit_tables()
            _cid2id2 = _COMP_FIT_CACHE.get("cid2id")
            if _cid2id2 is None:
                import hsbg_engine as _E2  # noqa: PLC0415
                _cid2id2 = {int(c["cid"]): str(c["id"]) for c in json.loads(_E2.catalog_json())}
                _COMP_FIT_CACHE["cid2id"] = _cid2id2
            _cards2 = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
            if isinstance(_cards2, dict):
                _cards2 = _cards2.get("cards") or _cards2.get("data") or list(_cards2.values())
            _by2 = {str(c["id"]): c for c in _cards2 if isinstance(c, dict) and c.get("id")}
            _turns2 = np.asarray(batch.turns, dtype=np.float64)
            _eps2 = np.asarray(batch.episode_ids)
            _b2 = np.flatnonzero(np.diff(_eps2) != 0) + 1
            _s2 = np.concatenate(([0], _b2))
            _e2 = np.concatenate((_b2, [_n2]))
            _w = {"tier": 0.4, "sig": 0.3, "surv": 0.2, "races": 0.1}
            for _st, _en in zip(_s2.tolist(), _e2.tolist()):
                _last = _en - 1
                _lt = float(_turns2[_last])
                _hit = {}
                for _tt in (7, 8, 9):
                    _idxs = np.flatnonzero(_turns2[_st:_en] == float(_tt))
                    _hit[_tt] = (_st + int(_idxs[-1])) if _idxs.size else None
                # 种族数（t9 或末回合）
                _race_cnt = {}
                for _tt, _idx in _hit.items():
                    if _idx is None:
                        continue
                    _rr = set()
                    for _c in _bcids[_idx]:
                        _cid = int(_c) - 1
                        if _cid < 0:
                            continue
                        _c_obj = _by2.get(_cid2id2.get(_cid, "")) or {}
                        for _r in (_c_obj.get("races") or []):
                            _rr.add(str(_r))
                    _race_cnt[_tt] = len(_rr)
                # t7 Σ>=200
                if _hit[7] is not None:
                    ok = float(_sig[_hit[7]]) >= 200.0
                    delta[_hit[7]] += _w["sig"] * (1.0 if ok else -1.0)
                    if ok:
                        _t1p["sig7"] += 1
                else:
                    delta[_last] -= _w["sig"]
                # t8 tier>=4
                if _hit[8] is not None:
                    ok = float(_tier_p[_hit[8]]) >= 4.0 - 1e-6
                    delta[_hit[8]] += _w["tier"] * (1.0 if ok else -1.0)
                    if ok:
                        _t1p["tier8"] += 1
                else:
                    delta[_last] -= _w["tier"]
                # t9: tier>=5 / Σ>=400 / races<=3
                if _hit[9] is not None:
                    _i9 = _hit[9]
                    ok_t = float(_tier_p[_i9]) >= 5.0 - 1e-6
                    delta[_i9] += _w["tier"] * (1.0 if ok_t else -1.0)
                    if ok_t:
                        _t1p["tier9"] += 1
                    ok_s = float(_sig[_i9]) >= 400.0
                    delta[_i9] += _w["sig"] * (1.0 if ok_s else -1.0)
                    if ok_s:
                        _t1p["sig9"] += 1
                    _rc = int(_race_cnt.get(9, 99))
                    ok_r = _rc <= 3
                    delta[_i9] += _w["races"] * (1.0 if ok_r else -1.0)
                    if ok_r:
                        _t1p["races"] += 1
                    _t1p["t9_tier"].append(float(_tier_p[_i9]))
                    _t1p["t9_sig"].append(float(_sig[_i9]))
                    _t1p["races9"].append(_rc)
                else:
                    delta[_last] -= (_w["tier"] + _w["sig"] + _w["races"])
                # 存活：death/末回合 >=12
                ok_d = _lt >= 12.0
                delta[_last] += _w["surv"] * (1.0 if ok_d else -1.0)
                if ok_d:
                    _t1p["surv"] += 1
                _t1p["death"].append(_lt)
                n_t1p += 1
        except BaseException:  # noqa: BLE001
            pass
    if not (n_up or n_win or n_gold or n_gold5 or n_ampb or n_engb or n_surv
            or n_t5tim or n_t6tim or n_cheap or n_t5buff or n_mix or n_lowstat
            or n_cf
            or float(strength_c) > 0.0 or float(t5plus_stat_w) > 0.0
            or float(tier_timing_w) > 0.0 or float(cheap_buy_p) > 0.0
            or float(t5plus_buff_w) > 0.0 or float(tier_mix_w) > 0.0
            or float(tier_mix_w) > 0.0 or float(lowtier_stat_p) > 0.0
            or float(comp_fit_c) > 0.0 or float(comp_fit_t9_bonus) > 0.0
            or float(comp_trinket_c) > 0.0 or float(t1p_coef) > 0.0
            or float(t1s_coef) > 0.0 or float(save_up_w) > 0.0
            or float(late_growth_coef) > 0.0 or float(late_shadow_coef) > 0.0
            or float(late_log_ratio_coef) > 0.0 or float(late_alive_bonus) > 0.0
            or float(late_death_penalty) > 0.0
            or float(churn_w) > 0.0 or float(hightier_w) > 0.0 or float(hero_power_w) > 0.0
            or float(tier_early_w) > 0.0
            or float(chain_w) > 0.0 or float(chain_complete_bonus) > 0.0
            or float(retain_growth_coef) > 0.0):
        return None
    rewards = (np.asarray(batch.rewards, dtype=np.float64) + delta)
    adv, ret = compute_gae(rewards, np.asarray(batch.values, dtype=np.float64),
                           np.asarray(batch.dones, dtype=np.float64),
                           gamma=float(gamma), lam=float(lam))
    batch.rewards = rewards.astype(np.float32)
    batch.advantages = adv
    batch.returns = ret
    return {"upgrade_w": float(upgrade_w), "upgrade_hits": n_up,
            "win_w": float(win_w), "win_episodes": n_win,
            "strength_c": float(strength_c),
            "golden_w": float(golden_w), "goldens_total": n_gold,
            "golden_t5_w": float(golden_t5_w), "goldens_t5_total": n_gold5,
            "amp_board_w": float(amp_board_w), "amp_board_total": n_ampb,
            "engine_board_w": float(engine_board_w), "engine_board_total": n_engb,
            "survive_t12_w": float(survive_t12_w), "survive_t12_eps": n_surv,
            "t5plus_stat_w": float(t5plus_stat_w), "t5plus_stat_eps": n_t5stat,
            "t5plus_stat_share_mean": float(_t5_share_mean),
            "tier_timing_w": float(tier_timing_w),
            "tier5_timing_eps": n_t5tim, "tier6_timing_eps": n_t6tim,
            "cheap_buy_p": float(cheap_buy_p), "cheap_buys": n_cheap,
            "t5plus_buff_w": float(t5plus_buff_w), "t5plus_buff_eps": n_t5buff,
            "t5plus_buff_sum_mean": float(_t5buff_mean),
            "tier_mix_w": float(tier_mix_w), "tier_mix_eps": n_mix,
            "tier_mix_mean": float(_mix_mean),
            "lowtier_stat_p": float(lowtier_stat_p), "lowtier_stat_eps": n_lowstat,
            "lowtier_stat_mean": float(_lowstat_mean),
            "comp_fit_c": float(comp_fit_c), "comp_fit_eps": n_cf,
            "comp_fit9_mean": float(_cf_fit9_mean),
            "comp_fit_t9_bonus": float(comp_fit_t9_bonus),
            "comp_trinket_c": float(comp_trinket_c),
            "comp_trinket_hits": _cf_trinket_hits,
            "t1p_coef": float(t1p_coef), "t1p_eps": n_t1p,
            "t1p_tier8": _t1p["tier8"], "t1p_tier9": _t1p["tier9"],
            "t1p_sig7": _t1p["sig7"], "t1p_sig9": _t1p["sig9"],
            "t1p_surv": _t1p["surv"], "t1p_races": _t1p["races"],
            "t1p_t9_tier_mean": (float(np.mean(_t1p["t9_tier"])) if _t1p["t9_tier"] else None),
            "t1p_t9_sig_mean": (float(np.mean(_t1p["t9_sig"])) if _t1p["t9_sig"] else None),
            "t1p_death_mean": (float(np.mean(_t1p["death"])) if _t1p["death"] else None),
            "t1p_races9_mean": (float(np.mean(_t1p["races9"])) if _t1p["races9"] else None),
            "t1s_coef": float(t1s_coef), "t1s_eps": n_t1s,
            "t1s_tier_ok": _t1s["tier_ok"], "t1s_gold_ok": _t1s["gold_ok"],
            "t1s_races_ok": _t1s["races_ok"], "t1s_alive_late": _t1s["alive_late"],
            "t1s_t9_tier_mean": (float(np.mean(_t1s["t9_tier"])) if _t1s["t9_tier"] else None),
            "t1s_t9_sig_mean": (float(np.mean(_t1s["t9_sig"])) if _t1s["t9_sig"] else None),
            "t1s_death_mean": (float(np.mean(_t1s["death"])) if _t1s["death"] else None),
            "late_growth_coef": float(late_growth_coef), "late_shadow_coef": float(late_shadow_coef),
            "churn_w": float(churn_w), "hightier_w": float(hightier_w),
            "hero_power_w": float(hero_power_w),
            "churn_sells": _ch["sells"], "churn_rolls": _ch["rolls"],
            "churn_h4": _ch["h4"], "churn_h5": _ch["h5"], "churn_h6": _ch["h6"],
            "churn_hp": _ch["hp"],
            "chain_w": float(chain_w), "chain_complete_bonus": float(chain_complete_bonus),
            "retain_growth_coef": float(retain_growth_coef),
            "chain2_w": float(chain2_w), "chain2_turns": _ch2.get("chain2_turns", 0),
            "late_rel_growth_coef": float(late_rel_growth_coef),
            "final_3500_w": float(final_3500_w), "final_20k_w": float(final_20k_w),
            "scaling_value_w": float(scaling_value_w),
            "sv_p_mean": round(_sv["p_mean"], 4), "sv_dp_sum": round(_sv["dp_sum"], 3),
            "sv_p50": round(_sv.get("p50", 0.0), 4), "sv_p90": round(_sv.get("p90", 0.0), 4),
            "sv_spearman": round(_sv.get("spearman", 0.0), 3),
            "sv_dp_turn_mean": round(_sv["dp_sum"] / max(1, _dp_turns), 5),
            "sv_eps": n_sv, "chain_early_w": float(chain_early_w),
            "chain_any_w": float(chain_any_w), "t9_chain_target_w": float(t9_chain_target_w),
            "roll_bonus_t8t9": float(roll_bonus_t8t9),
            "strength_from_turn": float(strength_from_turn),
            "chain_turns": _ch2["n_turns"], "chain_card_sum": _ch2["chain_sum"],
            "chain4_turns": _ch2["chain4_turns"], "retain_sum": round(_ch2["retain_sum"], 2),
            "tier_early_w": float(tier_early_w), "tier_early_t4": _te["t4"],
            "tier_early_t5": _te["t5"],
            "churn_pair_sell": _ch.get("pair", {}).get("n_sell", 0),
            "churn_pair_sell_hit": _ch.get("pair", {}).get("n_sell_pair", 0),
            "churn_pair_roll": _ch.get("pair", {}).get("n_roll", 0),
            "churn_pair_roll_hit": _ch.get("pair", {}).get("n_roll_pair", 0), "churn_early_upg": _ch.get("early_upg", 0),
            "churn_buf": round(_ch["buf"], 3),
            "late_log_ratio_coef": float(late_log_ratio_coef),
            "late_alive_bonus": float(late_alive_bonus),
            "late_death_penalty": float(late_death_penalty),
            "late_shadow_ratio": float(late_shadow_ratio),
            "late_eps": n_lg,
            "late_sigma8_mean": (float(np.mean(_lg["s8"])) if _lg["s8"] else None),
            "late_sigma15_mean": (float(np.mean(_lg["s15"])) if _lg["s15"] else None),
            "late_mult_mean": (float(np.mean(_lg["mult"])) if _lg["mult"] else None),
            "gold_probe_eps": n_gp,
            "gold_probe_t9_mean": (round(_gp_sum / n_gp, 3) if n_gp else None),
            "gold_probe_t9_g8_rate": (round(_gp_g8 / n_gp, 3) if n_gp else None),
            "gold_probe_t9_g9_rate": (round(_gp_g9 / n_gp, 3) if n_gp else None),
            "save_up_w": float(save_up_w), "save_up_eps": n_su,
            "save_gold7_mean": (float(np.mean(_su["g7"])) if _su["g7"] else None),
            "save_gold8_mean": (float(np.mean(_su["g8"])) if _su["g8"] else None),
            "save_gold9_mean": (float(np.mean(_su["g9"])) if _su["g9"] else None),
            "save_t9_upg_rate": (float(_su["t9_upg"]) / n_su if n_su else None),
            "save8_rate": (float(_su["save8"]) / n_su if n_su else None),
            "save8_then_t9upg_rate": (float(_su["save8_upg"]) / _su["save8"]
                                      if _su["save8"] else None),
            "t1s_upg_elig": _t1s["upg_elig"], "t1s_upg_hit": _t1s["upg_hit"],
            "t1s_upg_games": _t1s.get("upg_games", 0),
            "t1s_upg_per_game": _t1s.get("upg_per_game"),
            "t1s_buy_per_game": _t1s.get("buy_per_game"),
            "t1s_t9_gold_mean": _t1s.get("t9_gold_mean"),
            "t1s_gold_after_upg_mean": _t1s.get("gold_after_upg_mean"),
            "t1s_buys_upg_turn_mean": _t1s.get("buys_upg_turn_mean"),
            "reward_delta_sum": float(delta.sum()),
            "reward_delta_abs": float(np.abs(delta).sum())}


def _critic_param_names(model: Any, *, use_value_head: bool) -> List[str]:
    """默认 critic 路径 = ``rank_head``（8 名次 CE）；``value_head`` 只在 coef>0 时加入。"""
    names = [n for n, _ in model.named_parameters() if n.startswith("rank_head")]
    if use_value_head:
        names += [n for n, _ in model.named_parameters() if n.startswith("value_head")]
    return names


def _value_warmup(trainer: Any, batch: Any, *, iters: int, lr: float,
                  minibatch: int, seed: int) -> Optional[Dict[str, Any]]:
    """critic 预热：只训 critic 头（rank 头[+标量 value 头]）``iters`` 遍。

    为什么必须有：BC 只训策略 ⇒ critic 头仍是**随机初始化**。此时 GAE 的 advantage 与真实
    优势近似无关（沙盒实测符号一致率 52.8% ≈ 抛硬币），PPO 第一个 iteration 就会把策略
    推歪。这里先在**第一个 iteration 的真实轨迹**上把 critic 头校准到「能预测真实名次」。

    为什么只训头：entity 的 critic 与策略**共享 trunk**，整网回传会改变策略 logits
    （沙盒踩过：anchor_kl 首行 0.205、130k 后 Σ 1646→524）。冻结除 critic 头以外的全部
    参数 ⇒ 策略漂移**严格为 0**（由构造保证，不是经验值）。

    默认 ``iters=0`` 时本函数不会被调用 ⇒ 默认路径逐位等价于旧行为。
    """
    import torch  # noqa: PLC0415 - 延迟导入：tiny 路径不保证有 torch
    model = trainer.model
    cfg = trainer.config
    dev = torch.device(trainer.device)
    use_vh = float(getattr(cfg, "value_head_coef", 0.0) or 0.0) > 0.0
    names = _critic_param_names(model, use_value_head=use_vh)
    if not names:
        print("[value-warmup] 模型没有 rank_head/value_head，跳过预热", flush=True)
        return None
    name_set = set(names)
    params = [p for n, p in model.named_parameters() if n in name_set]
    n_params = int(sum(p.numel() for p in params))
    model.eval()

    n = len(batch)
    if n <= 0:
        print("[value-warmup] 批次为空，跳过预热", flush=True)
        return None
    mb = max(1, min(int(minibatch or 1024), int(n)))
    rng = np.random.default_rng([int(seed), 0x5A1])
    ranks_np = np.asarray(batch.ranks, dtype=np.int64)
    rets_np = np.asarray(batch.returns, dtype=np.float32)
    rank_mode = str(getattr(cfg, "value_loss", "rank")).strip().lower() == "rank"
    amp_bf16 = (str(getattr(cfg, "amp", "off")).strip().lower() in ("bf16", "bfloat16")
                and dev.type == "cuda")
    F = torch.nn.functional
    hist: List[float] = []
    for p in model.parameters():
        p.requires_grad_(False)
    for p in params:
        p.requires_grad_(True)
    opt = torch.optim.Adam(params, lr=float(lr))
    try:
        for _w in range(max(1, int(iters))):
            order = rng.permutation(int(n))
            tot, cnt = 0.0, 0
            for s0 in range(0, int(n), mb):
                idx = order[s0:s0 + mb]
                x = torch.from_numpy(np.ascontiguousarray(batch.features[idx])).to(dev)
                c = torch.from_numpy(
                    np.ascontiguousarray(batch.cards[idx].astype(np.int64))).to(dev)
                m = torch.from_numpy(
                    np.ascontiguousarray(batch.masks[idx].astype(bool))).to(dev)
                if amp_bf16:
                    with torch.autocast("cuda", dtype=torch.bfloat16):
                        _lg, rank_logits, scalar_value = forward_model(model, x, c, m)
                else:
                    _lg, rank_logits, scalar_value = forward_model(model, x, c, m)
                rl = rank_logits.float()
                if rank_mode:
                    tgt = torch.from_numpy(np.ascontiguousarray(
                        (ranks_np[idx] - 1).clip(0, rl.shape[-1] - 1))).to(dev)
                    loss = F.cross_entropy(rl, tgt)
                else:
                    tgt = torch.from_numpy(
                        np.ascontiguousarray(rets_np[idx])).to(dev)
                    loss = F.mse_loss(value_from_rank_logits_torch(rl), tgt)
                if use_vh and scalar_value is not None:
                    loss = loss + float(cfg.value_head_coef) * F.mse_loss(
                        scalar_value.float().reshape(-1), tgt)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                opt.step()
                tot += float(loss.detach()) * int(len(idx))
                cnt += int(len(idx))
            hist.append(tot / max(1, cnt))
    finally:
        for p in model.parameters():
            p.requires_grad_(True)
        model.zero_grad(set_to_none=True)
        model.eval()
    out = {"iters": int(iters), "critic_params": n_params,
           "critic_param_names": names, "lr": float(lr), "minibatch": mb,
           "loss_mode": "rank_ce" if rank_mode else "mse",
           "loss_first": float(hist[0]) if hist else None,
           "loss_last": float(hist[-1]) if hist else None,
           "n_samples": int(n), "policy_drift_by_construction": 0.0}
    print(f"[value-warmup] critic={names} params={n_params:,} iters={iters} "
          f"lr={lr:g} mb={mb} mode={out['loss_mode']} "
          f"loss {out['loss_first']:.4f} -> {out['loss_last']:.4f} "
          f"(n={n}; 策略/trunk 冻结 ⇒ 策略漂移=0)", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Entity PPO（持久 trainer + 进程 pool + 流水线）")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--stop-at-decisions", type=float, default=0.0,
                    help="累计 learner decisions 达到该值后停止（0=不启用）；与 --minutes 取先到者")
    ap.add_argument("--iterations", type=int, default=0)
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--arch", default="entity", choices=["tiny", "entity", "entity18m"])
    # ── entity 尺寸（只影响**从零构建**；带 --checkpoint/--trainer-state 时以 checkpoint
    #    meta 为准，本组只做一致性校验）。默认 0 = build_net 的历史默认（384/8/8），
    #    因此不传时与原路径逐位等价。0.667M = --d-model 128 --n-layers 2 --n-heads 4。
    ap.add_argument("--d-model", type=int, default=0,
                    help="entity 宽度（0=默认 384）；从零构建时生效")
    ap.add_argument("--n-layers", type=int, default=0,
                    help="entity Transformer 层数（0=默认 8）；从零构建时生效")
    ap.add_argument("--n-heads", type=int, default=0,
                    help="entity 注意力头数（0=默认 8）；从零构建时生效")
    ap.add_argument("--move-head-split", type=int, default=0, choices=[0, 1],
                    help="1=Move 段（196..244）用有向双投影（move_from/move_to），"
                         "方向差不再只由 move_bias 决定；旧 checkpoint 自动只初始化新投影。"
                         "默认 0=保持对称实现（逐位兼容旧 ckpt）")
    ap.add_argument("--move-guard", type=int, default=0, choices=[0, 1],
                    help="1=换位去抖守卫：采样前屏蔽「逆换位 / 同动作超限 / 本回合换位"
                         "超 cap」的 Move 动作位（见 docs/MOVE_GUARD.md）。"
                         "默认 0=关闭（与旧路径逐位等价）")
    ap.add_argument("--move-cap", type=int, default=3,
                    help="每回合换位次数上限：>=cap 后屏蔽全部 Move（默认 3；0=本回合禁止换位）")
    ap.add_argument("--move-repeat-limit", type=int, default=2,
                    help="同一 (from,to) 本回合出现 >=N 次后屏蔽（默认 2；1=不允许重复）")
    # ── 流派（archetype）软偏置（默认关闭；见 docs/ARCHETYPE_BIAS.md）──
    ap.add_argument("--archetype-bias-coef", type=float, default=0.0,
                    help="流派软偏置系数：0=关闭（逐位等价旧路径）。对当前流派在当前 "
                         "turn 的偏好动作加 coef*相对增益 的 logit（只加不减、不屏蔽），"
                         "建议 0.5–2.0")
    ap.add_argument("--archetype-min-prob", type=float, default=0.6,
                    help="检测置信度门槛：max_prob >= 该值才偏置（低置信不偏置，默认 0.6）")
    ap.add_argument("--archetype-table", default="",
                    help="偏好表路径（空= data/archetype/archetype_table.json）")
    ap.add_argument("--archetype-model", default="",
                    help="分类器模型路径（空= data/archetype/archetype_model.npz）")
    ap.add_argument("--archetype-cache", type=int, default=0,
                    help="1=流派特征/分类走输入哈希缓存（输出逐位相同，但实测命中率≈0，"
                         "默认 0 关闭；见 docs/PERF_COLLECT.md）")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--sims", type=int, default=4)
    ap.add_argument("--determinizations", type=int, default=1)
    ap.add_argument("--opponent", default="bot", choices=["bot", "self", "weak"])
    ap.add_argument("--behavior", default="net", choices=["net", "mcts", "mixed"])
    # ── 搜索作为行为策略：μ=(1−ε)π+ε·π_search（默认 eps=0 = 关闭、逐位等价旧路径）──
    #   见 hsbg/az/train/behavior_mix.py 与 docs/BEHAVIOR_MIX_PPO.md。
    ap.add_argument("--behavior-mix-eps", type=float, default=0.0,
                    help="关键决策以该概率改用 π_search 采样（μ=(1−ε)π+ε·π_search）；"
                         "0=关闭（默认，逐位等价旧路径）；建议 0.1–0.3")
    ap.add_argument("--behavior-mix-when", default="carrier_or_spell",
                    help="关键决策口径（sandbox_rollout.SEARCH_WHEN_NAMES；可逗号组合，"
                         "默认 carrier_or_spell，与 t6/AB 面板同口径）")
    ap.add_argument("--behavior-mix-max-per-turn", type=int, default=6,
                    help="每回合最多搜索几次（0=不限；默认 6 = t6 配置）")
    ap.add_argument("--behavior-mix-topk", type=int, default=8,
                    help="根候选数 = π top-k 非 Move 合法动作（默认 8）")
    ap.add_argument("--behavior-mix-turns", type=int, default=1,
                    help="叶值 horizon：1=到本回合末（默认，沿用 s17 的 t1 口径）")
    ap.add_argument("--behavior-mix-max-ms", type=float, default=500.0,
                    help="单次搜索墙钟上限（ms；0=不限）：超时放弃搜索、回退按 π 采样")
    ap.add_argument("--behavior-mix-exact", type=int, default=1, choices=[0, 1],
                    help="1=精确模式（默认）：每个关键决策都跑搜索，logp_mu 对全部"
                         "分支精确（IS 比 π/μ 无偏，权重 ≤1/(1−ε)）；"
                         "0=只在 ε 命中时搜索（成本 ×ε，跨分支不再等价 marginal μ）")
    ap.add_argument("--behavior-mix-report", default="",
                    help="可选：逐 iteration 的混合统计 JSONL 落盘路径（空=只写进 "
                         "history.jsonl 的 collect 段）")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--minibatch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lr-min-ratio", type=float, default=0.1)
    ap.add_argument("--max-updates", type=int, default=100000)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--target-kl", type=float, default=0.05)
    ap.add_argument("--lam", type=float, default=0.95,
                    help="GAE λ（与折扣 γ 无关；论文 0.995）")
    ap.add_argument("--gamma", type=float, default=1.0,
                    help="训练折扣 γ（默认 1.0：8 座单局终局效用；不是 GAE 的 λ）")
    # ── 信用分配（§B；默认 gae = 旧路径逐位等价）──
    ap.add_argument("--adv-estimator", default="gae",
                    choices=["gae", "power", "geom"],
                    help="advantage 时间核：gae=旧 GAE；power=幂率/分数阶；geom=几何对照")
    ap.add_argument("--power-alpha", type=float, default=0.25,
                    help="幂率核 α>=0（w_l=(1+l/κ)^(−α)）；仅 adv-estimator=power 生效")
    ap.add_argument("--power-kappa", type=float, default=10.0,
                    help="幂率核 κ>0；离线推荐 α=0.25, κ=10（见 docs/CREDIT_ASSIGNMENT.md）")
    ap.add_argument("--power-normalize", type=int, default=1, choices=[0, 1],
                    help="1=horizon 归一化（§B.1）；离线诊断建议 A/B 用 0"
                         "（归一化会把早期 |A| 压成 ~1/L）")
    ap.add_argument("--power-cutoff", type=int, default=0,
                    help="lag 截断（0=不截断）")
    ap.add_argument("--credit-timebase", default="decision",
                    choices=["decision", "turn"],
                    help="decision=按动作步；turn=未来 elapsed turn 的 SMDP 折扣")
    ap.add_argument("--baseline-action-dependent", type=int, default=0,
                    choices=[0, 1],
                    help="动作条件 baseline：仅允许 0（actor baseline 只用 V(s)）。"
                         "1 会直接报错，见 §B.3")
    ap.add_argument("--max-grad-norm", type=float, default=0.5,
                    help="梯度裁剪范数（论文 1.0）")
    ap.add_argument("--grad-accum", type=int, default=1,
                    help="梯度累积步数：有效 minibatch = minibatch * grad_accum（论文 8192）")
    ap.add_argument("--leaf-compile", type=int, default=0,
                    help="1=叶前向 torch.compile + TF32（实测 B=64 5.4→0.7 ms）")
    ap.add_argument("--leaf-amp", default="off", choices=["off", "bf16"],
                    help="采集/评测叶前向精度（bf16 实测 collect 约 -5%%）")
    ap.add_argument("--leaf-wait-ms", type=float, default=2.0,
                    help="批量叶服务器聚批等待（ms）；单客户端建议 0.1")
    ap.add_argument("--rc-threads", type=int, default=8,
                    help="Rust 采集器内部引擎线程数（BatchEnv threads）")
    ap.add_argument("--rust-collector", type=int, default=0,
                    help="1=Rust 全采集器（BatchEnv 驱动，记录打包在 Rust）")
    ap.add_argument("--library-pool", default="",
                    help="镜像对手库 JSONL（空=不用）；见 docs/LIBRARY_POOL_PLAN.md")
    ap.add_argument("--frozen-seats", type=int, default=0,
                    help="由冻结对手驱动的 bot 座位数（1–2 性价比最高；7=全部，慢 ~25x）")
    ap.add_argument("--frozen-opponent", default="",
                    help="冻结对手模型 checkpoint（空=引擎 bot）；bot 座位由它驱动（分裂模型/自对弈）")
    ap.add_argument("--script-seats", type=int, default=0,
                    help="脚本席数（0..3，默认 0）：把 1..N 号 bot 席位换成固定阵容脚本"
                         "（comp scripts，hybrid：阵容动作优先、其余引擎 bot）。"
                         "脚本席只改变对手分布，不改变奖励/PPO 数学；需要 --lockstep 1、"
                         "--opponent bot|weak，且不能与 --frozen-opponent 同时给。")
    ap.add_argument("--script-comps", default="auto",
                    help="脚本席阵容：auto（按 seed 稳定轮转）或逗号分隔的阵容 key"
                         "（见 python scripts/comp_scripts.py --list）")
    ap.add_argument("--trajectory-pool", default="",
                    help="对手场面轨迹库目录（空=不用）；见 docs/LIBRARY_POOL_PLAN.md")
    ap.add_argument("--trajectory-p", type=float, default=0.0,
                    help="每局被轨迹镜像替换的概率（建议 0.1 起）")
    ap.add_argument("--mirror-snaps", default="",
                    help="回合末场面快照库目录（snap_*.json.gz；空=不用）；见 "
                         "docs/MIRROR_SNAPSHOT_DESIGN.md")
    ap.add_argument("--mirror-seats", type=int, default=0,
                    help="回合末快照镜像的座位数：给 seat 1..N 注入（0=关闭，最大 7）")
    ap.add_argument("--mirror-p", type=float, default=0.0,
                    help="每座位每回合注入快照的概率（默认 0=关闭，零影响）")
    ap.add_argument("--mirror-sample", "--sample", dest="mirror_sample", default="p50",
                    choices=["p50", "p75", "p90", "max", "strong", "weak", "random"],
                    help="快照桶内采样：p50/p75/p90=强度分位课程（默认），max/strong=旧上限")
    ap.add_argument("--mirror-p-ramp", default="",
                    help="线性 p ramp，如 0.1@0,0.25@0.3,0.25@1.0（x 与 iteration 同单位）；"
                         "空=用固定 --mirror-p")
    ap.add_argument("--mirror-seat-random", type=int, default=0,
                    help="1=每回合从全部非 learner 座位随机抽 --mirror-seats 个（课程模式）")
    ap.add_argument("--human-boards", default="",
                    help="人类战团（board-only）JSONL（默认 "
                         "data/real_library/library_real_degraded.jsonl；空=不用）；见 "
                         "docs/HUMAN_BOARD_OPPONENT.md")
    ap.add_argument("--human-board-p", type=float, default=0.0,
                    help="每个候选座位每回合注入人类战团的概率（默认 0=关闭，零影响）")
    ap.add_argument("--human-board-seats", type=int, default=2,
                    help="每回合从全部非 learner 座位里随机抽几个座位注入（默认 2）")
    ap.add_argument("--human-board-sample", default="auto",
                    choices=["auto", "p50", "p75", "p90", "max"],
                    help="人类战团桶内分位：auto=按 turn 走难度曲线（t<=8 p50 / 9..12 p75 "
                         "/ t>=13 p90，默认）")
    ap.add_argument("--human-board-set-tier", type=int, default=1,
                    help="1=同时写入按 turn 派生的酒馆等级（人类数据没有 tier 字段；默认 1）")
    ap.add_argument("--human-board-fidelity", default="board",
                    choices=["board", "hand", "full"],
                    help="人类战团注入保真度：board=board-only（默认，逐位等价现状）；"
                         "hand=board+手牌；full=board+hand+可推断 counters"
                         "（关键词位/金身/圣盾层数/tavern tier）。hand/full 需要 "
                         "data/real_library/library_real_quasi_full.jsonl"
                         "（scripts/build_fidelity_library.py 生成）；见 "
                         "docs/FIDELITY_INJECTION.md")
    ap.add_argument("--human-board-fast-inject", type=int, default=0,
                    help="1=人类战团注入走快速路径（payload 注入视图缓存 + orjson + "
                         "ended 位字符串替换）；**与默认路径逐位等价**（同 seed 动作序列/"
                         "状态 JSON 完全相同），实测采集侧 Python 成本降约四成。默认 0=旧路径")
    # ---- 对手强度课程：human-board 席数/概率/分位按累计 decisions 爬坡 ----
    #     默认（空 spec + adaptive=0）完全恒等：CollectConfig 里仍是 --human-board-* 的值。
    #     见 docs/BOARD_RAMP.md。
    ap.add_argument("--human-board-ramp", default="",
                    help="对手强度课程（席数/概率）：decisions:seats:p,...，例 "
                         "\"0:1:0.30,10M:2:0.50,20M:3:0.70,30M:5:0.90\"。按**累计 learner "
                         "decisions** 求值，decisions 支持 K/M/B 后缀；空=用固定 "
                         "--human-board-seats/--human-board-p（默认，逐位等价）")
    ap.add_argument("--human-board-quantile-ramp", default="",
                    help="分位课程（与席数/p 独立）：decisions:quantile,...，例 "
                         "\"0:p75,20M:p90\"；取值 auto/p50/p75/p90/max；空=用固定 "
                         "--human-board-sample（默认不爬坡）")
    ap.add_argument("--ramp-mode", default="step", choices=["step", "linear"],
                    help="档位插值方式：step=分段常数（默认，边界突变）；linear=段内线性"
                         "（seats 四舍五入、p 连续），用于平滑过渡实验")
    ap.add_argument("--ramp-adaptive", type=int, default=0, choices=[0, 1],
                    help="1=自适应门控：用最近 --ramp-window 个 iter 的「存活到 t12」与"
                         "「tier>=4」比例决定提前升档（连续达标）/推迟下一档（不达标）；"
                         "默认 0=严格按 decisions 走课程")
    ap.add_argument("--ramp-window", type=int, default=5,
                    help="自适应门控的滑动窗口 iteration 数（默认 5）")
    ap.add_argument("--ramp-survive-threshold", type=float, default=0.25,
                    help="升档门槛：窗口内存活到 t12 比例 >= 该值（默认 0.25）")
    ap.add_argument("--ramp-tier4-threshold", type=float, default=0.30,
                    help="升档门槛：窗口内 tier>=4 比例 >= 该值（默认 0.30）")
    ap.add_argument("--ramp-delay-decisions", default="2M",
                    help="不达标时把后续档位整体推迟多少 decisions（默认 2M；每档最多一次）")
    ap.add_argument("--ramp-max-forced-per-game", type=float, default=12.0,
                    help="门控保护：每局「强制结束回合」均值超过该值说明存活是动作上限"
                         "刷出来的假象，不允许提前升档（默认 12；s15 真实值 ≈0.16）")
    ap.add_argument("--ramp-start-decisions", default="0",
                    help="ramp 的起始累计 decisions 偏移（续训时要传上一次的累计值，"
                         "否则课程会从 band0 重新开始；默认 0）")
    ap.add_argument("--ramp-quality-json", default="",
                    help="可选：离线质量统计 JSON（scripts/quality_monitor.py 输出）。给了就"
                         "优先用它的 survive_t12_ratio / tier_ge4_ratio 做门控指标；"
                         "空=用采集轨迹代理（max_turn>=12 / max_turn>=8）")
    # ---- 势函数奖励塑形（默认关闭，见 docs/REWARD_SHAPING.md）----
    ap.add_argument("--shaping-coef", type=float, default=0.0,
                    help="势函数奖励塑形系数 λ；0=关闭（默认，records/GAE 与旧路径逐位等价）")
    ap.add_argument("--shaping-gamma", type=float, default=None,
                    help="塑形折扣 γ_s（默认空=跟随训练 --gamma；只有与训练 γ 严格相等才满足"
                         "策略不变性；显式不一致会启动期警告并记录累计偏差）")
    ap.add_argument("--shaping-w-str", type=float, default=1.0,
                    help="Φ 的 Σ(atk+hp) 权重（默认 1.0；log_strength 口径下乘 L(Σ)）")
    ap.add_argument("--shaping-w-tier", type=float, default=0.5,
                    help="Φ 的 TIER_BONUS 权重（默认 0.5；log_strength 口径建议 0）")
    ap.add_argument("--shaping-mode", default="sigma", choices=["sigma", "log_strength"],
                    help="塑形强度口径：sigma（默认，原始 Σ）/ log_strength（L(Σ)，与"
                         "沙盒/推理期叶值同曲线；整局望远镜和 = shaping_coef·L(Σ_T)）")
    ap.add_argument("--game-weight-mode", default="none", choices=["none", "adv"],
                    help="per-episode 长强加权：none=关闭（默认，旧路径逐位等价）；"
                         "adv=按(对局长度,对手最强盘面)缩放 advantage（alpha=beta=0.5，均值归一到 1）")
    ap.add_argument("--game-weight-alpha", type=float, default=0.5,
                    help="长度分位的混合权重（默认 0.5）")
    ap.add_argument("--game-weight-beta", type=float, default=0.5,
                    help="对手强度分位的混合权重（默认 0.5）")
    ap.add_argument("--game-weight-floor", type=float, default=0.5,
                    help="原始权重下限（默认 0.5，见 hsbg/eval/metrics.game_weights）")
    ap.add_argument("--game-weight-cap", type=float, default=2.0,
                    help="原始权重上限（默认 2.0）")
    ap.add_argument("--rank-utility-coef", type=float, default=1.0,
                    help="终局名次效用系数（默认 1.0=旧行为）。混合奖励用："
                         "0.3 = 0.7·强度 + 0.3·名次")
    ap.add_argument("--terminal-strength-coef", type=float, default=0.0,
                    help="终局强度奖励系数（默认 0=关闭）：末步额外加 coef·L(Σ_末决策)；"
                         "0.7 = 0.7·强度 + 0.3·名次")
    ap.add_argument("--shaping-tier-bonus", default="0,0,20,60,150,400,900",
                    help="按 tier 直接索引的奖励表（逗号分隔；索引 0=占位，越界按 0）")
    # ---- 等级进度奖励（tier-target，默认关闭，见 docs/TIER_TARGET.md）----
    ap.add_argument("--tier-spread", type=int, default=0, choices=[0, 1],
                    help="1=未达标惩罚均分到该回合全部 decision（默认 0=只在回合首条）")
    ap.add_argument("--tier-target-coef", type=float, default=0.0,
                    help="等级进度奖励系数；0=关闭（默认，records/GAE 与旧路径逐位等价）")
    ap.add_argument("--tier-penalty", type=float, default=0.02,
                    help="某回合 tier 未达目标时该回合第一条 decision 的惩罚（乘 coef；默认 0.02）")
    ap.add_argument("--tier-bonus", type=float, default=0.15,
                    help="首次达标某回合目标时的一次性奖励（乘 coef；默认 0.15）")
    ap.add_argument("--tier-target-table", default="7:4,9:5,12:6",
                    help="目标曲线 turn:tier，逗号分隔（默认 7:4,9:5,12:6）")
    ap.add_argument("--library-p", type=float, default=0.0,
                    help="每回合每个 bot 座位的注入概率（建议 0.3 起）")
    ap.add_argument("--lockstep", type=int, default=0,
                    help="1=lock-step 批量 actor（每 worker 内多局同步推进）")
    ap.add_argument("--fast-act", type=int, default=1,
                    help="1=worker 侧采样（省 245 维 prior 回传）；0=旧路径（A/B 用）")
    ap.add_argument("--amp", default="off", choices=["off", "bf16"],
                    help="PPO 前向/反向精度；bf16 实测 2.03×（loss 侧仍 fp32）")
    ap.add_argument("--compile-train", type=int, default=0, choices=[0, 1, 2],
                    help="训练侧 torch.compile（只 learner 的 fwd+bwd + anchor 参考前向）："
                         "0=关（默认）1=默认模式 2=max-autotune。失败自动回退 eager；"
                         "叶前向/自对弈/评测路径不受影响（docs/TRAINING_COMPILE.md）")
    ap.add_argument("--anchor-amp", type=int, default=0, choices=[0, 1],
                    help="1=anchor 参考前向也用 --amp 的精度（bf16，实测约 1.8×）；"
                         "只影响 KL 正则项参考分布，默认 0=旧行为 fp32")
    ap.add_argument("--pi-coef", type=float, default=0.1)
    # ---- 动作序列辅助任务（默认关闭，见 docs/ACTION_SEQUENCE_AUX.md）----
    ap.add_argument("--seq-coef", type=float, default=0.0,
                    help="动作序列辅助头（该 seat 在本 turn 内动作 multi-hot 的 BCE）权重；"
                         "0=关闭（默认，records→batch→loss 与旧路径逐字节等价）")
    ap.add_argument("--seq-coef-ramp", default="",
                    help='按 decisions 比例的线性 ramp，如 "0.02@0,0.05@0.5"；'
                         "给了 ramp 时本 iteration 的系数由 ramp 决定")
    ap.add_argument("--seq-ramp-total-decisions", type=float, default=0.0,
                    help="ramp 的 100%% 进度对应的累计 decisions（0=用 --stop-at-decisions，"
                         "再缺省 30M）")
    # ---- 真实人类 BC 辅助正则（默认关闭，见 docs/BC_AUX.md）----
    ap.add_argument("--bc-coef", type=float, default=0.0,
                    help="真实人类对局（Firestone）BC 辅助 CE 权重（形态 A）；"
                         "0=关闭（默认，不加载 BC、不采样、loss 与旧路径逐位等价）")
    ap.add_argument("--bc-coef-ramp", default="",
                    help='BC 系数 ramp（与 --seq-coef-ramp 同语法），如 "0.005@0,0.02@0.3"；'
                         "按累计 decisions 求值后写回 bc_coef")
    ap.add_argument("--bc-mmr-min", type=int, default=6000,
                    help="BC 样本 MMR 下限（低于该值丢弃；默认 6000）")
    ap.add_argument("--bc-mmr-boost", type=float, default=1.0,
                    help="MMR 线性增强：1=不加权（默认）；1.5=在 6000..8000 上从 1.0 线性升到 1.5")
    ap.add_argument("--bc-class-weight", default="",
                    help='稀有动作类别权重覆盖，如 "upgrade=4,hero_power=2"；'
                         "在 class-balanced 权重之上再乘。空=现状（默认）")
    ap.add_argument("--bc-samples", default="data/firestone_bc/bc_samples.jsonl.gz",
                    help="BC 样本 JSONL(.gz) 路径（默认仓库 data/firestone_bc/bc_samples.jsonl.gz）")
    ap.add_argument("--bc-batch", type=int, default=128,
                    help="每个 PPO 微批抽取/编码的 BC 样本数（默认 128；固定形状编译）")
    ap.add_argument("--bc-every", type=int, default=1,
                    help="每 N 个 PPO 微批做一次 BC（默认 1=每个微批）；N>1 时该步 "
                         "BC 权重乘 N 保持等效平均权重，跳过步不跑 forward_bc")
    ap.add_argument("--bc-compile", type=int, default=1, choices=[0, 1],
                    help="--compile-train>0 时是否也把 BC 批次单独 torch.compile（默认 1）；"
                         "0=BC 保持 eager（A/B 基线，其余不变）")
    ap.add_argument("--bc-type-weight", type=float, default=1.0,
                    help="分层 BC 的类型级 CE 权重（9 类 log-sum-exp 聚合；默认 1.0）")
    ap.add_argument("--bc-card-weight", type=float, default=0.5,
                    help="分层 BC 的卡牌身份 CE 权重（3983 类 card_head，仅 buy/play；"
                         "默认 0.5；0=不建/不用 card_head）")
    ap.add_argument("--dpo-coef", type=float, default=0.0,
                    help="upgrade 子集 one-sided DPO 系数（0=关闭，默认）；每 "
                         "--dpo-every 个 iteration 把 coef*L_dpo 加进同一次 backward，"
                         "见 docs/DPO_UPGRADE.md")
    ap.add_argument("--dpo-beta", type=float, default=0.1,
                    help="DPO 温度 β（-logsigmoid(β·Δlogp)；默认 0.1）")
    ap.add_argument("--dpo-batch", type=int, default=128,
                    help="每个 DPO 步从 upgrade 池无放回抽样的样本数（默认 128）")
    ap.add_argument("--dpo-every", type=int, default=4,
                    help="DPO 周期，按 **iteration** 计（默认 4=每 4 个 iteration 一次）；"
                         "系数不做周期折算，平均梯度占比 ≈ coef/every")
    ap.add_argument("--dpo-samples", default="data/firestone_bc/bc_samples.jsonl.gz",
                    help="upgrade 样本来源 JSONL(.gz)（只读 action_type==upgrade 的行）；"
                         "默认 data/firestone_bc/bc_samples.jsonl.gz")
    # ---- 场面题（自对弈关键局面 + 人类参考解）与强度辅助头（默认关闭）----
    # 见 docs/RESEARCH_PLAN_V2.md §4.1 与 docs/BOARD_PROBLEMS.md。
    ap.add_argument("--problem-pool", default="data/board_problems/problems.jsonl",
                    help="场面题池（scripts/build_board_problems.py 产出）；"
                         "两个系数都为 0 时不读该文件")
    ap.add_argument("--problem-bc-coef", type=float, default=0.0,
                    help="场面题 soft-label CE 系数（0=关闭，默认）；只在题目状态上算，"
                         "与 BC/DPO 正交。>0 需要 --problem-pool 存在且模型支持 "
                         "forward_problem")
    ap.add_argument("--problem-bc-every", type=int, default=1,
                    help="场面题 CE 周期（按 iteration；默认 1=每次）")
    ap.add_argument("--problem-batch", type=int, default=128,
                    help="每批题目行数（题目 CE 与强度辅助头共用同一批 + 同一次前向）")
    ap.add_argument("--problem-turn-weight", default="",
                    help="场面题 turn 加权（默认空 = 不加权，逐位等价）："
                         "'10:2,12:3,14:4,15:4'；未列出的 turn 权重 1，权重 0 = "
                         "该 turn 的题从池里剔除。非法语法直接报错退出")
    ap.add_argument("--problem-min-strength-delta", type=float, default=0.0,
                    help="场面题强度增量过滤（默认 0 = 不过滤）：只保留 "
                         "label.strength_delta（t+3 log1p 增量）>= 阈值的题")
    ap.add_argument("--strength-aux-coef", type=float, default=0.0,
                    help="强度辅助头系数（0=关闭，默认）：t+3 战团强度增量的 log1p "
                         "回归 + tier+1 二分类，只在有标注（t+3 时存活）的题目上算")
    ap.add_argument("--strength-aux-every", type=int, default=1,
                    help="强度辅助头周期（按 iteration；默认 1=每次）")
    ap.add_argument("--strength-tier-pos-weight", type=float, default=1.0,
                    help="强度辅助头 tier+1 BCE 的正样本权重（默认 1.0）")
    ap.add_argument("--strength-head-init", default="fit", choices=["fit", "random"],
                    help="强度辅助头初始化：fit=在题目池上离线拟合线性头（CV 选 lambda "
                         "的 ridge + logistic，并冻结；推荐，40-60 iter 的小 lr 下随机头"
                         "无法校准）、random=保持 nn.Linear 随机初始化（纯消融）")
    ap.add_argument("--strength-head-ridge", type=float, default=1.0,
                    help="离线拟合的 ridge 强度（乘以样本数；默认 1.0）")
    # ---- 经济（金币）课程（默认关闭 = 逐位等价；见 docs/CURRICULUM_SCALING.md）----
    ap.add_argument("--gold-curriculum", type=int, default=0,
                    help="1=启用经济课程（--curriculum-stage 仍为 none 时按 warmup 处理）；"
                         "默认 0=关闭")
    ap.add_argument("--curriculum-stage", default="none",
                    choices=["none", "warmup", "anneal"],
                    help="none=关闭（默认，逐位等价）；warmup=金币收入 ×mult 在 "
                         "--curriculum-anneal-decisions 内线性降到 1.0；anneal=先保持 "
                         "mult 半个窗口再线性降到 1.0")
    ap.add_argument("--curriculum-gold-mult", type=float, default=1.0,
                    help="金币收入倍数（默认 1.0；warmup 建议 3.0）")
    ap.add_argument("--curriculum-anneal-decisions", type=int, default=10_000_000,
                    help="线性退火窗口（累计 decisions；默认 10M）")
    # ---- 缩放教师 DAgger / 过程价值（默认关闭 = 逐位等价）----
    ap.add_argument("--teacher-bc-coef", type=float, default=0.0,
                    help="在线缩放教师 CE 系数（0=关闭，默认）；采集侧只在 "
                         "gold>=10 且 tier>=4 的决策上产出教师标签")
    ap.add_argument("--process-value-coef", type=float, default=0.0,
                    help="过程价值辅助头系数（0=关闭，默认）：预测 log1p(酒馆永久 buff) / "
                         "log1p(施法数) / log1p(consume 数)")
    ap.add_argument("--entropy-coef", type=float, default=0.005)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--log-every", type=int, default=10)
    ap.add_argument("--workers", type=int, default=1,
                    help=">1 时使用并行采集 + 共享批量叶 server（非 pool 路径）")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--processes", type=int, default=1,
                    help=">1 时用进程级 actor pool（每进程绑定一张 GPU）")
    ap.add_argument("--gpus", default="",
                    help="actor pool 使用的物理 GPU 序号（任意列表，如 1,3,0,4,5；"
                         "不要设 CUDA_VISIBLE_DEVICES）")
    ap.add_argument("--gpu-free-check", type=int, default=1,
                    help="1=启动 actor pool 前用 nvidia-smi 剔除已被占用的 GPU"
                         "（邻居抢占；0=不检查）")
    ap.add_argument("--gpu-free-mib", type=int, default=1024,
                    help="--gpu-free-check 阈值：已用显存 > 该值（MiB）视为被占用")
    ap.add_argument("--threads", type=int, default=16,
                    help="每个 actor 进程内的采集线程数（每轮 games 应 >= processes*threads）")
    # ── records 数据通路（默认 auto/fp16：进程 pool 走 shm + features 半精度存储；
    #    `--ipc-mode disk --records-dtype fp32` = 历史逐位等价路径。见 docs/TRAIN_THROUGHPUT.md）──
    ap.add_argument("--records-dtype", default="fp16", choices=["fp32", "fp16"],
                    help="records 存储精度：fp16（默认）只把 features(=3227 floats, 占 88%% 字节)"
                         "降精度写盘/写 shm，父进程读入后立刻还原 fp32（12 iter 动作流 sha 逐位"
                         "相同）；fp32=历史路径")
    ap.add_argument("--ipc-mode", default="auto", choices=["auto", "disk", "shm"],
                    help="worker→父进程的 records 通路：auto（默认）= 有进程 pool 且 /dev/shm "
                         "可用时走 shm，否则 disk；shm=/dev/shm 环形缓冲 + 父进程零拷贝映射"
                         "（省掉 335-438 MB/iter 写盘+读盘）；disk=npz 落盘再读回（历史路径）")
    ap.add_argument("--ipc-shm-slots", type=int, default=2,
                    help="--ipc-mode shm 时每个 worker 的环形 slot 数（>=2 让父进程读上一轮时"
                         " worker 能写下一轮；容量按 32 MiB 向上取整）")
    ap.add_argument("--collect-sha", type=int, default=0, choices=[0, 1],
                    help="1=把每个 iteration 采集批次的「动作流 sha256」写进 history（actions/"
                         "turns/game_ids/seats 拼接后哈希）；默认 0=不写，字段与旧版一致")
    ap.add_argument("--pipeline", type=int, default=0,
                    help="1=double-buffer：collect(k+1) 与 update(k) 并行（需 --processes>1）")
    ap.add_argument("--pipeline-guard", default="warn", choices=["warn", "abort"],
                    help="流水线的 ratio 守卫触发时：warn 只记录，abort 立即保存并退出")
    ap.add_argument("--keep-versions", type=int, default=3,
                    help="保留几个历史权重文件（流水线用；每个 61 MB）")
    ap.add_argument("--snapshot-every", type=int, default=1,
                    help="每 N 个 iteration 落一次快照（进程 actor 下建议 5）")
    ap.add_argument("--keep-snapshots", type=int, default=3,
                    help="只保留最近 K 个 snapshot 目录（0=不清理）")
    ap.add_argument("--anchor-beta", type=float, default=0.0,
                    help="KL anchor 系数 β（论文 Table 7 = 0.1；0=关闭）")
    ap.add_argument("--anchor-iterations", type=int, default=100,
                    help="β 生效的前 N 个 iteration（论文 300 个中的前 100）")
    ap.add_argument("--anchor-beta-tail", type=float, default=0.0,
                    help="前 N 个 iteration 之后保留的 anchor β（stage-3 建议 0.02；0=旧行为）")
    ap.add_argument("--eval-every-decisions", type=int, default=0,
                    help="每累计 N decisions 做一次 C0 评测（0=关闭）")
    ap.add_argument("--eval-first-decisions", type=int, default=0,
                    help="断点续训用：本进程第一次评测的 decisions 门槛"
                         "（默认 0 = 同 --eval-every-decisions；只影响评测时点）")
    ap.add_argument("--eval-games", type=int, default=512)
    ap.add_argument("--eval-seats", type=int, default=8)
    ap.add_argument("--eval-seed-base", type=int, default=420000)
    ap.add_argument("--eval-async", type=int, default=0,
                    help="1=异步评测：ckpt 交给独立子进程跑 c0_gate，主循环不等待"
                         "（并发上限 1；默认 0=同步阻塞，旧行为）")
    ap.add_argument("--eval-device", default="",
                    help="评测用的 GPU（同步默认跟随 --device；异步默认 cuda:4）")
    ap.add_argument("--eval-drain", type=int, default=0,
                    help="1=训练退出时等待在跑的异步评测完成（默认 0=直接终止，不拖 wall）")
    ap.add_argument("--eval-stop-mean-rank", type=float, default=0.0,
                    help="评测 mean_rank <= 该值时在下一个 iteration 边界停止训练"
                         "（0=关闭；异步/同步共用，结果到达时判定）")
    ap.add_argument("--eval-panel", default="both", choices=["bot", "human", "both"],
                    help="周期评测面板：bot=256/512 局 bot 面板（已饱和）；human=人类战团"
                         "对手面板（新主指标）；both=两个面板各起一个子进程串行排队"
                         "（默认 both；并发上限仍为 1）")
    ap.add_argument("--eval-human-quantile", default="auto",
                    choices=["auto", "p50", "p75", "p90"],
                    help="human 面板的对手强度分位：auto=t<=8 p50 / 9-12 p75 / >=13 p90"
                         "（默认，见 docs/EVAL_PANELS.md）")
    ap.add_argument("--eval-human-boards", default="",
                    help="human 面板使用的人类战团 JSONL（空=默认 "
                         "data/real_library/library_real_degraded.jsonl）")
    ap.add_argument("--eval-human-baseline-bot", type=int, default=0,
                    help="1=human 面板同 seed 再跑 bot 基线（配对 CI；默认 0=只评 learner，"
                         "省一半 wall；TRIGGER/早停只看 bot 面板）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--checkpoint", default="")
    # ── critic（价值/名次头）预热：BC 只训策略 ⇒ critic 头仍是随机初始化，此时 GAE 的
    #    advantage 与真实优势近似无关，PPO 第一个 iteration 就会把策略推歪
    #    （沙盒实测 anchor_kl 首行 0.205、130k 后 Σ 1646→524）。iters>0 时在**第一个
    #    iteration 的 update 之前**只训 critic 头（冻结策略与 trunk，策略漂移由构造为 0）。
    #    默认 0 = 关闭，逐位等价旧路径。
    ap.add_argument("--value-warmup-iters", type=int, default=0,
                    help="critic 预热遍数：只训 rank 头（--value-head-coef>0 时含标量 "
                         "value 头），冻结策略/trunk；0=关闭（默认）")
    ap.add_argument("--value-warmup-lr", type=float, default=1e-3,
                    help="critic 预热的 Adam lr（默认 1e-3；仅 --value-warmup-iters>0 生效）")
    ap.add_argument("--value-warmup-minibatch", type=int, default=1024,
                    help="critic 预热的 minibatch 行数（默认 1024；仅 iters>0 生效）")
    ap.add_argument("--value-warmup-every", type=int, default=0,
                    help="周期性重热 critic 的周期（按 iteration；0=只在第一个 iteration 预热）。"
                         "预热的效果会被后续 PPO 的 trunk 漂移抹掉，长训练建议 50–100 重热一次")
    ap.add_argument("--upgrade-reward", type=float, default=0.0,
                    help="给 **upgrade 动作（action_space_std.A_UPGRADE=3）** 的即时奖励 w"
                         "（默认 0=关闭，逐位等价）。rank-only 下升本收益要 5–8 回合后才兑现，"
                         "在 GAE λ=0.995 下被压没；这个'局部可行'信号直接解决'升本动作没有"
                         "正收益'。实现：加在 reward 上并**重算 GAE**（advantages/returns）")
    ap.add_argument("--win-only-reward", type=float, default=0.0,
                    help="终局**只有第 1 名** +w、其余 0（默认 0=关闭，逐位等价）。"
                         "用于「减弱名次奖励、只奖励夺冠」，通常配 --rank-utility-coef 0")
    ap.add_argument("--strength-reward-coef", type=float, default=0.0,
                    help="每回合 ΔL(Σ) 密集强度奖励系数（默认 0=关闭，逐位等价）："
                         "L=log1p(Σ)/log1p(30000)，回合末决策加 c×(L_t−L_{t−1})")
    # ── 复利结构奖励（金卡/高星/放大器/引擎卡/存活；全部默认 0 = 逐位等价）──
    ap.add_argument("--golden-reward", type=float, default=0.0,
                    help="金卡数量密集增量奖励（board+hand 里 '_G' 卡，默认 0=关闭）")
    ap.add_argument("--golden-t5-reward", type=float, default=0.0,
                    help="金卡且 tier>=5 的密集增量奖励（默认 0=关闭）")
    ap.add_argument("--amp-board-reward", type=float, default=0.0,
                    help="放大器家族（Titus/Drakkari/Gatekeeper）在场数量增量（默认 0=关闭）")
    ap.add_argument("--engine-board-reward", type=float, default=0.0,
                    help="引擎卡（BG36_762/BG28_633/BG36_704/BG_LOE_077）在场数量增量（默认 0=关闭）")
    ap.add_argument("--survive-t12-reward", type=float, default=0.0,
                    help="活到 t12 的终局奖励（episode 末回合 >=12；默认 0=关闭）")
    ap.add_argument("--t5plus-stat-reward", type=float, default=0.0,
                    help="终局 (tier>=5 随从身材 / 全体身材) × W（默认 0=关闭）；"
                         "tier 取自 obs 的 tier/6 编码")
    ap.add_argument("--tier-timing-reward", type=float, default=0.0,
                    help="升星时点奖励（默认 0=关闭）：t<=10 首次到 tier>=5、t<=12 首次到 "
                         "tier>=6 各给 W×折扣（折扣 = max(0.2, 1-(turn-1)/15)）")
    ap.add_argument("--cheap-buy-penalty", type=float, default=0.0,
                    help="便宜牌惩罚（默认 0=关闭）：buy 一个 tier<=3 随从扣 P")
    ap.add_argument("--t5plus-buff-reward", type=float, default=0.0,
                    help="终局 tier>=5 随从的永久 buff 量奖励（默认 0=关闭）："
                         "Σ(atk+hp − 卡面基础) 归一化 (/200, clamp 3) 后 × W")
    ap.add_argument("--tier-mix-reward", type=float, default=0.0,
                    help="终局 tier>=5 随从占 7 槽位比例 × W（默认 0=关闭，直接改盘面构成）")
    ap.add_argument("--lowtier-stat-penalty", type=float, default=0.0,
                    help="终局 tier<=3 随从身材占比 × P 扣分（默认 0=关闭，镜像项）")
    ap.add_argument("--gold-bonus-turn", default="",
                    help="指定回合金币加成，如 \"5:1,7:1,9:3\"（默认空=逐位等价）")
    ap.add_argument("--tier-upgrade-discount-scope", default="all",
                    help="折扣范围：all（默认）或 tier5（只降「升到 tier5」）")
    ap.add_argument("--tier-upgrade-discount", type=int, default=0,
                    help="A/B：所有升本费用再减 N 金（默认 0；经 HSBG_TIER_UPGRADE_DISCOUNT 传给引擎）")
    ap.add_argument("--late-growth-coef", type=float, default=0.0,
                    help="后段课程：log1p(Σ15)−log1p(Σ8) × coef（默认 0=关）")
    ap.add_argument("--churn-reward", type=float, default=0.0,
                    help="s35 周转：每卖一张 +w、每次刷新 +0.667w（默认 0=关）")
    ap.add_argument("--hightier-buy-reward", type=float, default=0.0,
                    help="s35 高 tier 买牌：t4 +0.5w / t5 +w / t6 +1.5w（默认 0=关）")
    ap.add_argument("--early-upgrade-reward", type=float, default=0.0,
                    help="s36 早升：t∈{2,3,4,5} 发生 upgrade 时 +w（默认 0=关）")
    ap.add_argument("--collect-chain-ids", default="",
                    help="s49：伴生卡 id 列表（逗号分隔；空=默认四卡）")
    ap.add_argument("--collect-reroll-bias-t8t9", type=float, default=0.0,
                    help="s49：t8-9 reroll 动作偏置（默认 0=关）")
    ap.add_argument("--collect-chain-buy-bias", type=float, default=0.0,
                    help="s42：采集期商店出现链四卡时对 buy 位 +该偏置（默认 0=关）")
    ap.add_argument("--chain-reward", type=float, default=0.0,
                    help="s41 链定向：盘面四卡（塔蕾苟萨/诗人/奥术师/融合怪）每张 +w/回合")
    ap.add_argument("--scaling-value-reward", type=float, default=0.0,
                    help="s50：0.3·Δp(Σ15>=3.5k) 逐回合密集奖励（默认 0=关）")
    ap.add_argument("--scaling-value-model", default="data/scaling_value/logit.npz",
                    help="logistic 潜力模型路径")
    ap.add_argument("--final-3500-reward", type=float, default=0.0,
                    help="s49：终局 Σ>=3,500 时 +w（普通成功档）")
    ap.add_argument("--final-20k-reward", type=float, default=0.0,
                    help="s46：终局 Σ≥20k 时 +w（到达可爆档）")
    ap.add_argument("--roll-bonus-t8t9", type=float, default=0.0,
                    help="s49：t8-9 本回合已 roll>=2 后，每次再 roll +w")
    ap.add_argument("--t9-chain-target-reward", type=float, default=0.0,
                    help="s47：t9 时 tier>=4 且盘面有塔蕾/诗人/奥术师 任一 → +w")
    ap.add_argument("--chain-early-reward", type=float, default=0.0,
                    help="s46：t<=10 盘面出现塔蕾/诗人/奥术师任一 +w/回合")
    ap.add_argument("--late-rel-growth-coef", type=float, default=0.0,
                    help="s44：末决策 0.5·log1p(Σ_end/Σ_start−1)（相对起点增长）")
    ap.add_argument("--chain-any-reward", type=float, default=0.0,
                    help="s44：每回合盘面出现任一链卡 +w")
    ap.add_argument("--strength-from-turn", type=float, default=0.0,
                    help="strength 奖励只在这些回合之后生效（默认 0=全程）")
    ap.add_argument("--chain2-reward", type=float, default=0.0,
                    help="s43：塔蕾苟萨 + 任意其他链卡 1 张 → +w/回合（中间目标）")
    ap.add_argument("--chain-complete-bonus", type=float, default=0.5,
                    help="s41：四卡齐全额外 +bonus/回合（默认 0.5）")
    ap.add_argument("--retain-growth-coef", type=float, default=0.0,
                    help="s41：每回合 0.3·log1p(max(0,Σ_t−Σ_{t−1})) 保留型成长")
    ap.add_argument("--tier-early-reward", type=float, default=0.0,
                    help="s39：t<=9 到达 tier4/tier5 各 +w（一次性、非门控；默认 0=关）")
    ap.add_argument("--churn-pair-reward", type=float, default=0.0,
                    help="s37 卖→买配对：卖出后 2 回合内买进随从时 +w（默认 0=关）")
    ap.add_argument("--roll-pair-reward", type=float, default=0.0,
                    help="s37 刷→买配对：刷新后 1 回合内买进随从时 +w（默认 0=关）")
    ap.add_argument("--churn-sell-cap", type=float, default=12.0,
                    help="卖牌每局上限（>cap 不给分；1-8 全额、8-cap 半额）")
    ap.add_argument("--churn-roll-cap", type=float, default=8.0,
                    help="刷新每局上限（1-4 全额、4-8 半额、>cap 0）")
    ap.add_argument("--hero-power-reward", type=float, default=0.0,
                    help="s35 英雄技能：每次 +w（默认 0=关）")
    ap.add_argument("--late-log-ratio-coef", type=float, default=0.0,
                    help="后段课程：coef·(log1p(Σ15) − log1p(ratio·Σ8))（默认 0）")
    ap.add_argument("--late-alive-bonus", type=float, default=0.0,
                    help="后段课程：活到 t15 给 +bonus（默认 0）")
    ap.add_argument("--late-death-penalty", type=float, default=0.0,
                    help="后段课程：t15 前死亡给 −penalty（默认 0）")
    ap.add_argument("--late-shadow-ratio", type=float, default=3.15,
                    help="脚本影子比率（S 臂 t15/t8 中位，默认 3.15）")
    ap.add_argument("--late-shadow-coef", type=float, default=0.0,
                    help="后段课程：shadow·(Σ15 − 283)（默认 0=关）")
    ap.add_argument("--save-up-reward", type=float, default=0.0,
                    help="s29 攒钱纪律：t7/t8/t9 回合末金币>=8 时 +w（默认 0=关）")
    ap.add_argument("--t1s-coef", type=float, default=0.0,
                    help="T1s 密集 shaping：每回合 tier>=curve 0.30 + 金币>=3 0.10 + "
                         "种族收敛 0.10 + t>=10 存活 0.20（默认 0=关）")
    ap.add_argument("--t1p-coef", type=float, default=0.0,
                    help="T1' 里程碑：t8 tier>=4 / t9 tier>=5 / t7 Σ>=200 / t9 Σ>=400 / "
                         "death>=12 / t9 种族<=3，二值 +1/-1（权重 .4/.3/.2/.1；默认 0=关）")
    ap.add_argument("--comp-fit-coef", type=float, default=0.0,
                    help="T1：t1-9 每回合 Δcomp_fit × c（默认 0=关闭；comp_fit=对 26 套取 max）")
    ap.add_argument("--comp-fit-t9-bonus", type=float, default=0.0,
                    help="T1：t9（或末回合）终局 comp_fit × bonus（默认 0=关闭）")
    ap.add_argument("--comp-trinket-coef", "--trinket-fit-reward", dest="comp_trinket_coef",
                    type=float, default=0.0,
                    help="饰品契合：t6/t9 trinket 选择命中 best-fit 套关键饰品 × w（默认 0=关闭）")
    # ── 复利结构选牌先验（**collect 侧**，纯 obs；默认 0 = 不构造对象 ⇒ 逐位等价）──
    ap.add_argument("--collect-discover-bias", type=float, default=0.0,
                    help="训练采集侧 Discover 先验：三连奖励 3 选 1 里含放大器/引擎卡时，"
                         "给对应 choose 位加该常数（默认 0=关闭，逐位等价）")
    ap.add_argument("--collect-triple-bias", type=float, default=0.0,
                    help="训练采集侧三连先验：能凑三连的 buy 位 +2W、能凑对子 +W（默认 0=关闭）")
    ap.add_argument("--record-logp-mu", type=int, default=0,
                    help="1=采集侧记录 logp_mu/logp_pi（配合 --collect-*-bias）：PPO ratio 分母"
                         "用行为 μ(a)、KL/approx_kl 口径用无偏 π(a)；默认 0=不写（逐位等价）")
    # ── 复利结构**辅助 BC**（推荐路径：行为策略无偏、把结构选择学进权重）────────
    ap.add_argument("--upgrade-curve-bc-turns", default="2,5,7,9",
                    help="upgrade BC 生效回合（逗号分隔；默认 2,5,7,9；s28c 用 2,5,7）")
    ap.add_argument("--upgrade-curve-bc-guard-ratio", type=float, default=-1.0,
                    help="upgrade BC 单独 guard ratio（<0=沿用 --bc-guard-ratio；0=不走 guard 固定系数）")
    ap.add_argument("--upgrade-curve-bc-coef", type=float, default=0.0,
                    help="升级曲线辅助 BC（默认 0=关）：t∈{2,5,7,9} 且 tier<曲线且金币够时，"
                         "对 upgrade(动作3) 加辅助 CE（自适应 guard 与 discover/triple 相同）")
    ap.add_argument("--discover-bc-coef", type=float, default=0.0,
                    help="Discover 辅助交叉熵系数（默认 0=关闭）：选项含放大器/引擎卡时，"
                         "把这些 choose 位当教师（多选项 uniform 加权）")
    ap.add_argument("--triple-bc-coef", type=float, default=0.0,
                    help="三连辅助交叉熵系数（默认 0=关闭）：能凑三连的 buy 位权重 2×、对子 1×")
    ap.add_argument("--bc-ce-norm", type=int, default=1, choices=[0, 1],
                    help="辅助 BC 的 CE 归一化（减掉均匀基线 log k；默认 1=开）")
    ap.add_argument("--bc-warmup-decisions", type=float, default=0.0,
                    help="辅助 BC 系数的线性 warmup 决策数（默认 0=不 warmup，恒定系数）")
    ap.add_argument("--bc-guard-ratio", type=float, default=0.0,
                    help=">0 时启用 guard：若 coef*CE > ratio*policy_loss 则把系数减半（默认 0=关）")
    # ── 动态课程（默认 0 = 关闭，逐位等价）───────────────────────────────────
    # 规则（Lead 定）：起点 start 席 × p；**每当真实强度口径（5 席 p0.9 面板的 t15 Σ p50）
    # 比上一次评测提升 >= threshold，就回加一席**（上限 max）；回加后若比上一次评测
    # 回退 > threshold，则退回一档并保持 hold-decisions。训练剂量只作参考，主判据用真实口径。
    ap.add_argument("--dyn-curriculum", type=int, default=0, choices=[0, 1],
                    help="1=启用动态对手强度课程（按真实强度口径 t15 Σ 自动加/减席）")
    ap.add_argument("--dyn-start-seats", type=int, default=2,
                    help="动态课程起始人类战团席数（默认 2）")
    ap.add_argument("--dyn-max-seats", type=int, default=5,
                    help="席数上限（默认 5）")
    ap.add_argument("--dyn-p", type=float, default=0.75,
                    help="动态课程使用的注入概率 p（默认 0.75）")
    ap.add_argument("--dyn-threshold", type=float, default=0.10,
                    help="加/减席的判定阈值（相对上一次评测的 t15 Σ 变化；默认 0.10=10%%）")
    ap.add_argument("--dyn-hold-decisions", type=float, default=10000000.0,
                    help="减席后至少保持多少 decisions 再考虑加席（默认 10M）")
    ap.add_argument("--dyn-quality-games", type=int, default=96,
                    help="真实强度口径面板局数（5 席 p0.9，默认 96）")
    ap.add_argument("--trainer-state", default="")
    ap.add_argument("--out", default="runs/az_entity_sync")
    args = ap.parse_args()
    _gb = str(getattr(args, "gold_bonus_turn", "") or "").strip()
    if _gb:
        os.environ["HSBG_GOLD_BONUS_TURNS"] = _gb
    if int(getattr(args, "tier_upgrade_discount", 0) or 0) > 0:
        os.environ["HSBG_TIER_UPGRADE_DISCOUNT"] = str(int(args.tier_upgrade_discount))
        _scope = str(getattr(args, "tier_upgrade_discount_scope", "all") or "all")
        if _scope != "all":
            os.environ["HSBG_TIER_UPGRADE_DISCOUNT_SCOPE"] = _scope
    args.out = os.path.abspath(args.out)
    # ── 脚本席（固定阵容脚本作为 bot 席位）──────────────────────────────────
    # 语义：只改对手分布（seat 1..N 由 CompPolicy hybrid 驱动），不改奖励/PPO 数学。
    _script_seats = int(getattr(args, "script_seats", 0) or 0)
    if _script_seats:
        if not (0 <= _script_seats <= 3):
            print("[error] --script-seats 必须在 0..3（0=关闭）", file=sys.stderr)
            return 2
        if not int(args.lockstep):
            print("[error] --script-seats>0 需要 --lockstep 1"
                  "（脚本席只在 lockstep 采集路径生效）", file=sys.stderr)
            return 2
        if str(args.opponent) not in ("bot", "weak"):
            print(f"[error] --script-seats>0 需要 --opponent bot|weak，"
                  f"收到 {args.opponent!r}", file=sys.stderr)
            return 2
        if str(args.frozen_opponent).strip():
            print("[error] --script-seats 与 --frozen-opponent 不能同时给"
                  "（二者都占用冻结席位）", file=sys.stderr)
            return 2
        try:
            from hsbg.az.train.comp_offline_policy import resolve_comp_keys
            _script_keys = resolve_comp_keys(str(args.script_comps), _script_seats,
                                             int(args.seed))
        except Exception as exc:  # noqa: BLE001 - 启动期参数错误，直接报错退出
            print(f"[error] --script-comps 非法: {exc}", file=sys.stderr)
            return 2
        if int(getattr(args, "frozen_seats", 0) or 0) not in (0, _script_seats):
            print(f"[warn] --frozen-seats={args.frozen_seats} 被 --script-seats="
                  f"{_script_seats} 覆盖", flush=True)
        args.frozen_seats = _script_seats
        args.frozen_opponent = "comp:" + (str(args.script_comps).strip() or "auto")
        print(f"[script-seats] seats={_script_seats} comps={_script_keys} "
              f"frozen_opponent={args.frozen_opponent!r}（hybrid：阵容动作优先、"
              f"其余引擎 bot；不改变奖励）", flush=True)
    elif str(getattr(args, "script_comps", "auto") or "auto").strip().lower() != "auto":
        print("[warn] --script-comps 只在 --script-seats>0 时生效", flush=True)
    # 经济课程：gold_curriculum=1 且 stage=none 时按 warmup 处理；非法倍数/窗口启动期报错
    if int(args.gold_curriculum) and str(args.curriculum_stage) == "none":
        args.curriculum_stage = "warmup"
    try:
        _curr_cfg = curriculum_schedule(
            stage=str(args.curriculum_stage),
            mult=float(args.curriculum_gold_mult),
            anneal_decisions=float(args.curriculum_anneal_decisions))
    except ValueError as exc:
        print(f"[error] 经济课程参数非法: {exc}", file=sys.stderr)
        return 2
    if (_curr_cfg["curriculum_stage"] != "none"
            and _curr_cfg["curriculum_gold_mult"] == 1.0):
        print("[warn] 经济课程已开启但 --curriculum-gold-mult=1.0：金币不变（等价关闭）",
              flush=True)
    if (float(args.teacher_bc_coef) > 0.0
            or float(args.process_value_coef) > 0.0) and not int(args.lockstep):
        print("[warn] 教师 DAgger / 过程价值标签只在 --lockstep 1 采集路径产出；"
              "本次非 lockstep 将得到空标签（对应损失为 0）", flush=True)
    if float(args.library_p) > 0.0:
        print("[error] --library-p（v1 单座位注入）未通过终审，已禁用；"
              "请用 --trajectory-pool/--trajectory-p", file=sys.stderr)
        return 2
    # 回合末场面快照镜像（默认关闭；--mirror-p 0 且无 ramp 时完全零影响）
    _mirror_ramp = str(args.mirror_p_ramp).strip()
    if _mirror_ramp:
        try:
            ramp_p(0, _mirror_ramp)      # 提前校验格式，避免训练中途才报错
        except ValueError as exc:
            print(f"[error] --mirror-p-ramp 格式错误: {exc}", file=sys.stderr)
            return 2
    if (float(args.mirror_p) > 0.0 or _mirror_ramp) and int(args.mirror_seats) <= 0:
        print("[error] --mirror-p>0/--mirror-p-ramp 需要 --mirror-seats>0"
              "（给随机/固定座位注入）", file=sys.stderr)
        return 2
    if (float(args.mirror_p) > 0.0 or _mirror_ramp) and not int(args.lockstep):
        print("[warn] 回合末快照镜像只在 --lockstep 1 路径生效", flush=True)
    if str(args.mirror_snaps) and not os.path.isdir(str(args.mirror_snaps)):
        print(f"[warn] --mirror-snaps 目录不存在: {args.mirror_snaps}", flush=True)
    # ---- 对手强度课程（human-board 席数/概率/分位按累计 decisions 爬坡）----
    # 默认（spec 全空 + adaptive=0）是恒等映射：下面所有分支都走旧路径。
    try:
        board_ramp = BoardRampController(
            str(args.human_board_ramp), mode=str(args.ramp_mode),
            quantile_spec=str(args.human_board_quantile_ramp),
            adaptive=bool(int(args.ramp_adaptive)),
            base_seats=int(args.human_board_seats),
            base_p=float(args.human_board_p),
            base_sample=str(args.human_board_sample),
            window=int(args.ramp_window),
            survive_threshold=float(args.ramp_survive_threshold),
            tier4_threshold=float(args.ramp_tier4_threshold),
            max_forced_per_game=float(args.ramp_max_forced_per_game),
            delay_decisions=args.ramp_delay_decisions,
            start_decisions=args.ramp_start_decisions)
    except ValueError as exc:
        print(f"[error] 对手强度课程参数非法: {exc}", file=sys.stderr)
        return 2
    if board_ramp.enabled:
        _desc = board_ramp.describe()
        print(f"[ramp] 对手强度课程开启: mode={_desc['mode']} "
              f"bands={_desc['bands']} spec={_desc['spec']!r} "
              f"quantile={_desc['quantile_spec']!r} "
              f"adaptive={int(_desc['adaptive'])} window={_desc['window']} "
              f"start_decisions={_desc['start_decisions']}", flush=True)
        if int(args.ramp_adaptive):
            print(f"[ramp] 门控: survive_t12>={float(args.ramp_survive_threshold):g} 且 "
                  f"tier4>={float(args.ramp_tier4_threshold):g} 且 "
                  f"forced/game<={float(args.ramp_max_forced_per_game):g} 才升档；"
                  f"否则推迟 {int(_desc['delay_decisions'])} decisions", flush=True)
        for _i, (_d, _s, _p) in enumerate(_desc["points"]):
            print(f"[ramp] band {_i}: decisions>={_d} seats={_s} p={_p:g}",
                  flush=True)
        for _i, (_d, _q) in enumerate(_desc["quantile_points"]):
            print(f"[ramp] quantile band {_i}: decisions>={_d} sample={_q}",
                  flush=True)
        if not int(args.lockstep):
            print("[warn] 对手强度课程依赖人类战团注入，只在 --lockstep 1 路径生效",
                  flush=True)
        if int(args.ramp_adaptive) and str(args.ramp_quality_json):
            print(f"[ramp] 自适应门控指标优先读质量统计: {args.ramp_quality_json}",
                  flush=True)
        elif int(args.ramp_adaptive):
            print("[ramp] 自适应门控指标：采集轨迹代理（max_turn>=12 / max_turn>=8）；"
                  "没有真实 tier 观测，建议用 --ramp-quality-json 接 quality_monitor",
                  flush=True)
        if float(_desc["start_decisions"]) > 0.0:
            print(f"[ramp] 起始 decisions 偏移 = {_desc['start_decisions']}"
                  "（续训请传上一次的累计值）", flush=True)
    # 人类战团（board-only）注入（默认关闭；p 全 0 时完全零影响）
    if board_ramp.max_p() > 0.0:
        if int(args.human_board_seats) <= 0 and not board_ramp.enabled:
            print("[error] --human-board-p>0 需要 --human-board-seats>0", file=sys.stderr)
            return 2
        if not str(args.human_boards):
            args.human_boards = "data/real_library/library_real_degraded.jsonl"
        if not os.path.isfile(str(args.human_boards)):
            print(f"[error] --human-boards 文件不存在: {args.human_boards}", file=sys.stderr)
            return 2
        _fid = str(getattr(args, "human_board_fidelity", "board") or "board")
        if _fid != "board":
            _need_rows = 0
            try:
                _need_rows = sum(1 for _ in open(args.human_boards, encoding="utf-8")
                                 if '"board_detail"' in _)
            except BaseException:  # noqa: BLE001
                _need_rows = 0
            if _need_rows <= 0:
                print(f"[error] --human-board-fidelity={_fid} 需要准完整库"
                      "（含 board_detail 的行）；当前文件没有："
                      f"{args.human_boards}\n"
                      "  先跑 PYTHONPATH=rust/python:. python "
                      "scripts/build_fidelity_library.py --stats", file=sys.stderr)
                return 2
            print(f"[info] 人类战团保真度 = {_fid}（准完整行 {_need_rows}；"
                  "注入走 apply_turn_snapshots + ended_turn 复位）", flush=True)
        if not int(args.lockstep):
            print("[warn] 人类战团注入只在 --lockstep 1 路径生效", flush=True)
        if int(args.processes) <= 1:
            print("[warn] 人类战团注入只在 --processes>1 的进程池 worker 内生效；"
                  "--processes 1 的逐局采集不会注入（对手强度课程因此无效）", flush=True)
        elif (float(args.mirror_p) > 0.0 or _mirror_ramp):
            print("[info] 人类战团 + 回合末快照镜像同时开启："
                  "同座位同回合镜像快照优先（记 human_board_skipped_by_mirror）", flush=True)
    elif str(args.human_boards):
        print("[warn] --human-boards 已设置但 --human-board-p=0：本次不注入", flush=True)
    # ── 搜索作为行为策略 μ=(1−ε)π+ε·π_search（默认 eps=0 = 完全关闭）──────────
    if float(args.behavior_mix_eps) > 0.0:
        if not (0.0 <= float(args.behavior_mix_eps) < 1.0):
            print("[error] --behavior-mix-eps 必须在 [0,1)", file=sys.stderr)
            return 2
        if not int(args.lockstep) or int(args.processes) <= 1:
            print("[error] --behavior-mix-eps>0 需要 --lockstep 1 且 --processes>1"
                  "（混合行为策略只在进程池的 lockstep 采集器里生效）",
                  file=sys.stderr)
            return 2
        if str(args.behavior) != "net":
            print("[error] --behavior-mix-eps>0 需要 --behavior net"
                  "（μ 的网络分量是 π；mcts/mixed 会再叠一层 MCTS 混合）",
                  file=sys.stderr)
            return 2
        print(f"[behavior-mix] 开启：eps={float(args.behavior_mix_eps):g} "
              f"when={args.behavior_mix_when} "
              f"max_per_turn={int(args.behavior_mix_max_per_turn)} "
              f"topk={int(args.behavior_mix_topk)} turns={int(args.behavior_mix_turns)} "
              f"max_ms={float(args.behavior_mix_max_ms):g}；"
              "records 写 logp_mu/logp_pi，PPO ratio 分母 = logp_mu", flush=True)
    if str(args.behavior_mix_report):
        _bm_dir = os.path.dirname(os.path.abspath(str(args.behavior_mix_report)))
        if _bm_dir:
            os.makedirs(_bm_dir, exist_ok=True)
        print(f"[behavior-mix] 逐 iteration 统计 -> {args.behavior_mix_report}",
              flush=True)

    # ---- 势函数奖励塑形（默认关闭；coef=0 时零影响）----
    if float(args.shaping_coef) < 0.0:
        print("[error] --shaping-coef 必须 >= 0", file=sys.stderr)
        return 2
    try:
        parse_tier_bonus(str(args.shaping_tier_bonus))   # 启动期 fail-fast
    except ValueError as exc:
        print(f"[error] --shaping-tier-bonus 非法: {exc}", file=sys.stderr)
        return 2
    # 折扣范围与一致性：γ_s 缺省 = 跟随训练 γ；显式不一致必须警告（不静默）
    if not (0.0 <= float(args.gamma) <= 1.0):
        print("[error] --gamma 必须在 [0, 1] 内", file=sys.stderr)
        return 2
    if args.shaping_gamma is not None and not (0.0 <= float(args.shaping_gamma) <= 1.0):
        print("[error] --shaping-gamma 必须在 [0, 1] 内", file=sys.stderr)
        return 2
    shape_gamma = (float(args.gamma) if args.shaping_gamma is None
                   else float(args.shaping_gamma))
    shape_aligned = (shape_gamma == float(args.gamma))
    if float(args.shaping_coef) > 0.0:
        if str(args.opponent) == "self":
            print("[error] 奖励塑形只支持 --opponent bot|weak（单 learner seat）",
                  file=sys.stderr)
            return 2
        if int(args.rust_collector):
            print("[error] Rust 采集器暂不支持奖励塑形；请设 --shaping-coef 0 "
                  "或 --rust-collector 0", file=sys.stderr)
            return 2
        print(f"[shaping] 势函数奖励塑形开启: coef={float(args.shaping_coef):g} "
              f"γ_s={shape_gamma:g}（训练 γ={float(args.gamma):g}，"
              f"{'对齐' if shape_aligned else '不一致'}） "
              f"Φ={float(args.shaping_w_str):g}*Σ(atk+hp)+"
              f"{float(args.shaping_w_tier):g}*tier_bonus "
              f"tier_bonus={args.shaping_tier_bonus}", flush=True)
        if not shape_aligned:
            print("[shaping][warn] " + shaping_gamma_warning(
                float(args.shaping_coef), shape_gamma, float(args.gamma)),
                file=sys.stderr, flush=True)
        if not int(args.lockstep):
            print("[info] 非 lockstep 路径：塑形在逐局采集（collect_ppo_records_parallel）"
                  "内生效", flush=True)

    # ---- records 数据通路（默认 auto/fp16；`--ipc-mode disk --records-dtype fp32` = 历史路径。
    #      见 docs/TRAIN_THROUGHPUT.md：shm 省掉 335-438 MB/iter 写盘+读盘，fp16 再减半字节）----
    _ipc_requested = str(args.ipc_mode).strip().lower()
    if _ipc_requested == "auto":
        args.ipc_mode = ("shm" if (int(args.processes) >= 2 and os.path.isdir("/dev/shm"))
                         else "disk")
    if str(args.ipc_mode) == "shm":
        if int(args.processes) < 2:
            print("[error] --ipc-mode shm 需要 --processes >= 2（只有进程 pool 才走 IPC）",
                  file=sys.stderr)
            return 2
        if not os.path.isdir("/dev/shm"):
            print("[error] --ipc-mode shm 需要 /dev/shm（本机不存在）", file=sys.stderr)
            return 2
        print(f"[ipc] shm 环形缓冲: slots={int(args.ipc_shm_slots)}（每 slot 按 32 MiB 取整），"
              f"records_dtype={args.records_dtype}", flush=True)
    else:
        print(f"[ipc] disk 通路（ipc_mode={_ipc_requested}->disk），"
              f"records_dtype={args.records_dtype}", flush=True)

    # ---- 换位去抖守卫（默认关闭；--move-guard 0 时零影响）----
    if int(args.move_cap) < 0:
        print("[error] --move-cap 必须 >= 0", file=sys.stderr)
        return 2
    if int(args.move_repeat_limit) < 1:
        print("[error] --move-repeat-limit 必须 >= 1", file=sys.stderr)
        return 2
    if int(args.move_guard):
        if int(args.rust_collector):
            print("[error] Rust 采集器不支持换位守卫（它不经 PPOSelfPlayPolicy 采样）；"
                  "请设 --move-guard 0 或 --rust-collector 0", file=sys.stderr)
            return 2
        print(f"[move-guard] 换位去抖守卫开启: cap={int(args.move_cap)} "
              f"repeat_limit={int(args.move_repeat_limit)} "
              f"（逆换位 + 同动作超限 + 每回合 cap，见 docs/MOVE_GUARD.md）",
              flush=True)
        if not int(args.lockstep):
            print("[info] 非 lockstep 路径：守卫在逐局采集（collect_ppo_records_parallel）"
                  "内同样生效", flush=True)

    # ---- 等级进度奖励（tier-target，默认关闭；coef=0 时零影响）----
    if float(args.tier_target_coef) < 0.0:
        print("[error] --tier-target-coef 必须 >= 0", file=sys.stderr)
        return 2
    if float(args.tier_penalty) < 0.0 or float(args.tier_bonus) < 0.0:
        print("[error] --tier-penalty / --tier-bonus 必须 >= 0", file=sys.stderr)
        return 2
    try:
        parse_tier_target_table(str(args.tier_target_table))
    except ValueError as exc:
        print(f"[error] --tier-target-table 非法: {exc}", file=sys.stderr)
        return 2
    if float(args.tier_target_coef) > 0.0:
        if str(args.opponent) == "self":
            print("[error] 等级进度奖励只支持 --opponent bot|weak（单 learner seat）",
                  file=sys.stderr)
            return 2
        if int(args.rust_collector):
            print("[error] Rust 采集器暂不支持等级进度奖励；请设 --tier-target-coef 0 "
                  "或 --rust-collector 0", file=sys.stderr)
            return 2
        print(f"[tier-target] 等级进度奖励开启: coef={float(args.tier_target_coef):g} "
              f"penalty={float(args.tier_penalty):g} bonus={float(args.tier_bonus):g} "
              f"table={args.tier_target_table} spread={int(args.tier_spread)}",
              flush=True)
        if not int(args.lockstep):
            print("[info] 非 lockstep 路径：等级进度奖励在逐局采集"
                  "（collect_ppo_records_parallel / collect_ppo_batch）内生效", flush=True)

    # ---- 动作序列辅助任务：系数 ramp（默认关闭 = 零影响）----
    try:
        seq_schedule = SeqCoefSchedule.from_spec(
            base_coef=float(args.seq_coef), spec=str(args.seq_coef_ramp),
            total_decisions=(float(args.seq_ramp_total_decisions) if
                             float(args.seq_ramp_total_decisions) > 0 else
                             (float(args.stop_at_decisions) if
                              float(args.stop_at_decisions) > 0 else 3.0e7)))
    except ValueError as exc:
        print(f"[error] --seq-coef-ramp 非法: {exc}", file=sys.stderr)
        return 2
    seq_enabled = bool(seq_schedule.enabled)
    if seq_enabled:
        print(f"[seq] 动作序列辅助任务开启: {json.dumps(seq_schedule.describe(), ensure_ascii=False)}"
              f" coef(dec=0)={seq_schedule.coef(0):.4f}", flush=True)
    elif float(args.seq_coef) < 0.0:
        print("[error] --seq-coef 必须 >= 0", file=sys.stderr)
        return 2

    # ---- 注入（镜像快照 / 人类战团）：先校验引擎构建是否带注入 API ----
    # 典型事故：conda env 里 `hsbg_engine` 指向旧 clone（/tmp/...），训练命令又没设
    # PYTHONPATH → worker 每回合 AttributeError，注入全部静默失败。这里在父进程
    # 启动前 fail-fast，并给出修复命令。
    _inject_wanted = bool(int(args.lockstep)) and (
        (bool(args.mirror_snaps) and int(args.mirror_seats) > 0
         and (float(args.mirror_p) > 0.0 or str(args.mirror_p_ramp).strip()))
        or (bool(args.human_boards) and int(args.human_board_seats) > 0
            and float(args.human_board_p) > 0.0))
    if _inject_wanted:
        try:
            import hsbg_engine as _engine
            _need = []
            if bool(args.mirror_snaps) and int(args.mirror_seats) > 0 and \
                    (float(args.mirror_p) > 0.0 or str(args.mirror_p_ramp).strip()):
                _need.append("apply_turn_snapshots")
            if bool(args.human_boards) and int(args.human_board_seats) > 0 and \
                    float(args.human_board_p) > 0.0:
                _need.append("inject_board")
            _missing = [n for n in _need if not hasattr(_engine.Game, n)]
        except Exception as exc:  # noqa: BLE001
            print(f"[error] 无法 import hsbg_engine：{exc!r}", file=sys.stderr)
            return 2
        if _missing:
            print("[error] 当前 hsbg_engine 缺少注入 API "
                  f"{_missing}（import 自 {getattr(_engine, '__file__', '?')}）。"
                  "这是旧构建，注入会 100% 静默失败。请设置 "
                  "`PYTHONPATH=rust/python:.` 或 `pip install -e rust/python` 后重跑。",
                  file=sys.stderr)
            return 2

    # ---- 真实人类 BC 辅助正则：系数 ramp + 预加载池（默认关闭 = 零影响）----
    if float(args.bc_coef) < 0.0:
        print("[error] --bc-coef 必须 >= 0", file=sys.stderr)
        return 2
    if int(args.bc_batch) <= 0 or int(args.bc_every) <= 0:
        print("[error] --bc-batch 必须 > 0 且 --bc-every 必须 >= 1", file=sys.stderr)
        return 2
    if float(args.bc_type_weight) < 0.0 or float(args.bc_card_weight) < 0.0:
        print("[error] --bc-type-weight/--bc-card-weight 必须 >= 0", file=sys.stderr)
        return 2
    # ---- upgrade 子集 DPO（默认关闭 = 零影响）：系数/β/批量/周期校验 ----
    if not np.isfinite(float(args.dpo_coef)) or float(args.dpo_coef) < 0.0:
        print("[error] --dpo-coef 必须 >= 0", file=sys.stderr)
        return 2
    if not np.isfinite(float(args.dpo_beta)) or float(args.dpo_beta) <= 0.0:
        print("[error] --dpo-beta 必须是有限正数", file=sys.stderr)
        return 2
    if int(args.dpo_batch) <= 0 or int(args.dpo_every) <= 0:
        print("[error] --dpo-batch 必须 > 0 且 --dpo-every 必须 >= 1", file=sys.stderr)
        return 2
    # 场面题 / 强度辅助头（默认关闭）：系数非负、批量/周期合法
    for _nm in ("problem_bc_coef", "strength_aux_coef"):
        _v = float(getattr(args, _nm))
        if not np.isfinite(_v) or _v < 0.0:
            print(f"[error] --{_nm.replace('_', '-')} 必须 >= 0", file=sys.stderr)
            return 2
    for _nm in ("problem_batch", "problem_bc_every", "strength_aux_every"):
        if int(getattr(args, _nm)) <= 0:
            print(f"[error] --{_nm.replace('_', '-')} 必须 >= 1", file=sys.stderr)
            return 2
    # 题池开关（默认关闭）：turn 权重语法 + 强度增量阈值**启动即校验**（非法报错退出）。
    # 只在「启用场面题或显式给了开关」时导入 board_problems（保持默认路径不导入）。
    problem_turn_weights = {}
    _board_flag = (float(args.problem_bc_coef) > 0.0
                   or float(args.strength_aux_coef) > 0.0
                   or bool(str(args.problem_turn_weight or "").strip())
                   or float(args.problem_min_strength_delta) > 0.0)
    if _board_flag:
        try:
            from hsbg.az.train.board_problems import (format_turn_weights,
                                                     parse_turn_weights)
            problem_turn_weights = parse_turn_weights(
                str(args.problem_turn_weight or ""))
        except ValueError as exc:
            print(f"[error] --problem-turn-weight 非法：{exc}", file=sys.stderr)
            return 2
    _pmd = float(args.problem_min_strength_delta)
    if not np.isfinite(_pmd) or _pmd < 0.0:
        print(f"[error] --problem-min-strength-delta 必须有限且 >= 0，"
              f"得到 {args.problem_min_strength_delta!r}", file=sys.stderr)
        return 2
    _strength_enabled = bool(float(args.strength_aux_coef) > 0.0)
    _problem_enabled = bool(float(args.problem_bc_coef) > 0.0)
    _board_enabled = bool(_strength_enabled or _problem_enabled)
    try:
        bc_class_weights = parse_bc_class_weights(str(args.bc_class_weight))
    except ValueError as exc:
        print(f"[error] --bc-class-weight 非法: {exc}", file=sys.stderr)
        return 2
    try:
        bc_schedule = SeqCoefSchedule.from_spec(
            base_coef=float(args.bc_coef), spec=str(args.bc_coef_ramp),
            total_decisions=(float(args.stop_at_decisions) if
                             float(args.stop_at_decisions) > 0 else 3.0e7))
    except ValueError as exc:
        print(f"[error] --bc-coef-ramp 非法: {exc}", file=sys.stderr)
        return 2
    bc_enabled = bool(bc_schedule.enabled)
    if bc_enabled and float(args.bc_type_weight) <= 0.0 \
            and float(args.bc_card_weight) <= 0.0:
        print("[warn] BC 已启用但两层权重都为 0：自动关闭 bc_coef=0", flush=True)
        bc_enabled = False
        args.bc_coef = 0.0
        args.bc_coef_ramp = ""
    #: 是否构建/使用卡牌身份头（只在 BC 启用且 card 权重 > 0 时；bc_coef=0 不建）
    bc_card_head = bool(bc_enabled and float(args.bc_card_weight) > 0.0)
    bc_pool = None
    if bc_enabled:
        try:
            _t_bc = time.time()
            bc_pool = load_bc_samples(
                str(args.bc_samples), mmr_min=int(args.bc_mmr_min),
                mmr_boost=float(args.bc_mmr_boost),
                class_weight_overrides=(bc_class_weights or None))
            if len(bc_pool) == 0:
                raise ValueError("过滤后样本数为 0（动作白名单/MMR 下限）")
            _sum = bc_pool_summary(bc_pool)
            print(f"[bc] 真实人类 BC 池: samples={len(bc_pool)} "
                  f"mmr>={int(args.bc_mmr_min)} load={time.time() - _t_bc:.1f}s "
                  f"path={bc_pool.path}", flush=True)
            print(f"[bc] class_counts={json.dumps(_sum['class_counts'], ensure_ascii=False)}",
                  flush=True)
            print(f"[bc] class_fractions="
                  f"{json.dumps({k: round(v, 4) for k, v in _sum['class_fractions'].items()}, ensure_ascii=False)}",
                  flush=True)
            print(f"[bc] 分层目标: type_weight={float(args.bc_type_weight):g} "
                  f"card_weight={float(args.bc_card_weight):g} "
                  f"card_head={'on' if bc_card_head else 'off'} "
                  f"class_weights={json.dumps(bc_class_weights, ensure_ascii=False)} "
                  f"coef(dec=0)={bc_schedule.coef(0):.4g} "
                  f"ramp={json.dumps(bc_schedule.describe(), ensure_ascii=False)}",
                  flush=True)
        except Exception as exc:  # noqa: BLE001 - BC 可选，失败自动关闭
            print(f"[warn] BC 数据加载失败，自动关闭 bc_coef=0（不中断训练）："
                  f"{type(exc).__name__}: {exc}", flush=True)
            bc_enabled = False
            bc_card_head = False
            args.bc_coef = 0.0
            args.bc_coef_ramp = ""
            bc_pool = None

    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2
    if not torch_available():
        print("[error] torch 不可用", file=sys.stderr)
        return 2
    import torch
    if args.minutes <= 0 or args.games <= 0 or args.iterations < 0:
        print("[error] minutes/games 必须 >0，iterations 必须 >=0", file=sys.stderr)
        return 2
    if args.workers <= 0 or args.batch_size <= 0:
        print("[error] workers/batch-size 必须 >0", file=sys.stderr)
        return 2
    # 信用分配（§B）安全边界：默认 gae 完全不进入新路径。
    if int(args.baseline_action_dependent) != 0:
        print("[error] --baseline-action-dependent 只允许 0：动作条件 Q(s,a) 只能进 "
              "critic/TD loss，不能直接当 actor baseline（有偏，§B.3）。"
              "若要做 b(s,a) 必须走双采样/显式加权修正并通过 tests/test_credit.py。",
              file=sys.stderr)
        return 2
    if str(args.adv_estimator) in ("power", "geom"):
        if not (float(args.power_alpha) >= 0.0):
            print("[error] --power-alpha 必须 >= 0", file=sys.stderr)
            return 2
        if not (float(args.power_kappa) > 0.0):
            print("[error] --power-kappa 必须 > 0", file=sys.stderr)
            return 2
        if int(args.power_cutoff) < 0:
            print("[error] --power-cutoff 必须 >= 0", file=sys.stderr)
            return 2
        print(f"[credit] adv_estimator={args.adv_estimator} "
              f"alpha={args.power_alpha:g} kappa={args.power_kappa:g} "
              f"normalize={int(args.power_normalize)} "
              f"cutoff={int(args.power_cutoff)} timebase={args.credit_timebase}",
              flush=True)
    elif str(args.credit_timebase) != "decision":
        print("[error] --credit-timebase turn 需要 --adv-estimator power|geom",
              file=sys.stderr)
        return 2
    if args.trainer_state and not os.path.isfile(args.trainer_state):
        print(f"[error] trainer-state 不存在: {args.trainer_state}", file=sys.stderr)
        return 2
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed) % (2 ** 32))
    os.makedirs(args.out, exist_ok=True)
    eng = engine_info()
    print(f"[engine] {json.dumps(eng, ensure_ascii=False)}", flush=True)

    norm_mean = norm_std = None
    if args.checkpoint:
        model, meta = load_checkpoint(args.checkpoint, device=args.device)
        arch = str(meta.get("arch", args.arch))
        norm_mean, norm_std = meta.get("norm_mean"), meta.get("norm_std")
        # --d-model/--n-layers/--n-heads 只对「从零构建」生效；这里只做一致性提示，
        # 避免「以为建了 0.667M，其实加载了 checkpoint 的 384×8」这类静默错配。
        _size_want = _net_size_kwargs(args)
        _size_have = {k: int(meta.get(k, 0) or 0) for k in _size_want}
        _size_mismatch = {k: (v, _size_have[k]) for k, v in _size_want.items()
                          if _size_have[k] != v}
        if _size_mismatch:
            print(f"[warn] --d-model/--n-layers/--n-heads 与 checkpoint meta 不一致"
                  f"（以 meta 为准）：{_size_mismatch}", flush=True)
        print(f"[net] checkpoint meta 尺寸="
              f"{ {k: meta.get(k) for k in ('d_model','n_layers','n_heads')} }",
              flush=True)
        print(f"[net] checkpoint={args.checkpoint} arch={arch}", flush=True)
        # 有向 Move 头：旧 ckpt 没有 move_from/move_to 时，只追加两个投影并继承其余权重
        _move_split_loaded = bool(getattr(model, "move_head_split", False))
        if int(args.move_head_split) and not _move_split_loaded:
            _p0 = sum(p.numel() for p in model.parameters())
            try:
                attach_move_head_split(model)
            except ValueError as exc:
                print(f"[error] --move-head-split 1 不可用: {exc}", file=sys.stderr)
                return 2
            _p1 = sum(p.numel() for p in model.parameters())
            print(f"[net] move_head_split=on（旧 checkpoint 无有向 Move 投影）："
                  f"已追加 move_from/move_to，参数 +{_p1 - _p0:,}"
                  f"（{_p0:,} -> {_p1:,}），其余权重继承", flush=True)
        elif _move_split_loaded:
            print("[net] move_head_split=on（checkpoint meta 已声明）", flush=True)
        if seq_enabled and getattr(model, "seq_head", None) is None:
            print("[warn] checkpoint 没有动作序列辅助头（旧 checkpoint）：本次关闭 seq 辅助任务",
                  flush=True)
            seq_enabled = False
        if bc_card_head and getattr(model, "card_head", None) is None:
            # 旧 checkpoint（如 champion_c0_1975）没有 card_head：加载后追加，
            # 随机初始化，随后由 BC 卡牌身份 CE 训练。
            try:
                attach_bc_card_head(model)
                print(f"[bc] checkpoint 无 card_head：已追加 "
                      f"Linear({bc_card_head_dim(model)}, 3983)", flush=True)
            except Exception as exc:  # noqa: BLE001 - 退化到只做类型级 BC
                print(f"[warn] 追加 card_head 失败（本次只用类型级 BC）：{exc!r}",
                      flush=True)
                bc_card_head = False
                args.bc_card_weight = 0.0
    elif args.trainer_state and os.path.isfile(args.trainer_state):
        # trainer.pt 的 model state 是 strict 加载：老 state 没有 card_head 时不能
        # 在加载前追加（会 unexpected key），因此 trainer-state 路径要求 state 已含该头。
        # 尺寸必须与 state 一致：--d-model/--n-layers/--n-heads 在这里**必须**生效
        # （否则会按默认 384×8 建网，667k 的 state 直接 size mismatch 报错）。
        _size = _net_size_kwargs(args)
        model = build_net(arch=args.arch, seq_head=seq_enabled,
                          bc_card_head=False, **_size)
        if _size:
            print(f"[net] trainer-state 重建 {args.arch} {_size}", flush=True)
        if int(args.move_head_split):
            print("[warn] --trainer-state 路径按 state 的架构加载；--move-head-split 1 "
                  "只对 --checkpoint（model.pt）生效，本次忽略", flush=True)
        meta = {"arch": args.arch, **_size}
        arch = args.arch
        print(f"[net] empty model for trainer-state={args.trainer_state}", flush=True)
    else:
        _size = _net_size_kwargs(args)
        model = build_net(arch=args.arch, seq_head=seq_enabled,
                          bc_card_head=bc_card_head,
                          move_head_split=bool(int(args.move_head_split)),
                          **_size)
        meta = {"arch": args.arch, **_size}
        arch = args.arch
        if _size:
            print(f"[net] 从零构建 {args.arch} {_size}", flush=True)
    if bc_enabled and bc_card_head and getattr(model, "card_head", None) is None:
        print("[warn] 模型没有 card_head（trainer-state/旧 ckpt）：本次只用类型级 BC "
              "(bc_card_weight=0)", flush=True)
        bc_card_head = False
        args.bc_card_weight = 0.0
    if float(args.process_value_coef) > 0.0:
        if getattr(model, "process_head", None) is None:
            if args.trainer_state:
                print("[warn] --trainer-state 路径的 state 不含 process_head："
                      "本次关闭 process_value_coef=0（请在 --checkpoint 路径追加头）",
                      flush=True)
                args.process_value_coef = 0.0
            else:
                try:
                    attach_process_head(model)
                    print(f"[process] checkpoint 无 process_head：已追加 "
                          f"Linear({bc_card_head_dim(model)}, 3)（log1p 酒馆永久 buff / "
                          f"施法数 / consume 数）", flush=True)
                except Exception as exc:  # noqa: BLE001 - 非 entity/测试替身
                    print(f"[warn] 追加 process_head 失败（本次关闭 "
                          f"process_value_coef=0）：{exc!r}", flush=True)
                    args.process_value_coef = 0.0
        else:
            print("[process] checkpoint 已带 process_head（沿用权重）", flush=True)
    model.to(torch.device(args.device))
    print(f"[net] arch={arch} params={sum(p.numel() for p in model.parameters()):,}",
          flush=True)

    # ---- 场面题池 + 强度辅助头（默认关闭 = 不读文件、不建头、零影响）----------
    # 题目池里同时有「人类参考动作 top-k 软标签」与「t+3 战团强度/tier+1 标签」：
    # 题目 CE 与强度辅助头共用同一批题目 + 同一次 forward_problem（B/C/D 三臂可比）。
    problem_pool = None
    if _board_enabled:
        try:
            from hsbg.az.train.board_problems import load_problem_pool
            _t_prob = time.time()
            problem_pool = load_problem_pool(
                str(args.problem_pool),
                min_strength_delta=float(args.problem_min_strength_delta),
                turn_weights=str(args.problem_turn_weight or ""))
            if len(problem_pool) == 0:
                raise ValueError(f"题目池为空/不存在: {args.problem_pool}")
            _ps = problem_pool.summary()
            print(f"[problems] pool={problem_pool.path} n={_ps['problems']} "
                  f"bc_valid={_ps['bc_valid']}({_ps['bc_valid_rate']:.1%}) "
                  f"aux_valid={_ps['aux_valid']}({_ps['aux_valid_rate']:.1%}) "
                  f"turns={_ps['by_turn']} "
                  f"load={time.time() - _t_prob:.1f}s", flush=True)
            _pfil = dict(_ps.get("filter") or {})
            print(f"[problems] filter: pool_size={_pfil.get('problem_pool_size')} "
                  f"used={_pfil.get('problem_pool_used')} "
                  f"dropped_by_delta={_pfil.get('problem_pool_dropped_by_delta')} "
                  f"dropped_by_turn={_pfil.get('problem_pool_dropped_by_turn')} "
                  f"min_strength_delta={float(_pmd):g} "
                  f"turn_weight={format_turn_weights(problem_turn_weights) or '-'} "
                  f"used_turn_weight="
                  f"{format_turn_weights(problem_pool.turn_weights) or '-'} "
                  f"late_turn(>= {_ps.get('late_turn_min')})="
                  f"{_ps.get('late_turn_problems')} "
                  f"delta_p50={_ps.get('strength_delta_p50', 0.0):.3f}",
                  flush=True)
            print(f"[problems] by_tag={json.dumps(_ps['by_tag'], ensure_ascii=False)} "
                  f"tier_up_rate={_ps['tier_up_rate']:.3f} "
                  f"strength_p50 before={_ps['strength_before_p50']:.0f} "
                  f"after={_ps['strength_after_p50']:.0f} "
                  f"norm={json.dumps(_ps['norm'], ensure_ascii=False)}", flush=True)
            if _problem_enabled and int(_ps["bc_valid"]) == 0:
                print("[warn] 题目池没有任何合法参考解（bc_valid=0）："
                      "自动关闭 problem_bc_coef=0", flush=True)
                args.problem_bc_coef = 0.0
                _problem_enabled = False
            if _strength_enabled and int(_ps["aux_valid"]) == 0:
                print("[warn] 题目池没有任何 t+3 强度标注（aux_valid=0）："
                      "自动关闭 strength_aux_coef=0", flush=True)
                args.strength_aux_coef = 0.0
                _strength_enabled = False
        except Exception as exc:  # noqa: BLE001 - 可选辅助，失败不中断训练
            print(f"[warn] 场面题池加载失败，自动关闭 problem_bc_coef/"
                  f"strength_aux_coef（不中断训练）：{type(exc).__name__}: {exc}",
                  flush=True)
            args.problem_bc_coef = 0.0
            args.strength_aux_coef = 0.0
            _problem_enabled = _strength_enabled = False
            problem_pool = None
    if _strength_enabled and problem_pool is not None:
        _snorm = dict(problem_pool.norm or {"mean": 0.0, "std": 1.0})
        if getattr(model, "strength_head", None) is None:
            try:
                attach_strength_head(model, norm=_snorm)
                print(f"[strength] checkpoint 无 strength_head：已追加 "
                      f"Linear({bc_card_head_dim(model)}, 2)（t+3 log1p 强度 + tier+1），"
                      f"norm={json.dumps(_snorm, ensure_ascii=False)}", flush=True)
            except Exception as exc:  # noqa: BLE001 - 非 entity/测试替身
                print(f"[warn] 追加 strength_head 失败（本次关闭 strength_aux_coef=0）："
                      f"{exc!r}", flush=True)
                args.strength_aux_coef = 0.0
                _strength_enabled = False
        else:
            model.strength_norm = _snorm
            print(f"[strength] checkpoint 已带 strength_head（沿用权重）；"
                  f"norm={json.dumps(_snorm, ensure_ascii=False)}", flush=True)
        if str(args.strength_head_init) == "fit":
            from hsbg.az.train.board_problems import fit_strength_head
            try:
                _rep = fit_strength_head(
                    model, problem_pool, ridge=float(args.strength_head_ridge),
                    device=str(args.device))
                print(f"[strength] 离线拟合线性头（题目池 aux_valid="
                      f"{_rep['n']}）：mse={_rep['mse']:.4f} bce={_rep['bce']:.4f} "
                      f"tier_acc={_rep['tier_acc']:.3f} "
                      f"cv_mse={_rep.get('cv_mse', float('nan')):.4f} "
                      f"pearson(增量)={_rep['pearson_delta']:.3f} "
                      f"ridge={_rep['ridge']:g} frozen={_rep['frozen']}", flush=True)
            except Exception as exc:  # noqa: BLE001 - 拟合失败保留随机头
                print(f"[warn] 强度头离线拟合失败（保留随机初始化）："
                      f"{type(exc).__name__}: {exc}", flush=True)
    if (_problem_enabled or _strength_enabled):
        print(f"[problems] problem_bc_coef={float(args.problem_bc_coef):g} "
              f"every={int(args.problem_bc_every)} "
              f"turn_weight={format_turn_weights(problem_turn_weights) or '-'} "
              f"min_strength_delta={float(args.problem_min_strength_delta):g} "
              f"strength_aux_coef={float(args.strength_aux_coef):g} "
              f"every={int(args.strength_aux_every)} "
              f"batch={int(args.problem_batch)} "
              f"tier_pos_weight={float(args.strength_tier_pos_weight):g}", flush=True)

    # ---- upgrade 子集 DPO：预加载池 + 启动诊断（默认关闭 = 零影响）------------
    # 池 ~3050 条 / ~7s；只在 --dpo-coef>0 时加载。失败自动关闭（不中断训练）。
    dpo_pool: Optional[UpgradeSamples] = None
    if float(args.dpo_coef) > 0.0:
        try:
            _t_dpo = time.time()
            dpo_pool = load_upgrade_samples(str(args.dpo_samples))
            if len(dpo_pool) == 0:
                raise ValueError("过滤后样本数为 0（动作白名单/MMR 下限）")
            print(f"[dpo] upgrade 池: samples={len(dpo_pool)} "
                  f"mmr>={int(dpo_pool.mmr_min)} "
                  f"load={time.time() - _t_dpo:.1f}s path={dpo_pool.path}",
                  flush=True)
        except Exception as exc:  # noqa: BLE001 - DPO 可选，失败自动关闭
            print(f"[warn] upgrade DPO 样本加载失败，自动关闭 dpo_coef=0"
                  f"（不中断训练）：{type(exc).__name__}: {exc}", flush=True)
            args.dpo_coef = 0.0
            dpo_pool = None
    if dpo_pool is not None and len(dpo_pool) > 0:
        # 启动诊断：当前策略在池上的 DPO 初值 / 接受率（no_grad，不改权重）
        _p = _dpo_startup_probe(model, dpo_pool, beta=float(args.dpo_beta),
                                device=str(args.device))
        _term = float(args.dpo_coef) * float(_p["loss"])
        _avg = _term / float(max(1, int(args.dpo_every)))
        _ref, _ref_src = _ppo_total_ref(str(args.out))
        print(f"[dpo] beta={float(args.dpo_beta):g} coef={float(args.dpo_coef):g} "
              f"batch={int(args.dpo_batch)} every={int(args.dpo_every)} "
              f"（每 {int(args.dpo_every)} 个 iteration 加一次 coef*L_dpo）", flush=True)
        print(f"[dpo] 当前策略 on 池: dpo_loss={_p['loss']:.4f} "
              f"accept_rate={_p['accept_rate']:.3f}（n={int(_p['n'])}）"
              f" -> 单步项={_term:.5f}，平均/iteration={_avg:.5f}", flush=True)
        print(f"[dpo] 期望梯度占比（loss 标度参考）: 单步 DPO 项 / |PPO total| ≈ "
              f"{_term / max(abs(_ref), 1e-9) * 100:.2f}%（参考 total={_ref:.4f}，"
              f"来自{_ref_src}）", flush=True)
        _gref = _dpo_grad_ref()
        if _gref is not None:
            _gc = float(args.dpo_coef) * float(_gref["share_per_coef"])
            print(f"[dpo] 期望梯度占比（实测 ‖g_dpo‖/‖g_ppo‖，"
                  f"来自 {_gref['path']}）: 单步≈{_gc * 100:.2f}%，"
                  f"平均/iteration≈{_gc / max(1, int(args.dpo_every)) * 100:.2f}%",
                  flush=True)
        else:
            print("[dpo] 期望梯度占比：暂无实测梯度范数比（可跑 "
                  "scripts/dpo_grad_probe.py 生成 runs/dpo_grad_probe.json）",
                  flush=True)

    p_cfg = PPOConfig(
        epochs=int(args.epochs), minibatch=int(args.minibatch), lr=float(args.lr),
        clip=float(args.clip), gamma=float(args.gamma), lam=float(args.lam),
        target_kl=float(args.target_kl),
        rank_utility_coef=float(args.rank_utility_coef),
        terminal_strength_coef=float(args.terminal_strength_coef),
        adv_estimator=str(args.adv_estimator),
        power_alpha=float(args.power_alpha),
        power_kappa=float(args.power_kappa),
        power_normalize=bool(int(args.power_normalize)),
        power_cutoff=int(args.power_cutoff),
        credit_timebase=str(args.credit_timebase),
        baseline_action_dependent=int(args.baseline_action_dependent),
        entropy_coef=float(args.entropy_coef), pi_coef=float(args.pi_coef),
        max_grad_norm=float(args.max_grad_norm),
        grad_accum=int(args.grad_accum), amp=str(args.amp),
        device=str(args.device), seed=int(args.seed),
        log_every=int(args.log_every),
        compile_train=int(args.compile_train),
        anchor_amp=bool(int(args.anchor_amp)),
        # 动作序列辅助任务：初始系数由 ramp 在 dec=0 处给出（无 ramp 时=--seq-coef）
        seq_coef=(seq_schedule.coef(0) if seq_enabled else 0.0),
        seq_coef_ramp=(str(args.seq_coef_ramp) if seq_enabled else ""),
        # 真实人类 BC 辅助正则（分层目标）：初始系数由 ramp 在 dec=0 处给出；
        # 池在下方注入 trainer。
        bc_coef=(bc_schedule.coef(0) if bc_enabled else 0.0),
        bc_coef_ramp=(str(args.bc_coef_ramp) if bc_enabled else ""),
        bc_mmr_min=int(args.bc_mmr_min),
        bc_mmr_boost=float(args.bc_mmr_boost),
        bc_class_weights=dict(bc_class_weights),
        bc_samples_path=str(args.bc_samples),
        bc_batch=int(args.bc_batch),
        bc_every=int(args.bc_every),
        bc_compile=int(args.bc_compile),
        bc_type_weight=float(args.bc_type_weight),
        bc_card_weight=float(args.bc_card_weight),
        # upgrade 子集 one-sided DPO：系数固定（无 ramp）；池在下方注入 trainer
        dpo_coef=float(args.dpo_coef),
        dpo_beta=float(args.dpo_beta),
        dpo_batch=int(args.dpo_batch),
        dpo_every=int(args.dpo_every),
        dpo_samples=str(args.dpo_samples),
        # 场面题 soft-label CE + 强度辅助头（默认关闭；池在下方注入 trainer）
        problem_bc_coef=float(args.problem_bc_coef),
        problem_bc_every=int(args.problem_bc_every),
        problem_batch=int(args.problem_batch),
        problem_pool_path=str(args.problem_pool),
        problem_turn_weight=str(args.problem_turn_weight or ""),
        problem_min_strength_delta=float(args.problem_min_strength_delta),
        strength_aux_coef=float(args.strength_aux_coef),
        strength_aux_every=int(args.strength_aux_every),
        strength_tier_pos_weight=float(args.strength_tier_pos_weight),
        # 缩放教师 DAgger / 过程价值（默认 0 = 逐位等价）
        teacher_bc_coef=float(args.teacher_bc_coef),
        process_value_coef=float(args.process_value_coef),
        # 复利结构辅助 BC（默认 0 = 逐位等价；标签由 _attach_replication_bc_labels 写入 batch）
        discover_bc_coef=float(args.discover_bc_coef),
        triple_bc_coef=float(args.triple_bc_coef),
        upgrade_bc_coef=float(getattr(args, "upgrade_curve_bc_coef", 0.0) or 0.0),
        upgrade_bc_guard_ratio=(-1.0 if getattr(
            args, "upgrade_curve_bc_guard_ratio", -1.0) is None else float(
            getattr(args, "upgrade_curve_bc_guard_ratio", -1.0))),
        bc_ce_norm=bool(int(args.bc_ce_norm)),
        bc_guard_ratio=float(args.bc_guard_ratio),
        # 搜索行为混合（默认 eps=0 -> PPO 侧只用于回显/统计，未启用时整组键被移除）
        behavior_mix_eps=float(args.behavior_mix_eps),
        behavior_mix_when=str(args.behavior_mix_when),
        behavior_mix_max_per_turn=int(args.behavior_mix_max_per_turn),
        behavior_mix_topk=int(args.behavior_mix_topk),
        behavior_mix_turns=int(args.behavior_mix_turns),
        behavior_mix_max_ms=float(args.behavior_mix_max_ms),
        behavior_mix_exact=int(args.behavior_mix_exact))
    trainer: Optional[PPOTrainer] = None
    if args.trainer_state and os.path.isfile(args.trainer_state):
        trainer = PPOTrainer.load(model, args.trainer_state, config=p_cfg,
                                  device=args.device, bc_pool=bc_pool,
                                  dpo_pool=dpo_pool)
        print(f"[trainer] loaded updates={trainer.updates} "
              f"lr={trainer.optimizer.param_groups[0]['lr']:.3g}", flush=True)
    else:
        trainer = PPOTrainer(model, p_cfg, lr_min_ratio=float(args.lr_min_ratio),
                             max_updates=int(args.max_updates), bc_pool=bc_pool,
                             dpo_pool=dpo_pool)

    # BC 池注入（CLI 已预加载/打印；trainer 若自己加载过则复用）
    if bc_enabled:
        if bc_pool is not None:
            trainer.set_bc_pool(bc_pool)
        elif getattr(trainer, "bc_pool", None) is not None:
            bc_pool = trainer.bc_pool
        if getattr(trainer, "bc_pool", None) is None:
            print("[warn] BC 池不可用，自动关闭 bc_coef=0", flush=True)
            bc_enabled = False
            trainer.config.bc_coef = 0.0
            trainer.config.bc_coef_ramp = ""

    # upgrade DPO 池注入（CLI 已预加载/打印；trainer 若自己加载过则复用）
    dpo_enabled = bool(float(args.dpo_coef) > 0.0)
    if dpo_enabled:
        if dpo_pool is not None:
            trainer.set_dpo_pool(dpo_pool)
        elif getattr(trainer, "dpo_pool", None) is not None:
            dpo_pool = trainer.dpo_pool
            print(f"[dpo] 复用 trainer 已加载的 upgrade 池: samples={len(dpo_pool)}",
                  flush=True)
        if getattr(trainer, "dpo_pool", None) is None:
            print("[warn] upgrade DPO 池不可用，自动关闭 dpo_coef=0", flush=True)
            dpo_enabled = False
            trainer.config.dpo_coef = 0.0

    # 场面题池注入（CLI 已预加载/打印；未启用时为 None，trainer 不会自己加载）
    if _board_enabled and problem_pool is not None and not args.trainer_state:
        trainer.set_problem_pool(problem_pool)

    # ---- 日志：history.jsonl 追加（兼容旧 history.json）----
    history: List[Dict[str, Any]] = []
    history_path = os.path.join(args.out, "history.jsonl")
    legacy_history = os.path.join(args.out, "history.json")
    if args.trainer_state:
        if os.path.isfile(history_path):
            _, history = read_run(history_path)
        elif os.path.isfile(legacy_history):
            _, history = read_run(legacy_history)
    write_header(history_path, {k: v for k, v in vars(args).items()})

    if trainer.extra.get("norm_mean") is not None:
        norm_mean = np.asarray(trainer.extra["norm_mean"], dtype=np.float32)
    if trainer.extra.get("norm_std") is not None:
        norm_std = np.asarray(trainer.extra["norm_std"], dtype=np.float32)
    trainer.extra["norm_mean"] = (None if norm_mean is None else norm_mean.tolist())
    trainer.extra["norm_std"] = (None if norm_std is None else norm_std.tolist())
    start_i = int(trainer.updates)
    print(f"[resume] start_iter={start_i} updates={trainer.updates}", flush=True)

    # ---- KL anchor（AutoTavern Table 7：β=0.1，仅前 100 个 iteration）----
    if float(args.anchor_beta) > 0.0:
        trainer.set_anchor()
        print(f"[anchor] beta={args.anchor_beta} for first "
              f"{int(args.anchor_iterations)} iters (stage-start policy frozen)",
              flush=True)
    if int(args.compile_train) > 0:
        tf = getattr(trainer, "train_forward", None)
        if tf is None:
            print("[compile] train compile 请求但未生效（回退 eager）", flush=True)
        else:
            print(f"[compile] train compile={int(args.compile_train)} "
                  f"active={tf.active} main={tf.main_compiled} aux={tf.aux_compiled} "
                  f"warmup={tf.warmup_seconds:.1f}s"
                  + (f" warnings={tf.warnings}" if tf.warnings else ""), flush=True)
        af = getattr(trainer, "anchor_forward", None)
        if af is not None:
            print(f"[compile] anchor compile active={af.active} "
                  f"warmup={af.warmup_seconds:.1f}s", flush=True)

    # ---- 周期 C0 评测（监控曲线；avg rank<=3.0 触发镜像库）----
    # 同步（--eval-async 0，旧行为）在主循环里阻塞；异步（1）把 ckpt 丢给独立子进程，
    # 由轻量线程回收结果。两条路径共用 _post_eval 做 TRIGGER / 早停判定。
    evals: list = []
    eval_dir = os.path.join(args.out, "eval")
    eval_async = bool(int(args.eval_async))
    eval_device = str(args.eval_device or ("cuda:4" if eval_async else args.device))
    # panel 列表：bot=旧 c0_gate 面板；human=人类战团面板；both=两个子进程串行排队。
    eval_panels = panels_from_spec(args.eval_panel)
    eval_human_boards = str(args.eval_human_boards or os.path.join(
        ROOT, "data", "real_library", "library_real_degraded.jsonl"))
    if "human" in eval_panels and not os.path.isfile(eval_human_boards):
        print(f"[error] human 评测面板需要人类战团数据: {eval_human_boards}",
              file=sys.stderr)
        return 2
    eval_stop = threading.Event()
    eval_state: Dict[str, Any] = {"stop_reason": ""}
    eval_history_lock = threading.Lock()
    #: 最近一次各面板结果（写 history.jsonl 的 eval 段；bot -> mean_rank，
    #: human -> human_mean_rank，见 docs/EVAL_PANELS.md）
    latest_eval: Dict[str, Dict[str, Any]] = {}

    def _save_eval_ckpt(decisions_done: int) -> Tuple[str, str]:
        """落一份评测专用 ckpt（与训练权重解耦，子进程只读它）。"""
        os.makedirs(eval_dir, exist_ok=True)
        tag = f"{int(decisions_done):09d}"
        ckpt = os.path.join(eval_dir, f"ckpt_{tag}.pt")
        save_checkpoint(model, ckpt, meta={**meta, "arch": arch},
                        norm_mean=norm_mean, norm_std=norm_std)
        return tag, ckpt

    def _dyn_step(decisions_done: int) -> Optional[Dict[str, Any]]:
        """动态课程一步：跑**真实强度口径**面板（5 席 × p0.9，96 局），按 t15 Σ 加减席。

        规则（Lead 定，可配置）：起点 `--dyn-start-seats` 席 × `--dyn-p`；
        - 若 `S15 >= last_S15 × (1 + +threshold)` 且 `seats < --dyn-max-seats` ⇒ **加一席**；
        - 若 `seats > start` 且 `S15 < last_S15 × (1 - threshold)` ⇒ **退一席**，
          并保持 `--dyn-hold-decisions` 不再加席；
        - 主判据用真实口径，训练剂量只作参考。
        结果写 `out/dynamic_curriculum.json`，并进 `history.jsonl` 的 `ppo.dyn_curriculum`。
        """
        tag, ckpt = _save_eval_ckpt(decisions_done)
        out_json = os.path.join(eval_dir, f"dyn_quality_{tag}.json")
        cmd = [sys.executable, os.path.join(ROOT, "scripts", "quality_monitor.py"),
               "--checkpoint", str(ckpt), "--arch", str(arch),
               "--device", str(args.eval_device or args.device),
               "--games", str(int(args.dyn_quality_games)), "--seed-base", "520000",
               "--human-boards", str(args.human_boards),
               "--human-board-p", "0.9", "--human-board-seats", "5",
               "--human-board-fidelity", "full", "--human-board-sample", "auto",
               "--human-board-set-tier", "1", "--human-board-fast-inject", "1",
               "--move-guard", "1", "--move-cap", "3", "--move-repeat-limit", "2",
               "--out", str(out_json)]
        try:
            _t = time.time()
            subprocess.run(cmd, check=False, timeout=1800)
            with open(out_json, encoding="utf-8") as f:
                q = json.load(f)
            s15 = float((q.get("infer_search") or {}).get("strength_t15_p50") or 0.0)
        except BaseException as exc:  # noqa: BLE001 - 质量面板失败不能中断训练
            print(f"[dyn] 真实强度面板失败（本点跳过）：{exc!r}", flush=True)
            return None
        last = _dyn["last_s15"]
        act = "hold"
        thr = float(args.dyn_threshold)
        if last is not None and s15 >= last * (1.0 + thr) \
                and _dyn["seats"] < int(args.dyn_max_seats) \
                and cum_decisions >= _dyn["hold_until"]:
            _dyn["seats"] += 1
            act = "up"
        elif last is not None and s15 < last * (1.0 - thr) \
                and _dyn["seats"] > int(args.dyn_start_seats):
            _dyn["seats"] -= 1
            _dyn["hold_until"] = cum_decisions + float(args.dyn_hold_decisions)
            act = "down"
        rec = {"decisions": int(decisions_done), "s15_real": s15,
               "last_s15_real": last, "seats": int(_dyn["seats"]),
               "action": act, "seconds": round(time.time() - _t, 1),
               "quality_json": out_json,
               "tier_t15": q.get("tier_p50_t15"),
               "death_turn_p50": q.get("death_turn_p50"),
               "survive_t12": q.get("survive_t12_ratio"),
               "mean_rank": q.get("mean_rank")}
        _dyn["last_s15"] = s15
        _dyn["history"].append(rec)
        try:
            write_json_atomic(os.path.join(args.out, "dynamic_curriculum.json"),
                              {"seats": int(_dyn["seats"]), "p": float(args.dyn_p),
                               "history": _dyn["history"]})
        except BaseException:  # noqa: BLE001
            pass
        print(f"[dyn] dec={decisions_done} S15_real={s15:.0f} (last={last}) "
              f"seats={_dyn['seats']} action={act} tier_t15={rec['tier_t15']} "
              f"death={rec['death_turn_p50']}", flush=True)
        return rec

    def _post_eval(rec: Dict[str, Any]) -> None:
        """评测结果后处理（同步/异步共用，异步时在 monitor 线程执行）。"""
        panel = str(rec.get("panel") or "bot")
        has = (rec.get("human_mean_rank") is not None if panel == "human"
               else rec.get("mean_rank") is not None)
        with eval_history_lock:
            if has:
                latest_eval[panel] = dict(rec)
        # TRIGGER / 早停只按 bot 面板（旧语义），human 面板只作主指标记录。
        mr = rec.get("mean_rank") if panel == "bot" else None
        if mr is None:
            return
        mr = float(mr)
        if mr <= 3.0:
            trig = os.path.join(args.out, "TRIGGER_library.json")
            write_json_atomic(trig, {"decisions": int(rec["decisions"]),
                                     "mean_rank": mr,
                                     "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
            print(f"[TRIGGER] avg rank {mr:.3f} <= 3.0 -> "
                  f"构建高质量对局镜像库 ({trig})", flush=True)
        th = float(args.eval_stop_mean_rank)
        if th > 0.0 and mr <= th:
            eval_state["stop_reason"] = (f"mean_rank={mr:.4f} <= {th:.4f} "
                                         f"@dec={int(rec['decisions'])}")
            eval_stop.set()
            print(f"[eval] stop requested: {eval_state['stop_reason']} "
                  f"-> 下一个 iteration 边界停止", flush=True)

    def _eval_snapshot() -> Dict[str, Any]:
        """history.jsonl 的 ``eval`` 段：bot 面板 ``mean_rank`` + human 面板
        ``human_mean_rank``（两个键并存，方便画图脚本直接读）。"""
        with eval_history_lock:
            bot = dict(latest_eval.get("bot") or {})
            human = dict(latest_eval.get("human") or {})
            if not bot and not human:
                return {}
            return {
                "mean_rank": bot.get("mean_rank"),
                "human_mean_rank": human.get("human_mean_rank"),
                "bot_mean_rank": bot.get("bot_mean_rank"),
                "top4": bot.get("top4"),
                "win": bot.get("win"),
                "human_top4": human.get("human_top4"),
                "human_win": human.get("human_win"),
                "human_quantile": human.get("quantile"),
                "bot_decisions": bot.get("decisions"),
                "human_decisions": human.get("decisions"),
            }

    def _append_eval_history(rec: Dict[str, Any]) -> None:
        with eval_history_lock:
            evals.append(rec)
            write_json_atomic(os.path.join(eval_dir, "history.json"), {"evals": evals})

    def _run_eval(decisions_done: int) -> None:
        """同步评测：主循环阻塞到各 panel 的子进程依次结束。"""
        tag, ckpt = _save_eval_ckpt(decisions_done)
        for panel in eval_panels:
            prefix = "c0" if panel == "bot" else "human"
            out_json = os.path.join(eval_dir, f"{prefix}_{tag}.json")
            log_path = os.path.join(eval_dir, f"{prefix}_{tag}.log")
            if panel == "bot":
                cmd = build_c0_cmd(
                    sys.executable, ROOT, ckpt, arch=str(arch), device=eval_device,
                    games=int(args.eval_games), seats=int(args.eval_seats),
                    seed_base=int(args.eval_seed_base), out_json=out_json)
            else:
                cmd = build_human_cmd(
                    sys.executable, ROOT, ckpt, arch=str(arch), device=eval_device,
                    games=int(args.eval_games), seats=int(args.eval_seats),
                    seed_base=int(args.eval_seed_base), out_json=out_json,
                    quantile=str(args.eval_human_quantile),
                    human_boards=eval_human_boards,
                    baseline_bot=bool(int(args.eval_human_baseline_bot)))
            t_eval = time.time()
            print(f"[eval] dec={int(decisions_done)} panel={panel} "
                  f"start games={args.eval_games}", flush=True)
            with open(log_path, "w", encoding="utf-8") as lf:
                rc = subprocess.call(cmd, cwd=ROOT, stdout=lf, stderr=lf)
            rec = parse_panel_result(decisions_done, rc, time.time() - t_eval,
                                     out_json, panel=panel)
            _append_eval_history(rec)
            if panel == "human" and rec.get("human_mean_rank") is not None:
                print(f"[eval] dec={int(decisions_done)} panel=human "
                      f"human_mean_rank={rec['human_mean_rank']:.3f} "
                      f"top4={rec['human_top4']:.3f} win={rec['human_win']:.3f} "
                      f"({rec['seconds']}s)", flush=True)
            elif panel == "bot" and rec.get("mean_rank") is not None:
                print(f"[eval] dec={int(decisions_done)} panel=bot "
                      f"mean_rank={rec['mean_rank']:.3f} "
                      f"bot={rec['bot_mean_rank']:.3f} top4={rec['top4']:.3f} "
                      f"win={rec['win']:.3f} ({rec['seconds']}s)", flush=True)
            else:
                print(f"[eval] dec={int(decisions_done)} panel={panel} FAILED rc={rc} "
                      f"error={rec.get('error')} log={log_path}", flush=True)
            _post_eval(rec)

    # 异步评测：独立子进程 + 一个轻量回收线程（并发上限 1，提交本身只花 ~0.3s 存 ckpt）
    eval_runner: Optional[AsyncEvalRunner] = None
    if eval_async:
        eval_runner = AsyncEvalRunner(
            out_dir=args.out, root=ROOT, arch=arch, device=eval_device,
            games=int(args.eval_games), seats=int(args.eval_seats),
            seed_base=int(args.eval_seed_base),
            panels=eval_panels,
            human_quantile=str(args.eval_human_quantile),
            human_boards=eval_human_boards,
            baseline_bot=bool(int(args.eval_human_baseline_bot)),
            on_result=_post_eval)
        print(f"[eval-async] on：device={eval_device} games={args.eval_games} "
              f"seats={args.eval_seats} panels={eval_panels} "
              f"human_quantile={args.eval_human_quantile}；主循环不等待"
              f"（并发上限 1，panel 串行排队，drain={int(args.eval_drain)}）",
              flush=True)
        if int(args.eval_every_decisions) <= 0:
            print("[warn] --eval-async 1 但 --eval-every-decisions=0：不会触发评测",
                  flush=True)
        if str(eval_device).startswith("cuda") and int(args.gpu_free_check):
            try:
                _eidx = int(str(eval_device).split(":")[1]) if ":" in str(eval_device) else 0
            except ValueError:
                _eidx = None
            _used = _gpu_used_mib()
            if _eidx is not None and _used.get(_eidx, 0) > int(args.gpu_free_mib):
                print(f"[warn] 评测卡 {eval_device} 已被占用 "
                      f"{_used[_eidx]}MiB（>{int(args.gpu_free_mib)}MiB）：评测子进程可能 "
                      f"OOM/变慢，建议换 --eval-device（如 cuda:6/7）", flush=True)

    def _submit_eval(decisions_done: int) -> None:
        """异步提交：只保存 ckpt + spawn，不等待（跳过时 runner 自己记 eval_skipped）。

        已有一个评测在跑时**不落 61MB ckpt**：直接让 runner 记一条 skipped。
        """
        if eval_runner.running():
            eval_runner.submit(decisions_done, "")
            return
        _tag, ckpt = _save_eval_ckpt(decisions_done)
        eval_runner.submit(decisions_done, ckpt)

    search_fn = search_cfg = None
    if int(args.sims) > 0:
        try:
            from hsbg.az import SearchConfig, search as az_search
        except Exception as exc:  # noqa: BLE001
            print(f"[error] search unavailable: {exc!r}", file=sys.stderr)
            return 2
        search_cfg = SearchConfig(simulations=int(args.sims),
                                  determinizations=int(args.determinizations),
                                  seed=int(args.seed))
        search_fn = az_search

    # ---- actor pool / 单进程采集 ----
    pool: Optional[ProcessActorPool] = None
    pool_ckpt = os.path.join(args.out, "_pool_weights.pt")
    if int(args.processes) > 1:
        if not str(args.gpus).strip():
            print("[error] --processes>1 需要 --gpus（物理 GPU 序号）", file=sys.stderr)
            return 2
        if os.environ.get("CUDA_VISIBLE_DEVICES"):
            print("[error] 请 unset CUDA_VISIBLE_DEVICES：--gpus 用物理序号", file=sys.stderr)
            return 2
        gpus = [int(x) for x in str(args.gpus).split(",") if x.strip()]
        # 邻居抢占检测：显存已用 > 阈值（默认 1 GiB）的卡从 actor 列表剔除并 warn。
        # 失败（nvidia-smi 不可用）时不做剔除，按用户给的列表跑。
        if int(args.gpu_free_check):
            used = _gpu_used_mib()
            if used:
                threshold = int(args.gpu_free_mib)
                busy = [g for g in gpus if used.get(g, 0) > threshold]
                if busy:
                    detail = ", ".join(f"cuda:{g}={used.get(g)}MiB" for g in busy)
                    warn = (f"[warn] GPU 已被占用（>{threshold}MiB，疑似邻居进程）：{detail}"
                            f" -> 从 actor 列表剔除")
                    print(warn, flush=True)
                    gpus = [g for g in gpus if g not in busy]
                if not gpus:
                    print("[error] --gpu-free-check 后没有可用 GPU（可用 --gpu-free-check 0 "
                          "跳过检查）", file=sys.stderr)
                    return 2
        per_gpu = {g: sum(1 for k in range(int(args.processes)) if gpus[k % len(gpus)] == g)
                   for g in gpus}
        print(f"[pool] processes={int(args.processes)} gpus={gpus} "
              f"workers/gpu={per_gpu}", flush=True)
        if len(gpus) != len(set(gpus)):
            print(f"[warn] --gpus 有重复项: {gpus}", flush=True)
        save_checkpoint(model, pool_ckpt, meta={**meta, "arch": arch},
                        norm_mean=norm_mean, norm_std=norm_std)
        pool = ProcessActorPool(
            int(args.processes), gpus, pool_ckpt, arch=arch,
            sims=int(args.sims), determinizations=int(args.determinizations),
            seed=int(args.seed), threads=int(args.threads),
            batch_size=int(args.batch_size),
            max_wait_ms=float(args.leaf_wait_ms),
            tmpdir=os.path.join(args.out, "_proc_tmp"),
            ipc_mode=str(args.ipc_mode),
            records_dtype=str(args.records_dtype),
            shm_slots=int(args.ipc_shm_slots),
            collect_sha=bool(int(args.collect_sha)))
        print(f"[pool] {json.dumps(pool.describe(), ensure_ascii=False)}", flush=True)
        if eval_async and str(eval_device).startswith("cuda"):
            try:
                _eidx = int(str(eval_device).split(":")[1]) if ":" in str(eval_device) else 0
            except ValueError:
                _eidx = None
            if _eidx is not None and _eidx in gpus:
                print(f"[warn] 评测卡 {eval_device} 同时是 actor 卡：异步评测不会阻塞主循环，"
                      f"但会与 actor 抢算力（想完全隔离可换 --eval-device cuda:6/7）",
                      flush=True)
    batch_server = None
    evaluator = None
    if pool is None and args.workers > 1:
        batch_server = BatchLeafServer(model, device=args.device,
                                       batch_size=int(args.batch_size),
                                       max_wait_ms=2.0, queue_size=8192,
                                       norm_mean=norm_mean, norm_std=norm_std)
        evaluator = BatchPPOEvaluator(batch_server)
    elif pool is None:
        evaluator = PPOEvaluator(model, device=args.device,
                                 norm_mean=norm_mean, norm_std=norm_std)

    # ---- 权重版本文件（流水线：worker 在任务开始时按版本懒加载）----
    weights_dir = os.path.join(args.out, "_weights")
    os.makedirs(weights_dir, exist_ok=True)
    published: Dict[str, Any] = {"version": None, "path": None, "history": {}}

    def _publish_weights(version: int) -> str:
        path = os.path.join(weights_dir, f"w_{int(version):06d}.pt")
        tmp = path + ".tmp"
        save_checkpoint(model, tmp, meta={**meta, "arch": arch},
                        norm_mean=norm_mean, norm_std=norm_std)
        os.replace(tmp, path)
        published["version"], published["path"] = int(version), path
        keep = max(2, int(args.keep_versions))
        # 按**写入时间**裁剪，而不是按版本号字符串排序：续训时 trainer.updates 会**回落到
        # checkpoint 里的版本**（如 501），而目录里已有更高版本（536–538）；按名字排序会把
        # 刚写出的 w_000501.pt 当成"最旧"删掉 ⇒ 第一个 iteration 采集直接
        # FileNotFoundError（本 run 踩过）。刚发布的文件永不删。
        olds = sorted(glob.glob(os.path.join(weights_dir, "w_*.pt")),
                      key=lambda p: os.path.getmtime(p))
        for old in olds[:-keep]:
            if os.path.abspath(old) == os.path.abspath(path):
                continue
            try:
                os.remove(old)
            except OSError:
                pass
        return path

    if pool is not None:
        _publish_weights(int(trainer.updates))

    pipeline_on = bool(int(args.pipeline)) and pool is not None
    if int(args.pipeline) and pool is None:
        print("[warn] --pipeline 需要 --processes>1，已退回串行", flush=True)
    if pipeline_on:
        # 实测：learner 与 actor 共用一张卡时两者互相拖慢（collect +42%、PPO +27%），
        # 流水线整体只快 19%；把 learner 放到独立卡可到 +44%。
        learner_idx = None
        if str(args.device).startswith("cuda"):
            learner_idx = int(str(args.device).split(":")[1]) if ":" in str(args.device) else 0
        actor_gpus = [int(x) for x in str(args.gpus).split(",") if x.strip()]
        if learner_idx is not None and learner_idx in actor_gpus:
            suggest = ",".join(str(g) for g in actor_gpus if g != learner_idx) or "（无其它卡）"
            print(f"[warn] 流水线开启但 learner 与 actor 共用 GPU{learner_idx}："
                  f"实测会互抢（2,552 vs 隔离后 3,100 dec/s）。"
                  f"建议 --gpus {suggest} 或 --device cuda:<空闲卡>。", flush=True)

    def _collect_for(idx: int, wv: Optional[int] = None,
                     wp: Optional[str] = None
                     ) -> Tuple[Any, Dict[str, Any], CollectConfig, float, Any]:
        # p ramp：按 iteration 下标求值（空 schedule = 固定 --mirror-p）。
        _mp = float(args.mirror_p)
        if str(args.mirror_p_ramp).strip():
            _mp = float(ramp_p(int(idx), str(args.mirror_p_ramp)))
        # 经济课程：按**已累计 decisions** 求本 iteration 的金币倍数（默认 none -> 1.0）
        _gold_mult = gold_mult_at(
            cum_decisions, stage=_curr_cfg["curriculum_stage"],
            mult=_curr_cfg["curriculum_gold_mult"],
            anneal_decisions=_curr_cfg["curriculum_anneal_decisions"])
        # 对手强度课程：按**已累计 learner decisions** 求本 iteration 生效的
        # seats/p/sample（空 spec -> 原样返回 CLI 值，逐位等价）。
        _hb_state = board_ramp.state(cum_decisions)
        # 动态课程（--dyn-curriculum 1）覆盖阶段式的 seats/p；其余（sample/quantile）不变。
        _hb_seats, _hb_p = int(_hb_state.seats), float(_hb_state.p)
        if int(args.dyn_curriculum) > 0:
            _hb_seats = int(_dyn["seats"])
            _hb_p = float(args.dyn_p)
        c_cfg = CollectConfig(
            games=int(args.games), seed=int(args.seed) + idx * 1000,
            opponent=str(args.opponent), behavior=str(args.behavior),
            max_actions_per_turn=int(args.max_actions_per_turn),
            max_steps=int(args.max_steps), fast_act=bool(int(args.fast_act)),
            lockstep=bool(int(args.lockstep)),
            move_guard=bool(int(args.move_guard)),
            move_cap=int(args.move_cap),
            archetype_bias_coef=float(args.archetype_bias_coef),
            archetype_min_prob=float(args.archetype_min_prob),
            archetype_cache=bool(int(args.archetype_cache)),
            archetype_table=str(args.archetype_table),
            archetype_model=str(args.archetype_model),
            collect_discover_bias=float(args.collect_discover_bias),
            collect_triple_bias=float(args.collect_triple_bias),
            collect_chain_buy_bias=float(getattr(args, "collect_chain_buy_bias", 0.0) or 0.0),
            collect_chain_ids=str(getattr(args, "collect_chain_ids", "") or ""),
            collect_reroll_bias_t8t9=float(getattr(args, "collect_reroll_bias_t8t9", 0.0) or 0.0),
            record_logp_mu=int(args.record_logp_mu),
            move_repeat_limit=int(args.move_repeat_limit),
            library_pool=str(args.library_pool), library_p=float(args.library_p),
            trajectory_pool=str(args.trajectory_pool), trajectory_p=float(args.trajectory_p),
            mirror_snaps=str(args.mirror_snaps), mirror_seats=int(args.mirror_seats),
            mirror_p=_mp, mirror_sample=str(args.mirror_sample),
            mirror_p_ramp=str(args.mirror_p_ramp),
            mirror_seat_random=bool(int(args.mirror_seat_random)),
            human_boards=str(args.human_boards),
            human_board_p=_hb_p,
            human_board_seats=_hb_seats,
            human_board_sample=str(_hb_state.sample),
            human_board_set_tier=bool(int(args.human_board_set_tier)),
            human_board_fidelity=str(args.human_board_fidelity),
            human_board_fast_inject=bool(int(args.human_board_fast_inject)),
            frozen_opponent=str(args.frozen_opponent),
            frozen_seats=int(args.frozen_seats),
            rust_collector=bool(int(args.rust_collector)),
            rc_threads=int(args.rc_threads), leaf_amp=str(args.leaf_amp),
            leaf_compile=bool(int(args.leaf_compile)),
            leaf_wait_ms=float(args.leaf_wait_ms),
            # 动作序列辅助任务：只在启用时让采集/打包侧产出 seq_target（默认 False）
            seq_aux=bool(seq_enabled),
            # 势函数奖励塑形（默认 coef=0 -> 零影响）
            shaping_coef=float(args.shaping_coef),
            shaping_gamma=args.shaping_gamma,
            shaping_w_str=float(args.shaping_w_str),
            shaping_w_tier=float(args.shaping_w_tier),
            shaping_mode=str(args.shaping_mode),
            shaping_tier_bonus=str(args.shaping_tier_bonus),
            # 等级进度奖励（默认 coef=0 -> 零影响）
            tier_target_coef=float(args.tier_target_coef),
            tier_spread=bool(int(args.tier_spread)),
            tier_penalty=float(args.tier_penalty),
            tier_bonus=float(args.tier_bonus),
            tier_target_table=str(args.tier_target_table),
            # 经济课程（默认 none+1.0 -> 采集侧不碰金币，逐位等价）
            curriculum_stage=str(_curr_cfg["curriculum_stage"]),
            curriculum_gold_mult=float(_gold_mult),
            # 在线缩放教师 / 过程价值标签（默认 False -> 不查教师、不读日志）
            teacher_bc=bool(float(args.teacher_bc_coef) > 0.0),
            process_value=bool(float(args.process_value_coef) > 0.0),
            # 搜索作为行为策略（默认 eps=0 -> 不构造 mixer、零开销）
            behavior_mix_eps=float(args.behavior_mix_eps),
            behavior_mix_when=str(args.behavior_mix_when),
            behavior_mix_max_per_turn=int(args.behavior_mix_max_per_turn),
            behavior_mix_topk=int(args.behavior_mix_topk),
            behavior_mix_turns=int(args.behavior_mix_turns),
            behavior_mix_max_ms=float(args.behavior_mix_max_ms),
            behavior_mix_exact=int(args.behavior_mix_exact),
            # 长强局加权（默认 none -> 采集/建批逐位等价旧路径）
            game_weight_mode=str(args.game_weight_mode),
            game_weight_alpha=float(args.game_weight_alpha),
            game_weight_beta=float(args.game_weight_beta),
            game_weight_floor=float(args.game_weight_floor),
            game_weight_cap=float(args.game_weight_cap))
        t_c = time.time()
        if pool is not None:
            batch, collect_meta = pool.collect(
                c_cfg, int(args.games), return_records=True, progress=not pipeline_on,
                seed=int(c_cfg.seed), gamma=float(p_cfg.gamma), lam=float(args.lam),
                adv_estimator=str(args.adv_estimator),
                power_alpha=float(args.power_alpha),
                power_kappa=float(args.power_kappa),
                power_normalize=bool(int(args.power_normalize)),
                power_cutoff=int(args.power_cutoff),
                credit_timebase=str(args.credit_timebase),
                rank_utility_coef=float(args.rank_utility_coef),
                terminal_strength_coef=float(args.terminal_strength_coef),
                game_weight_mode=str(args.game_weight_mode),
                game_weight_alpha=float(args.game_weight_alpha),
                game_weight_beta=float(args.game_weight_beta),
                game_weight_floor=float(args.game_weight_floor),
                game_weight_cap=float(args.game_weight_cap),
                weights_version=(published["version"] if wv is None else wv),
                weights_path=(published["path"] if wp is None else wp))
        elif args.workers > 1:
            batch, collect_meta = collect_ppo_batch_parallel(
                model, c_cfg, workers=int(args.workers),
                search_fn=search_fn, search_config=search_cfg,
                eval_fn=evaluator, device=str(args.device),
                seed=int(args.seed) + idx * 1000, gamma=float(p_cfg.gamma),
                lam=float(args.lam),
                norm_mean=norm_mean, norm_std=norm_std, progress=True,
                adv_estimator=str(args.adv_estimator),
                power_alpha=float(args.power_alpha),
                power_kappa=float(args.power_kappa),
                power_normalize=bool(int(args.power_normalize)),
                power_cutoff=int(args.power_cutoff),
                credit_timebase=str(args.credit_timebase),
                rank_utility_coef=float(args.rank_utility_coef),
                terminal_strength_coef=float(args.terminal_strength_coef))
        else:
            batch, collect_meta = collect_ppo_batch(
                model, c_cfg, search_fn=search_fn, search_config=search_cfg,
                eval_fn=evaluator, device=str(args.device),
                seed=int(args.seed) + idx * 1000, gamma=float(p_cfg.gamma),
                lam=float(args.lam),
                norm_mean=norm_mean, norm_std=norm_std, progress=True,
                adv_estimator=str(args.adv_estimator),
                power_alpha=float(args.power_alpha),
                power_kappa=float(args.power_kappa),
                power_normalize=bool(int(args.power_normalize)),
                power_cutoff=int(args.power_cutoff),
                credit_timebase=str(args.credit_timebase),
                rank_utility_coef=float(args.rank_utility_coef),
                terminal_strength_coef=float(args.terminal_strength_coef))
        return batch, collect_meta, c_cfg, time.time() - t_c, _hb_state

    def _pre_ratio(batch: Any, n: int = 2048) -> float:
        """用当前参数对 batch 抽样算 mean ratio（流水线的越策略守卫）。"""
        total = len(batch.actions)
        idx = np.arange(total)
        if total > n:
            idx = np.random.default_rng(0).choice(total, size=n, replace=False)
        dev = torch.device(args.device)
        x = torch.from_numpy(np.ascontiguousarray(batch.features[idx])).to(dev)
        c = torch.from_numpy(np.ascontiguousarray(batch.cards[idx].astype(np.int64))).to(dev)
        m = torch.from_numpy(np.ascontiguousarray(batch.masks[idx].astype(bool))).to(dev)
        a = torch.from_numpy(np.ascontiguousarray(batch.actions[idx].astype(np.int64))).to(dev)
        old = torch.from_numpy(
            np.ascontiguousarray(batch.old_logprobs[idx].astype(np.float32))).to(dev)
        with torch.no_grad():
            logits, _r, _s = split_model_outputs(forward_model(model, x, c, m))
            logp = masked_log_softmax_torch(logits, m).gather(1, a.unsqueeze(1)).squeeze(1)
            ratio = torch.exp(logp - old)
        return float(ratio.mean())

    t0 = time.time()
    deadline = t0 + float(args.minutes) * 60.0
    cum_decisions = 0
    _eval_every = int(args.eval_every_decisions)
    _eval_first = int(getattr(args, "eval_first_decisions", 0) or 0)
    next_eval = ((_eval_first if _eval_first > 0 else _eval_every)
                 if _eval_every > 0 else 10 ** 18)
    i = int(start_i)
    end_i = (int(start_i) + int(args.iterations)) if int(args.iterations) > 0 else 0
    last_len = 0.0
    executor = ThreadPoolExecutor(max_workers=1) if pipeline_on else None
    pending = None
    #: critic 预热只在**第一个 iteration** 做一次（--value-warmup-iters>0 时）
    _value_warmed = False
    #: 动态课程状态（--dyn-curriculum 1 时生效；默认 seats=0 表示不覆盖）
    _dyn: Dict[str, Any] = {"seats": int(args.dyn_start_seats) if int(args.dyn_curriculum) > 0 else 0,
                            "last_s15": None, "hold_until": 0.0, "history": []}
    _vwarm: Optional[Dict[str, Any]] = None
    if executor is not None:
        pending = executor.submit(_collect_for, i, published["version"], published["path"])
        print(f"[pipeline] on：collect(k+1) 与 update(k) 并行；"
              f"每 batch 版本钉死（lag<=1）；guard={args.pipeline_guard}", flush=True)

    try:
        while time.time() < deadline:
            if end_i > 0 and i >= end_i:
                break
            if float(args.stop_at_decisions) > 0 and cum_decisions >= float(args.stop_at_decisions):
                print(f"[loop] decisions {cum_decisions} >= {int(args.stop_at_decisions)}; stop",
                      flush=True)
                break
            if last_len > 0 and (deadline - time.time()) < max(60.0, last_len):
                print("[loop] remaining time < last iteration; stop", flush=True)
                break
            if eval_stop.is_set():
                # 异步评测结果到达后置 flag：只在下个 iteration 边界停，已完成的 iteration
                # 一定保留（history/snapshot 都已落盘）。
                print(f"[loop] eval stop requested ({eval_state['stop_reason']}); "
                      f"stop at iteration boundary", flush=True)
                if pending is not None:
                    pending.cancel()
                break
            _history_s_prev = locals().get("_history_s", 0.0)
            iter_start = time.time()
            _tl = {"t_iter_start": time.monotonic()}
            _reload_s = 0.0

            if pending is not None:
                batch, collect_meta, c_cfg, _collect_s, _hb_state = pending.result()
                pending = None
            else:
                batch, collect_meta, c_cfg, _collect_s, _hb_state = _collect_for(i)
            _tl["t_collect_done"] = time.monotonic()
            # 阶段计时（仅 HSBG_PROF_STAGES=1 时打印；默认零输出、零语义影响）
            _st = {"t0": _tl["t_collect_done"]}

            errs = batch.validate()
            if errs:
                print(f"[error] batch invalid: {errs}", file=sys.stderr)
                return 3
            _st["validate"] = time.monotonic()

            # ── 自定义奖励（--upgrade-reward / --win-only-reward / --strength-reward-coef）
            # 必须放在 update 之前：改 rewards 后整批重算 advantages/returns。
            # 三者默认全 0 ⇒ 本块不执行 ⇒ 逐位等价旧路径。
            _rw: Optional[Dict[str, Any]] = None
            # 复利结构辅助 BC 标签（默认两系数 0 -> 不写标签、不进 batch）
            if (float(args.discover_bc_coef) > 0.0 or float(args.triple_bc_coef) > 0.0
                    or float(getattr(args, "upgrade_curve_bc_coef", 0.0) or 0.0) > 0.0):
                try:
                    _bc_stat = _attach_replication_bc_labels(
                        batch,
                        want_upgrade=(float(getattr(args, "upgrade_curve_bc_coef", 0.0)
                                            or 0.0) > 0.0),
                        upgrade_turns=str(getattr(args, "upgrade_curve_bc_turns",
                                                  "2,5,7,9") or "2,5,7,9"))
                    print(f"[rep-bc] labels: discover={_bc_stat['discover_states']} "
                          f"triple={_bc_stat['triple_states']} pair={_bc_stat['pair_states']} "
                          f"upgrade={_bc_stat.get('upgrade_states', 0)}", flush=True)
                    _rw = _bc_stat
                except BaseException as _exc:  # noqa: BLE001 - 标不出来也照常训练
                    print(f"[rep-bc] 标签生成失败（跳过）: {_exc!r}", flush=True)
                _st["rep_bc"] = time.monotonic()
            if (float(args.upgrade_reward) > 0.0 or float(args.win_only_reward) > 0.0
                    or float(args.strength_reward_coef) > 0.0
                    or float(args.golden_reward) > 0.0 or float(args.golden_t5_reward) > 0.0
                    or float(args.amp_board_reward) > 0.0
                    or float(args.engine_board_reward) > 0.0
                    or float(args.survive_t12_reward) > 0.0
                    or float(args.t5plus_stat_reward) > 0.0
                    or float(args.tier_timing_reward) > 0.0
                    or float(args.cheap_buy_penalty) > 0.0
                    or float(args.t5plus_buff_reward) > 0.0
                    or float(args.tier_mix_reward) > 0.0
                    or float(args.lowtier_stat_penalty) > 0.0
                    or float(args.comp_fit_coef) > 0.0
                    or float(args.comp_fit_t9_bonus) > 0.0
                    or float(args.comp_trinket_coef) > 0.0
                    or float(args.t1p_coef) > 0.0
                    or float(args.t1s_coef) > 0.0
                    or float(getattr(args, "save_up_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "late_growth_coef", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "late_shadow_coef", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "late_log_ratio_coef", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "late_alive_bonus", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "late_death_penalty", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "churn_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "hightier_buy_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "hero_power_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "early_upgrade_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "churn_pair_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "roll_pair_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "tier_early_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "chain_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "chain2_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "late_rel_growth_coef", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "final_20k_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "final_3500_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "scaling_value_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "chain_early_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "t9_chain_target_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "roll_bonus_t8t9", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "chain_any_reward", 0.0) or 0.0) > 0.0
                    or float(getattr(args, "retain_growth_coef", 0.0) or 0.0) > 0.0):
                _rw = _apply_custom_rewards(
                    batch, upgrade_w=float(args.upgrade_reward),
                    win_w=float(args.win_only_reward),
                    strength_c=float(args.strength_reward_coef),
                    strength_from_turn=float(getattr(args, "strength_from_turn", 0.0) or 0.0),
                    golden_w=float(args.golden_reward),
                    golden_t5_w=float(args.golden_t5_reward),
                    amp_board_w=float(args.amp_board_reward),
                    engine_board_w=float(args.engine_board_reward),
                    survive_t12_w=float(args.survive_t12_reward),
                    t5plus_stat_w=float(args.t5plus_stat_reward),
                    tier_timing_w=float(args.tier_timing_reward),
                    cheap_buy_p=float(args.cheap_buy_penalty),
                    t5plus_buff_w=float(args.t5plus_buff_reward),
                    tier_mix_w=float(args.tier_mix_reward),
                    lowtier_stat_p=float(args.lowtier_stat_penalty),
                    comp_fit_c=float(args.comp_fit_coef),
                    comp_fit_t9_bonus=float(args.comp_fit_t9_bonus),
                    comp_trinket_c=float(args.comp_trinket_coef),
                    t1p_coef=float(args.t1p_coef),
                    t1s_coef=float(args.t1s_coef),
                    save_up_w=float(getattr(args, "save_up_reward", 0.0) or 0.0),
                    late_growth_coef=float(getattr(args, "late_growth_coef", 0.0) or 0.0),
                    late_shadow_coef=float(getattr(args, "late_shadow_coef", 0.0) or 0.0),
                    late_log_ratio_coef=float(getattr(args, "late_log_ratio_coef", 0.0) or 0.0),
                    late_alive_bonus=float(getattr(args, "late_alive_bonus", 0.0) or 0.0),
                    late_death_penalty=float(getattr(args, "late_death_penalty", 0.0) or 0.0),
                    late_shadow_ratio=float(getattr(args, "late_shadow_ratio", 3.15) or 3.15),
                    churn_w=float(getattr(args, "churn_reward", 0.0) or 0.0),
                    hightier_w=float(getattr(args, "hightier_buy_reward", 0.0) or 0.0),
                    hero_power_w=float(getattr(args, "hero_power_reward", 0.0) or 0.0),
                    early_upgrade_w=float(getattr(args, "early_upgrade_reward", 0.0) or 0.0),
                    churn_sell_cap=float(getattr(args, "churn_sell_cap", 12.0) or 12.0),
                    churn_roll_cap=float(getattr(args, "churn_roll_cap", 8.0) or 8.0),
                    churn_pair_w=float(getattr(args, "churn_pair_reward", 0.0) or 0.0),
                    tier_early_w=float(getattr(args, "tier_early_reward", 0.0) or 0.0),
                    chain_w=float(getattr(args, "chain_reward", 0.0) or 0.0),
                    chain_complete_bonus=float(getattr(args, "chain_complete_bonus", 0.5) or 0.5),
                    chain2_w=float(getattr(args, "chain2_reward", 0.0) or 0.0),
                    late_rel_growth_coef=float(getattr(args, "late_rel_growth_coef", 0.0) or 0.0),
                    final_20k_w=float(getattr(args, "final_20k_reward", 0.0) or 0.0),
                    final_3500_w=float(getattr(args, "final_3500_reward", 0.0) or 0.0),
                    scaling_value_w=float(getattr(args, "scaling_value_reward", 0.0) or 0.0),
                    scaling_value_model=str(getattr(args, "scaling_value_model",
                                                     "data/scaling_value/logit.npz")),
                    chain_early_w=float(getattr(args, "chain_early_reward", 0.0) or 0.0),
                    t9_chain_target_w=float(getattr(args, "t9_chain_target_reward", 0.0) or 0.0),
                    roll_bonus_t8t9=float(getattr(args, "roll_bonus_t8t9", 0.0) or 0.0),
                    chain_any_w=float(getattr(args, "chain_any_reward", 0.0) or 0.0),
                    retain_growth_coef=float(getattr(args, "retain_growth_coef", 0.0) or 0.0),
                    roll_pair_w=float(getattr(args, "roll_pair_reward", 0.0) or 0.0),
                    gamma=float(args.gamma), lam=float(args.lam))
                _st["rewards"] = time.monotonic()

            batch_version = int(collect_meta.get("policy_version", -1))
            if batch_version < 0:  # 非 pool 路径
                batch_version = int(trainer.updates)
            lag = int(trainer.updates) - batch_version
            if lag < 0 or lag > 1:
                raise RuntimeError(
                    f"流水线滞后异常：batch_version={batch_version} "
                    f"trainer_version={trainer.updates} lag={lag}（上限 1）")

            # 先发起下一轮采集（用当前已发布权重），再跑 update —— 这是流水的关键顺序
            if executor is not None and (end_i <= 0 or i + 1 < end_i) \
                    and (deadline - time.time()) > 60.0:
                pending = executor.submit(_collect_for, i + 1,
                                          published["version"], published["path"])
            _st["issue"] = time.monotonic()

            pre_ratio = 1.0
            guard_tripped = False
            if pipeline_on and lag >= 1:
                pre_ratio = _pre_ratio(batch)
                if not (0.8 <= pre_ratio <= 1.25):
                    guard_tripped = True
                    print(f"[pipeline] ratio guard tripped: pre_ratio_mean={pre_ratio:.3f} "
                          f"(lag={lag}); guard={args.pipeline_guard}", flush=True)

            trainer.config.anchor_coef = (
                float(args.anchor_beta) if i < int(args.anchor_iterations)
                else float(args.anchor_beta_tail))
            if seq_enabled:
                # 权重 ramp：按**已累计** decisions 的进度插值（本 iteration 生效）
                trainer.config.seq_coef = float(seq_schedule.coef(cum_decisions))
                if getattr(batch, "seq_target", None) is None and i == start_i:
                    print("[warn] seq 辅助任务已开启但批次没有 seq_target"
                          "（--rust-collector 路径暂不产出标签）-> 本批次 seq_loss=0",
                          flush=True)
            if bc_enabled:
                # BC 系数 ramp：与 seq 同一进度口径（累计 decisions）
                trainer.config.bc_coef = float(bc_schedule.coef(cum_decisions))
            # ── critic 预热（--value-warmup-iters>0；默认 0 完全跳过）─────────────
            # 放在**第一个 iteration 的 update 之前**：此时批次来自（预热的）策略、还没被
            # 随机 critic 的噪声梯度动过，用它校准 critic 头最干净。
            # `--value-warmup-every N>0` 时每 N 个 iteration 再重热一次：实测一次预热的效果
            # 会被后续 PPO 的 trunk 漂移抹掉（rank-CE 0.90→2.4），长训练需要周期性重热。
            _vw_due = False
            if int(args.value_warmup_iters) > 0:
                if not _value_warmed:
                    _value_warmed = True
                    _vw_due = True
                elif (int(args.value_warmup_every) > 0 and i > int(start_i)
                      and (i % int(args.value_warmup_every)) == 0):
                    _vw_due = True
            if _vw_due:
                _vwarm = _value_warmup(
                    trainer, batch,
                    iters=int(args.value_warmup_iters),
                    lr=float(args.value_warmup_lr),
                    minibatch=int(args.value_warmup_minibatch),
                    seed=int(args.seed))
            # 辅助 BC 系数 warmup（guard 在 PPO epoch 内；独立 scale 不被 warmup 重置）
            _bc_base_d = float(args.discover_bc_coef)
            _bc_base_t = float(args.triple_bc_coef)
            if (_bc_base_d > 0.0 or _bc_base_t > 0.0):
                _wu = float(getattr(args, "bc_warmup_decisions", 0.0) or 0.0)
                _frac = 1.0 if _wu <= 0.0 else min(1.0, float(cum_decisions) / _wu)
                trainer.config.discover_bc_coef = _bc_base_d * _frac
                trainer.config.triple_bc_coef = _bc_base_t * _frac
                if int(i) % 20 == 0:
                    print(f"[bc-warmup] cum={int(cum_decisions)} frac={_frac:.3f} "
                          f"coef={trainer.config.discover_bc_coef:.3g}", flush=True)
            _t_ppo = time.time()
            _tl["t_ppo_start"] = time.monotonic()
            if os.environ.get("HSBG_PROF_STAGES"):
                _keys = [k for k in ("validate", "rep_bc", "rewards", "issue")
                         if k in _st]
                _prev = _st["t0"]
                _parts = []
                for _k in _keys:
                    _parts.append(f"{_k}={_st[_k] - _prev:.3f}")
                    _prev = _st[_k]
                _parts.append(f"pre_update={_tl['t_ppo_start'] - _prev:.3f}")
                print(f"[stages] iter {i} " + " ".join(_parts), flush=True)
            stats = trainer.update(batch)
            if _rw is not None:
                stats["custom_rewards"] = dict(_rw)
            if _vwarm is not None:
                stats["value_warmup"] = dict(_vwarm)
                _vwarm = None
            # 塑形可观测性：history.jsonl 的 ppo 段带系数与实际 shaping 奖励均值。
            _cmeta = collect_meta.get("collect") if isinstance(collect_meta, dict) else None
            if not isinstance(_cmeta, dict):
                _cmeta = collect_meta if isinstance(collect_meta, dict) else {}
            stats["shaping_coef"] = float(args.shaping_coef)
            stats["shaping_gamma"] = float(shape_gamma)
            stats["shaping_gamma_aligned"] = bool(shape_aligned)
            stats["reward_shaping_mean"] = float(
                _cmeta.get("reward_shaping_mean", 0.0) or 0.0)
            stats["reward_shaping_bias_sum"] = float(
                _cmeta.get("reward_shaping_bias_sum", 0.0) or 0.0)
            # 优势标准差（PPOBatch 已算 advantage_std；history 里此前只有 adv_mean）
            stats["adv_std"] = float(np.std(batch.advantages))
            # 等级进度奖励可观测性（默认关闭时全为 0；history 字段名固定）
            stats["tier_target_coef"] = float(args.tier_target_coef)
            stats["tier_hits"] = int(_cmeta.get("tier_hits", 0) or 0)
            stats["tier_misses"] = int(_cmeta.get("tier_misses", 0) or 0)
            stats["tier_bonus_sum"] = float(_cmeta.get("tier_bonus_sum", 0.0) or 0.0)
            _ppo_s = time.time() - _t_ppo
            _tl["t_ppo_done"] = time.monotonic()

            # 发布新权重（供下一轮 collect 的 *下一次* 使用；lag 恒为 1）
            if pool is not None:
                _publish_weights(int(trainer.updates))

            slim = slim_collect(collect_meta)
            # ── 对手强度课程：本 iter 实际生效值 + 自适应门控 ──────────────────
            # 注意：``_hb_state`` 由 ``_collect_for`` 在提交采集时求值，pipeline 模式下
            # 最多滞后 1 个 iteration（与 batch 版本滞后同源）；history 记录的就是它。
            _decisions_i = int(slim.get("decisions", 0) or 0)
            _cum_after = int(cum_decisions) + _decisions_i
            _ramp_events: List[Dict[str, Any]] = []
            _ramp_gate: Optional[Dict[str, Any]] = None
            if board_ramp.enabled and int(args.ramp_adaptive):
                _quality = _read_quality_json(str(args.ramp_quality_json))
                _ramp_gate = ramp_progress_metrics(
                    getattr(batch, "turns", None), getattr(batch, "game_ids", None),
                    collect_meta=collect_meta, quality=_quality)
                _ramp_events = board_ramp.observe(i, _cum_after, _ramp_gate)
                for _ev in _ramp_events:
                    print(f"[ramp] iter {i} gate event: {_ev}", flush=True)
            rec = {"iter": i, "collect": slim, "ppo": stats,
                   "pipeline": {"enabled": pipeline_on, "lag": int(lag),
                                "batch_version": int(batch_version),
                                "pre_ratio_mean": round(float(pre_ratio), 4),
                                "guard_tripped": bool(guard_tripped)},
                   "profile": {"reload_s": round(_reload_s, 3),
                               "collect_s": round(_collect_s, 3),
                               "ppo_s": round(_ppo_s, 3),
                               "build_batch_s": round(float(slim.get("build_batch_s", 0.0)), 3),
                               "parent_read_s": round(float(slim.get("parent_read_s", 0.0)), 3),
                               "records_mb": round(float(slim.get("records_bytes", 0)) / 1e6, 1),
                               "history_prev_s": round(float(_history_s_prev), 3)},
                   "batch_server": (dict(batch_server.stats) if batch_server is not None else None),
                   "seconds": time.time() - t0}
            rec["human_board"] = board_ramp_history(
                _hb_state, spec=str(args.human_board_ramp),
                quantile_spec=str(args.human_board_quantile_ramp),
                mode=str(args.ramp_mode), adaptive=bool(int(args.ramp_adaptive)),
                events=_ramp_events)
            # 平铺三键：history.jsonl 里一眼能查「本 iter 实际生效值」
            rec["human_board_seats"] = int(_hb_state.seats)
            rec["human_board_p"] = round(float(_hb_state.p), 6)
            rec["human_board_sample"] = str(_hb_state.sample)
            if _ramp_gate is not None:
                rec["ramp_gate"] = dict(
                    _ramp_gate, events=list(_ramp_events),
                    window=board_ramp.window_summary())
            if problem_pool is not None:
                # 题池过滤口径（默认 0/空 -> dropped 全 0）：池大小 / 按 delta 丢 /
                # 按 turn 丢，与 ppo 段的 problem_pool_* 同源
                rec["problems"] = dict(problem_pool.filter_report)
            # 经济课程可观测性（默认关闭时也写，字段固定：stage/mult/progress）
            _curr_prog = float(anneal_progress(
                cum_decisions, _curr_cfg["curriculum_anneal_decisions"]))
            rec["curriculum_stage"] = str(_curr_cfg["curriculum_stage"])
            rec["curriculum_gold_mult"] = round(
                float(c_cfg.curriculum_gold_mult), 6)
            rec["curriculum_anneal_progress"] = round(_curr_prog, 6)
            rec["curriculum"] = {
                "stage": str(_curr_cfg["curriculum_stage"]),
                "gold_mult": round(float(c_cfg.curriculum_gold_mult), 6),
                "anneal_progress": round(_curr_prog, 6),
                "decisions": int(cum_decisions),
            }
            history.append(rec)
            print(f"[iter {i}] ts={time.strftime('%H:%M:%S')} samples={len(batch)} "
                  f"updates={stats['trainer_updates']} "
                  f"lr={stats['lr']:.3g} total={stats['epochs'][-1]['total']:.4f}"
                  + (f" lag={lag} ratio={pre_ratio:.3f}" if pipeline_on else "")
                  + (f" seq={stats.get('seq_loss', 0.0):.4f}"
                     f" seq_coef={stats.get('seq_coef', 0.0):.4g}" if seq_enabled else "")
                  + (f" bc={stats.get('bc_loss', 0.0):.4f}"
                     f" bc_type={stats.get('bc_type_loss', 0.0):.4f}"
                     f" bc_card={stats.get('bc_card_loss', 0.0):.4f}"
                     f" bc_coef={stats.get('bc_coef', 0.0):.4g}"
                     f" bc_samples={stats.get('bc_samples', 0.0):.0f}"
                     if bc_enabled else "")
                  + (f" dpo={stats['dpo_loss']:.4f}"
                     f" dpo_acc={stats['dpo_accept_rate']:.3f}"
                     f" dpo_coef={stats['dpo_coef']:.4g}"
                     f" dpo_n={stats['dpo_samples']:.0f}"
                     if dpo_enabled and "dpo_loss" in stats else "")
                  + (f" pbc={stats['problem_bc_loss']:.4f}"
                     f" pbc_top1={stats.get('problem_bc_top1_acc', 0.0):.3f}"
                     if _problem_enabled and "problem_bc_loss" in stats else "")
                  + (f" saux={stats['strength_aux_loss']:.4f}"
                     f" s_mse={stats.get('strength_mse', 0.0):.4f}"
                     f" s_bce={stats.get('strength_bce', 0.0):.4f}"
                     if _strength_enabled and "strength_aux_loss" in stats else "")
                  + (f" hb={int(_hb_state.seats)}s/p{float(_hb_state.p):.2f}"
                     f"/{_hb_state.sample}/b{int(_hb_state.band)}"
                     if board_ramp.enabled else "")
                  + (f" goldx={c_cfg.curriculum_gold_mult:g}"
                     if str(_curr_cfg["curriculum_stage"]) != "none" else "")
                  + (f" teach={stats['teacher_bc_loss']:.4f}"
                     f" teach_n={stats.get('teacher_samples', 0.0):.0f}"
                     if "teacher_bc_loss" in stats else "")
                  + (f" proc={stats['process_value_loss']:.4f}"
                     f" proc_n={stats.get('process_samples', 0.0):.0f}"
                     if "process_value_loss" in stats else ""),
                  flush=True)

            # 版本化快照：trainer 为权威，model 为导出；manifest 最后原子发布
            ver = int(trainer.updates)
            do_snap = (int(args.snapshot_every) <= 1) or ((i % int(args.snapshot_every)) == 0)
            if do_snap:
                snap = os.path.join(args.out, "snapshots", f"step_{ver:06d}")
                os.makedirs(snap, exist_ok=True)
                trainer.save(os.path.join(snap, "trainer.pt"))
                ckpt = os.path.join(snap, "model.pt")
                tmp_ckpt = ckpt + ".tmp"
                save_checkpoint(model, tmp_ckpt,
                                meta={**meta, "arch": arch, "trainer_updates": ver},
                                norm_mean=norm_mean, norm_std=norm_std)
                os.replace(tmp_ckpt, ckpt)
                trainer.save(os.path.join(args.out, "trainer.pt"))
                ckpt_flat = os.path.join(args.out, "model.pt")
                save_checkpoint(model, ckpt_flat + ".tmp",
                                meta={**meta, "arch": arch, "trainer_updates": ver},
                                norm_mean=norm_mean, norm_std=norm_std)
                os.replace(ckpt_flat + ".tmp", ckpt_flat)
                manifest = {"version": ver, "trainer": os.path.join(snap, "trainer.pt"),
                            "model": os.path.join(snap, "model.pt"),
                            "arch": arch, "seed": int(args.seed),
                            "elapsed_s": time.time() - t0,
                            "history_len": len(history)}
                with open(os.path.join(args.out, "latest.json.tmp"), "w",
                          encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
                os.replace(os.path.join(args.out, "latest.json.tmp"),
                           os.path.join(args.out, "latest.json"))
                keep = int(args.keep_snapshots)
                if keep > 0:
                    snap_root = os.path.join(args.out, "snapshots")
                    olds = sorted(d for d in os.listdir(snap_root)
                                  if d.startswith("step_")
                                  and os.path.isdir(os.path.join(snap_root, d)))
                    for d in olds[:-keep]:
                        shutil.rmtree(os.path.join(snap_root, d), ignore_errors=True)

            # history：追加一行（O(1)），不再全量重写
            _th0 = time.time()
            _tl["t_history_done"] = time.monotonic()
            rec["profile"]["timeline"] = dict(_tl)
            rec["profile"]["collect_timeline"] = slim.get("timeline")
            # history.jsonl 的 eval 段：bot 面板 mean_rank + human 面板
            # human_mean_rank（结果到达后写入后续 iteration；绘图见
            # scripts/plot_quality_curves.py）。
            _eval_seg = _eval_snapshot()
            if _eval_seg:
                rec["eval"] = _eval_seg
            append_record(history_path, to_jsonable(rec))
            if str(args.behavior_mix_report):
                # 混合行为策略的逐 iteration 统计（ε 命中率 / 搜索覆盖率 / KL(μ‖π)
                # / 采集侧搜索耗时 / PPO 侧 IS 权重与 ESS）；默认关闭时不落盘。
                _bm_c = (collect_meta.get("behavior_mix")
                         if isinstance(collect_meta, dict) else None) or {}
                _bm_p = (stats.get("behavior_mix") or {}) if isinstance(stats, dict) else {}
                append_record(str(args.behavior_mix_report), to_jsonable({
                    "iter": int(i),
                    "decisions": int(cum_decisions),
                    "updates": int(stats.get("trainer_updates", 0) or 0),
                    "collect_s": float(_collect_s),
                    "collect": _bm_c,
                    "ppo": _bm_p,
                }))
            _history_s = time.time() - _th0

            cum_decisions += int(slim.get("decisions", 0))
            if cum_decisions >= next_eval:
                if eval_runner is not None:
                    # 异步：只花 ~0.3s 存 ckpt + spawn；评测在 cuda:4 独立跑，主循环继续
                    if not eval_stop.is_set():
                        _submit_eval(cum_decisions)
                else:
                    _run_eval(cum_decisions)
                # 动态课程：在主循环里**同步**跑一次真实强度口径面板（5 席 p0.9，~2–3 min），
                # 按 t15 Σ 变化加/减席；结果写 out/dynamic_curriculum.json（默认关闭时不执行）。
                if int(args.dyn_curriculum) > 0:
                    _dyn_step(cum_decisions)
                while next_eval <= cum_decisions:
                    next_eval += int(args.eval_every_decisions)
            last_len = time.time() - iter_start
            i += 1

            if guard_tripped and str(args.pipeline_guard) == "abort":
                save_checkpoint(model, os.path.join(args.out, "model.pt"),
                                meta={**meta, "arch": arch,
                                      "trainer_updates": int(trainer.updates)},
                                norm_mean=norm_mean, norm_std=norm_std)
                print("[pipeline] guard=abort：已保存权重并退出（需要人工检查）", flush=True)
                return 4
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
        if batch_server is not None:
            batch_server.close()
        if pool is not None:
            pool.close()
        if eval_runner is not None:
            # 默认直接终止在跑的评测（不拖 wall）；--eval-drain 1 才等它落 history
            eval_runner.close(drain=bool(int(args.eval_drain)))

    # 收尾：导出最终模型（评测/续训都要用）
    try:
        save_checkpoint(model, os.path.join(args.out, "model.pt"),
                        meta={**meta, "arch": arch,
                              "trainer_updates": int(trainer.updates)},
                        norm_mean=norm_mean, norm_std=norm_std)
        trainer.save(os.path.join(args.out, "trainer.pt"))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] final save failed: {exc!r}", flush=True)
    summary = {"iterations": i, "updates": trainer.updates,
               "elapsed_s": time.time() - t0, "config": vars(args),
               "history_len": len(history),
               "evals": (eval_runner.results_snapshot() if eval_runner is not None
                         else evals),
               "pipeline": {"enabled": pipeline_on,
                            "lag_max_allowed": 1},
               "last_records": history[-5:]}
    if eval_runner is not None:
        summary["eval_async"] = eval_runner.stats()
        summary["evals_skipped"] = list(eval_runner.skipped)
    if eval_state["stop_reason"]:
        summary["eval_stop_reason"] = eval_state["stop_reason"]
    if board_ramp.enabled:
        # 对手强度课程：配置 + 收尾实际生效值 + 自适应事件（默认关闭时 summary 不变）
        summary["board_ramp"] = {
            **board_ramp.describe(),
            "final": board_ramp.state(cum_decisions).as_dict(),
            "events": list(board_ramp.events),
            "cum_decisions": int(cum_decisions),
        }
    if seq_enabled:
        # 动作序列辅助任务：ramp 终点与累计 decisions（默认关闭时 summary 不变）
        summary["seq"] = {**seq_schedule.describe(),
                          "coef_final": float(seq_schedule.coef(cum_decisions)),
                          "cum_decisions": int(cum_decisions)}
    if bc_enabled:
        summary["bc"] = {
            **bc_schedule.describe(),
            "coef_final": float(bc_schedule.coef(cum_decisions)),
            "cum_decisions": int(cum_decisions),
            "batch": int(args.bc_batch),
            "every": int(args.bc_every),
            "compile": bool(int(args.bc_compile)),
            "type_weight": float(args.bc_type_weight),
            "card_weight": float(args.bc_card_weight),
            "class_weights": dict(bc_class_weights),
            "card_head": bool(bc_card_head),
            "pool": (bc_pool_summary(bc_pool) if bc_pool is not None else None),
        }
    if dpo_enabled:
        # upgrade 子集 DPO：池规模/系数/周期，以及最终 DPO 接受率（=1-选 upgrade 比例）
        summary["dpo"] = {
            "coef": float(args.dpo_coef), "beta": float(args.dpo_beta),
            "batch": int(args.dpo_batch), "every": int(args.dpo_every),
            "samples_path": str(args.dpo_samples),
            "pool_samples": (int(len(dpo_pool)) if dpo_pool is not None else 0),
        }
    write_summary(os.path.join(args.out, "summary.json"), to_jsonable(summary))
    print(f"[done] iters={i} updates={trainer.updates} "
          f"elapsed={time.time()-t0:.0f}s -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
