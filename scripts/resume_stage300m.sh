#!/bin/bash
# =============================================================================
# resume_stage300m.sh — 从 Stage-300M 的最近 snapshot 继续（进程崩溃/被中断后）
#
# 逻辑：
#   1) 读 runs/<OUT>/history.jsonl 的累计 decisions（= 已完成预算）；
#   2) 取 runs/<OUT>/snapshots/step_* 里最新的同时含 model.pt + trainer.pt 的目录；
#   3) STOP_DECISIONS = 目标 - 已完成；以该 snapshot 精确续训（optimizer/updates/LR/RNG）；
#   4) FORCE=1 复用非空 OUT（history 继续追加；header 不会重复写）。
#
# 用法：bash scripts/resume_stage300m.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

OUT="${OUT:-runs/az_stage300m_b01}"
TARGET="${STOP_DECISIONS:-300000000}"
PY="${PYTHON:-/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python}"

[ -d "$OUT" ] || { echo "[resume] missing OUT: $OUT" >&2; exit 2; }

DONE=$("$PY" - "$OUT/history.jsonl" <<'PY'
import json, sys, os
p = sys.argv[1]
tot = 0
if os.path.isfile(p):
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if isinstance(r, dict) and r.get("type") != "header":
            tot += int((r.get("collect") or {}).get("decisions") or 0)
print(tot)
PY
)
echo "[resume] completed decisions=${DONE} target=${TARGET}"

if [ "$DONE" -ge "$TARGET" ]; then
  echo "[resume] target already reached; nothing to do"
  exit 0
fi

SNAP=$(ls -d "$OUT"/snapshots/step_* 2>/dev/null | sort | tail -n 1 || true)
if [ -z "$SNAP" ] || [ ! -f "$SNAP/model.pt" ] || [ ! -f "$SNAP/trainer.pt" ]; then
  echo "[resume] no snapshot with model.pt+trainer.pt under $OUT/snapshots; abort" >&2
  exit 2
fi
echo "[resume] latest snapshot: $SNAP"

REMAIN=$((TARGET - DONE))
MINUTES=$(( REMAIN / 8000 / 60 + 90 ))   # 按 8k dec/s 保守估计 + 90min 余量
echo "[resume] remaining=${REMAIN} minutes_guard=${MINUTES}"

CK="$SNAP/model.pt" TS="$SNAP/trainer.pt" OUT="$OUT" FORCE=1 \
STOP_DECISIONS="$REMAIN" MINUTES="$MINUTES" TAG="${TAG:-az_stage300m_b01}" \
bash scripts/run_stage300m.sh
