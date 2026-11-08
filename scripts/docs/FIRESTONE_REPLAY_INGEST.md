# Firestone Web 回放抓取与接入（BG）

> 状态：**已落地**。500 局最近 BG 回放（XML + post-match stats）已落盘到
> `data/firestone_replays/`，解析为 10,811 行人类战团库 +
> 149,166 条逐动作样本。`human_board_pool` 可直接加载。
>
> 采集时间：2026-10-31；feed 覆盖 2026-10-26 ~ 2026-10-31（最近 5 天）。

## 0. TL;DR

| 项 | 结果 |
|---|---|
| 列表来源 | `https://static.zerotoheroes.com/api/bgs/bgs-perfect-games.json`（1000 条，最近约 5 天） |
| 回放 XML | `https://xml.firestoneapp.com/<replayKey>`（zip 内 `replay.xml`，HSReplay 格式，~11 MB/局） |
| 结构化战团 | `https://bgs-post-match-stats.firestoneapp.com/<reviewId>.gz.json`（~190 KB/局） |
| 单条元数据（可选） | `GET https://itkmxena7k2kkmkgpevc6skcie0tlwmk.lambda-url.us-west-2.on.aws//<reviewId>`，header `x-firestone-client: coliseum` |
| 抓取规模 | 500 局，XML 335 MB（zip），PMS 120 MB，0 失败 |
| 解析结果 | 10,811 行战团帧（6,119 self + 4,692 opponent），149,166 条动作 |
| 字段覆盖 | board/tier/hero_hp/main_placement 100%；hero 97.4%；gold 56.6%；hand 55.2%；placement（self）56.6%；keywords 75.4% |
| 卡表映射 | 58,850 个随从提及，**0 个未映射** |
| `human_board_pool` | 10,811 行读入，10,806 行可用（5 行 `stat_outlier`），payload 10,806 |
| 与 `bc_samples` 重叠 | **0 局**（两批 reviewId 完全不相交） |

Cloudflare **没有**成为障碍：三个公开端点直接 `urllib`/`Invoke-WebRequest`
带浏览器 UA + `Referer: https://replays.firestoneapp.com/` 即可 200。
不需要 Playwright、无头浏览器或登录态。

---

## 1. 端点是怎么找到的

### 1.1 Web 回放站只有「查看器」，没有公开列表 API

`https://replays.firestoneapp.com/` 是 Angular SPA（`main.ccdf36e2f81aae1c.js`），
页面只处理 `?reviewId=<uuid>`。`source=replays-list` 只是 analytics 参数
（见桌面端 bundle：`` `...?reviewId=${reviewId}&source=replays-list` ``），
**不是**列表接口。

Web bundle 里的加载链：

```js
// main.*.js  ReplayLoadService
const RETRIEVE_REVIEW_URL = 'https://itkmxena7k2kkmkgpevc6skcie0tlwmk.lambda-url.us-west-2.on.aws/';
const REPLAY_API = 'https://xml.firestoneapp.com/';

fetchReviewMetadata(reviewId) {
  return api.callGetApi(`${RETRIEVE_REVIEW_URL}/${reviewId}`, {
    headers: { 'x-firestone-client': 'coliseum' },   // overwolf | desktop | coliseum
  });  // -> { replayKey, replayUrl?, playerDecklist? }
}

downloadReplayXml({ replayKey, replayUrl }) {
  const url = replayUrl ?? REPLAY_API + replayKey;   // 直链，无签名
  // .zip -> unzip 第一个文件；否则按 text/xml 读取
}
```

实测：

```text
GET https://itkmxena7k2kkmkgpevc6skcie0tlwmk.lambda-url.us-west-2.on.aws//<reviewId>
x-firestone-client: coliseum
-> 200 {"reviewId":"...","replayKey":"hearthstone/replay/2026/10/30/<uuid>.xml.zip", ...}
```

`replayKey` 形如 `hearthstone/replay/YYYY/MM/DD/<reviewId>.xml.zip`，
直接拼到 `https://xml.firestoneapp.com/` 即可下载，没有 presigned URL。

### 1.2 桌面端 bundle 里也没有「最近回放」列表

Overwolf 桌面端 `main.*.js` 的 Replays 页是：
- 本机记录的对局（IndexedDB / 本地文件）；
- 公开的 *perfect games* feed：

