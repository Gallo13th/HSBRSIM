#!/bin/bash
# =============================================================================
# run_stage300m_b09.sh — B09「强制升本 + 人类复利 BC」
#
# 依据：B08 已验证「强制升本」把 tier≥5@t15 从 7.7% 拉到 100%，且不牺牲对 bot 胜率；
# 但 6 本盘面的**放大器卡位占比 = 0%**（人类 6 本盘面是 7.0%），即"复利骨架"没学出来。
# 人类 6k+ MMR 数据里已经有这个知识（data/firestone_bc/bc_samples.jsonl.gz），
# 架构里也有卡牌级 BC 头（bc_card_head），所以本轮唯一新增 = **打开人类 BC 辅助监督**。
#
# 保持不变：强制升本（user 明确要求继续）、5 席 p0.90 full 人盘、禁用加重护手、
# 无长强加权、无 tier-target（A 已弃用）、λ=0.995。
#
# 用法：
#   bash scripts/run_stage300m_b09.sh
#   MINUTES=5 STOP=200000000 OUT=runs/az_stage300m_b09_pilot TAG=az_stage300m_b09_pilot \
#     bash scripts/run_stage300m_b09.sh        # pilot（验证 BC loss 真的在跑）
# =============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH=rust/python:.

CK="${CK:-runs/az_stage300m_b09_base.pt}"   # 由启动脚本指向 B08 的终评权重
TS="${TS-}"
OUT="${OUT:-runs/az_stage300m_b09}"
SEED="${SEED:-28103}"
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
TAG="${TAG:-az_stage300m_b09}"

LR="${LR:-3.0e-06}"
LR_MIN_RATIO="${LR_MIN_RATIO:-0.5}"
MAX_UPDATES="${MAX_UPDATES:-4300}"
EPOCHS="${EPOCHS:-1}"
CLIP="${CLIP:-0.2}"
TARGET_KL="${TARGET_KL:-0.02}"
ENTROPY_COEF="${ENTROPY_COEF:-0.001}"
MAX_GRAD_NORM="${MAX_GRAD_NORM:-1.0}"
LAM="${LAM:-0.995}"

# —— 保留：强制升本（B08 的骨架）——
FORCED_UPGRADE="${FORCED_UPGRADE:-1}"
FORCED_UPGRADE_MARGIN="${FORCED_UPGRADE_MARGIN:-0}"
export HSBRSIM_FORCE_UPGRADE="$FORCED_UPGRADE"

# —— 新增：人类 BC（复利行为）——
BC_COEF="${BC_COEF:-0.05}"
BC_MMR_MIN="${BC_MMR_MIN:-6000}"
BC_MMR_BOOST="${BC_MMR_BOOST:-1.0}"
BC_TYPE_WEIGHT="${BC_TYPE_WEIGHT:-1.0}"
BC_CARD_WEIGHT="${BC_CARD_WEIGHT:-1.0}"
BC_CLASS_WEIGHT="${BC_CLASS_WEIGHT:-buy_minion=1.5,refresh=2.0}"
BC_BATCH="${BC_BATCH:-128}"
BC_EVERY="${BC_EVERY:-1}"
BC_SAMPLES="${BC_SAMPLES:-data/firestone_bc/bc_samples.jsonl.gz}"

# 场地 = B07/B08（5 席 p0.90 full + 按回合曲线）
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

# A（tier-target）保持关闭
TIER_COEF="${TIER_COEF:-0}"
TIER_SPREAD="${TIER_SPREAD:-0}"

FROZEN_SEATS="${FROZEN_SEATS:-0}"
FROZEN_OPPONENT="${FROZEN_OPPONENT:-}"

[ -f "$CK" ] || { echo "[b09] ERROR: 起点不存在 $CK（用 CK=... 指定 B08 权重）" >&2; exit 2; }
[ -f "$BC_SAMPLES" ] || { echo "[b09] ERROR: BC 数据不存在 $BC_SAMPLES" >&2; exit 2; }

export LAM LR LR_MIN_RATIO MAX_UPDATES EPOCHS CLIP TARGET_KL ENTROPY_COEF MAX_GRAD_NORM
export HB_LIB HB_FIDELITY HB_SEATS
export FORCED_UPGRADE FORCED_UPGRADE_MARGIN
export TIER_COEF TIER_SPREAD

echo "[b09] CK=$CK OUT=$OUT SEED=$SEED stop=$STOP"
echo "[b09] 保留：强制升本 forced_upgrade=$FORCED_UPGRADE margin=$FORCED_UPGRADE_MARGIN"
echo "[b09] 新增：人类 BC coef=$BC_COEF mmr_min=$BC_MMR_MIN card_w=$BC_CARD_WEIGHT type_w=$BC_TYPE_WEIGHT class=$BC_CLASS_WEIGHT every=$BC_EVERY"
echo "[b09] 场地：$HB_SEATS 席 / $HB_FIDELITY / 禁用饰品=${HSBRSIM_BAN_TRINKETS:-无}  加权=$GAME_WEIGHT_MODE  λ=$LAM"

CK="$CK" TS="$TS" OUT="$OUT" SEED="$SEED" STOP_DECISIONS="$STOP" \
MINUTES="$MINUTES" PROCESSES="$PROCESSES" THREADS="$THREADS" \
MINIBATCH="$MINIBATCH" GRAD_ACCUM="$GRAD_ACCUM" GAMES="$GAMES" \
GPUS="$GPUS" DEVICE="$DEVICE" EVAL_DEVICE="$EVAL_DEVICE" EVAL_GAMES=96 \
SNAPSHOT_EVERY="$SNAPSHOT_EVERY" KEEP_SNAPSHOTS="$KEEP_SNAPSHOTS" TAG="$TAG" \
LR="$LR" LR_MIN_RATIO="$LR_MIN_RATIO" MAX_UPDATES="$MAX_UPDATES" \
LAM="$LAM" TIER_COEF="$TIER_COEF" TIER_SPREAD="$TIER_SPREAD" \
FORCED_UPGRADE="$FORCED_UPGRADE" FORCED_UPGRADE_MARGIN="$FORCED_UPGRADE_MARGIN" \
BC_COEF="$BC_COEF" BC_MMR_MIN="$BC_MMR_MIN" BC_MMR_BOOST="$BC_MMR_BOOST" \
BC_TYPE_WEIGHT="$BC_TYPE_WEIGHT" BC_CARD_WEIGHT="$BC_CARD_WEIGHT" \
BC_CLASS_WEIGHT="$BC_CLASS_WEIGHT" BC_BATCH="$BC_BATCH" BC_EVERY="$BC_EVERY" \
BC_SAMPLES="$BC_SAMPLES" \
HB_RAMP="$HB_RAMP" HB_QUANTILE_RAMP="$HB_QUANTILE_RAMP" RAMP_MODE="$RAMP_MODE" \
RAMP_START="$RAMP_START" FROZEN_SEATS="$FROZEN_SEATS" FROZEN_OPPONENT="$FROZEN_OPPONENT" \
LEAF_WAIT_MS=0.0 \
FORCE="${FORCE:-1}" \
bash scripts/run_stage300m.sh
