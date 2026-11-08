#!/usr/bin/env bash
# =============================================================================
# train_block_clean.sh — 单进程「干净续训块」（HSBRSIM / entity PPO）
#
# 基线：runs/next_block.sh（逐字保留全部开关），只做 Lead 指定的改动：
#   --checkpoint + --trainer-state（精确续训：恢复 optimizer/updates/LR/RNG）
#   --out runs/az_entity_s73 / --seed 27301 / --eval-device cuda:1
#   --eval-drain 1 / --gpu-free-check 1
# 结束自动跑唯一评测口径：bash scripts/eval_panel.sh $OUT/model.pt ${TAG}_panel 96
#
# 用法：
#   bash scripts/train_block_clean.sh --dry-run     # 只打印最终命令（不创建目录/不训练）
#   bash scripts/train_block_clean.sh               # 真跑
#   DRY_RUN=1 bash scripts/train_block_clean.sh     # 等价
#
# 环境变量（默认值 = 今晚正式配置）：
#   CK               runs/az_entity_s61/eval/ckpt_020026719.pt  模型权重
#   TS               runs/az_entity_s61/trainer.pt              trainer 状态（必须同时给）
#   OUT              runs/az_entity_s73                         输出目录
#   SEED             27301                                      seed
#   STOP_DECISIONS   20000000                                   本块 decisions 上限
#   GAMES            384                                        每 iteration 采集局数
#   PROCESSES        24                                         actor 进程数
#   GPUS             3,4,5                                      actor 物理 GPU
#   DEVICE           cuda:6                                     learner
#   EVAL_DEVICE      cuda:1                                     in-training 评测 + eval_panel
#   COMP_FIT_COEF    0
#   COMP_FIT_T9_BONUS 0
#   COMP_TRINKET_COEF 0
#   DRY_RUN          0                                          1=只打印命令
# 其它：TAG（默认 OUT 的 basename）、EVAL_GAMES（96）、FORCE（0=拒绝复用非空 OUT）、
#       ALLOW_RUNNING（0=检测到 trainer 在跑就拒绝，防并行）。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python}"

