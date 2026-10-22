"""批次 trinkets29 台账守卫 + 引擎缺口守卫（本批 30 张作业范围，当前
DEFERRED 17 张；已迁出 13 张，作业单 2026-09-14）。

本批 `register()` 返回**空列表**——30 张逐张复评为"无法用现有原语做成语义
精确实现"（SOP §6b 二态铁律），因此**没有行为层可测**。按 TEST_SOP 与
`audit_vacuous_tests.py` 的口径，本文件只包含**结构性守卫**（注册表 /
DEFERRED 台账 / 数据链 / 卡面文本漂移 / 引擎缺口），两个测试类均显式标注
`@engine-only`，避免被空转审计误判为"行为测试空转"。
（777 Goose Portrait 于 2026-09-17 由 batch_goose_lucky_egg 注册迁出；
其行为层测试见 test_batch_goose_lucky_egg.py。）

**通用覆盖项在本批不适用**（无注册卡 → 无效果可探针）:
  - 正效果 + 同方法内负/正对照 / owner 隔离 / 跨回合·一次性 / 落空不消耗
    资源 / 池占返配平（含金色 `GILDED_NOT_TRIPLED`）/ 满手队列 /
    `len(options) == N` / 双施（per-cast）/ Titus / 两份副本 / 同 seed
    确定性 —— 全部属于"已注册卡的行为验证"，本批 0 注册故不存在可被跳过
    的同类卡（对照 batch_trinkets27/28 的同类声明）。
  - 本文件的替代价值: **DEFERRED 台账守卫**（防静默注册第三态）+
    **引擎缺口守卫**（缺口闭合时转红 → 提示可解冻对应卡）。

守卫语义:
  1. `TestBatch29Ledger` —— 30 个 id 存在 / 可提供 / 未注册 / docstring
     含 Status+Dependency+Implementation path / 不带任何钩子方法 / 数值与
     数据链与卡面文本逐张钉死。
  2. `TestBatch29EngineGaps` —— 每个阻塞族的**引擎现状**（缺什么）用运行时
     事实钉死: 缺口一旦闭合，本类转红 → 该族卡片可进入解冻流程。
"""

from __future__ import annotations

import importlib
import inspect
import re
import unittest
from pathlib import Path

from hsrl2 import events as hsrl2_events
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.scripts import REGISTRY
from hsrl2.tags import CardType, GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
BATCH_MODULE = "hsrl2.scripts.batches.batch_trinkets29"

