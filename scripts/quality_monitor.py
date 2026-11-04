#!/usr/bin/env python3
"""对局质量监控：逐回合记录我方战团强度/经济，并与真实 10k+ MMR 同 turn 分位对比。

指标（learner seat）：
- board_strength = Σ(atk+hp)，board_count，tier，gold，health，turn
- 死亡回合、死亡时战团强度、每 turn 的强度分位
对比基准：data/real_library/strength_calibration.json 的 real p50/p75/p90（分 turn）。

用法::

  PYTHONPATH=rust/python:. python scripts/quality_monitor.py \
    --checkpoint runs/champion_c0_1746.pt --device cuda:2 --games 256 \
    --seed-base 520000 --out runs/quality/champ_1746.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available, mask_from_bytes  # noqa: E402
from hsbg.az.train.human_board_pool import (HumanBoardStats,  # noqa: E402
                                            inject_turn as inject_human_turn,
                                            load_pool as load_human_pool)
from hsbg.az.train.infer_search import (  # noqa: E402
    ACTION_MODES,
    InferSearchConfig,
    InferSearchPolicy,
)
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator, PPOSelfPlayPolicy
from hsbg.eval.metrics import weighted_eval_summary  # noqa: E402


#: action aliases for --action-logit-bias (see hsbg/env/action_space_std.py)
_ACTION_ALIASES = {"upgrade": 3, "end": 0, "refresh": 1, "freeze": 2}

#: Discover / 选一 的动作段（`choose 0..15`）
A_CHOOSE_ = 30
N_CHOICE_ = 16
try:  # 以引擎侧常量为准（保持与训练一致）
    from hsbg.env.action_space_std import (A_BUY as _A_BUY, A_CHOOSE as A_CHOOSE_,
                                           A_FREEZE as _A_FREEZE,
                                           N_CHOICE as N_CHOICE_)
except BaseException:  # noqa: BLE001
    _A_BUY, _A_FREEZE = 4, 2
A_BUY = int(_A_BUY)
A_FREEZE = int(_A_FREEZE)
A_CHOOSE = int(A_CHOOSE_)
N_CHOICE = int(N_CHOICE_)

#: 三连奖励 / Discover 目标卡（放大器 + 引擎卡，见 docs/CHAIN_FUNNEL.md §7）
DISCOVER_TARGETS = {
    # 放大器（Titus / Drakkari / Gatekeeper，含金色版）
    "BG25_354", "BG25_354_G", "BG26_ICC_901", "BG26_ICC_901_G",
    "BG36_640", "BG36_640_G",
    # 引擎卡（用户指定：恶魔干扰者 / 邪能野猪人 / 巴琳达 / 铜须）
    "BG36_762", "BG36_762_G", "BG28_633", "BG28_633_G",
    "BG36_704", "BG36_704_G", "BG_LOE_077", "BG_LOE_077_G",
}


def _shop_card_id(raw, cid2id: dict) -> Optional[str]:
    """商店 slot → 卡牌 id（Minion / Spell 两种 item 形态）。"""
    item = (raw or {}).get("item") if isinstance(raw, dict) else None
    if not isinstance(item, dict):
        return None
    m = item.get("Minion") if "Minion" in item else (item.get("Spell") if "Spell" in item else None)
    if not isinstance(m, dict):
        return None
    return cid2id.get(int(m.get("card") or -1), "")


def _triple_bias_map(pj_now: dict, cid2id: dict, w: float) -> dict:
    """三连/对子先验：给「能凑成三连/对子」的商店 buy 位加 bias（只加不减、只对合法项）。

    计数口径：board + hand 里**同名非金色**张数：``cnt>=2`` ⇒ 买第三张成三连（+2w）；
    ``cnt==1`` ⇒ 凑对子（+w）。
    """
    if w <= 0.0:
        return {}
    from collections import Counter
    own = Counter()
    for key in ("board", "hand"):
        for m in (pj_now.get(key) or []):
            cid = cid2id.get(int(m.get("card") or -1), "")
            if cid and not str(cid).endswith("_G"):
                own[cid] += 1
    out = {}
    for slot, raw in enumerate(pj_now.get("shop") or []):
        cid = _shop_card_id(raw, cid2id)
        if not cid:
            continue
        cnt = own.get(cid, 0)
        if cnt >= 2:
            out[A_BUY + slot] = float(w) * 2.0
        elif cnt == 1:
            out[A_BUY + slot] = float(w)
    return out


def _card_of(x) -> Optional[str]:
    """从 pending option（dict/nested dict/str）里尽力提取卡牌 id。"""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        for k in ("card", "id", "card_id"):
            if k in x and isinstance(x[k], str):
                return x[k]
        for v in x.values():
            got = _card_of(v)
            if got:
                return got
    return None


def _parse_action_logit_bias(spec: str) -> dict:
    """``"upgrade:0.25,3:0.5"`` -> ``{3: 0.25}`` (later wins). Empty -> {}."""
    out: dict = {}
    for part in str(spec or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        key, _, val = part.partition(":")
        idx = _ACTION_ALIASES.get(key.strip().lower())
        if idx is None:
            try:
                idx = int(key.strip())
            except ValueError as exc:
                raise ValueError(f"--action-logit-bias bad action: {part!r}") from exc
        out[int(idx)] = float(val)
    return out


class _LogitBiasEvaluator:
    """Wrap a leaf evaluator with a **bounded logit bias** (eval only, legal actions only).

    Equivalent to adding a constant to the masked logits before softmax:
    ``prior' = softmax(log(prior) + b)`` (prior is already a masked softmax, so log inverts it).
    ``act()`` forwards a ``bias=`` vector to the inner evaluator (same temperature/seed
    semantics). Not wrapping this class = bit-identical to the old path.
    """

    def __init__(self, inner, bias_map: dict) -> None:
        self._inner = inner
        self._map = {int(k): float(v) for k, v in dict(bias_map).items()}
        #: 动态偏置（逐决策设置；例如「Discover 选项里含目标卡」时只偏置那几个 choose 位）
        self._dynamic: dict = {}

    def set_dynamic_bias(self, bias_map: Optional[dict]) -> None:
        """每次决策前由评测循环设置；``None``/空 = 清空。"""
        self._dynamic = {} if not bias_map else {int(k): float(v)
                                                 for k, v in dict(bias_map).items()}

    def _vec(self, mask) -> np.ndarray:
        m = np.asarray(mask, dtype=bool).reshape(-1)
        v = np.zeros(m.size, dtype=np.float32)
        for a, w in list(self._map.items()) + list(self._dynamic.items()):
            if 0 <= a < m.size and bool(m[a]):
                v[a] += float(w)
        return v

    def __call__(self, features, cards, mask, seat: int = 0):
        prior, value = self._inner(features, cards, mask, seat)
        m = np.asarray(mask, dtype=bool).reshape(-1)
        if not (self._map or self._dynamic) or not m.any():
            return prior, value
        z = np.log(np.maximum(np.asarray(prior, dtype=np.float64).reshape(-1), 1e-12))
        z = z + self._vec(m)
        z = np.where(m, z, -np.inf)
        z -= float(np.max(z[m]))
        e = np.where(m, np.exp(z), 0.0)
        s = float(e.sum())
        return ((e / s) if s > 0 else np.asarray(prior, np.float32)), value

    def __getattr__(self, name):
        return getattr(self._inner, name)


_CARD_BASE: dict = {}


def _card_base() -> dict:
    global _CARD_BASE
    if not _CARD_BASE:
        import json as _j
        cards = _j.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
        if isinstance(cards, dict):
            cards = cards.get("cards") or cards.get("data") or list(cards.values())
        _CARD_BASE = {str(c["id"]): (int(c.get("atk") or 0), int(c.get("hp") or 0))
                      for c in cards if isinstance(c, dict) and c.get("id")}
    return _CARD_BASE


def _board_stats(pj: dict) -> dict:
    board = pj.get("board") or []
    strength = 0
    for m in board:
        strength += int(m.get("atk") or 0) + int(m.get("hp") or 0)
    return {"strength": strength, "count": len(board)}


def _board_sig(game, seat: int = 0) -> list[str]:
    """棋盘卡牌序列（**顺序敏感**）：换位的净效果就看这个签名是否变化。"""
    pj = json.loads(game.player_json(int(seat)))
    return [str(m.get("card")) for m in (pj.get("board") or [])]


def _carrier_panel(rows: list, carrier_ids) -> dict:
    """质量面板的载体三指标（docs/CARRIER_SCALING.md §4）。

    - ``carrier_encounter_rate``：局级载体率（曾有主集合载体上场）；
    - ``casts_on_carrier_mean``：每局「目标选择命中载体」的施法次数；
    - ``r_carrier_turns_str12``：r(载体在场回合数 ≤12, Σ₁₂)（Pearson + bootstrap CI）。

    注：本面板只走「目标选择」口径（不解析引擎日志），所以是**严格下界**；
    完整的「触发载体施法」口径见 ``scripts/carrier_audit.py`` / ``carrier_metrics.py``。
    """
    carrier_ids = set(carrier_ids or [])
    if not carrier_ids:
        return {"carrier_audit": False}
    ok = [r for r in rows if r and r.get("turns")]

    def _ct12(r):
        return sum(1 for t in r["turns"]
                   if int(t.get("turn") or 0) <= 12 and t.get("board_carriers"))

    def _s12(r):
        for t in r["turns"]:
            if int(t.get("turn") or 0) == 12:
                return int(t.get("strength") or 0)
        return None

    ever = [r for r in ok if any(t.get("board_carriers") for t in r["turns"])]
    t9 = [r for r in ok if any(int(t.get("turn") or 0) == 9 and t.get("board_carriers")
                               for t in r["turns"])]
    t12 = [r for r in ok if any(int(t.get("turn") or 0) == 12 and t.get("board_carriers")
                                for t in r["turns"])]
    shop = [r for r in ok if r.get("carrier_shop_seen")]
    casts = [int(r.get("casts_on_carrier") or 0) for r in ok]
    corr_rows = [r for r in ok if _s12(r) is not None]
    ct = [_ct12(r) for r in corr_rows]
    sv = [_s12(r) for r in corr_rows]
    r_p = r_s = None
    ci = None
    try:
        from scripts.carrier_common import _boot_corr_ci, _pearson, _spearman
        r_p = _pearson(ct, sv)
        r_s = _spearman(ct, sv)
        ci = _boot_corr_ci(ct, sv)
    except BaseException:  # noqa: BLE001
        pass
    return {
        "carrier_audit": True,
        "carrier_ids": len(carrier_ids),
        "carrier_encounter_rate": (len(ever) / len(ok)) if ok else None,
        "carrier_t9_rate": (len(t9) / len(ok)) if ok else None,
        "carrier_t12_rate": (len(t12) / len(ok)) if ok else None,
        "carrier_shop_offer_rate": (len(shop) / len(ok)) if ok else None,
        "carrier_turns_mean": (sum(ct) / len(ct)) if ct else 0.0,
        "casts_on_carrier_mean": (sum(casts) / len(casts)) if casts else 0.0,
        "casts_on_carrier_mean_given_carrier": (
            sum(int(r.get("casts_on_carrier") or 0) for r in ever) / len(ever)
            if ever else 0.0),
        "r_carrier_turns_str12": r_p,
        "r_carrier_turns_str12_ci95": ci,
        "r_carrier_turns_str12_spearman": r_s,
        "n_t12": len(corr_rows),
        "str12_p50": (float(np.percentile(sv, 50)) if sv else None),
    }


def _pending_target_eids(pend: dict) -> list | None:
    """从 ``view(seat)["me"]["pending"]`` 取目标候选 eid（与动作 30..45 下标一一对应）。

    **引擎契约**：``Pending::Target`` 序列化出来的键是 **``targets``**
    （``Vec<EntityId>`` = int 列表；``rust/crates/hsbg-engine/src/debug.rs``：

    ```text
    Pending::Target { options, .. } => json!({"kind": "target", "targets": options}),
    ```
    ）。

    历史 bug：本脚本读的是 ``pending["options"]`` ⇒ 永远拿不到 Target 的候选
    ⇒ ``casts_on_carrier`` 恒为 0（``docs/ECONOMY_SANDBOX.md`` §9.7）。这里先读
    ``targets``，再回退 ``options``（旧数据 / 旧序列化里出现过元素为 ``{"eid": ..}``
    dict 的形态），两种都归一化成 eid 列表。

    返回 ``None`` 表示「当前不是目标选择」（或结构不可用），空列表表示「是目标选择
    但没有候选」。元素无法转 int 时留 ``None``（不会被误判命中）。
    """
    if not isinstance(pend, dict) or str(pend.get("kind")) != "target":
        return None
    raw = pend.get("targets")
    if raw is None:                      # 兼容旧数据：options 形态
        raw = pend.get("options")
    if raw is None:
        return None
    out: list = []
    for x in raw:
        val = x.get("eid") if isinstance(x, dict) else x
        try:
            out.append(int(val))
        except (TypeError, ValueError):
            out.append(None)
    return out


def _play(seed: int, policy, q: dict) -> dict | None:
    """跑一局；返回 {'placement','death_turn','death_strength','turns':[{...}]}。

    每个 turn 行额外记录 ``moves``（本回合 learner 选择的换位次数）、
    ``board_start``/``board_end``（回合内 learner **最后一次行动后**的棋盘卡牌序列），
    用于统计「每回合换位次数」与「净盘面不变回合比例」。

    ``q["human_board_pool"]`` 非空且 ``human_board_p > 0`` 时，在每个**新回合开始、
    任何座位行动前**，从全部非 learner 座位随机抽 ``human_board_seats`` 个座位、各按
    ``human_board_p`` 注入该 turn 的人类战团（与训练采集 ``human_board_pool.inject_turn``
    同一条代码路径；默认关闭 -> 行为与旧版逐位一致）。
    """
    import hsbg_engine as E
    from hsbg.az.train.game_rules import game_config_json as _game_cfg

    game = E.Game(seed=int(seed), config_json=_game_cfg())
    policy.reset()
    turns = []
    last_turn = -1
    steps = 0
    max_steps = int((q or {}).get("max_steps", 20000) or 20000)
    # ── 对手强度（人类战团注入；默认关闭）──────────────────────────────
    hpool = (q or {}).get("human_board_pool")
    hb_seats = int((q or {}).get("human_board_seats", 2) or 2)
    hb_p = float((q or {}).get("human_board_p", 0.0) or 0.0)
    hb_stats = HumanBoardStats(
        fidelity=str((q or {}).get("human_board_fidelity", "board") or "board"))
    hb_rng = random.Random(int(seed) * 1000003 + 17)
    injected_turn = -1

    def _maybe_inject(turn_now: int) -> None:
        nonlocal injected_turn
        if hpool is None or hb_p <= 0.0 or int(turn_now) == injected_turn:
            return
        injected_turn = int(turn_now)
        if int(turn_now) < 1:
            # 引擎 turn=0 是开局准备帧（人类数据从 turn=1 起；该帧注入会被拒绝）。
            return
        inject_human_turn(
            game, hpool, int(turn_now), seats_count=hb_seats, p=hb_p,
            rng=hb_rng, learner_seat=0, stats=hb_stats,
            set_tier=bool((q or {}).get("human_board_set_tier", True)),
            fidelity=str((q or {}).get("human_board_fidelity", "board") or "board"),
            fast_inject=bool((q or {}).get("human_board_fast_inject", False)))

    # ── 载体审计（docs/CARRIER_SCALING.md）：局级载体率 + 对载体施法 ──
    carrier_ids = set((q or {}).get("carrier_ids") or [])
    #: Discover 选牌先验（--discover-bias）：只对选项里含目标卡的 choose 位加常数
    q_discover_w = float((q or {}).get("discover_bias", 0.0) or 0.0)
    q_discover_targets = set((q or {}).get("discover_targets") or ())
    #: 三连/对子先验
    q_triple_w = float((q or {}).get("triple_bias", 0.0) or 0.0)
    q_buy_core_w = float((q or {}).get("buy_core_bias", 0.0) or 0.0)
    q_tgt_w = float((q or {}).get("carrier_target_bias", 0.0) or 0.0)
    q_core_ids = set((q or {}).get("core_ids") or ())
    q_bias_carriers = set((q or {}).get("bias_carrier_ids") or ())
    q_pair_freeze = bool(int((q or {}).get("pair_freeze", 0) or 0))
    q_cid2id = dict((q or {}).get("cid2id") or {})
    _froze_turn = -1
    cid2id = dict((q or {}).get("cid2id") or {})
    casts_on_carrier = 0
    carrier_shop_seen = False
    carrier_turns = 0
    # 与 official eval（hsbg/az/train/evaluate.py）一致：**每个 pass 每个座位只走一步**。
    # 不能用 `while needs_action(p)`：引擎可能在一次 EndTurn 后立刻推进到下一回合，
    # 会把两个回合的 learner 动作记进同一行（历史 quality_monitor 的 turn 行会错位）。
    while not game.is_over() and steps < max_steps:
        _maybe_inject(int(game.turn))
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            pj = json.loads(game.player_json(0))
            bs = _board_stats(pj)
            board_ids = [cid2id.get(int(m.get("card")), "")
                         for m in (pj.get("board") or [])]
            board_carriers = [x for x in board_ids if x in carrier_ids]
            shop_carriers = []
            for slot in (pj.get("shop") or []):
                item = (slot or {}).get("item") if isinstance(slot, dict) else None
                m = item.get("Minion") if isinstance(item, dict) else None
                if isinstance(m, dict):
                    cid = cid2id.get(int(m.get("card")), "")
                    if cid in carrier_ids:
                        shop_carriers.append(cid)
            if shop_carriers:
                carrier_shop_seen = True
            if board_carriers:
                carrier_turns += 1
            turns.append({"turn": t, "strength": bs["strength"], "count": bs["count"],
                          "tier": int(pj.get("tier") or 0), "gold": int(pj.get("gold") or 0),
                          "health": int(pj.get("health") or 0),
                          "alive": bool(pj.get("alive", True)),
                          "moves": 0, "move_legal": False,
                          "board_carriers": board_carriers,
                          "shop_carrier_ids": shop_carriers,
                          "casts_on_carrier_turn": 0,
                          "board_start": [str(m.get("card")) for m in (pj.get("board") or [])],
                          "board_end": None})
        acted = False
        for p in range(8):
            if game.is_over():
                break
            # 引擎可能在 for 中途推进 turn：新回合必须在任何座位行动前注入
            _maybe_inject(int(game.turn))
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p == 0:
                m = mask_from_bytes(game.legal_mask(0))
                if bool(m[196:245].any()):
                    turns[-1]["move_legal"] = True
                # ── Discover 选牌先验（--discover-bias；默认关）──────────────────
                # 只有出现 choose 合法位时才取一次 view，按选项卡 id 给对应 choose 位加 bias。
                if q_discover_w and bool(m[A_CHOOSE:A_CHOOSE + N_CHOICE].any()):
                    try:
                        _view = json.loads(game.view(0))
                        _pend = (_view.get("me") or {}).get("pending")
                        _ents = _pend if isinstance(_pend, list) else ([_pend] if _pend else [])
                        _bias = {}
                        for _e in _ents:
                            if not (isinstance(_e, dict) and str(_e.get("kind")) == "discover"):
                                continue
                            for _i, _opt in enumerate(_e.get("options") or []):
                                _cid = _card_of(_opt)
                                if _cid in q_discover_targets:
                                    _bias[A_CHOOSE + _i] = float(q_discover_w)
                            break
                        _ev = getattr(policy, "eval_fn", None)
                        if hasattr(_ev, "set_dynamic_bias"):
                            _ev.set_dynamic_bias(_bias or None)
                    except BaseException:  # noqa: BLE001 - 采集失败不影响对局
                        pass
                # ── 三连/对子先验（--triple-bias；默认关）──────────────────────
                # 必须在 decide 之前设置；与 Discover bias 合并到同一个动态向量。
                _triple_bias = {}
                if (q_triple_w > 0.0) and q_cid2id and bool(m[A_BUY:A_BUY + 8].any()):
                    try:
                        _pj_now = json.loads(game.player_json(0))
                        _triple_bias = _triple_bias_map(_pj_now, q_cid2id, q_triple_w)
                        _ev_t = getattr(policy, "eval_fn", None)
                        if _triple_bias and hasattr(_ev_t, "set_dynamic_bias"):
                            _ev_t.set_dynamic_bias(_triple_bias)
                    except BaseException:  # noqa: BLE001
                        _triple_bias = {}
                # 待选目标（施法打谁）：只有出现选择时才多取一次 view（约 0.17ms）
                pend_eids = None
                pend_carrier_eids = set()
                if carrier_ids and bool(m[30:46].any()):
                    try:
                        view = json.loads(game.view(0))
                        me_v = view.get("me") or {}
                        # 引擎 Pending::Target 的键是 targets（见 _pending_target_eids）
                        pend_eids = _pending_target_eids(me_v.get("pending") or {})
                        pend_carrier_eids = {
                            int(x.get("eid")) for x in (me_v.get("board") or [])
                            if str(x.get("id")) in carrier_ids}
                    except BaseException:  # noqa: BLE001
                        pend_eids = None
                # ── 模型+定向层（评测侧；默认 0 = 无偏置、逐位等价）──────────
                _dyn = dict(_triple_bias)
                if q_buy_core_w > 0.0:
                    try:
                        _pj3 = json.loads(game.player_json(0))
                        for _slot, _raw in enumerate((_pj3.get("shop") or [])[:8]):
                            _cid3 = _shop_card_id(_raw, q_cid2id)
                            if _cid3 in q_core_ids and bool(m[A_BUY + _slot]):
                                _dyn[A_BUY + _slot] = _dyn.get(A_BUY + _slot, 0.0) + q_buy_core_w
                    except BaseException:  # noqa: BLE001
                        pass
                if q_tgt_w > 0.0 and bool(m[A_CHOOSE:A_CHOOSE + N_CHOICE].any()):
                    try:
                        _v3 = json.loads(game.view(0))
                        _me3 = _v3.get("me") or {}
                        _o3 = _pending_target_eids(_me3.get("pending") or {})
                        _car3 = {int(x.get("eid")) for x in (_me3.get("board") or [])
                                 if str(x.get("id")) in q_bias_carriers}
                        if _o3 and _car3:
                            for _i, _tg in enumerate(_o3):
                                if (isinstance(_tg, int) and _tg in _car3
                                        and bool(m[A_CHOOSE + _i])):
                                    _dyn[A_CHOOSE + _i] = (_dyn.get(A_CHOOSE + _i, 0.0)
                                                           + q_tgt_w)
                    except BaseException:  # noqa: BLE001
                        pass
                if _dyn:
                    _evp = getattr(policy, "eval_fn", None)
                    if hasattr(_evp, "set_dynamic_bias"):
                        _evp.set_dynamic_bias(_dyn)
                a = int(policy.decide(game, 0).action)
                _ev = getattr(policy, "eval_fn", None)
                if hasattr(_ev, "set_dynamic_bias"):
                    _ev.set_dynamic_bias(None)   # 用完即清，避免污染下一决策
                # ── 三连/对子先验（--triple-bias）+ 差一张时冻结（--pair-freeze）──
                if (q_triple_w > 0.0 or q_pair_freeze) and q_cid2id:
                    try:
                        _pj = json.loads(game.player_json(0))
                        _tb = _triple_bias_map(_pj, q_cid2id, q_triple_w) if q_triple_w > 0.0 else {}
                        if _tb and hasattr(_ev, "set_dynamic_bias"):
                            pass  # 已过决策点：本轮 bias 需在 decide 前设置（见下）
                        if q_pair_freeze and int(game.turn) != _froze_turn:
                            _gold = int(_pj.get("gold") or 0)
                            _need = False
                            for _slot, _raw in enumerate(_pj.get("shop") or []):
                                _cid = _shop_card_id(_raw, q_cid2id)
                                if not _cid:
                                    continue
                                _own = sum(1 for k in ("board", "hand")
                                           for m in (_pj.get(k) or [])
                                           if q_cid2id.get(int(m.get("card") or -1), "") == _cid
                                           and not str(_cid).endswith("_G"))
                                if _own >= 2:
                                    _need = True
                                    break
                            if _need and _gold < 3 and bool(m[A_FREEZE]):
                                _froze_turn = int(game.turn)
                                a = int(A_FREEZE)          # 本回合只冻一次
                    except BaseException:  # noqa: BLE001
                        pass
                if not (0 <= a < 245 and bool(m[a])):
                    nz = np.flatnonzero(m)
                    a = int(nz[0]) if nz.size else 0
                if 196 <= a < 245:      # Move 段：196..244
                    turns[-1]["moves"] = int(turns[-1].get("moves", 0)) + 1
                if pend_eids is not None and 30 <= a < 46:
                    idx = a - 30
                    if (idx < len(pend_eids) and isinstance(pend_eids[idx], int)
                            and pend_eids[idx] in pend_carrier_eids):
                        casts_on_carrier += 1
                        turns[-1]["casts_on_carrier_turn"] = int(
                            turns[-1].get("casts_on_carrier_turn", 0)) + 1
                game.step(0, a)
                # 只取「learner 行动后、战斗前」的盘面，避免战斗死亡污染净盘面判定
                turns[-1]["board_end"] = _board_sig(game)
            else:
                game.bot_play(p)
        if not acted and not game.is_over():
            break
    if not game.is_over():
        return None
    placements = list(game.placements())
    death_turn = None
    death_strength = None
    alive_rows = [row for row in turns if row["alive"]]
    if alive_rows:
        # 取死亡前最后一个「非空战团」回合；若最后一行恰好被清空（终局/战斗后），回退一格
        pick = alive_rows[-1]
        for row in reversed(alive_rows):
            if row["strength"] > 0:
                pick = row
                break
        death_turn, death_strength = pick["turn"], pick["strength"]
    _cb = _tb = 0.0
    try:
        _v4 = json.loads(game.view(0))
        _fb = (_v4.get("me") or {}).get("board") or []
        _base4 = _card_base()
        for _m4 in _fb:
            _cid4 = str(_m4.get("id") or "")
            _b4 = _base4.get(_cid4)
            if _b4 is None:
                continue
            _mult = 2 if _m4.get("golden") else 1
            _buf = max(0.0, (int(_m4.get("atk") or 0) - _mult * _b4[0])
                       + (int(_m4.get("hp") or 0) - _mult * _b4[1]))
            _tb += _buf
            if _cid4 in q_bias_carriers or _cid4 in carrier_ids:
                _cb += _buf
    except BaseException:  # noqa: BLE001
        pass
    try:
        _fb_all = [json.loads(game.player_json(p)) for p in range(8)]
        _final_max = max(
            sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                for m in (pj.get("board") or [])) for pj in _fb_all)
    except BaseException:  # noqa: BLE001
        _final_max = None
    _game_turns = max((int(x["turn"]) for x in turns), default=0)
    return {"placement": int(placements[0]), "death_turn": death_turn,
            "death_strength": death_strength, "turns": turns,
            "game_turns": int(_game_turns),
            "final_max_strength": _final_max,
            "carrier_buff": float(_cb), "total_buff": float(_tb),
            "carrier_buff_share": (float(_cb / _tb) if _tb > 0 else None),
            "carrier_turns": int(carrier_turns),
            "carrier_ever_on_board": bool(carrier_turns > 0),
            "carrier_shop_seen": bool(carrier_shop_seen),
            "casts_on_carrier": int(casts_on_carrier),
            "human_board": hb_stats.to_meta()}


class _ArenaPolicy:
    """把 ``scripts/arena_agent.act`` 包成 quality_monitor 的口径（部署路径离线复现）。

    观测直接喂本地引擎的 v1 字节（features 3227 / cards 124 / mask 245），所以必须
    ``ARENA_CARD_MAP=off``：本地 cards 已经是 37.0 下标，再走竞技场 36.6→37.0 映射
    会整体错位。守卫开关由 ``--move-guard/--move-cap/--move-repeat-limit`` 写进同名
    环境变量 —— 与线上部署**同一条代码路径**（见 docs/ARENA_GUARD.md）。

    每回合动作上限由**驱动侧**模拟竞技场的 ``context.action_limit``（默认 40，与训练
    评测路径 ``max_actions_per_turn`` 同口径）：达到上限后只允许 EndTurn。这是环境
    约束、不是 agent 逻辑；不加它，本地引擎不会像服务器那样强制结束回合，无守卫的
    策略会把 20,000 步预算刷满（truncation），短跑跑不完。
    """

    name = "arena_agent"

    def __init__(self, args) -> None:  # noqa: ANN001 - argparse.Namespace
        import scripts.arena_agent as AA
        self._AA = AA
        self._match = 0
        self._max_actions_per_turn = 40        # 竞技场 action_limit / 训练同口径
        self._turn_actions: dict = {}
        os.environ["ARENA_MODEL"] = os.path.abspath(args.checkpoint)
        os.environ["ARENA_DEVICE"] = str(args.device)
        os.environ["ARENA_CARD_MAP"] = "off"     # 本地观测已是 37.0 下标，不能映射
        os.environ["ARENA_MOVE_GUARD"] = "1" if int(args.move_guard) else "0"
        os.environ["ARENA_MOVE_CAP"] = str(int(args.move_cap))
        os.environ["ARENA_MOVE_REPEAT_LIMIT"] = str(int(args.move_repeat_limit))

    def reset(self) -> None:
        self._match += 1
        self._turn_actions = {}
        self._AA.reset_state()

    def move_guard_meta(self) -> dict:
        return self._AA.guard_meta()

    def decide(self, game, seat: int = 0):  # noqa: ANN001
        from types import SimpleNamespace
        raw = game.observe(int(seat))
        mask = mask_from_bytes(game.legal_mask(int(seat)))
        key = (int(self._match), int(seat), int(game.turn))
        n_used = int(self._turn_actions.get(key, 0)) + 1
        self._turn_actions[key] = n_used
        if n_used > self._max_actions_per_turn and bool(mask[0]):
            return SimpleNamespace(action=0, info={"forced": True})
        obs = {"features": np.frombuffer(raw[0], dtype=np.float32).copy(),
               "cards": np.frombuffer(raw[1], dtype=np.int32).copy(),
               "action_mask": mask.astype(np.uint8)}
        ctx = {"match_id": int(self._match), "seat": int(seat),
               "turn": int(game.turn)}
        return SimpleNamespace(action=int(self._AA.act(obs, ctx)), info={})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="runs/champion_c0_1746.pt")
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=256)
    ap.add_argument("--seed-base", type=int, default=520000)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--calibration", default="data/real_library/strength_calibration.json")
    ap.add_argument("--policy", default="selfplay", choices=("selfplay", "arena"),
                    help="selfplay=训练侧策略（默认）；arena=走 scripts/arena_agent.act "
                         "的部署路径（换位守卫默认开，见 docs/ARENA_GUARD.md）")
    ap.add_argument("--move-guard", type=int, default=0, choices=[0, 1],
                    help="1=评测时也启用换位去抖守卫（默认 0=纯模型行为）")
    ap.add_argument("--move-cap", type=int, default=3,
                    help="每回合换位次数上限（仅 --move-guard 1 时生效；默认 3）")
    ap.add_argument("--move-repeat-limit", type=int, default=2,
                    help="同一 (from,to) 本回合出现 >=N 次后屏蔽（默认 2）")
    ap.add_argument("--out", default="runs/quality/quality.json")
    ap.add_argument("--action-logit-bias", default="",
                    help="eval-only bounded logit bias, format `action:weight[,...]` "
                         "(e.g. `upgrade:0.25` or `3:0.5`); alias: upgrade=3, "
                         "end=0, refresh=1, freeze=2. Empty = no wrapper (bit-identical).")
    ap.add_argument("--discover-bias", type=float, default=0.0,
                    help="Discover 选牌先验（默认 0=关闭）：选项里含目标卡（放大器/引擎卡）时，"
                         "给对应 choose 位加该常数（只加不减、只对合法项）")
    ap.add_argument("--discover-targets", default="amp,engine",
                    help="Discover 目标卡集合：amp / engine / all / 逗号分隔卡 id（默认 amp,engine）")
    ap.add_argument("--triple-bias", type=float, default=0.0,
                    help="三连/对子先验（默认 0=关闭）：商店里有能凑三连(+2W)/对子(+W)的同名牌时，"
                         "给对应 buy 位加常数（只加不减、只对合法项）")
    ap.add_argument("--pair-freeze", type=int, default=0, choices=[0, 1],
                    help="1=有对子/差一张三连且买不起第三张时，本回合执行一次 freeze")
    ap.add_argument("--carriers", default="data/scaling/carriers.json",
                    help="载体清单（docs/CARRIER_SCALING.md）；缺失时自动构建")
    ap.add_argument("--carrier-audit", type=int, default=1, choices=[0, 1],
                    help="1=面板里带 carrier_encounter_rate / casts_on_carrier_mean / "
                         "r(载体回合数, Σ12)")
    # ── 加权对局指标（长度 + 终局强度）：0.5/0.5 = 各占一半 ──
    ap.add_argument("--weight-alpha", type=float, default=0.5,
                    help="对局长度在权重中的占比（默认 0.5）")
    ap.add_argument("--weight-beta", type=float, default=0.5,
                    help="对局强度（终局最强盘面 Σ）在权重中的占比（默认 0.5）")
    # ── 对手强度（人类战团注入）：默认关闭 -> 与旧版逐位一致 ──
    #    与训练采集同一条注入路径（human_board_pool.inject_turn），用于对照
    #    「1 席 vs 2 席」「不同分位」下的存活率 / tier 分布（docs/BOARD_RAMP.md §4）。
    ap.add_argument("--human-boards", default="",
                    help="人类战团 JSONL（空=不用；建议 "
                         "data/real_library/library_real_quasi_full.jsonl）")
    ap.add_argument("--human-board-p", type=float, default=0.0,
                    help="每个候选座位每回合注入概率（默认 0=关闭）")
    ap.add_argument("--human-board-seats", type=int, default=2,
                    help="每回合随机抽几个非 learner 座位注入（默认 2）")
    ap.add_argument("--human-board-sample", default="auto",
                    choices=["auto", "p50", "p75", "p90", "max"],
                    help="桶内分位（默认 auto=按 turn 走难度曲线）")
    ap.add_argument("--human-board-set-tier", type=int, default=1, choices=[0, 1],
                    help="1=同时写入按 turn 派生的酒馆等级（默认 1）")
    ap.add_argument("--human-board-fidelity", default="board",
                    choices=["board", "hand", "full"],
                    help="board=board-only（默认）；full=board+hand+可推断 counters"
                         "（需要准完整库）")
    ap.add_argument("--human-board-fast-inject", type=int, default=0, choices=[0, 1],
                    help="1=快速注入路径（与默认路径逐位等价，默认 0）")
    # ── 模型+定向层（评测侧；默认 0 = 无偏置）──────────────────────────────
    ap.add_argument("--buy-core-bias", type=float, default=0.0,
                    help="商店出现核心卡时对应 buy 位 +W（默认 0=关；只对合法位生效）")
    ap.add_argument("--carrier-target-bias", type=float, default=0.0,
                    help="目标选择里选中载体时对应 choose 位 +W（默认 0=关）")
    ap.add_argument("--core-cards", default="BG35_883,BG36_640,BG36_762,BG28_633,BG32_873",
                    help="核心卡 id 逗号分隔（默认 巴琳达/守门/干扰者/野猪人/灰烬腐蚀者）")
    ap.add_argument("--bias-carrier-cards", default="BG36_640,BG36_762,BG28_633",
                    help="载体卡 id 逗号分隔（默认 守门/干扰者/野猪人）")
    # ── 推理期搜索（rollout 叶值 + π_search；默认关，只包评测策略）──────────
    ap.add_argument("--handover-spec", default="",
                    help="混合策略：t0-8:model,t9-15:script（默认空=纯模型）")
    ap.add_argument("--infer-search", type=int, default=0, choices=[0, 1],
                    help="1=关键决策上用推理期搜索覆盖动作（默认 0 = 纯 π_base）")
    ap.add_argument("--infer-search-turns", type=int, default=1, choices=[1, 3],
                    help="叶值 horizon：1=到本回合末，3=到第 3 个回合末")
    ap.add_argument("--infer-search-max-per-turn", type=int, default=3,
                    help="每回合最多搜索几次（默认 3）")
    ap.add_argument("--infer-search-when", default="carrier_or_spell",
                    help="关键决策口径（默认 carrier_or_spell = 沙盒实测口径）")
    ap.add_argument("--infer-search-action", default="pi_argmax",
                    choices=list(ACTION_MODES),
                    help="覆盖动作规则：pi_argmax（默认）/argmax_q/sample")
    ap.add_argument("--infer-search-topk", type=int, default=8,
                    help="根候选数 = π_base top-k 非 Move 合法动作")
    ap.add_argument("--infer-search-adv-clip", type=float, default=30.0,
                    help="π 构造的优势裁剪（nats）")
    ap.add_argument("--infer-search-max-ms", type=float, default=0.0,
                    help="单次搜索墙钟上限（ms；0=不限）：超时退回 π_base 动作")
    ap.add_argument("--infer-search-tier-bonus", type=float, default=0.0,
                    help="叶值 tier 项权重：+w·(tier/6)（默认 0 = 纯 log1p(Σ)）")
    ap.add_argument("--infer-search-health-bonus", type=float, default=0.0,
                    help="叶值血量项权重：+w·(health/30)（默认 0）")
    args = ap.parse_args()
    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2

    # ── 载体清单（与 scripts/carrier_audit.py 同源）──────────────────────
    carrier_ids: list = []
    cid2id: dict = {}
    if int(args.carrier_audit):
        try:
            from scripts.carrier_common import (CATALOG_OUT,
                                                ids_from_catalog,
                                                load_or_build_catalog)
            import json as _json
            import hsbg_engine as _E
            _cat = load_or_build_catalog(args.carriers)
            carrier_ids = sorted(ids_from_catalog(_cat, "primary"))
            cid2id = {int(c["cid"]): str(c["id"])
                      for c in _json.loads(_E.catalog_json())}
        except BaseException as exc:  # noqa: BLE001
            print(f"[warn] 载体清单不可用（{exc}）；跳过载体指标", file=sys.stderr)
            carrier_ids, cid2id = [], {}

    if args.policy == "arena":
        # 部署路径：checkpoint/设备/守卫全部由 arena_agent 的环境变量在 act 内消费。
        policy = _ArenaPolicy(args)
        cfg_dict = {"max_steps": int(args.max_steps)}
    else:
        model, meta = load_checkpoint(args.checkpoint, device=args.device)
        ev = PPOEvaluator(model, device=args.device,
                          norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
        # bounded logit bias (eval only; empty -> no wrapper -> bit-identical to old path)
        _bias_map = _parse_action_logit_bias(str(getattr(args, "action_logit_bias", "") or ""))
        _disc_w = float(getattr(args, "discover_bias", 0.0) or 0.0)
        _buy_w = float(getattr(args, "buy_core_bias", 0.0) or 0.0)
        _tgt_w = float(getattr(args, "carrier_target_bias", 0.0) or 0.0)
        if _bias_map or _disc_w or _buy_w > 0.0 or _tgt_w > 0.0:
            ev = _LogitBiasEvaluator(ev, _bias_map)
            print(f"[quality] action_logit_bias={_bias_map} discover_bias={_disc_w} "
                  f"buy_core_bias={_buy_w} carrier_target_bias={_tgt_w}", flush=True)
        from hsbg.az.train.ppo import CollectConfig
        cfg = CollectConfig(games=1, seed=int(args.seed_base), opponent="bot", behavior="net",
                            max_steps=int(args.max_steps),
                            move_guard=bool(int(args.move_guard)),
                            move_cap=int(args.move_cap),
                            move_repeat_limit=int(args.move_repeat_limit))
        policy = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=ev,
                                   seed=int(args.seed_base), move_model=False)
        cfg_dict = cfg.__dict__

    # ── 推理期搜索包装（默认关 = 纯 pass-through；不改训练路径）─────────────
    search_cfg = InferSearchConfig(
        enabled=int(args.infer_search), turns=int(args.infer_search_turns),
        max_searches_per_turn=int(args.infer_search_max_per_turn),
        search_when=str(args.infer_search_when),
        action=str(args.infer_search_action), topk=int(args.infer_search_topk),
        adv_clip=float(args.infer_search_adv_clip),
        tier_bonus=float(args.infer_search_tier_bonus),
        health_bonus=float(args.infer_search_health_bonus),
        max_ms_per_search=float(args.infer_search_max_ms),
        seed=int(args.seed_base),
        # PPOSelfPlayPolicy 的 pi 不是 π_base（可能是均匀/one-hot）⇒ 自己重算先验
        use_base_prior=0).validate()
    if int(search_cfg.enabled):
        if args.policy == "arena":
            # 竞技场策略没有暴露 leaf evaluator：单独加载同一 checkpoint 当搜索先验
            _m, _meta = load_checkpoint(args.checkpoint, device=args.device)
            search_ev = PPOEvaluator(_m, device=args.device,
                                     norm_mean=_meta.get("norm_mean"),
                                     norm_std=_meta.get("norm_std"))
        else:
            search_ev = ev
        policy = InferSearchPolicy(policy, evaluator=search_ev, config=search_cfg,
                                   device=str(args.device))
        print(f"[quality] infer_search=1 turns={search_cfg.turns} "
              f"when={search_cfg.search_when} action={search_cfg.action} "
              f"max/turn={search_cfg.max_searches_per_turn}", flush=True)

    if str(getattr(args, "handover_spec", "") or ""):
        from policy_hybrid import HybridPolicy, ScriptAdapter
        policy = HybridPolicy(policy, ScriptAdapter("auto", seed=int(args.seed_base)),
                              str(args.handover_spec))
        print(f"[quality] handover_spec={args.handover_spec}", flush=True)

    rows = []
    # Discover 选牌先验：把目标卡集合与 bias 写进 q（_play 逐决策使用）
    _disc_w = float(getattr(args, "discover_bias", 0.0) or 0.0)
    if _disc_w > 0.0:
        cfg_dict = dict(cfg_dict or {})
        _tg = str(getattr(args, "discover_targets", "") or "")
        _set = set()
        for _tok in [x.strip() for x in _tg.split(",") if x.strip()]:
            if _tok == "amp":
                _set |= {c for c in DISCOVER_TARGETS
                         if c.startswith(("BG25_354", "BG26_ICC_901", "BG36_640"))}
            elif _tok in ("engine", "engines"):
                _set |= {c for c in DISCOVER_TARGETS
                         if c.startswith(("BG36_762", "BG28_633", "BG36_704", "BG_LOE_077"))}
            elif _tok == "all":
                _set |= set(DISCOVER_TARGETS)
            else:
                _set.add(_tok)
        cfg_dict["discover_bias"] = _disc_w
        cfg_dict["discover_targets"] = sorted(_set)
        print(f"[quality] discover_bias={_disc_w} targets={len(_set)}", flush=True)
    _core_ids = [x.strip() for x in str(getattr(args, "core_cards", "") or "").split(",")
                 if x.strip()]
    _bias_carriers = [x.strip() for x in
                      str(getattr(args, "bias_carrier_cards", "") or "").split(",") if x.strip()]
    cfg_dict = dict(cfg_dict or {})
    cfg_dict.update({"buy_core_bias": float(getattr(args, "buy_core_bias", 0.0) or 0.0),
                     "carrier_target_bias": float(getattr(args, "carrier_target_bias", 0.0) or 0.0),
                     "core_ids": _core_ids, "bias_carrier_ids": _bias_carriers})
    if carrier_ids:
        cfg_dict = dict(cfg_dict or {})
        cfg_dict["carrier_ids"] = sorted(carrier_ids)
        cfg_dict["cid2id"] = dict(cid2id)
    # 三连/对子先验：把参数与 cid2id 写进 q
    if float(getattr(args, "triple_bias", 0.0) or 0.0) > 0.0 or int(getattr(args, "pair_freeze", 0) or 0):
        cfg_dict = dict(cfg_dict or {})
        cfg_dict["triple_bias"] = float(args.triple_bias)
        cfg_dict["pair_freeze"] = int(args.pair_freeze)
        try:
            import hsbg_engine as _E
            cfg_dict["cid2id"] = {int(c["cid"]): str(c["id"])
                                  for c in json.loads(_E.catalog_json())}
        except BaseException:  # noqa: BLE001
            pass
        print(f"[quality] triple_bias={args.triple_bias} pair_freeze={args.pair_freeze}",
              flush=True)
    # ── 人类战团注入（默认 --human-board-p 0 -> 旧行为不变）──────────────
    hb_pool = None
    if str(args.human_boards) and float(args.human_board_p) > 0.0:
        hb_pool = load_human_pool(str(args.human_boards),
                                  sample=str(args.human_board_sample))
        if hb_pool is None:
            print(f"[warn] 人类战团库为空/不存在: {args.human_boards}；退回纯 bot",
                  file=sys.stderr)
        cfg_dict = dict(cfg_dict or {})
        cfg_dict.update({
            "human_board_pool": hb_pool,
            "human_board_p": float(args.human_board_p),
            "human_board_seats": int(args.human_board_seats),
            "human_board_sample": str(args.human_board_sample),
            "human_board_set_tier": bool(int(args.human_board_set_tier)),
            "human_board_fidelity": str(args.human_board_fidelity),
            "human_board_fast_inject": bool(int(args.human_board_fast_inject)),
        })
    for g in range(int(args.games)):
        r = _play(int(args.seed_base) + g, policy, cfg_dict)
        if r:
            rows.append(r)
    if hasattr(policy, "flush"):     # 推理期搜索：先把最后一局收进轨迹
        policy.flush()
    # 聚合：每 turn 的强度分位
    by_turn: dict[int, list[int]] = {}
    deaths: dict[int, list[int]] = {}
    tiers: dict[int, list[int]] = {}
    golds: dict[int, list[int]] = {}
    turn_moves: dict[int, list[int]] = {}
    all_turn_moves: list[int] = []
    net_unchanged = 0
    net_measured = 0
    move_legal_turns = 0
    move_turns = 0
    net_unchanged_move_turns = 0
    for r in rows:
        for row in r["turns"]:
            by_turn.setdefault(row["turn"], []).append(row["strength"])
            tiers.setdefault(row["turn"], []).append(row["tier"])
            golds.setdefault(row["turn"], []).append(row["gold"])
            n_mv = int(row.get("moves", 0) or 0)
            all_turn_moves.append(n_mv)
            turn_moves.setdefault(row["turn"], []).append(n_mv)
            if bool(row.get("move_legal")):
                move_legal_turns += 1
            if n_mv > 0:
                move_turns += 1
            be, bs = row.get("board_end"), row.get("board_start")
            if be is not None and bs is not None:
                net_measured += 1
                same = list(be) == list(bs)
                if same:
                    net_unchanged += 1
                if n_mv > 0 and same:
                    net_unchanged_move_turns += 1
        dt = r["death_turn"] or 0
        if r["placement"] > 1 and r["death_strength"] is not None:
            deaths.setdefault(dt, []).append(r["death_strength"])
    calib = {}
    if os.path.isfile(args.calibration):
        calib = json.load(open(args.calibration))
    summary = []
    for t in sorted(by_turn):
        v = np.asarray(by_turn[t])
        tv = np.asarray(tiers[t], dtype=np.int64)
        real = (calib.get(str(t)) or {}).get("real") or {}
        summary.append({
            "turn": t, "n": int(v.size),
            "ours_p50": float(np.percentile(v, 50)), "ours_p90": float(np.percentile(v, 90)),
            "ours_max": float(v.max()),
            "real_p50": real.get("p50"), "real_p75": real.get("p75"), "real_p90": real.get("p90"),
            "ratio_p50": (float(np.percentile(v, 50)) / real["p50"]) if real.get("p50") else None,
            "tier_p50": float(np.percentile(tiers[t], 50)),
            # tier≥5 / ≥6 比例（本 turn 全部局）：DPO A/B 的主判据之一
            "tier_ge5_ratio": float(np.mean(tv >= 5)),
            "tier_ge6_ratio": float(np.mean(tv >= 6)),
            "gold_p50": float(np.percentile(golds[t], 50)),
            "moves_mean": float(np.mean(turn_moves[t])),
            "moves_max": int(np.max(turn_moves[t])),
        })
    if deaths:
        all_deaths = [s for v in deaths.values() for s in v]
        death_turns = [t for t, v in deaths.items() for _ in v]
    else:
        all_deaths, death_turns = [], []
    # ── 对手强度对照指标（docs/BOARD_RAMP.md §4）───────────────────────────
    # 「存活到 t12」= **learner 还活着的最大回合** >= 12。注意不能用「局的最大回合」：
    # learner 死后 bot 之间会继续打，局可以到 t15 —— 那样存活率恒 ~1，测不出强度差。
    # 「tier>=4」给两种口径：
    #   tier_ge4_ratio      = 局级（该局 learner 最大 tier >= 4，ramp 门控用）
    #   tier_ge4_turn_ratio = 回合级（tier>=4 的 learner 回合占比，对齐「t1..t6 回合数」
    #                         口径的 s15 证据；分母只算 learner 存活回合）
    alive_turns = [max((int(x["turn"]) for x in r["turns"] if bool(x.get("alive", True))),
                       default=0) for r in rows]
    game_turns = [max((int(x["turn"]) for x in r["turns"]), default=0) for r in rows]
    # ── 加权对局指标（长度 + 强度）─────────────────────────────────────────
    weighted_out = None
    if rows:
        try:
            weighted_out = weighted_eval_summary(
                [int(r["placement"]) for r in rows],
                [float(r.get("game_turns") or 0) for r in rows],
                [float(r.get("final_max_strength") or 0) for r in rows],
                alpha=float(getattr(args, "weight_alpha", 0.5) or 0.5),
                beta=float(getattr(args, "weight_beta", 0.5) or 0.5),
                num_players=8)
        except BaseException:  # noqa: BLE001 - 加权指标不阻塞主评测
            weighted_out = None
    max_tiers = [max((int(x["tier"]) for x in r["turns"]), default=0) for r in rows]
    tier_turn_hist: dict[int, int] = {}
    for r in rows:
        for x in r["turns"]:
            if not bool(x.get("alive", True)):
                continue          # learner 已死：这些回合不反映「活到后期」
            k = int(x["tier"])
            tier_turn_hist[k] = tier_turn_hist.get(k, 0) + 1
    n_turns = int(sum(tier_turn_hist.values()))
    tier_ge4_turns = int(sum(v for k, v in tier_turn_hist.items() if k >= 4))
    hb_sum: dict = {}
    for r in rows:
        for k, v in (r.get("human_board") or {}).items():
            if isinstance(v, int) and not isinstance(v, bool) and k.startswith("human_board_"):
                hb_sum[k] = int(hb_sum.get(k, 0)) + int(v)
    human_board_out = dict(hb_sum, seats=int(args.human_board_seats),
                           p=float(args.human_board_p),
                           sample=str(args.human_board_sample),
                           fidelity=str(args.human_board_fidelity),
                           on=bool(hb_pool is not None and float(args.human_board_p) > 0.0))
    out = {"checkpoint": args.checkpoint, "games": len(rows),
           "policy": args.policy,
           "seed_base": int(args.seed_base),
           "weighted": weighted_out,
           "placements": [r["placement"] for r in rows],
           "mean_rank": float(np.mean([r["placement"] for r in rows])) if rows else None,
           "top4": float(np.mean([r["placement"] <= 4 for r in rows])) if rows else None,
           "win": float(np.mean([r["placement"] == 1 for r in rows])) if rows else None,
           "death_turn_hist": {str(t): len(v) for t, v in sorted(deaths.items())},
           "death_strength_p50": float(np.percentile(all_deaths, 50)) if all_deaths else None,
           "death_strength_mean": float(np.mean(all_deaths)) if all_deaths else None,
           "by_turn": summary,
           "death_turn_p50": float(np.percentile(death_turns, 50)) if death_turns else None,
           # ── 换位去抖（guard）指标 ──
           "move_guard": bool(int(args.move_guard)),
           "move_cap": int(args.move_cap),
           "move_repeat_limit": int(args.move_repeat_limit),
           "turns_total": int(len(all_turn_moves)),
           "move_actions_total": int(sum(all_turn_moves)),
           "moves_per_turn_mean": (float(np.mean(all_turn_moves))
                                   if all_turn_moves else 0.0),
           "moves_per_turn_p50": (float(np.percentile(all_turn_moves, 50))
                                  if all_turn_moves else 0.0),
           "moves_per_turn_p90": (float(np.percentile(all_turn_moves, 90))
                                  if all_turn_moves else 0.0),
           "moves_per_turn_max": int(np.max(all_turn_moves)) if all_turn_moves else 0,
           "turns_with_move": int(sum(1 for v in all_turn_moves if v > 0)),
           "turns_with_move_ratio": (float(np.mean([1.0 if v > 0 else 0.0
                                                    for v in all_turn_moves]))
                                     if all_turn_moves else 0.0),
           "move_legal_turns": int(move_legal_turns),
           "moves_per_move_legal_turn_mean": (float(sum(all_turn_moves))
                                              / move_legal_turns
                                              if move_legal_turns else 0.0),
           "move_turns": int(move_turns),
           "moves_per_move_turn_mean": (float(sum(all_turn_moves)) / move_turns
                                       if move_turns else 0.0),
           "net_board_unchanged_turns": int(net_unchanged),
           "net_board_unchanged_measured": int(net_measured),
           "net_board_unchanged_ratio": (float(net_unchanged) / net_measured
                                         if net_measured else 0.0),
           "net_board_unchanged_move_turns": int(net_unchanged_move_turns),
           "net_board_unchanged_move_ratio": (float(net_unchanged_move_turns)
                                              / move_turns if move_turns else 0.0),
           "tier_p50_t9": (next((row["tier_p50"] for row in summary
                                 if row["turn"] == 9), None)),
           "tier_p50_t12": (next((row["tier_p50"] for row in summary
                                  if row["turn"] == 12), None)),
           "tier_p50_t15": (next((row["tier_p50"] for row in summary
                                  if row["turn"] == 15), None)),
           # tier≥5 比例（turn 9/12/15）：upgrade DPO 的主判据（docs/DPO_UPGRADE.md）
           "tier_ge5_t9": (next((row["tier_ge5_ratio"] for row in summary
                                 if row["turn"] == 9), None)),
           "tier_ge5_t12": (next((row["tier_ge5_ratio"] for row in summary
                                  if row["turn"] == 12), None)),
           "tier_ge5_t15": (next((row["tier_ge5_ratio"] for row in summary
                                  if row["turn"] == 15), None)),
           # 战团强度比（ours_p50 / real_p50，turn 9/12/15）
           "strength_ratio_t9": (next((row["ratio_p50"] for row in summary
                                       if row["turn"] == 9), None)),
           "strength_ratio_t12": (next((row["ratio_p50"] for row in summary
                                        if row["turn"] == 12), None)),
           "strength_ratio_t15": (next((row["ratio_p50"] for row in summary
                                        if row["turn"] == 15), None)),
           "move_guard_meta": policy.move_guard_meta(),
           # ── 推理期搜索（--infer-search；关闭时保留同名字段便于 A/B 对齐）──
           "infer_search": (dict(getattr(policy, "stats")()) if hasattr(policy, "stats")
                            else {"search_enabled": 0, "search_calls": 0,
                                  "mean_ms_per_call": None}) | {
               "strength_t12_p50": next((row["ours_p50"] for row in summary
                                         if row["turn"] == 12), None),
               "strength_t15_p50": next((row["ours_p50"] for row in summary
                                         if row["turn"] == 15), None)},
           # ── 对手强度对照（docs/BOARD_RAMP.md §4；human_board_p=0 时指标为空）──
           "survive_t12_ratio": (float(np.mean([t >= 12 for t in alive_turns]))
                                 if alive_turns else None),
           "tier_ge4_ratio": (float(np.mean([t >= 4 for t in max_tiers]))
                              if max_tiers else None),
           "tier_ge4_turn_ratio": (float(tier_ge4_turns) / n_turns
                                   if n_turns else None),
           "tier_turn_hist": {str(k): int(v) for k, v in sorted(tier_turn_hist.items())},
           "max_tier_p50": (float(np.percentile(max_tiers, 50)) if max_tiers else None),
           "learner_turn_p50": (float(np.percentile(alive_turns, 50))
                                if alive_turns else None),
           "game_turn_p50": (float(np.percentile(game_turns, 50))
                             if game_turns else None),
           "turns_alive_total": n_turns,
           "human_board": human_board_out}
    _cbs = [r.get("carrier_buff_share") for r in rows
            if r.get("carrier_buff_share") is not None]
    out["carrier_buff_share_mean"] = float(np.mean(_cbs)) if _cbs else None
    out["carrier_buff_share_p50"] = float(np.percentile(_cbs, 50)) if _cbs else None
    out["carrier_buff_p50"] = (float(np.percentile([r.get("carrier_buff") or 0
                                                    for r in rows], 50)) if rows else None)
    out["buy_core_bias"] = float(getattr(args, "buy_core_bias", 0.0) or 0.0)
    out["carrier_target_bias"] = float(getattr(args, "carrier_target_bias", 0.0) or 0.0)
    out.update(_carrier_panel(rows, carrier_ids))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)
    _show = {k: out.get(k) for k in (
        "games", "policy", "move_guard", "mean_rank", "top4", "win", "death_turn_p50",
        "death_strength_p50",
        "moves_per_turn_mean", "moves_per_turn_p90", "moves_per_turn_max",
        "moves_per_turn_p50", "turns_with_move",
        "net_board_unchanged_ratio",
        "moves_per_move_legal_turn_mean", "moves_per_move_turn_mean",
        "net_board_unchanged_turns",
        "net_board_unchanged_move_turns", "net_board_unchanged_move_ratio",
        "tier_p50_t9", "tier_p50_t12", "tier_p50_t15",
        "tier_ge5_t9", "tier_ge5_t12", "tier_ge5_t15",
        "strength_ratio_t9", "strength_ratio_t12", "strength_ratio_t15",
        "infer_search",
        "carrier_encounter_rate", "carrier_t9_rate", "casts_on_carrier_mean",
        "r_carrier_turns_str12", "r_carrier_turns_str12_ci95",
        "survive_t12_ratio", "tier_ge4_ratio", "tier_ge4_turn_ratio",
        "max_tier_p50", "learner_turn_p50", "game_turn_p50",
        "tier_turn_hist", "human_board")}
    if weighted_out is not None:
        _show["weighted"] = weighted_out["weighted"]
        _show["weight_n_eff"] = weighted_out["n_eff"]
        _show["weight_stats"] = weighted_out["weight_stats"]
    print(json.dumps(_show, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