CK="${CK:-runs/az_entity_s61/eval/ckpt_020026719.pt}"
# 注意：用 `-` 而不是 `:-` —— 显式传 TS="" 表示 **不加载 trainer state**（fresh optimizer）；
# 只有调用方完全没设 TS 时才回落到 s61（历史默认）。B05 起必须能真正 fresh。
TS="${TS-runs/az_entity_s61/trainer.pt}"
OUT="${OUT:-runs/az_entity_s73}"
SEED="${SEED:-27301}"
STOP_DECISIONS="${STOP_DECISIONS:-20000000}"
GAMES="${GAMES:-384}"
MINUTES="${MINUTES:-400}"
EVAL_FIRST_DECISIONS="${EVAL_FIRST_DECISIONS:-0}"
SNAPSHOT_EVERY="${SNAPSHOT_EVERY:-100}"
KEEP_SNAPSHOTS="${KEEP_SNAPSHOTS:-4}"
PROCESSES="${PROCESSES:-24}"
THREADS="${THREADS:-3}"
MINIBATCH="${MINIBATCH:-1024}"
GRAD_ACCUM="${GRAD_ACCUM:-8}"
GPUS="${GPUS:-3,4,5}"
DEVICE="${DEVICE:-cuda:6}"
EVAL_DEVICE="${EVAL_DEVICE:-cuda:1}"
COMP_FIT_COEF="${COMP_FIT_COEF:-0}"
COMP_FIT_T9_BONUS="${COMP_FIT_T9_BONUS:-0}"
COMP_TRINKET_COEF="${COMP_TRINKET_COEF:-0}"
# 0 = 不按「已用显存 > 阈值」剔除 actor 卡（默认；邻居只占 5GB 时仍可用）
GPU_FREE_CHECK="${GPU_FREE_CHECK:-0}"
# leaf 批等待（ms）：0=不等待（默认，旧行为逐位等价）；>0 让并发 worker 的叶子评估攒批，
# 提高 GPU batch_fill（吞吐优化，不影响算法）。见 docs/THROUGHPUT_300M.md
LEAF_WAIT_MS="${LEAF_WAIT_MS:-0.0}"
# 优化器强度（B05 起可调；默认值 = 旧硬编码，未设时命令行逐字不变）
LR="${LR:-1.17e-06}"
LR_MIN_RATIO="${LR_MIN_RATIO:-0.5}"
MAX_UPDATES="${MAX_UPDATES:-3000}"
EPOCHS="${EPOCHS:-1}"
CLIP="${CLIP:-0.2}"
LAM="${LAM:-0.995}"
TIER_COEF="${TIER_COEF:-0.0}"
TIER_PENALTY="${TIER_PENALTY:-0.02}"
TIER_BONUS="${TIER_BONUS:-0.0}"
TIER_TABLE="${TIER_TABLE:-7:4,9:5,12:6}"
TIER_SPREAD="${TIER_SPREAD:-0}"
FORCED_UPGRADE="${FORCED_UPGRADE:-0}"
CEILING_AUX_COEF="${CEILING_AUX_COEF:-0}"
BC_TIER_MIN="${BC_TIER_MIN:-0}"
FORCED_UPGRADE_MAX_TIER="${FORCED_UPGRADE_MAX_TIER:-5}"
FORCED_UPGRADE_MARGIN="${FORCED_UPGRADE_MARGIN:-0}"
TARGET_KL="${TARGET_KL:-0.02}"
ENTROPY_COEF="${ENTROPY_COEF:-0.001}"
MAX_GRAD_NORM="${MAX_GRAD_NORM:-1.0}"
# per-episode 长强加权（B06）：none=关闭（默认，逐位等价旧行为）；adv=缩放 advantage
GAME_WEIGHT_MODE="${GAME_WEIGHT_MODE:-none}"
GAME_WEIGHT_ALPHA="${GAME_WEIGHT_ALPHA:-0.5}"
GAME_WEIGHT_BETA="${GAME_WEIGHT_BETA:-0.5}"
GAME_WEIGHT_FLOOR="${GAME_WEIGHT_FLOOR:-0.5}"
GAME_WEIGHT_CAP="${GAME_WEIGHT_CAP:-2.0}"
# 人类盘面注入：库 / 保真度 / 席数（B07 起可切到与评测同构）
HB_LIB="${HB_LIB:-data/real_library/winner_library.jsonl}"
HB_FIDELITY="${HB_FIDELITY:-board}"
HB_SEATS="${HB_SEATS:-3}"
# 人类盘面课程 ramp（空 = 不传 -> 用 --human-board-sample auto 的"按回合难度曲线"）
HB_RAMP="${HB_RAMP:-}"
HB_QUANTILE_RAMP="${HB_QUANTILE_RAMP:-}"
RAMP_MODE="${RAMP_MODE:-step}"
RAMP_START="${RAMP_START:-0}"
RAMP_START="${RAMP_START:-0}"
# 固定阵容脚本席（1..3；0=关闭）。脚本席 = hybrid 对手：阵容动作优先、其余引擎 bot 兜底。
SCRIPT_SEATS="${SCRIPT_SEATS:-0}"
SCRIPT_COMPS="${SCRIPT_COMPS:-auto}"
# 冻结对手（联赛/自对弈）：FROZEN_SEATS 个 bot 席位由 FROZEN_OPPONENT 这个 checkpoint 驱动。
# 空/0 = 纯引擎 bot（旧行为，逐位等价）。见 docs/B04_DESIGN.md §2。
FROZEN_SEATS="${FROZEN_SEATS:-0}"
FROZEN_OPPONENT="${FROZEN_OPPONENT:-}"
DRY_RUN="${DRY_RUN:-0}"
TAG="${TAG:-$(basename "$OUT")}"
EVAL_GAMES="${EVAL_GAMES:-96}"
FORCE="${FORCE:-0}"
ALLOW_RUNNING="${ALLOW_RUNNING:-0}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,42p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "[error] 未知参数: $1（本脚本只接受 --dry-run / --help；其余用环境变量）" >&2; exit 2 ;;
  esac
  shift
done

