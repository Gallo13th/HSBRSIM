#!/bin/bash
# Relabel post-resume in-training eval ckpts (process-local decisions) to GLOBAL decisions
# by hardlinking ckpt_<local>.pt -> ckpt_<local+OFFSET>.pt. Monitor then finds global names.
#
# Usage: bash scripts/eval_relabel.sh [offset] [since]
set -u
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
OFFSET="${1:-34980549}"
SINCE="${2:-2026-11-04 11:46:00}"
DIR=runs/az_stage300m_b01/eval
MARK="$DIR/.relabeled"
touch "$MARK"

while true; do
  # only post-resume local ckpts (mtime after resume), not yet processed
  while IFS= read -r f; do
    base=$(basename "$f")
    [ "$base" = "$(basename "$f")" ] || continue
    grep -qxF "$base" "$MARK" && continue
    local_dec=$(echo "$base" | sed -n 's/^ckpt_0*\([0-9][0-9]*\)\.pt$/\1/p')
    [ -n "$local_dec" ] || { echo "$base" >> "$MARK"; continue; }
    # 已经带全局名（decisions 很大）的跳过
    if [ "$local_dec" -ge "$OFFSET" ]; then echo "$base" >> "$MARK"; continue; fi
    global=$((local_dec + OFFSET))
    gname=$(printf "ckpt_%09d.pt" "$global")
    if [ ! -e "$DIR/$gname" ]; then
      ln "$f" "$DIR/$gname" 2>/dev/null && echo "[relabel] $base -> $gname"
    fi
    echo "$base" >> "$MARK"
  done < <(find "$DIR" -maxdepth 1 -name 'ckpt_*.pt' -newermt "$SINCE" -type f 2>/dev/null | sort)
  sleep 30
done
