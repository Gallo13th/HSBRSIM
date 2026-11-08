#!/bin/bash
# GPU 恢复后自动续训 B11（无需 root）：轮询 nvidia-smi，一旦可用就拉起训练 + 四件套。
# 用法：setsid nohup bash tools/resume_b11_when_gpu.sh > /tmp/resume_when_gpu.log 2>&1 &
set -u
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
STATE_DONE=29330426          # step_000501 的累计决策
SNAP=runs/az_stage300m_b11/snapshots/step_000501
LOG=/tmp/resume_when_gpu.log

say() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

if ! "$PY" -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
  say "torch.cuda 不可用，开始轮询（每 60s）"
  for i in $(seq 1 2880); do            # 最多等 48 小时
    if "$PY" -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
      say "GPU 恢复（第 $i 次轮询）"
      break
    fi
    sleep 60
  done
fi
if ! "$PY" -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
  say "等待超时，放弃"; exit 1
fi
if pgrep -u "$(id -un)" -f 'train_entity_sync[.]py' >/dev/null 2>&1; then
  say "已有 trainer 在跑，不再启动"; exit 0
fi
say "启动 B11 续训：snap=$SNAP DONE=$STATE_DONE"
setsid nohup env SNAPSHOT_EVERY=50 \
  CK="$SNAP/model.pt" TS="$SNAP/trainer.pt" OUT=runs/az_stage300m_b11 SEED=28341 \
  STOP=$((300000000 - STATE_DONE)) RAMP_START="$STATE_DONE" MINUTES=1500 \
  bash scripts/run_stage300m_b11.sh > /tmp/b11_launch4.log 2>&1 < /dev/null &
sleep 60
setsid nohup bash tools/relabel_b11.sh 0 "$(date '+%F %T')" > /tmp/relabel_b11.log 2>&1 < /dev/null &
setsid nohup bash -c "export HSBRSIM_FORCE_UPGRADE=1 HSBRSIM_FORCE_UPGRADE_MAX_TIER=5 HSBRSIM_BAN_TRINKETS=BG36_MagicItem_414 PYTHONPATH=rust/python:.; exec $PY scripts/stage_monitor.py --run runs/az_stage300m_b11 --until-decisions 300000000 --eval-gpu auto --gpu-priority 7,1,6 --bot-panel-games 96 --bot-panel-seed 620000 --redraw-every 120 --dev-offset 0 --cum-offset $STATE_DONE --retry-skipped 1 --retry-min-decisions 0" > /tmp/b11_monitor.log 2>&1 < /dev/null &
setsid nohup bash tools/eval_b11_panels.sh > /tmp/eval_b11_panels.log 2>&1 < /dev/null &
"$PY" - <<PY
import json
rows=[json.loads(l) for l in open('runs/az_stage300m_b11/history.jsonl') if l.strip()]
json.dump({"done": $STATE_DONE, "hist_len": len(rows), "gen": 13}, open('/tmp/watchdog_b11_state.json','w'))
PY
setsid nohup "$PY" "$PWD/tools/watchdog_b11.py" >> /tmp/watchdog_b11.log 2>&1 < /dev/null &
say "续训 + 四件套已启动"
