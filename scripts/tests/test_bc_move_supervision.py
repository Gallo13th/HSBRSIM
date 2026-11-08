"""Move(196..244) 动作族 BC 监督的单测（见 ``docs/BC_PRETRAIN.md`` §9）。

覆盖：

1. ``reposition`` 样本被纳入第 10 类 type CE，``--bc-class-weight`` 覆盖生效；
2. 关闭开关（默认 / ``--bc-include-reposition 0``）时与历史 9 类实现**逐位等价**
   （数组字段、``bc_obs_batch``、``bc_hier_loss`` 与 CLI 存盘 checkpoint）；
3. ``--bc-move-anchor-coef``（``coef * MSE(move_logits, init)``）在 1 步 / 短训后
   让 Move logits 的漂移更小；
4. 10 类路径与原 9 类 type CE 兼容（9 类数据、9 类损失不变）。
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from hsbg.az.train.bc_aux import (  # noqa: E402
    BC_MOVE_SLICE,
    BC_REPOSITION_TYPE,
    DEFAULT_BC_ACTION_TYPES,
    bc_action_types,
    bc_obs_batch,
    bc_type_ids,
    bc_type_logits,
    parse_bc_class_weights,
    load_bc_samples,
    bc_hier_loss,
)
from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS  # noqa: E402
from hsbg.az.train.model import build_net, load_checkpoint, save_checkpoint  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "bc_pretrain.py"
TYPES_10 = bc_action_types(True)


# ══════════════════════════════════════════════════════════════════════════
# 合成数据
# ══════════════════════════════════════════════════════════════════════════
def _write_cards(path: Path) -> str:
    cards = [
        {"id": "TEST_MINION", "kind": "minion", "tier": 1, "atk": 2, "hp": 3,
         "cost": 3, "races": ["BEAST"], "keywords": ["TAUNT"]},
        {"id": "TEST_SPELL", "kind": "spell", "tier": 2, "atk": 0, "hp": 0,
         "cost": 2, "races": [], "keywords": []},
        {"id": "TEST_MINION_G", "kind": "minion", "tier": 2, "atk": 4, "hp": 6,
         "cost": 3, "races": ["BEAST"], "keywords": []},
        {"id": "TEST_HERO", "kind": "hero", "tier": 0, "atk": 0, "hp": 0,
         "cost": 0, "races": [], "keywords": []},
    ]
    path.write_text(json.dumps({"meta": {"count": len(cards)}, "cards": cards}),
                    encoding="utf-8")
    return str(path)


def _row(**kw) -> dict:
    base = {
        "game_id": "g", "player_folder": "p", "player": "tester", "hero": "TEST_HERO",
        "turn": 6, "mmr": "7200", "action_type": "end_turn", "action_index": 0,
        "gold": 6, "tier": 3, "health": 28, "armor": 0, "damage": 0,
        "board_cards": [], "board_pos": [],
        "hand_cards": [], "hand_pos": [],
        "shop_cards": [], "shop_pos": [],
        "card_id": None,
    }
    base.update(kw)
    return base


def _rows(n: int = 300) -> list[dict]:
    """6 种动作循环；每 6 条 1 条 ``reposition``（3 张棋盘 -> 6 个合法换位）。"""
    board = ["TEST_MINION"] * 3
    board_pos = [0, 1, 2]
    shop = ["TEST_MINION"] * 7
    rows = []
    for i in range(int(n)):
        gid = f"game-{i // 10:03d}"
        kind = i % 6
        if kind == 0:
            rows.append(_row(game_id=gid))
        elif kind == 1:
            rows.append(_row(game_id=gid, action_type="reroll", action_index=1))
        elif kind == 2:
            rows.append(_row(game_id=gid, action_type="sell",
                             action_index=16 + (i % 3), board_cards=board,
                             board_pos=board_pos, card_id="TEST_MINION"))
        elif kind == 3:
            rows.append(_row(game_id=gid, action_type="buy_minion",
                             action_index=8 + (i % 7), shop_cards=shop,
                             shop_pos=list(range(7)), card_id="TEST_MINION"))
        elif kind == 4:
            rows.append(_row(game_id=gid, action_type="play_minion",
                             action_index=46, hand_cards=["TEST_MINION"],
                             hand_pos=[0], board_cards=board,
                             board_pos=board_pos, card_id="TEST_MINION"))
        else:
            # Move(from, to) = 196 + from*7 + to（from != to）
            f, t = i % 3, (i + 1) % 3
            assert f != t
            rows.append(_row(game_id=gid, action_type=BC_REPOSITION_TYPE,
                             action_index=196 + f * 7 + t,
                             board_cards=board, board_pos=board_pos))
    return rows


def _rows_norepo(n: int = 120) -> list[dict]:
    """不含 reposition 的样本（用于 9 类兼容性测试）。"""
    return [r for r in _rows(n * 2) if r.get("action_type") != BC_REPOSITION_TYPE][:n]


def _write_jsonl(path: Path, rows: list[dict]) -> str:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(path)


def _subprocess_env() -> dict:
    env = dict(os.environ)
    parts = [str(ROOT)]
    rust_py = ROOT / "rust" / "python"
    if rust_py.is_dir():
        parts.append(str(rust_py))
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _run(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), *args]
    proc = subprocess.run(cmd, cwd=str(ROOT), env=_subprocess_env(),
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise AssertionError(
            f"bc_pretrain 退出码 {proc.returncode}\ncmd={' '.join(cmd)}\n"
            f"--- stdout ---\n{proc.stdout[-4000:]}\n"
            f"--- stderr ---\n{proc.stderr[-4000:]}")
    return proc


def _load_script_module():
    spec = importlib.util.spec_from_file_location("bc_pretrain_move_mod", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════════════════════════════════════════════════════
# 1. reposition 纳入 + class-weight
# ══════════════════════════════════════════════════════════════════════════
def test_reposition_included_and_class_weight_applied(tmp_path):
    cards = _write_cards(tmp_path / "cards.json")
    samples_path = _write_jsonl(tmp_path / "bc.jsonl.gz", _rows(300))
    samples = load_bc_samples(samples_path, cards_path=cards,
                              action_types=TYPES_10,
                              class_weight_overrides={"reposition": 2.0})
    assert len(samples) == 300
    dist = samples.class_distribution()
    assert dist[BC_REPOSITION_TYPE] == 50
    assert samples.action_types == TYPES_10
    repo = np.where(samples.action_class == 9)[0]
    assert repo.size == 50
    # 覆盖权重只作用在 reposition 上
    assert np.allclose(samples.class_weight[repo], 2.0)
    other = np.ones(len(samples), dtype=bool)
    other[repo] = False
    assert np.allclose(samples.class_weight[other], 1.0)

    # 混合 batch（reposition + 其它类型），才能验证 class-weight 的**相对**加权
    other_rows = np.where(samples.action_class != 9)[0][:25]
    sel_idx = np.concatenate([repo[:25], other_rows])
    batch = bc_obs_batch(samples, indices=sel_idx)
    # Move 段整体归属第 10 类；reposition 样本的 target = 9
    assert np.all(batch.type_ids[:, BC_MOVE_SLICE] == 9)
    assert np.all(batch.class_ids[:25] == 9)
    # reposition 样本 3 张棋盘 -> 6 个合法换位候选（from != to）
    assert np.all(batch.action_mask[:25, BC_MOVE_SLICE].sum(axis=1) == 6)

    # class-weight 进入 type CE：与手算加权 CE 逐位一致
    torch.manual_seed(0)
    logits = torch.randn(sel_idx.size, N_ACTIONS)
    counts = np.ones(len(TYPES_10), dtype=np.int64)   # 关闭 class-balanced
    hier = bc_hier_loss(logits, batch.type_ids, batch.class_ids,
                        action_mask=batch.action_mask, class_counts=counts,
                        class_weight=batch.class_weight, n_types=10)
    type_logits = bc_type_logits(logits, batch.type_ids, batch.action_mask,
                                 n_types=10)
    per = torch.nn.functional.cross_entropy(
        type_logits, torch.as_tensor(batch.class_ids, dtype=torch.long),
        reduction="none")
    w = torch.as_tensor(batch.class_weight, dtype=per.dtype)
    manual = (per * w).sum() / w.sum()
    assert torch.allclose(hier["type_loss"], manual, atol=1e-6)
    # 关掉覆盖权重 -> 损失不同（证明 class-weight 真的生效）
    hier_plain = bc_hier_loss(logits, batch.type_ids, batch.class_ids,
                              action_mask=batch.action_mask,
                              class_counts=counts, class_weight=None,
                              n_types=10)
    assert not torch.allclose(hier["type_loss"], hier_plain["type_loss"])

    # 解析器：开关打开后接受 "reposition=2"，默认 9 类仍然拒绝
    assert parse_bc_class_weights("reposition=2", TYPES_10) == {
        BC_REPOSITION_TYPE: 2.0}
    with pytest.raises(ValueError):
        parse_bc_class_weights("reposition=2")


# ══════════════════════════════════════════════════════════════════════════
# 2. 关闭开关 = 历史 9 类实现（逐位等价）
# ══════════════════════════════════════════════════════════════════════════
def test_reposition_off_is_bitwise_equivalent(tmp_path):
    cards = _write_cards(tmp_path / "cards.json")
    samples_path = _write_jsonl(tmp_path / "bc.jsonl.gz", _rows(300))
    default = load_bc_samples(samples_path, cards_path=cards)
    explicit = load_bc_samples(samples_path, cards_path=cards,
                               action_types=bc_action_types(False))
    assert default.action_types == DEFAULT_BC_ACTION_TYPES
    assert "reposition" not in default.class_distribution()
    fields = ("action_index", "action_class", "mmr", "weight", "class_weight",
              "turn", "gold", "tier", "health", "armor", "hero", "shop",
              "shop_present", "hand", "hand_present", "board", "board_present",
              "turn_known", "gold_known", "tier_known", "health_known",
              "armor_known", "class_counts", "card_target", "card_valid")
    for name in fields:
        assert np.array_equal(getattr(default, name), getattr(explicit, name)), name

    # Move 段：默认不参与类型聚合、也不进近似动作掩码
    idx = np.arange(min(60, len(default)))
    batch = bc_obs_batch(default, indices=idx)
    assert np.all(batch.type_ids[:, BC_MOVE_SLICE] == -1)
    assert not np.any(batch.action_mask[:, BC_MOVE_SLICE])
    assert int(np.max(batch.class_ids)) < 9

    # 9 类 loss：默认 n_types 与显式 n_types=9 逐位相同，且等于手算 logsumexp CE
    torch.manual_seed(1)
    logits = torch.randn(idx.size, N_ACTIONS)
    counts = np.ones(9, dtype=np.int64)
    h_default = bc_hier_loss(logits, batch.type_ids, batch.class_ids,
                             action_mask=batch.action_mask, class_counts=counts)
    h_nine = bc_hier_loss(logits, batch.type_ids, batch.class_ids,
                          action_mask=batch.action_mask, class_counts=counts,
                          n_types=9)
    assert h_default["type_logits"].shape == (idx.size, 9)
    assert torch.equal(h_default["type_loss"], h_nine["type_loss"])
    tl = bc_type_logits(logits, batch.type_ids, batch.action_mask, n_types=9)
    per = torch.nn.functional.cross_entropy(
        tl, torch.as_tensor(batch.class_ids, dtype=torch.long), reduction="none")
    assert torch.allclose(h_default["type_loss"], per.mean(), atol=1e-6)

    # 9 类静态表未被修改（Move 段仍为 -1）
    assert np.all(bc_type_ids(default, idx)[:, BC_MOVE_SLICE] == -1)


def test_cli_flag_off_matches_default_checkpoint(tmp_path):
    cards = _write_cards(tmp_path / "cards.json")
    samples_path = _write_jsonl(tmp_path / "bc.jsonl.gz", _rows(300))
    common = ["--from-scratch", "--arch", "tiny", "--device", "cpu", "--amp", "off",
              "--samples", samples_path, "--cards", cards, "--steps", "1",
              "--epochs", "1", "--batch", "64", "--lr", "1e-3", "--seed", "0",
              "--log-every", "1"]
    out0, out1 = tmp_path / "out0", tmp_path / "out1"
    _run(*common, "--out", str(out0))
    _run(*common, "--bc-include-reposition", "0", "--out", str(out1))
    m0, meta0 = load_checkpoint(str(out0 / "model.pt"), device="cpu")
    m1, meta1 = load_checkpoint(str(out1 / "model.pt"), device="cpu")
    sd0, sd1 = m0.state_dict(), m1.state_dict()
    assert set(sd0) == set(sd1)
    for key in sd0:
        assert torch.equal(sd0[key], sd1[key]), key
    rep0 = json.loads((out0 / "report.json").read_text(encoding="utf-8"))
    rep1 = json.loads((out1 / "report.json").read_text(encoding="utf-8"))
    assert rep0["data"]["action_types"] == rep1["data"]["action_types"]
    assert [r["loss"] for r in rep0["train"]["curve"]] == \
        [r["loss"] for r in rep1["train"]["curve"]]
    assert int(meta0["bc_include_reposition"]) == int(meta1["bc_include_reposition"]) == 0
    assert int(meta0.get("bc_n_types", 9)) == 9


# ══════════════════════════════════════════════════════════════════════════
# 3. Move 段 MSE 锚定
# ══════════════════════════════════════════════════════════════════════════
class _ToyMoveModel(torch.nn.Module):
    """测试替身：策略 logits 直接就是一个 ``[245]`` 参数（可微、无 trunk）。"""

    def __init__(self, logits: torch.Tensor) -> None:
        super().__init__()
        self.p = torch.nn.Parameter(logits.clone())

    def forward_bc(self, features, cards=None, mask=None):
        z = self.p.unsqueeze(0).expand(int(features.shape[0]), -1)
        if mask is not None:
            z = z.masked_fill(~mask.bool(), -1e9)
        return z, None


def _toy_batch(n: int = 4) -> dict:
    return {
        "x": torch.zeros(n, OBS_FLOATS),
        "cards": torch.zeros(n, OBS_CARDS, dtype=torch.long),
        "action_mask": torch.ones(n, N_ACTIONS, dtype=torch.bool),
    }


def _toy_step(model, teacher, batch, *, anchor_coef: float, torch_mod,
              anchor_fn, pull: float = 1.0, lr: float = 1e-3
              ) -> tuple[float, float]:
    """一步 SGD：目标把 Move logits 往 ``init + pull`` 推（模拟 BC 漂移方向）。

    返回 ``(本步 Move logits 的平均变化量, 相对 init 的平均漂移)``。用 SGD 而不是
    Adam 是为了让“惩罚降低步长/方向”可见（Adam 会把每参数步长归一化）。
    """
    opt = torch_mod.optim.SGD([model.p], lr=float(lr))
    init_move = teacher.p.detach()[BC_MOVE_SLICE].clone()
    before = model.p.detach()[BC_MOVE_SLICE].clone()
    ce = (model.p[BC_MOVE_SLICE] - (init_move + float(pull))).pow(2).mean()
    loss = ce
    if anchor_coef > 0.0:
        logits, _ = model.forward_bc(batch["x"], batch["cards"],
                                     batch["action_mask"])
        anchor = anchor_fn(model, teacher, batch, logits, torch_mod)
        loss = loss + float(anchor_coef) * anchor
    opt.zero_grad()
    loss.backward()
    opt.step()
    change = float((model.p.detach()[BC_MOVE_SLICE] - before).abs().mean())
    drift = float((model.p.detach()[BC_MOVE_SLICE] - init_move).abs().mean())
    return change, drift


def test_move_anchor_is_zero_gradient_at_init_and_damps_drift_in_one_step():
    torch.manual_seed(0)
    init_logits = torch.randn(N_ACTIONS) * 0.5
    batch = _toy_batch()
    anchor_fn = _load_script_module()._move_anchor_mse

    teacher = _ToyMoveModel(init_logits)
    teacher.eval()
    for p in teacher.parameters():
        p.requires_grad_(False)

    # (a) 恰好在 init：MSE 的梯度为 0 -> 第 1 步与不加锚定逐位相同
    m_plain = _ToyMoveModel(init_logits)
    m_anchor = _ToyMoveModel(init_logits)
    c_plain, _ = _toy_step(m_plain, teacher, batch, anchor_coef=0.0,
                           torch_mod=torch, anchor_fn=anchor_fn)
    c_anchor, _ = _toy_step(m_anchor, teacher, batch, anchor_coef=50.0,
                            torch_mod=torch, anchor_fn=anchor_fn)
    assert c_plain == pytest.approx(c_anchor, rel=0.0, abs=1e-12)
    assert torch.equal(m_plain.p.detach(), m_anchor.p.detach())

    # (b) 已经漂移过（= 训练第 1 步之后的状态）：1 步内锚定让 Move logits 变化/漂移更小
    drifted = init_logits.clone()
    drifted[BC_MOVE_SLICE] += 0.02
    kw = dict(pull=10.0, lr=1e-1)
    c_plain, d_plain = _toy_step(_ToyMoveModel(drifted), teacher, batch,
                                 anchor_coef=0.0, torch_mod=torch,
                                 anchor_fn=anchor_fn, **kw)
    c_anchor, d_anchor = _toy_step(_ToyMoveModel(drifted), teacher, batch,
                                   anchor_coef=500.0, torch_mod=torch,
                                   anchor_fn=anchor_fn, **kw)
    assert c_anchor < 0.9 * c_plain, (c_anchor, c_plain)
    assert d_anchor < d_plain


def _save_tiny_init(path: Path, *, seed: int = 7) -> str:
    torch.manual_seed(int(seed))
    model = build_net(256, bc_card_head=True, bc_card_dim=4)
    save_checkpoint(model, str(path), meta={"arch": "tiny"})
    return str(path)


def test_move_anchor_script_reduces_move_logit_drift(tmp_path):
    cards = _write_cards(tmp_path / "cards.json")
    samples_path = _write_jsonl(tmp_path / "bc.jsonl.gz", _rows(300))
    init = _save_tiny_init(tmp_path / "init.pt")
    common = ["--init", init, "--device", "cpu", "--amp", "off",
              "--samples", samples_path, "--cards", cards, "--steps", "50",
              "--epochs", "10", "--batch", "64", "--lr", "1e-4", "--seed", "0",
              "--log-every", "100", "--bc-include-reposition", "1"]
    out_b, out_c = tmp_path / "base", tmp_path / "anchor"
    _run(*common, "--out", str(out_b))
    _run(*common, "--bc-move-anchor-coef", "50", "--out", str(out_c))

    init_model, _ = load_checkpoint(init, device="cpu")
    base_model, _ = load_checkpoint(str(out_b / "model.pt"), device="cpu")
    anchor_model, _ = load_checkpoint(str(out_c / "model.pt"), device="cpu")
    torch.manual_seed(123)
    features = torch.randn(32, OBS_FLOATS)
    cards_t = torch.randint(0, 4, (32, OBS_CARDS), dtype=torch.long)

    def move_logits(model):
        with torch.no_grad():
            return model.forward_bc(features, cards_t, None)[0][:, 196:245].numpy()

    init_mv = move_logits(init_model)
    drift_base = np.abs(move_logits(base_model) - init_mv).mean()
    drift_anchor = np.abs(move_logits(anchor_model) - init_mv).mean()
    assert drift_anchor < 0.85 * drift_base, (drift_anchor, drift_base)

    rep = json.loads((out_c / "report.json").read_text(encoding="utf-8"))
    last = rep["train"]["curve"][-1]["move_anchor"]
    assert last is not None and np.isfinite(last)
    assert float(last) > 0.0
    _model, meta = load_checkpoint(str(out_c / "model.pt"), device="cpu")
    assert float(meta["bc_move_anchor_coef"]) == pytest.approx(50.0)
    assert float(meta["bc_move_anchor_last"]) == pytest.approx(float(last))


# ══════════════════════════════════════════════════════════════════════════
# 4. 10 类路径与原 9 类 type CE 兼容
# ══════════════════════════════════════════════════════════════════════════
def test_ten_class_path_compatible_with_nine_class_data(tmp_path):
    cards = _write_cards(tmp_path / "cards.json")
    samples_path = _write_jsonl(tmp_path / "bc_norepo.jsonl.gz", _rows_norepo(120))
    samples = load_bc_samples(samples_path, cards_path=cards,
                              action_types=TYPES_10)
    assert len(samples) == 120
    dist = samples.class_distribution()
    assert dist[BC_REPOSITION_TYPE] == 0
    assert samples.class_counts.shape == (10,)

    idx = np.arange(60)
    batch = bc_obs_batch(samples, indices=idx)
    assert int(np.max(batch.class_ids)) <= 8
    torch.manual_seed(2)
    logits = torch.randn(idx.size, N_ACTIONS)
    counts = np.ones(10, dtype=np.int64)
    hier = bc_hier_loss(logits, batch.type_ids, batch.class_ids,
                        action_mask=batch.action_mask, class_counts=counts,
                        n_types=10)
    assert hier["type_logits"].shape == (idx.size, 10)
    assert torch.isfinite(hier["type_loss"])
    assert torch.isfinite(hier["loss"])
    per = torch.nn.functional.cross_entropy(
        hier["type_logits"],
        torch.as_tensor(batch.class_ids, dtype=torch.long), reduction="none")
    assert torch.allclose(hier["type_loss"], per.mean(), atol=1e-6)

    # 9 类 type_ids 也能走 10 类损失（第 10 类为空 -> 有限哨兵，不 NaN）
    tids9 = bc_type_ids(samples, idx)
    assert np.all(tids9[:, BC_MOVE_SLICE] == 9)   # 10 类表的 Move 段 = 第 10 类
    hier10 = bc_hier_loss(logits, tids9, batch.class_ids,
                          action_mask=batch.action_mask, class_counts=counts,
                          n_types=10)
    assert torch.isfinite(hier10["loss"])

    # SimpleNamespace 没有 action_types -> 按默认 9 类处理（向后兼容）
    samples9 = load_bc_samples(samples_path, cards_path=cards,
                               action_types=bc_action_types(False))
    tids9_default = bc_type_ids(samples9, idx)
    assert np.all(tids9_default[:, BC_MOVE_SLICE] == -1)
    simple = SimpleNamespace(
        card_table=samples9.card_table, hand=samples9.hand[idx],
        hand_present=samples9.hand_present[idx],
        action_index=samples9.action_index[idx],
        action_class=samples9.action_class[idx])
    tids_simple = bc_type_ids(simple, np.arange(idx.size))
    assert np.array_equal(tids_simple, tids9_default)
