# 数据（官方 37.0.0.255790）

## 基线

- 客户端/数据：**37.0.0.255790**（hsdata tag `255790`；`README.md` Version）。
- 原始数据只保留当前版本：`reversed/hsdata_255790/CardDefs.Bacon.xml`（5,787 BG 实体）。
- 只保留当前版本数据，不保留历史备份与旧轨迹。

## 两层产物

| 层 | 文件 | 用途 |
|---|---|---|
| 官方派生 | `data/bg_cards.json`、`bg_pool_minions.json`、`bg_pool_spells.json`、`bg_heroes.json`、`bg_hero_powers.json`、`bg_trinkets.json`、`bg_tavern_spells.json`、`bg_dark_gifts.json`、`bg_anomalies.json`、`bg_quest_rewards.json`、`bg_summary.json`、`pool_minion_texts.json`、`card_zhcn.json` | `tools/generate_bg_data.py` 从 CardDefs 生成 |
| AutoTavern schema | `data/p2/cards_37.json`、`MANIFEST.json`、`at_scripted_ids.json`、`new_cards_37.json` | `tools/p2_data/gen_carddb_37.py` 生成；Rust 引擎直接使用 |

**3983 = 3695 张 37 映射 + 288 张 36.6.3 compat**。compat 条目 `pools=[] / reachable=false`，
只为让 AutoTavern 的脚本 registry 能解析全部 card id（缺失会 panic）。

## 当前池计数

- 随从：**256**（原始池文件 252；Dark Paradox base 不入池、5 形态入池，另含 DRAGON/NAGA 双种族 `BG32_820`）
- 酒馆法术：**73**（全量 76 剔除 3 张 Duos-only）
- 英雄：118；饰品：236；tier7：12；timewarp：253；dark gift：47
- 主英雄技能 129 个中 9 个长尾缺失（Duos/旧替换技能；不阻塞 RL）

## 更新流程

```bash
# 1) 抓取最新 hsdata（示例：255790）
python tools/rea_fetch_hsdata.py --tag 255790

# 2) 用 CardDefs.Bacon.xml 生成官方派生数据（Bacon-only；BG 数据不需要 constructed 70MB）
python tools/generate_bg_data.py        # 读取 reversed/hsdata_<tag>/CardDefs.Bacon.xml

# 3) 生成 AutoTavern schema；需要上游 AutoTavern checkout
HSBRSIM_AT_ROOT=/path/to/AutoTavern python tools/p2_data/gen_carddb_37.py --out /tmp/p2_new
# 4) 校验后复制到 data/ 与 rust/.../data/cards.json，重建引擎
```

## 生成器

- `tools/generate_bg_data.py`：解析 `CardDefs.Bacon.xml`，导出 12 个 `bg_*.json`/文本表。
- `tools/p2_data/gen_carddb_37.py`（v1.2.0）：37 官方数据 → AutoTavern schema；T1 映射 / T2 36.6.3 继承 / T3 默认；compat 并集；`--check` 幂等。

## 约束

- 数值/文本以官方 CardDefs 为准；不要用旧中文快照覆盖英文权威。
- `data/p2/cards_37.json` 与 `rust/crates/hsbg-engine/data/cards.json` 必须 byte-identical。
- 跨数据版本时卡牌 embedding 下标不可复用；旧 checkpoint 需重训。
- TavernBench 的 36.6.3 states 不能加载到 37 引擎（卡表 fingerprint 会拒绝）。
