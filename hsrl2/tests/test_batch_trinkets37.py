"""`batch_trinkets37` — Weary Portrait（`BG32_MagicItem_933`）回归测试。

真实路径: 饰品商店 `_offer_trinkets` → `PendingChoice` → `choose` →
`on_bind`（授予载荷 + 注册永久化规则）→ 真实 `summon` 生成 Spellcraft
法术 → 真实 `play_spell` 结算 → 下一招募阶段验证"永久 vs 回收"。

负对照: 无饰品（法术为 temporary 且下一回合被回收）/ 非 Weary Mage 来源
不标记 / 对手来源不标记 / 饰品离场后规则失效。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.tags import GameTag

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

WEARY_PORTRAIT = "BG32_MagicItem_933"
WEARY = "BG31_830"           # Weary Mage（Spellcraft 来源，非池卡 T4）
WEARY_G = "BG31_830_G"
WEARY_SPELL = "BG31_830t"    # Reinvigoration "Give a minion +2/+2"
WEARY_SPELL_G = "BG31_830_Gt"
OTHER_SOURCE = "BG23_000"    # Mini-Myrmidon（纳迦 Spellcraft，非 Weary Mage）
NAGA_TARGET = "BG23_000"     # 纳迦目标（Reinvigoration 会额外给 Reborn）
AMALGAM = "BG36_640"         # Gatekeeper Amalgam 6/6 T6（Race.ALL，算纳迦）
BEAST_TARGET = "BG26_802"    # Banana Slamma 3/6 T4 野兽（非纳迦，无 Reborn）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 940) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def offer_and_buy(game: Game, hero: Hero, tid: str, kind: str = "lesser"):
    """真实饰品商店路径: `_offer_trinkets` → PendingChoice → resolve。"""
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    choice = game.pending_choices.pop(0)
    choice.options = [get_db().get(tid)]
    choice.choose(0)
    return hero.trinkets[-1]


def hand_ids(hero: Hero) -> list:
    return [e.card_id for e in hero.hand]


class TestRegistryState(unittest.TestCase):
    def test_registered(self):
        self.assertIn(WEARY_PORTRAIT, REGISTRY)

    def test_in_offer_pool_as_lesser(self):
        d = get_db().get(WEARY_PORTRAIT)
        self.assertIn(d, get_db().trinket_offer_pool())
        self.assertEqual(d.spell_school, 11)      # Lesser
        self.assertEqual(d.cost, 5)

    def test_evolution_data_chain(self):
        d = get_db().get(WEARY_PORTRAIT)
        related = get_db().by_dbf(d.evolution_card_id)
        self.assertIsNotNone(related)
        self.assertEqual(related.id, WEARY)
        self.assertFalse(related.is_pool_minion)

    def test_payload_and_spell_registered(self):
        for cid in (WEARY, WEARY_G, WEARY_SPELL, WEARY_SPELL_G):
            with self.subTest(cid=cid):
                self.assertIn(cid, REGISTRY)

    def test_spellcraft_data_link_intact(self):
        self.assertEqual(get_db().by_dbf(get_db().get(WEARY).spellcraft_id).id,
                         WEARY_SPELL)


class TestWearyPortrait(unittest.TestCase):
    TID = WEARY_PORTRAIT

    def _play_weary(self, game, hero, card_id=WEARY):
        """打出 Weary Mage（真实 `summon` → 生成第一张 Spellcraft）。"""
        hero.gold = 30
        m = game.create_minion(card_id, controller=hero)
        self.assertTrue(game.summon(hero, m))
        return m

    def _spell_in_hand(self, hero, card_id=WEARY_SPELL):
        spells = [e for e in hero.hand
                  if isinstance(e, Spell) and e.card_id == card_id]
        assert spells, [e.card_id for e in hero.hand]
        return spells[0]

    def test_bind_grants_weary_mage_and_registers_rule(self):
        g = make_game(seed=9401)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID)
        self.assertEqual(hand_ids(a).count(WEARY), 1)
        self.assertEqual(len(a.permanent_spellcraft_rules), 1)

    def test_spellcraft_from_weary_mage_is_permanent(self):
        """正对照: 永久化命中 → +2/+2 与 **Reborn** 均跨回合保留。

        本体法术的临时项是 Reborn（"until next turn"），+2/+2 本就不带
        期限 → 判据必须用 Reborn，否则测不出永久化差异。
        """
        g = make_game(seed=9402)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID)
        self._play_weary(g, a)
        target = g.create_minion(NAGA_TARGET, controller=a)
        self.assertTrue(g.summon(a, target))
        spell = self._spell_in_hand(a)
        self.assertTrue(getattr(spell, "permanent_spellcraft", False))
        base = target.atk
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertEqual(target.atk, base + 2)
        self.assertTrue(target.has(GameTag.REBORN))
        atk_after = target.atk
        g._begin_recruit_for(a)                        # 下一招募阶段
        self.assertEqual(target.atk, atk_after)        # 属性不回收
        self.assertTrue(target.has(GameTag.REBORN))    # Reborn 保留

    def test_without_trinket_reborn_expires(self):
        """负对照: 无饰品时 Reborn 是 temporary，下一回合被清除。"""
        g = make_game(seed=9403)
        a = g.heroes[0]
        self._play_weary(g, a)
        target = g.create_minion(NAGA_TARGET, controller=a)
        self.assertTrue(g.summon(a, target))
        spell = self._spell_in_hand(a)
        self.assertFalse(getattr(spell, "permanent_spellcraft", False))
        base = target.atk
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertEqual(target.atk, base + 2)
        self.assertTrue(target.has(GameTag.REBORN))
        g._begin_recruit_for(a)
        self.assertFalse(target.has(GameTag.REBORN))   # 已清除
        self.assertEqual(target.atk, base + 2)         # 属性本就永久

    def test_amalgam_counts_as_naga_and_keeps_reborn(self):
        """Race.ALL（融合怪）算纳迦 → 同样吃 Reborn 且永久化保留。"""
        g = make_game(seed=9409)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID)
        self._play_weary(g, a)
        target = g.create_minion(AMALGAM, controller=a)
        self.assertTrue(g.summon(a, target))
        spell = self._spell_in_hand(a)
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertTrue(target.has(GameTag.REBORN))
        g._begin_recruit_for(a)
        self.assertTrue(target.has(GameTag.REBORN))

    def test_non_naga_target_gets_no_reborn(self):
        """负对照: 非纳迦目标只得 +2/+2（无 Reborn，永久化不适用）。"""
        g = make_game(seed=9410)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID)
        self._play_weary(g, a)
        target = g.create_minion(BEAST_TARGET, controller=a)
        self.assertTrue(g.summon(a, target))
        spell = self._spell_in_hand(a)
        base = target.atk
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertEqual(target.atk, base + 2)
        self.assertFalse(target.has(GameTag.REBORN))

    def test_other_spellcraft_source_not_marked(self):
        g = make_game(seed=9404)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID)
        self._play_weary(g, a, card_id=OTHER_SOURCE)
        spells = [e for e in a.hand
                  if isinstance(e, Spell) and e.has(GameTag.SPELLCRAFT)]
        self.assertTrue(spells)
        for s in spells:
            self.assertFalse(getattr(s, "permanent_spellcraft", False))

    def test_golden_weary_mage_matches(self):
        g = make_game(seed=9405)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID)
        self._play_weary(g, a, card_id=WEARY_G)
        spell = self._spell_in_hand(a, WEARY_SPELL_G)
        self.assertTrue(getattr(spell, "permanent_spellcraft", False))

    def test_rule_expires_when_trinket_leaves(self):
        g = make_game(seed=9406)
        a = g.heroes[0]
        trinket = offer_and_buy(g, a, self.TID)
        mage = g.create_minion(WEARY, controller=a)
        self.assertTrue(g._permanent_spellcraft_matches(a, mage))
        a.trinkets.remove(trinket)
        self.assertFalse(g._permanent_spellcraft_matches(a, mage))

    def test_owner_isolation(self):
        g = make_game(seed=9407)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID)
        self._play_weary(g, b)
        spells = [e for e in b.hand
                  if isinstance(e, Spell) and e.has(GameTag.SPELLCRAFT)]
        self.assertTrue(spells)
        for s in spells:
            self.assertFalse(getattr(s, "permanent_spellcraft", False))

    def test_duplicate_copies_grant_two_and_rules_independent(self):
        g = make_game(seed=9408)
        a = g.heroes[0]
        g.grant_trinket(a, self.TID, source="test")
        g.grant_trinket(a, self.TID, source="test", duplicate=True)
        self.assertEqual(hand_ids(a).count(WEARY), 2)
        self.assertEqual(len(a.permanent_spellcraft_rules), 2)
        a.trinkets.pop(0)                              # 移除一份
        mage = g.create_minion(WEARY, controller=a)
        self.assertTrue(g._permanent_spellcraft_matches(a, mage))


    def test_regenerated_spellcraft_is_permanent_too(self):
        """两条生成路径都打标: 召唤时 `grant_spellcraft_spell` 与每招募阶段
        `spellcraft.generate_for_hero` 重生成的 Spellcraft 均永久。"""
        g = make_game(seed=9411)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID)
        mage = self._play_weary(g, a)
        first = self._spell_in_hand(a)
        self.assertTrue(getattr(first, "permanent_spellcraft", False))
        self.assertTrue(g.play_spell(a, first, target=mage))
        g._begin_recruit_for(a)                        # 重新生成
        regen = self._spell_in_hand(a)
        self.assertTrue(getattr(regen, "permanent_spellcraft", False))
        target = g.create_minion(NAGA_TARGET, controller=a)
        self.assertTrue(g.summon(a, target))
        self.assertTrue(g.play_spell(a, regen, target=target))
        self.assertTrue(target.has(GameTag.REBORN))
        g._begin_recruit_for(a)
        self.assertTrue(target.has(GameTag.REBORN))    # 重生成法术同样永久


    def test_spell_generated_before_purchase_still_permanent(self):
        """BUG-1 回归（对抗审查 2026-09-14）: 当回合法术**先于**饰品生成/入手，
        施放时仍须永久化。

        时序: `_begin_recruit_for` 先生成 Spellcraft → 之后才买到 Portrait
        → 手里那张生成时未标记。引擎在施放时反查来源随从并回写
        `spell.permanent_spellcraft`（game.py 施放路径），载荷据同一标记
        决定是否注册 Reborn 过期监听。
        """
        g = make_game(seed=9412)
        a = g.heroes[0]
        mage = self._play_weary(g, a)          # 先打出 → 当回合法术已生成
        stale = self._spell_in_hand(a)
        self.assertFalse(getattr(stale, "permanent_spellcraft", False))
        offer_and_buy(g, a, self.TID)          # 之后才绑定饰品
        self.assertFalse(getattr(stale, "permanent_spellcraft", False))
        target = g.create_minion(NAGA_TARGET, controller=a)
        self.assertTrue(g.summon(a, target))
        self.assertTrue(g.play_spell(a, stale, target=target))
        self.assertTrue(target.has(GameTag.REBORN))
        g._begin_recruit_for(a)
        self.assertTrue(target.has(GameTag.REBORN))    # 修复前为 False
        self.assertIsNotNone(mage)


    def test_recast_via_effect_path_keeps_permanent_keyword(self):
        """ENGINE_BACKLOG #26 回归: 重施放（效果施法）同样永久化。

        Lovely Locket `BG36_MagicItem_211` 对友方随从施法后把同一法术再施
        放到另一个友方随从 → `cast_spell_effect(source=原始法术)` 继承
        `spellcraft_source_uuid`，`_resolve_cast_permanence` 命中规则 →
        重施放的目标也保留 Reborn（修复前该目标次回合丢失 Reborn）。
        """
        g = make_game(seed=9413)
        a = g.heroes[0]
        mage = self._play_weary(g, a)
        g.grant_trinket(a, "BG36_MagicItem_211", source="test")   # Lovely Locket
        offer_and_buy(g, a, self.TID)                            # Weary Portrait
        naga = g.create_minion(NAGA_TARGET, controller=a)
        self.assertTrue(g.summon(a, naga))
        spell = self._spell_in_hand(a)
        self.assertTrue(g.play_spell(a, spell, target=naga))
        self.assertTrue(naga.has(GameTag.REBORN))
        # 重施放落在唯一"其他"随从 = Weary Mage 本体（纳迦）
        self.assertTrue(mage.has(GameTag.REBORN))
        g._begin_recruit_for(a)
        self.assertTrue(naga.has(GameTag.REBORN))
        self.assertTrue(mage.has(GameTag.REBORN))    # #26 修复前为 False

    def test_effect_cast_without_locket_source_still_expires(self):
        """负对照: 效果施法不传 `source` 时无法判定来源 → 不永久化（诚实
        标注的残余契约: 调用方必须提供来源，见 `ENGINE_BACKLOG` #26）。"""
        g = make_game(seed=9414)
        a = g.heroes[0]
        self._play_weary(g, a)
        offer_and_buy(g, a, self.TID)
        target = g.create_minion(NAGA_TARGET, controller=a)
        self.assertTrue(g.summon(a, target))
        self.assertTrue(g.cast_spell_effect(a, WEARY_SPELL, target=target))
        self.assertTrue(target.has(GameTag.REBORN))
        g._begin_recruit_for(a)
        self.assertFalse(target.has(GameTag.REBORN))  # 未知来源 → 不永久


    def test_recast_inherits_resolved_flag_when_source_left(self):
        """FALSIFIER 1 回归（对抗审查 2026-09-14）: 同一法术的**已解析**永久化
        标记随 `source=` 继承。

        时序: 饰品在场时生成法术（生成期标记）→ **卖掉来源随从**（签名反查
        失手）→ 直施仍因生成期标记而永久 → Locket 重施放必须同结论。
        """
        g = make_game(seed=9415)
        a = g.heroes[0]
        g.grant_trinket(a, "BG36_MagicItem_211", source="test")   # Lovely Locket
        offer_and_buy(g, a, self.TID)                            # Portrait 先绑
        mage = self._play_weary(g, a)          # 生成期即打标（饰品已在场）
        spell = self._spell_in_hand(a)
        self.assertTrue(getattr(spell, "permanent_spellcraft", False))
        left = g.create_minion(NAGA_TARGET, controller=a)
        right = g.create_minion(NAGA_TARGET, controller=a)
        self.assertTrue(g.summon(a, left))
        self.assertTrue(g.summon(a, right))
        self.assertTrue(g.sell_minion(a, mage))                  # 来源离场
        self.assertNotIn(mage, a.board)
        self.assertTrue(g.play_spell(a, spell, target=left))
        self.assertTrue(left.has(GameTag.REBORN))
        self.assertTrue(right.has(GameTag.REBORN))               # 重施放
        g._begin_recruit_for(a)
        self.assertTrue(left.has(GameTag.REBORN))
        self.assertTrue(right.has(GameTag.REBORN))    # FALSIFIER 1 修复前 False

    def test_nested_effect_cast_does_not_clobber_permanence_window(self):
        """FALSIFIER 2 回归（对抗审查 2026-09-14，引擎既有缺陷）: 在
        `spell_resolving` 中嵌套效果施法不得清掉外层的待翻转目标。

        Coral Spear `BG35_MagicItem_925` 在 `spell_resolving` 里再施放
        Might of Stormwind; 外层 Thaumaturgist 的 temporary buff 仍须被
        永久化（修复前 buff 保持 temporary 并在次回合回收）。
        """
        g = make_game(seed=9416)
        a = g.heroes[0]
        offer_and_buy(g, a, "BG32_MagicItem_920", kind="greater")
        g.grant_trinket(a, "BG35_MagicItem_925", source="test")   # Coral Spear
        mage = g.create_minion("BG31_924", controller=a)
        self.assertTrue(g.summon(a, mage))
        target = g.create_minion(BEAST_TARGET, controller=a)
        self.assertTrue(g.summon(a, target))
        spell = [e for e in a.hand if isinstance(e, Spell)
                 and e.card_id == "BG31_924t"][0]
        self.assertTrue(getattr(spell, "permanent_spellcraft", False))
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertTrue(target._buffs)
        self.assertTrue(all(not b.temporary for b in target._buffs))
        atk = target.atk
        g._begin_recruit_for(a)
        self.assertEqual(target.atk, atk)             # 不回收
        self.assertIsNone(getattr(g, "_permanence_pending", None))
        self.assertIsNotNone(mage)


if __name__ == "__main__":
    unittest.main()
