# Stage-3 训练配方（可执行版）

> 目标：在 **30M decisions** 预算内，用 stage-1+stage-2 的冠军权重继续训练，把 C0 mean rank 稳定
> 压到 **≤3.0**，并且**不复发 stage-2 的发散**（entropy 上升 / 回合变长）。
> 本文只写"怎么跑、怎么判、怎么回滚"；依据与文献背景见 `docs/RECIPE_IDEAS_REVIEW.md`、
> 复盘见 `docs/MULTISTAGE_TRAINING.md` §13。

## 1. 起点与基线

| 项 | 值 |
|---|---|
| 起点权重 | `runs/champion_c0_3004.pt`（stage-2 在 10.03M 的冠军） |
| C0 512 局（seed_base 420000） | **mean rank 3.004 / top4 83.4% / 吃鸡 16.6%** |
| 在线竞技场 10 局（practice） | 均名 3.10 / 前四 70% / 吃鸡 20% |
| stage-2 失败态（对照） | 25M 时 mean rank 4.504、entropy 0.581、decisions/局 244 |

## 2. 超参（相对 stage-2 的改动只有 4 处）

| 项 | stage-2 | **stage-3** | 理由 |
|---|---|---|---|
| KL anchor | β=0.1 前 100 iter，之后 **0** | β=0.1 前 20%，之后 **0.02**（`--anchor-beta-tail 0.02`） | stage-2 撤锚后 entropy 0.37→0.58 |
| 学习率 | 6e-6 | **2e-6**（`--lr-min-ratio 0.5`，余弦到 1e-6） | 已收敛策略上 6e-6 步子太大 |
| target KL | 0.05 | **0.02** | approx_kl 中位 0.0035、p90 0.076 → 收紧 |
| entropy_coef | 0.002 | **0.001** | 降低"鼓励随机"的项 |
| 其余 | clip 0.2 / γ=1.0 / λ=0.995 / 有效 minibatch 8192（1024×8）/ bf16 / pipeline / lock-step | **不变** | 已验证 |

## 3. 评测与早停

- **每 2.5M decisions** 做一次 512 局 C0 评测（`--eval-every-decisions 2500000 --eval-games 512 --eval-seats 8 --eval-seed-base 420000`）；
- 每 **5M** 在未见面板（`--eval-seed-base 440000`）复核一次，防止过拟合监控面板；
- **早停规则**：若某次评测比历史最佳差 **>0.2**（mean rank），且下一次仍未恢复 → 停止训练、回滚到最佳 checkpoint；
- 每次评测同时记录：`top4`、`win`、`illegal`、`truncated`、训练侧 `entropy`、`approx_kl`、`decisions/局`。

## 4. 验收标准（全部满足才算成功）

1. C0 512 局 **mean rank ≤ 3.0**，且 top4 ≥ 83%；
2. 训练稳定：`entropy ≤ 0.45`、`decisions/局 ≤ 200`、`approx_kl` 中位 ≤0.01；
3. 未见面板 mean rank 与监控面板差 ≤0.15（不过拟合）；
4. 在线竞技场 10 局 mean rank ≤3.1（与冠军持平或更好）。

## 5. 失败回退（按顺序）

1. 回滚到最佳 checkpoint（不丢已有进展）；
2. 降 lr 到 1e-6、target KL 到 0.01；
3. 关掉流水线（`--pipeline 0`，消除 1 批滞后）；
4. 暂停 anchor-tail（`--anchor-beta-tail 0.05` 提高锚强度）。

## 6. 命令（当前空闲卡 1/2/3，learner 用 2）

```bash
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM

env -u CUDA_VISIBLE_DEVICES $P scripts/train_entity_sync.py \
  --checkpoint runs/champion_c0_3004.pt --arch entity --device cuda:2 \
  --processes 12 --gpus 1,3,0 --threads 16 --games 192 --sims 0 \
  --epochs 1 --minibatch 1024 --grad-accum 8 --amp bf16 \
  --lr 2e-6 --lr-min-ratio 0.5 --max-updates 1200 \
  --clip 0.2 --target-kl 0.02 --lam 0.995 --max-grad-norm 1.0 \
  --entropy-coef 0.001 --pi-coef 0.0 \
  --anchor-beta 0.1 --anchor-iterations 200 --anchor-beta-tail 0.02 \
  --pipeline 1 --lockstep 1 --seed 2100 \
  --eval-every-decisions 2500000 --eval-games 512 --eval-seats 8 --eval-seed-base 420000 \
  --iterations 1000 --minutes 180 --snapshot-every 50 --keep-snapshots 3 \
  --out runs/az_entity_s3
```

> `--anchor-iterations 200` ≈ 30M 预算里的前 20%（1000 iter 的上限按实际 decisions 计）。

## 7. 预算与产出

- 预计 wall：**约 1.5–2 h**（30M decisions，collect 6.1 s / PPO 4.5 s 的流水线，含 12 次评测）；
- 产出：`runs/az_entity_s3/{history.jsonl, eval/, snapshots/, TRIGGER_library.json?}`；
- 触发条件：任意一次评测 mean rank ≤3.0 → 自动写 `TRIGGER_library.json`，届时按
  `docs/RECIPE_IDEAS_REVIEW.md` §2 的顺序开始镜像库保真工作。