```js
const RETRIEVE_PERFECT_GAMES_ENDPOINT =
  'https://static.zerotoheroes.com/api/bgs/bgs-perfect-games.json';
// map(res => GameStat.create({...res, bgsPerfectGame: true, additionalResult: '1'}))
```

因此 **没有**「最近 N 局全部玩家回放」的公开接口；可用的公开种子就是
`bgs-perfect-games.json`。本任务用它作为「最近回放」列表。

### 1.3 post-match stats（战团的首选来源）

桌面端 bundle 还有：

```js
`https://bgs-post-match-stats.firestoneapp.com/${reviewId}.gz.json`
```

返回 Firestone 自己从回放重建的逐回合统计：`boardHistory`、`battleResultHistory`
（含双方完整 `battleInfo`）、`hpOverTurn`、`tavernTimings`、`rerollsOverTurn`、
`minionsBoughtOverTurn`、`leaderboardPositionOverTurn`、`oldMmr/newMmr` 等。
详见第 4 节。

---

## 2. 抓取（可复现）

### 2.1 命令

```bash
# 1) 列表 feed + XML zip + PMS JSON（并发 4，失败重试 2，只补缺失）
python scripts/fetch_firestone_replays.py \
    --root data/firestone_replays --limit 500 --workers 4

# 2) XML + PMS -> 人类战团库 + 动作样本
python scripts/parse_firestone_replay_xml.py --workers 8
```

输出：

| 路径 | 内容 | 大小 |
|---|---|---|
| `data/firestone_replays/bgs-perfect-games.json` | 原始 feed（1000 条） | 5.8 MB |
| `data/firestone_replays/index.json` | 本次 500 局的元数据 | 4.2 MB |
| `data/firestone_replays/xmlz/<reviewId>.xml.zip` | 原始回放 XML（zip） | 335 MB |
| `data/firestone_replays/pms/<reviewId>.json` | post-match stats | 120 MB |
| `data/real_library/library_firestone_recent.jsonl` | 战团库（每行一帧） | 20 MB |
| `data/firestone_replays/firestone_recent_actions.jsonl.gz` | 动作样本 | 3.7 MB |
| `data/real_library/library_firestone_recent_stats.json` | 统计 | 6 KB |

礼貌约束：并发 ≤4、每请求重试 ≤2、总量 500（脚本支持最多 1000）。
XML 单局 0.6–1.1 MB（zip），解压后约 11 MB。

### 2.2 本地探索记录（不是最终路径）

探索时抓取脚本放在 Windows 本地 `C:\Users\letgao\firestone_replays\`
（`fetch_replays.py` / `fetch_pms.py`），最终数据已用 scp 上传到远端
`data/firestone_replays/`。仓库里的 `scripts/fetch_firestone_replays.py`
是合并后的可复现版本。

### 2.3 feed 语义与偏差（重要）

`bgs-perfect-games.json` 是 Firestone 的 **curated「perfect game」** 列表，
不是随机最近对局：

- 1000 条覆盖约 5 天；本次取最近 500 条；
- 491/500 最终名次 = 1（来自 XML tag 1373），9 局为 2/4/5/6/7；
- MMR 4,003–14,816，中位数约 6.5k（**不是** 10k+ 高分段）；
- 因此它是「近期、偏强、偏赢」的战团分布，不能当作无偏天梯采样。

---

## 3. XML 结构映射

### 3.1 文件形态

`<reviewId>.xml.zip` 内只有一个 `replay.xml`：

```xml
<?xml version="1.0" encoding="utf-8"?>
<HSReplay>
  <Game ts="..." buildNumber="255790" type="0" gameType="23" formatType="1" ...>
    <GameEntity id="10"> <Tag tag="..." value="..."/> ... </GameEntity>
    <Player id="11" isMainPlayer="true" name="..."> <Tag .../> </Player>
    <Player id="12" isMainPlayer="false" ...> ... </Player>
    <FullEntity id="..." cardID="BG31_149"> <Tag .../> </FullEntity>
    <ShowEntity entity="..." cardID="..."> ... </ShowEntity>
    <TagChange entity="..." tag="..." value="..."/>
    <Block type="7" entity="..." target="..."> ... </Block>
    <Block type="1" entity="..." target="..."> ... </Block>
    <Choices><Choice entity="..." index="0"/></Choices>
  </Game>
