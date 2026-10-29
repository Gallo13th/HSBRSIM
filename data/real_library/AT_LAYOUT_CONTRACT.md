# AT 数据/动作布局契约

> AT = AutoTavern / TavernGym。当前 HSBRSIM 直接 fork TavernGym 引擎；本文件记录
> **数据布局与动作序列的硬契约**，防止换机器/改模型时静默漂移。

## 1. 观测布局

AT `crates/taverngym/src/obs.rs` 与 HSBRSIM `hsbg/env/obs_std.py` / `hsbg_engine`：
`layout()` 返回：

```text
OBS_FLOATS = 3227
OBS_CARDS  = 124
N_SHOP=8 N_BOARD=7 N_HAND=10 N_CHOICE=16 N_POS=8 N_OPP=7
PENDING_KINDS=9
MINION_F=31 ITEM_F=40 GLOBAL_F=53 QUEST_F=2 OPP_F=9
```

测试：`tests/test_at_layout_contract.py`。

## 2. 动作布局（必须逐 index 一致）

```text
0 EndTurn
1 Refresh
2 Freeze
3 Upgrade
4..6 HeroPower(0..1)   # N_POWERS=2; 6 是 DarkGift
6 DarkGift          # 注意：HeroPower 区是 4..5，6 是 DarkGift
7 Cancel
8..16 Buy(0..8)     # 8 个 shop slot
16..23 Sell(0..7)
23..30 Activate(0..7)
30..46 Choose(0..16)
46..126 Play(hand 0..10, pos 0..8)
126..196 Magnetize(hand 0..10, board 0..7)
196..245 Move(from 0..7, to 0..7)
N_ACTIONS = 245
```

边界：

```text
A_END=0 A_REFRESH=1 A_FREEZE=2 A_UPGRADE=3
A_HERO_POWER=4 A_DARK_GIFT=6 A_CANCEL=7
A_BUY=8 A_SELL=16 A_ACTIVATE=23 A_CHOOSE=30
A_PLAY=46 A_MAGNETIZE=126 A_MOVE=196
```

HSBRSIM 的 `SEG` / pointer head 必须使用同一组 index；`tests/test_at_layout_contract.py`
用 `hsbg_engine.layout()/action_name()` 校验代表动作。

## 3. 模型 token 与 AT 数据的关系

- `entity`（49 token）：1 global + 7 board + 10 hand + 8 shop + **16 choices** + 7 opp；
- `entity18m`（57 token = 1 global + 56 entity）：在上述 49 基础上增加
  **8 个 pending-context token**，由 `global + pending one-hot` 派生；
- 动作候选仍是 **245**，pointer head 的 action index/段完全不变；
- 57 token 是对齐 paper 的 **56+1 结构补位**，不是新增 8 个真实 AT 观测槽位。

因此：

- **AT 数据/动作布局：已对齐，并由测试锁定**；
- **模型 token 数：entity18m 为 57，但 8 个是派生补位**；
- 不能声称“AT 原始 obs 有 56 个 entity token”；AT engine 的 `N_CHOICE` 是 16。

## 4. 进程级 actor pool（原型）

`hsbg/az/train/process_pool.py`：

- multiprocessing spawn；
- 每个进程独立 model/evaluator/Game；
- 进程绑定 GPU（`torch.cuda.set_device`）；
- 返回 records/meta，由 learner 组 PPO batch；
- 不是完整 topology A（没有共享 inference server），但避开单进程 GIL。

`scripts/bench_process_pool.py`：

```bash
CUDA_VISIBLE_DEVICES=0,1,2,3 python scripts/bench_process_pool.py \
  --checkpoint /tmp/entity18m_random.pt \
  --processes 4 --gpus 0,1,2,3 --games 64 --sims 4 \
  --minutes 30 --out runs/bench/process_4gpu_30min.json
```

记录每轮 decisions/s、GPU util/显存、illegal/truncated。

## 5. 换机器检查

1. `hsbg_engine.layout()` 必须等于上面的常量；
2. `action_name` 边界必须一致；
3. `entity18m` 参数 17,982,654、token 57；
4. checkpoint meta.arch 必须是 `entity` 或 `entity18m`；
5. 任何改 `N_CHOICE/N_POS/N_ACTIONS` 的提交必须同步改 AT 引擎、数据、本测试。
