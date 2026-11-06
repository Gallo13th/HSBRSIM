#!/bin/bash
# =============================================================================
# run_stage300m_b06.sh — B06「长强局加权」300M launcher
#
# 依据：docs/B06_DESIGN.md
#   B05@150M 在 bot 384 局上 rank 1.599 / win 52.6%（B03@150M 1.784 / 47.9%），
#   但「长且强」子集 win 只有 11.1%（B03 18.2%）、tier5@t15 32.2%（B03 37.6%）——
#   即 B05 用「节奏」换了「经济」，长局滚雪球反而退化。
#   B06 = **B05 配方逐字不变**，唯一新增 `--game-weight-mode adv`：
#   每局按 (对局长度, 对手最强盘面) 的均值归一权重缩放 advantage（α=β=0.5，
#   floor 0.5 / cap 2.0，复用 hsbg/eval/metrics.game_weights 的评测口径）。
#
# 起点：B05 300M 权重（`runs/az_stage300m_b05/model.pt`），fresh optimizer。
# =============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH=rust/python:.

CK="${CK:-runs/az_stage300m_b05/model.pt}"
TS="${TS-}"
OUT="${OUT:-runs/az_stage300m_b06}"
SEED="${SEED:-27803}"
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
TAG="${TAG:-az_stage300m_b06}"

# 优化器强度 = B05 原样
LR="${LR:-3.0e-06}"
LR_MIN_RATIO="${LR_MIN_RATIO:-0.5}"
MAX_UPDATES="${MAX_UPDATES:-4300}"
EPOCHS="${EPOCHS:-1}"
CLIP="${CLIP:-0.2}"
TARGET_KL="${TARGET_KL:-0.02}"
ENTROPY_COEF="${ENTROPY_COEF:-0.001}"
MAX_GRAD_NORM="${MAX_GRAD_NORM:-1.0}"

# —— B06 的唯一新增因子 ——
GAME_WEIGHT_MODE="${GAME_WEIGHT_MODE:-adv}"
GAME_WEIGHT_ALPHA="${GAME_WEIGHT_ALPHA:-0.5}"
GAME_WEIGHT_BETA="${GAME_WEIGHT_BETA:-0.5}"
GAME_WEIGHT_FLOOR="${GAME_WEIGHT_FLOOR:-0.5}"
GAME_WEIGHT_CAP="${GAME_WEIGHT_CAP:-2.0}"

# 对手/课程与 B05 一致（无冻结席）
FROZEN_SEATS="${FROZEN_SEATS:-0}"
FROZEN_OPPONENT="${FROZEN_OPPONENT:-}"
HB_RAMP="${HB_RAMP:-0:1:0.30, 15M:2:0.50, 40M:3:0.70, 80M:3:0.90}"
HB_QUANTILE_RAMP="${HB_QUANTILE_RAMP:-0:p50, 40M:p75, 150M:p90}"
RAMP_MODE="${RAMP_MODE:-step}"
RAMP_START="${RAMP_START:-0}"

[ -f "$CK" ] || { echo "[b06] ERROR: 起点不存在 $CK" >&2; exit 2; }

export LR LR_MIN_RATIO MAX_UPDATES EPOCHS CLIP TARGET_KL ENTROPY_COEF MAX_GRAD_NORM
export GAME_WEIGHT_MODE GAME_WEIGHT_ALPHA GAME_WEIGHT_BETA GAME_WEIGHT_FLOOR GAME_WEIGHT_CAP

echo "[b06] CK=$CK OUT=$OUT SEED=$SEED stop=$STOP"
echo "[b06] 优化器 = B05：lr=$LR mb=$MINIBATCH accum=$GRAD_ACCUM max_updates=$MAX_UPDATES"
echo "[b06] 唯一新增：GAME_WEIGHT_MODE=$GAME_WEIGHT_MODE alpha=$GAME_WEIGHT_ALPHA beta=$GAME_WEIGHT_BETA floor=$GAME_WEIGHT_FLOOR cap=$GAME_WEIGHT_CAP"

CK="$CK" TS="$TS" OUT="$OUT" SEED="$SEED" STOP_DECISIONS="$STOP" \
MINUTES="$MINUTES" PROCESSES="$PROCESSES" THREADS="$THREADS" \
MINIBATCH="$MINIBATCH" GRAD_ACCUM="$GRAD_ACCUM" GAMES="$GAMES" \
GPUS="$GPUS" DEVICE="$DEVICE" EVAL_DEVICE="$EVAL_DEVICE" EVAL_GAMES=96 \
SNAPSHOT_EVERY="$SNAPSHOT_EVERY" KEEP_SNAPSHOTS="$KEEP_SNAPSHOTS" TAG="$TAG" \
LR="$LR" LR_MIN_RATIO="$LR_MIN_RATIO" MAX_UPDATES="$MAX_UPDATES" \
HB_RAMP="$HB_RAMP" HB_QUANTILE_RAMP="$HB_QUANTILE_RAMP" RAMP_MODE="$RAMP_MODE" \
RAMP_START="$RAMP_START" FROZEN_SEATS="$FROZEN_SEATS" FROZEN_OPPONENT="$FROZEN_OPPONENT" \
LEAF_WAIT_MS=0.0 \
FORCE="${FORCE:-1}" \
bash scripts/run_stage300m.sh
