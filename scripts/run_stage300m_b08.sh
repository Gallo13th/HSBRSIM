#!/bin/bash
# =============================================================================
# run_stage300m_b08.sh — B08「信用分配 + 视野」实验（astra 建议的 A + C）
#
# A（信用分配）：`--tier-spread 1` —— 未达标惩罚不再只落在回合第一条 decision，
#   而是**均分到该回合所有 learner decision**（`hsbg/az/train/tier_target.py`）。
#   目标曲线 7:4 / 9:5 / 12:6（真实 6k+ MMR 是 t8 到 5 本、t9 到 6 本，这里故意温和一档）。
# C（视野）：`--lam 0.995 → 0.999`（终局奖励对早期决策权重更大；KL 门禁不变）。
#
# 其余完全沿用 B07：5 席 p0.90 full 人盘、无长强加权、禁用加重护手、lr 3e-6 恢复。
#
# 用法：
#   bash scripts/run_stage300m_b08.sh
#   MINUTES=5 STOP=200000000 OUT=runs/az_stage300m_b08_pilot TAG=az_stage300m_b08_pilot \
#     bash scripts/run_stage300m_b08.sh        # pilot
# =============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH=rust/python:.

CK="${CK:-runs/az_stage300m_b07/model.pt}"
TS="${TS-}"
OUT="${OUT:-runs/az_stage300m_b08}"
SEED="${SEED:-28003}"
STOP="${STOP:-300000000}"
MINUTES="${MINUTES:-1500}"
PROCESSES="${PROCESSES:-32}"
THREADS="${THREADS:-2}"
MINIBATCH="${MINIBATCH:-1024}"
GRAD_ACCUM="${GRAD_ACCUM:-2}"
GAMES="${GAMES:-384}"
GPUS="${GPUS:-3,4,5,6}"
DEVICE="${DEVICE:-cuda:0}"
EVAL_DEVICE="${EVAL_DEVICE:-cuda:1}"
SNAPSHOT_EVERY="${SNAPSHOT_EVERY:-50}"
KEEP_SNAPSHOTS="${KEEP_SNAPSHOTS:-8}"
TAG="${TAG:-az_stage300m_b08}"

# 优化器 = B05/B06/B07 原样
LR="${LR:-3.0e-06}"
LR_MIN_RATIO="${LR_MIN_RATIO:-0.5}"
MAX_UPDATES="${MAX_UPDATES:-4300}"
EPOCHS="${EPOCHS:-1}"
CLIP="${CLIP:-0.2}"
TARGET_KL="${TARGET_KL:-0.02}"
ENTROPY_COEF="${ENTROPY_COEF:-0.001}"
MAX_GRAD_NORM="${MAX_GRAD_NORM:-1.0}"

# —— A：信用分配（spread）——
TIER_COEF="${TIER_COEF:-5}"
TIER_PENALTY="${TIER_PENALTY:-0.02}"
TIER_BONUS="${TIER_BONUS:-0.5}"
TIER_TABLE="${TIER_TABLE:-7:4,9:5,12:6}"
TIER_SPREAD="${TIER_SPREAD:-1}"

# —— C：GAE 视野 ——
LAM="${LAM:-0.999}"

# 场地 = B07（5 席 p0.90 full + 按回合曲线），禁用加重护手
HB_LIB="${HB_LIB:-data/real_library/library_real_quasi_full.jsonl}"
HB_FIDELITY="${HB_FIDELITY:-full}"
HB_SEATS="${HB_SEATS:-5}"
HB_RAMP="${HB_RAMP:-}"
HB_QUANTILE_RAMP="${HB_QUANTILE_RAMP:-}"
RAMP_MODE="${RAMP_MODE:-step}"
RAMP_START="${RAMP_START:-0}"
GAME_WEIGHT_MODE="${GAME_WEIGHT_MODE:-none}"
BAN_TRINKETS="${BAN_TRINKETS-BG36_MagicItem_414}"
export HSBRSIM_BAN_TRINKETS="$BAN_TRINKETS"

FROZEN_SEATS="${FROZEN_SEATS:-0}"
FROZEN_OPPONENT="${FROZEN_OPPONENT:-}"

[ -f "$CK" ] || { echo "[b08] ERROR: 起点不存在 $CK" >&2; exit 2; }
[[ -n "$TS" && ! -f "$TS" ]] && { echo "[b08] ERROR: TS 不存在 $TS" >&2; exit 2; }

export LAM TIER_COEF TIER_PENALTY TIER_BONUS TIER_TABLE TIER_SPREAD
export LR LR_MIN_RATIO MAX_UPDATES EPOCHS CLIP TARGET_KL ENTROPY_COEF MAX_GRAD_NORM

echo "[b08] CK=$CK OUT=$OUT SEED=$SEED stop=$STOP"
echo "[b08] A 信用分配: tier_coef=$TIER_COEF spread=$TIER_SPREAD table=$TIER_TABLE bonus=$TIER_BONUS"
echo "[b08] C 视野: lam=$LAM"
echo "[b08] 场地: $HB_SEATS 席 / $HB_FIDELITY / 库=$(basename "$HB_LIB")  禁用饰品=${HSBRSIM_BAN_TRINKETS:-无}"
echo "[b08] 加权: $GAME_WEIGHT_MODE"

CK="$CK" TS="$TS" OUT="$OUT" SEED="$SEED" STOP_DECISIONS="$STOP" \
MINUTES="$MINUTES" PROCESSES="$PROCESSES" THREADS="$THREADS" \
MINIBATCH="$MINIBATCH" GRAD_ACCUM="$GRAD_ACCUM" GAMES="$GAMES" \
GPUS="$GPUS" DEVICE="$DEVICE" EVAL_DEVICE="$EVAL_DEVICE" EVAL_GAMES=96 \
SNAPSHOT_EVERY="$SNAPSHOT_EVERY" KEEP_SNAPSHOTS="$KEEP_SNAPSHOTS" TAG="$TAG" \
LR="$LR" LR_MIN_RATIO="$LR_MIN_RATIO" MAX_UPDATES="$MAX_UPDATES" \
LAM="$LAM" TIER_COEF="$TIER_COEF" TIER_PENALTY="$TIER_PENALTY" \
TIER_BONUS="$TIER_BONUS" TIER_TABLE="$TIER_TABLE" TIER_SPREAD="$TIER_SPREAD" \
HB_RAMP="$HB_RAMP" HB_QUANTILE_RAMP="$HB_QUANTILE_RAMP" RAMP_MODE="$RAMP_MODE" \
RAMP_START="$RAMP_START" FROZEN_SEATS="$FROZEN_SEATS" FROZEN_OPPONENT="$FROZEN_OPPONENT" \
LEAF_WAIT_MS=0.0 \
FORCE="${FORCE:-1}" \
bash scripts/run_stage300m.sh
