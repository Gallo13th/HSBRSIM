"""训练吞吐数据通路测试：records 落盘精度（fp32/fp16）与 IPC（disk/shm）。

契约（三条，全部为**可关闭开关**，默认值 = 历史行为）：

1. ``--ipc-mode disk`` + ``--records-dtype fp32``（默认）不改变任何字节，父进程看到的
   数组与旧版 ``_save_built_batch`` 逐位相同；
2. ``--ipc-mode shm`` 只是把同一批数组从「npz 文件」换成「/dev/shm 段」，
   父进程读回的数组与 disk 路径**逐位相同**（`np.array_equal` 全字段）；
3. ``--records-dtype fp16`` 只把 ``features``（float32, 3227 列，占 records 字节的 88%）
   降精度存储，父进程 ``_upcast_records`` 立刻还原成 float32；其他字段（cards int16 /
   masks bool / actions int64 …）**不受影响**，逐位相同。

另含 micro-benchmark（``python tests/test_train_throughput.py --bench``）：直接量化
「worker 侧 save + 父进程 read + concat」在 4 种组合下的耗时与字节数。
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train import process_pool as PP  # noqa: E402

_N_FEAT = 3227
_N_CARDS = 124
_N_EB = 245
_SHM_OK = os.path.isdir("/dev/shm")


# ---------------------------------------------------------------------------
# 合成一份与 ``_batch_arrays`` 同构的 records 数组集合
# ---------------------------------------------------------------------------
def _make_arrays(n: int = 64, *, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    n_games = (n + 7) // 8
    game_ids = np.repeat(np.arange(n_games, dtype=np.int64), 8)[:n]
    seats = np.tile(np.arange(8, dtype=np.int32), n_games)[:n]
    # features：真实观测里既有小整数也有浮点（atk/hp/统计位），这里两者都覆盖
    feats = rng.integers(0, 300, size=(n, _N_FEAT)).astype(np.float32)
    feats[:, :128] = rng.random((n, 128), dtype=np.float32)
    # 少量超过 fp16 整数精度（2048）的值，用来证明 fp16 是「有损但只在 features 上」
    feats[:2, 0] = 123456.0
    cards = rng.integers(0, 3981, size=(n, _N_CARDS)).astype(np.int16)
    masks = np.zeros((n, _N_EB), dtype=bool)
    masks[:, :50] = True
    return {
        "features": feats,
        "cards": cards,
        "masks": masks,
        "actions": rng.integers(0, 245, size=n).astype(np.int64),
        "old_logprobs": rng.standard_normal(n).astype(np.float32),
        "values": rng.standard_normal(n).astype(np.float32),
        "rewards": np.zeros(n, np.float32),
        "dones": np.zeros(n, np.float32),
        "advantages": rng.standard_normal(n).astype(np.float32),
        "returns": rng.standard_normal(n).astype(np.float32),
        "seats": seats,
        "game_ids": game_ids,
        "ranks": rng.integers(1, 9, size=n).astype(np.int64),
        "turns": rng.integers(1, 16, size=n).astype(np.int32),
        "forced": (rng.random(n) < 0.05),
        "has_pi": np.zeros(n, dtype=bool),
        "episode_ids": (game_ids * 8 + seats).astype(np.int64),
        "target_pi": rng.random((n, _N_EB), dtype=np.float32),
    }


def _assert_arrays_equal(a: dict, b: dict, *, keys=None) -> None:
    keys = list(keys or a.keys())
    assert sorted(keys) == sorted(b.keys()), f"字段集合不同: {sorted(a)} vs {sorted(b)}"
    for k in keys:
        x, y = np.asarray(a[k]), np.asarray(b[k])
        assert x.dtype == y.dtype, f"{k} dtype {x.dtype} != {y.dtype}"
        assert x.shape == y.shape, f"{k} shape {x.shape} != {y.shape}"
        assert np.array_equal(x, y), f"{k} 不逐位相等"


def _read_disk(path: str) -> dict:
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


# ---------------------------------------------------------------------------
# 1) 默认路径（disk + fp32）：npz 写读逐位往返
# ---------------------------------------------------------------------------
def test_disk_fp32_bitwise_roundtrip(tmp_path) -> None:
    arrays = _make_arrays(48)
    path = str(tmp_path / "rec.npz")
    meta = PP._emit_records(arrays, ipc_mode="disk", records_dtype="fp32",
                            records_file=path)
    assert meta is None
    assert os.path.getsize(path) > 0
    got = _read_disk(path)
    _assert_arrays_equal(arrays, got)
    # fp32 路径不做 upcast（原 dtype 就是 fp32）
    _assert_arrays_equal(got, PP._upcast_records(got))


# ---------------------------------------------------------------------------
# 2) shm：与 disk 路径逐位相同（核心等价性）
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _SHM_OK, reason="需要 /dev/shm")
def test_shm_fp32_bitwise_equals_disk(tmp_path) -> None:
    arrays = _make_arrays(48)
    path = str(tmp_path / "rec.npz")
    PP._emit_records(arrays, ipc_mode="disk", records_dtype="fp32", records_file=path)
    disk = _read_disk(path)

    slots: dict = {}
    name = f"{PP._SHM_PREFIX}unit_{uuid.uuid4().hex[:8]}"
    try:
        meta = PP._emit_records(arrays, ipc_mode="shm", records_dtype="fp32",
                                shm_name=name, slots=slots, slot_idx=0)
        assert meta and meta["name"] == name
        assert meta["size"] >= meta["nbytes"] > 0
        shm_arrays, seg = PP._shm_read(meta)
        try:
            _assert_arrays_equal(disk, shm_arrays)
        finally:
            del shm_arrays
            seg.close()
    finally:
        PP._shm_close_slot(slots, 0)
    assert not os.path.exists(os.path.join("/dev/shm", name))


# ---------------------------------------------------------------------------
# 3) fp16：只动 features，父进程立刻还原 fp32
# ---------------------------------------------------------------------------
def test_records_dtype_fp16_only_features(tmp_path) -> None:
    arrays = _make_arrays(32)
    path32 = str(tmp_path / "f32.npz")
    path16 = str(tmp_path / "f16.npz")
    PP._emit_records(arrays, ipc_mode="disk", records_dtype="fp32", records_file=path32)
    PP._emit_records(arrays, ipc_mode="disk", records_dtype="fp16", records_file=path16)

    f32 = _read_disk(path32)
    f16 = _read_disk(path16)
    # features：存储 dtype 变 fp16，upcast 后与「fp32→fp16→fp32」逐位相等
    assert f16["features"].dtype == np.float16
    assert f32["features"].dtype == np.float32
    expect = PP._cast_fp32(f16["features"])
    up = PP._upcast_records(f16)
    assert up["features"].dtype == np.float32
    assert np.array_equal(up["features"], expect)
    # clamp：>65504 的值夹到 fp16 上限（不出 inf/NaN）
    assert np.isfinite(up["features"]).all()
    assert float(up["features"].max()) <= 65504.0
    # 除 features 外全部逐位相同（cards 是 int16，转 fp16 既不省字节又丢索引）
    others = [k for k in arrays if k != "features"]
    _assert_arrays_equal({k: f32[k] for k in others}, {k: f16[k] for k in others})
    # 字节收益：features 恰好减半，其余不变
    saved = os.path.getsize(path32) - os.path.getsize(path16)
    assert saved == arrays["features"].nbytes // 2

    # 有损性必须在 features 里真实存在（否则本用例覆盖不到 fp16 路径）
    assert not np.array_equal(up["features"], arrays["features"])


@pytest.mark.skipif(not _SHM_OK, reason="需要 /dev/shm")
def test_shm_fp16_payload_and_roundtrip() -> None:
    arrays = _make_arrays(24)
    slots: dict = {}
    name = f"{PP._SHM_PREFIX}unit16_{uuid.uuid4().hex[:8]}"
    try:
        meta = PP._emit_records(arrays, ipc_mode="shm", records_dtype="fp16",
                                shm_name=name, slots=slots, slot_idx=0)
        other = sum(np.asarray(v).nbytes for k, v in arrays.items() if k != "features")
        assert meta["nbytes"] == arrays["features"].nbytes // 2 + other
        got, seg = PP._shm_read(meta)
        up = PP._upcast_records(got)
        try:
            assert np.array_equal(
                up["features"], PP._cast_fp32(PP._cast_fp16(arrays["features"])))
            for k in arrays:
                if k != "features":
                    assert np.array_equal(np.asarray(up[k]), np.asarray(arrays[k])), k
        finally:
            # up 里非 fp16 字段是 shm 视图：必须先全部放掉才能 close（否则 BufferError）
            del up, got
            seg.close()
            PP._shm_close_slot(slots, 0)
    finally:
        PP._shm_close_slot(slots, 0)


# ---------------------------------------------------------------------------
# 4) 环形 slot：复用 / 扩容 / 清理
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _SHM_OK, reason="需要 /dev/shm")
def test_shm_slot_reuse_grow_and_cleanup() -> None:
    slots: dict = {}
    name = f"{PP._SHM_PREFIX}unitring_{uuid.uuid4().hex[:8]}"
    try:
        small = _make_arrays(4)
        m0 = PP._emit_records(small, ipc_mode="shm", records_dtype="fp32",
                              shm_name=name, slots=slots, slot_idx=0)
        sz0 = slots[0].size
        big = _make_arrays(64)
        m1 = PP._emit_records(big, ipc_mode="shm", records_dtype="fp32",
                              shm_name=name, slots=slots, slot_idx=0)
        assert len(slots) == 1 and slots[0].size >= m1["nbytes"]
        assert slots[0].size >= sz0
        got, seg = PP._shm_read(m1)
        try:
            assert np.array_equal(got["features"], big["features"])
        finally:
            del got
            seg.close()
        # 第二个 slot 独立
        m2 = PP._emit_records(small, ipc_mode="shm", records_dtype="fp32",
                              shm_name=name + "_s1", slots=slots, slot_idx=1)
        assert len(slots) == 2 and m2["name"].endswith("_s1")
    finally:
        for slot in list(slots):
            PP._shm_close_slot(slots, slot)
    assert not os.path.exists(os.path.join("/dev/shm", name))
    assert not os.path.exists(os.path.join("/dev/shm", name + "_s1"))


@pytest.mark.skipif(not _SHM_OK, reason="需要 /dev/shm")
def test_purge_stale_shm_only_old_and_prefixed() -> None:
    from multiprocessing import shared_memory

    old_name = f"{PP._SHM_PREFIX}unit_old_{uuid.uuid4().hex[:8]}"
    new_name = f"{PP._SHM_PREFIX}unit_new_{uuid.uuid4().hex[:8]}"
    foreign = f"other_app_{uuid.uuid4().hex[:8]}"
    segs = []
    try:
        for nm in (old_name, new_name, foreign):
            segs.append(shared_memory.SharedMemory(name=nm, create=True, size=1 << 20))
        old_path = os.path.join("/dev/shm", old_name)
        os.utime(old_path, (time.time() - 7200, time.time() - 7200))
        removed = PP._purge_stale_shm(max_age_s=3600)
        assert removed >= 1
        assert not os.path.exists(old_path)
        assert os.path.exists(os.path.join("/dev/shm", new_name))
        assert os.path.exists(os.path.join("/dev/shm", foreign))
    finally:
        for seg in segs:
            try:
                seg.close()
                seg.unlink()
            except FileNotFoundError:
                pass


@pytest.mark.skipif(not _SHM_OK, reason="需要 /dev/shm")
def test_purge_dead_owner_segments() -> None:
    """trainer 被 SIGKILL 后：下一次 pool 启动按 owner 文件的 pid 清掉整族残留段。"""
    from multiprocessing import shared_memory

    tag = f"unitdead_{uuid.uuid4().hex[:8]}"
    name = f"{PP._SHM_PREFIX}{tag}_w0_s0"
    owner = PP._shm_owner_path(tag)
    seg = shared_memory.SharedMemory(name=name, create=True, size=1 << 20)
    try:
        with open(owner, "w", encoding="utf-8") as f:
            f.write("999999999")            # 不存在的 pid = 主人已死
        removed = PP._purge_stale_shm()
        assert removed >= 1
        assert not os.path.exists(os.path.join("/dev/shm", name))
        assert not os.path.exists(owner)
    finally:
        try:
            seg.close()
            seg.unlink()
        except FileNotFoundError:
            pass
        if os.path.exists(owner):
            os.unlink(owner)


@pytest.mark.skipif(not _SHM_OK, reason="需要 /dev/shm")
def test_shm_parent_read_close_does_not_leak_fds() -> None:
    """父进程 50 轮 read→concat→close：fd 数不得增长（2026-11-02 生产 fd 泄漏回归）。"""
    if not os.path.isdir("/proc/self/fd"):
        pytest.skip("需要 /proc 查看 fd 数")
    arrays = _make_arrays(16)
    slots: dict = {}
    name = f"{PP._SHM_PREFIX}unitfd_{uuid.uuid4().hex[:8]}"
    try:
        meta = PP._emit_records(arrays, ipc_mode="shm", records_dtype="fp32",
                                shm_name=name, slots=slots, slot_idx=0)
        base = len(os.listdir("/proc/self/fd"))
        for _ in range(50):
            got, seg = PP._shm_read(meta)
            merged = {k: np.concatenate([np.asarray(v)], axis=0)
                      for k, v in got.items()}
            got.clear()
            del got, merged
            seg.close()                    # 视图已放掉 ⇒ 不应再抛 BufferError
        now = len(os.listdir("/proc/self/fd"))
        assert now <= base + 3, f"fd 从 {base} 涨到 {now}（每轮 attach 后必须 close）"
    finally:
        PP._shm_close_slot(slots, 0)


@pytest.mark.skipif(not _SHM_OK, reason="需要 /dev/shm")
def test_close_shm_never_breaks_on_buffer_error() -> None:
    """即使某个段还有活视图，_close_shm 也必须把**其余**段全关掉（旧实现会 break）。"""
    from multiprocessing import shared_memory

    name = f"{PP._SHM_PREFIX}unitclose_{uuid.uuid4().hex[:8]}"
    segs = [shared_memory.SharedMemory(name=f"{name}_s{i}", create=True, size=1 << 20)
            for i in range(3)]
    pool = object.__new__(PP.ProcessActorPool)      # 不 spawn worker
    pool._shm_open = list(segs)
    pool._shm_unclosed = 0
    keep_view = np.frombuffer(segs[1].buf, dtype=np.float32, count=1024)
    try:
        pool._close_shm()
        # s0/s2 关掉了；s1 因为视图活着被留到下轮（旧实现会 break，两个都不关）
        assert pool._shm_unclosed == 1
        del keep_view
        pool._close_shm()
        assert pool._shm_unclosed == 0
    finally:
        try:
            del keep_view
        except (NameError, UnboundLocalError):
            pass
        for seg in segs:
            try:
                seg.close()
                seg.unlink()
            except (BufferError, FileNotFoundError):
                pass


# ---------------------------------------------------------------------------
# 5) 开关校验（非法值必须在 spawn worker 之前 fail-fast）
# ---------------------------------------------------------------------------
def test_pool_rejects_bad_ipc_flags(tmp_path) -> None:
    ckpt = str(tmp_path / "model.pt")
    with pytest.raises(ValueError):
        PP.ProcessActorPool(2, [0], ckpt, ipc_mode="bogus")
    with pytest.raises(ValueError):
        PP.ProcessActorPool(2, [0], ckpt, records_dtype="bf16")


# ---------------------------------------------------------------------------
# 6) micro-benchmark：disk/shm × fp32/fp16 的 save / read / concat
# ---------------------------------------------------------------------------
def _bench_round(n: int, dtype: str, mode: str, tmpdir: str) -> dict:
    arrays = _make_arrays(n)
    slots: dict = {}
    name = f"{PP._SHM_PREFIX}bench_{uuid.uuid4().hex[:8]}"
    path = os.path.join(tmpdir, f"bench_{dtype}_{mode}.npz")
    t0 = time.perf_counter()
    cast = PP._cast_records_dtype(arrays, dtype)
    cast_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    meta = PP._emit_records(cast, ipc_mode=mode, records_dtype=dtype,
                            records_file=path, shm_name=name, slots=slots, slot_idx=0)
    save_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    if mode == "shm":
        got, seg = PP._shm_read(meta)
    else:
        got, seg = _read_disk(path), None
    read_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    merged = {k: np.concatenate([np.asarray(v)], axis=0) for k, v in got.items()}
    concat_s = time.perf_counter() - t0
    if seg is not None:
        del got
        seg.close()
        PP._shm_close_slot(slots, 0)
    nbytes = int(meta["nbytes"]) if mode == "shm" else int(os.path.getsize(path))
    assert np.array_equal(merged["actions"], arrays["actions"])
    if mode == "disk":
        os.remove(path)
    return {"n": n, "dtype": dtype, "mode": mode, "mb": nbytes / 1e6,
            "cast_s": cast_s, "save_s": save_s, "read_s": read_s,
            "concat_s": concat_s,
            "total_s": cast_s + save_s + read_s + concat_s}


def bench(n: int = 25000, out: str = "") -> dict:
    tmpdir = os.path.join(ROOT, "runs", "bench")
    os.makedirs(tmpdir, exist_ok=True)
    rows = []
    for dtype in ("fp32", "fp16"):
        for mode in ("disk", "shm"):
            if mode == "shm" and not _SHM_OK:
                continue
            rows.append(_bench_round(n, dtype, mode, tmpdir))
    print(f"\nrecords IPC micro-bench（n={n} decisions/iter）")
    print("| mode | dtype | MB | cast_s | save_s | read_s | concat_s | total_s |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print("| {mode} | {dtype} | {mb:.1f} | {cast_s:.3f} | {save_s:.3f} | {read_s:.3f} "
              "| {concat_s:.3f} | {total_s:.3f} |".format(**r))
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        print(f"[bench] 写入 {out}")
    return {"n": n, "rows": rows}


if __name__ == "__main__":
    n = 25000
    out = ""
    args = sys.argv[1:]
    for k, a in enumerate(args):
        if a == "--n" and k + 1 < len(args):
            n = int(args[k + 1])
        if a == "--out" and k + 1 < len(args):
            out = args[k + 1]
    bench(n=n, out=out)
