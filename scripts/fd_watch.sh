#!/bin/bash
# s23b fd/shm 宸℃锛氭瘡 60s 璁板綍鐖惰繘绋?fd 鏁颁笌鏈€杩?iter 鐨?collect.shm_unclosed
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
OUT=runs/az_entity_s23b/fd_watch.log
: > "$OUT"
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
for i in $(seq 1 400); do
  P=$(ps -eo pid,cmd | grep "train_entity_sync.py --checkpoint runs/az_entity_s23/snapshots/step_000101" | grep -v grep | awk '{print $1}' | head -1)
  if [ -z "$P" ]; then
    # 杩涚▼鍙兘浠ュ埆鐨勫懡浠よ鍚姩锛岄€€鍥炴寜 run_s23b 鎵?    P=$(ps -eo pid,cmd | grep "scripts/train_entity_sync.py" | grep -v grep | awk '{print $1}' | head -1)
  fi
  FD=$( [ -n "$P" ] && ls /proc/$P/fd 2>/dev/null | wc -l || echo NA )
  SU=$("$PY" - <<'EOF' 2>/dev/null
import json
p="runs/az_entity_s23b/history.jsonl"
try:
    last=None
    for line in open(p,encoding="utf-8"):
        line=line.strip()
        if not line: continue
        r=json.loads(line)
        if "iter" in r: last=r
    c=(last or {}).get("collect") or {}
    print(f"iter={last['iter']} shm_unclosed={c.get('shm_unclosed')} fd_limit={c.get('fd_limit')} dec_s={round(c.get('decisions_per_s',0))}")
except Exception as e:
    print("NA")
EOF
)
  echo "$(date +%H:%M:%S) pid=$P fd=$FD $SU" >> "$OUT"
  sleep 60
done
