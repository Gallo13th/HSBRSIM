# AGENTS.md — HSbg Agent 协作指南（AI/人类开发者必读）

> 目标：把「炉石传说·酒馆战棋」做成可训练、可评估、可复现的智能体项目。
> 三层：**模拟引擎** → **强化学习环境** → **策略与训练**。

## 1. 仓库布局

```
C:\HSagent\
├── hsrl2/                 # 模拟引擎（vendored，机制精度权威；4164 项测试全绿）
│   ├── game.py            # Game：招募回合 / 配对 / 战斗 / 淘汰（5204 行）
│   ├── hero.py minion.py entity.py tags.py
│   ├── combat.py queue.py events.py pools.py db.py defs.py
│   ├── actions/           # 引擎 Action 原语
│   ├── scripts/           # 卡牌/英雄/饰品/异变效果脚本 + REGISTRY
│   └── tests/             # 引擎回归测试（禁止为了新功能改红）
├── data/                  # 引擎卡牌数据 JSON（S14 / patch 36.2.2 基线）
├── hsdata/CardDefs.xml    # 原始 CardDefs（数值唯一权威）
├── hsbg/                  # ★ 本项目新增代码
│   ├── env/               # RL 环境（spec 契约 / 观测 / 动作 / 对局循环 / 向量化）
│   ├── agents/            # 脚本对手 / 启发式教师
│   ├── policy/            # 实体 Transformer 策略 + 价值头
│   ├── train/             # BC / PPO 训练管线
│   ├── eval/              # 评测 / 锦标赛 / 基线
│   ├── bridge/            # 真实对局桥（Power.log 解析、数据资产）
│   └── paths.py
├── tests/                 # ★ 新增功能的测试（pytest）
├── scripts/               # 可执行入口（demo / train / evaluate）
├── docs/                  # 架构、环境契约、引擎 API、训练手册
├── tools/                 # 引擎自带审计/生成器（只读使用）
└── runs/                  # 训练产物（git 忽略）
```

**`hsrl2/` 是 vendored 引擎**：默认视为只读。确需修改时：
1. 先在 `hsrl2/tests/` 或 `tests/test_engine_fixes.py` 写失败测试；
2. 改动必须保持 `python -m pytest hsrl2/tests -q` 全绿；
3. 在 `docs/ENGINE_NOTES.md` 记录动机、规则依据、影响面；
4. 只有 Lead 批准才能改 `game.py` / `combat.py` / `queue.py` / `tags.py` 等核心文件。

规则权威文档在 `docs/reference_old/BATTLEGROUNDS_RULES.md`（113KB，旧项目遗留，
查规则时参考）；卡牌录入参考 `docs/reference_old/CARD_REGISTRATION_GUIDE.md`、
`docs/reference_old/MECHANICS_REFERENCE.md`。旧项目的 RL 文档（`RL_SYSTEM_GUIDE.md`、
`RL_ENVIRONMENT_AUDIT.md`）仅供参考，**不要**照搬其 v1 引擎接口。

## 2. 环境与命令（Windows，Python 3.13）

```powershell
cd C:\HSagent
python -m pytest hsrl2/tests -q          # 引擎回归（~28s，当前 4164 passed）
python -m pytest tests -q                # 本项目新增测试
python tools/smoke_random_games.py --games 8 --seed 2000   # 全对局压测
```

依赖：`numpy`、`torch`（CUDA 可用，RTX 4060 Ti 16GB）、`pytest`。
新增第三方依赖前先问 Lead。**禁止**引入 gym/stable-baselines3 作为硬依赖
（环境层提供 gymnasium 兼容外观即可，内部零依赖）。

## 3. 核心约定

- **语言**：代码注释/文档用中文；标识符用英文。
- **编码**：所有文件 UTF-8（`open(..., encoding="utf-8")`）；不要用系统默认编码。
- **确定性**：环境行为必须由 `seed` 完全决定（引擎 RNG = `game.rng`）。
  训练可复现性依赖这一点。
- **引擎随机**：`hsrl2` 内禁止 `import random`（走 `game.rng`）；新增代码同理。
- **PendingChoice 契约**：`game.pending_choices` 是队列；`choice.choose(i)`
  只结算**不出队**，必须由环境 `pop(0)`，否则重复结算（引擎文档 TEST_SOP §8）。
- **异常**：动作非法时引擎抛 `hsrl2.game.GameStateError`；环境层必须捕获并
  转为 `info["invalid"]=True`，不得让训练进程崩溃。
- **观测/动作**：以 `hsbg/env/spec.py` 为唯一契约；改字段 = 升 `version` 并同步
  `docs/ENV_SPEC.md`。
- **测试**：每个新模块必须有对应 `tests/test_*.py`；性能敏感路径加基准测试。
- **不要提交 `runs/`、`__pycache__`、模型权重**。

## 4. 并行开发与写权限（重要）

多个 agent 共享同一工作目录，**只写自己 scope 内的文件**：

| 角色 | 写范围 |
|------|--------|
| Lead | `hsbg/env/spec.py`、`hsbg/paths.py`、`docs/`、`tests/test_integration.py`、`scripts/`、根配置 |
| engine-analyst | `docs/ENGINE_API.md`、`docs/ENGINE_RL_READINESS.md`、`tools/probe_*.py` |
| env-builder | `hsbg/env/**`、`tests/test_env_*.py`、`hsbg/agents/**`、`tests/test_agents_*.py` |
| policy-builder | `hsbg/policy/**`、`hsbg/train/**`、`tests/test_policy_*.py`、`scripts/train_*.py` |
| bridge-analyst | `hsbg/bridge/**`、`tools/powerlog_*.py`、`tests/test_bridge_*.py`、`docs/REAL_GAME_BRIDGE.md` |

遇到必须跨 scope 修改的情况：先读文件、改最小片段，并在回复里明确告知 Lead。

## 5. 数据现状（已知缺口）

- 引擎卡池数据基线 **S14 / patch 36.2.2**；线上游戏为 **36.6.3**（见
  `docs/REAL_GAME_BRIDGE.md`）。新卡/数值差异属于已知问题，不阻塞 RL 管线；
  但**不要**把"数据旧"当成环境 bug 去改引擎。
- `data/` 是生成产物；更新应走 `tools/generate_bg_data.py` + `hsdata/CardDefs.xml`。

## 6. 验收门槛

任何改动合入前：
```powershell
python -m pytest hsrl2/tests -q      # 必须 0 failed
python -m pytest tests -q            # 必须 0 failed
python tools/smoke_random_games.py --games 4 --seed 7   # crashes=0
```
环境/策略层额外要求：
- 环境：同一 seed 两次 rollout 的观测/动作序列完全一致（确定性测试）。
- 策略：`forward` 对随机 batch 输出形状正确、masked softmax 不含 NaN；
  短 PPO 冒烟能跑通并保存/加载 checkpoint。