# 本批 30 张（CardDB 按名核实——禁止凭记忆写 id）
# 777 Goose Portrait 已由 batch_goose_lucky_egg 注册（2026-09-17——次生
# 载荷 `BG30_104`/`_G` 由本批补齐）→ 移出本 DEFERRED 台账
DEFERRED_IDS = (
    # A. 载荷 / 家族改写通道缺失
    "BG30_MagicItem_402",   # Conductor Portrait — 弃牌系统 + 载荷未注册
    "BG30_MagicItem_431",   # Azerite Portrait — 载荷 BG28_707 未注册
    "BG32_MagicItem_806",   # Battlecruiser Portrait — Upgrade 附着子系统
    # B. 多值种族 RACES（0）——418 / 825 / 971 / 179 已由 batch_family_races
    # 注册（2026-09-21，家族类型身份改写 + owner 作用域）→ 全部移出本台账
    # C. 子系统 / 引擎原语缺失（12）
    "BG30_MagicItem_416",   # Token of the Old Gods — 两段定向选择链
    "BG30_MagicItem_707",   # Tickatus Sticker — Darkmoon Prize 卡表
    "BG30_MagicItem_711",   # Marine Signet — improve 档位递增权威
    "BG32_MagicItem_809",   # Gem Donation — 宝石枚数读法
    "BG30_MagicItem_994",   # Yogg-Tastic Pastry — Wheel of Yogg
    "BG32_MagicItem_300",   # Putricide Sticker — Craft 合成链
    # BG32_MagicItem_804 Selfless Portrait 已由 batch_trinkets35 注册
    # （2026-09-13，RULES §7.4.17 条件化战吼协议——载荷
    # `SelflessHeroScript` 声明 `battlecry_flag` +
    # `FLAG_SELFLESS_BATTLECRY`，引擎 `Game.has_battlecry` /
    # `granted_battlecry` 按开关判定）→ 移出本台账
    # BG32_MagicItem_803 Macaw Portrait 已由 batch_trinkets36 注册
    # （2026-09-13，RULES §7.4.17 条件化战吼第二消费者——载荷
    # `MonstrousMacawScript.rally` 读 `FLAG_MACAW_EXTRA_BATTLECRY` 追加
    # 最左战吼; 资格集口径由 32.2 论坛复现串 `M G x B y z` 裁定）→ 移出
    # 本台账
    # BG32_MagicItem_274 Bristlebach Portrait 已由 batch_trinkets34 注册
    # （2026-09-13，`hero.family_flags` + `Game.add_family_flag` /
    # `family_flag` 行为开关通道 → 载荷 `BristlebachScript.avenge`
    # 读 `FLAG_SCOPE_ALL_FRIENDLY`）→ 移出本台账
    # BG32_MagicItem_417 Tarecgosa Sticker 已由 batch_trinkets30 注册
    # （`PERSIST_BONUS_ONLY` + `PERSIST_COMBAT_CHANGES` 战斗持久化通道，
    # 2026-09-15）→ 移出本台账（仍计入本批 30 张作业范围）。
    # BG30_MagicItem_803 Kaboom Bot Portrait 已由 batch_trinkets39 注册
    # （2026-09-18——家族亡语伤害加成读取点 RULES §7.4.16 `family_flags`
    # + 载荷侧 `FLAG_KABOOM_DR_BONUS`; 金色逐实例 +10 按 wiki 无 Notes →
    # 卡面天然语言）→ 移出本台账。
    # 868 / 869 / 987 / 283 已由 batch_trinkets31 注册（2026-09-19——owner
    # 权威序: wiki 页均无 Notes 段 → 卡面天然语言 "also give X" 增量 =
    # 同句既有量; 869 的两载荷同批注册）→ 移出本台账。
)

# id → 本批 DEFERRED 脚本类名（docstring 台账守卫用）
_CARD_CLASSES = {
    "BG30_MagicItem_402": "ConductorPortraitScript",
    "BG30_MagicItem_431": "AzeritePortraitScript",
    "BG32_MagicItem_806": "BattlecruiserPortraitScript",
    "BG30_MagicItem_416": "TokenOfTheOldGodsScript",
    "BG30_MagicItem_707": "TickatusStickerScript",
    "BG30_MagicItem_711": "MarineSignetScript",
    "BG32_MagicItem_809": "GemDonationScript",
    "BG30_MagicItem_994": "YoggTasticPastryScript",
    "BG32_MagicItem_300": "PutricideStickerScript",
}

# 卡面文本签名（数据漂移守卫）——每项必须**同时**出现在 CardDef.text 与
# 对应脚本类 docstring 中（normalize 后比较; 见 `_norm`）。
_TEXT_SIGNATURES = {
    "BG30_MagicItem_402": ("Get a Snarling Conductor. Whenever you discard a "
                           "card, this plays a Blood Gem on all your "
                           "minions."),
    "BG30_MagicItem_416": ("Spellcraft: Choose a minion. Then choose a minion "
                           "from a Tier higher to transform it into."),
    "BG30_MagicItem_431": ("Get a Living Azerite. Your Living Azerites also "
                           "give stats to friendly Elementals."),
    "BG30_MagicItem_707": ("Discover a Tier 3 Darkmoon Prize. At the start of "
                           "every three turns, repeat this."),
    "BG30_MagicItem_711": ("After you play 4 minions, get a random Tier {1} "
                           "Tavern spell and improve this."),
    "BG30_MagicItem_994": ("Spin the Wheel of Yogg-Saron. At the start of each "
                           "turn, spin it again."),
    "BG32_MagicItem_300": ("Craft a custom Undead. At the start of every 2 "
                           "turns, repeat this."),
    "BG32_MagicItem_806": ("Get an 12/12 Battlecruiser. Whenever the Tavern is "
                           "Refreshed, add a Battlecruiser Upgrade to it."),
    "BG32_MagicItem_809": ("The first minion you sell each turn plays its "
                           "Blood Gems on the 3 highest-Tier minions in the "
                           "Tavern."),
}

