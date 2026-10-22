"""批次 anomalies_final 语义测试（异变收口批; 作业单 2026-09-11）。

覆盖 5 张注册异变 + 1 张随载荷第二技能槽技能（真实引擎路径:
`Game(anomaly=...)` + `start_game()`、真实 `_begin_recruit_for` 回合开始、
真实 `run_combat` + `combat_end`、真实 `upgrade_tavern` /
`_process_eliminations`）:

  - BG27_Anomaly_307 Oops, All EVIL!    —— 酒馆种族白名单 = `num(0)`
  - BG27_Anomaly_800 Little League      —— `game.max_tavern_tier = 4`
  - BG27_Anomaly_803 Anomalous Evidence —— 每回合 2 选 1 任务奖励（T4 解锁）
  - BG27_Anomaly_805 Match Fixing       —— 第二技能槽 0 费竞猜按钮
  - BG27_Anomaly_805t Match Fixing（Hero Power）—— 竞猜对 → 3 张 Tavern Coin
  - BG35_Anomaly_006 Anomalous Expedition —— 开局 T6/T4/T2 三选一，到档发放

约定（SOP §16 空转测试判定法）: 每个负面/落空断言都在**同一方法内**配
正对照; owner 隔离一律 2 英雄（异变本身是**全局**作用域——种族白名单 /
档位上限 / 按钮授予对全体英雄一致，只有"兑现物"（任务奖励、Tavern
Coin、到档随从）归各自 owner）; 随机一律同 seed 复跑。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.entity import Buff
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_anomalies_final as BF
from hsrl2.spell import Spell
from hsrl2.tags import CardType, GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

HERO_A = "BG20_HERO_103"        # 主技能 Bloodbound（已注册）
PLAIN_T1 = "BG25_001"           # Risen Rider — T1 非纳迦（对照用）
TAVERN_COIN = "BG28_810"        # "Gain 1 Gold."（Match Fixing 兑现物）

ANOM_EVIL = "BG27_Anomaly_307"
ANOM_LEAGUE = "BG27_Anomaly_800"
ANOM_EVIDENCE = "BG27_Anomaly_803"
ANOM_MATCH = "BG27_Anomaly_805"
POWER_MATCH = "BG27_Anomaly_805t"
ANOM_EXPED = "BG35_Anomaly_006"

REGISTERED_IDS = (
    ANOM_EVIL, ANOM_LEAGUE, ANOM_EVIDENCE, ANOM_MATCH, POWER_MATCH,
    ANOM_EXPED,
)

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def game_with(anomaly: str | None = None, seed: int = 30, names=("A", "B"),
              start: bool = True) -> Game:
    heroes = [Hero(HERO_A, n) for n in names]
    g = Game(heroes, get_db(), seed=seed, anomaly=anomaly)
    if start:
        g.start_game()
    return g


def tavern_minions(hero) -> list:
    return [e for e in hero.tavern if isinstance(e, Minion)]


def hand_minions(hero) -> list:
    return [e for e in hero.hand if isinstance(e, Minion)]


def hand_coins(hero) -> list:
    return [e for e in hero.hand
            if isinstance(e, Spell) and e.card_id == TAVERN_COIN]


def board_minion(game: Game, hero: Hero, card_id: str,
                 buff: tuple | None = None) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    game.summon(hero, m)
    if buff is not None:
        m.add_buff(Buff(atk=buff[0], health=buff[1]))
    return m


def choices_of(game: Game, kind: str, owner=None) -> list:
    out = [c for c in game.pending_choices if c.kind == kind]
    if owner is not None:
        out = [c for c in out if c.owner is owner]
    return out


def pick_choice(game: Game, kind: str, owner=None, index: int = 0):
    """取出一条待决（**必须出队**——SOP §13 压测教训）。"""
    chs = choices_of(game, kind, owner)
    assert chs, f"no pending choice {kind!r}"
    ch = chs[0]
    game.pending_choices.remove(ch)
    if index is not None and index >= 0:
        assert index < len(ch.options)
    return ch


def start_turn(game: Game, turn: int, clear_choices: bool = False) -> None:
    """驱动真实回合开始（每存活英雄一次; 引擎 `_begin_recruit_for`）。"""
    if clear_choices:
        game.pending_choices.clear()
    game.turn = turn
    for h in game.heroes:
        if h.is_alive:
            game._begin_recruit_for(h)


# ══════════════ 结构性（注册表 / 卡定义 / 台账守卫） ══════════════

class TestRegistry(unittest.TestCase):
    """注册面 + DEFERRED 台账守卫 + CardDef 数据一致性（结构性）。"""

    def test_registry_all_ids_registered(self):
        for cid in REGISTERED_IDS:
            self.assertIn(cid, REGISTRY, cid)
            self.assertIsNotNone(get_db().get(cid), cid)

    def test_registry_class_binding(self):
        expected = {
            ANOM_EVIL: "OopsAllEvilAnomaly",
            ANOM_LEAGUE: "LittleLeagueAnomaly",
            ANOM_EVIDENCE: "AnomalousEvidenceAnomaly",
            ANOM_MATCH: "MatchFixingAnomaly",
            POWER_MATCH: "MatchFixingPower",
            ANOM_EXPED: "AnomalousExpeditionAnomaly",
        }
        for cid, name in expected.items():
            self.assertIs(REGISTRY[cid], getattr(BF, name), cid)

    def test_registry_card_types(self):
        for cid in (ANOM_EVIL, ANOM_LEAGUE, ANOM_EVIDENCE, ANOM_MATCH,
                    ANOM_EXPED):
            self.assertEqual(get_db().get(cid).card_type,
                             CardType.BACON_ANOMALY, cid)
        self.assertEqual(get_db().get(POWER_MATCH).card_type,
                         CardType.HERO_POWER)

    def test_registry_deferred_ids_not_registered(self):
        self.assertEqual(len(BF.DEFERRED_IDS), 35)
        # 117 已由 batch_anomalies7 注册; 101/102 已由 batch_anomalies3 注册
        for cid in BF.DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)

    def test_carddef_data_chain_and_params(self):
        """数据链: 307 的 num(0) = 种族 id; 805t 的约定后缀载荷。"""
        evil = get_db().get(ANOM_EVIL)
        self.assertEqual(int(evil.num(0)), int(Race.NAGA))
        self.assertIsNone(get_db().get(ANOM_LEAGUE).num(0))     # 无模板参数
        power = get_db().get(f"{ANOM_MATCH}t")
        self.assertEqual(power.card_type, CardType.HERO_POWER)
        self.assertEqual(power.cost, 0)                          # 免费按钮
        self.assertEqual(int(get_db().get(ANOM_EVIDENCE + "t")
                             .card_type), int(CardType.SPELL))   # 载荷说明卡
        # 803 载荷说明卡存在且文本含 "Choose from 2 Quest Rewards"
        self.assertIn("Choose from 2 Quest Rewards",
                      get_db().get(ANOM_EVIDENCE + "t").text)


# ══════════════ BG27_Anomaly_307 Oops, All EVIL! ══════════════

class TestOopsAllEvil(unittest.TestCase):
    """酒馆种族白名单（num(0)=NAGA; 全局作用域）。"""

    def test_tavern_race_hook_wired_from_carddef(self):
        g = game_with(ANOM_EVIL, seed=101)
        self.assertEqual(g._tavern_race, Race(get_db().get(ANOM_EVIL).num(0)))
        self.assertEqual(g._tavern_race, Race.NAGA)

    def test_tavern_only_naga_with_control(self):
        g = game_with(ANOM_EVIL, seed=102)
        a = g.heroes[0]
        shown = tavern_minions(a)
        self.assertEqual(len(shown), 3)                 # T1 展示数
        for m in shown:
            self.assertIn(get_db().get(m.card_id).race,
                          (Race.NAGA, Race.ALL), m.card_id)
        self.assertTrue(any(get_db().get(m.card_id).race == Race.NAGA
                            for m in shown))
        # 全局作用域: 对手酒馆同样过白名单
        for m in tavern_minions(g.heroes[1]):
            self.assertIn(get_db().get(m.card_id).race,
                          (Race.NAGA, Race.ALL), m.card_id)
        # 正对照: 同 seed 无异常局出现非纳迦
        ctrl = game_with(None, seed=102)
        ctrl_races = {get_db().get(m.card_id).race
                      for m in tavern_minions(ctrl.heroes[0])}
        self.assertTrue(ctrl_races - {Race.NAGA, Race.ALL})

    def test_manual_refresh_still_filtered(self):
        g = game_with(ANOM_EVIL, seed=103)
        a = g.heroes[0]
        a.gold = 20
        ctrl = game_with(None, seed=103)
        c = ctrl.heroes[0]
        c.gold = 20
        for _ in range(5):
            g.refresh_tavern(a)
            ctrl.refresh_tavern(c)
        for m in tavern_minions(a):
            self.assertIn(get_db().get(m.card_id).race,
                          (Race.NAGA, Race.ALL), m.card_id)
        # 正对照: 无异常局累计出现非纳迦（证明过滤器真的在起作用）
        ctrl_ids = {m.card_id for _ in range(3)
                    for m in (ctrl.refresh_tavern(c) or tavern_minions(c))}
        self.assertTrue(any(get_db().get(i).race not in (Race.NAGA, Race.ALL)
                            for i in ctrl_ids))


# ══════════════ BG27_Anomaly_800 Little League ══════════════

class TestLittleLeague(unittest.TestCase):
    """"Only Tavern Tiers 1, 2, 3, and 4 exist."（全局档位上限 = 4）。"""

    def test_upgrade_chain_stops_at_four_with_control(self):
        g = game_with(ANOM_LEAGUE, seed=111)
        a = g.heroes[0]
        self.assertEqual(g.max_tavern_tier, 4)
        a.gold = 99
        for _ in range(3):
            self.assertTrue(g.upgrade_tavern(a))
        self.assertEqual(a.tavern_tier, 4)
        gold_before = a.gold
        self.assertFalse(g.upgrade_tavern(a))            # 4→5 被拒
        self.assertEqual(a.tavern_tier, 4)
        self.assertEqual(a.gold, gold_before)            # 失败不扣费
        # 正对照: 同 setup 无异常局可升到 5
        ctrl = game_with(None, seed=111)
        b = ctrl.heroes[0]
        b.gold = 99
        for _ in range(4):
            self.assertTrue(ctrl.upgrade_tavern(b))
        self.assertEqual(b.tavern_tier, 5)
        self.assertEqual(ctrl.max_tavern_tier, 6)

    def test_tavern_minions_capped_at_four(self):
        g = game_with(ANOM_LEAGUE, seed=112)
        a = g.heroes[0]
        a.gold = 99
        for _ in range(4):                    # 第 4 次（4→5）必然被拒
            g.upgrade_tavern(a)
        self.assertEqual(a.tavern_tier, 4)
        self.assertEqual(g.max_tavern_tier, 4)
        seen = set()
        for _ in range(8):
            g.refresh_tavern(a)
            shown = tavern_minions(a)
            self.assertTrue(shown)
            for m in shown:
                seen.add(get_db().get(m.card_id).tech_level)
        self.assertTrue(seen)
        self.assertTrue(max(seen) <= 4, seen)
        # 正对照: 无异常局同 setup 升到 5 并刷出 T5（证明封顶真在起作用）
        ctrl = game_with(None, seed=112)
        b = ctrl.heroes[0]
        b.gold = 99
        for _ in range(4):
            ctrl.upgrade_tavern(b)
        self.assertEqual(b.tavern_tier, 5)
        ctrl_seen = set()
        for _ in range(8):
            ctrl.refresh_tavern(b)
            for m in tavern_minions(b):
                ctrl_seen.add(get_db().get(m.card_id).tech_level)
        self.assertTrue(max(ctrl_seen) >= 5, ctrl_seen)

    def test_triple_reward_tier_capped(self):
        g = game_with(ANOM_LEAGUE, seed=113)
        a = g.heroes[0]
        t4 = sorted(d.id for d in get_db().pool_minions()
                    if d.tech_level == 4)[0]
        golden = g.create_minion(t4, controller=a, golden=True)
        golden.set(GameTag.TRIPLE_BASE_CARD_ID, t4)
        g._grant_triple_reward(a, golden)
        ch = pick_choice(g, "triple_reward", owner=a)
        self.assertTrue(ch.options)
        for oid in ch.options:
            self.assertEqual(get_db().get(oid).tech_level, 4, oid)
        # 正对照: 无异常局同一 T4 三连 → 奖励档 = 5
        ctrl = game_with(None, seed=113)
        c = ctrl.heroes[0]
        g2 = ctrl.create_minion(t4, controller=c, golden=True)
        g2.set(GameTag.TRIPLE_BASE_CARD_ID, t4)
        ctrl._grant_triple_reward(c, g2)
        ch2 = pick_choice(ctrl, "triple_reward", owner=c)
        self.assertTrue(ch2.options)
        for oid in ch2.options:
            self.assertEqual(get_db().get(oid).tech_level, 5, oid)


# ══════════════ BG27_Anomaly_803 Anomalous Evidence ══════════════

class TestAnomalousEvidence(unittest.TestCase):
    """每回合 2 选 1 新任务奖励（T4 解锁; 每英雄独立）。"""

    def test_unlock_turn_boundary(self):
        g = game_with(ANOM_EVIDENCE, seed=121)
        start_turn(g, 3, clear_choices=True)
        self.assertEqual(choices_of(g, "quest_reward_choice"), [])
        start_turn(g, 4)
        for h in g.heroes:
            got = choices_of(g, "quest_reward_choice", h)
            self.assertEqual(len(got), 1)
            self.assertEqual(len(got[0].options), 2)
        # 正对照: 无异常局第 4 回合没有任何本类待决
        ctrl = game_with(None, seed=121)
        start_turn(ctrl, 4, clear_choices=True)
        self.assertEqual(choices_of(ctrl, "quest_reward_choice"), [])

    def test_options_are_new_rewards_and_grant_wires_on_bind(self):
        g = game_with(ANOM_EVIDENCE, seed=122)
        start_turn(g, 4, clear_choices=True)
        a, b = g.heroes
        self.assertEqual(a.quest_rewards, [])
        ch = pick_choice(g, "quest_reward_choice", a)
        self.assertEqual(len(set(ch.options)), 2)            # 互异
        for oid in ch.options:
            self.assertTrue(oid.startswith("BG24_Reward_"), oid)
            self.assertIsNotNone(get_db().get(oid))
        calls = []
        orig = g.run_script_hook

        def spy(entity, hook, *args, **kw):
            calls.append((getattr(entity, "card_id", None), hook))
            return orig(entity, hook, *args, **kw)

        g.run_script_hook = spy
        picked = ch.options[1]
        ch.choose(1)
        g.run_script_hook = orig
        self.assertIn(picked, {e.card_id for e in a.quest_rewards})
        self.assertEqual(len(a.quest_rewards), 1)
        self.assertIs(a.quest_rewards[0].controller, a)
        self.assertIn((picked, "on_bind"), calls)            # on_bind 活性
        # owner 隔离: 对手未被授予 A 的选择
        self.assertEqual(b.quest_rewards, [])

    def test_next_turn_excludes_chosen(self):
        g = game_with(ANOM_EVIDENCE, seed=123)
        start_turn(g, 4, clear_choices=True)
        a = g.heroes[0]
        ch = pick_choice(g, "quest_reward_choice", a)
        chosen = ch.options[0]
        ch.choose(0)
        start_turn(g, 5, clear_choices=True)
        ch2 = pick_choice(g, "quest_reward_choice", a)
        self.assertNotIn(chosen, ch2.options)                # "new"
        self.assertEqual(len(ch2.options), 2)

    def test_candidates_exhausted_falls_through(self):
        g = game_with(ANOM_EVIDENCE, seed=124)
        a = g.heroes[0]
        db = get_db()
        for d in db._by_id.values():
            if d.id.startswith("BG24_Reward_"):
                a.quest_rewards.append(g.create_entity(d.id, controller=a))
        start_turn(g, 4, clear_choices=True)
        self.assertEqual(choices_of(g, "quest_reward_choice", a), [])
        # 正对照: 有候选时同 setup 必然给出选择
        b = g.heroes[1]
        self.assertEqual(len(choices_of(g, "quest_reward_choice", b)), 1)

    def test_same_seed_determinism(self):
        g1 = game_with(ANOM_EVIDENCE, seed=125)
        g2 = game_with(ANOM_EVIDENCE, seed=125)
        start_turn(g1, 4, clear_choices=True)
        start_turn(g2, 4, clear_choices=True)
        o1 = [c.options for c in choices_of(g1, "quest_reward_choice")]
        o2 = [c.options for c in choices_of(g2, "quest_reward_choice")]
        self.assertEqual(len(o1), 2)                         # 每英雄一份
        self.assertEqual(o1, o2)


# ══════════════ BG27_Anomaly_805 Match Fixing ══════════════

class TestMatchFixing(unittest.TestCase):
    """"Guess which player will win your next combat."（0 费按钮 + 3 Coin）。"""

    def test_second_slot_granted_to_all_heroes(self):
        g = game_with(ANOM_MATCH, seed=131)
        for h in g.heroes:
            self.assertEqual(h._second_power_id, POWER_MATCH)
            self.assertIn(POWER_MATCH, g.hero_power_ids(h))
        # 正/负对照: 同 seed 无异常局无第二槽且该技能不可用
        ctrl = game_with(None, seed=131)
        c = ctrl.heroes[0]
        self.assertIsNone(getattr(c, "_second_power_id", None))
        c.gold = 10
        self.assertFalse(ctrl.use_hero_power(c, power_id=POWER_MATCH))
        self.assertEqual(c.gold, 10)

    def test_power_is_free_and_prompts_two_way_choice(self):
        g = game_with(ANOM_MATCH, seed=132)
        a = g.heroes[0]
        a.gold = 7
        self.assertTrue(g.use_hero_power(a, power_id=POWER_MATCH))
        self.assertEqual(a.gold, 7)                          # cost = 0
        ch = pick_choice(g, "friendly_wager", a)
        self.assertEqual(list(ch.options), ["me", "opponent"])
        # 主技能不受影响（次数独立，RULES §9.5）
        self.assertIsNotNone(g.hero_power_def(a))
        self.assertFalse(g.use_hero_power(a, power_id=POWER_MATCH))  # 1/回合

    def test_correct_guess_pays_three_coins_others_pay_none(self):
        g = game_with(ANOM_MATCH, seed=133)
        a, b = g.heroes
        a.gold = 7
        self.assertTrue(g.use_hero_power(a, power_id=POWER_MATCH))
        pick_choice(g, "friendly_wager", a).choose(0)         # 猜自己
        board_minion(g, a, PLAIN_T1, buff=(9, 9))
        board_minion(g, b, PLAIN_T1)
        result = g.run_combat(a, b)
        self.assertIs(result.winner, a)
        g.events.fire(g, "combat_end", hero_a=a, hero_b=b, result=result)
        self.assertEqual(len(hand_coins(a)), 3)               # 猜中 → 3 张
        self.assertEqual([s for s in b.hand if isinstance(s, Spell)], [])
        # 一次性（"your **next** combat"）: 同一赌局不得二次兑现
        g.events.fire(g, "combat_end", hero_a=a, hero_b=b, result=result)
        self.assertEqual(len(hand_coins(a)), 3)
        # 同方法内负对照: 同技能猜自己但战败 → 无
        g2 = game_with(ANOM_MATCH, seed=134)
        a2, b2 = g2.heroes
        a2.gold = 7
        self.assertTrue(g2.use_hero_power(a2, power_id=POWER_MATCH))
        pick_choice(g2, "friendly_wager", a2).choose(0)
        board_minion(g2, a2, PLAIN_T1)
        board_minion(g2, b2, PLAIN_T1, buff=(9, 9))
        r2 = g2.run_combat(a2, b2)
        self.assertIs(r2.winner, b2)
        g2.events.fire(g2, "combat_end", hero_a=a2, hero_b=b2, result=r2)
        self.assertEqual(hand_coins(a2), [])

    def test_guess_opponent_wins_and_draw_pays_none(self):
        g = game_with(ANOM_MATCH, seed=135)
        a, b = g.heroes
        a.gold = 7
        self.assertTrue(g.use_hero_power(a, power_id=POWER_MATCH))
        pick_choice(g, "friendly_wager", a).choose(1)         # 猜对手
        board_minion(g, a, PLAIN_T1)
        board_minion(g, b, PLAIN_T1, buff=(9, 9))
        result = g.run_combat(a, b)
        self.assertIs(result.winner, b)
        g.events.fire(g, "combat_end", hero_a=a, hero_b=b, result=result)
        self.assertEqual(len(hand_coins(a)), 3)
        # 负对照: 双空板平局（猜测方向仍为对手）→ 无 Coin
        g2 = game_with(ANOM_MATCH, seed=136)
        a2, _b2 = g2.heroes
        a2.gold = 7
        self.assertTrue(g2.use_hero_power(a2, power_id=POWER_MATCH))
        pick_choice(g2, "friendly_wager", a2).choose(1)
        r2 = g2.run_combat(a2, g2.heroes[1])
        self.assertIsNone(r2.winner)
        g2.events.fire(g2, "combat_end", hero_a=a2, hero_b=g2.heroes[1],
                       result=r2)
        self.assertEqual(hand_coins(a2), [])

    def test_occupied_second_slot_not_overwritten(self):
        g = game_with(ANOM_MATCH, seed=137, start=False)
        a, b = g.heroes
        a._second_power_id = "TB_BaconShop_HP_081"     # 已被其它来源占用
        BF.MatchFixingAnomaly.on_bind(g)
        self.assertEqual(a._second_power_id, "TB_BaconShop_HP_081")
        self.assertEqual(b._second_power_id, POWER_MATCH)     # 正对照
        # 未注册/不存在的载荷 → 整卡落空（不授予空转按钮）
        g2 = game_with(ANOM_MATCH, seed=138, start=False)
        g2.anomaly = "BG27_Anomaly_9999"
        BF.MatchFixingAnomaly.on_bind(g2)
        for h in g2.heroes:
            self.assertIsNone(getattr(h, "_second_power_id", None))

    def test_payload_lookup_wired_to_grant(self):
        """数据约定解析必须校验卡类型/注册态（防授予空转技能）。"""
        g = game_with(ANOM_MATCH, seed=139, start=False)
        self.assertEqual(BF.match_fixing_power_id(g), POWER_MATCH)
        BF.MatchFixingAnomaly.on_bind(g)
        self.assertEqual(g.heroes[0]._second_power_id, POWER_MATCH)  # 活性
        # 载荷存在但不是 Hero Power（803t 是 [DNT] 法术）→ 拒绝
        g.anomaly = ANOM_EVIDENCE
        self.assertIsNone(BF.match_fixing_power_id(g))
        # 载荷是 Hero Power 但**脚本未注册** → 拒绝（不授予空转按钮）
        # （117t 已由 batch_anomalies7 注册 → 临时摘除验证同一分支，
        #  finally 还原注册表——契约测试不污染全局）
        g.anomaly = "BG31_Anomaly_117"
        self.assertEqual(get_db().get("BG31_Anomaly_117t").card_type,
                         CardType.HERO_POWER)
        saved = REGISTRY.pop("BG31_Anomaly_117t")
        try:
            self.assertIsNone(BF.match_fixing_power_id(g))
        finally:
            REGISTRY["BG31_Anomaly_117t"] = saved
        self.assertEqual(BF.match_fixing_power_id(g),
                         "BG31_Anomaly_117t")         # 还原正对照
        # 载荷卡不存在（006 无 t 卡）→ 拒绝
        g.anomaly = ANOM_EXPED
        self.assertIsNone(BF.match_fixing_power_id(g))
        # 无异常局 → 拒绝
        g.anomaly = None
        self.assertIsNone(BF.match_fixing_power_id(g))


# ══════════════ BG35_Anomaly_006 Anomalous Expedition ══════════════

class TestAnomalousExpedition(unittest.TestCase):
    """开局 T6/T4/T2 三选一，到达对应酒馆等级时入手。"""

    def _choice_for_tier(self, game, hero, tier):
        for c in choices_of(game, "discover_expedition", hero):
            levels = {get_db().get(o).tech_level for o in c.options}
            if levels == {tier}:
                return c
        raise AssertionError(f"no choice for tier {tier}")

    def test_three_discovers_per_hero_exact_tiers(self):
        g = game_with(ANOM_EXPED, seed=141)
        for h in g.heroes:
            chs = choices_of(g, "discover_expedition", h)
            self.assertEqual(len(chs), 3)
            self.assertEqual(sorted({get_db().get(c.options[0]).tech_level
                                     for c in chs}), [2, 4, 6])
            for c in chs:
                self.assertEqual(len(c.options), 3)          # 三选一
                levels = {get_db().get(o).tech_level for o in c.options}
                self.assertEqual(len(levels), 1, c.options)  # 档位同质
                self.assertIn(levels.pop(), (2, 4, 6))
        # 正对照: 无异常局无任何本类待决
        ctrl = game_with(None, seed=141)
        self.assertEqual(choices_of(ctrl, "discover_expedition"), [])
        self.assertFalse(hasattr(ctrl.heroes[0], "_expedition_pending"))

    def test_reserve_pool_copy_and_grant_on_reaching_tier(self):
        g = game_with(ANOM_EXPED, seed=142)
        a, b = g.heroes
        ch2 = self._choice_for_tier(g, a, 2)
        pick2 = ch2.options[0]
        # 选项在生成时即已预留（acquire）; 选中 = 不释放，未选 = 立即回池
        avail = {o: g.minion_pool.available(o) for o in ch2.options}
        g.pending_choices.remove(ch2)
        ch2.choose(0)
        self.assertEqual(g.minion_pool.available(pick2), avail[pick2])
        for other in ch2.options[1:]:
            self.assertEqual(g.minion_pool.available(other), avail[other] + 1)
        self.assertEqual(a._expedition_pending.get(2), pick2)
        # 另取 T4（未兑现前不得入手）
        ch4 = self._choice_for_tier(g, a, 4)
        pick4 = ch4.options[1]
        g.pending_choices.remove(ch4)
        ch4.choose(1)
        self.assertEqual(hand_minions(a), [])
        a.gold = 99
        self.assertTrue(g.upgrade_tavern(a))                 # → T2
        self.assertEqual([m.card_id for m in hand_minions(a)], [pick2])
        self.assertIsNone(a._expedition_pending.get(2))
        self.assertEqual(a._expedition_pending.get(4), pick4)  # 未提前发放
        self.assertEqual(hand_minions(b), [])                  # owner 隔离
        self.assertTrue(g.upgrade_tavern(a))
        self.assertTrue(g.upgrade_tavern(a))                 # → T4
        self.assertEqual(sorted(m.card_id for m in hand_minions(a)),
                         sorted([pick2, pick4]))

    def test_pending_not_visible_to_opponent(self):
        g = game_with(ANOM_EXPED, seed=143)
        a, b = g.heroes
        ch = self._choice_for_tier(g, a, 6)
        pick = ch.options[0]
        g.pending_choices.remove(ch)
        ch.choose(0)
        self.assertEqual(a._expedition_pending.get(6), pick)
        self.assertNotIn(pick, (b._expedition_pending or {}).values())
        b.gold = 99
        for _ in range(4):
            g.upgrade_tavern(b)
        self.assertEqual(b.tavern_tier, 5)
        for _ in range(6):
            g.upgrade_tavern(b)
        self.assertEqual(b.tavern_tier, 6)
        self.assertEqual([m.card_id for m in hand_minions(b)], [])  # 未选择
        self.assertEqual([m.card_id for m in hand_minions(a)], [])  # T6 未到

    def test_elimination_releases_unredeemed_reservation(self):
        g = game_with(ANOM_EXPED, seed=144)
        a = g.heroes[0]
        picks = []
        for c in list(choices_of(g, "discover_expedition", a)):
            g.pending_choices.remove(c)
            c.choose(0)
            picks.append(c.options[0])
        self.assertEqual(len(picks), 3)
        before = {cid: g.minion_pool.available(cid) for cid in picks}
        a.health = 0
        g._process_eliminations()
        for cid in picks:
            self.assertGreaterEqual(g.minion_pool.available(cid),
                                    before[cid] + 1)
        self.assertEqual(a._expedition_pending, {})
        self.assertNotIn(a, g.heroes)

    def test_same_seed_determinism(self):
        g1 = game_with(ANOM_EXPED, seed=145)
        g2 = game_with(ANOM_EXPED, seed=145)
        o1 = sorted((c.owner.name, tuple(c.options))
                    for c in choices_of(g1, "discover_expedition"))
        o2 = sorted((c.owner.name, tuple(c.options))
                    for c in choices_of(g2, "discover_expedition"))
        self.assertEqual(len(o1), 6)                         # 2 英雄 × 3 档
        self.assertEqual(o1, o2)


if __name__ == "__main__":
    unittest.main()
