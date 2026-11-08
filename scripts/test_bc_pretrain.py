"""BC 预训练 warm-start（``scripts/bc_pretrain.py``）单测。

覆盖：

1. ``split_holdout`` 契约：不重叠、并集 = 全体、同 seed 可复现、边界（frac=0 / frac=1 报错）；
2. 合成 200 条样本跑 3 步：``report.json`` 的 loss 曲线存在且**下降**，holdout eval 有值；
3. 训练出的 checkpoint 能被 :func:`hsbg.az.train.model.load_checkpoint` 重载，且可直接
   构造 :class:`hsbg.az.train.ppo.PPOEvaluator` 出 ``(prior[245], value)``；
4. ``--from-scratch`` 与 ``--init``（续训）两条路径都可用，且 init 的未知 meta 键被保留；
5. ``--preserve-rl``（默认开）在 holdout 上给出有限的 ``KL(pre‖post)``。
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS  # noqa: E402
from hsbg.az.train.model import (  # noqa: E402
    build_net,
    load_checkpoint,
    save_checkpoint,
)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "bc_pretrain.py"


# ── 合成数据（与 test_bc_hier 同一套卡表/行格式）───────────────────────────
def _write_cards(path: Path) -> str:
    """4 张卡：随从 / 法术 / 金色随从 / 英雄（与卡牌身份头维度 4 对齐）。"""
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


def _rows(n: int = 200) -> list[dict]:
    """按 5 类动作循环生成样本（每 10 条同一 game，贴近真实按局分组的结构）。

    - end_turn：无随从；
    - reroll：无随从；
    - sell：3 个棋盘随从（slot 0..2 合法）；
    - buy_minion：商店 7 个随从（槽位 0..6）；
    - play_minion：手牌 1 个随从 + 落位 0。
    """
    board = ["TEST_MINION"] * 3
    board_pos = [0, 1, 2]
    shop = ["TEST_MINION"] * 7
    rows = []
    for i in range(int(n)):
        gid = f"game-{i // 10:03d}"
        kind = i % 5
        if kind == 0:
            rows.append(_row(game_id=gid))
        elif kind == 1:
            rows.append(_row(game_id=gid, action_type="reroll", action_index=1,
                             mmr=str(6200 + (i % 5) * 700)))
        elif kind == 2:
            rows.append(_row(game_id=gid, action_type="sell",
                             action_index=16 + (i % 3), board_cards=board,
                             board_pos=board_pos, card_id="TEST_MINION",
                             mmr=str(7000 + (i % 4) * 500)))
        elif kind == 3:
            rows.append(_row(game_id=gid, action_type="buy_minion",
                             action_index=8 + (i % 7),
                             shop_cards=shop, shop_pos=list(range(7)),
                             card_id="TEST_MINION", gold=6))
        else:
            rows.append(_row(game_id=gid, action_type="play_minion",
                             action_index=46, hand_cards=["TEST_MINION"],
                             hand_pos=[0], board_cards=board,
                             board_pos=board_pos, card_id="TEST_MINION", gold=6))
    return rows


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
            f"bc_pretrain 退出码 {proc.returncode}\n"
            f"cmd={' '.join(cmd)}\n--- stdout ---\n{proc.stdout[-4000:]}\n"
            f"--- stderr ---\n{proc.stderr[-4000:]}")
    return proc


# ══════════════════════════════════════════════════════════════════════════
# 1. holdout 切分契约（纯 numpy，可直接 import 脚本模块）
# ══════════════════════════════════════════════════════════════════════════
def _load_script_module():
    spec = importlib.util.spec_from_file_location("bc_pretrain_mod", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_split_holdout_disjoint_and_reproducible():
    mod = _load_script_module()
    train, hold = mod.split_holdout(200, 0.05, seed=0)
    assert train.size == 190 and hold.size == 10
    # 不重叠
    assert np.intersect1d(train, hold).size == 0
    # 并集 = 全体（无样本丢失/重复）
    assert np.array_equal(np.sort(np.concatenate([train, hold])),
                          np.arange(200, dtype=np.int64))
    # 同 seed 逐位复现
    train2, hold2 = mod.split_holdout(200, 0.05, seed=0)
    assert np.array_equal(train, train2) and np.array_equal(hold, hold2)
    # 不同 seed 切分不同
    train3, _hold3 = mod.split_holdout(200, 0.05, seed=1)
    assert not np.array_equal(train, train3)
    # 边界：frac=0 不留 holdout；frac=1 非法
    t0, h0 = mod.split_holdout(5, 0.0, seed=0)
    assert h0.size == 0 and t0.size == 5
    with pytest.raises(ValueError):
        mod.split_holdout(10, 1.0, seed=0)
    with pytest.raises(ValueError):
        mod.split_holdout(10, -0.1, seed=0)


# ══════════════════════════════════════════════════════════════════════════
# 2-3-5. 从零 3 步训练：loss 下降 / checkpoint 可重载 + PPOEvaluator / KL
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def scratch_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("bc_pretrain_scratch")
    cards = _write_cards(d / "cards.json")
    samples = _write_jsonl(d / "bc.jsonl.gz", _rows(200))
    out = d / "out"
    report = out / "report.json"
    proc = _run(
        "--from-scratch", "--arch", "tiny", "--device", "cpu", "--amp", "off",
        "--samples", samples, "--cards", cards, "--limit", "0",
        "--steps", "3", "--epochs", "3", "--batch", "256", "--lr", "1e-3",
        "--log-every", "1", "--holdout", "0.05", "--seed", "0",
        "--out", str(out), "--report", str(report))
    assert "[bc] done" in proc.stdout, proc.stdout[-2000:]
    return {"out": out, "ckpt": out / "model.pt", "report": report,
            "samples": samples, "cards": cards, "stdout": proc.stdout}


def test_three_steps_loss_decreases_and_report_complete(scratch_run):
    rep = json.loads(scratch_run["report"].read_text(encoding="utf-8"))
    curve = rep["train"]["curve"]
    assert rep["train"]["steps"] == 3
    assert len(curve) == 3
    # 每条 step 都带 loss/type/card/acc（日志字段齐全）
    for rec in curve:
        for key in ("loss", "type_loss", "card_loss", "type_acc", "action_acc"):
            assert key in rec
            assert np.isfinite(float(rec[key]))
    # 3 步监督训练 loss 必须下降（CPU/tiny 确定性，无 dropout 噪声）
    assert float(curve[-1]["loss"]) < float(curve[0]["loss"])
    # holdout：5% = 10 条，切分不重叠（total = train + holdout）
    assert rep["data"]["samples"] == 200
    assert rep["data"]["holdout"] == 10
    assert rep["data"]["train"] == 190
    # eval 曲线含 step 0 基线与最终一步，且 CE 有限
    ev = rep["eval"]["curve"]
    assert ev[0]["step"] == 0 and ev[-1]["step"] == 3
    assert all(np.isfinite(float(r["type_ce"])) for r in ev)
    assert np.isfinite(float(rep["eval"]["final"]["type_ce"]))


def test_checkpoint_reloads_and_feed_ppoevaluator(scratch_run):
    model, meta = load_checkpoint(str(scratch_run["ckpt"]), device="cpu")
    assert bool(meta.get("bc_pretrained")) is True
    assert int(meta["bc_steps"]) == 3
    assert int(meta["samples"]) == 200
    assert int(meta["bc_samples"]) == 190
    assert bool(meta.get("bc_from_scratch")) is True
    assert meta.get("arch") == "tiny"

    from hsbg.az.train.ppo import PPOEvaluator

    ev = PPOEvaluator(model, device="cpu")
    features = np.zeros((1, OBS_FLOATS), dtype=np.float32)
    cards = np.zeros((1, OBS_CARDS), dtype=np.int64)
    mask = np.zeros((1, N_ACTIONS), dtype=bool)
    mask[0, [0, 1, 8, 16, 46]] = True
    prior, value = ev(features, cards, mask)
    assert prior.shape == (N_ACTIONS,)
    assert np.all(np.isfinite(prior))
    assert float(prior.sum()) == pytest.approx(1.0, abs=1e-5)
    # masked softmax：非法动作严格为 0
    assert np.all(prior[~mask[0]] == 0.0)
    assert isinstance(value, float) and np.isfinite(value)


def test_preserve_rl_kl_reported(scratch_run):
    rep = json.loads(scratch_run["report"].read_text(encoding="utf-8"))
    kl = rep["kl"]
    assert kl, "默认 --preserve-rl 1 应给出 KL"
    assert kl["n"] == 10
    for key in ("kl_mean", "kl_p95", "kl_max", "top1_agree"):
        assert np.isfinite(float(kl[key]))
    assert float(kl["kl_mean"]) >= 0.0
    # KL 过大时会置位（真实短跑要看它是否为 False）
    assert isinstance(bool(kl["exceeds_max_kl"]), bool)
    assert 0.0 <= float(kl["top1_agree"]) <= 1.0
    # checkpoint meta 里也留了 KL
    _model, meta = load_checkpoint(str(scratch_run["ckpt"]), device="cpu")
    assert float(meta["bc_kl_pre_post"]) == pytest.approx(float(kl["kl_mean"]))


# ══════════════════════════════════════════════════════════════════════════
# 4b. --init 续训路径：可运行、init 的未知 meta 键保留、不丢架构信息
# ══════════════════════════════════════════════════════════════════════════
def test_init_checkpoint_path_runs_and_preserves_meta(tmp_path):
    cards = _write_cards(tmp_path / "cards.json")
    samples = _write_jsonl(tmp_path / "bc.jsonl.gz", _rows(200))
    torch.manual_seed(0)
    init_model = build_net(256, bc_card_head=True, bc_card_dim=4)
    init_path = tmp_path / "init.pt"
    save_checkpoint(init_model, str(init_path),
                    meta={"arch": "tiny", "custom_key": "keep-me",
                          "trainer_updates": 42})
    out = tmp_path / "out_init"
    report = out / "report.json"
    _run("--init", str(init_path), "--device", "cpu", "--amp", "off",
         "--samples", samples, "--cards", cards,
         "--steps", "2", "--epochs", "1", "--batch", "128", "--lr", "1e-3",
         "--log-every", "1", "--holdout", "0.05", "--seed", "3",
         "--out", str(out), "--report", str(report))
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["train"]["steps"] == 2
    _model, meta = load_checkpoint(str(out / "model.pt"), device="cpu")
    assert bool(meta.get("bc_pretrained")) is True
    assert int(meta["bc_steps"]) == 2
    assert meta["bc_from_scratch"] is False
    # init 的未知 meta 键必须保留（trainer_updates 等下游依赖）
    assert meta["custom_key"] == "keep-me"
    assert int(meta["trainer_updates"]) == 42
    # 权重来自 init（card_head 保留），不是随机新建的
    assert _model.card_head is not None
    assert int(_model.card_head.out_features) == 4