# 有模板参数的 3 张（其余 16 张 num(0..4) 全 None——逐张钉死）
# 440 / 822 已由 batch_trinkets32 注册（2026-09-15）→ 移出本台账
# 828 / 944 已由 batch_trinkets33 注册（2026-09-13）→ 移出本台账
# 777 已由 batch_goose_lucky_egg 注册（2026-09-17）→ 移出本台账
_NUM_PARAMS = {
    "BG30_MagicItem_707": (3, None, None, None, None),
    "BG30_MagicItem_711": (4, 1, None, None, None),
    "BG32_MagicItem_300": (2, None, None, None, None),
}

# 数据链 `evolution_card_id` → 期望关联卡（RULES §7.4.6）
_RELATED_CARDS = {
    "BG30_MagicItem_402": "BG28_585",
    "BG30_MagicItem_431": "BG28_707",
    "BG32_MagicItem_806": "BG31_HERO_801pt",
}

# 无数据链的 10 张（36.2.2 逐条核实 `evolution_card_id` 为空）
_NO_RELATED_CARDS = (
    "BG30_MagicItem_416", "BG30_MagicItem_440",
    "BG30_MagicItem_707", "BG30_MagicItem_711", "BG30_MagicItem_804",
    "BG30_MagicItem_822", "BG30_MagicItem_994", "BG32_MagicItem_300",
    "BG32_MagicItem_809",
)

# 阻塞 A 类的载荷：未注册者（交付/行为不存在）
_UNREGISTERED_PAYLOADS = (
    "BG28_585",         # 402 Snarling Conductor
    "BG31_HERO_801pt",  # 806 Battlecruiser
    "BG30_MagicItem_416t",  # 416 的 Spellcraft 法术
)
# 已迁出（2026-10-18，batch_37x_poolgap2）: BG28_707 Living Azerite（431 载荷）
# —— "Whenever you cast a Tavern spell, give Elementals in the Tavern
# +4/+3 this game（金色 twice）" 已按公开 `tavern_buff` 动作族实现 →
# 载荷本体注册并迁入 `_REGISTERED_PAYLOADS`; 431 AzeritePortrait 的残余
# 阻塞变为**纯 "also give stats to friendly Elementals" 家族通道**（该饰品
# 仍 DEFERRED，待饰品批次解冻）。
# 已迁出（2026-09-20，batch_stats_gained）: BG21_013/`_G`（825 Whelp
# Smuggler 载荷）——引擎 `stats_gained` 原语落地（生产点 `Entity.add_buff`
# + 复制/复原抑制; 触发域逐路径裁定见 ENGINE_BACKLOG §E）→ 载荷本体注册
# 并迁入 `_REGISTERED_PAYLOADS`; 825 的残余阻塞变为**纯类型改写通道**
# （单值家族种族覆写 + 作用域 N5，见 `batch_trinkets29.SmugglerPortraitScript`）。
# 已迁出（2026-09-19，batch_trinkets31 + batch_payload_minions）:
# BG29_873 / BG29_877（869 Felblood Portrait 的两载荷，含金色）→ 移入
# `_REGISTERED_PAYLOADS`; 869 饰品本体同批注册，阻塞整体闭合。
# 已迁出: TB_BaconUps_307（821t2 金色 Fish of N'Zoth）——2026-09-13 对抗
# 验证证伪"回落基础版静默降级 twice"后由 batch_misc_final 注册金色脚本。
# 已迁出（2026-09-16，batch_remaining2）: BG29_801 / BG29_801_G（777
# Silver Goose 基础+金色）、BG_BOT_606 / TB_BaconUps_028（803(30)
# Kaboom Bot 基础+金色）——载荷行为已就绪 → 移入 `_REGISTERED_PAYLOADS`;
# 对应饰品的残余阻塞变为**纯通道**（见各类 docstring）。
# 已迁出（2026-09-17，batch_goose_lucky_egg）: BG30_104 / BG30_104_G
# （777 次生载荷 Lucky Egg 基础+金色）→ 移入 `_REGISTERED_PAYLOADS`;
# 777 饰品本体同批注册，其阻塞整体闭合。

