"""复利 BC 蒸馏（``scripts/train_compound_bc.py`` / ``scripts/eval_compound_bc.py``）单测。

覆盖（对应 ``docs/COMPOUND_BC.md`` §5 的验收项）：
1. npz 字段加载：两种观测布局（合并 3351 / 分开 cards）、mask 的 bool/uint8/float、
   缺字段与坏形状必须**显式报错**（不能静默跑歪）；
2. mask 语义：非法动作被丢弃并计数、``mask`` 在 CE 里真的把非法位排除；
3. CE 与手算一致：numpy 参考实现 vs 手推公式、torch 实现 vs numpy（运行期守卫同款）；
4. holdout 按局切（同一局的动作不跨 train/val），比例 ≈ 5%；
5. 两种尺寸参数量：0.667M（d128×2）/ 14.8M（d384×8）；
6. **默认路径不改变旧行为**：CLI 默认值、只写 ``--out``、评测配置与教师
   ``compound_script.group_configs()`` 逐字同参、旧共享模块未被 import 修改。

需要 ``torch``；需要引擎的用例（配置/沙盒）各自 ``importorskip("hsbg_engine")``。
"""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("torch")

import train_compound_bc as T  # noqa: E402
import eval_compound_bc as V  # noqa: E402

NF, NC, NA = T.OBS_FLOATS, T.OBS_CARDS, T.N_ACTIONS


def _obs(n: int, seed: int = 0, *, combined: bool = True):
    rng = np.random.default_rng(seed)
    feats = rng.normal(0.0, 1.0, size=(n, NF)).astype(np.float32)
    cards = rng.integers(0, 512, size=(n, NC)).astype(np.float32)
    obs = np.concatenate([feats, cards], axis=1) if combined else feats
    return obs, cards


