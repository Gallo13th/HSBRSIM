# 37.0.0 内容移植计划（P2-C）

> **任务**：量化「AutoTavern / TavernGym 1.0.0 内容脚本（客户端 36.6.3.253932）→
> HSBRSIM 官方数据 37.0.0.255130」的移植缺口，产出可执行分批计划；并给出
> 「游戏内支持但两引擎都未实现」的操作清单（动作空间 245+ 扩展依据）。
>
> **输入**（全部只读）：上游 `/Users/letiangao/HSAgent/repos/AutoTavern`
> （commit `fb61201`，MIT，36.6.3）；HSBRSIM `data/bg_*.json`（37.0.0.255130）、
> `hsrl2/scripts/**`（37.x Python 参考实现）、`docs/LIVE_TO_SIM_GAP.md`、
> `docs/AUDIT_ENGINE_MECHANICS.md`、`docs/AUTOTAVERN_P2_KICKOFF.md`。
>
> **产物**：`tools/p2_delta/`（可复现脚本）、`runs/p2_delta/`（覆盖矩阵 JSON +
> markdown 摘要，gitignore）。本文所有数字均由脚本产出，复现命令见 §9。

---

## 0. 结论先行（TL;DR）

1. **内容缺口远小于预期**：AT 36.6.3 的内容脚本（**1301 个 card id**，58 个 `.rs`
   文件）对 37.0.0 **池内随从覆盖率 258/273（94.5%）**；池内只缺 **15 张**（14 张
   Naga + 1 张全类型），其中 **13 张有 hsrl2 Python 参考实现**。
   37.0.0 相对 36.6.3 **没有新增可玩卡 id**（新增 id 122 个 = 异变定义 108 +
   UI 按钮/token 14）；版本差异主要是**Naga 种族回池**、池子轮换与少量文本/数值微调。
2. **“37.0.0 可用”的最小内容集合 = 18 张卡**（严格去重，全部 M 级难度）：
   池内随从 15 + 主英雄技能 1（Azshara）+ 池内酒馆法术 2（剔除 3 张 Duos 伪影）；
   T7 唯一缺口 `BG27_514` 已含在池内随从里（不重复计）；黑暗赠礼 47/47 已被
   AT 覆盖，无需移植。
3. **饰品是最大内容缺口**：409 个定义中 AT 覆盖 248 → 缺 161（37 新增 BG36 饰品
   缺 8 张；hsrl2 可提供池口径缺 138 张）；**37 数据没有轮换池标志**，需先人工
   triage 再排期（§4.4）。
4. **37.0.0 的系统支持**：饰品、黑暗赠礼、Deity、Aberration 种族、Discard 在 AT
   36.6.3 引擎**都有原语**；Timewarp 253 张 37 数据全在、AT 已实现 253/253
   （按 config 开关，零脚本移植）；**异变（Anomaly）是 AT 唯一完全缺失的系统**
   （108 条历史定义、0 张 37 新增，无证据表明 37.0.0 轮换启用 → 不阻塞 P1）。
5. **操作缺口只有 3 项**（其余 14 项核对均已被 AT 覆盖，见 §6）：
   * **单槽位冻结/解冻**（真实游戏可按单个酒馆随从操作；两引擎都只有整馆 toggle）
     → 建议扩展动作 **266..273**；
   * **第 3+ 英雄技能槽可用**（AT 引擎内部支持任意 slot，动作空间只编码 0..1）
     → 已在 std profile 预留 **246..249**；
   * **异变系统**（AT 无系统；是否需要动作取决于是否启用异变，建议不新增动作）。
   动作空间 245..265 已被 P2-D std profile 占用（Unfreeze/技能槽/选项槽），
   故新增编号从 **266** 起，总动作数 274。
6. **工作量（估算，标注口径见 §8）**：P1 = 18 卡 ≈ **3.5–7 人天** + 数据管线
   1–2 人天 + 验收 1–2 人天 ≈ **5.5–11 人天**；P2 饰品/法术 ≈ **15–45 人天**；
   P3 任务/异变/长尾 ≈ **50–95 人天**（取决于是否启用异变）。

---

## 1. 输入、工具与产物

### 1.1 工具（可复现，只读）

```bash
# 一键复现（约 3s）；产物写入 runs/p2_delta/（gitignore）
python3 tools/p2_delta/run_all.py

# 分步
python3 tools/p2_delta/extract_at_content.py   # AT content 注册表 -> at_content.json
python3 tools/p2_delta/compare_37.py           # 覆盖矩阵 -> coverage_matrix.json / summary.md
python3 tools/p2_delta/probe_ops.py            # 操作探针 -> ops_probe.json
```

| 产物 | 用途 |
| --- | --- |
| `runs/p2_delta/coverage_matrix.json` | **唯一事实来源**：分 kind 覆盖/缺失/变更/难度/P1/池子变化 |
| `runs/p2_delta/summary.md` | 覆盖矩阵的 markdown 摘要（本文表格的生成源） |
| `runs/p2_delta/missing_pool_minions.md` | 池内缺失随从 15 张逐条表（可直接派工） |
| `runs/p2_delta/ops_probe.json` | 17 项操作核对：两侧源码 file:line + 37 卡面证据 |
| `tools/p2_delta/README.md` | 工具与口径说明 |

### 1.2 抽取正确性校验

`extract_at_content.py` 复刻上游 `crates/taverngym/examples/content_report.rs` 的口径，
并与上游 `repos/AutoTavern/docs/CONTENT.md` 的表头数字**逐项交叉校验（7/7 一致，脚本输出
`cross_check_content_md.status = "match"`）**：

| 类别（AT 口径） | 重算值 | CONTENT.md |
| --- | ---: | ---: |
| 池内随从（含纯关键词） | 244（239 scripted） | 244（239 scripted） |
| 英雄（主技能已实现） | 116 / 116 | 116 / 116 |
| 酒馆法术 | 70 / 70 | 70 / 70 |
| 饰品（36.6.3 轮换池） | 236 / 236 | 236 / 236 |
| 黑暗赠礼 | 47 / 47 | 47 / 47 |
| Timewarp（含金色） | 253 / 253 | 253 / 253 |
| Tier 7 | 12 / 12 | 12 / 12 |

AT content 共 **58 个 `.rs` 文件 / 1301 个注册 card id**（54 个模块有 `scripts()`
或 `scripts_p1()`，4 个 helper 模块无注册表：helpful/timewarp/trinket_offers/yogg）。
`all_scripts()` 拼接顺序由 `mod.rs` 静态解析校验，无未知/重复 id。

---

## 2. 口径与数据限制（必须与数字一起读）

### 2.1 AT 侧“已实现”

* **scripted**：`content/*.rs` 的 `scripts()` 注册表命中 card id（1301 个）；
* **keyword-only**：卡面去关键词（Divine Shield/Taunt/Reborn/Windfury/Venomous/
  Stealth/Magnetic）与标点后为空（复刻上游 `script.rs::implemented_uncached`）；
* 金色/变体沿 AT `cards.json` 的 `normal` 链解析到本体脚本（与上游 `registry()` 一致）。

### 2.2 37 侧“现有卡/池”

一律用数据标志，不按 id 前缀猜：