# 阻塞 A 类的载荷脚本标记（载荷侧"extra/also"读取点）——本批上报的 G1;
# 标记落地（缺口闭合）时本守卫转红 → 提示解冻对应饰品。
# 944 Redeemer Portrait / 828 Shaker Portrait 的 extra 通道已于
# 2026-09-13 通过引擎 `hero.giver_bonus` + 载荷消费点闭合
# （batch_trinkets33 注册）→ 两者标记移出本表，见
# `test_giver_bonus_channel_now_available`。
# 274 Bristlebach Portrait 的阻塞已于 2026-09-13 通过引擎
# `hero.family_flags` + 载荷消费点闭合（batch_trinkets34 注册）→
# 其标记移出本表，见 `test_family_flag_channel_now_available`。
# 804 Selfless Portrait 的阻塞已于 2026-09-13 通过引擎"条件化战吼"
# 协议（载荷 `battlecry_flag` + `Game.has_battlecry` /
# `granted_battlecry`，RULES §7.4.17）+ 载荷消费点闭合（batch_trinkets35
# 注册）→ 其标记移出本表，见
# `test_conditional_battlecry_channel_now_available`。
# 803(32) Macaw Portrait 的阻塞已于 2026-09-13 通过同一"条件化战吼"
# 协议（载荷 `MonstrousMacawScript.rally` 读
# `FLAG_MACAW_EXTRA_BATTLECRY`，RULES §7.4.17）+ 32.2 论坛复现串裁定
# 资格集口径闭合（batch_trinkets36 注册）→ 其标记移出本表，见
# `test_macaw_family_channel_now_available`。本批上报的全部载荷通道标记
# 至此**清空**（空容器保留，供后续批次追加标记时沿用同一守卫）。
_FAMILY_CHANNEL_MARKERS = {
    "hsrl2.scripts.batches.batch_payload_minions": (),
}

# 已注册的载荷（本体就绪但改写通道缺失——见各类 docstring）
_REGISTERED_PAYLOADS = (
    "BG26_505",   # 828 Zesty Shaker
    "BG26_174",   # 868 Soul Rewinder
    "BG28_551",   # 944 Nalaa the Redeemer
    "BG26_814",   # 987 Lovesick Balladist
    "BG26_157",   # 274 Bristlebach
    "BG28_741",   # 283 Charging Czarina
    "BG28_707",   # 431 Living Azerite（batch_37x_poolgap2, 2026-10-18）
    "BGS_078",    # 803(32) Monstrous Macaw
    "BG_OG_221",  # 804(32) Selfless Hero
    "BGS_009",    # 971 Lightfang Enforcer
    "BG26_ICC_901",   # 179 Drakkari Enchanter
    "BG_LOE_077",     # 418 Brann Bronzebeard
    "BG29_801",       # 777 Silver Goose（batch_remaining2, 2026-09-16）
    "BG29_801_G",     # 777 Silver Goose 金色（同上）
    "BG_BOT_606",     # 803(30) Kaboom Bot（同上）
    "TB_BaconUps_028",  # 803(30) Kaboom Bot 金色（同上）
    "BG30_104",       # 777 次生载荷 Lucky Egg（batch_goose_lucky_egg,
    "BG30_104_G",     #     2026-09-17——战吼 Discover 金色 T3/T4 变形）
    "BG29_873",       # 869 Slimy Felblood（batch_payload_minions, 2026-09-19）
    "BG29_873_G",     # 869 Slimy Felblood 金色（同上）
    "BG29_877",       # 869 Fiery Felblood（同上）
    "BG29_877_G",     # 869 Fiery Felblood 金色（同上）
    "BG21_013",       # 825 Whelp Smuggler（batch_stats_gained, 2026-09-20）
    "BG21_013_G",     # 825 Whelp Smuggler 金色（同上）——家族"获得攻击力"
                      # 观察点已由 `stats_gained` 原语闭合; 825 残余阻塞
                      # = owner 级家族**单值**类型改写读取点（N5）
)

# 本批 DEFERRED 类**不得**定义任何引擎钩子（防"注册但 no-op"第三态）
_ENGINE_HOOKS = (
    "battlecry", "deathrattle", "start_of_combat", "avenge", "rally",
    "start_of_turn", "end_of_turn", "on_sell", "on_summon", "on_play",
    "activate", "atk", "health", "on_enter_hand", "on_bind",
    "hero_power", "available", "cost_override", "target_candidates",
)

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def _norm(text: str) -> str:
    """卡面文本归一: 去 BBCode 标签、压平空白（卡面/数据换行差异）。"""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def _batch_module():
    return importlib.import_module(BATCH_MODULE)


