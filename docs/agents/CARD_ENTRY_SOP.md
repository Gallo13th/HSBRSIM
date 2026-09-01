# SOP: 卡牌录入 (Card Entry)

> 适用: 把 data/*.json 中新补丁新增/改动的卡牌接入 hsrl2 引擎。
> 前置阅读: docs/REFACTOR_PLAN.md §2/§3。作业范围: 仅 `hsrl2/scripts/`。

## 0. 作业单格式

编排者派发的作业单形如:

```
录入以下 8 张 S14 新卡（来源 docs/S14_DIFF_REPORT.md "Pool Minions Added"）:
BG36_701, BG36_509, BG36_503, BG36_201, BG36_206, BG36_520, BG36_521, ...
```

## 1. 录入流程（每张卡）

### 1.1 读取权威数据

```python
from hsrl2.db import CardDB
db = CardDB.load("data")
d = db.get("BG36_701")
print(d.name, d.atk, d.health, d.tech_level, d.race,
      d.keywords, d.script_data_num_1, d.script_data_num_2, d.text)
```

**铁律**: 数值/参数只从 CardDef 取，禁止凭记忆/旧 wiki 硬编码。
历史教训: Goldrinn 文本 +{0}/+{1} 参数已是 +8/+8，旧实现硬编码 4/4 静默
过期 2 个版本。模板参数读法: `d.num(0)` = {0}，`d.num(1)` = {1}。

### 1.2 判断卡的类别

| 特征 | 归属文件 | 备注 |
|------|---------|------|
| 池随从 | `scripts/minions.py` | is_pool_minion=True |
| token（亡语召唤物等） | `scripts/minions.py` TOKEN 区 | 不入池、tech_level=1 |
| 池法术 | `scripts/spells.py` | is_pool_spell=True |
| 英雄/英雄技能 | `scripts/heroes.py` | 绑定 hero_power_id |
| 饰品 | `scripts/trinkets.py` | CardType.BACON_TRINKET |
| Dark Gift | `scripts/dark_gifts.py` | dark_gift=True（见 §3） |

### 1.3 判断是否需要脚本

- **纯白板/纯关键词**（无 text 或 text 只是关键词说明）→ 无需脚本类，
  引擎自动处理关键词（taunt/DS/windfury/poisonous/venomous/reborn/
  magnetic/cleave/stealth）
- **有触发效果**（Battlecry/Deathrattle/Start of Combat/Avenge/Rally/
  Activate/End of Turn/...）→ 需要 `EFFECT_SCRIPT_SOP.md` 流程
- 若数据缺关键词标志但文本明显有（如 "Also damages adjacent minions"
  而无 cleave 标志）→ 在录入代码中显式 `keywords += {"cleave"}`，并在
  注释中标注"文本兜底"

### 1.4 金色绑定

金色版本是 CardDefs 中的独立实体（`triple_upgrade_id` 指向 dbf id）。
`CardDB.golden_version(d)` 返回金色本体（自带数值/文本/参数）。
录入时:
- 检查金色版存在: `db.golden_version(d) is not None`
- **不要**手写"数值×2"——用金色本体定义
- 若金色本体缺失（个别老卡），作业结果中报告 `MISSING_GOLDEN: <card_id>`

### 1.5 注册到 registry

```python
# hsrl2/scripts/registry.py 中追加（或 minions.py 的 REGISTRY dict）
REGISTRY["BG36_701"] = KelpKeeperScript   # 见 EFFECT_SCRIPT_SOP
```

## 2. 完成校验（每张卡）

```bash
python -c "
from hsrl2.db import CardDB
db = CardDB.load('data')
d = db.get('<card_id>')
assert d is not None
# 金色链
g = db.golden_version(d)
print(f'{d.id}: {d.atk}/{d.health} T{d.tech_level} golden={g.id if g else None}')
"
```

## 3. S14 特殊录入注意

| 机制 | 数据特征 | 录入要点 |
|------|---------|---------|
| Activate | keywords 含 "activate"，activate_cost=N | 脚本需实现 `activate` 钩子；每回合约束由引擎处理 |
| Dark Gift | dark_gift=True（43 张 BG36_MidGameEffect_000t*） | 见 dark_gifts.py 专节；效果多为对宿主随从的持续附魔 |
| Lockbox | card_type=SPELL, unplayable=True | 手牌倒计时实体；脚本实现 `start_of_turn` 递减 |
| Fishbait | evolution_card_id 指向 BG36_205 | 生成逻辑在源卡脚本；Fishbait 本体是 1 血 token + 亡语给击杀者 +N/+N |
| Chromadrake | subsets 含 "dragon" 且非池 | 仅由生成效果出现——**不得**注册为可购池卡 |

## 4. 作业单返回格式

```
录入完成: <n>/<n>
- OK: BG36_701 Kelp Keeper（脚本: activate→trigger battlecry）
- OK: BG36_206 Snarky Shark（纯脚本: on_sell→refresh+fishbait）
- MISSING_GOLDEN: BGXX_XXX
- 需要引擎支持: <机制描述>（卡片列表）—— 未实现，等待主线
- AMBIGUOUS: BGXX_YYY（<歧义描述+候选解释>）—— 未实现
测试: <pytest 输出末行>
审计: <audit 输出末行>
```

## 5. 经验库（持续追加）

- 2026-08-21: `card_type=24` 等未知协议类型会被 CardDef 降级为 INVALID，
  不影响池过滤；遇到时无需处理
- 2026-08-21: 同一 card_id 在 bg_cards.json 与 bg_pool_minions.json 重复
  出现是预期的（全量目录+池子集），CardDB.register 幂等合并
- 2026-08-21: activate 的 `{0}` 模板参数与 tag 4090 (INTERACTABLE_OBJECT_COST)
  同值，取 activate_cost 字段即可
