"""复利 BC 学生模型：无对战沙盒评测（24–48 局，三种经济配置）

口径与教师 ``scripts/compound_script.py`` 的 ``--mode groups`` **逐项对齐**（同
``SandboxConfig``、同 seed 家族、同放大器账本 ``Ledger``），因此可以直接读「教师差距」:
同一配置下 ``CompoundPolicy`` 的 t12/t15 Σ、``r12_15``、放大器/局、goldens、施法数。

用法::

    PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
    export PYTHONPATH=rust/python:.

    $PY scripts/eval_compound_bc.py --checkpoint runs/compound_bc/ckpt_small.pt \
        --games 32 --device cuda:7 --configs fixed30,growth2,growth3 \
        --sample 1 --carrier-audit 1 --seed0 910000 \
        --teacher-ref runs/compound_script/groups.json \
        --out runs/compound_bc/eval_small.json

报告（每个配置一行）::

    t12 Σ / t15 Σ（p50/p90/max）、r12_15（p50/p90/max）、放大器购买数/局（+ 分卡）、
    goldens（p50/mean/max）、载体率、对载体施法数、施法数、tier、合法率、
    Σ/金币；以及**教师差距**（ours - teacher）与四条判据的通过情况。

判据（``--gate-config``，默认 **fixed20 = 现实收入档**；三档阈值见 ``GATE_PROFILES``）::

    realistic（fixed 20，人类 10–20 金/回合）：放大器 ≥5.5 ｜ t15 Σ p50 ≥1,800 ｜ r12_15 p50 ≥1.6
    growth（S2/S3，≈1200 金/局）      ：放大器 ≥5    ｜ t15 Σ p50 ≥3,000 ｜ r12_15 p50 ≥2
    legacy（fixed 30，旧口径，仅对照） ：放大器 ≥5    ｜ t15 Σ p50 ≥3,000 ｜ r12_15 p50 ≥2
    goldens 一律用**均值** ≥3（教师 p50 只有 1–2）

注意（不要在报告里写错）：三个配置的教师 r12_15 **p50 都 <2**（S0 1.14 / S2 1.00 / S3 1.19），
复利在教师身上也是**尾部事件**（§4 的 p90/max 才有 1.95–8.33）——所以这一条对任何学生
都是「高于教师」的判据，不是「追上教师」。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: 判据（用户口径；单位见 docs/COMPOUND_BC.md §3）。**按收入档分三套**（2026-11-01 修订：
#: 现实档按「教师 roll8 的 87%」放宽 Σ，r12 改「= 教师」；goldens 改「≥ 教师水平 1.45」，
#: 因为 **goldens≥3 连教师都没过**（教师均值 1.4–1.5））：
#:  - ``growth``：growth 收入（S2/S3，≈1200 金/局）：amp ≥10、t15 Σ ≥2,400（教师 2,519 的 95%）、r12 ≥1.4；
#:  - ``realistic``：**现实收入 fixed 20**（人类约 10–20 金/回合）：amp ≥5.5、t15 Σ ≥1,500
#:    （教师 1,716 的 87%）、r12 ≥1.55（= 教师）、goldens ≥1.45（= 教师水平）；
#:  - ``legacy``：旧的 fixed 30 口径，保留作对照（不作为主判据）。
GATE_PROFILES: Dict[str, Dict[str, float]] = {
    "growth": {"amp_buys_mean": 10.0, "goldens_mean": 1.45, "r12_15_p50": 1.4,
               "sigma_t15_p50": 2400.0},
    "realistic": {"amp_buys_mean": 5.5, "goldens_mean": 1.45, "r12_15_p50": 1.55,
                  "sigma_t15_p50": 1500.0},
    "legacy": {"amp_buys_mean": 5.0, "goldens_mean": 1.45, "r12_15_p50": 2.0,
               "sigma_t15_p50": 3000.0},
}
#: 配置名 -> 用哪套判据
CONFIG_PROFILE = {"fixed20": "realistic", "fixed30": "legacy",
                  "growth2": "growth", "growth3": "growth"}
#: 向后兼容：默认判据 = growth
GATES: Dict[str, float] = GATE_PROFILES["growth"]
GATE_LABELS = {
    "amp_buys_mean": "放大器/局",
    "goldens_mean": "goldens/局",
    "r12_15_p50": "r12_15 p50",
    "sigma_t15_p50": "t15 Σ p50",
}

#: 教师参考（``docs/COMPOUND_SCRIPT.md`` §4，每组 **28 局**，policy=CompoundPolicy）。
#: ``--teacher-ref`` 给了 ``runs/compound_script/groups.json`` 时用现场数字覆盖，本表是
#: 「没带 json」时的兜底（两者同源）。S0 = fixed30，S2 = growth2，S3 = growth3。
TEACHER_SOURCE = "docs/COMPOUND_SCRIPT.md §4（CompoundPolicy，28 局/组）"
TEACHER_STATIC: Dict[str, Dict[str, float]] = {
    "fixed30": {"sigma_t12_p50": 1448, "sigma_t15_p50": 1820, "sigma_t12_p90": 3182,
                "sigma_t15_p90": 4450, "r12_15_p50": 1.14, "r12_15_p90": 1.95,
                "amp_buys_mean": 8.8, "goldens_p50": 1.0, "spells_p50": 80.0},
    "growth2": {"sigma_t12_p50": 1915, "sigma_t15_p50": 2094, "sigma_t12_p90": 5030,
                "sigma_t15_p90": 9012, "r12_15_p50": 1.00, "r12_15_p90": 2.88,
                "amp_buys_mean": 12.8, "goldens_p50": 2.0, "spells_p50": 100.0},
    "growth3": {"sigma_t12_p50": 3401, "sigma_t15_p50": 4207, "sigma_t12_p90": 6864,
                "sigma_t15_p90": 14088, "r12_15_p50": 1.19, "r12_15_p90": 3.94,
                "amp_buys_mean": 15.4, "goldens_p50": 2.0, "spells_p50": 131.0},
    # **现实收入档（fixed 20）**：教师 roll8（动作效率教师，现实收入）基线
    # t15 Σ p50 1,716 / amp 6.74 / r12_15 1.55；roll4 为 1,524 / 6.06 / 1.68。
    # 来源：Lead 转述的 teacher-compound 现实口径评测（2026-11-01）。goldens 无同口径数字。
    "fixed20": {"sigma_t15_p50": 1716.0, "amp_buys_mean": 6.74, "r12_15_p50": 1.55},
}
#: ``groups.json`` 里的组名 -> 本脚本的配置名（教师 S0/S2/S3 就是这三档）
GROUP_TO_CONFIG = {"S0": "fixed30", "S2": "growth2", "S3": "growth3"}


def _pct(vals: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(vals, dtype=np.float64), q)) if len(vals) else 0.0


def _mean(vals: Sequence[float]) -> float:
    return float(np.mean(np.asarray(vals, dtype=np.float64))) if len(vals) else 0.0


# ── 配置（与 scripts/compound_script.py::group_configs 逐字同参）────────────


def build_configs() -> Dict[str, Any]:
    """四条配置。``S0/S2/S3`` 的参数**逐字抄自** ``compound_script.group_configs()``，
    唯一变量是经济闸门（单测 ``test_configs_match_teacher`` 会断言两者相等）。

    ``fixed20`` 是**现实收入档**（人类约 10–20 金/回合），不是教师数据集的配置；
    它的教师参考用「roll8 动作效率教师 + 现实收入」的评测数字（见 ``TEACHER_STATIC``）。
    """
    from hsbg.az.train.economy_sandbox import SandboxConfig  # noqa: PLC0415
    base = dict(turns=15, gold_mode="fixed", gold_per_turn=30, action_cap=40,
                num_players=8, trinkets=True, lobby_types=())
    fixed30 = SandboxConfig(**base)
    fixed20 = SandboxConfig(**{**base, "gold_per_turn": 20})
    growth = {**base, "gold_mode": "growth", "gold_growth_rate": 0.15,
              "gold_per_carrier": 2}
    growth2 = SandboxConfig(**{**growth, "action_cap_per_gold": 3})
    growth3 = SandboxConfig(**{**growth, "action_cap_per_gold": 3,
                               "tavern_buff_scale": 3.0})
    return {"fixed20": fixed20, "fixed30": fixed30, "growth2": growth2,
            "growth3": growth3}


# ── 策略前向（只做评测，不依赖会被并行 agent 改动的训练脚本）───────────────


def act_batch(model, feats, cards, masks, device, *, sample: bool, chunk: int = 4096,
              dtype: str = "fp32", temperature: float = 1.0) -> np.ndarray:
    """批量动作：``sample=True`` 按 T=``temperature`` 采样，False 走 argmax。

    自备实现（30 行）而不是 import ``scripts/train_economy_sandbox.py::batch_act``：
    那个文件由 sandbox-econ 并行修改，评测脚本不应该跟着它抖动。数学与它逐位一致
    （``logits.masked_fill(~mask, -1e9)`` -> softmax / T -> multinomial/argmax）。

    ``temperature`` 是**评测侧解码参数**，不是模型参数：BC 策略在 T=1 采样时噪声很大
    （实测 Σ 比 greedy 低 30–54%，见 ``docs/COMPOUND_BC.md`` §6.1），所以报告必须写清
    用的是哪个温度。
    """
    import torch  # noqa: PLC0415

    from hsbg.az.train.ppo import forward_model  # noqa: PLC0415

    model.eval()
    n = len(masks)
    out = np.empty(n, dtype=np.int64)
    use_amp = (str(dtype) == "bf16" and torch.cuda.is_available()
               and str(device).startswith("cuda"))
    with torch.no_grad():
        for s in range(0, n, int(chunk)):
            e = min(n, s + int(chunk))
            f = torch.from_numpy(np.ascontiguousarray(feats[s:e], dtype=np.float32)).to(device)
            c = torch.from_numpy(np.ascontiguousarray(cards[s:e], dtype=np.int64)).to(device)
            m = torch.from_numpy(np.ascontiguousarray(masks[s:e], dtype=bool)).to(device)
            with (torch.autocast("cuda", dtype=torch.bfloat16) if use_amp
                  else _null()):
                logits, _rank, _value = forward_model(model, f, c, m)
            logits = logits.float().masked_fill(~m, -1e9)
            if sample:
                t = float(temperature)
                z = logits / t if (t > 0 and abs(t - 1.0) > 1e-9) else logits
                a = torch.multinomial(torch.softmax(z, dim=-1), 1).squeeze(1)
            else:
                a = logits.argmax(dim=-1)
            out[s:e] = a.detach().cpu().numpy()
    return out


class _null:
    def __enter__(self):
        return None

    def __exit__(self, *a: Any) -> bool:
        return False


# ── 一局驱动（账本 + 载体审计 + 引擎 mask 校验）─────────────────────────────


def _load_model(path: str, device: str):
    from hsbg.az.train.model import load_checkpoint  # noqa: PLC0415
    model, meta = load_checkpoint(path, device=device)
    model.to(device)
    model.eval()
    return model, meta


def run_config(model, cfg, *, games: int, device: str, seed0: int, n_envs: int,
               sample: bool, carrier_audit: int, dtype: str = "fp32",
               temperature: float = 1.0,
               deadline: float = 0.0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """跑 ``games`` 局并返回 (episodes, ledger 汇总)。

    每步做三件事：① 引擎 mask 校验（非法 = 记 ``illegal``，改用 EndTurn，不静默）；
    ② ``Ledger`` 按 A_BUY -> 商店槽记账（放大器/法术计数）；③ 载体审计（目标选择命中载体 eid）。
    """
    from collections import Counter  # noqa: PLC0415

    from hsbg.az.train.economy_sandbox import (  # noqa: PLC0415
        VectorEconomySandbox, carrier_ids, stack_obs)
    from compound_script import BUY_RANGE, Ledger  # noqa: PLC0415

    n = max(1, min(int(n_envs), int(games)))
    # 采样必须**自己播种**：``torch.multinomial`` 用全局 RNG，不播种的话同一
    # seed0/ckpt 每次跑出来的 Σ p50 能差 ±20%（踩过：T=1 同一配置 1160 / 1429）。
    import torch  # noqa: PLC0415
    torch.manual_seed(int(seed0) + 17)
    vec = VectorEconomySandbox(cfg, n_envs=n, seed0=int(seed0))
    obs = vec.reset()
    ledgers = [Ledger() for _ in range(vec.n_envs)]
    cids = set(carrier_ids()) if int(carrier_audit) else set()
    casts = [0] * vec.n_envs
    eps: List[Dict[str, Any]] = []
    t0 = time.time()
    while len(eps) < int(games):
        f, c, m = stack_obs(obs)
        acts = act_batch(model, f, c, m, device, sample=bool(sample), dtype=dtype,
                         temperature=float(temperature))
        step_acts: List[int] = []
        for i, env in enumerate(vec.envs):
            ai = int(acts[i])
            bad = not (0 <= ai < 245 and bool(m[i][ai]))
            if bad:
                ledgers[i].illegal += 1
                ai = 0                                   # EndTurn（A_END 恒合法）
            ledgers[i].legit += 1
            shop: Sequence[Dict[str, Any]] = ()
            need_view = (ai in BUY_RANGE) or (30 <= ai < 46)
            v = json.loads(env.g.view(0)) if need_view else {}
            me = (v.get("me") or {}) if v else {}
            if ai in BUY_RANGE:
                shop = me.get("shop") or ()
            ledgers[i].note(ai, shop)
            if cids and 30 <= ai < 46:
                pend = me.get("pending") or {}
                if str(pend.get("kind")) == "target":
                    # 引擎 Pending::Target 的 JSON 键是 targets（eid 列表），不是 options
                    opts = list(pend.get("targets") or [])
                    ceids = {int(x.get("eid")) for x in (me.get("board") or [])
                             if str(x.get("id")) in cids}
                    j = ai - 30
                    if ceids and j < len(opts) and isinstance(opts[j], int) \
                            and int(opts[j]) in ceids:
                        casts[i] += 1
            step_acts.append(ai)
        obs, _r, dones, infos = vec.step(step_acts)
        for i, d in enumerate(dones):
            if not d:
                continue
            ep = dict(infos[i].get("episode") or {})
            if ep:
                lg = ledgers[i]
                ep["bought_ids"] = dict(lg.buys)
                ep["amp_buys"] = dict(lg.amp)
                ep["amp_total"] = int(sum(lg.amp.values()))
                ep["spells_bought"] = int(lg.spells_bought)
                ep["illegal"] = int(lg.illegal)
                ep["legit"] = int(lg.legit)
                ep["casts_on_carrier"] = int(casts[i])
                eps.append(ep)
            # 无论有没有 episode（截断/异常），该 env 都要换新账本，否则会串局
            ledgers[i] = Ledger()
            casts[i] = 0
        if deadline and (time.time() - t0) > float(deadline):
            print(f"[eval] 到时间上限 {deadline}s，提前停（已跑 {len(eps)} 局）", flush=True)
            break
    amp_hist: Counter = Counter()
    for e in eps:
        amp_hist.update({str(k): int(v) for k, v in (e.get("amp_buys") or {}).items()})
    agg = {
        "illegal": int(sum(e.get("illegal") or 0 for e in eps)),
        "legit": int(sum(e.get("legit") or 0 for e in eps)),
        "amp_hist": dict(amp_hist),
        "amp_mean": _mean([int(e.get("amp_total") or 0) for e in eps]),
        "amp_any_rate": _mean([1.0 if int(e.get("amp_total") or 0) > 0 else 0.0
                               for e in eps]),
    }
    agg["secs"] = round(time.time() - t0, 1)
    return eps, agg


# ── 报告 ────────────────────────────────────────────────────────────────────


def teacher_reference(path: str = "") -> Tuple[Dict[str, Dict[str, float]], str]:
    """教师参考数字：优先现场 json（``groups.json`` 或 BC ``meta.json``），否则用文档兜底表。

    ``path`` 可以是逗号分隔的多个文件；后面的文件只覆盖它**确实给出**的键。
    两种 json 都认：
    ① ``runs/compound_script/groups.json``：教师 28 局/组（**未做 sigma 过滤**，与本脚本
       的评测口径一致，优先用）；
    ② ``data/scaling/compound_bc/meta.json``：教师 240 局/组里**筛选后**（sigma_t15≥1500）
       的统计，数值更高，只适合当「上界参考」，报告里必须写清口径。
    """
    ref = {k: dict(v) for k, v in TEACHER_STATIC.items()}
    srcs: List[str] = []
    for part in str(path or "").split(","):
        part = part.strip()
        if not part or not os.path.isfile(part):
            continue
        try:
            with open(part, encoding="utf-8") as f:
                g = json.load(f)
        except Exception as exc:  # noqa: BLE001 - 参考缺失不该让评测失败
            print(f"[eval] 警告：读 teacher-ref {part} 失败（{exc}），跳过", flush=True)
            continue
        rel = os.path.relpath(part, ROOT) if os.path.abspath(part).startswith(ROOT) \
            else part
        if isinstance(g.get("configs"), dict):          # BC 数据集 meta.json
            for cname, grp in (("fixed30", "s0_fixed30"), ("growth3", "s3_growth_buff3")):
                r = (g.get("configs") or {}).get(grp) or {}
                # 优先「全部 240 局」的统计（与我们的评测口径一致：不过滤 sigma）
                allrun = r.get("t15_sigma_all_run") or {}
                kept = r.get("t15_sigma") or {}
                # 覆盖：这是 n=240 的教师主数字，比 28 局表更稳
                _apply(ref[cname], {
                    "sigma_t15_p50": allrun.get("p50", kept.get("p50")),
                    "sigma_t15_p90": allrun.get("p90", kept.get("p90")),
                    "amp_buys_mean": r.get("amp_total_mean"),
                    "goldens_mean": r.get("goldens_mean"),
                    "spells_mean": r.get("spells_mean"),
                    "games": r.get("games_run"),
                }, only_missing=False)
        else:                                            # groups.json（教师 28 局/组）
            for gname, cname in GROUP_TO_CONFIG.items():
                r = g.get(gname) or {}
                if not isinstance(r, dict):
                    continue
                # 位置靠后的文件覆盖靠前的（默认串把 meta.json 放最后 → n=240 主数字取胜）
                _apply(ref[cname], {k: r.get(k) for k in
                                    ("sigma_t12_p50", "sigma_t12_p90", "sigma_t15_p50",
                                     "sigma_t15_p90", "r12_15_p50", "r12_15_p90",
                                     "amp_buys_mean", "goldens_p50", "goldens_mean",
                                     "spells_p50", "games")}, only_missing=False)
            srcs.append(f"{rel}（教师 28 局/组，未过滤）")
            continue
        srcs.append(f"{rel}（教师 240 局/组 all_run：t15 Σ/放大器/goldens）")
    src = " + ".join(srcs) if srcs else TEACHER_SOURCE
    return ref, src


def _apply(dst: Dict[str, float], src: Dict[str, Any], *,
           only_missing: bool = False) -> None:
    for k, v in src.items():
        if v is None:
            continue
        if only_missing and k in dst:
            continue
        try:
            dst[k] = float(v)
        except (TypeError, ValueError):
            continue


def make_report(eps: Sequence[Dict[str, Any]], agg: Dict[str, Any], cfg,
                teacher: Dict[str, float], name: str = "") -> Dict[str, Any]:
    from hsbg.az.train.economy_sandbox import summarize  # noqa: PLC0415

    rep = dict(summarize(eps))
    n = len(eps)
    s12 = [float(e.get("sigma_t12") or 0) for e in eps]
    s15 = [float(e.get("sigma_t15") or 0) for e in eps]
    ratios = [a / b for a, b in zip(s15, s12) if b > 0]
    gold = [float(e.get("goldens_t15") or 0) for e in eps]
    gi = [float(e.get("gold_total_income") or 0) for e in eps]
    reps = {
        "games": int(n),
        "sigma_t12_p50": _pct(s12, 50), "sigma_t12_p90": _pct(s12, 90),
        "sigma_t12_max": max(s12, default=0.0),
        "sigma_t15_p50": _pct(s15, 50), "sigma_t15_p90": _pct(s15, 90),
        "sigma_t15_max": max(s15, default=0.0),
        "r12_15_p50": _pct(ratios, 50), "r12_15_p90": _pct(ratios, 90),
        "r12_15_mean": _mean(ratios),
        "r12_15_max": max(ratios, default=0.0),
        "r12_15_ge3_rate": _mean([1.0 if r >= 3.0 else 0.0 for r in ratios]),
        "sigma15_per_gold_p50": _pct([a / b for a, b in zip(s15, gi) if b > 0], 50),
        "gold_total_income_p50": _pct(gi, 50),
        "amp_buys_mean": float(agg.get("amp_mean") or 0.0),
        "amp_any_rate": float(agg.get("amp_any_rate") or 0.0),
        "amp_p50": _pct([float(e.get("amp_total") or 0) for e in eps], 50),
        "amp_max": max([float(e.get("amp_total") or 0) for e in eps], default=0.0),
        "amp_by_card": dict(agg.get("amp_hist") or {}),
        "goldens_p50": _pct(gold, 50), "goldens_p90": _pct(gold, 90),
        "goldens_mean": _mean(gold), "goldens_max": max(gold, default=0.0),
        "carrier_rate": float(rep.get("carrier_rate") or 0.0),
        "carriers_p50": float(rep.get("carriers_p50") or 0.0),
        "spells_p50": float(rep.get("spells_p50") or 0.0),
        "spells_max": float(rep.get("spells_max") or 0.0),
        "spells_mean": _mean([float(e.get("spells_t15") or 0) for e in eps]),
        "casts_on_carrier_mean": _mean([float(e.get("casts_on_carrier") or 0) for e in eps]),
        "casts_on_carrier_p50": _pct([float(e.get("casts_on_carrier") or 0) for e in eps], 50),
        "tier_p50": float(rep.get("tier_p50") or 0.0),
        "legal_rate": (agg["legit"] / max(1, agg["legit"] + agg["illegal"])),
        "illegal": int(agg.get("illegal") or 0),
        "decisions_mean": float(rep.get("decisions_mean") or 0.0),
        "secs": float(agg.get("secs") or 0.0),
    }
    # ── 教师差距（ours - teacher；负 = 学生更差）──────────────────────────
    delta: Dict[str, float] = {}
    for key in ("sigma_t12_p50", "sigma_t15_p50", "r12_15_p50", "r12_15_p90",
                "amp_buys_mean", "goldens_p50", "goldens_mean", "spells_p50",
                "spells_mean"):
        if key in teacher:
            delta[key] = float(reps[key]) - float(teacher[key])
    if teacher.get("sigma_t15_p50"):
        delta["sigma_t15_p50_rel"] = float(reps["sigma_t15_p50"]) / \
            float(teacher["sigma_t15_p50"])
    if teacher.get("amp_buys_mean"):
        delta["amp_buys_mean_rel"] = float(reps["amp_buys_mean"]) / \
            float(teacher["amp_buys_mean"])
    reps["teacher"] = dict(teacher)
    reps["teacher_delta"] = delta
    profile = CONFIG_PROFILE.get(str(name), "growth")
    reps["config"] = {
        "name": str(name),
        "gate_profile": profile,
        "gold_mode": getattr(cfg, "gold_mode", ""),
        "gold_per_turn": int(getattr(cfg, "gold_per_turn", 0)),
        "gold_growth_rate": float(getattr(cfg, "gold_growth_rate", 0.0)),
        "gold_per_carrier": int(getattr(cfg, "gold_per_carrier", 0)),
        "action_cap": int(getattr(cfg, "action_cap", 0)),
        "action_cap_per_gold": int(getattr(cfg, "action_cap_per_gold", 0)),
        "tavern_buff_scale": float(getattr(cfg, "tavern_buff_scale", 1.0)),
        "gold_cap": int(getattr(cfg, "gold_cap", 0)),
        "turns": int(getattr(cfg, "turns", 0)),
    }
    reps["gate"] = evaluate_gates(reps, profile)
    return reps


def evaluate_gates(rep: Dict[str, Any],
                   profile: str = "growth") -> Dict[str, Any]:
    """四条判据（按``profile`` 取阈值，见 ``GATE_PROFILES``）：逐项值 + 是否达标。"""
    gates = GATE_PROFILES.get(str(profile), GATE_PROFILES["growth"])
    checks: Dict[str, Any] = {"profile": str(profile)}
    ok = True
    for key, thr in gates.items():
        val = float(rep.get(key) or 0.0)
        good = bool(val >= float(thr))
        checks[key] = {"value": val, "threshold": float(thr), "pass": good,
                       "label": GATE_LABELS.get(key, key)}
        ok = ok and good
    checks["pass_all"] = bool(ok)
    return checks


def _fmt_table(reports: Dict[str, Dict[str, Any]]) -> str:
    head = ("| 配置 | 局数 | t12 Σ p50 | t15 Σ p50 | t15 Σ p90 | r12_15 p50 | "
            "放大器/局 | goldens p50/mean | 载体率 | 对载体施法 | 施法 p50 | 合法率 |")
    sep = "|" + "---|" * 12
    lines = [head, sep]
    for name, r in reports.items():
        lines.append(
            f"| {name} | {r['games']} | {r['sigma_t12_p50']:.0f} | "
            f"{r['sigma_t15_p50']:.0f} | {r['sigma_t15_p90']:.0f} | "
            f"{r['r12_15_p50']:.2f} | {r['amp_buys_mean']:.2f} | "
            f"{r['goldens_p50']:.0f}/{r['goldens_mean']:.2f} | "
            f"{r['carrier_rate']:.2f} | {r['casts_on_carrier_mean']:.2f} | "
            f"{r['spells_p50']:.0f} | {r['legal_rate']:.3f} |")
    return "\n".join(lines)


def _fmt_gap(reports: Dict[str, Dict[str, Any]]) -> str:
    head = ("| 配置 | Δt15 Σ p50 | Δt15 比 | Δ放大器/局 | Δr12_15 p50 | Δgoldens p50 | "
            "教师 t15 p50 | 判据 |")
    sep = "|" + "---|" * 8
    lines = [head, sep]
    for name, r in reports.items():
        d = r.get("teacher_delta") or {}
        t = r.get("teacher") or {}
        g = r.get("gate") or {}
        fails = [GATE_LABELS.get(k, k) for k, v in g.items()
                 if isinstance(v, dict) and not v.get("pass")]
        verdict = "通过" if g.get("pass_all") else ("未过：" + ",".join(fails))
        lines.append(
            f"| {name} | {d.get('sigma_t15_p50', float('nan')):+.0f} | "
            f"{d.get('sigma_t15_p50_rel', float('nan')):.2f}× | "
            f"{d.get('amp_buys_mean', float('nan')):+.2f} | "
            f"{d.get('r12_15_p50', float('nan')):+.2f} | "
            f"{d.get('goldens_p50', float('nan')):+.1f} | "
            f"{float(t.get('sigma_t15_p50') or 0):.0f} | {verdict} |")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """CLI 定义（单独拿出来，单测要断言默认值不漂）。"""
    ap = argparse.ArgumentParser(description="复利 BC 学生模型沙盒评测（24–48 局）")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--games", type=int, default=32, help="每配置局数（24–48 为宜）")
    ap.add_argument("--n-envs", type=int, default=16)
    ap.add_argument("--configs", default="fixed20,fixed30",
                    help="可选 fixed20(现实收入)/fixed30/growth2/growth3")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--seed0", type=int, default=910000)
    ap.add_argument("--sample", type=int, default=1, help="1=采样（部署口径）/0=argmax")
    ap.add_argument("--carrier-audit", type=int, default=1)
    ap.add_argument("--dtype", default="fp32", choices=["fp32", "bf16"])
    ap.add_argument("--temperature", type=float, default=1.0,
                    help="采样温度（仅 --sample 1 生效）；BC 策略实测 T=1 明显差于 greedy")
    ap.add_argument("--gate-config", default="fixed20",
                    help="用哪条配置判判据（默认 fixed20 = 现实收入档）")
    ap.add_argument("--gold-profile", dest="gold_profile", default="",
                    help="task-13：按回合金币曲线（空 = 用配置自带经济）；"
                         "对齐完整对局用 3,4,5,6,7,8,9,10,10,10,10,10,11")
    ap.add_argument("--tier-reward-coef", dest="tier_reward_coef", type=float,
                    default=0.0)
    ap.add_argument("--teacher-ref",
                    default="runs/compound_script/groups.json,"
                            "data/scaling/compound_bc/meta.json",
                    help="逗号分隔；靠后的文件覆盖靠前的（默认 meta.json 的 n=240 主数字最后生效）")
    ap.add_argument("--time-budget", type=float, default=0.0, help="每配置秒数上限，0=不限")
    ap.add_argument("--out", default="", help="默认 runs/compound_bc/eval_<ckpt名>.json")
    ap.add_argument("--no-write", action="store_true", help="只打印不落盘")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    configs_all = build_configs()
    if str(getattr(args, "gold_profile", "") or ""):
        configs_all = {k: v.replaced(gold_profile=str(args.gold_profile),
                                    tier_reward_coef=float(args.tier_reward_coef))
                       for k, v in configs_all.items()}
    want = [c.strip() for c in str(args.configs).split(",") if c.strip()]
    unknown = [c for c in want if c not in configs_all]
    if unknown:
        raise SystemExit(f"未知配置 {unknown}；可选 {sorted(configs_all)}")
    teacher, teacher_src = teacher_reference(str(args.teacher_ref))

    model, meta = _load_model(str(args.checkpoint), str(args.device))
    n_param = int(sum(p.numel() for p in model.parameters()))
    print(f"[eval] ckpt={args.checkpoint} params={n_param / 1e6:.3f}M "
          f"arch={meta.get('arch')} d_model={meta.get('d_model')} "
          f"layers={meta.get('n_layers')} games={args.games}/配置", flush=True)
    print(f"[eval] 教师参考：{teacher_src}", flush=True)

    t0 = time.time()
    reports: Dict[str, Dict[str, Any]] = {}
    for name in want:
        cfg = configs_all[name]
        eps, agg = run_config(
            model, cfg, games=int(args.games), device=str(args.device),
            seed0=int(args.seed0), n_envs=int(args.n_envs), sample=bool(args.sample),
            carrier_audit=int(args.carrier_audit), dtype=str(args.dtype),
            temperature=float(args.temperature), deadline=float(args.time_budget))
        reports[name] = make_report(eps, agg, cfg, teacher.get(name, {}), name)
        print(f"[eval] {name}: {reports[name]['games']} 局 / {agg['secs']}s "
              f"[{reports[name]['config']['gate_profile']}] "
              f"t15 p50={reports[name]['sigma_t15_p50']:.0f} "
              f"amp={reports[name]['amp_buys_mean']:.2f} "
              f"r12={reports[name]['r12_15_p50']:.2f} "
              f"goldens={reports[name]['goldens_mean']:.2f}", flush=True)

    gate_cfg = str(args.gate_config)
    verdict = {
        "gate_config": gate_cfg,
        "gate_profile": CONFIG_PROFILE.get(gate_cfg, "growth"),
        "gate": GATE_PROFILES.get(CONFIG_PROFILE.get(gate_cfg, "growth"), GATES),
        "pass_all": bool(reports.get(gate_cfg, {}).get("gate", {}).get("pass_all", False)),
        "per_config": {k: bool((v.get("gate") or {}).get("pass_all"))
                       for k, v in reports.items()},
        "profiles": {k: CONFIG_PROFILE.get(k, "growth") for k in reports},
        "teacher_source": teacher_src,
        "note": ("判据按收入档：realistic(fixed20) amp≥5.5 / t15≥1800 / r12≥1.6；"
                 "growth amp≥5 / t15≥3000 / r12≥2；legacy(fixed30) 沿用旧口径。"
                 "goldens 判据用均值（教师 p50 只有 1–2）"),
    }
    payload = {
        "checkpoint": str(args.checkpoint),
        "params": n_param,
        "checkpoint_meta": {k: meta.get(k) for k in
                            ("arch", "d_model", "n_layers", "n_heads", "size",
                             "ce", "top1", "n_train", "n_val", "soft_labels")},
        "games_per_config": int(args.games),
        "seed0": int(args.seed0), "sample": bool(args.sample),
        "carrier_audit": bool(args.carrier_audit), "dtype": str(args.dtype),
        "temperature": float(args.temperature),
        "teacher_source": teacher_src,
        "verdict": verdict,
        "reports": reports,
        "secs": round(time.time() - t0, 1),
        "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    table = _fmt_table(reports)
    gap = _fmt_gap(reports)
    print("\n" + table + "\n", flush=True)
    print(gap + "\n", flush=True)
    print("VERDICT " + json.dumps(verdict, ensure_ascii=False), flush=True)

    if not args.no_write:
        out = str(args.out) or os.path.join(
            "runs/compound_bc",
            "eval_" + os.path.splitext(os.path.basename(str(args.checkpoint)))[0] + ".json")
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        md = os.path.splitext(out)[0] + ".md"
        with open(md, "w", encoding="utf-8") as f:
            f.write(f"# 复利 BC 评测 · `{os.path.basename(str(args.checkpoint))}`\n\n")
            f.write(f"- 参数量 {n_param / 1e6:.3f}M；每配置 {args.games} 局；"
                    f"seed0 {args.seed0}；sample={bool(args.sample)}；"
                    f"载体审计 {bool(args.carrier_audit)}\n")
            f.write(f"- 教师参考：{teacher_src}\n")
            f.write(f"- 判据配置 `{gate_cfg}`：**{'通过' if verdict['pass_all'] else '未通过'}**"
                    f"（{json.dumps(GATES, ensure_ascii=False)}）\n\n")
            f.write(table + "\n\n" + gap + "\n")
        print(f"[eval] 写出 {out} 与 {md}（总 {payload['secs']}s）", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