class TestBatch29Ledger(unittest.TestCase):
    """@engine-only 结构性: 注册表 / DEFERRED 台账 / 数据链 / 卡面文本守卫。

    这些断言与脚本钩子无关（本批 0 注册、各类无钩子）——按 SOP §16 末段
    显式标注 `@engine-only`，避免被空转审计误判为"行为测试空转"。
    """

    def test_registry_ledger_has_zero_registrations(self):
        """本批 CORRECT = 0（SOP §6b 二态铁律）: `register()` 空列表。"""
        mod = _batch_module()
        self.assertEqual(mod.register(), [])
        # 418 / 825 / 971 / 179 已由 batch_family_races 注册（2026-09-21）
        # → 台账由 13 降为 9。
        self.assertEqual(len(DEFERRED_IDS), 9)
        self.assertEqual(len(set(DEFERRED_IDS)), 9)

    # 440 Boom Controller / 804 Ancient Wishbone / 822 Twin Sky Lanterns 已由
    # batch_trinkets32 注册（2026-09-15）→ 移出本 DEFERRED 台账
    # 828 Shaker Portrait / 944 Redeemer Portrait 已由 batch_trinkets33
    # 注册（2026-09-13，`hero.giver_bonus` 通道）→ 移出本台账
    # 803(32) Macaw Portrait 已由 batch_trinkets36 注册
    # （2026-09-13，RULES §7.4.17 条件化战吼第二消费者）→ 移出本台账

    def test_deferred_not_registered_in_registry(self):
        for tid in DEFERRED_IDS:
            self.assertIsNone(REGISTRY.get(tid), tid)

    def test_all_ids_exist_as_bacon_trinkets(self):
        db = get_db()
        self.assertEqual(
            [tid for tid in DEFERRED_IDS if db.get(tid) is None], [])
        for tid in DEFERRED_IDS:
            d = db.get(tid)
            self.assertEqual(d.card_type, CardType.BACON_TRINKET, tid)
            self.assertIn(d.spell_school, (11, 12), tid)   # 11=Lesser/12=Greater

    def test_pool_membership_of_all_ids(self):
        """17/17 在商店可提供集内（含 821t2——`t2` 后缀无同名本体）。"""
        pool = {d.id for d in get_db().trinket_offer_pool()}
        self.assertEqual(
            sorted(tid for tid in DEFERRED_IDS if tid not in pool), [])

    def test_deferred_status_dependency_path_ledger(self):
        mod = _batch_module()
        self.assertEqual(len(_CARD_CLASSES), 9)
        self.assertEqual(set(_CARD_CLASSES), set(DEFERRED_IDS))
        for tid, cls_name in _CARD_CLASSES.items():
            cls = getattr(mod, cls_name, None)
            self.assertIsNotNone(cls, f"{tid} → {cls_name}")
            doc = cls.__doc__ or ""
            self.assertIn("Status: DEFERRED", doc, tid)
            self.assertIn("Dependency:", doc, tid)
            self.assertIn("Implementation path:", doc, tid)
            self.assertIn("阻塞卡:", doc, tid)

    def test_deferred_classes_declare_no_engine_hooks(self):
        """任何 DEFERRED 类**不得**定义钩子（否则可能被误注册 = 第三态）。"""
        mod = _batch_module()
        for tid, cls_name in _CARD_CLASSES.items():
            cls = getattr(mod, cls_name)
            declared = [h for h in _ENGINE_HOOKS if h in vars(cls)]
            self.assertEqual(declared, [], f"{tid} {cls_name} 定义了钩子")

    def test_carddef_text_matches_carddef_and_docstring(self):
        """卡面文本漂移守卫: 签名同时存在于 CardDef.text 与类 docstring。"""
        db = get_db()
        mod = _batch_module()
        self.assertEqual(set(_TEXT_SIGNATURES), set(DEFERRED_IDS))
        for tid, fragment in _TEXT_SIGNATURES.items():
            self.assertIn(fragment, _norm(db.get(tid).text), tid)
            doc = getattr(mod, _CARD_CLASSES[tid]).__doc__ or ""
            self.assertIn(fragment, _norm(doc), tid)

    def test_carddef_num_param_integrity(self):
        """数值纪律: 4 张有参卡的 num(0..4) 逐位钉死; 其余 14 张全 None。"""
        db = get_db()
        for tid in DEFERRED_IDS:
            d = db.get(tid)
            expected = _NUM_PARAMS.get(tid, (None, None, None, None, None))
            self.assertEqual(
                tuple(d.num(i) for i in range(5)), expected, tid)

    def test_related_card_data_drift(self):
        db = get_db()
        for tid, related in _RELATED_CARDS.items():
            evo = db.get(tid).evolution_card_id
            self.assertIsNotNone(evo, tid)
            rel = db.by_dbf(evo)
            self.assertIsNotNone(rel, tid)
            self.assertEqual(rel.id, related, tid)
        for tid in _NO_RELATED_CARDS:
            self.assertIsNone(db.get(tid).evolution_card_id, tid)

    def test_registered_payloads_are_bound(self):
        """A 类"载荷本体已注册但缺改写通道"的事实（缺口闭合后本测试
        仍成立; 通道缺失由 `TestBatch29EngineGaps` 守卫）。"""
        for cid in _REGISTERED_PAYLOADS:
            self.assertIsNotNone(get_db().get(cid), cid)
            self.assertIsNotNone(REGISTRY.get(cid), cid)