</HSReplay>
```

一局约 11 MB / 8 万 Tag+TagChange / 4,500 Block。`Tag`/`TagChange` 是
**扁平事件流**，实体状态需要自己维护。

### 3.2 关键 tag（本解析器用到）

| tag | 含义 | 备注 |
|---|---|---|
| 20 | `TURN` | 主玩家实体上 = BG 回合（1 起）；GameEntity 上是全局 turn |
| 26 | `RESOURCES` | 金币（主玩家实体） |
| 27 | `HERO_ENTITY` | 玩家 -> 英雄实体 id |
| 44/45 | `DAMAGE` / `HEALTH` | 英雄/随从当前生命 |
| 47 | `ATK` | 随从攻击 |
| 49 | `ZONE` | 1=PLAY，3=HAND，6=SETASIDE，4=GRAVEYARD |
| 50 | `CONTROLLER` | 玩家 controller（4/12…） |
| 53 | `ENTITY_ID` | 分组时用来识别实体 |
| 263 | `ZONE_POSITION` | **0 起**（0..6 棋盘，0..7 酒馆） |
| 12 | `PREMIUM` | 金色（也看 card_id `_G` 后缀） |
| 190/189/194/1085/363/849/191 | TAUNT/WINDFURY/DIVINE_SHIELD/REBORN/POISONOUS/MAGNETIC/STEALTH | 关键词 |
| 1377 | `PLAYER_TECH_LEVEL` | 玩家 = 酒馆等级；随从 = 酒馆 tier |
| 1373 | `PLAYER_LEADERBOARD_PLACE` | **最终名次**（英雄实体上） |
| 292 | `ARMOR` | 英雄护甲 |

> 名次 tag 1373 是从桌面端 bundle 的 `GameTag["PLAYER_LEADERBOARD_PLACE"] = 1373`
> 确认的；实测 500 局 100% 可读到，491 局为 1。

### 3.3 Firestone XML 的两个坑

1. **合并式 `<GameEntity>`**：每个 phase 边界，Firestone 会把
   `GameEntity + Player 11 + Player 12 + 英雄` 的 tag 合并写进同一个
   `<GameEntity id="10">`。直接按父元素归属会把玩家 tag 错写到 GameEntity。
   解析器按 `tag 50 (CONTROLLER)` + 已出现 `tag 53` 分组，组的实体 id 取组内 `53`。
2. **Block 自闭合**：本批 4,490 个 Block 中 1,524 个是 `<Block ... />`
   （无 end 事件），2,966 个有 `</Block>`。解析器用 start/end 栈配对，
   自闭合块只参与 start。

### 3.4 Block type

| type | 含义 | 用途 |
|---|---|---|
| 1 | ATTACK | 战斗开始；每回合首个 ATTACK 触发战团快照 |
| 7 | PLAY | 买/卖/刷新/升级/技能/打出手牌（按 entity cardID 分类） |
| 12 | MOVE_MINION | 换位（本库未纳入，可扩展） |
| 3/5 | POWER / DEATHRATTLE | 战斗内效果，不当作玩家动作 |

动作分类（Block type 7 的 entity cardID）：

| cardID 特征 | action_type | 动作空间 |
|---|---|---|
| `TB_BaconShop_DragBuy` | `buy_minion` | `8+slot` |
| `TB_BaconShop_DragBuy_Spell` | `buy_spell` | `15` |
| `TB_BaconShop_DragSell` | `sell` | `16+slot` |
| `TB_BaconShop_8p_Reroll_Button` | `reroll` | `1` |
| `TB_BaconShopLockAll_Button` | `freeze` | `2` |
| `TB_BaconShop_TechUp` | `upgrade` | `3` |
| `TB_BaconShop_HP_*` | `hero_power` | `4` |
| `TB_BaconShop_Triples_*` | `triple` | 选项未知，`null` |
| `TB_BaconShop_DarkGift*` | `dark_gift` | `6` |
| 卡表 kind=minion | `play_minion` | `46+hand*8+pos` |
| 卡表 kind=spell/tavern_spell | `play_spell` | `46+hand*8+pos` |

### 3.5 XML 自身战团的局限

- **自己**的战团在首刀前是完整的，去重后与 PMS 实际战斗自战团的
  Jaccard p50 = 1.0、mean = 0.929、exact 4,159/5,707。
- **对手**战团在 XML 里是战斗中逐步 `ShowEntity` 揭示的；首刀时不一定
  全部可见，且上一场战斗的复制体/遗留实体会污染 zone=1。因此
  **对手战团不用 XML 重建**，改用 PMS 的 `battleInfo.opponentBoard`。
- 回合 1/2 等没有战斗的回合没有 ATTACK block；解析器在 tag 20
  递增时补一张 `turn_end` 快照。

---

## 4. PMS（post-match stats）结构与选帧

`https://bgs-post-match-stats.firestoneapp.com/<reviewId>.gz.json`
（HTTP 头是 gzip，`urllib` 自动解压）顶层键：

