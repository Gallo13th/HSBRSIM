#!/usr/bin/env python3
"""B06 崩溃看门狗（泛化版）：detect trainer 消失 -> 从最新快照续训，并同步 monitor 的
``--cum-offset``（关键：续训后 history.jsonl 会保留崩溃前行，monitor 的累加值会超前
offset = Σhistory − DONE，不传就会重演 B05 的「点全被 skipped」）。

用法：
  python /tmp/watchdog_b10.py --init --done 0     # 开跑前登记基线
  setsid nohup python /tmp/watchdog_b10.py > /tmp/watchdog_b10.log 2>&1 &
  touch /tmp/watchdog_b10.pause                   # 暂停（不自动续训）
"""
import json
import os
import re
import subprocess
import sys
import time
import glob

ROOT = "/home/data/users/gaoletian/projects/HSBRSIM"
RUN = os.path.join(ROOT, "runs/az_stage300m_b10")
TAG = "az_stage300m_b10"
HIST = os.path.join(RUN, "history.jsonl")
STATE = "/tmp/watchdog_b10_state.json"
LOG = "/tmp/watchdog_b10.log"
PAUSE = "/tmp/watchdog_b10.pause"
LOCK = "/tmp/watchdog_b10.lock"
STOP_GLOBAL = 300_000_000
SEED_BASE = 28210
GAME_WEIGHT_MODE = "none"      # B07：关闭长强加权
# B07 的唯一变量：人盘 5 席 + full 保真（续训必须原样保留，否则等于换配方）
HB_LIB = "data/real_library/library_real_quasi_full.jsonl"
HB_FIDELITY = "full"
HB_SEATS = "5"
BAN_TRINKETS = "BG36_MagicItem_414"   # 禁用「加重护手」（引擎级报价剔除）
FORCED_UPGRADE = "1"                  # 强制升本（B08 骨架，B10 保留）
CEILING_AUX_COEF = "0.02"             # B10：终局上限辅助头系数（续训必须保留）
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
                "stage_monitor.py", "relabel_b10.sh"):
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
HB_RAMP=""            # B07 用 sample=auto 的按回合曲线
HB_QUANTILE_RAMP=""
RAMP_MODE=step
RAMP_START=$DONE
export EPOCHS=1 CLIP=0.2 TARGET_KL=0.02 ENTROPY_COEF=0.001 MAX_GRAD_NORM=1.0
export GAME_WEIGHT_MODE={gwm} GAME_WEIGHT_ALPHA={gwa} GAME_WEIGHT_BETA={gwb} \\
       GAME_WEIGHT_FLOOR={gwf} GAME_WEIGHT_CAP={gwc}
