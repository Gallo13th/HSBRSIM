# TavernArena 在线竞技场接入

> 目标：用本仓库训练出的 checkpoint，在 TavernArena（`https://rizling.top`）的在线环境里做评估。
> 模型完全本地推理，**只上传动作**；密钥只从环境变量 `ARENA_API_KEY` 读取，绝不入库。

## 0. 一次跑通（TL;DR）

```bash
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM

# 1) 竞技场契约自检（不需要密钥，不入队）
PYTHONPATH=rust/python:.:scripts $P scripts/arena_client.py \
  --url https://rizling.top --check --policy arena_agent:act \
  --expected-ruleset tg36-bc45cfc55a0e5cd6c14c \
  --catalog-sha256 c4c42e6ce5060e1b79fbcd5f4edbf6d17495f0f52690072481d690610f7ef6d7

# 2) 练习（不计分，立即开局）
ARENA_API_KEY=... PYTHONPATH=rust/python:.:scripts $P scripts/arena_client.py \
  --url https://rizling.top --mode practice --policy arena_agent:act --games 10 \
  --catalog-sha256 c4c42e6ce5060e1b79fbcd5f4edbf6d17495f0f52690072481d690610f7ef6d7 \
  --expected-ruleset tg36-bc45cfc55a0e5cd6c14c --model-version "hsbrsim-kl30m"

# 3) 计分（arena：60s 起步倒计时，规则机器人补位；满 5 场才上 bots 榜）
ARENA_API_KEY=... PYTHONPATH=rust/python:.:scripts $P scripts/arena_client.py \
  --url https://rizling.top --mode arena --policy arena_agent:act --games 5 \
  --catalog-sha256 c4c42e6ce5060e1b79fbcd5f4edbf6d17495f0f52690072481d690610f7ef6d7 \
  --expected-ruleset tg36-bc45cfc55a0e5cd6c14c --model-version "hsbrsim-kl30m"
```

密钥获取与轮换在网页 `/lobby` 登录后操作；**不要**写进 Git、命令行参数、日志或 URL。

## 1. 组件

| 文件 | 作用 |
|---|---|
| `scripts/arena_client.py` | 竞技场官方连接器（`/downloads/client.py`，vendored 未改）。HTTP + 重试 + 幂等 request_id + 心跳 |
| `scripts/arena_agent.py` | 本地策略 `act(observation, context)`：加载 checkpoint → v2 观测取 v1 前缀 → 卡牌下标重映射 → masked argmax |
| `scripts/build_arena_card_map.py` | 生成 `runs/arena/card_map.json`（竞技场卡牌 index → 我们 obs 值） |

## 2. 跨版本适配（关键，别忽略）

竞技场：公开 TavernGym **1.1.0 / 36.6.3**，观测 v2 = `features[4017] + cards[447] + mask[245]`；
本仓库：fork 的 `hsbg_engine` / **37.0.0.255790**，观测 3227 + 124。

协议明确 **v1 的 3227/124 是 v2 的前缀**，所以适配器只做三件事：

1. `features[:3227]`、`cards[:124]`、`mask`（245，动作空间与布局常量完全一致）；
2. 卡牌下标映射：竞技场 catalog 的 `index→id` 对照我们 `cards.json` 的 `id→index`；
   实测竞技场 3,983 张卡的 id **100%** 出现在我们的数据里，映射覆盖 3,983/3,983；
3. 未识别卡 → 0（空槽）。

**这是零样本跨版本评估**：词表 id 对得上，但数值/机制来自 36.6.3，模型训练在 37.0.0，
部分失误应归因于此，不要当成模型能力上限。

## 3. 信息边界（按竞技场协议）

- 模型只拿标准 TavernGym 自己席位的**正常可见观测**（含对手公开信息与已见阵容）；
- 没有观战、对手隐藏状态、操作历史、回放接口；公开接口只给已结束对局的最终阵容与名次；
- 服务器无法证明本地权重未被更换，登记身份为人格担保（`model_version` 只是公开标签）。

## 4. 结果记录（每次跑完追加）

| 日期 | 模型 | 模式 | 局数 | 名次分布 | 备注 |
|---|---|---|---:|---|---|
| 2026-10-28 | `runs/az_entity_kl_30m/model_30m.pt`（30M stage-1） | practice | 1 | 2nd | 首次接入，14 turns / 41.6 s |
| 2026-10-28 | 同上 | practice | 10 | `[5,1,2,1,5,3,4,5,5,4]` → **mean 3.50 / top4 60% / first 20%** | 每局 58 s，7 个规则机器人 |
| 2026-10-28 | 同上 | arena（计分） | 5 | 见 `/tmp/arena_ranked5.log` | 60 s 队列倒计时 + 机器人补位 |

## 5. 已知限制 / 下一步

1. 连接器与 agent 都是**单进程同步**，一局一局跑；批量评估要循环 `--games N`；
2. GPU 只在本地做一次前向（~1–3 ms/决策），瓶颈是回合计时与机器人补位；
3. 计分榜（`bots` 榜）需要 **满 5 场有效对局** 才显示正式排名；练习/约战不计分；
4. 若要做「和真人对战」的评估，用 `--mode standard`（严格 8 个账号，无机器人补位）或
   `--mode arena --wait-for-human`（至少 1 个真人账号，其余仍可补机器人）；
5. 跨版本失配的根治办法：把我们引擎升到 36.6.3 的数据重建模型，或按竞技场 patch 重训。