| kind | 37 集合 | 数量 |
| --- | --- | ---: |
| 池内随从 | `data/bg_pool_minions.json`（`is_pool_minion`，含 T7 13 张） | 273 |
| 池内酒馆法术 | `data/bg_pool_spells.json`（`is_pool_spell`） | 76 |
| 酒馆法术全量 | `data/bg_tavern_spells.json`（card_type 42，含 token） | 205 |
| 英雄 | `data/bg_heroes.json` | 118 |
| 英雄技能 | `data/bg_hero_powers.json`（含变体） | 165 |
| 饰品 | `data/bg_trinkets.json` | 409 |
| 任务奖励 | `data/bg_quest_rewards.json` | 73 |
| 黑暗赠礼 | `data/bg_dark_gifts.json` | 47 |
| 异变 | `data/bg_anomalies.json` | 108 |
| 任务卡 | `hsrl2.game.is_quest_card` 同源谓词 | 20 |
| 伙伴（非池） | `bg_cards` 中 `_Buddy` 本体 | 127 |
| Timewarp | 37 数据中存在的 AT Timewarp 池卡（37 无池标志） | 253 |

### 2.3 卡面文本对拍口径（跨版本 changed 判定的关键）

37 数据 `text` 与 AT 数据的书写方式不同，直接比较会产生大量假阳性。本工具做了
以下**确定性归一**（实现见 `tools/p2_delta/common.py`）：

1. **`@` 有两种含义**（37 CardDefs 原始文本）：
   * *动态数值占位符*：前后两段是同一句话被数字切开（如 `(...@ Gold left!)`、
     `Discover a Tier @ minion`）→ 拼回文本，`@` 记作 `#`；
   * *Duos 文本变体分隔符*：`@` 后是第二段完整文本（**仅 5 个 37 新卡**带
     “or Pass” 变体）；判别规则 = 两段词集 Jaccard ≥ 0.5 视为变体、取第一段。
2. `{0}..{4}` → `script_data_num_1..5` 还原成实际数字；**无法还原**的卡进
   `unverified_cards`（单独列“无法对拍”），不冒充 changed。
3. 忽略：HTML 标记、`[x]`、换行、`_` 分词下划线、动态计数器 `(N left!)`、
   复数标记 `|4(sing, plur)`（对两种展开分别匹配）、`left- most` 断词。
4. **cost 不比较随从**：AT 数据约定 BG 池内随从 `cost=0`（购买价固定 3 金），
   37 数据 `cost=3`；只有酒馆法术/饰品/任务奖励等比较 cost。

### 2.4 37 数据管线的 4 个注意点（交接给 P2-B/P2-F）

1. **文本 `@` 必须拆分**：`data/p2/cards_37.json` 若把 37 原始 `text` 直接拷进
   AT schema，脚本/`implemented()`/`shown` 会读到 Duos 变体段（当前仅 5 张卡，
   如 `BG36_100` 第二段多出 “or Pass”）。建议生成器：`text = split('@')[0]`，
   动态占位符按 `#` 保留并另存原始两段。
2. **Duos-only 卡混入单人池**：`bg_pool_spells` 含 `BG31_242 Bargain Bundle` /
   `BG31_243 Portal in a Fountain` / `BG31_244 Portal in a Crystal`（文本含
   “teammate / Pass”），单人池应剔除（详见 §4.5、§6 OPS-12）。
3. **UI 按钮/token**：37 数据新增 14 个 `TB_BaconShop*_Button/BG22_BuddyMeter/
   BG36_Button_DarkGift` 等 UI token，不应进卡池（AT `cards.json` 不导出）。
4. **compat 条目**：AT 内容脚本引用的 1301 个 id 中 **1300 个在 37 数据中存在**，
   只有 `BG_OG_044 Fandral Staghelm`（AT `naga.rs` 脚本）在 37 数据缺失 →
   `cards_37.json` 需为其生成 compat 条目（`pools=[]`、`reachable=false`），
   保证上游 `script.rs::registry()` 的 `db().id()` 断言不 panic。

**与 P2-B 产物的交叉校验（2026-10-26 实测）**：`data/p2/cards_37.json` 已生成
（3983 = 3695 mapped + 288 compat），用本工具复算：

```bash
python3 - <<'PY'
import json
d=json.load(open('data/p2/cards_37.json',encoding='utf-8'))
ids={c['id'] for c in d['cards']}
at=json.load(open('runs/p2_delta/at_content.json',encoding='utf-8'))
print('cards:', len(ids), '| AT registry missing:', sorted(set(at['registry'])-ids))
print('BG_OG_044:', 'BG_OG_044' in ids)
print('text 仍含 @:', [c['id'] for c in d['cards'] if '@' in (c.get('text') or '')])
PY
```

结果：**AT registry 1301 个 id 全部可解析（0 missing）**、`BG_OG_044` 已有 compat
条目、`text` 已拆出 `text_alt`（仅 `JAIL_800hp2` 残留 1 例 `@`）。
**遗留 1 项**：`BG31_242/243/244` 三张 Duos-only 法术仍标 `pools=['spell']`、
`reachable=true` → 需在 `tools/p2_data/gen_carddb_37.py` 的池映射里剔除
（单人池应为 73 张而非 76）。

### 2.5 难度分级（S/M/L，确定性规则）

| 级别 | 规则（`compare_37.py::classify_difficulty`） |
| --- | --- |
| **S** | 纯关键词/白板：卡面去关键词后为空；或只有静态光环且无触发 hook |
| **M** | 单一触发 hook（战吼/亡语/Rally/Avenge/Start of Combat/EoT/SoT/出售/Activate/Spellcraft/Choose One/…） |
| **L** | ≥2 个触发 hook（跨阶段复合），或命中「AT 无对应原语」系统词 |

> 难度是**可复算的文本/数据标签**，用于排序；不是人天。人天估算见 §8，且明确标注。

---

## 3. 覆盖统计（AT 已实现 vs 37.0.0 现有）

### 3.1 分 kind 总表

> 数据源：`runs/p2_delta/coverage_matrix.json` → `summary`。`extra` = AT 实现但
> 不在 37 该 kind 集合中的 id（多为轮换出池/令牌/Duos，见 §3.4）。

| kind | 定义 | AT 已实现 | 37 总数 | AT 覆盖 | **缺失** | extra | changed | 37 新增 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `pool_minions` | 池内随从（含 T7） | 244 | 273 | 258 | **15** | 5 | 0 | 0 |
| `heroes` | 英雄（主技能已实现） | 116 | 118 | 117 | **1** | 0 | 0 | 0 |
| `hero_powers` | 英雄技能定义（165，含变体） | 123 | 165 | 123 | **42** | 11 | 1 | 0 |
| `hero_main_power` | 118 位英雄的主技能 | 116 | 118 | 117 | **1** | 0 | 0 | 0 |
| `pool_spells` | 当前池内酒馆法术 | 70 | 76 | 71 | **5**（实际 2） | 0 | 0 | 0 |
| `tavern_spells_all` | 酒馆法术全量（含 token） | 111 | 205 | 111 | **94** | 3 | 1 | 0 |
| `trinkets` | 饰品定义 | 248 | 409 | 248 | **161** | 0 | 0 | 0 |
| `quest_rewards` | 任务奖励 | 71 | 73 | 71 | **2** | 0 | 1 | 0 |
| `dark_gifts` | 黑暗赠礼 | **47** | 47 | **47** | **0** | 0 | 0 | 0 |
| `anomalies` | 异变 | 0 | 108 | 0 | **108** | 0 | 0 | 108 |
| `tier7` | 池内 T7 随从 | 12 | 13 | 12 | **1** | 0 | 0 | 0 |
| `buddies` | 伙伴（非池） | 109 | 127 | 109 | **18** | 5 | 1 | 1 |
| `quests` | 任务卡 | 20 | 20 | 19 | **1** | 4 | 0 | 0 |
| `timewarp` | Timewarp（37 数据存在的 AT 池卡） | **253** | 253 | **253** | **0** | 0 | 2 | 0 |

