"""批次 trinkets9 行为层测试（饰品非商店授予/替换族 4 张 + 888 台账守卫）。

全部断言走真实引擎路径:
  - 购买: 真实 `game._offer_trinkets` + PendingChoice.resolve（扣费 /
    `_trinkets_granted` / `hero.trinkets.append` / `run_script_hook(on_bind)`）
  - 随机授予: 真实 `game.grant_random_trinket`（`on_bind` 钩子路径）
  - 替换: 真实 `game.replace_trinket`（移除实体 + `events.unregister_owner`
    + `grant_trinket`）
  - 回合推进: 真实 `game.end_recruit_phase()`（SoT/EoT/战斗全流程）
  - 法术: 真实 `game.play_spell`（池法术占池→施放→回池）
  - 事件: 真实 `trinket_bought` / `card_played` 广播

覆盖（SOP §16 空转测试判定法——每个效果类都有正对照）:
  - owner 隔离（2 英雄; 每个效果都有"对手活动不生效"断言）
  - 语义: "new/un-granted" 候选、档位过滤（Lesser/Greater Naga）、
    每回合节奏、免费替换、陈旧选择防护、每局去重
  - 数值与 CardDef.num 双向钉死
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets9 as B9

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实，非凭记忆 id）
ORB = "BG35_MagicItem_816"          # Orb of the Unknown（lesser）
RUNE = "BG36_MagicItem_305"         # Rune of Transmutation（lesser）
CUBE = "BG30_MagicItem_703"         # Mystery Cube（lesser）
VOUCHERS = "BG30_MagicItem_891"     # Trip Vouchers（lesser）
# BG30_MagicItem_888 Souvenir Stand 已迁出（batch_trinkets13 实现——
# 副本条款，RULES §7.4.3）
SOUVENIR = "BG30_MagicItem_888"
CHARGING_STAFF = "BG30_MagicItem_984"   # lesser，on_bind 仅注册监听器
FRIGID_BLOSSOM = "BG36_MagicItem_300"   # lesser，on_bind 仅注册监听器
SPELL_PLAIN = "BG28_800"            # Careful Investment（池法术，无定向）
MINION_PLAIN = "BG31_803"           # Buzzing Vermin T1 野兽

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 1200) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def take_choice(game: Game, kind: str, owner=None):
    """取出一条 PendingChoice 并出队（SOP §13 契约: choose 只结算不出队）。"""
    if owner is None:
        ch = next(c for c in game.pending_choices if c.kind == kind)
    else:
        ch = next(c for c in game.pending_choices
                  if c.kind == kind and c.owner is owner)
    game.pending_choices.remove(ch)
    return ch


def replace_choices(game: Game, owner=None):
    return [c for c in game.pending_choices
            if c.kind == "trinket_replace"
            and (owner is None or c.owner is owner)]


def trinket_offers(game: Game, owner=None):
    return [c for c in game.pending_choices
            if c.kind == "trinket_offer"
            and (owner is None or c.owner is owner)]


def buy_trinket(game: Game, hero, tid: str, kind: str):
    """真实商店路径: `_offer_trinkets` → 选项定向到 tid → resolve。

    返回入栏的该饰品实体（注意其 on_bind 可能再入栏其它实体）。
    """
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    ch = take_choice(game, "trinket_offer", hero)
    ch.options = [get_db().get(tid)]
    ch.choose(0)
    return next(t for t in hero.trinkets if t.card_id == tid)


def cast_spell(game: Game, hero, card_id: str = SPELL_PLAIN):
    """真实入手 + 施放一张池法术（施放结束回池，可重复使用）。"""
    assert game.spell_pool.acquire(card_id), card_id
    s = game.create_spell(card_id, controller=hero)
    hero.add_to_hand(s)
    assert game.play_spell(hero, s), card_id
    return s


def lesser_ids() -> list:
    return [d.id for d in get_db().trinket_offer_pool()
            if d.spell_school == 11]


def greater_naga_ids() -> list:
    return [d.id for d in get_db().trinket_offer_pool()
            if d.spell_school == 12 and "naga" in d.subsets]


# ══════════════ 结构性（注册表 / 数据一致性） ══════════════

class TestRegistryState(unittest.TestCase):
    """注册面 + 文本/数据一致性（结构性，与钩子无关）。"""

    IMPLEMENTED = (ORB, RUNE, CUBE, VOUCHERS)
    CLASSES = {
        ORB: "OrbOfTheUnknownScript",
        RUNE: "RuneOfTransmutationScript",
        CUBE: "MysteryCubeScript",
        VOUCHERS: "TripVouchersScript",
    }

    def test_all_registered_and_bound(self):
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIs(REGISTRY[tid], getattr(B9, self.CLASSES[tid]), tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_all_are_lesser_and_in_offer_pool(self):
        offer_ids = {d.id for d in get_db().trinket_offer_pool()}
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, offer_ids, tid)
            self.assertEqual(get_db().get(tid).spell_school, 11, tid)

    def test_deferred_ids_not_registered(self):
        """本批 DEFERRED 台账已清空（Souvenir Stand 由 batch_trinkets13
        经副本条款实现）——结构性断言保留为空遍历。"""
        for cid in ():
            self.assertNotIn(cid, REGISTRY, cid)

    def test_num_params_match_text(self):
        db = get_db()
        self.assertEqual(db.get(RUNE).num(0), 18)     # 37.0: "cast 18 spells"
        self.assertEqual(db.get(VOUCHERS).num(0), 2)   # "In 2 turns"
        self.assertIsNone(db.get(ORB).num(0))          # 文本无占位符
        self.assertIsNone(db.get(CUBE).num(0))

    def test_rune_data_declares_naga_subset(self):
        d = get_db().get(RUNE)
        self.assertIn("naga", d.subsets)
        self.assertTrue(greater_naga_ids())            # 载荷非空，非空转

    def test_deferred_ledger_records_engine_dependency(self):
        doc = B9.__doc__ or ""
        self.assertIn("Souvenir Stand", doc)
        self.assertIn("duplicate", doc.lower())


# ══════════════ BG35_MagicItem_816 Orb of the Unknown ══════════════

class TestOrbOfTheUnknown(unittest.TestCase):
    TID = ORB

    def test_buying_grants_a_new_random_lesser(self):
        g = make_game(seed=1101)
        a, b = g.heroes
        orb = buy_trinket(g, a, self.TID, "lesser")
        granted = [t for t in a.trinkets if t is not orb]
        self.assertEqual(len(granted), 1)
        gd = get_db().get(granted[0].card_id)
        self.assertEqual(gd.spell_school, 11)          # Lesser
        self.assertIn(granted[0].card_id, g._trinkets_granted)
        self.assertIs(granted[0].controller, a)
        self.assertEqual(b.trinkets, [])               # owner 隔离

    def test_forced_single_candidate_is_granted_and_its_on_bind_runs(self):
        """预记账其余全部 Lesser → 只剩一张候选，Orb 必授予它（"new"）。

        候选选 Sunken Anchor（on_bind 发 2 张 Bounty）→ 以**入手牌**
        证明被授予实体的 on_bind 真的跑了（不只是入栏）。
        """
        import hsrl2.constants as C
        g = make_game(seed=1102)
        a, _b = g.heroes
        forced = "BG35_MagicItem_890"          # Sunken Anchor（lesser）
        lessers = lesser_ids()
        self.assertIn(forced, lessers)
        a.gold = 50
        g._offer_trinkets(a, "lesser")                 # 先建商店选择
        ch = take_choice(g, "trinket_offer", a)
        ch.options = [get_db().get(self.TID)]
        # 预记账其余 Lesser（Orb 自身亦已获得，不影响 resolve）
        g._trinkets_granted.update(i for i in lessers if i != forced)
        a.trinkets_granted.update(i for i in lessers if i != forced)
        ch.choose(0)
        self.assertIn(forced, [t.card_id for t in a.trinkets])
        self.assertEqual(len(a.trinkets), 2)           # Orb + forced
        bounties = [c for c in a.hand
                    if c.card_id in C.BOUNTY_SPELL_IDS]
        self.assertEqual(len(bounties), 2)             # on_bind 已生效

    def test_no_candidate_when_all_lessers_granted(self):
        # 正对照: 正常池 → Orb 之外再授予一张
        g = make_game(seed=1103)
        a, _b = g.heroes
        buy_trinket(g, a, self.TID, "lesser")
        self.assertEqual(len(a.trinkets), 2)
        # 负面: 预占全部 Lesser（含 Orb 自身）→ 无候选，不再授予
        g2 = make_game(seed=1104)
        a2, _b2 = g2.heroes
        a2.gold = 50
        g2._offer_trinkets(a2, "lesser")
        ch = take_choice(g2, "trinket_offer", a2)
        ch.options = [get_db().get(self.TID)]
        g2._trinkets_granted.update(lesser_ids())
        a2.trinkets_granted.update(lesser_ids())
        ch.choose(0)
        self.assertEqual([t.card_id for t in a2.trinkets], [self.TID])


# ══════════════ BG36_MagicItem_305 Rune of Transmutation ══════════════

class TestRuneOfTransmutation(unittest.TestCase):
    TID = RUNE

    def test_counts_to_num0_then_replaces_with_greater_naga(self):
        g = make_game(seed=1111)
        a, _b = g.heroes
        rune = buy_trinket(g, a, self.TID, "lesser")
        n = get_db().get(self.TID).num(0)
        self.assertEqual(n, 18)        # 37.0: CardDef 15→18
        for _ in range(n - 1):
            cast_spell(g, a)
        self.assertIn(rune, a.trinkets)                # 未达阈值不替换
        self.assertEqual([t.card_id for t in a.trinkets], [self.TID])
        cast_spell(g, a)                               # 第 n 个
        self.assertNotIn(rune, a.trinkets)
        self.assertEqual(len(a.trinkets), 1)
        nd = get_db().get(a.trinkets[0].card_id)
        self.assertEqual(nd.spell_school, 12)          # Greater
        self.assertIn("naga", nd.subsets)              # Naga
        self.assertIn(nd.id, g._trinkets_granted)

    def test_listener_unregistered_after_replacement(self):
        g = make_game(seed=1112)
        a, _b = g.heroes
        buy_trinket(g, a, self.TID, "lesser")
        for _ in range(get_db().get(self.TID).num(0)):
            cast_spell(g, a)
        snapshot = [t.card_id for t in a.trinkets]
        cast_spell(g, a)                               # 替换后再施法
        self.assertEqual([t.card_id for t in a.trinkets], snapshot)

    def test_opponent_spells_do_not_count(self):
        g = make_game(seed=1113)
        a, b = g.heroes
        rune = buy_trinket(g, a, self.TID, "lesser")
        n = get_db().get(self.TID).num(0)
        for _ in range(n - 1):
            cast_spell(g, a)
        for _ in range(n):
            cast_spell(g, b)                           # 对手施法不计数
        self.assertIn(rune, a.trinkets)
        cast_spell(g, a)                               # 正对照: 本人第 n 个
        self.assertNotIn(rune, a.trinkets)
        self.assertEqual(get_db().get(a.trinkets[0].card_id).spell_school, 12)

    def test_minion_plays_do_not_count(self):
        g = make_game(seed=1115)
        a, _b = g.heroes
        rune = buy_trinket(g, a, self.TID, "lesser")
        n = get_db().get(self.TID).num(0)
        m = g.create_minion(MINION_PLAIN, controller=a)
        a.add_to_hand(m)
        self.assertTrue(g.play_minion(a, m))           # 随从打出不计数
        for _ in range(n - 1):
            cast_spell(g, a)
        self.assertIn(rune, a.trinkets)
        cast_spell(g, a)                               # 正对照
        self.assertNotIn(rune, a.trinkets)

    def test_exhausted_naga_pool_keeps_rune(self):
        # 正对照: 池有货 → 第 num(0) 个法术确实替换
        g = make_game(seed=1114)
        a, _b = g.heroes
        buy_trinket(g, a, self.TID, "lesser")
        for _ in range(get_db().get(self.TID).num(0)):
            cast_spell(g, a)
        self.assertEqual(len(a.trinkets), 1)
        self.assertEqual(get_db().get(a.trinkets[0].card_id).spell_school, 12)
        # 负面: 预占全部 Greater Naga → 池耗尽，Rune 保留
        g2 = make_game(seed=1141)
        a2, _b2 = g2.heroes
        rune2 = buy_trinket(g2, a2, self.TID, "lesser")
        g2._trinkets_granted.update(greater_naga_ids())
        a2.trinkets_granted.update(greater_naga_ids())
        for _ in range(get_db().get(self.TID).num(0)):
            cast_spell(g2, a2)
        self.assertIn(rune2, a2.trinkets)
        self.assertEqual([t.card_id for t in a2.trinkets], [self.TID])


# ══════════════ BG30_MagicItem_703 Mystery Cube ══════════════

class TestMysteryCube(unittest.TestCase):
    TID = CUBE

    def test_on_bind_offers_two_new_lessers(self):
        g = make_game(seed=1121)
        a, b = g.heroes
        cube = buy_trinket(g, a, self.TID, "lesser")
        choices = replace_choices(g)
        self.assertEqual(len(choices), 1)
        ch = choices[0]
        self.assertIs(ch.owner, a)                     # owner 隔离
        self.assertEqual(len(ch.options), 2)           # "Choose from 2"
        ids = [o.id for o in ch.options]
        self.assertEqual(len(set(ids)), 2)             # 互异
        for o in ch.options:
            self.assertEqual(o.spell_school, 11)       # Lesser
            self.assertNotIn(o.id, g._trinkets_granted)  # "new"
        self.assertIn(cube, a.trinkets)
        self.assertEqual(b.trinkets, [])

    def test_pick_replaces_cube_for_free(self):
        g = make_game(seed=1122)
        a, _b = g.heroes
        cube = buy_trinket(g, a, self.TID, "lesser")
        ch = take_choice(g, "trinket_replace", a)
        picked = ch.options[0]
        gold_before = a.gold
        ch.choose(0)
        self.assertNotIn(cube, a.trinkets)
        self.assertIn(picked.id, [t.card_id for t in a.trinkets])
        self.assertEqual(a.gold, gold_before)          # "for free"
        self.assertIn(picked.id, g._trinkets_granted)

    def test_start_of_turn_repeats(self):
        g = make_game(seed=1123)
        a, b = g.heroes
        buy_trinket(g, a, self.TID, "lesser")
        self.assertEqual(len(replace_choices(g, a)), 1)
        g.end_recruit_phase()                          # 真实推进回合 → SoT
        self.assertEqual(len(replace_choices(g, a)), 2)
        self.assertEqual(len(replace_choices(g, b)), 0)

    def test_owner_isolation(self):
        g = make_game(seed=1124)
        a, b = g.heroes
        buy_trinket(g, a, self.TID, "lesser")
        self.assertGreaterEqual(len(replace_choices(g, a)), 1)   # 正对照
        self.assertEqual(len(replace_choices(g, b)), 0)          # 负面
        self.assertEqual(b.trinkets, [])

    def test_empty_candidate_pool_makes_no_choice(self):
        # 正对照: 正常池 → on_bind 建 2 选 1
        g = make_game(seed=1125)
        a, _b = g.heroes
        buy_trinket(g, a, self.TID, "lesser")
        self.assertEqual(len(replace_choices(g, a)), 1)
        # 负面: 预占全部 Lesser → 无 "new" 候选，不建选择
        g2 = make_game(seed=1140)
        a2, _b2 = g2.heroes
        a2.gold = 50
        g2._offer_trinkets(a2, "lesser")
        ch = take_choice(g2, "trinket_offer", a2)
        ch.options = [get_db().get(self.TID)]
        g2._trinkets_granted.update(lesser_ids())
        a2.trinkets_granted.update(lesser_ids())
        ch.choose(0)
        self.assertIn(self.TID, [t.card_id for t in a2.trinkets])
        self.assertEqual(len(replace_choices(g2, a2)), 0)

    def test_stale_choice_does_not_grant_twice(self):
        g = make_game(seed=1126)
        a, _b = g.heroes
        buy_trinket(g, a, self.TID, "lesser")
        ch = take_choice(g, "trinket_replace", a)
        ch.options = [get_db().get(CHARGING_STAFF),
                      get_db().get(FRIGID_BLOSSOM)]
        ch.choose(0)
        after = [t.card_id for t in a.trinkets]
        self.assertEqual(after, [CHARGING_STAFF])
        ch.choose(1)                                   # 同一选择重复结算
        self.assertEqual([t.card_id for t in a.trinkets], after)


# ══════════════ BG30_MagicItem_891 Trip Vouchers ══════════════

class TestTripVouchers(unittest.TestCase):
    TID = VOUCHERS

    def _offer(self, g, owner):
        return trinket_offers(g, owner)

    def test_offer_opens_after_num0_turns(self):
        g = make_game(seed=1131)
        a, _b = g.heroes
        vouchers = buy_trinket(g, a, self.TID, "lesser")
        n = get_db().get(self.TID).num(0)
        self.assertEqual(n, 2)
        g.end_recruit_phase()                          # 第 1 个回合开始
        self.assertEqual(self._offer(g, a), [])
        self.assertIn(vouchers, a.trinkets)
        g.end_recruit_phase()                          # 第 2 个回合开始
        offers = self._offer(g, a)
        self.assertEqual(len(offers), 1)
        schools = {o.spell_school for o in offers[0].options if o is not None}
        self.assertEqual(schools, {12})                # 仅 Greater 档
        self.assertIn(vouchers, a.trinkets)            # 未买前券仍在

    def test_buying_replaces_vouchers(self):
        g = make_game(seed=1132)
        a, _b = g.heroes
        vouchers = buy_trinket(g, a, self.TID, "lesser")
        for _ in range(get_db().get(self.TID).num(0)):
            g.end_recruit_phase()
        ch = take_choice(g, "trinket_offer", a)
        a.gold = 50
        # 定向到一张**无脚本**的 Greater（on_bind 无副作用）以钉死支付额
        pick = next(d for d in get_db().trinket_offer_pool()
                    if d.spell_school == 12 and d.id not in REGISTRY
                    and (d.cost or 0) > 0)
        ch.options = [pick, None]
        ch.choose(0)
        self.assertNotIn(vouchers, a.trinkets)
        self.assertEqual([t.card_id for t in a.trinkets], [pick.id])
        self.assertEqual(a.gold, 50 - (pick.cost or 0))
        self.assertIn(pick.id, g._trinkets_granted)

    def test_declining_keeps_vouchers_and_gold(self):
        g = make_game(seed=1133)
        a, _b = g.heroes
        vouchers = buy_trinket(g, a, self.TID, "lesser")
        for _ in range(get_db().get(self.TID).num(0)):
            g.end_recruit_phase()
        ch = take_choice(g, "trinket_offer", a)
        a.gold = 50
        ch.choose(ch.options.index(None))              # 商店"放弃"选项
        self.assertIn(vouchers, a.trinkets)
        self.assertEqual([t.card_id for t in a.trinkets], [self.TID])
        self.assertEqual(a.gold, 50)

    def test_owner_isolation(self):
        g = make_game(seed=1134)
        a, b = g.heroes
        buy_trinket(g, a, self.TID, "lesser")
        for _ in range(get_db().get(self.TID).num(0)):
            g.end_recruit_phase()
        self.assertEqual(len(self._offer(g, a)), 1)    # 正对照
        self.assertEqual(self._offer(g, b), [])        # 负面
        self.assertEqual(b.trinkets, [])

    def test_opponent_greater_purchase_does_not_consume_voucher(self):
        """对手买到 Greater 饰品不得消费本券（2026-09-02 对抗审查 MAJOR:
        旧的 `once=True` 无 condition `trinket_bought` 监听器会被**任何**
        玩家的购买消费）。"""
        g = make_game(seed=1136)
        a, b = g.heroes
        vouchers = buy_trinket(g, a, self.TID, "lesser")
        for _ in range(get_db().get(self.TID).num(0)):
            g.end_recruit_phase()
        self.assertEqual(len(self._offer(g, a)), 1)     # 本券已开放 offer
        # 对手买一张 Greater（真实商店路径）
        other = next(d for d in get_db().trinket_offer_pool()
                     if d.spell_school == 12 and d.id not in REGISTRY)
        buy_trinket(g, b, other.id, "greater")
        self.assertIn(vouchers, a.trinkets)             # 本券未被消费
        # 正对照: 本人从自己的 offer 购买 → 本券被替换
        ch = take_choice(g, "trinket_offer", a)
        a.gold = 50
        pick = next(d for d in get_db().trinket_offer_pool()
                    if d.spell_school == 12 and d.id not in REGISTRY
                    and d.id != other.id and (d.cost or 0) > 0)
        ch.options = [pick, None]
        ch.choose(0)
        self.assertNotIn(vouchers, a.trinkets)
        self.assertIn(pick.id, [t.card_id for t in a.trinkets])

    def test_decline_then_unrelated_purchase_keeps_voucher(self):
        """放弃 offer 后再发生无关的 Greater 购买，本券仍在（旧实现会
        被残留的 once 监听器顺手销毁）。"""
        g = make_game(seed=1137)
        a, b = g.heroes
        vouchers = buy_trinket(g, a, self.TID, "lesser")
        for _ in range(get_db().get(self.TID).num(0)):
            g.end_recruit_phase()
        ch = take_choice(g, "trinket_offer", a)
        ch.choose(ch.options.index(None))               # 放弃
        self.assertIn(vouchers, a.trinkets)
        # **本人**之后发生一次无关的 Greater 商店购买（旧实现的常驻
        # once 监听器会在此刻把本券替换掉 → 券凭空消失）
        other = next(d for d in get_db().trinket_offer_pool()
                     if d.spell_school == 12 and d.id not in REGISTRY)
        buy_trinket(g, a, other.id, "greater")
        self.assertIn(vouchers, a.trinkets)             # 本券未被销毁
        self.assertIn(other.id, [t.card_id for t in a.trinkets])
        self.assertIn(self.TID, [t.card_id for t in a.trinkets])

    def test_standard_greater_slot_not_consumed(self):
        """本券是 T9 之外的额外机会——不得写 `(hero, "greater")` 记账。"""
        g = make_game(seed=1135)
        a, _b = g.heroes
        buy_trinket(g, a, self.TID, "lesser")
        for _ in range(get_db().get(self.TID).num(0)):
            g.end_recruit_phase()
        self.assertEqual(len(self._offer(g, a)), 1)
        self.assertNotIn((a, "greater"), g._trinket_offered)


if __name__ == "__main__":
    unittest.main()
