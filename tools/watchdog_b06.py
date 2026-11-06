#!/usr/bin/env python3
"""B06 崩溃看门狗（泛化版）：detect trainer 消失 -> 从最新快照续训，并同步 monitor 的
``--cum-offset``（关键：续训后 history.jsonl 会保留崩溃前行，monitor 的累加值会超前
offset = Σhistory − DONE，不传就会重演 B05 的「点全被 skipped」）。

用法：
  python /tmp/watchdog_b06.py --init --done 0     # 开跑前登记基线
  setsid nohup python /tmp/watchdog_b06.py > /tmp/watchdog_b06.log 2>&1 &
  touch /tmp/watchdog_b06.pause                   # 暂停（不自动续训）
"""
import json
import os
import re
import subprocess
import sys
import time
import glob

ROOT = "/home/data/users/gaoletian/projects/HSBRSIM"
RUN = os.path.join(ROOT, "runs/az_stage300m_b06")
TAG = "az_stage300m_b06"
HIST = os.path.join(RUN, "history.jsonl")
STATE = "/tmp/watchdog_b06_state.json"
LOG = "/tmp/watchdog_b06.log"
PAUSE = "/tmp/watchdog_b06.pause"
LOCK = "/tmp/watchdog_b06.lock"
STOP_GLOBAL = 300_000_000
SEED_BASE = 27810
GAME_WEIGHT_MODE = "adv"
GAME_WEIGHT_ALPHA = "0.5"
GAME_WEIGHT_BETA = "0.5"
GAME_WEIGHT_FLOOR = "0.5"
GAME_WEIGHT_CAP = "2.0"
PY = os.path.expanduser("~/.conda/envs/hiermolgen/bin/python")


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
    seg = entries[base_len:]
    idx = None
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
    return int(re.search(r"step_(\d+)", p).group(1)), p


