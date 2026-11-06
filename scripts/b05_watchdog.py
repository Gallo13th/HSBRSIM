#!/usr/bin/env python3
"""B05 崩溃看门狗（scripts/b05_watchdog.py）：检测 trainer 消失 -> 用**正确偏移**从最新快照续训（每 60s 检查）。

用法::
    python scripts/b05_watchdog.py --init --done <当前累计>   # 登记基线（hist_len 取段起点）
    setsid nohup python scripts/b05_watchdog.py >> /tmp/watchdog_b05.out 2>&1 &

每次续训会自动：写 /tmp/resume_b05_wd.sh、清理残留 worker/monitor/relabeler、重启 monitor（--dev-offset=DONE）
与 relabeler，并把新基线写回 /tmp/watchdog_b05_state.json。**不要在手动操作训练时让它同时跑**（touch /tmp/watchdog_b05.pause 可暂停）。


关键：DONE 必须取"快照那一步的累计决策数"，不能取崩溃点的累计（否则 RAMP/EVAL/STOP 全错位）。
本脚本通过 launch 时记录的 (done, hist_len) 基线 + 本次进程段内的 history 增量来计算。
"""
import json, os, re, subprocess, sys, time, glob

ROOT = "/home/data/users/gaoletian/projects/HSBRSIM"
RUN = os.path.join(ROOT, "runs/az_stage300m_b05")
HIST = os.path.join(RUN, "history.jsonl")
STATE = "/tmp/watchdog_b05_state.json"
LOG = "/tmp/watchdog_b05.log"
PAUSE = "/tmp/watchdog_b05.pause"
STOP_GLOBAL = 300_000_000
SEED_BASE = 27705


