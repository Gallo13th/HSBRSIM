"""人类战团（board-only）注入：池 / 采样 / 引擎驱动 / 训练接线的 CPU 单测（无 torch）。

对应 ``docs/HUMAN_BOARD_OPPONENT.md`` 与任务清单：

1. ``HumanBoardPool``：turn 分桶、strength 分位（p50/p75/p90/max + 同强度随机）、
   ``auto`` 难度曲线、超出数据范围时退化到最近回合；
2. 行过滤：空战团 / ``board>7`` / ``atk<0`` / ``hp<=0`` / 单随从离群 / 战团离群 /
   缺字段 / 非法 turn，全部计数且不带进对局；
3. 引擎驱动 ``inject_turn``：CPU 2 局、``p=1.0``、0 illegal（引擎不抛异常/无非法动作）、
   池平衡、游戏终局；被注入的座位本回合照常行动（``ended_turn`` 保持 False）；
4. 与镜像快照的组合：同座位同回合镜像优先（``skipped_by_mirror``），其它座位照常注入；
5. ``--human-board-p 0``（默认）零影响：同 seed 的终局 ``state_json`` 字节一致；
6. 训练接线：``collect_ppo_lockstep`` 参数、``CollectConfig`` 字段、``train_entity_sync``
   CLI 选项、meta 键（``human_board_attempt/applied/rejected/missing`` +
   ``source=human_board_approx``）。
"""

from __future__ import annotations

import inspect
import json
import random
from pathlib import Path

import pytest

hsbg_engine = pytest.importorskip(
    "hsbg_engine",
    reason="hsbg_engine 未安装（Rust 引擎需 `cd rust && python3 -m pip install -e .`）")
HB = pytest.importorskip("hsbg.az.train.human_board_pool",
                         reason="hsbg.az.train.human_board_pool 不可用")

ROOT = Path(__file__).resolve().parents[1]
REAL_JSONL = ROOT / "data" / "real_library" / "library_real_degraded.jsonl"
N_PLAYERS = 8

#: 真实卡表里确定是 minion 的两张卡（bg 数据 37.0.0）。
CARD_A = 824
CARD_B = 992

#: 允许出现的引擎拒绝原因（都是「该座位本回合不可注入」的正常情况）。
EXPECTED_REJECTS = {"already_ended", "pending_choice", "not_alive", "dying"}


def row(turn: int, board, *, strength=None, game_id: str = "g") -> dict:
    """构造一条与真实数据同构的行（``board`` 为 ``[(card, atk, hp, position)]``）。"""
    b = [{"card": int(c), "atk": int(a), "hp": int(h), "position": int(p)}
         for (c, a, h, p) in board]
    if strength is None:
        strength = sum(int(a) + int(h) for (_c, a, h, _p) in board)
    return {"turn": int(turn), "strength": int(strength), "board": b,
            "hero": 371, "source": "real_10k", "game_id": game_id,
            "quality": "degraded", "split": "train"}


def write_jsonl(path: Path, rows) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def synth_pool(tmp_path: Path, rows, **kw) -> HB.HumanBoardPool:
    return HB.HumanBoardPool(str(write_jsonl(tmp_path / "pool.jsonl", rows)), **kw)


# ────────────────────────── 工具 ──────────────────────────


def seat_json(g, seat: int) -> dict:
    return json.loads(g.player_json(int(seat)))


def board_sig(player: dict) -> list:
    return [(int(m["card"]), int(m["atk"]), int(m["hp"]))
            for m in (player.get("board") or [])]


def clean_seats(g, need_board: bool = True) -> list:
    """存活、pending 为空（且牌面非空）的座位——只有它们能作为注入目标。"""
    out = []
    for s in range(N_PLAYERS):
        pj = seat_json(g, s)
        if pj.get("alive") and not pj.get("pending"):
            if need_board and not pj.get("board"):
                continue
            out.append(int(s))
    return out