class TestBatch29EngineGaps(unittest.TestCase):
    """@engine-only 结构性: 阻塞本批 30 张的引擎缺口现状。

    每项断言"缺口**存在**"（运行时可观察事实）——主线补齐缺口后本类转红，
    即提示对应卡片可进入解冻流程（各卡 docstring 的 Implementation path
    给出解锁后的最小实现）。
    """

    def test_multi_race_identity_channel_now_available(self):
        """418 / 825 / 971 / 179 的阻塞已闭环（2026-09-21）。

        `GameTag.RACES`（实例类型身份集合）+ `Minion.races` /
        `Minion.has_race` + `Game.add_family_races` / `family_races` 家族
        类型改写通道落地（`batch_family_races` 注册 4 张）。权威:
        wiki `Multi-type minion` revid 855346 / `Minion` revid 817925 /
        `All` revid 893299; 作用域（Tavern/Discover）见 Patch 30.2.0.205267
        revid 814123 官方 Dev Comment。
        """
        self.assertIn("RACES", GameTag.__members__)
        self.assertTrue(hasattr(Game, "add_family_races"))
        self.assertTrue(hasattr(Game, "family_races"))
        self.assertTrue(hasattr(Game, "effective_races"))
        from hsrl2.minion import Minion as _M
        self.assertTrue(hasattr(_M, "races"))
        self.assertTrue(hasattr(_M, "has_race"))
        # 4 张已注册（不再是 DEFERRED 占位）
        for tid in ("BG30_MagicItem_418", "BG30_MagicItem_825",
                    "BG30_MagicItem_971", "BG32_MagicItem_179"):
            self.assertIsNotNone(REGISTRY.get(tid), tid)

    def test_payload_type_is_none_and_subset_is_not_race(self):
        """@engine-only 数据契约（AC-7）: `BACON_SUBSET_*` ≠ 类型身份。

        钉死 825 载荷 `BG21_013`/`_G` 的**类型表示**: 二者
        `race == Race.NONE`（无 CARDRACE、无 per-race 布尔 tag），只有
        `BACON_SUBSET_DRAGON`——subset 是饰品商店候选的类型标注
        （`Game._trinket_subsets`），不是随从类型。825 卡面为**单类型**
        "are Dragons"（非 "both"/"all"）。任一处漂移（例如给载荷补
        `card_race`/per-race tag，或卡面改成多类型集合读法）本守卫转红
        → 提示重评 825/`BG21_013` 的 DEFERRED 台账。
        """
        db = get_db()
        for cid in ("BG21_013", "BG21_013_G"):
            d = db.get(cid)
            self.assertEqual(d.race, Race.NONE, cid)
            self.assertIn("gains Attack", _norm(d.text), cid)
        # subset 是饰品候选标注（`Game._trinket_subsets`），与实例类型无关
        self.assertIn("dragon", db.get("BG21_013").subsets)
        portrait = db.get("BG30_MagicItem_825")
        self.assertEqual(portrait.race, Race.NONE)
        self.assertEqual(portrait.subsets, frozenset({"dragon"}))
        self.assertEqual(Game._trinket_subsets(portrait), {Race.DRAGON})
        # 825 卡面 = 单类型（无 both/all 的集合读法）
        text = _norm(portrait.text)
        self.assertIn("are Dragons", text)
        self.assertNotIn("both", text)
        self.assertNotIn("all minion types", text)

    def test_per_race_triple_threshold_now_available(self):
        """439 的阻塞已闭环（2026-09-02）: hero 级 `triple_threshold_race`
        已落地并由 `batch_misc_final` 注册该卡。"""
        from hsrl2.hero import Hero as _H
        self.assertIn("triple_threshold_race",
                      _H("T", "T").__dict__)

    def test_discard_system_now_available(self):
        """402 的阻塞已闭环（2026-10-18，F-08 Discard 子系统）:
        `Game.discard_card` + `card_discarded` 事件已落地。"""
        self.assertTrue(hasattr(Game, "discard_card"))
        self.assertIn("card_discarded", inspect.getsource(Game.discard_card))

    def test_engine_gap_no_wheel_of_yogg(self):
        """阻塞 994: Wheel of Yogg-Saron 缺失。"""
        self.assertFalse(hasattr(Game, "spin_wheel"))

    def test_engine_gap_no_craft_system(self):
        """阻塞 300: Craft 多步合成链缺失。"""
        self.assertFalse(hasattr(Game, "craft"))

    def test_hero_power_effect_doubling_now_available(self):
        """804 的阻塞已闭环（2026-09-02）: `hp_times` 已入引擎
        （`_finish_hero_power` 按 `1 + extra_trigger("hp_times")` 结算）。"""
        self.assertIn("hp_times", inspect.getsource(Game._finish_hero_power))

    def test_engine_gap_no_spell_target_chain(self):
        """阻塞 416: 法术路径无 `target_count` 两段选择链（仅英雄技能有）。"""
        self.assertNotIn("target_count", inspect.getsource(Game.play_spell))
        self.assertNotIn("target_count",
                         inspect.getsource(Game._finish_play_spell))

    def test_engine_gap_unregistered_payload_cards(self):
        """阻塞 402 / 431 / 806:
        载荷本体未迁移（RULES §7.4.6: 依赖其行为的饰品一并 DEFERRED）。
        （821t2 金色载荷已于 2026-09-13 迁出本台账; 777 Silver Goose 与
        803(30) Kaboom Bot 基础+金色已于 2026-09-16 由 batch_remaining2
        注册 → 移入 `_REGISTERED_PAYLOADS`，其饰品残余阻塞为纯通道;
        777 次生载荷 BG30_104/`_G` 已于 2026-09-17 由
        batch_goose_lucky_egg 注册 → 777 整体迁出本台账; 869 的两载荷
        BG29_873/877（含金色）已于 2026-09-19 由 batch_payload_minions
        注册 → 移入 `_REGISTERED_PAYLOADS`，869 整体迁出本台账;
        825 载荷 BG21_013/`_G` 已于 2026-09-20 由 batch_stats_gained
        注册 → 移入 `_REGISTERED_PAYLOADS`，825 残余阻塞为**纯类型改写
        通道**。）"""
        db = get_db()
        for cid in _UNREGISTERED_PAYLOADS:
            self.assertIsNotNone(db.get(cid), cid)
            self.assertIsNone(REGISTRY.get(cid), cid)

    def test_engine_gap_family_channel_markers_absent(self):
        """本批上报的载荷"extra/also"读取点缺口**全部闭合**（2026-09-13）。

        `_FAMILY_CHANNEL_MARKERS` 已清空（原 803(32) 的
        `macaw_extra_battlecry` 标记落地为活协议）——274 的 target-scope
        通道 / 804 的条件化战吼通道 / 803(32) 的 Macaw 追加战吼通道均已
        闭环 → 分别见 `test_family_flag_channel_now_available`、
        `test_conditional_battlecry_channel_now_available` 与
        `test_macaw_family_channel_now_available`。本守卫保留空容器，
        供后续批次追加标记时沿用。"""
        for module_name, markers in _FAMILY_CHANNEL_MARKERS.items():
            module = importlib.import_module(module_name)
            source = inspect.getsource(module)
            for marker in markers:
                self.assertNotIn(marker, source, f"{module_name}:{marker}")

    def test_conditional_battlecry_channel_now_available(self):
        """804 的阻塞已闭环（2026-09-13）: 引擎"条件化战吼"协议
        （RULES §7.4.17）已落地——载荷 `SelflessHeroScript` 声明
        `battlecry_flag = FLAG_SELFLESS_BATTLECRY` 并实现 `battlecry`
        分支（复用同一 `_give_divine_shield`），引擎 `Game.has_battlecry`
        / `granted_battlecry` 按开关门禁（`batch_trinkets35` 注册该
        饰品）。"""
        self.assertTrue(hasattr(Game, "has_battlecry"))
        self.assertTrue(hasattr(Game, "granted_battlecry"))
        for fn in (Game.has_battlecry, Game.granted_battlecry):
            self.assertIn("battlecry_flag", inspect.getsource(fn))
        from hsrl2.scripts.batches import batch_payload_minions as PM
        self.assertEqual(PM.SelflessHeroScript.battlecry_flag,
                         PM.FLAG_SELFLESS_BATTLECRY)
        src = inspect.getsource(PM.SelflessHeroScript)
        self.assertIn("battlecry_flag", src)
        self.assertIn("def battlecry", src)

    def test_macaw_family_channel_now_available(self):
        """803(32) 的阻塞已闭环（2026-09-13）: 同一"条件化战吼"协议
        （RULES §7.4.17）的第二消费者——载荷
        `MonstrousMacawScript.rally` 读 `FLAG_MACAW_EXTRA_BATTLECRY`
        追加最左战吼项（资格集 = `game.has_battlecry` 者，口径由 32.2
        论坛复现串 `M G x B y z` 裁定; 走 `TriggerBattlecry` 统一入口），
        `batch_trinkets36` 注册该饰品。"""
        from hsrl2.scripts.batches import batch_payload_minions as PM
        self.assertEqual(PM.FLAG_MACAW_EXTRA_BATTLECRY,
                         "macaw_extra_battlecry")
        src = inspect.getsource(PM.MonstrousMacawScript.rally)
        self.assertIn("FLAG_MACAW_EXTRA_BATTLECRY", src)
        self.assertIn("family_flag", src)
        self.assertIn("has_battlecry", src)
        self.assertIn("TriggerBattlecry", src)

    def test_family_flag_channel_now_available(self):
        """274 的阻塞已闭环（2026-09-13）: 引擎 `hero.family_flags` +
        `Game.add_family_flag` / `Game.family_flag`（RULES §7.4.16）已落地，
        载荷 `BristlebachScript.avenge` 已接消费点（`batch_trinkets34`
        注册该饰品）。"""
        from hsrl2.hero import Hero as _H
        self.assertIn("family_flags", _H("T", "T").__dict__)
        self.assertTrue(hasattr(Game, "add_family_flag"))
        self.assertTrue(hasattr(Game, "family_flag"))
        source = inspect.getsource(
            importlib.import_module(
                "hsrl2.scripts.batches.batch_payload_minions"))
        self.assertIn("family_flag", source)
        self.assertIn("FLAG_SCOPE_ALL_FRIENDLY", source)

    def test_giver_bonus_channel_now_available(self):
        """944 / 828 的阻塞已闭环（2026-09-13）: 引擎 `hero.giver_bonus_rules`
        + `Game.add_giver_bonus` / `Game.giver_bonus`（RULES §7.4.15）已落地，
        载荷 `NalaaTheRedeemerScript` / `ZestyShakerScript` 已接消费点
        （`batch_trinkets33` 注册两卡）。"""
        from hsrl2.hero import Hero as _H
        self.assertIn("giver_bonus_rules", _H("T", "T").__dict__)
        self.assertTrue(hasattr(Game, "add_giver_bonus"))
        self.assertTrue(hasattr(Game, "giver_bonus"))
        for module_name in ("hsrl2.scripts.batches.batch_payload_minions",
                            "hsrl2.scripts.batches.batch_econ_misc"):
            source = inspect.getsource(importlib.import_module(module_name))
            self.assertIn("giver_bonus", source, module_name)


if __name__ == "__main__":
    unittest.main()
