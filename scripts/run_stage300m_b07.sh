#!/bin/bash
# =============================================================================
# run_stage300m_b07.sh — B07「训练/评测分布对齐」300M launcher
#
# 依据：docs/B07_DESIGN.md（候选 A）
#   优化器与 B05/B06 完全一致（lr 3e-6 恢复、mb 1024/accum 2、max_updates 4300）；
#   唯一新增：人类盘面注入从「3 席 p0.90 board-only」对齐到「5 席 p0.90 full 保真」，
#   即与 canonical 评测 `scripts/eval_panel.sh`（5 席 / p0.90 / full / p75）同构，
#   但保留课程末端 p90 分位（训练比评测更硬一点）。
#
# 起点默认 B06 300M 权重（`runs/az_stage300m_b06/model.pt`）。
# 依赖：准完整库 data/real_library/library_real_quasi_full.jsonl（full 档必需）。
#
# 用法：
#   bash scripts/run_stage300m_b07.sh
#   MINUTES=5 STOP=200000000 OUT=runs/az_stage300m_b07_pilot TAG=az_stage300m_b07_pilot \
#     bash scripts/run_stage300m_b07.sh          # pilot（验证 full 注入的吞吐与稳定性）
# =============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH=rust/python:.

CK="${CK:-runs/az_stage300m_b06/model.pt}"
TS="${TS-}"
OUT="${OUT:-runs/az_stage300m_b07}"
SEED="${SEED:-27903}"
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
TAG="${TAG:-az_stage300m_b07}"

# 优化器 = B05/B06 原样（"恢复 lr"）
LR="${LR:-3.0e-06}"
LR_MIN_RATIO="${LR_MIN_RATIO:-0.5}"
MAX_UPDATES="${MAX_UPDATES:-4300}"
EPOCHS="${EPOCHS:-1}"
CLIP="${CLIP:-0.2}"
TARGET_KL="${TARGET_KL:-0.02}"
ENTROPY_COEF="${ENTROPY_COEF:-0.001}"
MAX_GRAD_NORM="${MAX_GRAD_NORM:-1.0}"

# —— B07 的唯一新增因子：注入分布对齐 ——
HB_LIB="${HB_LIB:-data/real_library/library_real_quasi_full.jsonl}"
HB_FIDELITY="${HB_FIDELITY:-full}"
HB_SEATS="${HB_SEATS:-5}"
# 课程：**不启用 seats/quantile ramp**（B05/B06 的教训见 docs/B07_DESIGN.md §2）——
# 用 --human-board-sample auto 自带的"按回合难度曲线"（turn≤8 p50 / 9–12 p75 / ≥13 p90），
# 只把"席数 3→5"和"保真度 board→full"作为唯一新增变量。
HB_RAMP="${HB_RAMP:-}"
HB_QUANTILE_RAMP="${HB_QUANTILE_RAMP:-}"
RAMP_MODE="${RAMP_MODE:-step}"
RAMP_START="${RAMP_START:-0}"

# 长强加权：**默认关闭**（B06 三点证据：长强 25.0%→15.6%→12.5%、经济 tier5 28.0%→21.3%→19.3%；见 docs/B07_DESIGN.md §2b）
GAME_WEIGHT_MODE="${GAME_WEIGHT_MODE:-none}"
GAME_WEIGHT_ALPHA="${GAME_WEIGHT_ALPHA:-0.5}"
GAME_WEIGHT_BETA="${GAME_WEIGHT_BETA:-0.5}"
GAME_WEIGHT_FLOOR="${GAME_WEIGHT_FLOOR:-0.5}"
GAME_WEIGHT_CAP="${GAME_WEIGHT_CAP:-2.0}"

FROZEN_SEATS="${FROZEN_SEATS:-0}"
FROZEN_OPPONENT="${FROZEN_OPPONENT:-}"

[ -f "$CK" ] || { echo "[b07] ERROR: 起点不存在 $CK" >&2; exit 2; }
[ -f "$HB_LIB" ] || { echo "[b07] ERROR: 人盘库不存在 $HB_LIB" >&2; exit 2; }

export LR LR_MIN_RATIO MAX_UPDATES EPOCHS CLIP TARGET_KL ENTROPY_COEF MAX_GRAD_NORM
export GAME_WEIGHT_MODE GAME_WEIGHT_ALPHA GAME_WEIGHT_BETA GAME_WEIGHT_FLOOR GAME_WEIGHT_CAP
export HB_LIB HB_FIDELITY HB_SEATS

echo "[b07] CK=$CK OUT=$OUT SEED=$SEED stop=$STOP"
echo "[b07] 优化器 = B05/B06：lr=$LR mb=$MINIBATCH accum=$GRAD_ACCUM max_updates=$MAX_UPDATES"
echo "[b07] 唯一新增：人盘 5 席 + full 保真（库=$(basename "$HB_LIB")），sample=auto（按回合曲线），ramp='$HB_RAMP'/'$HB_QUANTILE_RAMP'"
echo "[b07] 长强加权：$GAME_WEIGHT_MODE (alpha=$GAME_WEIGHT_ALPHA beta=$GAME_WEIGHT_BETA cap=$GAME_WEIGHT_CAP)"

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