LOG="$OUT/train.log"
META="$OUT/BLOCK_INFO.txt"
say() { printf '[train-block] %s\n' "$*"; }
die() { printf '[train-block][error] %s\n' "$*" >&2; exit 1; }

export PYTHONPATH="rust/python:."
unset CUDA_VISIBLE_DEVICES || true

# ---------------------------------------------------------------- 前置检查
[ -x "$PY" ] || die "python 不存在: $PY"
[ -f "$CK" ] || die "CK 不存在: $CK"
# TS 为空 = fresh optimizer（不加载 trainer state）；只有给了路径才校验存在性
if [ -n "$TS" ]; then
  [ -f "$TS" ] || die "TS 不存在: $TS（精确续训必须同时给 --checkpoint 与 --trainer-state）"
fi
[ -f scripts/train_entity_sync.py ] || die "缺 scripts/train_entity_sync.py"
[ -f scripts/eval_panel.sh ] || die "缺 scripts/eval_panel.sh"
[ "$STOP_DECISIONS" -ge 1000000 ] 2>/dev/null || die "STOP_DECISIONS 非法: $STOP_DECISIONS"

find_running_trainers() {
  local p cmd
  pgrep -u "$(id -un)" -f "train_entity_sync[.]py" 2>/dev/null | while read -r p; do
    cmd="$(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null || true)"
    case "$cmd" in *"--help"*) continue ;; esac
    printf '%s %s\n' "$p" "${cmd:0:140}"
  done
}
RUNNING_TRAINERS="$(find_running_trainers || true)"
if [ -n "$RUNNING_TRAINERS" ]; then
  if [ "$DRY_RUN" = "1" ] || [ "$ALLOW_RUNNING" = "1" ]; then
    say "[warn] 检测到正在运行的 trainer（并发会抢 GPU；开跑前确认它已退出）："
    printf '%s\n' "$RUNNING_TRAINERS" | sed 's/^/    /'
  else
    die "已有 train_entity_sync.py 在跑，拒绝并行启动（等它退出；ALLOW_RUNNING=1 可强行）：$RUNNING_TRAINERS"
  fi
fi

if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null || true)" ] && [ "$FORCE" != "1" ]; then
  die "OUT 非空: $OUT（换 OUT，或 FORCE=1 明确复用）"
fi

