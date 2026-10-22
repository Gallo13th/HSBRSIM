# POLICY_OBS_V3 —— 策略/训练侧对观测 v3 的适配说明

> 范围：`hsbg/policy/**`、`hsbg/train/**`（含 checkpoint 兼容性）、
> `tests/test_policy_*.py`。观测契约的权威定义仍是 `hsbg/env/spec.py`
> （owner: env-auditor/Lead），本文只记录**策略侧如何消费**观测 v3。
> 更新日期：2026-10-23（task-7）。

## 1. 背景：观测 v2 → v3 的差异

env 8h 改动把 `Observation.version` 从 2 升到 3，与本任务相关的三点：

| 变更 | 影响策略侧 |
|------|-----------|
| `ActionKind` 追加 `MOVE_MINION`（第 12 个，索引 **12**；`NUM_ACTION_KINDS` 12→13） | 候选 `kind` one-hot 宽度 12→13，`cand_num` 特征维 **38→39**；`kind_emb` 行数 12→13 |
| `extra["pending_choice_options"]`：选择步每个 option 的结构化元数据 `{index, card_id, secondary_id, label, name, secondary_name, cost}`，`secondary_id` = Dark Gift 的 `gift_id` / 任务 offer 的 `reward_id` | 新增编码张量 `entity_secondary`；模型把第二 id 拼进 choice 实体表示 |
| `extra["env_stats"]["agent_choice_autoresolved"]` | 纯统计，策略侧暂不编码（无需改动） |

MOVE_MINION 候选字段约定（见 `spec.CandidateAction`）：

* `src_zone="board" / src_slot=i`：被移动的随从；
* `position`：目标槽位（0..len(board)-1）；当前 env 只枚举相邻交换（i ↔ i+1），
  多次交换可达任意排列；
* `tgt_zone/tgt_slot` 不用（-1）。

## 2. 编码器（`hsbg/policy/encoder.py`）

* `CAND_FEATURE_BLOCKS` 的 `kind` 块使用 **`NUM_ACTION_KINDS`（=13）动态宽度**，
  `CAND_NUM_DIM = 13 + 26 = 39`。`ACTION_KIND_INDEX` 只在末尾追加，既有 0..11
  索引不变；`Observation`/`CandidateAction.kind` 保持字符串，策略侧不做枚举硬编码。
* 新增张量（已加入 `ENCODED_KEYS`，随 `collate`/RolloutBuffer/BC 数据集自动流通）：

  | key | shape | 说明 |
  |-----|-------|------|
  | `entity_secondary` | int64 `[B, E]` | choice 区槽位的第二 id 词表下标；0 = 无 |

  对齐规则：`extra["pending_choice_options"][i]["secondary_id"]` ↔
  `pending_choice.options[i]` ↔ `ZONE_CHOICE` 区第 i 个实体槽位。
  `card_id`（主 id）仍走 `entity_card`；`secondary_id` 未知时编码为 `<UNK>=1`
  （保留"存在第二 id"信号），缺失/畸形 extra 一律降级为 0，不抛异常。
* `collect_card_ids()` 现在也收集 `secondary_id`，动态建词表时 gift_id/reward_id
  能进词表（`CardVocab.from_data_dir()` 本就会读 `bg_dark_gifts.json` /
  `bg_quest_rewards.json` 的 id）。
* `EncoderDims` 新增 `num_action_kinds`（写进 checkpoint，默认 13）。

## 3. 模型（`hsbg/policy/model.py`）

* `_encode_state`：实体输入额外加上 `card_emb(entity_secondary)`。第二 id 与主
  card_id 的取值域不相交（gift/reward id 不会作为实体主 id 出现），因此**复用
  同一张 card embedding 表**、不新增参数、不改旧 state_dict 结构；0 号 padding
  行为零向量，缺失该 key 的旧 batch 等价于"无第二 id"。