def drive_to_turn(g, target: int) -> None:
    """推进到某个**新回合**开始（target 回合的任何座位都还没行动）。"""
    guard = 0
    while not g.is_over() and int(g.turn) < int(target) and guard < 20000:
        for p in range(N_PLAYERS):
            if g.is_over() or int(g.turn) >= int(target):
                break
            if g.needs_action(p):
                g.bot_play(p)
        guard += 1


def play_out(g) -> None:
    guard = 0
    while not g.is_over() and guard < 200000:
        acted = False
        for p in range(N_PLAYERS):
            if g.is_over():
                break
            if g.needs_action(p):
                g.bot_play(p)
                acted = True
        guard += 1
        if not acted:
            break


def play_game_with_injection(seed: int, pool, stats, *, p: float = 1.0,
                             seats_count: int = 2):
    """复刻 ``collect_ppo_lockstep`` 的注入窗口：**新回合、任何座位行动前**注入。

    返回 ``(game, pool_checks)``；``pool_checks`` 是做过守恒断言的回合数。
    """
    g = hsbg_engine.Game(seed=int(seed))
    rng = random.Random(int(seed) * 31 + 7)
    last = int(g.turn)
    checks = 0
    guard = 0
    while not g.is_over() and guard < 200000:
        guard += 1
        acted = False
        for p in range(N_PLAYERS):
            if g.is_over():
                break
            if int(g.turn) != last:              # 新回合、任何座位行动前
                last = int(g.turn)
                before = g.pool_balance()
                HB.inject_turn(g, pool, last, seats_count=seats_count, p=p, rng=rng,
                               learner_seat=0, stats=stats)
                assert g.pool_balance() == before, (last, before, g.pool_balance())
                assert g.pool_species_violations() == [], last
                checks += 1
            if g.needs_action(p):
                g.bot_play(p)
                acted = True
        if not acted:
            break
    return g, checks


# ────────────────────────── 1. 分桶 / 分位采样 ──────────────────────────