```text
heroesOffered, tavernTimings, tripleTimings, coinsWastedOverTurn, rerolls,
boardHistory, rerollsOverTurn, freezesOverTurn, mainPlayerHeroPowersOverTurn,
hpOverTurn, totalStatsOverTurn, compositionsOverTurn, minionsBoughtOverTurn,
minionsSoldOverTurn, damageToEnemyHeroOverTurn, wentFirstInBattleOverTurn,
battleResultHistory, faceOffs, playerIdToCardIdMapping,
leaderboardPositionOverTurn, oldMmr, newMmr
```

关键：`battleResultHistory[i].battleInfo`：

```json
{
  "playerBoard": {
    "player": {"tavernTier": 5, "hpLeft": 25, "cardId": "BG22_HERO_305_SKIN_A4",
               "heroPowers": [...], "hand": [...], "trinkets": [...], ...},
    "board": [
      {"cardId": "BG36_511", "attack": 1119, "health": 39, "maxHealth": 39,
       "taunt": true, "divineShield": false, "reborn": true,
       "tags": {"PREMIUM": 1, "TECH_LEVEL": 4, ...}}
    ]
  },
  "opponentBoard": { ... 同结构 ... },
  "gameState": {...}
}
```

`battleResultHistory` 里同时有**实际战斗**和 Firestone 用已知对手 board 做的
**scouting/模拟**条目。实际战斗的判据是 `actualResult != null`
（`won/tied/lost`）；其余条目只有 `simulationResult`。

本批 500 局共 **6,392** 条 `battleInfo`，其中 **5,707** 条是实际战斗。
解析器用「自战团 card-id 多重集 Jaccard + 唯一回合匹配」把实际战斗对到
XML 回合：

- 匹配 5,546 / 5,707 = **97.2%**
- Jaccard p50 = **1.0**，mean = **0.929**
- 完全一致 4,159 条

匹配上的回合，战团（双方）、酒馆等级、英雄血量改用 PMS（更完整）；
没匹配上的回合保留 XML 自战团，**不生成对手帧**（宁缺毋滥）。

> 两个容易踩的坑：
> 1) PMS 的 `leaderboardPositionOverTurn` **不是最终名次**。实测同一局
>    XML `tag 1373 = 1`，而 PMS 末值为 4；本库名次一律以 XML 1373 为准。
> 2) `faceOffs` / `battleResultHistory` 里同一回合可能有多条对手记录
>    （Firestone 用已知 board 做 scouting 模拟），只有 `actualResult != null`
>    是实际战斗；不要按 `turn` 字段直接配对。

---

## 5. 库 schema

`data/real_library/library_firestone_recent.jsonl`：一行一个
`(game_id, turn, perspective)` 战团帧。schema 对齐
`library_real_quasi_full.jsonl` / `hsbg.human_state_quasi_full`。

| 字段 | 类型 | 来源 / 说明 |
|---|---|---|
| `turn` | int | XML tag 20（主玩家回合，1 起）；PMS 匹配帧沿用该回合 |
| `strength` | int | `Σ(atk+hp)` |
| `board` | `[[card, atk, hp], ...]` | card = 引擎 `cards.json` 下标（cid） |
| `board_detail` | list[dict] | `card/card_id/atk/hp/golden/kw/bonus_kw/shield_max/position` |
| `hand` | list[dict] | 仅 self；`card/card_id/kind/atk/hp/golden/kw` |
| `hand_available` | bool | self=true；opponent=false |
| `hand_n` | int | 手牌数 |
| `tier` | int | 酒馆等级（PMS `tavernTier` / XML tag 1377） |
| `gold` | int/null | XML tag 26（self）；opponent=null |
| `hero` | int/null | 英雄 cid（skin 归一化到卡表） |
| `hero_card_id` | str | 原始英雄/皮肤 id |
| `hero_hp` | int | PMS `hpLeft` / XML tag 45 |
| `hero_armor` | int/null | XML tag 292（self） |
| `placement` | int/null | XML tag 1373；仅 self 帧（opponent 帧为 null） |
| `main_placement` | int | XML tag 1373；记录玩家最终名次，所有帧都有 |
| `perspective` | `self`/`opponent` | 视角 |
| `source` | str | `firestone_pms+xml` / `firestone_xml` / `firestone_pms_opponent` |
| `actual_battle` | bool | 是否 PMS 实际战斗（对手帧必 true） |
| `action_counts` | dict | 该回合 XML 动作计数（self） |
| `availability` | dict | 逐字段 observed/unavailable |
| `game_id` / `build_number` / `mmr` / `archetype` / `tribes` / `banned_tribes` | | feed 元数据 |
| `split` | `train`/`evaluation` | `md5(game_id) % 10`，约 10% eval |