* 其余结构（Transformer/候选打分/名次分布头）不变；`kind_emb` 行数与
  `cand_num_mlp` 输入维由 `PolicyConfig`（`num_action_kinds` / `cand_num_dim`）
  驱动，观测 v3 下自动为 13/39。

## 4. checkpoint 兼容性（重点）

新 checkpoint 格式版本 `CHECKPOINT_FORMAT_VERSION = 2`，payload 额外写
`obs_version=3`、`num_action_kinds=13`、`encoder_dims.num_action_kinds`。

旧（观测 v2 时代）checkpoint 的 `kind_emb` 只有 12 行、`cand_num_mlp` 输入只有
38 维；**直接按旧配置加载会静默把 `MOVE_MINION` 当成 `CHOOSE`、one-hot 列错位**。
因此加载路径做了显式兼容处理，由 `EntityTransformerPolicy.load(..., allow_legacy=...)`
控制：

| `allow_legacy` | 行为 | 适用场景 |
|---|---|---|
| `None`（默认） | **自动内存迁移 + `UserWarning`**（警告含原因、迁移规则与迁移命令） | 旧产物（`runs/bc/official_320/...`）继续评测/续训；不静默 |
| `False` | 抛 `CheckpointCompatibilityError`（含完整迁移说明） | 新训练/CI 严格入口，避免误用旧权重 |
| `True` | 静默内存迁移（不落盘） | 显式迁移流程（`migrate_legacy_checkpoint`）内部使用 |

默认警告示例（每次加载旧 ckpt 都会出现一次）::

    UserWarning: runs/bc/official_320/policy_bc.pt 是旧观测（v2）时代的策略 checkpoint，
    已自动做内存迁移后加载（不落盘）：format_version=1（当前 2）；缺少 obs_version ...
    迁移规则：kind_emb 新增 MOVE_MINION 行=旧行均值、cand_num_mlp 新 kind 列权重=0 ...
    详见 docs/POLICY_OBS_V3.md；严格报错用 allow_legacy=False，落盘迁移用
    migrate_legacy_checkpoint()。

严格模式报错示例::

    hsbg.policy.model.CheckpointCompatibilityError:
      <path> 是旧观测（v2）时代的策略 checkpoint，与当前观测 v3 不兼容：
        - format_version=1（当前 2）
        - 缺少 obs_version 字段（观测 v2 时代保存的 ckpt）
        - policy_config.num_action_kinds=12（当前 13：观测 v3 新增 MOVE_MINION）
        - policy_config.cand_num_dim=38（当前 39：kind one-hot 12→13）
      ... 迁移命令 ...


### 迁移方式（任选其一）

```powershell
# 1) 推荐：用观测 v3 重新训练 / 从 BC 初始化续训
python scripts/train_ppo.py --env mock --total-steps 1000 --out runs/ppo_v3_smoke

# 2) 落盘迁移旧权重（生成 <name>_obs_v3.pt，之后可正常加载）
python -c "from hsbg.policy.model import migrate_legacy_checkpoint as m; print(m('runs/ppo/official_v3/policy_final.pt', 'runs/ppo/official_v3/policy_obs_v3.pt'))"

# 3) 内存迁移（脚本内临时用，不落盘）
from hsbg.policy.model import load_policy_and_encoder
policy, encoder = load_policy_and_encoder(old_path, allow_legacy=True)  # 静默
policy, encoder = load_policy_and_encoder(old_path, allow_legacy=False)  # 严格报错
```

迁移规则（`_migrate_legacy_payload`）：

* `kind_emb.weight`：`[12, d] → [13, d]`，前 12 行原样保留，新增行 = 旧行均值
  （尺度一致，初始行为接近"平均动作"，避免随机行导致 move 候选 logit 偏置）；
* `cand_num_mlp.0.weight`：`[d, 38] → [d, 39]`——前 12 列（旧 kind one-hot）
  原样保留；第 13 列（MOVE_MINION 新列）权重置 0；后 26 列特征原样右移 1 位；
