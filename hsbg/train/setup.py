"""脚本装配工具：设备/输出目录/词表/模型/环境 的统一构建逻辑。

放在 ``hsbg.train`` 内（而不是 scripts/）以便测试复用，保证
``scripts/train_ppo.py`` / ``scripts/train_bc.py`` / ``scripts/evaluate_policy.py``
的行为一致、可复现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from hsbg.env.spec import Observation
from hsbg.paths import ROOT, ensure_runs_dir
from hsbg.policy.encoder import CardVocab, ObservationEncoder, collect_card_ids


def resolve_device(name: Optional[str]) -> str:
    """``auto``/``cpu``/``cuda``/``cuda:0`` → 实际可用设备字符串。"""
    import torch

    if name is None or str(name).lower() in ("auto", ""):
        return "cuda" if torch.cuda.is_available() else "cpu"
    name = str(name)
    if name.startswith("cuda") and not torch.cuda.is_available():
        print(f"[setup] 警告：请求 {name} 但 CUDA 不可用，回退 CPU")
        return "cpu"
    return name


def seed_everything(seed: int) -> None:
    """统一播种（训练可复现）：python/numpy/torch/cuda 全部固定。"""
    import random

    import numpy as np
    import torch

    seed = int(seed)
    random.seed(seed)            # nosec - 复现用；环境内部仍用 seed 决定
    np.random.seed(seed % (2 ** 32 - 1))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    try:
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except Exception:  # pragma: no cover - 某些构建无 cudnn
        pass


def resolve_out_dir(out: Optional[Union[str, Path]], *, default: str = "runs/run") -> Path:
    """相对路径解析到仓库根（``hsbg.paths.ROOT``），并创建目录。"""
    if out is None or str(out) == "":
        path = ensure_runs_dir(*Path(default).parts[1:]) if default.startswith("runs/") else ROOT / default
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = Path(out)
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_encoder(
    *,
    data_dir: Optional[Union[str, Path]] = None,
    observations: Optional[Iterable[Observation]] = None,
    vocab_path: Optional[Union[str, Path]] = None,
    base_vocab: Optional[CardVocab] = None,
) -> ObservationEncoder:
    """构建词表/编码器：``data/*.json`` ∪ 观测里出现的 card_id（动态补充）。"""
    if base_vocab is not None:
        vocab = base_vocab
    elif vocab_path is not None:
        vocab = CardVocab.load(vocab_path)
    else:
        vocab = CardVocab.from_data_dir(data_dir)
    if observations:
        seen = set()
        for obs in observations:
            seen |= collect_card_ids(obs)
        new_ids = sorted(cid for cid in seen if cid not in vocab)
        if new_ids:
            vocab.extend(new_ids)
    return ObservationEncoder(vocab)


def probe_observations(env: Any, max_count: int = 8) -> List[Observation]:
    """取一批观测用于动态补充词表（不改变训练用的 episode 语义）。"""
    obs_list = env.reset()
    return list(obs_list)[:max_count]


def env_kwargs_for_real(opponent: str = "heuristic", **extra: Any) -> Dict[str, Any]:
    """真环境的构造参数（Mock 会忽略不能识别的字段，所以仅真 env 时用）。"""
    kwargs: Dict[str, Any] = {"opponent": opponent}
    kwargs.update({k: v for k, v in extra.items() if v is not None})
    return kwargs


def describe_env(env: Any) -> str:
    """日志用：区分真环境与 Mock。"""
    cls = type(env).__name__
    num = getattr(env, "num_envs", "?")
    return f"{cls}(num_envs={num})"


__all__ = [
    "resolve_device",
    "seed_everything",
    "resolve_out_dir",
    "build_encoder",
    "probe_observations",
    "env_kwargs_for_real",
    "describe_env",
]