# ---------------------------------------------------------------- 最终命令（逐字基线：runs/next_block.sh）
CMD=("$PY" scripts/train_entity_sync.py
  --checkpoint "$CK" --trainer-state "$TS"
  --device "$DEVICE" --gpus "$GPUS" --processes "$PROCESSES" --threads "$THREADS"
  --minutes "$MINUTES" --seed "$SEED" --stop-at-decisions "$STOP_DECISIONS"
  --out "$OUT" --iterations 8000 --games "$GAMES"
  --arch entity --d-model 0 --n-layers 0 --n-heads 0
  --move-head-split 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2
  --archetype-bias-coef 0.0 --archetype-min-prob 0.6 --archetype-cache 0
  --sims 0 --determinizations 1 --opponent bot --behavior net
  --behavior-mix-eps 0.0 --behavior-mix-when carrier_or_spell
  --behavior-mix-max-per-turn 6 --behavior-mix-topk 8 --behavior-mix-turns 1
  --behavior-mix-max-ms 500.0 --behavior-mix-exact 1
  --epochs "$EPOCHS" --minibatch "$MINIBATCH" --lr "$LR" --lr-min-ratio "$LR_MIN_RATIO" --max-updates "$MAX_UPDATES"
  --clip "$CLIP" --target-kl "$TARGET_KL" --lam "$LAM" --gamma 1.0
  --adv-estimator gae --power-alpha 0.25 --power-kappa 10.0 --power-normalize 1
  --power-cutoff 0 --credit-timebase decision --baseline-action-dependent 0
  --max-grad-norm "$MAX_GRAD_NORM" --grad-accum "$GRAD_ACCUM"
  --leaf-compile 0 --leaf-amp off --leaf-wait-ms "$LEAF_WAIT_MS" --rc-threads 8
  --rust-collector 0 --frozen-seats "$FROZEN_SEATS" --trajectory-p 0.0
  --mirror-seats 0 --mirror-p 0.0 --mirror-sample p50 --mirror-seat-random 0
  --human-boards "$HB_LIB"
  --human-board-p 0.9 --human-board-seats "$HB_SEATS" --human-board-sample auto
  --human-board-set-tier 1 --human-board-fidelity "$HB_FIDELITY" --human-board-fast-inject 1
  --ramp-mode step --ramp-adaptive 0 --ramp-window 5
  --ramp-survive-threshold 0.25 --ramp-tier4-threshold 0.3
  --ramp-delay-decisions 2M --ramp-max-forced-per-game 12.0 --ramp-start-decisions "$RAMP_START"
  --shaping-coef 0.0 --shaping-w-str 1.0 --shaping-w-tier 0.5 --shaping-mode sigma
  --rank-utility-coef 1.0 --terminal-strength-coef 0.0
  --shaping-tier-bonus 0,0,20,60,150,400,900
  --forced-upgrade "$FORCED_UPGRADE" --forced-upgrade-margin "$FORCED_UPGRADE_MARGIN" \
  --forced-upgrade-max-tier "$FORCED_UPGRADE_MAX_TIER"
  --tier-target-coef "$TIER_COEF" --tier-penalty "$TIER_PENALTY" --tier-bonus "$TIER_BONUS"
  --tier-target-table "$TIER_TABLE" --tier-spread "$TIER_SPREAD"
  --library-p 0.0 --lockstep 1 --fast-act 1 --amp bf16
  --compile-train 1 --anchor-amp 1 --pi-coef 0.0
  --seq-coef 0.0 --seq-ramp-total-decisions 0.0
  --ceiling-aux-coef "${CEILING_AUX_COEF:-0}" \
  --bc-tier-min "${BC_TIER_MIN:-0}" --bc-coef "${BC_COEF:-0.0}" --bc-mmr-min "${BC_MMR_MIN:-6000}" --bc-mmr-boost "${BC_MMR_BOOST:-1.0}" \
  --bc-type-weight "${BC_TYPE_WEIGHT:-1.0}" --bc-card-weight "${BC_CARD_WEIGHT:-0.5}" \
  --bc-class-weight "${BC_CLASS_WEIGHT:-}" --bc-batch "${BC_BATCH:-128}" --bc-every "${BC_EVERY:-1}"
  --bc-samples "${BC_SAMPLES:-data/firestone_bc/bc_samples.jsonl.gz}"
  --bc-batch 128 --bc-every 1 --bc-compile 1 --bc-type-weight 1.0 --bc-card-weight 0.5
  --dpo-coef 0.0 --dpo-beta 0.1 --dpo-batch 128 --dpo-every 4
  --dpo-samples data/firestone_bc/bc_samples.jsonl.gz
  --problem-pool data/board_problems/problems.jsonl
  --problem-bc-coef 0.0 --problem-bc-every 1 --problem-batch 128
  --problem-min-strength-delta 0.0
  --strength-aux-coef 0.0 --strength-aux-every 1
  --strength-tier-pos-weight 1.0 --strength-head-init fit --strength-head-ridge 1.0
  --gold-curriculum 0 --curriculum-stage none --curriculum-gold-mult 1.0
  --curriculum-anneal-decisions 10000000
  --teacher-bc-coef 0.0 --process-value-coef 0.0
  --entropy-coef "$ENTROPY_COEF" --max-actions-per-turn 40 --max-steps 20000
  --log-every 10 --workers 1 --batch-size 64
  --gpu-free-check "$GPU_FREE_CHECK" --gpu-free-mib 1024
  --records-dtype fp32 --ipc-mode shm --ipc-shm-slots 2 --collect-sha 0
  --pipeline 1 --pipeline-guard warn --keep-versions 3
  --snapshot-every "$SNAPSHOT_EVERY" --keep-snapshots "$KEEP_SNAPSHOTS"
  --anchor-beta 0.1 --anchor-iterations 100000 --anchor-beta-tail 0.1
  --eval-every-decisions 10000000 --eval-first-decisions "$EVAL_FIRST_DECISIONS" \
  --eval-games 96 --eval-seats 8
  --eval-seed-base 420000 --eval-async 1 --eval-device "$EVAL_DEVICE"
  --eval-drain 1 --eval-stop-mean-rank 0.0
  --eval-panel human --eval-human-quantile auto --eval-human-baseline-bot 0
  --value-warmup-iters 5 --value-warmup-lr 0.001
  --value-warmup-minibatch 1024 --value-warmup-every 100
  --upgrade-reward 0.0 --win-only-reward 0.0 --strength-reward-coef 0.0
  --golden-reward 0.0 --golden-t5-reward 0.0 --amp-board-reward 0.0
  --engine-board-reward 0.0 --survive-t12-reward 0.0 --t5plus-stat-reward 0.0
  --tier-timing-reward 0.0 --cheap-buy-penalty 0.0 --t5plus-buff-reward 0.0
  --tier-mix-reward 0.0 --lowtier-stat-penalty 0.0
  --tier-upgrade-discount-scope all --tier-upgrade-discount 0
  --late-growth-coef 0.0 --churn-reward 0.0 --hightier-buy-reward 0.0
  --early-upgrade-reward 0.0 --collect-reroll-bias-t8t9 0.0 --collect-chain-buy-bias 0.0
  --chain-reward 0.0 --scaling-value-reward 0.0
  --scaling-value-model data/scaling_value/logit.npz
  --final-3500-reward 0.0 --final-20k-reward 0.0 --roll-bonus-t8t9 0.0
  --t9-chain-target-reward 0.0 --chain-early-reward 0.0 --late-rel-growth-coef 0.0
  --chain-any-reward 0.0 --strength-from-turn 0.0 --chain2-reward 0.0
  --chain-complete-bonus 0.5 --retain-growth-coef 0.0 --tier-early-reward 0.0
  --churn-pair-reward 0.0 --roll-pair-reward 0.0 --churn-sell-cap 12.0 --churn-roll-cap 8.0
  --hero-power-reward 0.0 --late-log-ratio-coef 0.0 --late-alive-bonus 0.0
  --late-death-penalty 0.0 --late-shadow-ratio 3.15 --late-shadow-coef 0.0
  --save-up-reward 0.0 --t1s-coef 0.0 --t1p-coef 0.0
  --comp-fit-coef "$COMP_FIT_COEF" --comp-fit-t9-bonus "$COMP_FIT_T9_BONUS"
  --comp-trinket-coef "$COMP_TRINKET_COEF"
  --collect-discover-bias 0.0 --collect-triple-bias 0.0 --record-logp-mu 0
  --upgrade-curve-bc-turns 2,5,7,9 --upgrade-curve-bc-guard-ratio -1.0
  --upgrade-curve-bc-coef 0.0 --discover-bc-coef 0.0 --triple-bc-coef 0.0
  --bc-ce-norm 1 --bc-warmup-decisions 0.0 --bc-guard-ratio 0.0
  --dyn-curriculum 0 --dyn-start-seats 2 --dyn-max-seats 5 --dyn-p 0.75
  --script-seats "$SCRIPT_SEATS" --script-comps "$SCRIPT_COMPS"
  --dyn-threshold 0.1 --dyn-hold-decisions 10000000.0 --dyn-quality-games 96)

