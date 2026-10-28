#!/usr/bin/env bash
# 一键 stage-1 训练：BC 冷启动（可选）→ PPO（论文超参 + KL anchor）→ 512 局评测。
#
# 用法：
#   bash scripts/train_stage1.sh --smoke              # 冒烟：tiny 网络、2 分钟，验证链路
#   bash scripts/train_stage1.sh --gpus 0,5,6,7       # 完整 stage-1（默认 30M decisions）
#   bash scripts/train_stage1.sh --gpus 0 --decisions 5M   # 单卡小预算
#   bash scripts/train_stage1.sh --init runs/xxx/model.pt  # 指定起点 checkpoint
#
# 关键默认值（与 docs/MULTISTAGE_TRAINING.md §12 的 stage-1 一致）：
#   sims=0（无 MCTS）/ behavior=net / clip 0.2 / target KL 0.05 / λ=0.995 /
#   entropy 0.002 / grad-clip 1.0 / lr 6e-6→5e-6 / 有效 minibatch 8192 /
#   KL anchor β=0.1 前 100 iter / 每 5M 做一次 512 局 C0 评测。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
PY="${PYTHON:-python3}"

GPUS="0,5,6,7"
PROCESSES=""
THREADS="16"
DECISIONS="30M"
GAMES="192"
SEED="900"
INIT=""
OUT="runs/stage1"
SMOKE="0"
BC_SAMPLES="500000"
EXTRA=()

while [ $# -gt 0 ]; do
  case "$1" in
    --smoke) SMOKE=1; shift ;;
    --gpus) GPUS="$2"; shift 2 ;;
    --processes) PROCESSES="$2"; shift 2 ;;
    --threads) THREADS="$2"; shift 2 ;;
    --decisions) DECISIONS="$2"; shift 2 ;;
    --games) GAMES="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --init) INIT="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --bc-samples) BC_SAMPLES="$2"; shift 2 ;;
    --) shift; EXTRA+=("$@"); break ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1;36m[train]\033[0m %s\n' "$*"; }
export PYTHONPATH="$REPO/rust/python:$REPO"

# ---- 0) 环境检查 -----------------------------------------------------------
"$PY" - <<'EOF' || { echo "缺依赖：先跑 bash scripts/bootstrap.sh" >&2; exit 2; }
import importlib.util, sys
missing = [m for m in ("numpy", "torch") if importlib.util.find_spec(m) is None]
if importlib.util.find_spec("hsbg_engine") is None and "hsbg_engine" not in sys.builtin_module_names:
    missing.append("hsbg_engine")
raise SystemExit(1 if missing else 0)
EOF

NVGPU=$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null | wc -l || echo 0)
say "检测到 GPU 数量: ${NVGPU}；使用 --gpus ${GPUS}"
if [ -z "$PROCESSES" ]; then
  N=$(awk -F, '{print NF}' <<< "$GPUS")
  PROCESSES=$(( N * 2 ))
fi

# ---- 1) 冒烟 ---------------------------------------------------------------
if [ "$SMOKE" = "1" ]; then
  say "冒烟：tiny 网络 + sims0 + 2 iteration（不产生正式结果）"
  "$PY" scripts/train_entity_sync.py --arch tiny --device "${SMOKE_DEVICE:-cpu}" \
    --sims 0 --processes 1 --workers 2 --games 4 --iterations 2 --epochs 1 \
    --minibatch 128 --lr 1e-4 --anchor-beta 0.1 --anchor-iterations 100 \
    --eval-every-decisions 0 --out runs/smoke_stage1 "$@" "${EXTRA[@]}"
  say "冒烟完成：runs/smoke_stage1/（可用 scripts/analyze_stage1.py 看曲线）"
  exit 0
fi

# ---- 2) 起点 checkpoint ----------------------------------------------------
if [ -z "$INIT" ]; then
  if [ -f "runs/az_entity_1m_s0/model.pt" ]; then
    INIT="runs/az_entity_1m_s0/model.pt"
    say "使用已有起点 checkpoint: ${INIT}"
  else
    say "没有现成 checkpoint → 先跑 BC 冷启动（${BC_SAMPLES} 样本，约 8–15 分钟）"
    "$PY" scripts/train_bc_bot.py --games 3753 --max-samples "$BC_SAMPLES" --epochs 3 \
      --arch entity --device "${BC_DEVICE:-cuda:0}" --out runs/bc_cold_start
    INIT="runs/bc_cold_start/model.pt"
  fi
fi

# ---- 3) 预算换算 -----------------------------------------------------------
case "$DECISIONS" in
  *M) TARGET=$(( ${DECISIONS%M} * 1000000 )) ;;
  *k) TARGET=$(( ${DECISIONS%k} * 1000 )) ;;
  *)  TARGET="$DECISIONS" ;;
esac
ITER=$(python3 -c "import math;print(max(1, math.ceil($TARGET / ($GAMES * 155))))")
say "预算 ${TARGET} decisions ≈ ${ITER} iterations（每 iter ${GAMES} 局）"

# ---- 4) 训练 ---------------------------------------------------------------
say "开始阶段训练：entity 14.8M / sims=0 / KL anchor / bf16 关闭 / 8×2 进程"
"$PY" scripts/train_entity_sync.py \
  --checkpoint "$INIT" --arch entity --device cuda:0 \
  --processes "$PROCESSES" --gpus "$GPUS" --threads "$THREADS" --games "$GAMES" \
  --sims 0 --determinizations 1 --opponent bot --behavior net \
  --epochs 1 --minibatch 1024 --grad-accum 8 \
  --lr 6e-6 --lr-min-ratio 0.833 --max-updates "$ITER" \
  --clip 0.2 --target-kl 0.05 --lam 0.995 --max-grad-norm 1.0 \
  --entropy-coef 0.002 --pi-coef 0.0 --max-steps 10000 \
  --anchor-beta 0.1 --anchor-iterations 100 \
  --iterations "$ITER" --minutes 900 \
  --snapshot-every 100 --keep-snapshots 5 \
  --eval-every-decisions 5000000 --eval-games 512 --eval-seats 8 \
  --eval-seed-base 420000 --eval-device cuda:0 \
  --seed "$SEED" --out "$OUT" "${EXTRA[@]}"

# ---- 5) 收尾评测 -----------------------------------------------------------
BEST="$OUT/model.pt"
if [ -f "$BEST" ]; then
  say "收尾：512 局 C0 评测（未见面板 seed_base 440000）"
  "$PY" scripts/c0_gate.py --checkpoint "$BEST" --arch entity --device cuda:0 \
    --games 512 --seats 8 --seed-base 440000 --smoke --bootstrap 1000 \
    --out "$OUT/eval/final_c0_440000.json" || true
  say "汇总："
  "$PY" scripts/analyze_stage1.py --run "$OUT" || true
fi
say "完成。产物在 ${OUT}/（model.pt、history.json、eval/）"