def log(msg):
    line = "[%s] %s" % (time.strftime("%F %T"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def hist_entries():
    out = []
    if not os.path.exists(HIST):
        return out
    for line in open(HIST, encoding="utf-8", errors="ignore"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        it = r.get("iter")
        dec = (r.get("collect") or {}).get("decisions") or 0
        if it is not None:
            out.append((int(it), int(dec)))
    return out


def cum_at(entries, base_done, base_len, snap_iter):
    """本段内 iter==snap_iter 的最后一条为止的累计。"""
    seg = entries[base_len:]
    idx = None
    # 取**本段第一次**出现 snap_iter 的位置（续训段可能重新写一行同号 iter）
    for i, (it, _) in enumerate(seg):
        if it == snap_iter:
            idx = i
            break
    if idx is None:
        for i, (it, _) in enumerate(seg):
            if it <= snap_iter:
                idx = i
    if idx is None:
        return None
    return base_done + sum(d for _, d in seg[: idx + 1])


def latest_snapshot():
    snaps = sorted(glob.glob(os.path.join(RUN, "snapshots/step_*/model.pt")))
    if not snaps:
        return None, None
    p = snaps[-1]
    it = int(re.search(r"step_(\d+)", p).group(1))
    return it, p


def trainer_alive():
    r = subprocess.run(["pgrep", "-u", os.environ.get("USER", "gaoletian"),
                        "-f", "train_entity_sync[.]py"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def cleanup():
    for pat in ("train_entity_sync[.]py", "multiprocessing.spawn",
                "stage_monitor.py", "relabel_b05.sh"):
        subprocess.run(["pkill", "-u", os.environ.get("USER", "gaoletian"), "-f", pat])
    time.sleep(4)
    subprocess.run(["pkill", "-9", "-u", os.environ.get("USER", "gaoletian"),
                    "-f", "multiprocessing.spawn"])
    time.sleep(3)


def launch(done, snap_iter, seed):
    stop = STOP_GLOBAL - done
    nxt = ((done // 10_000_000) + 1) * 10_000_000
    eval_first = max(1, nxt - done)
    out = "/tmp/resume_b05_wd.sh"
    tmpl = """#!/bin/bash
set -euo pipefail
cd {root}
export PYTHONPATH=rust/python:.
DONE={done}
CK={run}/snapshots/step_{it:06d}/model.pt
TS={run}/snapshots/step_{it:06d}/trainer.pt
OUT={run}
SEED={seed}
STOP=$((300000000 - DONE))
MINUTES=1200
PROCESSES=32; THREADS=2; MINIBATCH=1024; GRAD_ACCUM=2; GAMES=384
GPUS=3,4,5,6; DEVICE=cuda:0; EVAL_DEVICE=cuda:1; EVAL_GAMES=96
EVAL_FIRST={eval_first}
SNAPSHOT_EVERY=100; KEEP_SNAPSHOTS=8
TAG=az_stage300m_b05
LR=3.0e-06; LR_MIN_RATIO=0.5; MAX_UPDATES=4300
HB_RAMP="0:1:0.30, 15M:2:0.50, 40M:3:0.70, 80M:3:0.90"
HB_QUANTILE_RAMP="0:p50, 40M:p75, 150M:p90"
RAMP_MODE=step
RAMP_START=$DONE
export EPOCHS=1 CLIP=0.2 TARGET_KL=0.02 ENTROPY_COEF=0.001 MAX_GRAD_NORM=1.0
CK="$CK" TS="$TS" OUT="$OUT" SEED="$SEED" STOP_DECISIONS="$STOP" \\
MINUTES="$MINUTES" PROCESSES="$PROCESSES" THREADS="$THREADS" \\
MINIBATCH="$MINIBATCH" GRAD_ACCUM="$GRAD_ACCUM" GAMES="$GAMES" \\
GPUS="$GPUS" DEVICE="$DEVICE" EVAL_DEVICE="$EVAL_DEVICE" EVAL_GAMES="$EVAL_GAMES" \\
EVAL_FIRST_DECISIONS="$EVAL_FIRST" SNAPSHOT_EVERY="$SNAPSHOT_EVERY" KEEP_SNAPSHOTS="$KEEP_SNAPSHOTS" TAG="$TAG" \\
LR="$LR" LR_MIN_RATIO="$LR_MIN_RATIO" MAX_UPDATES="$MAX_UPDATES" \\
HB_RAMP="$HB_RAMP" HB_QUANTILE_RAMP="$HB_QUANTILE_RAMP" RAMP_MODE="$RAMP_MODE" RAMP_START="$RAMP_START" \\
FROZEN_SEATS=0 FROZEN_OPPONENT="" LEAF_WAIT_MS=0.0 FORCE=1 \\
bash scripts/run_stage300m.sh
""".format(root=ROOT, run=RUN, done=done, it=snap_iter, seed=seed, eval_first=eval_first)
    open(out, "w").write(tmpl)
    os.chmod(out, 0o755)
    subprocess.Popen(["setsid", "bash", out], stdout=open("/tmp/b05_wd_launch.log", "a"),
                     stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(2)
    # monitor + relabeler（offset=done）
    relabel = "/tmp/relabel_b05.sh"
    subprocess.Popen(["setsid", "bash", relabel, str(done), time.strftime("%F %T")],
                     stdout=open("/tmp/relabel_b05.log", "a"), stderr=subprocess.STDOUT,
                     start_new_session=True)
    mon = ["setsid", os.path.expanduser("~/.conda/envs/hiermolgen/bin/python"), "scripts/stage_monitor.py",
           "--run", RUN, "--until-decisions", str(STOP_GLOBAL), "--eval-gpu", "auto",
           "--gpu-priority", "7,1,6", "--bot-panel-games", "96", "--bot-panel-seed", "620000",
           "--redraw-every", "120", "--dev-offset", str(done), "--dev-resume-epoch", str(int(time.time()))]
    subprocess.Popen(mon, cwd=ROOT, stdout=open("/tmp/b05_monitor.log", "a"),
                     stderr=subprocess.STDOUT, start_new_session=True,
                     env=dict(os.environ, PYTHONPATH="rust/python:."))


def main():
    dry = "--dry-run" in sys.argv
    st = json.load(open(STATE)) if os.path.exists(STATE) else None
    if st is None:
        log("no state file; watchdog idle (需先登记基线)")
        return
    ents = hist_entries()
    if trainer_alive() or os.path.exists(PAUSE):
        return
    time.sleep(20)                      # 给"正常收尾"留缓冲
    if trainer_alive() or os.path.exists(PAUSE):
        return
    it, _ = latest_snapshot()
    if it is None:
        log("no snapshot; abort"); return
    done = cum_at(ents, st["done"], st["hist_len"], it)
    if done is None:
        log("cum_at 计算失败 iter=%d" % it); return
    seed = SEED_BASE + st.get("gen", 0) + 1
    log("trainer 消失 -> 续训: snap_iter=%d DONE=%d STOP=%d seed=%d" % (it, done, STOP_GLOBAL - done, seed))
    if dry:
        log("dry-run：不启动"); return
    cleanup()
    launch(done, it, seed)
    json.dump({"done": done, "hist_len": len(ents), "gen": st.get("gen", 0) + 1}, open(STATE, "w"))
    log("已启动续训；新基线 DONE=%d hist_len=%d" % (done, len(ents)))


if __name__ == "__main__":
    if "--init" in sys.argv:
        # 登记当前基线：DONE 取 step_000701 的真实累计
        ents = hist_entries()
        it, _ = latest_snapshot()
        base_done = int(sys.argv[sys.argv.index("--done") + 1])
        json.dump({"done": base_done, "hist_len": len(ents), "gen": 0}, open(STATE, "w"))
        log("init: DONE=%d hist_len=%d latest_snap=%s" % (base_done, len(ents), it))
    elif "--dry-run" in sys.argv:
        main()
    else:
        while True:
            try:
                main()
            except Exception as e:
                log("ERR %r" % (e,))
            time.sleep(60)
