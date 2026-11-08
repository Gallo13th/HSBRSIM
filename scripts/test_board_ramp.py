"""对手强度课程（human-board 席数/概率/分位按累计 decisions 爬坡）的单测。

覆盖（docs/BOARD_RAMP.md）：

1. ``parse_board_ramp`` 语法（含 K/M/B 后缀）与非法输入报错；
2. ``parse_quantile_ramp`` 语法 / 取值白名单 / 重复边界报错；
3. ``board_ramp_at`` 的 ``step`` / ``linear`` 插值，以及边界外保持；
4. ``BoardRampController`` 按 decisions 切档、超过最后一档保持、quantile 独立爬坡；
5. **默认（空 spec + adaptive=0）恒等映射**：同 seed 2 iteration 采集逐位等价
   （records 打包 sha 相同），且写回 CollectConfig 的值与 CLI 值逐字段相等；
6. 自适应门控：窗口未满不动、连续达标提前升档、不达标把下一档推迟 2M decisions
   （每档最多一次、档位不回退）、``--ramp-start-decisions`` 偏移；
7. ``ramp_progress_metrics`` 的代理口径（max_turn>=12 / >=8）与
   ``collect_meta`` > 代理、``quality`` > ``collect_meta`` 的优先级；
8. ``board_ramp_history`` 的 history 字段（seats/p/sample/band/events）；
9. 入口脚本暴露 9 个新 CLI 开关；
10. 端到端接线：脚本 2 iteration 的 ``history.jsonl`` 里 ``human_board`` 段是
    **实际生效值**且随累计 decisions 切档（p=0 的纯接线测例，不需要人类战团库）。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.ppo import (BOARD_RAMP_DELAY_DECISIONS, BoardRampController,
                               board_ramp_at, board_ramp_history,
                               parse_board_ramp, parse_decisions,
                               parse_quantile_ramp, quantile_ramp_at,
                               ramp_progress_metrics)

S15_SPEC = "0:1:0.30,10M:2:0.50,20M:3:0.70,30M:5:0.90"


def _needs_engine():
    return pytest.importorskip("hsbg_engine")


def _needs_torch():
    return pytest.importorskip("torch")


def _hash_arrays(packed: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(packed):
        a = np.ascontiguousarray(packed[k])
        h.update(k.encode())
        h.update(str(a.dtype).encode())
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


# ── 1. board ramp 解析 ────────────────────────────────────────────────────
def test_parse_board_ramp_valid_spec():
    pts = parse_board_ramp(S15_SPEC)
    assert pts == [(0.0, 1, 0.30), (10_000_000.0, 2, 0.50),
                   (20_000_000.0, 3, 0.70), (30_000_000.0, 5, 0.90)]
    # 空白 / 无序输入 / int 字面量都规范化
    assert parse_board_ramp(" 30M:5:0.9 , 0:1:0.3 ") == [(0.0, 1, 0.3),
                                                          (30_000_000.0, 5, 0.9)]
    assert parse_board_ramp("1500:2:0.25") == [(1500.0, 2, 0.25)]
    # 空 spec = 课程关闭
    assert parse_board_ramp("") == []
    assert parse_board_ramp(None) == []
    assert parse_board_ramp("   ") == []


@pytest.mark.parametrize("spec", [
    "0:1",                    # 字段不足
    "0:1:0.3:9",              # 字段过多
    "0:0:0.3",                # seats 下界
    "0:8:0.3",                # seats 超过 7 个对手座
    "0:1:1.5",                # p 上界
    "0:1:-0.1",               # p 下界
    "-1:1:0.3",               # 负 decisions
    "M:1:0.3",                # 非法 decisions 字面量
    "0:1.5:0.3",              # seats 非整数
    "0:1:0.3,0:2:0.4",        # decisions 重复
    "0:1:0.3,10M:2:0.5,bad",  # 尾部乱码
])
def test_parse_board_ramp_rejects_bad_specs(spec):
    with pytest.raises(ValueError):
        parse_board_ramp(spec)


# ── 2. decisions 字面量 ───────────────────────────────────────────────────
def test_parse_decisions_suffixes_and_errors():
    assert parse_decisions(0) == 0.0
    assert parse_decisions(1234) == 1234.0
    assert parse_decisions("10M") == 10_000_000.0
    assert parse_decisions("2.5M") == 2_500_000.0
    assert parse_decisions("500K") == 500_000.0
    assert parse_decisions("1B") == 1_000_000_000.0
    assert parse_decisions("1_000_000") == 1_000_000.0
    for bad in ("", "M", "-5M", "10X", True, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            parse_decisions(bad)


# ── 3. quantile ramp 解析 ─────────────────────────────────────────────────
def test_parse_quantile_ramp_and_lookup():
    pts = parse_quantile_ramp("0:p75,20M:p90")
    assert pts == [(0.0, "p75"), (20_000_000.0, "p90")]
    assert quantile_ramp_at(0, pts) == "p75"
    assert quantile_ramp_at(19_999_999, pts) == "p75"
    assert quantile_ramp_at(20_000_000, pts) == "p90"
    assert quantile_ramp_at(10 ** 12, pts) == "p90"
    assert parse_quantile_ramp("") == []
    for bad in ("0-p75", "0:p60", "0:P75:p90", "-1:p50", "0:p50,0:p90"):
        with pytest.raises(ValueError):
            parse_quantile_ramp(bad)


# ── 4. step / linear 插值 ─────────────────────────────────────────────────
def test_board_ramp_at_step_cuts_by_decisions():
    pts = parse_board_ramp(S15_SPEC)
    assert board_ramp_at(0, pts) == (1, 0.30)
    assert board_ramp_at(9_999_999, pts) == (1, 0.30)
    assert board_ramp_at(10_000_000, pts) == (2, 0.50)
    assert board_ramp_at(19_999_999, pts) == (2, 0.50)
    assert board_ramp_at(20_000_000, pts) == (3, 0.70)
    assert board_ramp_at(30_000_000, pts) == (5, 0.90)
    # 超过最后一档：保持最后一档
    assert board_ramp_at(10 ** 12, pts) == (5, 0.90)
    # 早于第一个控制点：取第一档
    pts_late = parse_board_ramp("10M:2:0.5")
    assert board_ramp_at(0, pts_late) == (2, 0.5)


def test_board_ramp_at_linear_interpolates_seats_and_p():
    pts = parse_board_ramp(S15_SPEC)
    assert board_ramp_at(5_000_000, pts, mode="linear") == (2, 0.40)
    assert board_ramp_at(15_000_000, pts, mode="linear") == (3, 0.60)
    assert board_ramp_at(25_000_000, pts, mode="linear") == (4, 0.80)
    # 端点与边界外与 step 一致
    assert board_ramp_at(0, pts, mode="linear") == (1, 0.30)
    assert board_ramp_at(30_000_000, pts, mode="linear") == (5, 0.90)
    assert board_ramp_at(10 ** 12, pts, mode="linear") == (5, 0.90)
    with pytest.raises(ValueError):
        board_ramp_at(0, pts, mode="cubic")
    with pytest.raises(ValueError):
        board_ramp_at(0, [])


# ── 5. controller：切档 / 边界 / quantile ─────────────────────────────────
def test_controller_state_switches_bands_and_holds_last():
    c = BoardRampController(S15_SPEC, quantile_spec="0:p75,20M:p90",
                            base_seats=5, base_p=0.9)
    st = c.state(0)
    assert (st.seats, st.p, st.sample, st.band, st.bands) == (1, 0.30, "p75", 0, 4)
    st = c.state(20_000_000)
    assert (st.seats, st.p, st.sample, st.band) == (3, 0.70, "p90", 2)
    st = c.state(10 ** 12)
    assert (st.seats, st.p, st.band) == (5, 0.90, 3)
    assert st.bands == 4 and st.mode == "step"


def test_controller_linear_mode_uses_interpolated_values():
    c = BoardRampController(S15_SPEC, mode="linear")
    st = c.state(5_000_000)
    assert (st.seats, round(st.p, 4)) == (2, 0.40)


def test_controller_disabled_is_identity():
    """默认（无 spec）: state() 原样返回基线值，observe() 不做任何事。"""
    c = BoardRampController("", base_seats=5, base_p=0.9, base_sample="auto")
    assert c.enabled is False and c.bands == 0
    for d in (0, 1, 10 ** 6, 10 ** 12):
        st = c.state(d)
        assert (st.seats, st.p, st.sample, st.band, st.bands) == (5, 0.9, "auto", 0, 0)
        assert c.state(d).as_dict()["seats"] == 5
    # adaptive 打开但无 spec：仍然恒等（不允许凭空改配置）
    c2 = BoardRampController("", adaptive=True, base_seats=3, base_p=0.4)
    assert c2.observe(0, 0, {"survive_t12": 1.0, "tier_ge4": 1.0}) == []
    assert c2.state(10 ** 9).seats == 3


# ── 6. 自适应门控 ─────────────────────────────────────────────────────────
GOOD = {"survive_t12": 0.4, "tier_ge4": 0.5}
BAD = {"survive_t12": 0.05, "tier_ge4": 0.05}


def test_adaptive_needs_full_window():
    c = BoardRampController("0:1:0.3,5M:2:0.5,10M:3:0.7", adaptive=True, window=3)
    assert c.observe(0, 0, GOOD) == []
    assert c.observe(1, 100, GOOD) == []
    assert c.state(200).band == 0          # 窗口未满 -> 不动
    ev = c.observe(2, 300, GOOD)
    assert [e["event"] for e in ev] == ["early"]
    assert c.state(400).band == 1


def test_adaptive_early_advance_jumps_one_band():
    c = BoardRampController("0:1:0.3,5M:2:0.5,10M:3:0.7",
                            adaptive=True, window=2)
    c.observe(0, 0, GOOD)
    ev = c.observe(1, 10, GOOD)
    assert ev and ev[0]["event"] == "early"
    assert ev[0]["from_band"] == 0 and ev[0]["to_band"] == 1
    st = c.state(20)
    assert (st.seats, st.p, st.band) == (2, 0.5, 1)
    assert st.early_advances == 1
    # 早期升档落在 band_floor：schedule 追上 5M 后不会重复跳档
    st = c.state(5_000_000)
    assert (st.seats, st.band) == (2, 1)
    # 已升到下一档后继续达标 -> 再升一档（窗口重置过一次，需要再满 window 次）
    assert c.observe(2, 5_100_000, GOOD) == []
    ev = c.observe(3, 5_200_000, GOOD)
    assert ev and ev[0]["event"] == "early" and ev[0]["to_band"] == 2


def test_adaptive_delay_shifts_next_bands_once_per_band():
    c = BoardRampController("0:1:0.3,5M:2:0.5,10M:3:0.7",
                            adaptive=True, window=2)
    assert c.observe(0, 1000, BAD) == []
    ev = c.observe(1, 2000, BAD)
    assert ev and ev[0]["event"] == "delay"
    assert ev[0]["delay_decisions"] == int(BOARD_RAMP_DELAY_DECISIONS)
    assert c.delay_decisions == BOARD_RAMP_DELAY_DECISIONS
    # 推迟后 5M 边界 -> 7M；档位不回退
    assert c.state(2_000_000).band == 0
    assert c.state(6_999_999).band == 0
    assert c.state(7_000_000).band == 1
    # 同一档位最多推迟一次
    assert c.observe(2, 7_100_000, BAD) == []
    ev2 = c.observe(3, 7_200_000, BAD)
    assert ev2 and ev2[0]["event"] == "delay" and ev2[0]["band"] == 1
    assert c.delay_decisions == 2 * BOARD_RAMP_DELAY_DECISIONS
    assert c.state(7_300_000).band == 1


def test_adaptive_forced_end_guard_blocks_early_advance():
    """强制结束回合过多 -> 存活是假的 -> 不升档（宁可推迟）。"""
    c = BoardRampController("0:1:0.3,5M:2:0.5,10M:3:0.7",
                            adaptive=True, window=2, max_forced_per_game=12.0)
    inflated = {"survive_t12": 0.9, "tier_ge4": 0.9, "forced_per_game": 40.0}
    assert c.observe(0, 0, inflated) == []
    ev = c.observe(1, 10, inflated)
    assert ev and ev[0]["event"] == "delay"      # 不升档，反而推迟
    assert c.state(20).band == 0
    # 正常 forced 水平下同样的存活率会升档
    c2 = BoardRampController("0:1:0.3,5M:2:0.5,10M:3:0.7",
                             adaptive=True, window=2, max_forced_per_game=12.0)
    ok = {"survive_t12": 0.9, "tier_ge4": 0.9, "forced_per_game": 3.0}
    c2.observe(0, 0, ok)
    ev2 = c2.observe(1, 10, ok)
    assert ev2 and ev2[0]["event"] == "early"
    assert c2.window_summary()["forced_per_game_mean"] == 3.0


def test_adaptive_does_not_fire_on_last_band():
    c = BoardRampController("0:1:0.3,5M:2:0.5", adaptive=True, window=1)
    c.state(10_000_000)                   # 已到最后一档
    assert c.observe(0, 10_000_000, GOOD) == []
    assert c.observe(1, 10_000_001, BAD) == []
    assert c.delay_decisions == 0.0


def test_controller_start_decisions_offset():
    c = BoardRampController("0:1:0.3,5M:2:0.5", start_decisions="4M")
    assert c.state(0).band == 0
    assert c.state(1_000_000).band == 1     # 4M + 1M = 5M
    assert c.state(0).band == 1             # 单调 x：不回退
    with pytest.raises(ValueError):
        BoardRampController("0:1:0.3,5M:2:0.5", start_decisions="-1")


# ── 7. 门控指标 ───────────────────────────────────────────────────────────
def test_ramp_progress_metrics_turn_proxy():
    turns = np.asarray([1, 2, 5, 12, 13, 3, 8, 9, 14], dtype=np.int32)
    gids = np.asarray([0, 0, 0, 0, 0, 1, 1, 1, 1], dtype=np.int64)
    m = ramp_progress_metrics(turns, gids)
    assert m["games"] == 2 and m["source"] == "batch"
    assert m["survive_t12"] == 1.0          # game0 到 13, game1 到 14
    assert m["tier_ge4"] == 1.0             # 两局 max_turn 都 >= 8
    m2 = ramp_progress_metrics(np.asarray([1, 2, 7], dtype=np.int32),
                               np.asarray([0, 0, 0], dtype=np.int64))
    assert m2["survive_t12"] == 0.0 and m2["tier_ge4"] == 0.0
    assert m2["max_turn_p50"] == 7.0        # 单局：max_turn 就是该局最大回合


def test_ramp_progress_metrics_override_precedence():
    turns = np.asarray([1, 2, 3], dtype=np.int32)
    gids = np.asarray([0, 0, 0], dtype=np.int64)
    meta = {"survive_t12_ratio": 0.6, "tier_ge4_ratio": 0.4, "forced_end_turns": 9}
    m = ramp_progress_metrics(turns, gids, collect_meta=meta)
    assert (m["survive_t12"], m["tier_ge4"], m["source"]) == (0.6, 0.4, "collect_meta")
    assert m["forced_end_turns"] == 9 and m["forced_per_game"] == 9.0
    # 嵌套 collect 段同样认
    m2 = ramp_progress_metrics(turns, gids, collect_meta={"collect": meta})
    assert (m2["survive_t12"], m2["source"]) == (0.6, "collect_meta")
    # quality（质量统计）优先级最高
    m3 = ramp_progress_metrics(turns, gids, collect_meta=meta,
                               quality={"survive_t12_ratio": 0.9,
                                        "tier_ge4_ratio": 0.8})
    assert (m3["survive_t12"], m3["tier_ge4"], m3["source"]) == (0.9, 0.8, "quality")
    # 空输入不炸
    m4 = ramp_progress_metrics(None, None)
    assert m4["games"] == 0 and m4["survive_t12"] == 0.0


# ── 8. history 字段 ───────────────────────────────────────────────────────
def test_board_ramp_history_fields():
    c = BoardRampController(S15_SPEC, adaptive=True, window=2)
    c.observe(0, 0, GOOD)
    ev = c.observe(1, 10, GOOD)
    st = c.state(20)
    rec = board_ramp_history(st, spec=S15_SPEC, mode="step", adaptive=True,
                             events=ev)
    for key in ("seats", "p", "sample", "band", "bands", "mode", "decisions",
                "adaptive", "early_advances", "delay_decisions",
                "start_decisions", "ramp", "quantile_ramp", "events"):
        assert key in rec, f"缺字段 {key}"
    assert (rec["seats"], rec["p"], rec["sample"], rec["band"]) == (2, 0.5, "auto", 1)
    assert rec["adaptive"] is True and rec["ramp"] == S15_SPEC
    assert rec["events"] and rec["events"][0]["event"] == "early"
    # 无 ramp：seats/p/sample 就是基线值，events 为空
    plain = BoardRampController("", base_seats=5, base_p=0.9)
    rec0 = board_ramp_history(plain.state(0), spec="")
    assert (rec0["seats"], rec0["p"], rec0["sample"], rec0["bands"]) == (5, 0.9, "auto", 0)
    assert rec0["events"] == [] and rec0["ramp"] == ""


# ── 9. 默认逐位等价（同 seed 2 iteration 采集）────────────────────────────
def test_ramp_disabled_config_identity_and_two_iter_sha():
    """空 spec 时控制器写回的 cfg 与 CLI 值逐字段相等，同 seed 2 iter 采集 sha 一致。"""
    torch = _needs_torch()
    _needs_engine()
    from hsbg.az.train.model import build_net
    from hsbg.az.train.parallel_collect import collect_ppo_lockstep
    from hsbg.az.train.ppo import CollectConfig, PPOEvaluator

    ctl = BoardRampController("", base_seats=2, base_p=0.3, base_sample="auto")

    def cfg(via_ctl: bool, seed: int, cum: int) -> CollectConfig:
        base = dict(games=1, seed=seed, opponent="bot", behavior="net",
                    lockstep=True, fast_act=False, max_steps=20000)
        if via_ctl:
            st = ctl.state(cum)
            return CollectConfig(human_board_seats=int(st.seats),
                                 human_board_p=float(st.p),
                                 human_board_sample=str(st.sample), **base)
        return CollectConfig(human_board_seats=2, human_board_p=0.3,
                             human_board_sample="auto", **base)

    def digest(recs) -> str:
        return _hash_arrays({
            "actions": np.asarray([r["action"] for r in recs], dtype=np.int64),
            "turns": np.asarray([r["turn"] for r in recs], dtype=np.int64),
            "gids": np.asarray([r["game_id"] for r in recs], dtype=np.int64),
        })

    torch.manual_seed(23)
    model = build_net(hidden=32, arch="tiny")
    ev = PPOEvaluator(model, device="cpu")
    cum = 0
    for it, seed in enumerate((900, 1000)):
        plain, wired = cfg(False, seed, cum), cfg(True, seed, cum)
        assert plain.__dict__ == wired.__dict__, "无 ramp 时写回的 cfg 必须逐字段相等"
        recs, _ = collect_ppo_lockstep(model, wired, eval_fn=ev, device="cpu",
                                       seed=seed, gamemode="bot")
        cum += len(recs)
        if it == 0:
            first = digest(recs)
    # 第二次同 seed 重采：与第一次逐位一致
    recs2, _ = collect_ppo_lockstep(model, cfg(True, 900, 0), eval_fn=ev,
                                    device="cpu", seed=900, gamemode="bot")
    assert digest(recs2) == first


# ── 10. CLI / 端到端接线 ──────────────────────────────────────────────────
def test_ramp_cli_exposes_flags():
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "train_entity_sync.py"),
         "--help"], capture_output=True, text=True, timeout=180)
    assert out.returncode == 0
    for flag in ("--human-board-ramp", "--human-board-quantile-ramp",
                 "--ramp-mode", "--ramp-adaptive", "--ramp-window",
                 "--ramp-survive-threshold", "--ramp-tier4-threshold",
                 "--ramp-delay-decisions", "--ramp-start-decisions",
                 "--ramp-quality-json", "--ramp-max-forced-per-game"):
        assert flag in out.stdout, f"CLI 缺少 {flag}"


def test_ramp_script_history_records_effective_values(tmp_path):
    """脚本 2 iteration：history 的 human_board 段是实际生效值，并随 decisions 切档。

    用 p=0 的纯接线课程（不读人类战团库）：iter0 = 1 席 p0.0 sample=p75；
    iter1 累计 decisions 越过 30 后 = 2 席 p0.0 sample=p90。
    """
    _needs_torch()
    _needs_engine()
    out = tmp_path / "run"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(ROOT, "rust", "python"), str(ROOT)])
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "train_entity_sync.py"),
           "--arch", "tiny", "--games", "2", "--iterations", "2",
           "--device", "cpu", "--opponent", "bot", "--lockstep", "1",
           "--sims", "0", "--minutes", "5", "--out", str(out), "--seed", "11",
           "--eval-every-decisions", "0", "--epochs", "1", "--minibatch", "32",
           "--human-board-ramp", "0:1:0.0,30:2:0.0",
           "--human-board-quantile-ramp", "0:p75,30:p90"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                          env=env, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-3000:]
    # history.jsonl 首行是 header（无 iter），用 read_run 读回 records
    from hsbg.az.train.runlog import read_run
    _hdr, rows = read_run(str(out / "history.jsonl"))
    assert len(rows) >= 2
    first, later = rows[0], rows[-1]
    assert (first["human_board_seats"], first["human_board_p"],
            first["human_board_sample"]) == (1, 0.0, "p75")
    assert first["human_board"]["band"] == 0
    assert (later["human_board_seats"], later["human_board_p"],
            later["human_board_sample"]) == (2, 0.0, "p90")
    assert later["human_board"]["band"] == 1
    # 三个平铺键与 human_board 段是同一组值（history 自洽）
    for row in rows:
        hb = row["human_board"]
        assert row["human_board_seats"] == hb["seats"]
        assert row["human_board_p"] == hb["p"]
        assert row["human_board_sample"] == hb["sample"]
    # p=0 时采集侧不注入（不产生 human_board_on 计数），接线仍按档位写 cfg
    assert not bool(first["collect"].get("human_board_on"))
    assert not bool(later["collect"].get("human_board_on"))
    # summary 里带课程描述与收尾状态
    summary = json.load(open(out / "summary.json", encoding="utf-8"))
    assert summary["board_ramp"]["bands"] == 2
    assert summary["board_ramp"]["final"]["seats"] == 2
