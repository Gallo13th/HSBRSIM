#!/bin/bash
# Relabel post-resume in-training eval ckpts (process-local decisions) to GLOBAL decisions
# by hardlinking ckpt_<local>.pt -> ckpt_<local+OFFSET>.pt. Monitor then finds global names.
#
# Usage: bash scripts/eval_relabel.sh [offset] [since]
set -u
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
OFFSET="${1:-0}"
SINCE="${2:-2026-11-04 11:46:00}"
DIR=runs/az_stage300m_b08/eval
MARK="$DIR/.relabeled"          # 已处理过的文件名（local 或 global）
CREATED="$DIR/.relabeled_global" # 由本脚本创建的 global 文件名
touch "$MARK" "$CREATED"

while true; do
  while IFS= read -r f; do
    base=$(basename "$f")
    grep -qxF "$base" "$MARK" && continue
    grep -qxF "$base" "$CREATED" && { echo "$base" >> "$MARK"; continue; }
    local_dec=$(echo "$base" | sed -n 's/^ckpt_0*\([0-9][0-9]*\)\.pt$/\1/p')
    [ -n "$local_dec" ] || { echo "$base" >> "$MARK"; continue; }
    # 注意：不能因为 local_dec >= OFFSET 就跳过——resume 后 local 35M > offset 34.98M
    # 也是合法 local 名；只靠 CREATED 集合区分本脚本创建的 global 名。
    global=$((local_dec + OFFSET))
    gname=$(printf "ckpt_%09d.pt" "$global")
    if [ ! -e "$DIR/$gname" ]; then
      ln "$f" "$DIR/$gname" 2>/dev/null && {
        echo "[relabel] $base -> $gname"
        echo "$gname" >> "$CREATED"
      }
    else
      echo "$gname" >> "$CREATED"
    fi
    echo "$base" >> "$MARK"
  done < <(find "$DIR" -maxdepth 1 -name 'ckpt_*.pt' -newermt "$SINCE" -type f 2>/dev/null | sort)
  sleep 30
done