### 5.1 规模与覆盖

| 指标 | 数值 |
|---|---|
| 行数 | 10,811（6,119 self + 4,692 opponent） |
| 来自 PMS | 9,204；纯 XML 自战团 1,607 |
| 去重移除 | 1,327（同 turn + 同战团/手牌/tier + 同视角） |
| 每局平均 | 24.3 帧 |
| 棋盘大小 | 1:544 / 2:868 / 3:964 / 4:739 / 5:863 / 6:1,424 / 7:5,409 |
| 空战团 | 0 |
| 随从提及 | 58,850，未映射 **0** |
| MMR | 4,003–14,816 |

字段覆盖率（分母 10,811）：

| 字段 | 覆盖率 | 说明 |
|---|---|---|
| board / tier / hero_hp / main_placement | 1.000 | |
| placement（self） | 0.566 | opponent 帧无「对方名次」，用 `main_placement` 表示记录者名次 |
| hero（cid） | 0.974 | 少数皮肤 id 不在 37.0 卡表 |
| keywords | 0.754 | 仅统计「至少一个随从有关键词」的行 |
| golden | 0.485 | 仅统计「至少一个金色随从」的行 |
| gold | 0.566 | 仅 self 帧 |
| hand | 0.552 | 仅 self 且 PMS/XML 有手牌信息 |

最终名次分布：1×491，2×1，4×4，5×2，6×1，7×1 —— 再次说明 feed 是
curated perfect games，不是随机天梯。

### 5.2 每回合强度（p50 / p90）

| turn | n | p50 | p90 |
|---|---|---|---|
| 1 | 195 | 6 | 9 |
| 2 | 325 | 7 | 14.6 |
| 3 | 863 | 16 | 26 |
| 4 | 946 | 26 | 43 |
| 5 | 956 | 40 | 66 |
| 6 | 941 | 64 | 110 |
| 7 | 902 | 103 | 195.9 |
| 8 | 864 | 163 | 365.4 |
| 9 | 819 | 313 | 935.6 |
| 10 | 799 | 731 | 2,584.6 |
| 11 | 788 | 1,722.5 | 6,746.7 |
| 12 | 786 | 3,267.5 | 13,762 |
| 13 | 797 | 6,432 | 28,980 |
| 14 | 511 | 11,060 | 49,130 |
| 15 | 228 | 21,167 | 84,165.2 |

早期回合行数偏少主要是**去重**（turn 1/2 的战团高度重复），不是采集缺失。

### 5.3 与现有 10k+ 库的强度对比

`library_real_degraded.jsonl` 是 10k+ MMR 观测，本库是 4k–15k 的 curated
perfect games，因此**不能**用它替代高分段校准库：

| turn | degraded p50 | firestone p50 |
|---|---|---|
| 5 | 48 | 40 |
| 8 | 261 | 163 |
| 10 | 1,144 | 731 |
| 12 | 4,858 | 3,267.5 |
| 15 | 29,729 | 21,167 |

用途应是「近期 meta 多样性 / perfect-game 上限样本」的补充，而不是替代。

---

## 6. 动作样本

`data/firestone_replays/firestone_recent_actions.jsonl.gz`：149,166 行，
每行一个 XML Block type=7 动作（外加每回合 `end_turn` 一条）。

| 字段 | 说明 |
|---|---|
| `game_id` / `turn` | reviewId / 回合 |
| `action_type` | 见 3.4 |
| `card_id` / `target_card_id` | 动作卡 / 目标卡（买/卖的目标随从） |
| `entity_id` / `target_id` | 客户端实体 id（跨局不可复用，仅调试） |
| `gold` / `tier` / `health` / `armor` | 动作发生前的主玩家状态 |
| `board_cards` / `hand_cards` / `shop_cards` | 动作前快照（原始 card_id 字符串） |
| `shop_slot` / `board_slot` / `hand_slot` / `play_pos` | 0 起槽位 |
| `action_index` | `hsbg/env/action_space_std.py` 下标；null=不可映射 |