def _mask_action(n: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    mask = np.zeros((n, NA), dtype=bool)
    mask[:, 0] = True
    for i in range(n):
        mask[i, rng.choice(np.arange(1, NA), size=3, replace=False)] = True
    action = np.asarray([int(rng.choice(np.flatnonzero(mask[i]))) for i in range(n)],
                        dtype=np.int64)
    return mask, action


def _write_npz(path, *, combined=True, mask_dtype=np.bool_, n=24, seed=0, soft=True):
    obs, cards = _obs(n, seed, combined=combined)
    mask, action = _mask_action(n, seed)
    payload = {"obs": obs, "action": action, "mask": mask.astype(mask_dtype)}
    if not combined:
        payload["cards"] = cards
    if soft:
        p = np.zeros((n, NA), dtype=np.float32)
        for i in range(n):
            p[i, action[i]] = 0.5
            rest = np.flatnonzero(mask[i])
            rest = rest[rest != action[i]]
            p[i, rest] = 0.5 / rest.size
        payload["soft"] = p
    payload["tier"] = np.full(n, 5, dtype=np.int64)
    payload["turn"] = np.arange(n) % 15 + 1
    payload["gold"] = np.full(n, 12, dtype=np.int64)
    payload["episode_id"] = np.arange(n) // 8
    payload["final_t15_sigma"] = np.linspace(800, 5200, n)
    payload["r12_15"] = np.linspace(0.7, 2.2, n)
    np.savez_compressed(path, **payload)
    return path


# ── 1. npz 加载 ─────────────────────────────────────────────────────────────


def test_load_combined_obs_splits_exactly(tmp_path):
    p = _write_npz(tmp_path / "a.npz", combined=True)
    d = T.load_npz(str(p))
    assert d["obs"].shape == (24, NF) and d["obs"].dtype == np.float32
    assert d["cards"].shape == (24, NC) and d["cards"].dtype == np.int64
    assert d["mask"].dtype == np.bool_ and d["mask"].shape == (24, NA)
    assert d["action"].dtype == np.int64
    # 合并布局的后 124 列必须逐位变回整数（不能被 float 截断）
    assert np.array_equal(d["cards"], np.rint(_obs(24)[1]).astype(np.int64))
    assert d["soft"].shape == (24, NA) and d["soft"].dtype == np.float32
    # soft 在 mask 外严格 0，行和为 1
    assert (d["soft"][~d["mask"]] == 0).all()
    assert np.allclose(d["soft"].sum(axis=1), 1.0, atol=1e-5)


def test_load_separate_cards_and_mask_dtypes(tmp_path):
    for dt in (np.uint8, np.float32, np.int64):
        p = _write_npz(tmp_path / f"m_{np.dtype(dt).name}.npz", combined=False,
                       mask_dtype=dt)
        d = T.load_npz(str(p))
        assert d["mask"].dtype == np.bool_, dt
        assert d["mask"].sum(axis=1).min() >= 1


@pytest.mark.parametrize("field", ["mask", "action"])
def test_load_missing_field_raises(tmp_path, field):
    p = _write_npz(tmp_path / "a.npz")
    with np.load(p) as z:
        d = {k: z[k] for k in z.files}
    d.pop(field)
    bad = tmp_path / "bad.npz"
    np.savez_compressed(bad, **d)
    with pytest.raises(ValueError, match=field):
        T.load_npz(str(bad))


def test_load_bad_obs_width_raises(tmp_path):
    d = {"obs": np.zeros((4, 100), dtype=np.float32), "action": np.zeros(4, np.int64),
         "mask": np.ones((4, NA), dtype=bool)}
    bad = tmp_path / "bad.npz"
    np.savez_compressed(bad, **d)
    with pytest.raises(ValueError, match="列数"):
        T.load_npz(str(bad))


def test_load_row_without_legal_action_raises(tmp_path):
    mask, action = _mask_action(8)
    mask[2] = False
    d = {"obs": _obs(8)[0], "action": action, "mask": mask}
    bad = tmp_path / "bad.npz"
    np.savez_compressed(bad, **d)
    with pytest.raises(ValueError, match="没有任何合法动作"):
        T.load_npz(str(bad))


def test_load_dataset_dir_and_glob(tmp_path):
    for i in range(3):
        _write_npz(tmp_path / f"s{i}.npz", seed=i)
    d, files = T.load_dataset(str(tmp_path))
    assert d["action"].shape[0] == 72 and len(files) == 3
    assert all(len(f["sha256_8"]) == 8 for f in files)
    d2, files2 = T.load_dataset(str(tmp_path / "*.npz"))
    assert d2["action"].shape[0] == 72 and len(files2) == 3
    with pytest.raises(FileNotFoundError):
        T.load_dataset(str(tmp_path / "nope"))


def test_load_teacher_layout_fp16_split_and_ep_stats(tmp_path):
    """教师真实布局：features float16 + cards int16 + ep_* 整局数组 + ep_split。"""
    n, n_ep = 40, 5
    rng = np.random.default_rng(5)
    feats = rng.normal(0.0, 1.0, size=(n, NF)).astype(np.float16)   # 必须**不**被升成 fp32
    cards = rng.integers(0, 512, size=(n, NC)).astype(np.int16)
    mask, action = _mask_action(n, 5)
    eid = np.repeat(np.arange(n_ep), n // n_ep).astype(np.int32)
    p = tmp_path / "teacher.npz"
    np.savez_compressed(
        p, features=feats, cards=cards, mask=mask, action=action.astype(np.uint8),
        turn=np.ones(n, np.uint8), tier=np.ones(n, np.uint8),
        gold=np.ones(n, np.int16), episode_id=eid,
        ep_sigma_t12=np.arange(n_ep, dtype=np.int32) * 100 + 500,
        ep_sigma_t15=np.arange(n_ep, dtype=np.int32) * 200 + 1500,
        ep_r12_15=np.linspace(1.0, 2.0, n_ep).astype(np.float32),
        ep_split=np.asarray([0, 0, 0, 0, 1], dtype=np.uint8))
    d = T.load_npz(str(p))
    assert d["obs"].dtype == np.float16                       # 不做无谓的 2× 内存
    assert d["cards"].dtype == np.int64
    # 整局标签摊平到逐决策
    assert np.array_equal(d["final_t15_sigma"],
                          (np.arange(n_ep) * 200 + 1500)[d["episode_id"]])
    want_r12 = np.linspace(1.0, 2.0, n_ep).astype(np.float32)[d["episode_id"]]
    assert np.array_equal(d["r12_15"], want_r12)
    assert np.array_equal(d["is_val"], d["episode_id"] == 4)
    tr, va = T.split_indices(n, 0.05, 0, d["episode_id"], d["is_val"])
    assert set(d["episode_id"][va].tolist()) == {4}           # 官方切分优先于 holdout
    assert set(d["episode_id"][tr].tolist()) == {0, 1, 2, 3}


def test_combined_float16_rejected(tmp_path):
    """合并布局 + float16 会丢卡牌 id → 必须报错而不是静默跑歪。"""
    d = {"obs": np.zeros((4, T.OBS_TOTAL), dtype=np.float16),
         "action": np.zeros(4, np.int64), "mask": np.ones((4, NA), dtype=bool)}
    bad = tmp_path / "bad.npz"
    np.savez_compressed(bad, **d)
    with pytest.raises(ValueError, match="float16"):
        T.load_npz(str(bad))


# ── 2. mask 语义 / 非法动作 ─────────────────────────────────────────────────


def test_filter_drops_illegal_action(tmp_path):
    p = _write_npz(tmp_path / "a.npz")
    d = T.load_npz(str(p))
    d["action"] = d["action"].copy()
    d["action"][3] = 200              # 该行 mask[200] 一定 False
    d["action"][7] = NA + 5           # 越界
    out, stats = T.filter_dataset(d)
    assert stats["rows_raw"] == 24 and stats["rows_illegal_dropped"] == 2
    assert out["action"].shape[0] == 22
    assert all(out["mask"][i, out["action"][i]] for i in range(22))


def test_filter_min_sigma_keeps_high_only(tmp_path):
    p = _write_npz(tmp_path / "a.npz")
    d = T.load_npz(str(p))
    out, stats = T.filter_dataset(d, min_sigma=3000.0)
    assert stats["rows_low_sigma_dropped"] > 0
    assert (out["final_t15_sigma"] >= 3000).all()
    assert out["action"].shape[0] == stats["rows_used"]


# ── 3. CE 与手算一致 ───────────────────────────────────────────────────────


def _hand_ce(logits, mask, a):
    """手推：masked softmax 后取 -log q(a)。"""
    idx = np.flatnonzero(mask)
    z = logits[idx]
    mx = z.max()
    logq = z - (mx + math.log(np.exp(z - mx).sum()))
    return -float(logq[list(idx).index(a)])


def test_masked_ce_hand_calc_simple():
    logits = np.asarray([[0.0, 1.0, 2.0]], dtype=np.float64)
    mask = np.ones((1, 3), dtype=bool)
    ce = T.masked_ce_numpy(logits, mask, np.asarray([2]))
    want = -math.log(math.exp(2) / (math.exp(0) + math.exp(1) + math.exp(2)))
    assert abs(ce[0] - want) < 1e-12
    # 均匀 logits + 3 个合法动作 → CE = log 3
    ce2 = T.masked_ce_numpy(np.zeros((1, 3)), mask, np.asarray([0]))
    assert abs(ce2[0] - math.log(3.0)) < 1e-12


def test_masked_ce_ignores_illegal_positions():
    """非法位即使 logits 很大也不该影响 CE（= masked_fill(-1e9) 的语义）。"""
    base = np.asarray([[0.0, 0.5, 1.0, 2.0]], dtype=np.float64)
    mask = np.asarray([[True, False, True, False]])
    a = np.asarray([2])
    ce_hi = T.masked_ce_numpy(base, mask, a)
    bumped = base.copy()
    bumped[0, 1] = 1e6
    bumped[0, 3] = 1e6
    ce_hi2 = T.masked_ce_numpy(bumped, mask, a)
    assert abs(ce_hi[0] - ce_hi2[0]) < 1e-12
    assert abs(ce_hi[0] - _hand_ce(base[0], mask[0], 2)) < 1e-12


def test_masked_ce_soft_label_matches_manual():
    logits = np.asarray([[0.2, -0.3, 1.1]], dtype=np.float64)
    mask = np.ones((1, 3), dtype=bool)
    soft = np.asarray([[0.5, 0.3, 0.2]], dtype=np.float64)
    ce = T.masked_ce_numpy(logits, mask, np.asarray([0]), soft=soft)
    z = logits[0]
    logq = z - (z.max() + math.log(np.exp(z - z.max()).sum()))
    assert abs(ce[0] - float(-(soft[0] * logq).sum())) < 1e-12


def test_torch_ce_matches_numpy_random():
    torch = pytest.importorskip("torch")
    rng = np.random.default_rng(7)
    logits = rng.normal(0.0, 2.0, size=(16, NA)).astype(np.float32)
    mask = np.zeros((16, NA), dtype=bool)
    mask[:, 0] = True
    for i in range(16):
        mask[i, rng.choice(np.arange(1, NA), size=4, replace=False)] = True
    action = np.asarray([int(rng.choice(np.flatnonzero(mask[i]))) for i in range(16)])
    want = T.masked_ce_numpy(logits, mask, action)
    from hsbg.az.train.ppo import masked_log_softmax_torch
    logp = masked_log_softmax_torch(
        torch.from_numpy(logits), torch.from_numpy(mask))
    got = (-logp.gather(1, torch.from_numpy(action).unsqueeze(1)).squeeze(1)
           ).double().numpy()
    assert np.allclose(got, want, atol=2e-6)


def test_ce_selfcheck_runs_on_real_data(tmp_path):
    p = _write_npz(tmp_path / "a.npz", n=32)
    d = T.load_npz(str(p))
    rep = T.ce_selfcheck(d, "cpu", pytest.importorskip("torch"))
    assert rep["max_abs_delta"] <= rep["atol"]


# ── 4. holdout 按局切 ──────────────────────────────────────────────────────


def test_action_weights_manual_per_kind():
    """窄加权：只给 buy_amp×4 / buy_carrier×2，其余类必须保持 1.0（不稀释 refresh 等）。"""
    n = 60
    kind = np.asarray([1, 2, 5, 8, 9, 10, 4] * (n // 7 + 1))[:n]
    data = {"action_kind": kind}
    w, info = T.action_weights(data, mode="manual", coef=8.0,
                               kinds="buy_amp:4,buy_carrier:2")
    assert w.shape == (n,)
    assert set(np.unique(w).tolist()) == {1.0, 2.0, 4.0}
    assert w[kind == 1].min() == 4.0 and w[kind == 2].min() == 2.0
    assert w[kind == 9].max() == 1.0 and w[kind == 10].max() == 1.0   # refresh/end_turn 不动
    assert info["kinds"] == ["buy_amp:4", "buy_carrier:2"]
    # 不给系数时回落到 --action-weight-coef
    w2, info2 = T.action_weights({"action_kind": kind}, mode="manual", coef=6.0,
                                 kinds="upgrade")
    assert w2[kind == 8].min() == 6.0 and info2["kinds"] == ["upgrade:6"]
    # off / rarity 的边界
    assert T.action_weights({"action_kind": kind}, mode="off")[0] is None
    with pytest.raises(ValueError):
        T.action_weights({"action_kind": kind}, mode="manual", kinds="nope")


def test_subsample_episodes_by_episode_and_deterministic():
    """path@frac 必须按「局」抽样且确定性（控制 DAgger:base 混比用）。"""
    eid = np.repeat(np.arange(100), 5)
    d = {"action": np.zeros(eid.size, np.int64), "episode_id": eid}
    out = T._subsample_episodes(d, 0.33)
    kept = np.unique(out["episode_id"])
    assert 20 <= kept.size <= 45                       # ≈33 局
    assert out["action"].shape[0] == kept.size * 5     # 整局保留，不切碎
    again = T._subsample_episodes(d, 0.33)
    assert np.array_equal(out["action"], again["action"])
    assert T._subsample_episodes(d, 0.33)["episode_id"].size < eid.size
    # frac>=1 原样返回
    assert T._subsample_episodes(d, 1.0)["action"].size == eid.size


def test_load_dataset_frac_syntax(tmp_path):
    for i in range(4):
        _write_npz(tmp_path / f"s{i}.npz", n=40, seed=i)   # 每个文件 5 局 × 8 决策
    full, files0 = T.load_dataset(str(tmp_path))
    part, files1 = T.load_dataset(f"{tmp_path}@0.5")
    assert full["action"].shape[0] == 160
    assert part["action"].shape[0] < 160
    assert files1[0]["frac"] == 0.5 and files0[0]["frac"] == 1.0
    # 混比写法：DAgger@0.33 + base 全量 = 修正项而不是主分布
    base = tmp_path / "s1.npz"
    one = tmp_path / "s0.npz"
    n_half = T._subsample_episodes(T.load_npz(str(one)), 0.5)["action"].shape[0]
    mixed, f2 = T.load_dataset(f"{one}@0.5,{base}")
    assert mixed["action"].shape[0] == n_half + 40
    assert [f["frac"] for f in f2] == [0.5, 1.0]



    eid = np.repeat(np.arange(20), 10)          # 20 局 × 10 动作
    tr, va = T.split_indices(eid.size, 0.05, 3, eid)
    assert va.size == 10                         # 至少 5% = 10 行
    assert not (set(eid[tr]) & set(eid[va]))
    assert tr.size + va.size == eid.size
    # 同一局的 10 条动作整体落在同一侧
    assert len(np.unique(eid[va])) == 1


def test_holdout_rowwise_when_no_episode():
    tr, va = T.split_indices(200, 0.05, 0, None)
    assert va.size == 10 and tr.size == 190
    assert not (set(tr.tolist()) & set(va.tolist()))
    tr0, va0 = T.split_indices(200, 0.0, 0, None)
    assert va0.size == 0 and tr0.size == 200


def test_holdout_reproducible():
    eid = np.repeat(np.arange(40), 5)
    a = T.split_indices(eid.size, 0.05, 11, eid)
    b = T.split_indices(eid.size, 0.05, 11, eid)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


# ── 5. 模型尺寸 ────────────────────────────────────────────────────────────


def test_param_counts_match_target_sizes():
    small = T.build_model("entity", 128, 2, 8)
    n_small = sum(p.numel() for p in small.parameters())
    assert 0.60e6 <= n_small <= 0.75e6, n_small
    assert 0.66e6 <= n_small <= 0.68e6, n_small          # 目标 0.667M
    main = T.build_model("entity", 384, 8, 8)
    n_main = sum(p.numel() for p in main.parameters())
    assert 14.5e6 <= n_main <= 15.2e6, n_main             # 目标 14.9M


def test_size_name_presets():
    assert T.size_name(128, 2) == "small"
    assert T.size_name(384, 8) == "main"
    assert T.size_name(256, 4) == "d256x4"


# ── 6. 端到端训练 + 默认不破坏旧行为 ──────────────────────────────────────


def test_cli_defaults_unchanged():
    a = T.build_parser().parse_args([])
    assert a.data == "data/scaling/compound_bc" and a.out == "runs/compound_bc"
    assert (a.arch, a.d_model, a.n_layers, a.n_heads) == ("entity", 128, 2, 8)
    assert (a.epochs, a.lr, a.batch_size, a.holdout) == (2, 3e-5, 256, 0.05)
    assert a.ce_selfcheck == 1 and a.soft == "auto"
    v = V.build_parser().parse_args(["--checkpoint", "x.pt"])
    assert v.games == 32 and v.configs == "fixed20,fixed30"     # 现实 + 旧口径两档
    assert v.seed0 == 910000 and v.sample == 1 and v.carrier_audit == 1
    assert v.gate_config == "fixed20"                            # 主判据 = 现实收入档
    # 教师参考：groups.json（28 局，未过滤）在前、meta.json（240 局）在后覆盖
    assert v.teacher_ref.split(",")[0].endswith("groups.json")
    assert v.teacher_ref.split(",")[-1].endswith("meta.json")


def test_train_end_to_end_writes_only_out(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_npz(data_dir / "a.npz", n=64, seed=1)
    _write_npz(data_dir / "b.npz", n=64, seed=2)
    out = tmp_path / "run"
    rc = T.main(["--data", str(data_dir), "--out", str(out), "--device", "cpu",
                 "--d-model", "64", "--n-layers", "1", "--n-heads", "4",
                 "--epochs", "1", "--batch-size", "16", "--lr", "1e-3",
                 "--size-name", "smoke", "--ce-selfcheck", "1"])
    assert rc == 0
    files = sorted(p.name for p in out.iterdir())
    assert files == ["ckpt_smoke.pt", "log_smoke.jsonl", "meta_smoke.json"], files
    meta = json.loads((out / "meta_smoke.json").read_text(encoding="utf-8"))
    assert meta["n_train"] + meta["n_val"] == 128
    assert meta["n_val"] >= 1                       # 5% holdout 非空
    assert 0.0 <= meta["top1"] <= 1.0
    assert math.isfinite(meta["ce"]) and meta["ce"] > 0
    assert meta["params"] == sum(p.numel() for p in
                                 T.build_model("entity", 64, 1, 4).parameters())
    assert meta["trained_by"] == "scripts/train_compound_bc.py"
    # 逐 epoch 日志与 history 对齐
    hist = [json.loads(x) for x in
            (out / "log_smoke.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(hist) == 1 and hist[0]["rows"] > 0 and "val" in hist[0]
    # checkpoint 能被主栈 load 回来（权重可回完整游戏的前提）
    from hsbg.az.train.model import load_checkpoint
    model, m2 = load_checkpoint(str(out / "ckpt_smoke.pt"), device="cpu")
    assert m2["d_model"] == 64 and sum(p.numel() for p in model.parameters()) == \
        meta["params"]


def test_train_soft_off_disables_soft_loss(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_npz(data_dir / "a.npz", n=32)
    out = tmp_path / "run"
    rep = T.train(T.build_parser().parse_args(
        ["--data", str(data_dir), "--out", str(out), "--device", "cpu",
         "--d-model", "64", "--n-layers", "1", "--n-heads", "4", "--epochs", "1",
         "--batch-size", "16", "--soft", "off", "--ce-selfcheck", "0"]))
    meta = json.loads(open(rep["meta"], encoding="utf-8").read())
    assert meta["soft_labels"] is False
    # 没有 soft 字段却强制 --soft on → 必须显式报错（不能静默退化成硬标签）
    hard_dir = tmp_path / "hard"
    hard_dir.mkdir()
    _write_npz(hard_dir / "a.npz", n=16, soft=False)
    with pytest.raises(ValueError, match="soft"):
        T.main(["--data", str(hard_dir), "--out", str(out), "--device", "cpu",
                "--soft", "on", "--d-model", "64", "--n-layers", "1",
                "--n-heads", "4", "--epochs", "1", "--ce-selfcheck", "0"])


def test_make_synthetic_roundtrip(tmp_path):
    paths = T.make_synthetic(str(tmp_path), 40, n_episodes=4, seed=3)
    d = T.load_npz(paths[0])
    assert d["action"].shape[0] == 40 and "soft" in d
    assert d["episode_id"].min() == 0 and d["episode_id"].max() <= 3
    assert all(d["mask"][i, d["action"][i]] for i in range(40))


# ── 7. 评测脚本：配置与教师同参 / 判据 / 报告 ──────────────────────────────


def test_eval_configs_match_teacher():
    pytest.importorskip("hsbg_engine")
    import compound_script as C
    ours = V.build_configs()
    theirs = C.group_configs()
    for mine, teacher in (("fixed30", "S0"), ("growth2", "S2"), ("growth3", "S3")):
        assert ours[mine].__dict__ == theirs[teacher].__dict__, mine
    # 现实收入档：只是 gold_per_turn 30 -> 20，其余与 S0 同参
    fixed20, fixed30 = ours["fixed20"], ours["fixed30"]
    d20 = dict(fixed20.__dict__)
    d30 = dict(fixed30.__dict__)
    assert d20.pop("gold_per_turn") == 20 and d30.pop("gold_per_turn") == 30
    assert d20 == d30


def test_gate_profiles():
    # 三档阈值必须与任务口径一致（2026-11-01 修订：现实档 Σ = 教师 87%、r12 = 教师、
    # goldens = 教师水平 1.45；growth 档 amp≥10 / Σ≥2400 / r12≥1.4）
    R, G, L = V.GATE_PROFILES["realistic"], V.GATE_PROFILES["growth"], \
        V.GATE_PROFILES["legacy"]
    assert (R["amp_buys_mean"], R["sigma_t15_p50"], R["r12_15_p50"]) == (5.5, 1500.0, 1.55)
    assert (G["amp_buys_mean"], G["sigma_t15_p50"], G["r12_15_p50"]) == (10.0, 2400.0, 1.4)
    assert G["goldens_mean"] == R["goldens_mean"] == 1.45
    assert L == {"amp_buys_mean": 5.0, "goldens_mean": 1.45, "r12_15_p50": 2.0,
                 "sigma_t15_p50": 3000.0}
    assert V.CONFIG_PROFILE == {"fixed20": "realistic", "fixed30": "legacy",
                               "growth2": "growth", "growth3": "growth"}
    # 现实档教师基线（roll8）：1716 / 6.74 / 1.55
    t = V.TEACHER_STATIC["fixed20"]
    assert (t["sigma_t15_p50"], t["amp_buys_mean"], t["r12_15_p50"]) == (1716.0, 6.74, 1.55)
    # 刚好达线算过、差一点算不过
    ok = {"amp_buys_mean": 5.5, "goldens_mean": 1.45, "r12_15_p50": 1.55,
          "sigma_t15_p50": 1500.0}
    assert V.evaluate_gates(ok, "realistic")["pass_all"] is True
    assert V.evaluate_gates(ok, "growth")["pass_all"] is False     # 同一组数在 growth 更严


def test_eval_gates_thresholds():
    # 用 realistic 档阈值构造「刚好达标」的一组数（growth 档更严，另有用例覆盖）
    ok = {"amp_buys_mean": 5.5, "goldens_mean": 1.45, "r12_15_p50": 1.55,
          "sigma_t15_p50": 1500.0}
    assert V.evaluate_gates(ok, "realistic")["pass_all"] is True
    for key in ok:
        bad = dict(ok)
        bad[key] = ok[key] * 0.99
        g = V.evaluate_gates(bad, "realistic")
        assert g["pass_all"] is False, key
        assert g[key]["pass"] is False


def test_eval_gates_growth_stricter():
    ok = {"amp_buys_mean": 5.5, "goldens_mean": 1.45, "r12_15_p50": 1.55,
          "sigma_t15_p50": 1500.0}
    g = V.evaluate_gates(ok, "growth")
    assert g["pass_all"] is False
    assert g["amp_buys_mean"]["threshold"] == 10.0
    assert g["sigma_t15_p50"]["threshold"] == 2400.0
    # 默认 profile = growth（向后兼容）
    assert V.evaluate_gates(ok)["amp_buys_mean"]["threshold"] == 10.0


def test_teacher_reference_static_and_json(tmp_path):
    ref, src = V.teacher_reference("")
    assert ref["fixed30"]["sigma_t15_p50"] == 1820
    assert "COMPOUND_SCRIPT" in src
    p = tmp_path / "groups.json"
    p.write_text(json.dumps({"S0": {"sigma_t15_p50": 1999, "amp_buys_mean": 9.5,
                                    "games": 28},
                             "S3": {"sigma_t15_p50": 5000, "r12_15_p50": 1.3}}),
                 encoding="utf-8")
    ref2, src2 = V.teacher_reference(str(p))
    assert ref2["fixed30"]["sigma_t15_p50"] == 1999
    assert ref2["fixed30"]["amp_buys_mean"] == 9.5
    assert ref2["growth3"]["sigma_t15_p50"] == 5000
    assert ref2["growth3"]["r12_15_p50"] == 1.3
    assert "groups.json" in src2
    assert ref2["growth2"]["sigma_t15_p50"] == 2094      # 未覆盖的沿用兜底表


def test_teacher_reference_bc_dataset_meta(tmp_path):
    """BC 数据集 meta.json：用 all_run（240 局、不过滤）当主数字，别拿筛选后的冒充。"""
    p = tmp_path / "meta.json"
    p.write_text(json.dumps({"kind": "compound_bc_dataset", "configs": {
        "s0_fixed30": {
            "games_run": 240, "games_kept": 126,
            "amp_total_mean": 8.85, "goldens_mean": 1.46, "spells_mean": 80.0,
            "t15_sigma": {"p50": 2600.0, "p90": 9000.0},          # 筛选后（偏高）
            "t15_sigma_all_run": {"p50": 2100.0, "p90": 8000.0},  # 全量（主数字）
        },
        "s3_growth_buff3": {
            "games_run": 240, "games_kept": 170, "amp_total_mean": 9.14,
            "goldens_mean": 1.51, "spells_mean": 86.7,
            "t15_sigma_all_run": {"p50": 2519.5, "p90": 8639.5},
        }}}, ensure_ascii=False), encoding="utf-8")
    ref, src = V.teacher_reference(str(p))
    assert ref["fixed30"]["sigma_t15_p50"] == 2100.0         # all_run 优先
    assert ref["fixed30"]["amp_buys_mean"] == 8.85
    assert ref["fixed30"]["goldens_mean"] == 1.46
    assert ref["growth3"]["sigma_t15_p50"] == 2519.5
    assert ref["growth3"]["spells_mean"] == 86.7
    assert ref["growth2"]["sigma_t15_p50"] == 2094           # 无对应组 → 兜底表
    assert "meta.json" in src
    # 逗号分隔两份：后者覆盖前者（默认串就是 groups.json 在前、meta.json 在后）
    g = tmp_path / "groups.json"
    g.write_text(json.dumps({"S0": {"sigma_t15_p50": 1820, "r12_15_p50": 1.14,
                                    "goldens_p50": 1.0}}), encoding="utf-8")
    ref3, _ = V.teacher_reference(f"{g},{p}")
    assert ref3["fixed30"]["sigma_t15_p50"] == 2100.0        # meta 后生效
    assert ref3["fixed30"]["r12_15_p50"] == 1.14             # 只有 groups 提供


def test_make_report_and_gap(tmp_path):
    pytest.importorskip("hsbg_engine")
    from hsbg.az.train.economy_sandbox import SandboxConfig
    cfg = SandboxConfig(turns=15, gold_mode="fixed", gold_per_turn=30, action_cap=40,
                        num_players=8, trinkets=True, lobby_types=())
    eps = []
    for i in range(8):
        eps.append({
            "sigma_t12": 1000 + 100 * i, "sigma_t15": 2000 + 200 * i,
            "goldens_t15": 2 + (i % 3), "carriers_t15": 1, "spells_t15": 50,
            "tavern_buff_t15": 4, "tier_final": 5, "gold_total_income": 450,
            "decisions": 300, "return": 1.0, "casts_on_carrier": i % 4,
            "amp_total": 6 + (i % 2), "rows": [],
        })
    agg = {"illegal": 0, "legit": 100, "amp_hist": {"Brann": 30, "Titus": 20},
           "amp_mean": 6.5, "amp_any_rate": 1.0, "secs": 1.0}
    rep = V.make_report(eps, agg, cfg, V.TEACHER_STATIC["fixed30"], name="fixed30")
    assert rep["games"] == 8
    assert abs(rep["r12_15_p50"] - float(np.percentile(
        [e["sigma_t15"] / e["sigma_t12"] for e in eps], 50))) < 1e-9
    assert rep["amp_buys_mean"] == 6.5 and rep["amp_by_card"]["Brann"] == 30
    assert rep["goldens_mean"] == pytest.approx(np.mean([2, 3, 4, 2, 3, 4, 2, 3]))
    assert rep["legal_rate"] == 1.0
    assert rep["teacher"]["sigma_t15_p50"] == 1820
    assert rep["teacher_delta"]["sigma_t15_p50"] == pytest.approx(
        rep["sigma_t15_p50"] - 1820)
    assert set(rep["gate"]) >= set(V.GATE_PROFILES["legacy"]) | {"pass_all"}
    # 该 8 局存档：amp 6.5 ≥5（legacy 档）/ goldens 均值 2.75 ≥1.45 → 这两项过；
    # t15 p50 与 r12 达不到 legacy 阈值 → overall 不过
    assert rep["gate"]["amp_buys_mean"]["pass"] is True
    assert rep["gate"]["goldens_mean"]["pass"] is True
    assert rep["gate"]["sigma_t15_p50"]["pass"] is False
    assert rep["gate"]["pass_all"] is False
    for name in V.TEACHER_STATIC:
        assert V.TEACHER_STATIC[name]["amp_buys_mean"] >= 5.0


def test_shared_modules_imported_as_is():
    """默认路径不破坏旧行为：本脚本不 import 训练脚本、不动共享常量。"""
    src_t = open(os.path.join(ROOT, "scripts", "train_compound_bc.py"),
                 encoding="utf-8").read()
    src_v = open(os.path.join(ROOT, "scripts", "eval_compound_bc.py"),
                 encoding="utf-8").read()
    for src in (src_t, src_v):
        # 只查**真 import 语句**（docstring 里提到这些文件名是说明，不是依赖）
        assert "import train_economy_sandbox" not in src
        assert "from train_economy_sandbox" not in src
    assert (T.OBS_FLOATS, T.OBS_CARDS, T.N_ACTIONS) == (3227, 124, 245)
    assert T.SIZE_PRESETS["small"] == (128, 2, 8)
    assert T.SIZE_PRESETS["main"] == (384, 8, 8)


@pytest.mark.skipif(os.environ.get("COMPOUND_BC_SLOW") != "1",
                    reason="沙盒 2 局 smoke 较慢；COMPOUND_BC_SLOW=1 才跑")
def test_eval_smoke_two_games(tmp_path):
    """真沙盒 2 局（fixed30）：验证整条评测链路能跑通且字段齐全。"""
    pytest.importorskip("hsbg_engine")
    ckpt = tmp_path / "ckpt_smoke.pt"
    from hsbg.az.train.model import build_net, save_checkpoint
    m = build_net(arch="entity", d_model=64, n_layers=1, n_heads=4)
    save_checkpoint(m, str(ckpt), meta={"arch": "entity", "d_model": 64,
                                        "n_layers": 1, "n_heads": 4})
    out = tmp_path / "eval.json"
    rc = V.main(["--checkpoint", str(ckpt), "--games", "2", "--n-envs", "2",
                 "--configs", "fixed30", "--device", "cpu", "--seed0", "910000",
                 "--teacher-ref", "", "--out", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text(encoding="utf-8"))["reports"]["fixed30"]
    assert rep["games"] == 2
    for key in ("sigma_t12_p50", "sigma_t15_p50", "r12_15_p50", "amp_buys_mean",
                "goldens_p50", "goldens_mean", "carrier_rate",
                "casts_on_carrier_mean", "spells_p50", "legal_rate", "gate",
                "teacher_delta"):
        assert key in rep, key
    assert out.with_suffix(".md").exists()