def test_turn_buckets_and_percentile_sampling(tmp_path: Path):
    """按 turn 分桶；桶内 strength 分位 = 最近秩（与 MirrorSnapshotPool 同算法）。"""
    rows = [row(3, [(CARD_A, s // 2, s - s // 2, 1)], game_id=f"t3_{s}")
            for s in (2, 12, 22, 32, 42)]
    rows += [row(5, [(CARD_B, 5, 5, 1)])]
    pool = synth_pool(tmp_path, rows)
    assert pool.turns() == [3, 5]
    assert len(pool.index[3]) == 5 and len(pool.index[5]) == 1
    assert pool.kept == 6 and pool.rows == 6

    def strength(board):
        return sum(int(a) + int(h) for (_c, a, h) in board)

    assert strength(pool.sample(3, random.Random(0), mode="p50")) == 22
    assert strength(pool.sample(3, random.Random(0), mode="p75")) == 32
    assert strength(pool.sample(3, random.Random(0), mode="p90")) == 42
    assert strength(pool.sample(3, random.Random(0), mode="max")) == 42
    # 单条桶：任何分位都只有它。
    assert pool.sample(5, random.Random(0), mode="p90") == [[CARD_B, 5, 5]]
    # 空桶（数据里没有该回合）→ 退化为最近回合并计数。
    assert pool.sample(9, random.Random(0)) == [[CARD_B, 5, 5]]
    assert pool.nearest_fallbacks == 1


def test_percentile_ties_are_randomized_but_same_strength(tmp_path: Path):
    """同强度多条：分位命中后用 rng 随机抽（不会永远取第一条）。"""
    rows = [row(4, [(CARD_A, 10, 10, 1)]), row(4, [(CARD_B, 12, 8, 1)])]
    pool = synth_pool(tmp_path, rows)
    picks = {pool.sample(4, random.Random(seed), mode="p50")[0][0] for seed in range(20)}
    assert picks == {CARD_A, CARD_B}, picks


def test_auto_schedule_by_turn(tmp_path: Path):
    """``auto`` 难度曲线：t<=8 p50、9..12 p75、t>=13 p90。"""
    assert [HB.sample_mode_for_turn(t) for t in (1, 8, 9, 12, 13, 20)] == [
        "p50", "p50", "p75", "p75", "p90", "p90"]
    assert HB.TURN_SCHEDULE[0] == (8, "p50")
    # 同一桶内三种分位强度不同：auto 在 t=15 必须取 p90 那条。
    rows = [row(15, [(CARD_A, s // 2, s - s // 2, 1)], game_id=f"t15_{s}")
            for s in (2, 12, 22, 32, 42)]
    pool = synth_pool(tmp_path, rows)
    picked = pool.sample(15, random.Random(0))
    assert sum(int(a) + int(h) for (_c, a, h) in picked) == 42
    assert pool.sample_mode == "auto"


def test_positions_are_sorted(tmp_path: Path):
    """``position`` 排序：注入顺序 = 战团从左到右。"""
    pool = synth_pool(tmp_path, [row(6, [(CARD_A, 1, 1, 2), (CARD_B, 2, 2, 1)])])
    assert pool.sample(6, random.Random(0)) == [[CARD_B, 2, 2], [CARD_A, 1, 1]]


# ────────────────────────── 2. 行过滤 ──────────────────────────


def test_board_filtering_counts_and_drops(tmp_path: Path):
    """空战团 / board>7 / 非正数值 / 单随从与战团离群 / 非法 turn 全部被过滤。"""
    missing_hp = {"turn": 7, "strength": 2, "board": [{"card": CARD_A, "atk": 1}]}
    rows = [
        row(3, [(CARD_A, 1, 1, 1)]),                                  # ok
        row(3, [], strength=0),                                       # empty_board
        row(4, [(CARD_A, 1, 1, i + 1) for i in range(8)]),            # board_over_7
        row(5, [(CARD_A, -1, 1, 1)]),                                 # bad_stats
        row(5, [(CARD_A, 1, 0, 1)]),                                  # bad_stats
        row(5, [(CARD_A, 0, 0, 1)]),                                  # bad_stats（hp=0）
        row(6, [(CARD_A, 200_000, 200_000, 1)]),                      # stat_outlier
        row(6, [(CARD_A, 99_000, 1, i + 1) for i in range(7)]),       # strength_outlier
        row(0, [(CARD_A, 1, 1, 1)]),                                  # bad_turn
        row(7, [(CARD_A, 1, 1, 1)], strength=999),                    # 保留 + strength_mismatch
        missing_hp,                                                   # bad_entry（缺 hp）
    ]
    pool = synth_pool(tmp_path, rows)
    assert pool.kept == 2, pool.stats()["filtered"]
    filt = pool.filtered
    assert filt.get("empty_board") == 1, filt
    assert filt.get("board_over_7") == 1, filt
    assert filt.get("bad_stats") == 3, filt
    assert filt.get("stat_outlier") == 1, filt
    assert filt.get("strength_outlier") == 1, filt
    assert filt.get("bad_turn") == 1, filt
    assert filt.get("strength_mismatch") == 1, filt
    assert filt.get("bad_entry") == 1, filt
    # 过滤后的战团都 <= 7 且数值合法。
    for t in pool.turns():
        for b in pool.index[t]:
            assert 1 <= len(b.board) <= HB.MAX_BOARD
            for (_c, a, h) in b.board:
                assert a >= 0 and h >= 1
    # 坏行（非 JSON）单独计数，不影响其它行。
    p2 = tmp_path / "bad.jsonl"
    p2.write_text('{"turn": 3, "board": [{"card": 824, "atk": 1, "hp": 1}]}\n{not json\n',
                  encoding="utf-8")
    pool2 = HB.HumanBoardPool(str(p2))
    assert pool2.bad_lines == 1 and pool2.kept == 1


def test_load_pool_none_for_missing(tmp_path: Path):
    assert HB.load_pool(None) is None
    assert HB.load_pool(str(tmp_path / "nope.jsonl")) is None
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert HB.load_pool(str(empty)) is None
    ok = write_jsonl(tmp_path / "ok.jsonl", [row(3, [(CARD_A, 1, 1, 1)])])
    pool = HB.load_pool(str(ok))
    assert pool is not None and pool.kept == 1


def test_turn_tier_is_capped_at_six():
    for t in range(1, 30):
        assert 1 <= HB.turn_tier(t) <= 6
    assert HB.turn_tier(1) == 1
    assert HB.turn_tier(20) == 6


# ────────────────────────── 3. 真实人类数据 ──────────────────────────


@pytest.mark.skipif(not REAL_JSONL.is_file(), reason="真实人类库不存在")
def test_real_library_loads_and_covers_all_turns():
    pool = HB.HumanBoardPool(str(REAL_JSONL))
    st = pool.stats()
    assert st["source"] == HB.SOURCE == "human_board_approx"
    assert st["rows"] >= 4000, st["rows"]
    assert st["kept"] >= 4000, st["kept"]
    assert st["turn_min"] == 1 and st["turn_max"] >= 15
    assert st["turns"] == list(range(st["turn_min"], st["turn_max"] + 1))
    # 分位单调（同一 turn），且 t13+ 的 p90 远高于 t5。
    for t, d in st["per_turn"].items():
        assert d["p50"] <= d["p75"] <= d["p90"] <= d["max"], (t, d)
    assert st["per_turn"][13]["p90"] > 10 * st["per_turn"][5]["p50"]
    # 采样出来的战团是 [[card, atk, hp], ...] 且 <= 7 张。
    for turn in (3, 8, 12, 16):
        board = pool.sample(turn, random.Random(turn))
        assert board, turn
        assert len(board) <= 7
        for m in board:
            assert len(m) == 3 and all(isinstance(x, int) for x in m)
    # 极端离群（单个随从 atk+hp 极大）被过滤掉。
    assert st["filtered"].get("stat_outlier", 0) >= 1, st["filtered"]


# ────────────────────────── 4. 引擎驱动（CPU 冒烟） ──────────────────────────


def test_driver_smoke_two_games_p1():
    """2 局、p=1.0、每回合 2 个随机座位：0 illegal（无异常）、池平衡、都终局。"""
    if not REAL_JSONL.is_file():
        pytest.skip("真实人类库不存在")
    pool = HB.HumanBoardPool(str(REAL_JSONL))
    stats = HB.HumanBoardStats()
    games = (771000, 771001)
    checks = 0
    for seed in games:
        g, c = play_game_with_injection(seed, pool, stats)
        checks += c
        assert g.is_over(), f"seed {seed}: 注入后必须能终局"
        held, initial = g.pool_balance()
        assert held == initial
        assert g.pool_species_violations() == []
        assert g.invariant_violations() == []
    meta = stats.to_meta()
    assert meta["human_board_source"] == "human_board_approx"
    assert meta["human_board_attempt"] > 0, meta
    assert meta["human_board_applied"] > 0, meta
    assert meta["human_board_errors"] == 0, meta
    assert meta["human_board_pool_unbalanced"] == 0, meta
    assert meta["human_board_missing"] == 0, meta
    assert meta["human_board_tier_set"] == meta["human_board_applied"], meta
    # 只有「该座位本回合不可注入」这类预期拒绝。
    assert set(meta["human_board_rejected_by_reason"]) <= EXPECTED_REJECTS, meta
    assert checks > 5, checks
    print(f"[human-board-smoke] games={len(games)} p=1.0 inject_rounds={checks} "
          f"attempt={meta['human_board_attempt']} applied={meta['human_board_applied']} "
          f"rejected={meta['human_board_rejected']} "
          f"skipped_by_mirror={meta['human_board_skipped_by_mirror']}")


def test_injected_seat_still_acts_and_board_is_replaced(tmp_path: Path):
    """注入只换 board：该座位不 ended、hand/shop/health/tier 不动，board 与采样一致。"""
    pool = synth_pool(tmp_path, [row(4, [(CARD_A, 7, 8, 1), (CARD_B, 2, 3, 2)])])
    g = hsbg_engine.Game(seed=772000)
    drive_to_turn(g, 4)
    assert int(g.turn) == 4, g.turn
    seats = clean_seats(g)
    assert seats, "turn 4 应有可注入座位"
    seat = 1 if 1 in seats else seats[0]
    before = seat_json(g, seat)
    stats = HB.inject_turn(g, pool, 4, seats=[seat], p=1.0, learner_seat=0,
                           set_tier=False)
    assert stats.applied == 1, stats.to_meta()
    after = seat_json(g, seat)
    assert board_sig(after) == [(CARD_A, 7, 8), (CARD_B, 2, 3)]
    assert after["ended_turn"] is False, "人类战团注入不结束该座位回合"
    assert g.needs_action(seat) is True
    for key in ("health", "armor", "alive", "placement", "hero", "gold", "tier"):
        assert after.get(key) == before.get(key), key
    assert len(after["hand"]) == len(before["hand"])
    assert len(after["shop"]) == len(before["shop"])
    # 新实体不占共享池。
    held, initial = g.pool_balance()
    assert held == initial
    assert g.pool_species_violations() == []
    print(f"[human-board-inject] seat={seat} board={board_sig(after)}")


def test_tier_is_written_when_enabled(tmp_path: Path):
    """``set_tier=True``（默认）写入按 turn 派生的 tier（t4 -> 3）。"""
    pool = synth_pool(tmp_path, [row(4, [(CARD_A, 7, 8, 1)])])
    g = hsbg_engine.Game(seed=776000)
    drive_to_turn(g, 4)
    seats = clean_seats(g)
    seat = 1 if 1 in seats else seats[0]
    before = seat_json(g, seat)
    HB.inject_turn(g, pool, 4, seats=[seat], p=1.0, learner_seat=0, set_tier=True)
    after = seat_json(g, seat)
    assert int(after["tier"]) == HB.turn_tier(4), (before["tier"], after["tier"])
    assert int(after["tier"]) == 3


def test_mirror_priority_skips_same_seat(tmp_path: Path):
    """同座位同回合镜像优先：``mirror_seats`` 里的座位记 skipped_by_mirror 且状态不变。"""
    pool = synth_pool(tmp_path, [row(4, [(CARD_A, 7, 8, 1)])])
    g = hsbg_engine.Game(seed=773000)
    drive_to_turn(g, 4)
    seats = [s for s in clean_seats(g) if s != 0]
    assert len(seats) >= 2, seats
    seat_m, seat_h = seats[0], seats[1]
    before_m = board_sig(seat_json(g, seat_m))
    stats = HB.inject_turn(g, pool, int(g.turn), seats=[seat_m, seat_h], p=1.0,
                           learner_seat=0, mirror_seats=[seat_m])
    meta = stats.to_meta()
    assert meta["human_board_skipped_by_mirror"] == 1, meta
    assert meta["human_board_applied"] == 1, meta
    assert meta["human_board_attempt"] == 1, "被镜像占用的座位不算 attempt"
    assert board_sig(seat_json(g, seat_m)) == before_m
    assert board_sig(seat_json(g, seat_h)) == [(CARD_A, 7, 8)]


def test_human_board_p_zero_is_noop(tmp_path: Path):
    """``--human-board-p 0``（默认）零影响：同 seed 终局 ``state_json`` 字节一致。"""
    pool = synth_pool(tmp_path, [row(4, [(CARD_A, 7, 8, 1)])])

    def run(with_pool: bool) -> str:
        g = hsbg_engine.Game(seed=774000)
        r = random.Random(12345)
        turn = int(g.turn)
        stats = HB.HumanBoardStats()
        guard = 0
        while not g.is_over() and guard < 20000:
            guard += 1
            if int(g.turn) != turn:
                turn = int(g.turn)
                HB.inject_turn(g, pool if with_pool else None, turn, seats_count=2,
                               p=0.0, rng=r, learner_seat=0, stats=stats)
            acted = False
            for p in range(N_PLAYERS):
                if g.needs_action(p):
                    g.bot_play(p)
                    acted = True
            if not acted:
                break
        if with_pool:
            meta = stats.to_meta()
            assert meta["human_board_attempt"] == 0
            assert meta["human_board_applied"] == 0
        return g.state_json()

    assert run(False) == run(True)


# ────────────────────────── 5. 训练接线（结构断言） ──────────────────────────


def test_collect_ppo_lockstep_wiring():
    """``--human-board-*`` 已接到 lockstep 采集 + ``CollectConfig`` + 训练入口 CLI。"""
    pc = pytest.importorskip("hsbg.az.train.parallel_collect")
    sig = inspect.signature(pc.collect_ppo_lockstep)
    for name in ("human_board_pool", "human_board_p", "human_board_seats",
                 "human_board_sample", "human_board_set_tier"):
        assert name in sig.parameters, name
    from hsbg.az.train.ppo import CollectConfig

    cfg = CollectConfig()
    assert cfg.human_boards == "" and cfg.human_board_p == 0.0
    assert cfg.human_board_seats == 2 and cfg.human_board_sample == "auto"
    assert cfg.human_board_set_tier is True
    src = (ROOT / "hsbg" / "az" / "train" / "parallel_collect.py").read_text(encoding="utf-8")
    for token in ("_maybe_human_board", "inject_human_boards", "human_stats",
                  "skipped_by_mirror", "mirror_applied_seats"):
        assert token in src, token
    cli = (ROOT / "scripts" / "train_entity_sync.py").read_text(encoding="utf-8")
    for token in ("--human-boards", "--human-board-p", "--human-board-seats",
                  "--human-board-sample", "human_boards=str(args.human_boards)"):
        assert token in cli, token
    pp = (ROOT / "hsbg" / "az" / "train" / "process_pool.py").read_text(encoding="utf-8")
    for token in ("_HUMAN_BOARD_CACHE", "human_board_pool=hpool"):
        assert token in pp, token
    meta = HB.HumanBoardStats(attempt=1, applied=1, rejected=2, missing=3,
                              skipped_by_mirror=4).to_meta()
    for key in ("human_board_attempt", "human_board_applied", "human_board_rejected",
                "human_board_missing", "human_board_skipped_by_mirror",
                "human_board_source"):
        assert key in meta, key
    assert meta["human_board_source"] == "human_board_approx"


def test_inject_turn_applied_out_supports_mirror_priority(tmp_path: Path):
    """镜像快照的 ``inject_turn(applied_out=...)`` 与实际成功的座位一致。"""
    MR = pytest.importorskip("hsbg.az.train.mirror_snapshots")
    g = hsbg_engine.Game(seed=775000)
    drive_to_turn(g, 4)
    seats = [s for s in clean_seats(g) if s != 0]
    assert seats, "turn 4 应有可注入座位"
    target = seats[0]
    # 用**本局真实**的 Player JSON 做帧（引擎按整份 Player 反序列化）。
    payload = seat_json(g, target)
    pool = MR.MirrorSnapshotPool(None, sample="p50")
    pool.index[(int(g.turn), target)] = [
        MR.SnapshotFrame(turn=int(g.turn), seat=target, player=payload)]
    other = next(s for s in range(1, N_PLAYERS) if s != target)
    out: list = []
    stats = MR.MirrorStats()
    MR.inject_turn(g, pool, int(g.turn), seats=[target, other], p=1.0,
                   rng=random.Random(0), learner_seat=0, stats=stats, applied_out=out)
    meta = stats.to_meta()
    assert out == [target], out
    assert meta["mirror_applied"] == 1
    assert meta["mirror_missing"] == 1


# ────────────────────────── 7. payload 透传 gold / hero_hp / main_placement ──────────────────────────


def _detail_row(turn: int, *, gold=None, hero_hp=None, main_placement=None,
                source: str = "firestone_pms+xml") -> dict:
    """构造一条带 ``board_detail`` 的准完整行（Firestone 库字段形态）。"""
    out = {
        "turn": int(turn), "strength": 12, "board": [[CARD_A, 5, 7]],
        "board_detail": [{"card": CARD_A, "atk": 5, "hp": 7, "golden": False,
                          "kw": 0, "bonus_kw": 0, "shield_max": 1, "position": 1}],
        "hand": [], "hand_available": True, "tier": 4,
        "hero": 371, "source": source, "game_id": "g-payload",
        "schema": "hsbg.human_state_quasi_full", "schema_version": 1,
    }
    if gold is not None:
        out["gold"] = gold          # 故意不做类型转换：由 _row_to_payload 兜底
    if hero_hp is not None:
        out["hero_hp"] = hero_hp
    if main_placement is not None:
        out["main_placement"] = main_placement
    return out


def test_payload_carries_gold_hero_hp_main_placement(tmp_path: Path):
    """行里有 ``gold`` / ``hero_hp`` / ``main_placement`` 时，payload 原样带上。"""
    pool = synth_pool(tmp_path, [_detail_row(5, gold=9, hero_hp=23, main_placement=1)])
    pay = pool.sample_payload(5, random.Random(0), "p50")
    assert pay is not None and pay["has_detail"] is True
    assert pay["gold"] == 9
    assert pay["hero_hp"] == 23
    assert pay["main_placement"] == 1
    # board / hand / tier 的原有语义不变
    assert pay["board_flat"] == [[CARD_A, 5, 7]]
    assert pay["tier"] == 4 and pay["hand"] == []


def test_payload_defaults_to_none_when_fields_absent(tmp_path: Path):
    """行里没有这些字段 -> payload 为 ``None``（与旧的 ``"gold": None`` 逐位一致）。"""
    row = _detail_row(6)
    for key in ("gold", "hero_hp", "main_placement"):
        row.pop(key, None)
    pool = synth_pool(tmp_path, [row])
    pay = pool.sample_payload(6, random.Random(0), "p50")
    assert pay["gold"] is None
    assert pay["hero_hp"] is None
    assert pay["main_placement"] is None


def test_payload_bad_values_degrade_to_none(tmp_path: Path):
    """非法/缺失值不能让整行失效：退化为 ``None``，其余字段照常。"""
    row = _detail_row(7, gold="not-an-int", hero_hp=None, main_placement=3.9)
    row.pop("hero_hp", None)
    pool = synth_pool(tmp_path, [row])
    pay = pool.sample_payload(7, random.Random(0), "p50")
    assert pay["gold"] is None
    assert pay["hero_hp"] is None
    assert pay["main_placement"] == 3
    assert pool.kept == 1


def test_real_quasi_library_payload_has_no_gold():
    """真实 10k+ 准完整库没有 gold/hero_hp/main_placement -> payload 全 None。

    这是「默认不改变现有库逐位行为」的回归锚点：A 臂（quasi_full）的 payload 与改动前
    完全一致（唯一的差别是新增了两个恒为 None 的键，注入路径不会读它们）。
    """
    quasi = ROOT / "data" / "real_library" / "library_real_quasi_full.jsonl"
    pool = HB.load_pool(str(quasi))
    assert pool is not None and pool.payload_kept > 1000
    pay = pool.sample_payload(10, random.Random(7), "p50")
    assert pay is not None and pay["has_detail"] is True
    assert pay["gold"] is None
    assert pay["hero_hp"] is None
    assert pay["main_placement"] is None


def test_real_firestone_library_payload_keeps_gold():
    """真实 Firestone 近期库：self 帧的 payload 带上 gold（覆盖率 ~57%）。"""
    path = ROOT / "data" / "real_library" / "library_firestone_recent.jsonl"
    pool = HB.load_pool(str(path))
    assert pool is not None and pool.payload_kept > 10_000
    with_gold = 0
    for turn in pool.turns():
        for hb in pool.index[turn][:5]:
            if isinstance(hb.payload, dict) and hb.payload.get("gold") is not None:
                with_gold += 1
    assert with_gold > 0, "Firestone 库应有一部分行带 gold"
