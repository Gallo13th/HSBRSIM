#!/bin/bash
# =============================================================================
# run_stage300m_b05.sh — B05「优化器强度」300M launcher（唯一因子：策略位移）
#
# 诊断（2026-11-06）：实测 B01→B03（300M 决策）权重相对位移只有 1.54%，
#   `approx_kl/iter` 0.0004–0.004，而 `target-kl` 上限是 0.02 —— 相当于闸门开得极小。
#   B04（2 席冻结克隆）在 150M 的 384 局是 2.003 / win 39.8%（B03@150M = 1.784 / 47.9%），
#   判为无效并停止。B05 只改「优化器强度」，其余配方与 B03 逐字一致。
#
# 位移预算：Δθ_rel ≈ 0.45 × lr_avg × steps/iter × iters
#   现状: 0.45 × 8.8e-7 × 9  × 4285 ≈ 1.5%（实测 1.54%）
#   B05 : 0.45 × 2.25e-6 × 33 × 4285 ≈ 14.3%（≈9.5×）
#   手段：lr 1.17e-6→3e-6；minibatch 2048→1024、grad-accum 4→2（步数 9→33，样本量不变）
#
# 纪律：target-kl 0.02 仍是安全阀（单 minibatch KL>0.03 直接跳过并结束该 epoch）；
#   若 pilot 出现 KL>0.015 连续 / clip>0.3 / entropy<0.70，回退保守档（lr 2e-6 + 16 步）。
# =============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH=rust/python:.

CK="${CK:-runs/az_stage300m_b03/model.pt}"   # B03 300M（human 面最好、bot 面无回归）
TS="${TS-}"                                  # fresh optimizer
OUT="${OUT:-runs/az_stage300m_b05}"
SEED="${SEED:-27703}"
STOP="${STOP:-300000000}"
MINUTES="${MINUTES:-1500}"
PROCESSES="${PROCESSES:-32}"
THREADS="${THREADS:-2}"
MINIBATCH="${MINIBATCH:-1024}"               # 2048 → 1024（步数 ×2）
GRAD_ACCUM="${GRAD_ACCUM:-2}"                # 4 → 2（步数 ×2；有效批 8192→2048）
GAMES="${GAMES:-384}"
GPUS="${GPUS:-3,4,5,6}"
DEVICE="${DEVICE:-cuda:0}"
EVAL_DEVICE="${EVAL_DEVICE:-cuda:1}"
SNAPSHOT_EVERY="${SNAPSHOT_EVERY:-100}"
KEEP_SNAPSHOTS="${KEEP_SNAPSHOTS:-8}"
TAG="${TAG:-az_stage300m_b05}"

# —— B05 的唯一因子：优化器强度 ——
LR="${LR:-3.0e-06}"                           # 1.17e-6 → 3e-6
LR_MIN_RATIO="${LR_MIN_RATIO:-0.5}"
MAX_UPDATES="${MAX_UPDATES:-4300}"            # lr 按 iter 退火，匹配 300M 的 ~4285 iter
EPOCHS="${EPOCHS:-1}"
CLIP="${CLIP:-0.2}"
TARGET_KL="${TARGET_KL:-0.02}"
ENTROPY_COEF="${ENTROPY_COEF:-0.001}"
MAX_GRAD_NORM="${MAX_GRAD_NORM:-1.0}"

# 对手/课程与 B03 完全一致（无冻结席）
FROZEN_SEATS="${FROZEN_SEATS:-0}"
FROZEN_OPPONENT="${FROZEN_OPPONENT:-}"
HB_RAMP="${HB_RAMP:-0:1:0.30, 15M:2:0.50, 40M:3:0.70, 80M:3:0.90}"
HB_QUANTILE_RAMP="${HB_QUANTILE_RAMP:-0:p50, 40M:p75, 150M:p90}"
RAMP_MODE="${RAMP_MODE:-step}"
RAMP_START="${RAMP_START:-0}"

export LR LR_MIN_RATIO MAX_UPDATES EPOCHS CLIP TARGET_KL ENTROPY_COEF MAX_GRAD_NORM
echo "[b05] CK=$CK OUT=$OUT SEED=$SEED stop=$STOP"
echo "[b05] 唯一因子: lr=$LR(min $LR_MIN_RATIO) minibatch=$MINIBATCH accum=$GRAD_ACCUM epochs=$EPOCHS max_updates=$MAX_UPDATES"
echo "[b05] 期望位移 ≈ 14%（B03 实测 1.5%）；对手/课程 = B03（FROZEN_SEATS=$FROZEN_SEATS）"

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