# 人类盘面课程 ramp（空 -> 不加参数；非空才覆盖 sample 的按回合曲线）
if [ -n "$HB_RAMP" ]; then
  CMD+=(--human-board-ramp "$HB_RAMP")
fi
if [ -n "$HB_QUANTILE_RAMP" ]; then
  CMD+=(--human-board-quantile-ramp "$HB_QUANTILE_RAMP")
fi
if [ -n "$HB_RAMP" ] || [ -n "$HB_QUANTILE_RAMP" ]; then
  CMD+=(--ramp-mode "$RAMP_MODE" --ramp-start-decisions "$RAMP_START")
fi

# 长强局加权（默认 none -> 不加任何参数，命令行逐字不变）
if [ "$GAME_WEIGHT_MODE" != "none" ]; then
  CMD+=(--game-weight-mode "$GAME_WEIGHT_MODE"
        --game-weight-alpha "$GAME_WEIGHT_ALPHA"
        --game-weight-beta "$GAME_WEIGHT_BETA"
        --game-weight-floor "$GAME_WEIGHT_FLOOR"
        --game-weight-cap "$GAME_WEIGHT_CAP")
fi

# 冻结对手（非空时才加，保证空值路径与旧命令逐位一致）
if [ -n "$FROZEN_OPPONENT" ] && [ "$FROZEN_SEATS" -gt 0 ] 2>/dev/null; then
  [ -f "$FROZEN_OPPONENT" ] || die "FROZEN_OPPONENT 不存在: $FROZEN_OPPONENT"
  case "$FROZEN_OPPONENT" in
    comp:*) ;;
    *) CMD+=(--frozen-opponent "$FROZEN_OPPONENT") ;;
  esac
