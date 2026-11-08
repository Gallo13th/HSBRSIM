# HSBRSIM 常用入口（复制即可用）
#
#   make setup            一键装环境（bash scripts/bootstrap.sh）
#   make verify           快速门禁（Rust + Python + smoke + TavernBench）
#   make smoke            冒烟训练（tiny，2 分钟）
#   make train            完整 stage-1（默认 GPU 0,5,6,7；可覆盖 GPUS=0）
#   make train-5m         单卡 5M decisions
#   make bench            吞吐基线（sims=0，3 分钟）
#   make arena-check      竞技场契约自检（不需要密钥）
#   make clean-runs       清理 runs/ 下的临时 profile 目录（保留 checkpoint）

PY ?= python3
GPUS ?= 0,5,6,7
DECISIONS ?= 30M
export PYTHONPATH := rust/python:.

.PHONY: setup verify smoke train train-5m bench arena-check clean-runs test

setup:
	bash scripts/bootstrap.sh

verify:
	$(PY) scripts/verify_all.py --fast

smoke:
	bash scripts/train_stage1.sh --smoke

train:
	bash scripts/train_stage1.sh --gpus $(GPUS) --decisions $(DECISIONS)

train-5m:
	bash scripts/train_stage1.sh --gpus 0 --decisions 5M --games 128

bench:
	$(PY) scripts/bench_process_pool.py \
	  --checkpoint runs/az_entity_kl_30m/model.pt --arch entity \
	  --processes 8 --gpus $(GPUS) --threads 16 --games 192 --sims 0 \
	  --warmup-rounds 0 --minutes 3 --out runs/bench/sims0_3min.json

arena-check:
	$(PY) scripts/arena_client.py --url https://rizling.top --check \
	  --policy arena_agent:act --expected-ruleset tg36-bc45cfc55a0e5cd6c14c \
	  --catalog-sha256 c4c42e6ce5060e1b79fbcd5f4edbf6d17495f0f52690072481d690610f7ef6d7

test:
	$(PY) -m pytest tests -q

clean-runs:
	rm -rf runs/profile_iter15 runs/timeline_iter5 runs/smoke_stage1 runs/bench/_proc_tmp