动作分布（500 局）：

| action_type | 数量 | 可映射率 |
|---|---|---|
| play_minion | 38,752 | 0.948 |
| play_spell | 28,835 | 1.000 |
| sell | 25,283 | 1.000 |
| reroll | 20,038 | 1.000 |
| buy_minion | 12,073 | 1.000 |
| end_turn | 6,827 | 1.000 |
| buy_spell | 6,741 | 1.000 |
| triple | 2,866 | 0（选项未知） |
| hero_power | 2,621 | 1.000 |
| upgrade | 2,424 | 1.000 |
| dark_gift | 1,444 | 1.000 |
| freeze | 1,262 | 1.000 |
| **合计** | **149,166** | **0.967** |

`triple` 之外的不可映射只有 198 条 `play_minion`（手牌/落位槽位越界，保守置 null）；
`sell` / `buy` / `reroll` / `freeze` / `upgrade` / `hero_power` 均已 100% 可映射。

### 6.1 动作计数与 PMS 交叉验证

把 XML 每局动作计数与 PMS 的逐回合聚合对比（500 局）：

| 动作 | 完全一致的局占比 | 每局平均绝对误差 | XML 总数 / PMS 总数 |
|---|---|---|---|
| buy_minion | 0.950 | 0.11 | 12,073 / 12,020 |
| sell | 0.946 | 0.28 | 25,283 / 25,141 |
| reroll | 0.932 | 0.51 | 20,038 / 19,784 |
| freeze | 0.994 | 0.01 | 1,262 / 1,258 |
| hero_power | 0.958 | 0.07 | 2,621 / 2,587 |

差异 < 0.5%，说明 XML Block 解析没有系统性漏抓。

---

## 7. 与 `data/firestone_bc/bc_samples.jsonl.gz` 的关系

| 项 | `bc_samples.jsonl.gz` | 本库 |
|---|---|---|
| 来源 | 1000 局 Firestone full replays（`events.jsonl.gz`，扁平事件流） | 500 局 Web 回放（原始 HSReplay XML + PMS） |
| 粒度 | 决策样本（每个动作一行） | 战团帧（每回合每视角一行）+ 动作样本 |
| 行数 | 308,944 | 10,811 帧 + 149,166 动作 |
| reviewId | 1000 个 | 500 个，与前者 **交集 0** |
| 主要用途 | BC / 动作监督 | `human_board_pool` 战团注入 / 近期 meta 多样性 |

两者**互补，不互相替代**：

- BC 训练继续用 `bc_samples.jsonl.gz`（覆盖 1000 局、动作更全）；
- 战团分布/注入用 `library_firestone_recent.jsonl`（PMS 双方完整战团、
  金色/关键词/圣盾层数/tier 齐全）；
- 如需合并动作样本，以 `(game_id, turn, action_type, card_id, target_card_id,
  board_cards, hand_cards)` 为键去重；两批 game_id 不相交，当前无需去重。

### 7.1 去重策略

1. **局级**：`game_id = reviewId`，跨批直接判重（当前 0 重叠）。
2. **帧级**：`(turn, board_detail(card/atk/hp/golden/kw), hand(card/kind), tier,
   perspective)`；本次移除 1,327 行完全重复帧。
3. **动作级**：`(game_id, turn, action_type, card_id, target_card_id,
   board_cards, hand_cards)`；同一局内重复动作（如连续 reroll）保留。

---

## 8. 接入训练：`human_board_pool` 改动点

### 8.1 已经可以直接用

`HumanBoardPool` 的 `_row_to_board` 只要求 `turn / board / strength`，并识别
`board_detail` 生成准完整 payload。本库 10,811 行全部通过：

```bash
PYTHONPATH=rust/python:. python - <<'PY'
from hsbg.az.train.human_board_pool import HumanBoardPool
p = HumanBoardPool('data/real_library/library_firestone_recent.jsonl')
print(p.rows, p.kept, p.payload_kept, p.filtered)
# 10811 10806 10806 {'stat_outlier': 5}
PY
```

训练命令把 `--human-boards` 指到新文件即可：