**关键读数**：

* 池内随从覆盖 **258/273 = 94.5%**；池内法术覆盖 71/76（其中 3 张是 Duos 伪影，
  实际覆盖 **71/73 = 97.3%**）。
* 黑暗赠礼 **47/47 全覆盖**；Timewarp **253/253 全覆盖**（AT 系统即插即用）。
* 42 个缺失英雄技能定义里**只有 1 个是 37 主技能**（Azshara），其余 41 个是
  替换/变体技能（不影响“37 可用”）。
* 异变 108 全缺（AT 无系统），但 37 无新增异变卡（见 §7）。

### 3.2 饰品的两个口径

| 口径 | 37 侧 | AT 覆盖 | 缺口 |
| --- | ---: | ---: | ---: |
| 全部饰品定义 | 409 | 248 | **161** |
| 商店可提供（hsrl2 `db.trinket_offer_pool()` 口径） | 357 | 219 | **138** |
| 37.0.0 新增（BG36 前缀） | 77（其中 AT 覆盖 69） | 69 | **8** |

> **限制**：37 数据只导出 `trinket: bool`，**不导出“当前轮换池”**；AT 的
> `cards.json` 有 `pools.trinket`（36.6.3 的 236 张轮换池）。因此 138 是“上界”，
> 需按 37 轮换 triage（P2 第一步）。

### 3.3 共享卡文本/数值变化（需改 AT 脚本的清单）

两版本都存在、AT 已实现、且数据确有差异的卡**只有 6 条（changed=6，全部为文本书写
差异，无 tier/atk/hp 变化）**：

| # | kind | Card ID | 变化类型 | 详情 | 需改 AT 脚本？ |
| ---: | --- | --- | --- | --- | --- |
| 1 | hero_powers | `BG23_HERO_201p` | text_changed | AT “summon a 2/2 Tentacle” ↔ 37 “summon a `#/@` Tentacle”（数值由数据/动态值给出） | 否（脚本本来按 `num()` 读） |
| 2 | tavern_spells_all | `EBG_Spell_014` | text_changed | AT 只有 “+4 Attack”；37 `@` 第二段为 “+{0}/{1}” 变体 | 否（取第一段实现） |
| 3 | quest_rewards | `BG28_Reward_505` | text_changed | AT “+1/+1” ↔ 37 “+@/+@”（动态值） | 否 |
| 4 | buddies | `TB_BaconShop_HERO_49_Buddy` | wording_changed | AT “(0 left!)” ↔ 37 “({0} left!)”（显示计数器） | 否（显示态） |
| 5 | timewarp | `BG34_Giant_201` | wording_changed | AT “(0 left!)” ↔ 37 “({0} left!)” | 否（显示态） |
| 6 | timewarp | `BG34_Giant_201_G` | wording_changed | 同上（金色） | 否（显示态） |

**结论：37.0.0 没有需要“改现有脚本数值”的共享卡**——6 条都是显示/占位符书写差异，
脚本本来就应按 `CardDef.num()` 读数值。另有 **45 张“无法对拍”**（37 文本占位符在
数据里无值可解，见 `coverage_matrix.json::unverified_cards`）：pool_minions 6、
hero_powers 3、quests 18、quest_rewards 7、dark_gifts 8、buddies 1、timewarp 2——
**不能据此断言有数值变化**，移植时按卡面 + hsrl2 参考脚本定值。

### 3.4 AT 轮换出池 / 37 回池（无需移植 / 需补脚本）

37 相对 AT **36.6.3 轮换池**的成员变化（`pool_membership`）：

| kind | 37 回池（AT 36.6.3 不在池） | AT 出池 | 说明 |
| --- | ---: | ---: | --- |
| 池内随从 | **+34** | -5 | +34 中 **20 张是 Naga 回池**（37 池内 Naga 21 张 vs AT 36.6.3 池内 2 张），另有 ALL/Undead 等；AT 出池 5 张是 **Dark Paradox 旧 token**（`BG36_360t3/t4/t5/t6/t9`，37 改为单卡 `BG36_360`） |
| 池内法术 | +6 | 0 | 3 张为 Duos 伪影（§4.5），实际 +3（`BG28_606`、`BG32_815`、`BG35_922`） |
| 英雄 | +2 | 0 | 新入池：`BG22_HERO_007` Queen Azshara、`BG23_HERO_304` Lady Vashj（两者脚本 AT 已有 1/2；Azshara 技能缺） |
| Tier 7 | +1 | 0 | `BG27_514` Sea Witch Zar'jira（Naga T7） |
| 饰品 | +173（定义集差） | 0 | 37 定义 409 vs AT 36.6.3 轮换池 236；AT 另有 420 个定义（含未轮换） |

**“AT 已移除、无需移植”**（真正在 37 数据中不存在的 AT 内容）：

* AT **内容脚本**引用但 37 数据缺失的 id **只有 1 个**：`BG_OG_044 Fandral Staghelm`
  （AT `naga.rs`，非池卡）→ 无需移植，仅需 compat 条目（§2.4-4）。
* AT **数据**（3983 id）在 37 数据（3817 id）中缺 288 个：Duos 135、英雄/技能 24、
  其余 token/按钮 129——都不影响内容移植（本工具已按内容注册表交集核对）。
* AT 出池的 5 个 Dark Paradox token（`BG36_360t3..t9`）**无需移植**（37 池改用
  `BG36_360` 单卡，该卡反过来需要新脚本，见 §4.1）。

### 3.5 37 新增内容与数据伪影

* 37 数据有、36.6.3 AT 数据无的 id 共 **122**：**异变 108**（历史定义，AT 数据
  不导出异变）+ **UI 按钮/token 14**（`TB_BaconShop*_Button`、`BG22_BuddyMeter`、
  `BG36_Button_DarkGift` 等）。**可玩卡新增 = 0**。
* Duos-only 文本混入单人池集合的卡 **3 张**（`BG31_242/243/244`），数据管线应剔除。

---

## 4. 37.x 缺口清单

### 4.1 池内缺失随从（15 张，全部 M 级）

> 完整表（含 hsrl2 参考路径 / AT 最近可复用脚本 / 相似度）见
> `runs/p2_delta/missing_pool_minions.md`。37 池内 Naga 共 **21 张，缺脚本 14 张**，
> 全部是 **Naga 回池**带来的（AT 36.6.3 池内只有 2 张 Naga），AT 的 `naga.rs`
> 只覆盖了其中一部分；另 1 张为 ALL 种族（`BG36_360`）。

