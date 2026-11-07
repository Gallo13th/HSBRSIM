#!/bin/bash
# =============================================================================
# run_stage300m_b08.sh — B08「强制升本」单变量实验
#
# 规则（docs/B08_DESIGN.md §A'）：本回合任一决策点，若
#   gold > upgrade_price + 商店里当下最便宜的商品
# 且升级合法，则**只允许升级**（mask 其余位清零）。用真实对局数据直接回答
# "高本到底值不值"，绕开 PPO 在 13+ 回合延迟收益上的探索/信用分配难题。
#
# 其余完全沿用 B07：5 席 p0.90 full 人盘、无长强加权、禁用加重护手、lr 3e-6、λ=0.995。
# 不开 tier-target（A）、不改 λ（C）——单变量优先，避免多臂并行拖慢出结果。
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

# —— 唯一变量：强制升本 ——
FORCED_UPGRADE="${FORCED_UPGRADE:-1}"
FORCED_UPGRADE_MARGIN="${FORCED_UPGRADE_MARGIN:-0}"
export HSBRSIM_FORCE_UPGRADE="$FORCED_UPGRADE"

# A / C 关闭（单变量）
TIER_COEF="${TIER_COEF:-0}"
TIER_PENALTY="${TIER_PENALTY:-0.02}"
TIER_BONUS="${TIER_BONUS:-0.0}"
TIER_TABLE="${TIER_TABLE:-7:4,9:5,12:6}"
TIER_SPREAD="${TIER_SPREAD:-0}"
LAM="${LAM:-0.995}"

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
export HB_LIB HB_FIDELITY HB_SEATS
export FORCED_UPGRADE FORCED_UPGRADE_MARGIN

echo "[b08] CK=$CK OUT=$OUT SEED=$SEED stop=$STOP"
echo "[b08] 强制升本: forced_upgrade=$FORCED_UPGRADE margin=$FORCED_UPGRADE_MARGIN"
echo "[b08] A/C 关闭: tier_coef=$TIER_COEF spread=$TIER_SPREAD lam=$LAM"
echo "[b08] 场地: $HB_SEATS 席 / $HB_FIDELITY / 库=$(basename "$HB_LIB")  禁用饰品=${HSBRSIM_BAN_TRINKETS:-无}"
echo "[b08] 加权: $GAME_WEIGHT_MODE"

CK="$CK" TS="$TS" OUT="$OUT" SEED="$SEED" STOP_DECISIONS="$STOP" \
MINUTES="$MINUTES" PROCESSES="$PROCESSES" THREADS="$THREADS" \
MINIBATCH="$MINIBATCH" GRAD_ACCUM="$GRAD_ACCUM" GAMES="$GAMES" \
GPUS="$GPUS" DEVICE="$DEVICE" EVAL_DEVICE="$EVAL_DEVICE" EVAL_GAMES=96 \
SNAPSHOT_EVERY="$SNAPSHOT_EVERY" KEEP_SNAPSHOTS="$KEEP_SNAPSHOTS" TAG="$TAG" \
LR="$LR" LR_MIN_RATIO="$LR_MIN_RATIO" MAX_UPDATES="$MAX_UPDATES" \
FORCED_UPGRADE="$FORCED_UPGRADE" FORCED_UPGRADE_MARGIN="$FORCED_UPGRADE_MARGIN" \
LAM="$LAM" TIER_COEF="$TIER_COEF" TIER_PENALTY="$TIER_PENALTY" \
TIER_BONUS="$TIER_BONUS" TIER_TABLE="$TIER_TABLE" TIER_SPREAD="$TIER_SPREAD" \
HB_RAMP="$HB_RAMP" HB_QUANTILE_RAMP="$HB_QUANTILE_RAMP" RAMP_MODE="$RAMP_MODE" \
RAMP_START="$RAMP_START" FROZEN_SEATS="$FROZEN_SEATS" FROZEN_OPPONENT="$FROZEN_OPPONENT" \
LEAF_WAIT_MS=0.0 \
FORCE="${FORCE:-1}" \
bash scripts/run_stage300m.sh