fi

gpu_snapshot() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader 2>/dev/null || true
  else
    echo "nvidia-smi 不可用"
  fi
}

# ---------------------------------------------------------------- dry-run
if [ "$DRY_RUN" = "1" ]; then
  say "=== GPU 现状 ==="
  gpu_snapshot
  say "=== 配置 ==="
  say "CK=$CK"
  say "TS=$TS"
  say "OUT=$OUT  TAG=$TAG  SEED=$SEED  STOP_DECISIONS=$STOP_DECISIONS  GAMES=$GAMES"
  say "PROCESSES=$PROCESSES  GPUS=$GPUS  DEVICE=$DEVICE  EVAL_DEVICE=$EVAL_DEVICE  GPU_FREE_CHECK=$GPU_FREE_CHECK  SCRIPT_SEATS=$SCRIPT_SEATS  SCRIPT_COMPS=$SCRIPT_COMPS"
  say "FROZEN_SEATS=$FROZEN_SEATS  FROZEN_OPPONENT=$FROZEN_OPPONENT"
  say "GAME_WEIGHT_MODE=$GAME_WEIGHT_MODE  alpha=$GAME_WEIGHT_ALPHA beta=$GAME_WEIGHT_BETA floor=$GAME_WEIGHT_FLOOR cap=$GAME_WEIGHT_CAP"
  say "HB_LIB=$HB_LIB  HB_FIDELITY=$HB_FIDELITY  HB_SEATS=$HB_SEATS"
  say "FORCED_UPGRADE=$FORCED_UPGRADE margin=$FORCED_UPGRADE_MARGIN"
  say "BC_COEF=${BC_COEF:-0} BC_MMR_MIN=${BC_MMR_MIN:-6000} BC_CARD_WEIGHT=${BC_CARD_WEIGHT:-0.5} BC_CLASS_WEIGHT=${BC_CLASS_WEIGHT:-}"
  say "LAM=$LAM  TIER_COEF=$TIER_COEF TIER_PENALTY=$TIER_PENALTY TIER_BONUS=$TIER_BONUS TIER_TABLE=$TIER_TABLE TIER_SPREAD=$TIER_SPREAD"
  say "HB_RAMP=$HB_RAMP  HB_QUANTILE_RAMP=$HB_QUANTILE_RAMP  RAMP_MODE=$RAMP_MODE  RAMP_START=$RAMP_START"
  say "LR=$LR  LR_MIN_RATIO=$LR_MIN_RATIO  MAX_UPDATES=$MAX_UPDATES  EPOCHS=$EPOCHS  MINIBATCH=$MINIBATCH  GRAD_ACCUM=$GRAD_ACCUM  CLIP=$CLIP  TARGET_KL=$TARGET_KL  ENTROPY_COEF=$ENTROPY_COEF  MAX_GRAD_NORM=$MAX_GRAD_NORM"
  say "COMP_FIT_COEF=$COMP_FIT_COEF  COMP_FIT_T9_BONUS=$COMP_FIT_T9_BONUS  COMP_TRINKET_COEF=$COMP_TRINKET_COEF"
  say "=== 最终训练命令 ==="
  printf '%s ' "${CMD[@]}"; printf '\n'
  say "=== 训练结束后 ==="
  say "EVAL_DEVICE=$EVAL_DEVICE bash scripts/eval_panel.sh $OUT/model.pt ${TAG}_panel $EVAL_GAMES"
  exit 0
