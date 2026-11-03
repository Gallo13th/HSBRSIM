"""续训 / 评测链的契约回归（CPU-only；不起训练、不用 GPU、不依赖引擎）。

对应 ``docs/BUG_AUDIT_SOL.md``：

- **P1-1**：``--checkpoint``（model-only ckpt）与 ``--trainer-state``（``PPOTrainer.save``）
  语义不同 —— 前者**没有**任何可续训状态，后者才有；
- **P2-5**：``--trainer-state`` 续训时 CLI ``--lr`` 被 state 覆盖（实际 lr 由 scheduler 延续）；
- **P0-1**：评测在跑时 ``_submit_eval`` 不落 ckpt（``train_entity_sync.py:3450-3454``），
  而 chain 用 ``ls -t eval/ckpt_*.pt | head -1`` 当下一块起点（``chain_300m.sh:38``），
  于是「记账 +20M、实际只到 10M」。

说明：``train_entity_sync.main()`` 内的 ``_save_eval_ckpt/_submit_eval`` 是内嵌函数，
无法直接 import；因此 P0-1 用**文件系统 + 命名口径**复现 shell 侧的选择逻辑（配置级测试），
并把建议的守卫写成断言。
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from hsbg.az.train.model import (  # noqa: E402
    build_net,
    load_checkpoint,
    save_checkpoint,
)
from hsbg.az.train.ppo import PPOConfig  # noqa: E402
from hsbg.az.train.ppo_trainer import PPOTrainer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

#: s61 的真实 state 参数（runs/az_entity_s61/trainer.pt：updates=285, max_updates=3000,
#: lr_min_ratio=0.5, config.lr=1.17e-6）；用于把「续训 lr 应该是多少」钉死。
S61_UPDATES = 285
S61_MAX_UPDATES = 3000
S61_LR_MIN_RATIO = 0.5
S61_BASE_LR = 1.17e-6


def _tiny_net(seed: int = 0):
    """tiny 默认 hidden=256（``save_checkpoint`` 不记录 ``hidden``，``load_checkpoint``
    对 tiny 固定用 256；非默认 hidden 的 tiny ckpt 无法回读，见报告附录 A-3）。"""
    torch.manual_seed(int(seed))
    return build_net(arch="tiny")


def _mini_net(seed: int = 0):
    """32 维 MLP：只用于 PPOTrainer 的 save/load（不经过 load_checkpoint 重建）。"""
    torch.manual_seed(int(seed))
    return build_net(hidden=32, arch="tiny")


def _lr_at(base_lr: float, step: int, max_updates: int, min_ratio: float) -> float:
    """与 ``PPOTrainer`` 的 LambdaLR 同式（ppo_trainer.py:62-67）。"""
    return float(base_lr) * max(float(min_ratio),
                                1.0 - (1.0 - float(min_ratio)) * float(step)
                                / float(max_updates))


# ── 1) --checkpoint：model-only，不可续训 ──────────────────────────────────

def test_model_only_checkpoint_cannot_resume(tmp_path):
    """``--checkpoint`` 落盘内容 = state_dict + meta(+norm)，**不含**续训状态。"""
    model = _tiny_net()
    path = str(tmp_path / "ckpt.pt")
    save_checkpoint(model, path, meta={"arch": "tiny"})
    payload = torch.load(path, map_location="cpu", weights_only=True)

    assert "state_dict" in payload and "meta" in payload
    for key in ("optimizer", "scheduler", "updates", "rng", "bc_rng", "dpo_rng",
                "problem_rng", "extra", "lr_min_ratio", "max_updates"):
        assert key not in payload, (
            f"model-only checkpoint 不应含 {key}：含了就会被误当成可续训（P1-1）")

    model2, meta = load_checkpoint(path, device="cpu")
    assert meta.get("arch") == "tiny"
    assert list(model2.state_dict()) == list(model.state_dict())

    # 语义对照：用 model-only 起 trainer ⇒ updates=0、lr=CLI 值（=「热启动」而非续训）。
    trainer = PPOTrainer(model2, PPOConfig(device="cpu", lr=S61_BASE_LR))
    assert int(trainer.updates) == 0
    assert abs(float(trainer.optimizer.param_groups[0]["lr"]) - S61_BASE_LR) < 1e-15


# ── 2) --trainer-state：精确续训（step/Adam/lr），且 CLI --lr 被覆盖 ─────────

def test_trainer_state_restores_step_optimizer_and_overrides_cli_lr(tmp_path):
    """``PPOTrainer.save/load`` 恢复 updates、Adam 矩、scheduler 位置；
    续训时 CLI ``--lr`` 不生效（P2-5）。"""
    model = _mini_net(seed=1)
    cfg = PPOConfig(device="cpu", lr=S61_BASE_LR, seed=0, compile_train=0)
    trainer = PPOTrainer(model, cfg, lr_min_ratio=S61_LR_MIN_RATIO,
                         max_updates=S61_MAX_UPDATES)

    # 造出 Adam 一阶/二阶矩（不做 PPO update，只一次合成 backward/step）
    loss = sum(p.float().pow(2).sum() for p in model.parameters())
    loss.backward()
    trainer.optimizer.step()
    trainer.optimizer.zero_grad(set_to_none=True)

    for _ in range(S61_UPDATES):        # 复刻 s61：scheduler 走到 285
        trainer.scheduler.step()
    trainer.updates = S61_UPDATES
    expect_lr = _lr_at(S61_BASE_LR, S61_UPDATES, S61_MAX_UPDATES, S61_LR_MIN_RATIO)
    assert abs(float(trainer.optimizer.param_groups[0]["lr"]) - expect_lr) < 1e-15

    path = str(tmp_path / "trainer.pt")
    trainer.save(path)
    saved = {k: v.detach().clone()
             for k, v in trainer.optimizer.state_dict()["state"][0].items()}
    assert saved, "测试前提：optimizer.state 应已非空"

    # 续训：CLI 故意给 9e-6，期望被 state 覆盖（P2-5 的契约）
    model2 = _mini_net(seed=1)
    cfg2 = PPOConfig(device="cpu", lr=9e-6, seed=0, compile_train=0)
    resumed = PPOTrainer.load(model2, path, config=cfg2, device="cpu")

    assert int(resumed.updates) == S61_UPDATES
    got = float(resumed.optimizer.param_groups[0]["lr"])
    assert abs(got - expect_lr) < 1e-12, (got, expect_lr)
    assert abs(got - 9e-6) > 1e-9, "CLI --lr 不应在 trainer-state 续训时生效（P2-5）"

    st = resumed.optimizer.state_dict()["state"][0]
    for key, val in saved.items():
        assert torch.equal(st[key], val), f"optimizer 状态 {key} 未逐位恢复"


# ── 3) eval skip：runner 记 skipped、且没有 ckpt 落盘 ──────────────────────

def test_async_eval_skip_does_not_produce_checkpoint(tmp_path):
    """评测在跑时 ``submit`` 返回 False、只记 ``eval_skipped``；
    这一步**不会**产生 ``eval/ckpt_*.pt``（P0-1 的直接成因）。"""
    from scripts.async_eval import AsyncEvalRunner

    runner = AsyncEvalRunner(
        out_dir=str(tmp_path), root=str(ROOT), arch="tiny", device="cpu",
        games=1, seats=8, seed_base=1, panels=("bot",))
    runner.running = lambda: True          # 模拟「上一个评测还在跑」

    assert runner.submit(20_000_000, "") is False
    assert len(runner.skipped) == 1
    assert runner.skipped[0]["eval_skipped"] is True
    assert runner.skipped[0]["reason"] == "eval_in_flight"
    assert not (tmp_path / "eval" / "ckpt_020000000.pt").exists()


# ── 4) chain 取 ckpt 的 bug 形态 ───────────────────────────────────────────

def _ckpt_tag(path: str) -> int:
    """``.../ckpt_<9 位 decisions>.pt`` -> decisions。"""
    return int(os.path.basename(path).split("_")[1].split(".")[0])


def test_chain_resume_falls_back_to_stale_ckpt_when_last_eval_skipped(tmp_path):
    """P0-1 形态：20M 处评测被 skip（无 ckpt）⇒ chain 的 ``ls -t ... | head -1``
    取到 10M 的旧 ckpt，但 ``CUM`` 仍 ``+= BLOCK_M`` ⇒ 记账超前一个块。"""
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    # 10M 的评测正常提交 → 落 ckpt；20M 的评测在跑 → skip（没有文件）
    p10 = eval_dir / "ckpt_010000000.pt"
    p10.write_bytes(b"x")
    os.utime(p10, (1_000.0, 1_000.0))

    newest = max(glob.glob(str(eval_dir / "ckpt_*.pt")), key=os.path.getmtime)
    block = 20_000_000
    assert _ckpt_tag(newest) == 10_000_000, "bug 形态：最新 ckpt 只有 10M"
    assert block - _ckpt_tag(newest) == 10_000_000, "记账超前 10M decisions"

    # 建议落地到 chain_300m.sh 的最小守卫（供后续修复参考，故此处只断言其行为）
    def assert_block_progress(prev_tag: int, new_tag: int, block_m: int,
                              floor: float = 0.95) -> None:
        if int(new_tag) - int(prev_tag) < float(floor) * int(block_m):
            raise AssertionError(
                f"块未推进：prev={int(prev_tag)} new={int(new_tag)} "
                f"block={int(block_m)}（< {floor:.0%}）")

    with pytest.raises(AssertionError):
        assert_block_progress(20_000_000, _ckpt_tag(newest), block)