export HB_LIB="{hb_lib}" HB_FIDELITY="{hb_fid}" HB_SEATS="{hb_seats}"
export FORCED_UPGRADE="{forced_upgrade}" FORCED_UPGRADE_MARGIN="0"
export CEILING_AUX_COEF="{ceiling_aux_coef}" BC_COEF="0.0"
export HSBRSIM_BAN_TRINKETS="{ban_trinkets}"
export HSBRSIM_FORCE_UPGRADE="{forced_upgrade}"
CK="$CK" TS="$TS" OUT="$OUT" SEED="$SEED" STOP_DECISIONS="$STOP" \\
MINUTES="$MINUTES" PROCESSES="$PROCESSES" THREADS="$THREADS" \\
MINIBATCH="$MINIBATCH" GRAD_ACCUM="$GRAD_ACCUM" GAMES="$GAMES" \\
GPUS="$GPUS" DEVICE="$DEVICE" EVAL_DEVICE="$EVAL_DEVICE" EVAL_GAMES="$EVAL_GAMES" \\
EVAL_FIRST_DECISIONS="$EVAL_FIRST" SNAPSHOT_EVERY="$SNAPSHOT_EVERY" KEEP_SNAPSHOTS="$KEEP_SNAPSHOTS" TAG="$TAG" \\
LR="$LR" LR_MIN_RATIO="$LR_MIN_RATIO" MAX_UPDATES="$MAX_UPDATES" \\
HB_RAMP="$HB_RAMP" HB_QUANTILE_RAMP="$HB_QUANTILE_RAMP" RAMP_MODE="$RAMP_MODE" RAMP_START="$RAMP_START" \
HB_LIB="$HB_LIB" HB_FIDELITY="$HB_FIDELITY" HB_SEATS="$HB_SEATS" \\
FORCED_UPGRADE="$FORCED_UPGRADE" FORCED_UPGRADE_MARGIN="$FORCED_UPGRADE_MARGIN" \\
CEILING_AUX_COEF="$CEILING_AUX_COEF" BC_COEF="0.0" \\
HSBRSIM_BAN_TRINKETS="$HSBRSIM_BAN_TRINKETS" \\
HSBRSIM_FORCE_UPGRADE="$HSBRSIM_FORCE_UPGRADE" \\
FROZEN_SEATS=0 FROZEN_OPPONENT="" LEAF_WAIT_MS=0.0 FORCE=1 \\
bash scripts/run_stage300m.sh
""".format(root=ROOT, run=RUN, it=snap_iter, done=done, seed=seed,
           stop=STOP_GLOBAL, eval_first=eval_first, tag=TAG,
           gwm=GAME_WEIGHT_MODE, gwa=GAME_WEIGHT_ALPHA, gwb=GAME_WEIGHT_BETA,
           gwf=GAME_WEIGHT_FLOOR, gwc=GAME_WEIGHT_CAP,
           hb_lib=HB_LIB, hb_fid=HB_FIDELITY, hb_seats=HB_SEATS,
           ban_trinkets=BAN_TRINKETS, forced_upgrade=FORCED_UPGRADE,
           ceiling_aux_coef=CEILING_AUX_COEF)


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
    subprocess.Popen(["setsid", "bash", "/home/data/users/gaoletian/projects/HSBRSIM/tools/relabel_b10.sh", str(done), time.strftime("%F %T")],
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
                     env=dict(os.environ, PYTHONPATH="rust/python:.",
                              HSBRSIM_FORCE_UPGRADE=FORCED_UPGRADE,
                              HSBRSIM_BAN_TRINKETS=BAN_TRINKETS))
    log("resume: snap=%d DONE=%d offset=%d eval_first=%d seed=%d" %
        (snap_iter, done, offset, eval_first, seed))
    # 续训后核对注入口径：模板丢失 env 会把训练场地悄悄换掉（B07 曾因此在 10:50 那次
    # 续训后变成 3 席 + board 跑了 25 分钟）。这里主动比对运行进程的命令行并告警。
    time.sleep(45)
    try:
        r = subprocess.run(["pgrep", "-u", os.environ.get("USER", "gaoletian"),
                            "-af", "train_entity_sync[.]py"],
                           capture_output=True, text=True)
        cmd = r.stdout
        checks = {
            "seats": '--human-board-seats %s' % HB_SEATS,
            "fidelity": '--human-board-fidelity %s' % HB_FIDELITY,
            "lib": os.path.basename(HB_LIB),
        }
        bad = [k for k, v in checks.items() if v not in cmd]
        if GAME_WEIGHT_MODE == "none" and "--game-weight-mode" in cmd:
            bad.append("game_weight")
        if bad:
            log("ERROR 续训口径不一致: %s（期望 seats=%s fidelity=%s lib=%s gw=%s）"
                % (",".join(bad), HB_SEATS, HB_FIDELITY, os.path.basename(HB_LIB),
                   GAME_WEIGHT_MODE))
        else:
            log("口径核对通过: seats=%s fidelity=%s lib=%s gw=%s"
                % (HB_SEATS, HB_FIDELITY, os.path.basename(HB_LIB), GAME_WEIGHT_MODE))
    except Exception as e:  # noqa: BLE001
        log("口径核对失败(忽略): %r" % (e,))


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
        # 心跳：每 5 分钟写一行，便于外部判断看门狗是否真的在跑
        # （用 `ps -eo cmd | grep "[w]atchdog_b07"` 才不会被自己的 grep 骗到）
        _hb = 0.0
        while True:
            try:
                main()
            except Exception as e:  # noqa: BLE001
                log("ERR %r" % (e,))
            if time.time() - _hb >= 300:
                _hb = time.time()
                log("heartbeat alive %s" % ("(trainer running)" if trainer_alive() else "(trainer down)"))
            time.sleep(60)
