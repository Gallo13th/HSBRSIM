#!/bin/bash
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
echo "=== load_checkpoint ==="
grep -n 'def load_checkpoint' -A 45 hsbg/az/train/model.py
echo
echo "=== model.eval() in collect paths ==="
grep -rn '\.eval()' hsbg/az/train/parallel_collect.py hsbg/az/train/process_pool.py hsbg/az/train/ppo.py | head -20
echo
echo "=== prior run args: ab_ls_p24 ==="
head -c 2000 runs/ab_ls_p24/history.jsonl 2>/dev/null | head -1
echo
echo "=== recent runs launch configs (processes/gpus/threads/games) ==="
for d in runs/az_entity_s16 runs/az_entity_s17 runs/az_entity_s19 runs/ab_ls_p24; do
  if [ -f "$d/history.jsonl" ]; then
    echo "--- $d"
    head -1 "$d/history.jsonl" | python3 -c "import sys,json; a=json.loads(sys.stdin.readline()); print({k:a.get(k) for k in ('processes','gpus','threads','games','sims','minibatch','grad_accum','lr','stop_at_decisions','eval_games','eval_every_decisions','human_board_seats','human_board_p','mirror_seats')})" 2>/dev/null
  fi
done