fi

# ---------------------------------------------------------------- 真跑
mkdir -p "$OUT"
exec 9>"$OUT/.train.lock"
flock -n 9 || die "OUT 已被另一个进程锁定: $OUT"

say "start $(date '+%F %T %z') seed=$SEED stop=$STOP_DECISIONS out=$OUT"
{
  echo "# train_block_clean.sh"
  echo "started_at=$(date '+%F %T %z')"
  echo "root=$ROOT"
  echo "git_head=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "ckpt=$CK"
  echo "ckpt_sha256=$(sha256sum "$CK" | cut -d' ' -f1)"
  echo "trainer_state=$TS"
  echo "trainer_state_sha256=$(sha256sum "$TS" | cut -d' ' -f1)"
  echo "seed=$SEED stop_decisions=$STOP_DECISIONS games=$GAMES processes=$PROCESSES"
  echo "gpus=$GPUS device=$DEVICE eval_device=$EVAL_DEVICE"
  echo "comp_fit_coef=$COMP_FIT_COEF comp_fit_t9_bonus=$COMP_FIT_T9_BONUS comp_trinket_coef=$COMP_TRINKET_COEF"
  echo "frozen_seats=$FROZEN_SEATS frozen_opponent=$FROZEN_OPPONENT"
  echo "gpu_snapshot_at_start:"
  gpu_snapshot | sed 's/^/  /'
  echo "command:"
  printf '%s ' "${CMD[@]}" | sed 's/^/  /'; echo
} > "$META"

rc=0
"${CMD[@]}" >>"$LOG" 2>&1 || rc=$?
say "trainer exited rc=$rc at $(date '+%F %T %z')"
if [ "$rc" -ne 0 ]; then
  tail -n 40 "$LOG" >&2 || true
  die "训练失败 rc=$rc（日志 $LOG）"
fi

# ---------------------------------------------------------------- 结束复评（canonical 口径）
FINAL_CKPT="$OUT/model.pt"
if [ ! -f "$FINAL_CKPT" ]; then
  FINAL_CKPT="$(ls -t "$OUT"/eval/ckpt_*.pt 2>/dev/null | head -n 1 || true)"
fi
[ -n "$FINAL_CKPT" ] && [ -f "$FINAL_CKPT" ] || die "训练结束但找不到 model.pt / eval ckpt：$OUT"
say "final_ckpt=$FINAL_CKPT sha256=$(sha256sum "$FINAL_CKPT" | cut -d' ' -f1)"

EVAL_OUT="runs/eval_panel/${TAG}_panel.json"
say "eval_panel start tag=${TAG}_panel device=$EVAL_DEVICE games=$EVAL_GAMES"
EVAL_DEVICE="$EVAL_DEVICE" bash scripts/eval_panel.sh "$FINAL_CKPT" "${TAG}_panel" "$EVAL_GAMES" >>"$LOG" 2>&1 \
  || say "[warn] eval_panel 非零退出；检查 $EVAL_OUT 与 runs/eval_panel/${TAG}_panel.err"

if [ -s "$EVAL_OUT" ]; then
  say "eval_panel OK -> $EVAL_OUT"
  "$PY" - "$EVAL_OUT" "$FINAL_CKPT" <<'PY' || true
import json, sys
d = json.load(open(sys.argv[1]))
print('[train-block] FINAL rank=%s top4=%s strength=%s tier4+=%s survive12=%s games=%s ckpt=%s' % (
    round((d.get('mean_rank') or 0), 3), round((d.get('top4') or 0), 3),
    d.get('death_strength_p50'), round((d.get('tier_ge4_ratio') or 0), 3),
    round((d.get('survive_t12_ratio') or 0), 3), d.get('games'), sys.argv[2]))
PY
else
  die "eval_panel 没产出有效 JSON: $EVAL_OUT"
fi
say "done $(date '+%F %T %z')"