* 其余参数原样加载；结构差异不止"kind 12→13"时**拒绝迁移**并提示重训；
* 迁移后的 `meta.legacy_migration` 记录来源/维度/注意事项；`meta.legacy_migrated=True`。

### 兼容性结论

| 场景 | 结论 |
|------|------|
| 旧 obs v2 ckpt 默认加载 | ⚠️ 自动内存迁移 + `UserWarning`（显式提示 MOVE_MINION 未训练），可正常推理/续训 |
| 旧 obs v2 ckpt + `allow_legacy=False` | ❌ 抛 `CheckpointCompatibilityError`（含迁移说明） |
| 旧 ckpt + `allow_legacy=True` / `migrate_legacy_checkpoint()` | ✅ 静默迁移；除 MOVE_MINION 外权重保留 |
| 迁移后策略的 MOVE_MINION 能力 | ⚠️ 未训练（新 kind 列=0、embedding=旧均值），需继续训练 |
| 旧 BC 数据集（`bc_dataset.pkl`，存原始 `Observation`） | ✅ 兼容：重新 `encoded()` 时自动带 v3 字段 |
| 旧 PPO rollout buffer | ✅ 不持久化，无兼容问题 |
| 新 ckpt（format 2 / obs 3） | ✅ 默认加载 |
| 未来更高 obs_version 的 ckpt | ❌ 显式拒绝（不支持降级加载） |

> 说明：`hsbg/search`、`hsbg/rl`、各 eval 脚本里默认加载的旧 ckpt
> （`runs/bc/official_320/policy_bc.pt` 等）走默认分支即可继续工作，但会打印
> 迁移警告；需要"零警告"时先 `migrate_legacy_checkpoint()` 生成 v3 文件并以
> 新路径替换（`runs/` 不入库，需在新机器上重新迁移）。

## 5. 测试

```powershell
python -m pytest tests/test_policy_obs_v3.py -q   # 本任务新增（19 项）
python -m pytest tests/test_policy_* tests/test_rl_gym.py -q
python -m pytest tests -q                          # 全量门禁
```

`tests/test_policy_obs_v3.py` 覆盖：13 kind/索引稳定、MOVE_MINION one-hot/
position/src 编码、含 move 候选 batch 的 forward/采样、secondary_id 编码与模型
消费、未知/畸形 extra 不崩、旧 ckpt 默认迁移+警告 / 严格模式报错 / 落盘迁移、
未来 obs 版本拒绝。另外 `tests/test_policy_encoder.py`/`test_policy_model.py`/
`test_policy_ppo.py` 等既有测试随 `ENCODED_KEYS` 自动覆盖新张量。

## 6. 剩余风险 / 待办

1. **MOVE_MINION 策略能力缺失**：当前没有针对走位的 BC 数据/奖励塑形；迁移
   ckpt 只会把 move 当"低分候选"，需要后续 SFT/PPO 数据才能学会走位。
2. **secondary_id 覆盖率**：只有 `data/*.json` 收录或真实观测出现过的 gift/
   reward id 能进词表；离线数据若用旧 `CardVocab` 且不刷新，Dark Gift 身份会
   退化成 `<UNK>`（同一向量）。训练新数据前建议用 `CardVocab.from_data_dir()`
   + `collect_card_ids()` 重建/扩充词表。
3. **label/文本未编码**：当前只编码结构性 id（secondary_id），`label` 文本
   （引擎目前为空）不进入模型；后续若引擎提供选项文字，需要另加文本特征。
4. **`env_stats` 未编码**：`agent_choice_autoresolved` 等统计只用于日志/审计，
   暂未作为全局特征（避免现有 checkpoint 维度再变）。
5. **迁移 ckpt 的数值偏差**：新 kind 列=0 + 旧均值 embedding 只是保守初始化，
   与从零重训的分布不同，评测时不要与 v2 结果直接比较。
