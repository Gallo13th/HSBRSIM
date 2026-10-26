"""HSbg Engine: a Hearthstone Battlegrounds solo-mode simulator with a reinforcement-learning
interface. HSBRSIM 的主引擎（vendored fork of TavernGym / AutoTavern, MIT；见 rust/FORK.md）。

公开 API 与上游 TavernGym 1.0.0 逐位一致（只有包名从 `taverngym` 改为 `hsbg_engine`）；额外
提供 `db_info()` / `data_info()` 便于核对当前编译进来的数据版本。

- `Game`: one eight-player game, every seat driven explicitly.
- `BattlegroundsEnv`: one learning seat against seven scripted bots (Gymnasium-style).
- `BatchEnv`: many games stepped together, any set of controlled seats.

数据：`rust/crates/hsbg-engine/data/cards.json`（编译期 include；换数据后必须重新
`pip install -e .` 重建）。当前为上游 36.6.3 数据，37.0.0.255130 数据由 HSBRSIM 数据任务替换。
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

try:
    from hsbg_engine._core import (
        N_ACTIONS,
        N_CARDS,
        OBS_CARDS,
        OBS_FLOATS,
        Game,
        SoloEnv,
        action_name,
        card_info,
        card_static,
        catalog_json,
        db_info,
        default_config_json,
        game_version,
        layout,
        mcts_search,
        run_bot_games,
        server_rules_version,
        turn_search,
        version,
    )
except ImportError as exc:  # pragma: no cover - only hit before the Rust build
    raise ImportError("hsbg_engine._core is not built; run `pip install -e .` (cd rust)") from exc


def data_info():
    """当前编译进二进制的卡表概况（fork 新增，便于集成核对）：
    `{"cards": 卡数(不含空位), "game_version": 客户端版本, "server_rules_version": 服务器规则,
      "n_cards": N_CARDS}`。可用环境变量 `HSBG_ENGINE_DB_INFO=1` 让 import 时打印一次。"""
    count, game, rules = db_info()
    return {
        "cards": int(count),
        "game_version": str(game),
        "server_rules_version": str(rules),
        "n_cards": int(N_CARDS),
    }


def build_info():
    """How the loaded native extension was built: `source_hash` (the fingerprint of the
    engine and binding sources it was compiled from), `profile` and the file loaded."""
    from hsbg_engine import _core

    source, profile = _core.build_info()
    return {"source_hash": source, "profile": profile, "file": _core.__file__}


def source_hash(repo_root=REPO_ROOT):
    """The `source_hash` an extension built from this checkout has (`crates/hsbg-engine-py/build.rs`
    computes the same), or None where the sources are not there (an installed package)."""
    import zlib

    crates = Path(repo_root) / "crates"
    data = crates / "hsbg-engine" / "data" / "cards.json"
    if not data.is_file():
        return None
    files = [*(crates / "hsbg-engine" / "src").rglob("*.rs"),
             *(crates / "hsbg-engine-py" / "src").rglob("*.rs"), data]  # fmt: skip
    h = 0xCBF29CE484222325
    for rel, f in sorted((f.relative_to(crates).as_posix(), f) for f in files):
        crc = zlib.crc32(f.read_bytes().replace(b"\r", b"")) & 0xFFFFFFFF
        for b in rel.encode() + b"\0" + crc.to_bytes(4, "little"):
            h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def build_is_current(repo_root=REPO_ROOT):
    """Whether the loaded extension was built from the sources of this checkout (None when
    that cannot be told: no sources here)."""
    built, here = build_info()["source_hash"], source_hash(repo_root)
    return None if here is None else built == here


from hsbg_engine.batch import BatchEnv  # noqa: E402
from hsbg_engine.env import BattlegroundsEnv  # noqa: E402

# fork：可选的一次性数据摘要（默认不打印；Lead 集成核对数据替换是否生效时用，
# 例如 `HSBG_ENGINE_DB_INFO=1 python3 -c "import hsbg_engine"`）。
if os.environ.get("HSBG_ENGINE_DB_INFO", "").strip().lower() in ("1", "true", "yes", "on"):
    _info = data_info()
    print(
        f"[hsbg_engine] game_version={_info['game_version']} "
        f"server_rules_version={_info['server_rules_version']} cards={_info['cards']} "
        f"n_cards={_info['n_cards']}"
    )

__all__ = [
    "N_ACTIONS",
    "N_CARDS",
    "OBS_CARDS",
    "OBS_FLOATS",
    "REPO_ROOT",
    "BatchEnv",
    "BattlegroundsEnv",
    "Game",
    "SoloEnv",
    "action_name",
    "build_info",
    "build_is_current",
    "card_info",
    "card_static",
    "catalog_json",
    "data_info",
    "db_info",
    "default_config_json",
    "game_version",
    "layout",
    "mcts_search",
    "run_bot_games",
    "server_rules_version",
    "turn_search",
    "source_hash",
    "version",
]