def trainer_alive():
    r = subprocess.run(["pgrep", "-u", os.environ.get("USER", "gaoletian"),
                        "-f", "train_entity_sync[.]py"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def cleanup():
    user = os.environ.get("USER", "gaoletian")
    for pat in ("train_entity_sync[.]py", "multiprocessing.spawn",
                "stage_monitor.py", "relabel_b06.sh"):
        subprocess.run(["pkill", "-u", user, "-f", pat])
    time.sleep(4)
    subprocess.run(["pkill", "-9", "-u", user, "-f", "multiprocessing.spawn"])
    time.sleep(3)


def resume_script(done, snap_iter, seed, eval_first, offset):
    return """#!/bin/bash
set -euo pipefail
cd {root}
export PYTHONPATH=rust/python:.
DONE={done}
CK={run}/snapshots/step_{it:06d}/model.pt
TS={run}/snapshots/step_{it:06d}/trainer.pt
OUT={run}
SEED={seed}
STOP=$(({stop} - DONE))
MINUTES=1200
PROCESSES=32; THREADS=2; MINIBATCH=1024; GRAD_ACCUM=2; GAMES=384
GPUS=3,4,5,6; DEVICE=cuda:0; EVAL_DEVICE=cuda:1; EVAL_GAMES=96
EVAL_FIRST={eval_first}
SNAPSHOT_EVERY=100; KEEP_SNAPSHOTS=8
TAG={tag}
LR=3.0e-06; LR_MIN_RATIO=0.5; MAX_UPDATES=4300
HB_RAMP="0:1:0.30, 15M:2:0.50, 40M:3:0.70, 80M:3:0.90"
HB_QUANTILE_RAMP="0:p50, 40M:p75, 150M:p90"
RAMP_MODE=step
RAMP_START=$DONE
export EPOCHS=1 CLIP=0.2 TARGET_KL=0.02 ENTROPY_COEF=0.001 MAX_GRAD_NORM=1.0
export GAME_WEIGHT_MODE={gwm} GAME_WEIGHT_ALPHA={gwa} GAME_WEIGHT_BETA={gwb} \\
       GAME_WEIGHT_FLOOR={gwf} GAME_WEIGHT_CAP={gwc}
CK="$CK" TS="$TS" OUT="$OUT" SEED="$SEED" STOP_DECISIONS="$STOP" \\
MINUTES="$MINUTES" PROCESSES="$PROCESSES" THREADS="$THREADS" \\
MINIBATCH="$MINIBATCH" GRAD_ACCUM="$GRAD_ACCUM" GAMES="$GAMES" \\
GPUS="$GPUS" DEVICE="$DEVICE" EVAL_DEVICE="$EVAL_DEVICE" EVAL_GAMES="$EVAL_GAMES" \\
EVAL_FIRST_DECISIONS="$EVAL_FIRST" SNAPSHOT_EVERY="$SNAPSHOT_EVERY" KEEP_SNAPSHOTS="$KEEP_SNAPSHOTS" TAG="$TAG" \\
LR="$LR" LR_MIN_RATIO="$LR_MIN_RATIO" MAX_UPDATES="$MAX_UPDATES" \\
HB_RAMP="$HB_RAMP" HB_QUANTILE_RAMP="$HB_QUANTILE_RAMP" RAMP_MODE="$RAMP_MODE" RAMP_START="$RAMP_START" \\
FROZEN_SEATS=0 FROZEN_OPPONENT="" LEAF_WAIT_MS=0.0 FORCE=1 \\
bash scripts/run_stage300m.sh
""".format(root=ROOT, run=RUN, it=snap_iter, done=done, seed=seed,
           stop=STOP_GLOBAL, eval_first=eval_first, tag=TAG,
           gwm=GAME_WEIGHT_MODE, gwa=GAME_WEIGHT_ALPHA, gwb=GAME_WEIGHT_BETA,
           gwf=GAME_WEIGHT_FLOOR, gwc=GAME_WEIGHT_CAP)


def launch(done, snap_iter, seed):
    nxt = ((done // 10_000_000) + 1) * 10_000_000
    eval_first = max(1, nxt - done)
    ents = hist_entries()
    offset = sum(d for _, d in ents) - done          # monitor 的 cum 超前量
    path = "/tmp/resume_b06_wd.sh"
    open(path, "w").write(resume_script(done, snap_iter, seed, eval_first, offset))
    os.chmod(path, 0o755)
    subprocess.Popen(["setsid", "bash", path],
                     stdout=open("/tmp/b06_wd_launch.log", "a"),
                     stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(2)
    subprocess.Popen(["setsid", "bash", "/home/data/users/gaoletian/projects/HSBRSIM/tools/relabel_b06.sh", str(done), time.strftime("%F %T")],
                     stdout=open("/tmp/relabel_b06.log", "a"),
                     stderr=subprocess.STDOUT, start_new_session=True)
    mon = ["setsid", PY, "scripts/stage_monitor.py",
           "--run", RUN, "--until-decisions", str(STOP_GLOBAL), "--eval-gpu", "auto",
           "--gpu-priority", "7,1,6", "--bot-panel-games", "96", "--bot-panel-seed", "620000",
           "--redraw-every", "120", "--dev-offset", str(done),
           "--cum-offset", str(offset),
           "--dev-resume-epoch", str(int(time.time())),
           "--retry-skipped", "1", "--retry-min-decisions", str(done)]
    subprocess.Popen(mon, cwd=ROOT, stdout=open("/tmp/b06_monitor.log", "a"),
                     stderr=subprocess.STDOUT, start_new_session=True,
                     env=dict(os.environ, PYTHONPATH="rust/python:."))
    log("resume: snap=%d DONE=%d offset=%d eval_first=%d seed=%d" %
        (snap_iter, done, offset, eval_first, seed))


def main(dry=False):
    st = json.load(open(STATE)) if os.path.exists(STATE) else None
    if st is None:
        log("无 state（需先 --init --done N）"); return
    if trainer_alive() or os.path.exists(PAUSE):
        return
    time.sleep(20)
    if trainer_alive() or os.path.exists(PAUSE):
        return
    it, _ = latest_snapshot()
    if it is None:
        log("无快照，放弃"); return
    ents = hist_entries()
    done = cum_at(ents, st["done"], st["hist_len"], it)
    if done is None:
        log("cum_at 失败 iter=%d" % it); return
    seed = SEED_BASE + st.get("gen", 0) + 1
    log("trainer 消失 -> 续训: snap=%d DONE=%d STOP=%d seed=%d" % (it, done, STOP_GLOBAL - done, seed))
    if dry:
        log("dry-run：不启动"); return
    cleanup()
    launch(done, it, seed)
    json.dump({"done": done, "hist_len": len(ents), "gen": st.get("gen", 0) + 1}, open(STATE, "w"))
    log("已启动；新基线 DONE=%d hist_len=%d" % (done, len(ents)))


if __name__ == "__main__":
    if "--init" in sys.argv:
        done = int(sys.argv[sys.argv.index("--done") + 1])
        ents = hist_entries()
        json.dump({"done": done, "hist_len": len(ents), "gen": 0}, open(STATE, "w"))
        log("init: DONE=%d hist_len=%d" % (done, len(ents)))
    elif "--dry-run" in sys.argv:
        main(dry=True)
    else:
        while True:
            try:
                main()
            except Exception as e:  # noqa: BLE001
                log("ERR %r" % (e,))
            time.sleep(60)
