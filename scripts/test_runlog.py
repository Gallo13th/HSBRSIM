"""`hsbg.az.train.runlog` 单测：jsonl 追加/读取、旧格式兼容、slim_collect 剪裁。"""

from __future__ import annotations

import json
import os

from hsbg.az.train.runlog import (append_record, read_run, slim_collect,
                                  write_header, write_summary)


def test_jsonl_append_and_read(tmp_path):
    p = str(tmp_path / "history.jsonl")
    write_header(p, {"games": 192, "arch": "entity"})
    assert os.path.isfile(p)
    # header 只写一次
    write_header(p, {"games": 999})
    for i in range(3):
        append_record(p, {"iter": i, "decisions": 1000 * i})
    header, records = read_run(p)
    assert header["games"] == 192          # 第二次 write_header 不覆盖
    assert [r["iter"] for r in records] == [0, 1, 2]
    assert records[2]["decisions"] == 2000


def test_read_run_handles_partial_line(tmp_path):
    p = str(tmp_path / "history.jsonl")
    write_header(p, {"seed": 1})
    append_record(p, {"iter": 0})
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"iter": 1, "dec')       # 崩溃时可能留下半行
    _h, records = read_run(p)
    assert [r["iter"] for r in records] == [0]


def test_read_run_legacy_json(tmp_path):
    p = str(tmp_path / "history.json")
    json.dump({"args": {"games": 8}, "history": [{"iter": 0}, {"iter": 1}]},
              open(p, "w", encoding="utf-8"))
    header, records = read_run(p)
    assert header["games"] == 8
    assert len(records) == 2


def test_read_run_missing_file(tmp_path):
    assert read_run(str(tmp_path / "nope.jsonl")) == ({}, [])


def test_slim_collect_drops_big_fields():
    meta = {
        "decisions": 31000,
        "worker_meta": [{"game": i, "big": "x" * 100} for i in range(192)],
        "collect": {"decisions": 31000, "worker_meta": [1, 2, 3],
                    "games_meta": [{"a": 1}], "records_bytes": 431000000},
    }
    slim = slim_collect(meta)
    assert "worker_meta" not in slim
    assert "worker_meta" not in slim["collect"]
    assert "games_meta" not in slim["collect"]
    assert slim["decisions"] == 31000
    assert slim["collect"]["records_bytes"] == 431000000
    # 原对象不被修改
    assert "worker_meta" in meta


def test_summary_is_compact(tmp_path):
    p = str(tmp_path / "summary.json")
    write_summary(p, {"iterations": 3, "updates": 3, "last_records": [{"iter": 2}]})
    data = json.load(open(p, encoding="utf-8"))
    assert data["iterations"] == 3
    assert os.path.isfile(p)
