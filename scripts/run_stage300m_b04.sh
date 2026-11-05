#!/bin/bash
# =============================================================================
# run_stage300m_b04.sh — B04「冻结对手席（联赛/自对弈）」300M launcher
#
# 设计：docs/B04_DESIGN.md §2（B04-C）
#   唯一变量：FROZEN_SEATS=2 个 bot 席由冻结 checkpoint 驱动（其余 5 席仍是引擎 bot，
#   3 席 human-board 注入照旧）。冻结对手 = B03 300M 权重（起跑时与 learner 同代），
#   随训练推进逐渐被超越 —— 这是「联赛阶梯」的廉价版；8 席全自对弈（--opponent self）
#   吞吐 ~25x 慢，300M 不可行。
#   其余配方（lr / 课程 / 奖励 / 评测）与 B03 完全一致，保证单变量。
#
# 用法：
#   bash scripts/run_stage300m_b04.sh                 # 正式跑（默认 300M）
#   MINUTES=8 STOP=200000000 OUT=runs/az_stage300m_b04_pilot bash scripts/run_stage300m_b04.sh   # 吞吐 pilot
# =============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH=rust/python:.

CK="${CK:-runs/az_stage300m_b03/model.pt}"      # B03 300M 权重（human 面最好、bot 面无回归）
TS="${TS-}"                                     # 默认 fresh optimizer（B02/B03 的教训）
OUT="${OUT:-runs/az_stage300m_b04}"
SEED="${SEED:-27603}"
STOP="${STOP:-300000000}"
MINUTES="${MINUTES:-1500}"
PROCESSES="${PROCESSES:-32}"
THREADS="${THREADS:-2}"
MINIBATCH="${MINIBATCH:-2048}"
GRAD_ACCUM="${GRAD_ACCUM:-4}"
GAMES="${GAMES:-384}"
GPUS="${GPUS:-3,4,5}"
DEVICE="${DEVICE:-cuda:0}"
EVAL_DEVICE="${EVAL_DEVICE:-cuda:1}"
SNAPSHOT_EVERY="${SNAPSHOT_EVERY:-100}"
KEEP_SNAPSHOTS="${KEEP_SNAPSHOTS:-8}"
TAG="${TAG:-az_stage300m_b04}"

# —— B04 的唯一变量 ——
FROZEN_SEATS="${FROZEN_SEATS:-2}"
FROZEN_OPPONENT="${FROZEN_OPPONENT:-runs/az_stage300m_b03/model.pt}"

# lr 排程与 B03 相同（预算比例照搬：每 10M ≈ 150 updates）
LR="${LR:-1.17e-06}"
LR_MIN_RATIO="${LR_MIN_RATIO:-0.5}"
MAX_UPDATES="${MAX_UPDATES:-4500}"

# 课程与 B03 完全一致（step 档位；resume 后按本 run 累计 decisions 计）
HB_RAMP="${HB_RAMP:-0:1:0.30, 15M:2:0.50, 40M:3:0.70, 80M:3:0.90}"
HB_QUANTILE_RAMP="${HB_QUANTILE_RAMP:-0:p50, 40M:p75, 150M:p90}"
RAMP_MODE="${RAMP_MODE:-step}"
RAMP_START="${RAMP_START:-0}"

[ -f "$FROZEN_OPPONENT" ] || { echo "[b04] ERROR: 缺冻结对手 $FROZEN_OPPONENT" >&2; exit 2; }

echo "[b04] CK=$CK TS='${TS:-<fresh>}' OUT=$OUT SEED=$SEED stop=$STOP minutes=$MINUTES"
echo "[b04] 唯一变量: FROZEN_SEATS=$FROZEN_SEATS FROZEN_OPPONENT=$FROZEN_OPPONENT"

CK="$CK" TS="$TS" OUT="$OUT" SEED="$SEED" STOP_DECISIONS="$STOP" \
MINUTES="$MINUTES" PROCESSES="$PROCESSES" THREADS="$THREADS" \
MINIBATCH="$MINIBATCH" GRAD_ACCUM="$GRAD_ACCUM" GAMES="$GAMES" \
GPUS="$GPUS" DEVICE="$DEVICE" EVAL_DEVICE="$EVAL_DEVICE" EVAL_GAMES=96 \
SNAPSHOT_EVERY="$SNAPSHOT_EVERY" KEEP_SNAPSHOTS="$KEEP_SNAPSHOTS" TAG="$TAG" \
LR="$LR" LR_MIN_RATIO="$LR_MIN_RATIO" MAX_UPDATES="$MAX_UPDATES" \
HB_RAMP="$HB_RAMP" HB_QUANTILE_RAMP="$HB_QUANTILE_RAMP" RAMP_MODE="$RAMP_MODE" \
RAMP_START="$RAMP_START" \
FROZEN_SEATS="$FROZEN_SEATS" FROZEN_OPPONENT="$FROZEN_OPPONENT" \
FORCE="${FORCE:-1}" \
bash scripts/run_stage300m.sh