```bash
python scripts/train_az_ppo.py ... \
  --human-boards data/real_library/library_firestone_recent.jsonl \
  --human-board-fidelity hand    # 或 full
```

### 8.2 建议的下一步改动（按优先级）

1. **`human_board_pool._row_to_payload` 传递 `gold` / `hero_hp` / `main_placement`**：
   当前 payload 里 `gold` 硬编码 `None`，而本库 self 帧有 56.6% 的
   `gold`。如果 `human_obs_full.inject_quasi_state` 接受 `gold`，可直接注入；
   否则至少在 payload 里保留，供采集 meta 记录。
2. **新增 `source=human_board_firestone_recent` 常量**（或在
   `HumanBoardPool.stats()` 里区分 `firestone_pms+xml` / `firestone_xml`），
   避免日志里和旧 `human_board_approx` 混淆。
3. **混池而不是替换**：建议把新库与 `library_real_quasi_full.jsonl` /
   `library_real_degraded.jsonl` 合并后按 turn 分桶；新库补近期 meta 和
   perfect-game 上限，旧库保留 10k+ 校准。合并时用 7.1 的帧级签名去重。
4. **对手帧的使用**：`perspective=opponent` 的行是真实对手战团，但
   `hand_available=false`、`gold=null`；`--human-board-fidelity full` 时应
   跳过对手 hand 注入，或只注入 board + counters。
5. **`actual_battle` 过滤**：如需「真实对战」严格配对，只用
   `actual_battle=true` 的行（9,204 行）；做纯战团分布时可用全部。

### 8.3 风险 / 偏差

- feed 是 curated perfect games：491/500 第一，MMR 中位 6.5k；
  **不能**当作天梯无偏采样，也不应当作 10k+ 强度校准。
- 对手战团只来自 PMS 实际战斗（5,546 帧），scouting 模拟未入池。
- XML 自战团在极少数回合（无 ATTACK block）用 `turn_end` 回退，可能包含
  战斗后的幸存者（无战斗回合则等价 recruit-end）。
- `gold` 是战斗开始前的剩余金币，不是回合收入；PMS 没有 gold 字段。
- `hero` 有 2.6% 皮肤 id 无法映射到 37.0 卡表（只影响 hero cid，不影响 board）。

---

## 9. 复现与验收

```bash
# 抓取（可只抓 10 局先验证）
python scripts/fetch_firestone_replays.py --root /tmp/fs --limit 10 --workers 4

# 解析（先 10 局）
python scripts/parse_firestone_replay_xml.py --limit 10 --workers 4 \
  --out /tmp/fs_lib.jsonl --stats /tmp/fs_stats.json \
  --actions-out /tmp/fs_actions.jsonl.gz

# 全量（本次结果）
python scripts/fetch_firestone_replays.py --limit 500 --workers 4
python scripts/parse_firestone_replay_xml.py --workers 8
```

期望：

```text
games=500 workers=8
rows=10811 actions=149166 games=500 errors=0 elapsed≈79s
```

关键验收数：

- `games.xml_ok = 500`，`games.pms_ok = 500`，`errors = 0`
- `rows.total = 10811`，`card_mapping.unmapped = 0`
- `battles.match_rate_of_actual = 0.972`，`match_jaccard_p50 = 1.0`
- `actions.mappable_ratio = 0.967`
- `HumanBoardPool(...).kept = 10806`，`payload_kept = 10806`

解析只走 CPU（8 进程，80 秒），不占 GPU；不触碰远端其它用户进程。

---

## 10. 已知未做 / 可扩展

- **没有**公开「最近全部玩家回放」列表；若需要更高 MMR / 随机对局，只能：
  1) 用本地已登录的 Firestone/Overwolf 客户端记录（桌面端 Replays 是本地库）；
  2) 从 `bgs-post-match-stats` 的 `faceOffs` / `battleResultHistory` 里反向
     收集其它玩家 board（本库已用于对手帧）；
  3) 等待 Firestone 提供新的 public feed。
- XML `Block type=12` 换位动作未纳入动作样本（可补 `reposition`，
  `action_index=196+from*7+to`）。
- `triple` 的 `Choices/Choice` 选项未解析（当前 `action_index=null`）。
- 对手手牌/金币不可得（客户端视角限制），未编造。
- 原始 XML/PMS 未入 git（`.gitignore` 已排除），只在远端磁盘保留；
  需要长期归档时建议单独对象存储，而不是提交仓库。
