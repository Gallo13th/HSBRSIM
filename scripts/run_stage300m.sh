#!/bin/bash
# =============================================================================
# run_stage300m.sh — Phase-2 Stage-300M launcher（单进程、连续 300M decisions）
#
# 起点：runs/az_entity_s73/model.pt + trainer.pt（精确续训: optimizer/updates/LR/RNG）
# 配方：clean recipe（与 B01/s73 相同的 233 flags；不含 comp_fit/shaping/辅助头）
# 预算：STOP_DECISIONS=300,000,000（= 300M stage），MINUTES 仅作兜底
# 评测：训练内 dev 面板每 10M（seed 420000）；canonical 96 局由 stage_monitor.py 每 10M 补
#
# 用法（推荐 nohup 常驻）：
#   nohup bash scripts/run_stage300m.sh > /tmp/stage300m_launch.out 2>&1 &
#   tail -f runs/az_stage300m_b01/train.log
#
# 断点重跑：见 scripts/resume_stage300m.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"

CK="${CK:-runs/az_entity_s73/model.pt}"
TS="${TS-runs/az_entity_s73/trainer.pt}"
OUT="${OUT:-runs/az_stage300m_b01}"
SEED="${SEED:-27501}"
STOP_DECISIONS="${STOP_DECISIONS:-300000000}"
MINUTES="${MINUTES:-1500}"
PROCESSES="${PROCESSES:-32}"
THREADS="${THREADS:-2}"
MINIBATCH="${MINIBATCH:-2048}"
GRAD_ACCUM="${GRAD_ACCUM:-4}"
GAMES="${GAMES:-384}"
GPUS="${GPUS:-3,4,5}"
DEVICE="${DEVICE:-cuda:0}"
EVAL_DEVICE="${EVAL_DEVICE:-cuda:1}"
EVAL_GAMES="${EVAL_GAMES:-96}"
EVAL_FIRST_DECISIONS="${EVAL_FIRST_DECISIONS:-0}"
SNAPSHOT_EVERY="${SNAPSHOT_EVERY:-100}"
KEEP_SNAPSHOTS="${KEEP_SNAPSHOTS:-8}"
TAG="${TAG:-az_stage300m_b01}"
FORCE="${FORCE:-0}"

META="$OUT/meta.txt"
LOG="$OUT/train.log"

die() { echo "[stage300m] ERROR: $*" >&2; exit 2; }

[ -f "$CK" ] || die "missing checkpoint: $CK"
if [ -n "$TS" ]; then
  [ -f "$TS" ] || die "missing trainer state: $TS（新 stage 可给 TS="" 走 fresh optimizer）"
fi
[ -f data/real_library/winner_library.jsonl ] || die "missing winner_library.jsonl"
if pgrep -u "$(id -un)" -f 'train_entity_sync[.]py' >/dev/null 2>&1; then
  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "[stage300m][warn] 已有 trainer 在跑，但 DRY_RUN=1 只打印命令" >&2
  else
    die "another train_entity_sync.py is already running"
  fi
fi
if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null || true)" ] && [ "$FORCE" != "1" ]; then
  die "OUT 非空: $OUT（断点重跑请用 scripts/resume_stage300m.sh 或 FORCE=1）"
fi

# 资源预检（只警告，不阻断；GPU 由用户/环境保证）
FREE() { nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits 2>/dev/null | \
  awk -v g="$1" -F', *' '$1==g {print $2}'; }
for g in ${GPUS//,/ }; do
  f=$(FREE "$g" || echo 0)
  [ "${f:-0}" -ge 1500 ] || echo "[stage300m][warn] GPU$g free=${f}MiB (<1500)" >&2
done
lf=$(FREE "${DEVICE#cuda:}" || echo 0)
[ "${lf:-0}" -ge 16000 ] || echo "[stage300m][warn] learner ${DEVICE} free=${lf}MiB (<16000)" >&2

mkdir -p "$OUT"
echo "[stage300m] start $(date -Is) out=$OUT seed=$SEED stop=$STOP_DECISIONS procs=$PROCESSES threads=$THREADS minibatch=$MINIBATCH accum=$GRAD_ACCUM" | tee -a "$LOG"

# 委托给唯一入口；本脚本只负责 Stage 配置与记录。
CK="$CK" TS="$TS" OUT="$OUT" SEED="$SEED" STOP_DECISIONS="$STOP_DECISIONS" \
MINUTES="$MINUTES" PROCESSES="$PROCESSES" THREADS="$THREADS" \
MINIBATCH="$MINIBATCH" GRAD_ACCUM="$GRAD_ACCUM" GAMES="$GAMES" \
GPUS="$GPUS" DEVICE="$DEVICE" EVAL_DEVICE="$EVAL_DEVICE" EVAL_GAMES="$EVAL_GAMES" \
EVAL_FIRST_DECISIONS="$EVAL_FIRST_DECISIONS" \
SNAPSHOT_EVERY="$SNAPSHOT_EVERY" KEEP_SNAPSHOTS="$KEEP_SNAPSHOTS" TAG="$TAG" \
LR="${LR:-1.17e-06}" LR_MIN_RATIO="${LR_MIN_RATIO:-0.5}" MAX_UPDATES="${MAX_UPDATES:-3000}" \
HB_RAMP="${HB_RAMP:-}" HB_QUANTILE_RAMP="${HB_QUANTILE_RAMP:-}" RAMP_MODE="${RAMP_MODE:-step}" \
RAMP_START="${RAMP_START:-0}" \
FROZEN_SEATS="${FROZEN_SEATS:-0}" FROZEN_OPPONENT="${FROZEN_OPPONENT:-}" \
LEAF_WAIT_MS="${LEAF_WAIT_MS:-0.0}" \
DRY_RUN="${DRY_RUN:-0}" \
EPOCHS="${EPOCHS:-1}" CLIP="${CLIP:-0.2}" TARGET_KL="${TARGET_KL:-0.02}" \
GAME_WEIGHT_MODE="${GAME_WEIGHT_MODE:-none}" GAME_WEIGHT_ALPHA="${GAME_WEIGHT_ALPHA:-0.5}" GAME_WEIGHT_BETA="${GAME_WEIGHT_BETA:-0.5}" \
GAME_WEIGHT_FLOOR="${GAME_WEIGHT_FLOOR:-0.5}" GAME_WEIGHT_CAP="${GAME_WEIGHT_CAP:-2.0}" \
HB_LIB="${HB_LIB:-data/real_library/winner_library.jsonl}" HB_FIDELITY="${HB_FIDELITY:-board}" HB_SEATS="${HB_SEATS:-3}" \
ENTROPY_COEF="${ENTROPY_COEF:-0.001}" MAX_GRAD_NORM="${MAX_GRAD_NORM:-1.0}" \
FORCE=1 \
bash scripts/train_block_clean.sh >> "$LOG" 2>&1

echo "[stage300m] trainer exited $(date -Is) log=$LOG" | tee -a "$LOG"