| # | Card ID | 名称 | T | 种族 | 攻/血 | 文本 | hsrl2 参考脚本 | 备注 |
| ---: | --- | --- | ---: | --- | --- | --- | --- | --- |
| 1 | `BG23_002` | Shell Collector | 2 | NAGA | 4/3 | <b>Battlecry:</b> Get a Tavern Coin. | `batches/batch_battlecry.py` | 战吼：获得一张酒馆币 |
| 2 | `BG26_505` | Zesty Shaker | 4 | NAGA | 6/7 | [x]Once per turn, when a <b>Spellcraft</b> spell is played on _this, get a new copy of it. | `batches/batch_econ_misc.py` | 每回合首次 Spellcraft 复制 |
| 3 | `BG27_514` | Sea Witch Zar'jira | 7 | NAGA | 4/5 | [x]<b>Spellcraft:</b> Choose a different minion in the Tavern to get a copy of. | `batches/batch_misc.py` | Spellcraft：复制酒馆随从（T7） |
| 4 | `BG31_035` | Groundbreaker | 6 | NAGA | 6/4 | [x]After you play a Naga, gain +{1}/+{1}. <i>(Improved by every 3 spells you've cast this … | `batches/batch_econ_misc.py` | 每 3 法术 Improve |
| 5 | `BG31_920` | Darkcrest Strategist | 5 | NAGA | 4/5 | <b>Spellcraft:</b> Get a random Tier # Naga. <i>(Improves each turn!)</i> | `batches/batch_misc.py` | Spellcraft：随机 Naga，Improve |
| 6 | `BG31_925` | Showy Cyclist | 5 | NAGA | 4/2 | [x]<b>Deathrattle:</b> Give all your Naga +{1}/+{3}. <i>(Improved by every 3 spells you've… | `batches/batch_deathrattle.py`<br>`batches/batch_trinkets31.py` | 亡语：Naga 群体增益 |
| 7 | `BG32_835` | Tranquil Meditative | 5 | NAGA | 3/8 | [x]<b>Spellcraft:</b> Your Tavern spells give an extra +{0}/+{1} this game. | `batches/batch_misc.py` | Spellcraft：酒馆法术额外 +X |
| 8 | `BG32_837` | Fauna Whisperer | 6 | NAGA | 4/9 | [x]At the end of your turn, cast Natural Blessing on adjacent minions. | `batches/batch_eot_sot.py` | EoT：对相邻施放 Natural Blessing |
| 9 | `BG33_319` | Rimescale Priestess | 4 | NAGA | 3/3 | <b>Spellcraft:</b> Get a random Tavern spell that gives stats. | — | Spellcraft：随机“给属性”酒馆法术（hsrl2 也无） |
| 10 | `BG34_925` | Seafloor Recruiter | 4 | NAGA | 3/5 | <b>Rally:</b> Cast Chef's Choice on the minion to the right. | `batches/batch_rally2.py` | Rally：对右侧施放 Chef's Choice |
| 11 | `BG35_921` | Abyssal Bruiser | 4 | NAGA | 2/1 | [x]<b>Divine Shield</b> Has +{0}/+{1} for each Tavern spell you've cast this game. | `batches/batch_counters.py` | 圣盾 + 每法术 +X |
| 12 | `BG36_360` | Dark Paradox | 1 | ALL | 1/1 | This has a different <b>Dark Gift</b>, stats, and Tier each game! | — | **37 重做卡**：每局随机 Dark Gift/属性/Tier（hsrl2 也无） |
| 13 | `BG36_508` | Cagey Conjurer | 4 | NAGA | 5/3 | [x]<b>Activate ({0}):</b> Cast {1} random Tavern spells __<i>(targets this if possible)</i… | `batches/batch_unfreeze.py` | Activate：随机施放酒馆法术 |
| 14 | `BG36_622` | Torrential Ruiner | 6 | NAGA | 6/3 | Whenever you cast a spell on a Naga, give your minions +{0}/+{1}. | `batches/batch_econ_misc2.py` | 对 Naga 施法 → 群体增益 |
| 15 | `BG36_921` | Fleeing Fugitive | 1 | NAGA | 5/2 | Whenever you cast a spell on this, gain +{0} Health. | `batches/batch_econ_misc2.py` | 被施法 → 加血 |

**AT 侧最接近的可复用脚本**（文本 Jaccard 启发，`similarity` 见 JSON）：
`BG23_002→TB_BaconShop_HERO_23_Buddy(0.38)`、`BG26_505→BG28_HERO_800_Buddy(0.63)`、
`BG27_514→BG_EX1_564(0.33)`、`BG31_035→BG36_318(0.45)`、`BG31_920→BG34_Giant_333(0.60)`、
`BG31_925→BG36_318(0.68)`、`BG32_835→BGS_Treasures_110(0.40)`、`BG32_837→BG22_403(0.46)`、
`BG33_319→BG28_606(0.70)`、`BG34_925→BG36_241(0.27)`、`BG35_921→BG36_MidGameEffect_000t30t(0.50)`、
`BG36_360→BG36_MagicItem_309(0.38)`、`BG36_508→BG36_240(0.34)`、
`BG36_622→BG36_MagicItem_307(0.30)`、`BG36_921→BG36_MagicItem_307(0.38)`。
> 启发式仅作选路提示；**权威参考是 hsrl2 的 Python 脚本**（数值/语义骨架）。

### 4.2 英雄与英雄技能

* **英雄缺 1**：`BG22_HERO_007` Queen Azshara（主技能 `BG22_HERO_007p`
  “Azshara's Ambition → Naga Conquest”）。hsrl2 参考：
  `hsrl2/scripts/batches/batch_hero_combat3.py::BG22_HERO_007p/p2`。
* **英雄技能定义缺 42**（37 主技能只缺 1 个）：
  * **主技能（hero 的主技能位）1**：`BG22_HERO_007p`（Azshara）；
  * 替换/变体技能 15：`BG20_HERO_201p2`、`BG20_HERO_283p_t1..3`、
    `BG22_HERO_000p`（Tavish 旧主技能，已被 `BG22_HERO_000p_Alt` 取代）、
    `BG22_HERO_000p_t1..4`、`BG22_HERO_001p_t1..4`、`BG22_HERO_007p2`、
    `BG28_HERO_400p2`；
  * 旧英雄替换技能 `TB_BaconShop_HP_*`（21，含 King of Aberrations 的 11 个变体
    `_041a.._041l`）；
  * 异变/Timewarp 附赠技能 token（5：`BG27_Anomaly_805t`、`BG31_Anomaly_117t`、
    `BG35_Anomaly_002t/007t/008t`）。
  **对 P1 无影响**（37 主技能只有 Azshara 缺）；其余列入 P3 长尾（按可达性）。
* AT extra 11 个技能定义在 37 不存在（Duos/旧英雄），无需移植。

### 4.3 池内酒馆法术（缺 5 → 实际 2）

| Card ID | 名称 | T | 结论 |
| --- | --- | ---: | --- |
| `BG31_242` | Bargain Bundle | 5 | **Duos-only**（“Your teammate gets the other options”），单人池应剔除 |
| `BG31_243` | Portal in a Fountain | 3 | **Duos-only**（`Pass` 语义），应剔除 |
| `BG31_244` | Portal in a Crystal | 5 | **Duos-only**，应剔除 |
| `BG32_815` | Shifting Tide | 4 | **需移植**（Naga 回池；hsrl2 `batch_spells4.py`） |
| `BG35_922` | Queen's Command | 5 | **需移植**（Naga 增益；hsrl2 `batch_spells_final.py`） |

> 酒馆法术**全量**（205）缺 94：其中 46 张是星际升级 token（`BG31_HERO_801pt*`，
  非池、按宿主卡生成），其余 48 张为非池/历史法术（含 Timewarp 遗留、Treasure 等），
  只有“可达性”成立时才需要移植（P2/P3）。

### 4.4 饰品（最大缺口）

* 全部 409 定义缺 **161**：按前缀 `BG30 69 / BG32 54 / BG35 30 / BG36 8`；
  其中 **26 张连 hsrl2 参考脚本也没有**（从零实现），其余有 hsrl2 脚本可转写。
* **37 新增 BG36 饰品缺 8 张**（应优先）：`BG36_MagicItem_205/305/361/362/380/412/
  412t2/841`。
* 商店可提供口径（357）缺 **138**；L 级 11 张：`BG30_MagicItem_821t2/917/919/982`、
  `BG32_MagicItem_415/862/862t`、`BG35_MagicItem_431t/432/714/834`。
* **限制**：数据无 37 轮换标志 → 138 是上界；先按“37 新增 8 + AT 36.6.3 轮换池
  236 的差集”triage，再排期（P2）。
* **完整 161 张逐卡清单**（id / hsrl2 参考 / AT 最近脚本 / 难度）见脚本产物
  `runs/p2_delta/summary.md` §7 的 `trinkets` 表；池内随从 15 张另见
  `runs/p2_delta/missing_pool_minions.md`（含完整卡面文本）。

### 4.5 任务奖励 / T7 / 黑暗赠礼 / 异变 / 伙伴 / 任务卡

| kind | 缺失 | 明细 | 影响 |
| --- | ---: | --- | --- |
| 任务奖励 | 2 | `BG24_Reward_321t` Alter Ego（hsrl2 有脚本）、`BG27_Anomaly_555t` No Place Like Holmes（异变 token） | 任务系统若启用才需要；P3 |
| T7 随从 | 1 | `BG27_514` Sea Witch Zar'jira（已含在池内随从 15 中） | P1 |
| 黑暗赠礼 | **0** | — | 无缺口 |
| 异变 | 108 | AT 无系统；37 无新增异变卡 | 不阻塞；§7 |
| 伙伴 | 18 | 新英雄伙伴 2（`BG22_HERO_007_Buddy`、`BG23_HERO_304_Buddy`）+ 旧变体/token 16 | 仅当引用伙伴的饰品/奖励移植时需要 |
| 任务卡 | 1 | `BG24_Quest_328` Close the Case | P3 |

### 4.6 37.0.0 新机制族 vs AT hook/flag 对照

AT 36.6.3 的脚本原语（`crates/taverngym/src/script.rs` + `event.rs`）覆盖度很高：
`Script` 结构体 **35 个字段**（battlecry/deathrattle/rally/avenge/start_of_combat/
end_of_turn/start_of_turn/on_sell/activate/after_attack/on_stats/on_merge/followup/
discover_pick/scheduled/on_event…）+ `flag` **15 个** + `ev` **25 个事件位** +
`TargetSpec` **23 种**（含 Hand/Tavern/多目标链/Buddy）。
对 37 缺失卡文本做机制族关键词扫描（`coverage_matrix.json::trigger_inventory`）：

| 机制族 | 缺失卡命中 | AT 对应原语（源码证据） | 结论 |
| --- | ---: | --- | --- |
| Spellcraft | 12 | `cards.rs::spellcraft_id` + `engine.rs`（AT 有 Spellcraft 系统） | ✅ 无新系统 |
| Timewarp / Chronum | 13 / 3 | `content/timewarp.rs` + `state.rs Pending::Timewarp` | ✅ 无新系统（按 config） |
| Trinket | 11 | `state.rs Pending::Trinket` + `content/trinkets_p1..p8.rs` | ✅ |
| Buddy | 8 | `content/buddies_a/b/c.rs` + `content::buddy_pool()` | ✅ |
| Quest | 3 | `state.rs Pending::Quest` + `content/quests.rs` | ✅ |
| Aberration（种族） | 1 | `types.rs Races::ABERRATION` + `content/aberrations.rs` | ✅ |
| Discard | 1 | `event.rs ev::DISCARDED` + `content/mod.rs::on_discard` | ✅ |
| Pass | 8 | **Duos 语义**；37 文本只在 `@` 第二段 | ❌ 不是单人机制 |
| **Anomaly** | 0（卡面不含该词） | **AT 无 anomaly 系统**（`crates/taverngym/src` 0 命中） | ⚠️ 唯一缺系统（§7） |

**结论**：37.0.0 没有引入 AT 完全没有原语的新玩法机制（除异变系统外）；缺口集中在
**脚本数量**与**数据管线**，而不是引擎原语。AT 侧需要新增的 hook 只有：
* `on_event` 已有 25 个事件位，37 缺失卡未出现表外触发词（“end of combat”、
  “after each combat”等均无命中）；
* 建议在 Rust fork 中为 **异变** 预留系统接口（若启用），不需要新 hook。

### 4.7 AT 已移除/轮换内容（不必移植）

* AT 出 37 池：Dark Paradox 5 个旧 token（`BG36_360t3/t4/t5/t6/t9`）——37 用单卡
  `BG36_360` 替代（该单卡反而要新脚本）；
* AT 数据独有的 Duos/旧英雄/UI token（288 id）——不在单人内容范围；
* Duos-only 池法术 3 张（`BG31_242/243/244`）——数据伪影，删除而非移植。

---

## 5. 移植参考与分批计划

### 5.1 难度分级统计（全部缺失卡，按 kind）

| kind | S | M | L | 合计 |
| --- | ---: | ---: | ---: | ---: |
| 池内随从 | 0 | 15 | 0 | 15 |
| 英雄（英雄卡） | 0 | 1 | 0 | 1 |
| 主英雄技能 | 0 | 1 | 0 | 1 |
| 英雄技能（含变体） | 0 | 41 | 1 | 42 |
| 池内酒馆法术 | 0 | 5 | 0 | 5 |
| 酒馆法术全量 | 0 | 93 | 1 | 94 |
| 饰品 | 0 | 150 | 11 | 161 |
| 任务奖励 | 0 | 2 | 0 | 2 |
| 异变 | 0 | 0 | 108 | 108 |
| Tier 7 | 0 | 1 | 0 | 1 |
| 伙伴 | 1 | 17 | 0 | 18 |
| 任务卡 | 0 | 1 | 0 | 1 |
| Timewarp | 0 | 0 | 0 | **0** |
| **合计（按 kind）** | **1** | **327** | **121** | **449** |

跨 kind 重复 7 条（只算一次的去重后 **442 个唯一 id**）：`BG22_HERO_007p`（主技能
⊂ 英雄技能）、`BG27_514`（T7 ⊂ 池内随从）、`BG31_242`/`BG31_243`/`BG31_244`/
`BG32_815`/`BG35_922`（池内法术 ⊂ 酒馆法术全量）。

### 5.2 分批计划

> 全部 14 个 kind 的逐卡缺失/变更/无法对拍清单由脚本生成在
> `runs/p2_delta/summary.md`（§7 分 kind 清单）与 `coverage_matrix.json`；
> 本文只内联 P1 关键 15 张池内随从（§4.1）。

#### P1（37.0.0 可用最小集）：**18 张卡，全部 M 级**

| 批次 | 内容 | 卡数 | 参考 |
| --- | --- | ---: | --- |
| P1-A | **数据管线先决**（非卡）：37 数据入 fork（`cards_37.json`）+ compat 条目 `BG_OG_044` + 文本 `@` 拆分 + Duos/UI token 过滤 + cost 约定 | — | §2.4；P2-B 生成器 |
| **P1 状态（2026-10-26）** | **✅ 已完成**：15 池内随从 + Azshara 主技能 + 2 池内法术已移植（`content/p3_batch_a.rs`/`p3_batch_b.rs`/`p3_systems.rs`）；池内覆盖 missing 0；hsrl2 oracle 15 MATCH/1 DEFERRED/2 STRUCTURAL_OK；全量 cargo test 887/0。证据见 `docs/P3_VERIFICATION.md` / `docs/AUTOTAVERN_P3_KICKOFF.md` §4。 | — | P3 |
| P1-B | 池内缺失随从 15：`BG23_002, BG26_505, BG27_514, BG31_035, BG31_920, BG31_925, BG32_835, BG32_837, BG33_319, BG34_925, BG35_921, BG36_360, BG36_508, BG36_622, BG36_921` | 15 | 13 张有 hsrl2 脚本；`BG33_319/BG36_360` 需新写（AT 最近脚本相似度 0.70/0.38） |
| P1-C | 主英雄技能 1：`BG22_HERO_007p`（Azshara） | 1 | `batch_hero_combat3.py` |
| P1-D | 池内酒馆法术 2：`BG32_815, BG35_922` | 2 | `batch_spells4.py` / `batch_spells_final.py` |
| P1-E | T7：`BG27_514`（已含在 P1-B） | 0 | — |
| P1-F | 黑暗赠礼：0（47/47 已覆盖） | 0 | — |

**P1 验收**（建议作为 Rust fork 的“37 可用”门禁）：

1. `cargo build --release -p hsbg-engine` + 冒烟：8 人 bot 对局 ×20 seeds，`crashes=0`；
2. 池内脚本覆盖审计：`pool_minions` 缺失 = 0、`pool_spells`（剔除 3 Duos）= 0、
   主英雄技能 = 0（等价于 `tools/audit_card_registry_v2.py --strict` 的
   pool_minion/pool_spell 门禁在 Rust content 上重放）；
3. 对拍：同 seed 下与 hsrl2 的 679 场官方战斗回放差分（`tools/diff_replay_combat.py`
   口径）中 `missing_script` 归因 = 0；池内随从战斗数值差分率不高于 hsrl2 基线；
4. 数据断言：AT content 1301 个 id 在近 37 卡表中 0 missing（含 compat）；
5. 确定性：同 seed 双跑状态指纹一致（引擎已有确定性测试口径）。

**P1 工作量（估算，见 §8）**：18 卡 × M（0.2–0.4 人天/卡，16 张有 hsrl2 参考）
≈ **3.5–7 人天**；+数据管线 1–2 人天 + 验收 1 人天 → **5.5–10 人天**。

#### P2（法术/饰品）

| 批次 | 内容 | 量 | 说明 |
| --- | --- | ---: | --- |
| P2-A | 37 新增 BG36 饰品（8） | 8 | `BG36_MagicItem_205/305/361/362/380/412/412t2/841`；3 张无 hsrl2 参考 |
| P2-B | 饰品 triage + 可提供池缺口 | 138（上界） | 先按 37 轮换/可达性筛；AT 侧已有 248 个饰品脚本可参考，hsrl2 有 316/357 |
| P2-C | 非池酒馆法术（可达性成立者） | ≤48 | 含 Timewarp 遗留/Treasure/载荷法术；46 张 `BG31_HERO_801pt*` 星际升级 token 按宿主卡生成，可后置 |
| P2-D | 英雄技能变体（若 37 轮换启用） | ≤41 | 替换/变体技能，按英雄可达性排序 |

**P2 验收**：饰品 offer 池 ⊆ content 注册表（AT 已有 `offer_ok` 钩子；对应 hsrl2
G-R1 门禁）；每批：单卡单测 + 池内 offer 池审计 0 空转；对拍差分 `missing_script`
不新增。

**P2 工作量（估算）**：饰品 8 新 + triage 后约 40–80 张有效缺口 × 0.2–0.3 人天
≈ **10–25 人天**；法术 ≈ 5–15 人天。

#### P3（任务/异变/长尾）

| 批次 | 内容 | 量 | 说明 |
| --- | --- | ---: | --- |
| P3-A | 异变系统（Rust 新系统 + 108 脚本） | 108 | 仅当决定启用异变；AT 无系统，hsrl2 有 41 张已实现可参考 |
| P3-B | 任务卡/奖励 | 1 + 2 | 任务系统若启用 |
| P3-C | 伙伴缺口 | 18 | 新英雄伙伴 2 张 + 变体 token 16 |
| P3-D | 英雄技能变体/旧英雄替换技能 | 41 | 按可达性 |

**P3 验收**：按“是否启用”开关分组；启用项通过对应系统单测 + 对拍；未启用项在
数据/文档标记 `reachable=false`。

**P3 工作量（估算）**：异变 30–60 人天（新系统 + 108 脚本）；其余 20–35 人天。

---

## 6. 缺失操作清单（游戏支持但两引擎都未实现）

> 全部 17 项核对见 `runs/p2_delta/ops_probe.json`（每项含两侧源码 file:line 与
> 37 卡面证据）。**结论：只有 3 项真缺口**，其中 2 项已有 std profile 预留编号。

### 6.1 核对总表

| # | 操作 | AT 36.6.3 | HSBRSIM（legacy） | 37 卡面/规则证据 | 结论 | 动作编号 |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | 整馆冻结/解冻 | ✅ `Freeze` 是 toggle（`recruit.rs:2125 set_frozen(!all)`；`state.rs:1154`） | ✅ FREEZE + F-23 `unfreeze_tavern` | 冻结/解冻按钮 | 已覆盖 | 245 Unfreeze（std） |
| 02 | **单槽位冻结/解冻** | ❌ 只有整馆；`unfreeze_shop(sid)` 仅内部替换清理，不是动作（`recruit.rs:392`） | ❌ 只有整馆 API | `BG22_HERO_004p` “Freeze **them both**” → 冻结是**按随从粒度**状态；真实 UI 每个酒馆随从有独立雪花 | **缺口** | **266..273 FREEZE_SLOT(0..7)** |
| 03 | 酒馆展示位 8 | ✅ `N_SHOP=8`（`actions.rs:28`）；= 7 随从 + 1 酒馆法术槽（`config.rs:241/334`） | ⚠️ legacy 观测 `TAVERN_MAX=7` 会截断第 8 张 | 37 池内酒馆法术 76 与随从同店 | 已覆盖（观测需修） | 8..15 Buy(0..7) |
| 04 | 选择选项 16 | ✅ `N_CHOICE=16`（`actions.rs:31`） | ⚠️ legacy `CHOICE_OPTION_MAX=5` | 37 无 >5 选项强制场景 | 已覆盖 | 30..45；250..265 预留 |
| 05 | 手牌 10 / 棋盘 7 | ✅ `hand_size=10/board_size=7`（`config.rs:243-244`）+ 上限校验（`actions.rs:246/258`） | ✅ HAND_MAX=10/BOARD_MAX=7（F-37 修过 Reborn 溢出） | 规则常数 | 已覆盖 | 动作维度 N_HAND/N_BOARD |
| 06 | 黑暗赠礼选择 | ✅ `Action::DarkGift`（`actions.rs:78`）+ `recruit.rs::dark_gift` | ✅ USE_DARK_GIFT | 47 张赠礼数据 | 已覆盖 | 6 + Choose |
| 07 | 任务选择 | ✅ `Pending::Quest`（`state.rs:659`）+ `recruit.rs:2411` | ✅ quest_offer | 73 奖励 / 20 任务 | 已覆盖 | Choose |
| 08 | 饰品选择（含放弃） | ✅ `Pending::Trinket`（`state.rs:649`） | ✅ trinket_offer | 409 饰品 | 已覆盖 | Choose |
| 09 | **第 3+ 英雄技能槽可用** | ⚠️ 引擎支持任意 slot（`state.rs:640-646`，HeroPowerChoice slot），但动作空间只编码 2 槽（`actions.rs:39 N_POWERS=2`） | ✅ `hero_power_ids` 列表 + `set_second_hero_power` | 21 张效果给“第二技能”（如 `BG36_MagicItem_411` Reinvigorating Light、`BG34_HeroPowerSpell_*`） | **缺口**（动作空间） | **246..249 HeroPower(2..5)**（std 已预留） |
| 10 | 目标取消 | ✅ `Action::Cancel`（`actions.rs:79`）+ `Pending::cancellable` | ⚠️ legacy ActionKind 无 CANCEL | 规则层操作 | AT 已覆盖 | 7 Cancel（std） |
| 11 | **异变系统/异变选择** | ❌ 无系统（源码 0 命中 anomaly） | ✅ `Game(anomaly=...)` + 41 张脚本 | 108 条历史定义、0 张 37 新增 | **缺口（系统）** | 不新增动作；P3 |
| 12 | Pass（Duos） | ❌ 不在范围 | ❌ hsrl2 F-08 裁定不实现 | 只出现在 `@` 第二段 Duos 变体（5 张 37 新卡）+ 2 张 Duos 法术 | 非单人机制 | 不新增 |
| 13 | 弃手牌选择 | ✅ `TargetSpec::Hand`（`content/minions.rs:1111`） | ✅ F-08 `discard_card` + `discard_card` pending | 37 Aberration 弃牌族 | 已覆盖 | Choose |
| 14 | 非随从 Discover | ✅ `Pending::Discover`（options 是 Item，可含法术/技能） | ⚠️ legacy G-F1（只造随从，4 脚本自建） | 池内法术/奖励可发现 | AT 已覆盖 | Choose（std） |
| 15 | 开局英雄选择 | ✅ `Pending::HeroSelect` + `config.hero_choices` | ✅ env 配置层 | 118 英雄 | 已覆盖 | Choose |
| 16 | Timewarp 购买/离开 | ✅ `Pending::Timewarp`（最后一项=离开） | ❌ hsrl2 无系统 | 37 数据 253 张全在 | AT 已覆盖（config 开关） | Choose（选项池） |
| 17 | Activate 带目标 | ✅ `Continuation::Activate` + `resolve_or_ask`（`recruit.rs:2236`） | ⚠️ legacy G-A3 非引擎级 | 池内 23 张 Activate | AT 已覆盖 | Activate + Choose |

### 6.2 建议扩展动作编号（245+）

P2-D std profile 已消费 245..265（`N_TOTAL_ACTIONS=266`，见
`hsbg/env/action_space_std.py`）：

| 索引 | 数量 | 动作 | 依据 |
| ---: | ---: | --- | --- |
| 245 | 1 | `Unfreeze` | 整馆解冻（语义已被 AT Freeze toggle 覆盖，std 拆成单向动作便于掩码） |
| 246..249 | 4 | `HeroPower(2..5)` | OPS-09：AT 引擎支持 slot ≥2，动作空间只到 1 |
| 250..265 | 16 | `Choose(16..31)` | 预留大选项池（当前 16 已够） |
| **266..273** | **8** | **`FreezeSlot(0..7)`**（toggle） | **OPS-02 唯一新增语义缺口**：单个酒馆随从冻结/解冻 |
| — | — | 扩展后 `N_TOTAL_ACTIONS = 245 + 21 + 8 = 274` | 若需显式单槽 `UnfreezeSlot(i)` 可再拆 8 个（274..281），当前不建议 |

> 不新增动作的核对项：Pass（Duos）、Anomaly（配置注入/系统）、Discard（Choose 手牌）、
> DarkGift/Quest/Trinket/HeroSelect/Timewarp（Choose 选项池）。

### 6.3 为什么 OPS-02 是真缺口（证据链）

1. **游戏语义**：酒馆里每个随从有独立冻结状态与 UI 雪花；整馆按钮与单卡按钮是两种
   操作（真实对局 `docs/LIVE_TO_SIM_GAP.md` L01 只覆盖整馆）。卡面证据：
   `BG22_HERO_004p Twice as Nice`“copy its highest-Tier minion and **Freeze them
   both**” / `TB_BaconShop_HP_014 Stay Frosty`“Freezes at the end of each turn”——
   效果能指定“them both/its minion”，说明引擎必须能表达**单随从冻结状态**。
2. **AT 侧**：`Action` 枚举只有 `Freeze`（整馆 toggle）；`recruit.rs::freeze()` 用
   `set_frozen(!all)`；`recruit.rs::unfreeze_shop(sid)` 是内部工具（卡被替换时清标记），
   既不是动作也不会广播（无 `ev` 事件）。
3. **HSBRSIM 侧**：`hsbg/env/spec.py::ActionKind.FREEZE` 只有整馆；引擎 F-23 的
   `unfreeze_tavern` 也是整馆对称 API，没有 per-slot 公开动作。
4. **影响面**：RL 策略无法表达“只冻/只解某槽位”，而这在真实对局中是保鲜/卡位手段；
   同时 AT 的卡片效果（Freeze them both）目前只能在脚本里直接写 `shop[i].frozen`
   ——动作空间与效果空间不一致，对“动作/观测统一”的可比基线不利。
5. **建议实现**：`FREEZE_SLOT(i)` toggle（8 槽 = 266..273）。Rust 侧在
   `recruit.rs` 加 `freeze_slot(p, idx)`：
   `can_freeze` 计数 + `players[p].shop[idx].frozen ^= true` + 事件
   （若未来有“冻结/解冻时”监听）；mask 仅对 `idx < shop.len()` 置位。

### 6.4 易误判项澄清（核对结论）

* **“AT 只有 Freeze 无 Unfreeze”**：动作枚举确实只有 `Freeze`，但**语义是 toggle**：
  `recruit.rs:2121-2125`“all frozen already → unfreeze them”。所以整馆解冻已被覆盖，
  真正缺的是**单槽位**。
* **“酒馆展示位 8”**：AT 已按 8 建模（7 随从 + 1 酒馆法术槽，`config.rs:334`
  `7 + shop_spell_slots == 8` 上限校验）；HSBRSIM legacy 观测 `TAVERN_MAX=7` 才是
  需要修的（截断第 8 张，属 P2-D 观测迁移）。
* **“选择 16”**：AT 已 16；HSBRSIM legacy 只有 5（观测层限制）→ std profile 迁移修。
* **“手牌/棋盘上限”**：两侧都已覆盖，不是动作缺口；注意 Rust fork 需要保证
  `hand_size=10`/`board_size=7` 可配置。
* **“黑暗赠礼/任务选择/备用技能槽/目标取消”**：AT 均已覆盖（见 §6.1 证据）。
* **“Pass”**：不是单人动作——37 数据里只出现在 `@` 第二段（Duos 文本变体）与 2 张
  Duos-only 法术；hsrl2 已在 F-08 裁定“Duos 语义不实现”。

---

## 7. 37.0.0 新系统数据支持评估

**判定方法**：系统的“是否在 37.0.0 启用”以**37 数据是否新增该系统卡**（BG36/BG37
前缀的新 id）为主证据；历史定义残留 + 文本引用作辅证。

| 系统 | 37 数据规模 | 37 新增该系统的卡 | AT 36.6.3 支持 | Rust fork 需要 | 优先级 |
| --- | ---: | ---: | --- | --- | --- |
| 饰品（Trinket） | 409（轮换池未知） | 77（BG36） | ✅ 系统完备（`Pending::Trinket` + 248 脚本） | 系统已有；补 8–138 脚本 | **P1/P2** |
| 黑暗赠礼（Dark Gift） | 47 | 47（BG36） | ✅ 全实现（47/47） | 无 | 无缺口 |
| Deity（旧神） | 池内 9 随从 + 1 法术 + 5 饰品 | 有（BG36/BGFYM） | ✅ `Player.deity` + `buff_deity`/`deity_awakened` | 系统已有；按卡补脚本（部分 P1/P2） | P1/P2 |
| Aberration 种族 | 池内 25、定义 64 | 有（BG36） | ✅ `Races::ABERRATION` + `content/aberrations.rs` | 种族位已有；补脚本 | P1/P2 |
| Discard | 弃牌族 12 池卡 | 有（BG36） | ✅ `ev::DISCARDED` + `on_discard` + `TargetSpec::Hand` | 原语已有；补脚本 | P2 |
| Timewarp | 253（37 数据全在） | **0** | ✅ 253/253 已实现（`timewarp.rs`，config 默认关） | 零脚本移植；按 `config.timewarp_enabled` 开关 | **可选**（无新增，建议 default off） |
| 任务/任务奖励 | 奖励 73、任务 20 | **0** | ✅ `Pending::Quest` + `quests.rs` | 已有系统；补 3 张 | P3 |
| 伙伴（Buddy） | 定义 127（非池） | 1（非池 token） | ✅ `buddies_*.rs` + `buddy_pool()` | 已有系统；补 18（按引用） | P3 |
| **异变（Anomaly）** | 108 | **0（仅 1 条 BG36_Anomaly_002 教学式条目）** | ❌ **无系统** | 需 Rust 新系统（开局覆写 + 可选局内选择）+ 108 脚本 | **P3/不启用** |
| Duos（队友/Pass） | 数据含 Duos 定义（135 id 不在 37） | — | ❌ 不在范围 | 不需要（单人 8 人局） | 排除 |

**异变专项结论**：108 条异变定义是 BG27/31/32/33/34/35 的历史定义；唯一 BG36 条目
`BG36_Anomaly_002 “Dark Gifts!”` 在 hsrl2 里被记为“S14 基线机制的文档化 no-op”。
**没有证据表明 37.0.0 轮换启用了异变系统** → 不列入 P1；若未来启用，需按 §5.2 P3-A
新增 Rust 系统（开局全局覆写框架 + 41 张 hsrl2 已有实现可参考 + 剩余 67 张）。
`hsbg/env/game_env.py` 目前以 `anomaly: Optional[str]` **配置注入**，不需要新增动作。

---

## 8. 结论：Rust 主引擎“37.0.0 可用”的最小内容集与工作量

### 8.1 最小内容集合（Must-have for P1）

**18 张卡（严格去重，全部 M 级）**：

* **池内随从 15**（§4.1；14 张 Naga + 1 张 ALL 种族的 `BG36_360` Dark Paradox），含
  T7 `BG27_514`；
* **主英雄技能 1**：`BG22_HERO_007p`（Azshara）；
* **池内酒馆法术 2**：`BG32_815`、`BG35_922`；
* **黑暗赠礼 0**（47/47 已覆盖）；**T7 0**（与池内随从重叠）；**异变 0**（不启用）。

**P1 的“可用”定义（建议门禁）**：见 §5.2 P1 验收 5 条。核心是
**池内脚本缺口=0 + 8 人 bot 对局可跑 + 对拍差分无新增 `missing_script` 归因 + 同
seed 确定性**。

### 8.2 工作量（估算；估算基准已标注）

> **估算口径**：按 `hsrl2` 参考脚本可直接转写（M 级≈0.2–0.4 人天/卡，含单测；
> 无 hsrl2 参考 ×1.5）与 AT 相近脚本骨架复用；**不是实测工时**，Lead 可按人力
> 调整。S≈0.05–0.1、M≈0.2–0.4、L≈0.5–1.5 人天/卡（含测试）。

| 阶段 | 内容 | 数量 | 估算人天 |
| --- | --- | ---: | ---: |
| P1-A | 数据管线（37 卡表 + compat + 文本 `@`/Duos/UI token + 池标志） | — | 1–2 |
| P1-B/C/D | 18 张 M 卡（16 张有 hsrl2 参考） | 18 | 3.5–7 |
| P1 验收 | 门禁 5 条 + 对拍回归建立 | — | 1–2 |
| **P1 合计** | | | **5.5–11 人天** |
| P2-A/B | 饰品：8 张 37 新增 + triage 后有效缺口（上界 138，估计 40–80） | 48–88 | 10–25 |
| P2-C/D | 非池法术/技能变体（可达性筛选后） | 20–89 | 5–20 |
| P2 合计 | | | **15–45 人天** |
| P3-A | 异变系统 + 108 脚本（仅当启用） | 108 | 30–60 |
| P3-B/C/D | 任务/伙伴/长尾 | 60 | 20–35 |
| P3 合计 | | | **50–95 人天** |

**排序建议**：P1-A → P1-B/C/D → 门禁 → P2-A（8 张）→ 以“37 轮换 triage”决定
P2-B 规模 → 再决定是否启动 P3-A（异变）。**异变是唯一需要 Rust 新系统的内容，
且证据不足表明 37.0.0 启用**——建议 P2 完成后再由 Lead 决策。

### 8.3 风险与限制

1. **37 轮换池未知**：饰品/异变/任务只有全量定义，没有“当前轮换”标志；138/108/73
   等数字是上界。需要 Lead 用官方公告/真实对局（live 观测）裁定或先按 AT 轮换习惯估值。
2. **37 文本占位符**：45 张卡的数字无法从数据还原（`unverified_cards`），移植时以
   hsrl2 参考 + 卡面 + 官方 wiki 定值，不能靠“文本对拍无差异”推断无改动。
3. **AT 数据版本**：AT `cards.json` 是 36.6.3（3983 id），37 数据是精简导出（3817 id）；
   “新增/移除”是**导出差**，不代表客户端真实增删。
4. **AT 脚本质量**：上游自己声明“Registry presence is coverage, not proof of
   game-rule accuracy”；对拍优先级参考 `docs/CONFORMANCE_AUTOTAVERN.md` 的 AC 台账。
5. **数据伪影**：3 张 Duos-only 池法术与 14 个 UI token 必须在数据管线剔除，否则
   池/脚本审计假阳性。

---

## 9. 复现与产物

```bash
cd /Users/letiangao/HSAgent/HSBRSIM
python3 tools/p2_delta/run_all.py
# 输出：
#   runs/p2_delta/at_content.json            （AT 注册表 + 与 CONTENT.md 交叉校验）
#   runs/p2_delta/coverage_matrix.json       （本文全部数字的唯一事实来源）
#   runs/p2_delta/summary.md                 （覆盖/缺失/变更 markdown 表）
#   runs/p2_delta/missing_pool_minions.md    （池内缺失 15 张逐条表）
#   runs/p2_delta/ops_probe.json             （17 项操作核对 + file:line 证据）
```

* 工具全部只读输入（AT 仓库 / `data/` / `hsrl2/scripts`），只写 `runs/p2_delta/`；
* 输出 JSON 确定性（无时间戳、固定排序），重复运行逐字节一致；
* 本文所有数字可在 `coverage_matrix.json` / `ops_probe.json` 中按字段复核；
* 相关文档：`docs/AUTOTAVERN_P2_KICKOFF.md`（P2 总计划）、
  `docs/LIVE_TO_SIM_GAP.md`（live 操作缺口）、
  `docs/AUDIT_ENGINE_MECHANICS.md`（hsrl2 机制审计，本文引用其 G-xx 编号）、
  `docs/CONFORMANCE_AUTOTAVERN.md`（跨引擎对拍台账）。
