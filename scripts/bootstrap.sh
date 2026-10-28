#!/usr/bin/env bash
# 一键环境：装 hsbg-agent + 编译/安装 Rust 引擎 hsbg_engine + 冒烟自检。
#
# 用法：
#   bash scripts/bootstrap.sh                 # 完整安装（含 torch）
#   SKIP_PIP=1 bash scripts/bootstrap.sh      # 只在已有环境里装引擎（跳过 pip 依赖）
#   SKIP_ENGINE=1 bash scripts/bootstrap.sh   # 只装 Python 包，不编译引擎
#   PYTHON=/path/to/python bash scripts/bootstrap.sh
#
# 依赖：Linux / macOS；Python ≥3.10；Rust ≥1.98（引擎需要）；GPU 可选。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
PY="${PYTHON:-python3}"
SKIP_PIP="${SKIP_PIP:-0}"
SKIP_ENGINE="${SKIP_ENGINE:-0}"

say() { printf '\n\033[1;36m[bootstrap]\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31m[bootstrap:error]\033[0m %s\n' "$*" >&2; exit 1; }

say "repo: $REPO"
say "python: $($PY -V 2>&1)  (路径: $($PY -c 'import sys;print(sys.executable)'))"
$PY - <<'EOF' || die "需要 Python >= 3.10"
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
EOF

if [ "$SKIP_PIP" != "1" ]; then
  say "安装 Python 依赖（numpy / torch / pytest / matplotlib）…"
  $PY -m pip install -U pip
  $PY -m pip install -e ".[train,dev,plot]"
else
  say "SKIP_PIP=1：跳过 Python 依赖安装"
fi

if [ "$SKIP_ENGINE" != "1" ]; then
  say "编译并安装 Rust 引擎（hsbg_engine，首次 2–5 分钟）…"
  if ! command -v cargo >/dev/null 2>&1; then
    die "找不到 cargo。请先装 Rust（https://rustup.rs），本仓库需要 1.98+；见 rust/rust-toolchain.toml"
  fi
  ( cd rust && $PY -m pip install -e . )
else
  say "SKIP_ENGINE=1：跳过引擎编译"
fi

say "自检：引擎版本 / 数据 / 动作-观测契约"
PYTHONPATH="$REPO/rust/python:$REPO" "$PY" - <<'EOF'
import hsbg_engine as E
print("engine   :", E.version(), "| game:", E.game_version(), "| data:", E.data_info())
print("layout   :", len(E.layout()), "项 | actions:", E.layout().get("N_ACTIONS") if hasattr(E.layout(), "get") else "n/a")
g = E.Game(seed=1)
for _ in range(200):
    for p in range(g.num_players):
        if g.needs_action(p):
            g.step(p, g.bot_action(p))
    if g.is_over():
        break
print("smoke    : turn", g.turn, "| over", g.is_over(), "| players", g.num_players)
EOF

if [ "$SKIP_PIP" != "1" ]; then
  say "跑快速门禁（Rust 测试 + Python 测试 + smoke + TavernBench；data_check 按需 SKIP）"
  PYTHONPATH="$REPO/rust/python:$REPO" "$PY" scripts/verify_all.py --fast || \
    die "门禁未通过；详见上面的输出（data_check 缺上游 AutoTavern 时 SKIP 属正常）"
fi

cat <<'EOF'

[bootstrap] 完成。下一步（任选）：

  # 1) 只做冒烟训练（CPU/单卡，几分钟）
  bash scripts/train_stage1.sh --smoke

  # 2) 完整 stage-1（BC 冷启动 → 30M PPO，4 卡约 6–7 小时；单卡更慢）
  bash scripts/train_stage1.sh --gpus 0,5,6,7 --decisions 30M

  # 3) 文档
  #   docs/QUICKSTART.md            一键开始 / 常见问题
  #   docs/MULTISTAGE_TRAINING.md   训练曲线与 stage-1 结果
  #   docs/THROUGHPUT_TIMELINE.md   吞吐瓶颈与并行方案
EOF
