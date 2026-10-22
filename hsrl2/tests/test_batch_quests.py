"""批次 quests 语义测试（2026-09-18）。

覆盖: 任务注册闸（19 注册 + 1 DEFERRED + 2 公告 token 排除）、目标值与
CardDefs `QUEST_PROGRESS_TOTAL` 的交叉校验、每张任务的**真实路径**推进
（真实 `refresh_tavern` / `play_minion` / `buy_from_tavern` / `sell_minion`
/ `spend_gold` / `add_to_hand` / `run_combat` / `destroy_minion` /
`play_spell` / `end_recruit_phase`）、奖励发放（`complete_quest` →
`hero.quest_rewards`）、持有者隔离负对照、超阈值不多发、未达阈值不完成，
以及变异探针（改阈值 / 去掉进度钩子必须失败）。

权威: 逐卡 wiki URL/oldid/引文见 `hsrl2/scripts/batches/batch_quests.py`
模块 docstring 与 `docs/agents/QUEST_DEFERRED_SPEC.md`。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.entity import Buff as Enchant
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.tags import CardType, GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

# 已注册任务（19）——含 3 张"当前不可选但同族"的移除卡。
REGISTERED = (
    "BG24_Quest_112", "BG24_Quest_114", "BG24_Quest_120",
    "BG24_Quest_123", "BG24_Quest_124", "BG24_Quest_125",
    "BG24_Quest_126", "BG24_Quest_151", "BG24_Quest_311",
    "BG24_Quest_313", "BG24_Quest_314", "BG24_Quest_318",
    "BG24_Quest_320", "BG24_Quest_351", "BG24_Quest_352",
    "BG27_Quest_800", "BG27_Quest_801", "BG27_Quest_802",
    "BG28_Quest_500",
)
# DEFERRED: "Win the game." 胜义无权威（第 1/前 4/单场战斗胜利无法消歧）;
# **不是缺目标值**——卡数据 quest_progress_total=1（tag 535），从未入池
DEFERRED = ("BG24_Quest_328",)
# 公告 token: 无进度条件（语义 = _offer_quests 的 T4 三选一）→ 不得注册
ANNOUNCE_TOKENS = ("BG24_Quest_Bob", "BG33_Anomaly_008_Quest")
REWARD = "BG24_Reward_134"          # 任意已注册任务奖励（batch_quest_rewards）


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 70, n_heroes: int = 2):
    g = Game([Hero("TEST_H_" + chr(65 + i), chr(65 + i))
              for i in range(n_heroes)], get_db(), seed=seed)
    g.start_game()
    return g


def attach(game, hero, qid, reward: str | None = REWARD):
    """真实发放前状态: 建任务实体 + 接线 + 暂存奖励（_offer_quests 同款）。"""
    q = game.create_entity(qid, controller=hero)
    hero.quest = q
    hero._quest_progress = 0
    hero._quest_completed = False
    hero._quest_reward_id = reward
    game.run_on_bind(q, ctx={"hero": hero})
    return q


def minion_id(name: str) -> str:
    for d in get_db().pool_minions():
        if d.name == name:
            return d.id
    raise KeyError(name)


def put(game, hero, cid, position=None):
    m = game.create_minion(cid, controller=hero)
    game.summon(hero, m, position)
    return m


def put_in_hand(game, hero, cid):
    m = game.create_minion(cid, controller=hero)
    hero.add_to_hand(m)
    return m


def tavern_m(game, hero, cid):
    m = game.create_minion(cid, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def free_spell(game, hero):
    """池法术（最低费）入手——施放测试用。"""
    d = min(get_db().pool_spells(), key=lambda x: x.cost or 0)
    s = game.create_spell(d.id, controller=hero)
    hero.add_to_hand(s)
    return s


MURLOC = minion_id("Tad")
# 37.0（build 255130）卡池轮换: 旧 `Sly Raptor`（BG25_806）已退出池内随从
# （255130 生成数据 `bg_pool_minions.json` 无此卡；bg_cards 仍有定义），
# 改用仍在池内的 T2 野兽 `Humming Bird`（BG26_805）——同为 BEAST 类型身份，
# 满足 "Unlikely Duo" 的 MURLOC/BEAST 双族购买计数语义。
BEAST = minion_id("Humming Bird")
QUILBOAR = minion_id("Razorfen Geomancer")     # 非 MURLOC/BEAST/ALL
BATTLECRY = minion_id("Razorfen Geomancer")    # 有 BATTLECRY
NO_BATTLECRY = minion_id("Roadboar")           # 无 BATTLECRY（同一 DB 校验）
DEATHRATTLE = minion_id("Sanguine Champion")
TAUNT = minion_id("Risen Rider")


class TestRegistryAndAuthority(unittest.TestCase):
    """注册闸 + 数值权威（wiki baseline == CardDefs tag 535）。"""

    def test_registered_set(self):
        for qid in REGISTERED:
            self.assertIn(qid, REGISTRY, qid)
        for qid in DEFERRED + ANNOUNCE_TOKENS:
            self.assertNotIn(qid, REGISTRY, qid)

    def test_quest_defs_is_full_family(self):
        g = make_game()
        ids = sorted(d.id for d in g.quest_defs())
        self.assertEqual(len(ids), 20)          # 19 注册 + 1 DEFERRED
        self.assertIn("BG24_Quest_328", ids)
        self.assertNotIn("BG24_Quest_Bob", ids)
        self.assertNotIn("BG33_Anomaly_008_Quest", ids)

    def test_offer_pool_excludes_deferred_and_tokens(self):
        """池门禁: 未注册任务永不发出（禁止空转第三态）。"""
        g = make_game()
        ids = sorted(d.id for d in g.quest_offer_pool())
        self.assertEqual(ids, sorted(REGISTERED))

    def test_every_script_target_matches_carddef(self):
        """交叉校验: 脚本 target 必须等于 CardDefs QUEST_PROGRESS_TOTAL。

        这是 wiki 当前 baseline 值的**数据副本**——变异任一侧必须失败。
        """
        for qid in REGISTERED:
            d = get_db().get(qid)
            script = REGISTRY[qid]
            self.assertEqual(script.target, d.quest_progress_total, qid)
            self.assertGreater(script.target, 0, qid)

    def test_bg24_quest_328_deferred_reason_is_win_semantics(self):
        """DEFERRED 前提: 目标值**存在**（tag 535=1）; 阻塞是 "Win the
        game." 胜义无权威——不是"无 baseline/target"。"""
        d = get_db().get("BG24_Quest_328")
        self.assertEqual(d.text, "<b>Quest:</b> Win the game.")
        # 数据**有**目标值（旧记录"无 baseline 行/无 target"为假）
        self.assertEqual(d.quest_progress_total, 1)
        # 无 QUEST tag（从未入池）
        self.assertFalse(d.quest)

    def test_announce_tokens_have_no_progress_condition(self):
        for qid in ANNOUNCE_TOKENS:
            d = get_db().get(qid)
            self.assertIn("choose one of three", d.text)


class TestQuest112TrackFootprints(unittest.TestCase):
    """真实 `refresh_tavern`（手动 + 自动同一生产点）。"""

    def test_manual_and_auto_count_then_complete_once(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_112")
        b.gold = 50
        # 真实刷新需付 `C.TAVERN_REFRESH_COST` 金——每次先备足
        for _ in range(7):
            a.gold = 10
            g.refresh_tavern(a, auto=False)
        self.assertEqual(a._quest_progress, 7)
        self.assertEqual(a.quest_rewards, [])      # 未达 8
        a.gold = 10
        g.refresh_tavern(a, auto=True)             # 自动刷新同计
        self.assertEqual(a._quest_progress, 8)
        self.assertTrue(a._quest_completed)
        self.assertEqual([r.card_id for r in a.quest_rewards], [REWARD])
        # 第 9 次不再计分（超阈值 + 二次发奖闸）
        a.gold = 10
        g.refresh_tavern(a, auto=True)
        self.assertEqual(a._quest_progress, 8)
        self.assertEqual(len(a.quest_rewards), 1)

    def test_opponent_refresh_does_not_count(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_112")
        b.gold = 50
        g.refresh_tavern(b, auto=False)
        self.assertEqual(a._quest_progress, 0)

    def test_without_quest_no_progress(self):
        """正对照: 无任务 → 事件不推进任何英雄。"""
        g = make_game()
        a = g.heroes[0]
        a.gold = 50
        g.refresh_tavern(a, auto=False)
        self.assertEqual(a._quest_progress, 0)


class TestQuest114AssembleLineup(unittest.TestCase):
    def test_play_minion_counts_to_target(self):
        """15 个**不同** MURLOC（避免三连合成额外的金色 summon 计数）。"""
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_114")
        ids = [d.id for d in get_db().pool_minions()
               if d.race == Race.MURLOC][:15]
        for i, cid in enumerate(ids):
            m = put_in_hand(g, a, cid)
            while len(a.board) >= 7:
                g.sell_minion(a, a.board[-1])
            g.play_minion(a, m)
            if i == 0:
                self.assertEqual(a._quest_progress, 1)
        self.assertEqual(a._quest_progress, 15)
        self.assertFalse(a._quest_completed)
        while len(a.board) >= 7:
            g.sell_minion(a, a.board[-1])
        m = put_in_hand(g, a, MURLOC)
        g.play_minion(a, m)
        self.assertTrue(a._quest_completed)
        self.assertEqual(len(a.quest_rewards), 1)

    def test_triple_combine_golden_summon_counts(self):
        """边界: 三连把金色随从置场，同样是 `summon` → 计 1。"""
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_114")
        for _ in range(2):
            m = put_in_hand(g, a, MURLOC)
            g.play_minion(a, m)
        self.assertEqual(a._quest_progress, 2)
        m = put_in_hand(g, a, MURLOC)
        g.play_minion(a, m)
        self.assertEqual(a._quest_progress, 4)      # 第 3 个 + 金色合成置场
        self.assertTrue(any(x.is_golden for x in a.board))

    def test_opponent_summon_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_114")
        put(g, b, MURLOC)
        self.assertEqual(a._quest_progress, 0)


class TestQuest120UnmaskCulprit(unittest.TestCase):
    def _fight(self, g, a, b):
        g.run_combat(a, b)

    def test_loss_counts_win_does_not(self):
        g = make_game(seed=71)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_120")
        # 必败局: 对手单个 100/100（本人空场）
        for i in range(3):
            for m in list(b.board):
                g.sell_minion(b, m)
            big = put(g, b, MURLOC)
            big.set(GameTag.BASE_ATK, 100)
            big.set(GameTag.HEALTH, 100)
            g.run_combat(a, b)
            g.events.fire(g, "combat_end", hero_a=a, hero_b=b,
                          result=None)
            self.assertEqual(a._last_combat_result, "loss", i)
        self.assertEqual(a._quest_progress, 3)
        self.assertTrue(a._quest_completed)

    def test_win_does_not_count(self):
        """负对照: 同一 hook 在胜局必须不推进。"""
        g = make_game(seed=72)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_120")
        m = put(g, a, MURLOC)
        m.set(GameTag.BASE_ATK, 50)
        m.set(GameTag.HEALTH, 50)
        g.run_combat(a, b)
        self.assertEqual(a._last_combat_result, "win")
        self.assertEqual(a._quest_progress, 0)

    def test_opponent_loss_not_counted_for_holder(self):
        g = make_game(seed=73)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_120")
        m = put(g, b, MURLOC)
        m.set(GameTag.BASE_ATK, 50)
        m.set(GameTag.HEALTH, 50)
        big = put(g, a, MURLOC)
        big.set(GameTag.BASE_ATK, 100)
        big.set(GameTag.HEALTH, 100)
        g.run_combat(a, b)
        g.events.fire(g, "combat_end", hero_a=a, hero_b=b, result=None)
        self.assertEqual(b._last_combat_result, "loss")
        self.assertEqual(a._quest_progress, 0)


class TestQuest123FindMurderWeapon(unittest.TestCase):
    def test_permanent_buff_counts_once_per_event(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_123")
        m = put(g, a, MURLOC)
        m.add_buff(Enchant(atk=2, health=2))
        # 一次 +2/+2 = 1 次（不是 4 个点数）
        self.assertEqual(a._quest_progress, 1)

    def test_temporary_buff_not_counted(self):
        """负对照: 战斗内临时附魔不算"增加属性"。"""
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_123")
        m = put(g, a, MURLOC)
        m.add_buff(Enchant(atk=3, health=3, temporary=True))
        self.assertEqual(a._quest_progress, 0)

    def test_opponent_minion_buff_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_123")
        m = put(g, b, MURLOC)
        m.add_buff(Enchant(atk=5, health=5))
        self.assertEqual(a._quest_progress, 0)

    def test_fourteen_events_complete(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_123")
        m = put(g, a, MURLOC)
        for i in range(14):
            m.add_buff(Enchant(atk=1, health=1))
        self.assertTrue(a._quest_completed)
        self.assertEqual(len(a.quest_rewards), 1)


class TestQuest124ReenactMurder(unittest.TestCase):
    def test_friendly_deaths_count(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_124")
        for i in range(17):
            m = put(g, a, MURLOC)
            g.destroy_minion(m, hero=a)
            if i == 0:
                self.assertEqual(a._quest_progress, 1)
        self.assertEqual(a._quest_progress, 17)
        self.assertTrue(a._quest_completed)

    def test_opponent_death_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_124")
        m = put(g, b, MURLOC)
        g.destroy_minion(m, hero=b)
        self.assertEqual(a._quest_progress, 0)


class TestQuest125SortItAllOut(unittest.TestCase):
    def _combat_with_boards(self, g, a, b, atks_a, atks_b):
        for x in atks_a:
            m = put(g, a, MURLOC)
            m.set(GameTag.BASE_ATK, x)
            m.set(GameTag.HEALTH, 1)
        for x in atks_b:
            m = put(g, b, MURLOC)
            m.set(GameTag.BASE_ATK, x)
            m.set(GameTag.HEALTH, 1)
        g.run_combat(a, b)

    def test_ascending_board_counts_descending_does_not(self):
        g = make_game(seed=74)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_125")
        self._combat_with_boards(g, a, b, [1, 2, 3], [5])
        self.assertEqual(a._quest_progress, 1)
        # 乱序（负对照）
        for m in list(a.board):
            m.set(GameTag.BASE_ATK, 9)
        self._combat_with_boards(g, a, b, [3, 1], [5])
        self.assertEqual(a._quest_progress, 1)

    def test_ties_allowed(self):
        g = make_game(seed=75)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_125")
        self._combat_with_boards(g, a, b, [2, 2], [5])
        self.assertEqual(a._quest_progress, 1)

    def test_opponent_order_irrelevant(self):
        g = make_game(seed=76)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_125")
        for x in (1, 2):
            put(g, a, MURLOC).set(GameTag.BASE_ATK, x)
        for x in (9, 1):
            put(g, b, MURLOC).set(GameTag.BASE_ATK, x)
        g.run_combat(a, b)
        # 本人升序 → 计 1（对手乱序不影响本人）
        self.assertEqual(a._quest_progress, 1)


class TestQuest126FollowTheMoney(unittest.TestCase):
    def test_gold_amount_accumulates(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_126")
        a.gold = 100
        g.spend_gold(a, 3)
        self.assertEqual(a._quest_progress, 3)
        g.spend_gold(a, 24)
        self.assertEqual(a._quest_progress, 27)
        self.assertTrue(a._quest_completed)
        self.assertEqual(len(a.quest_rewards), 1)

    def test_opponent_spend_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_126")
        b.gold = 100
        g.spend_gold(b, 27)
        self.assertEqual(a._quest_progress, 0)


class TestQuest151UnlikelyDuo(unittest.TestCase):
    def test_races_come_from_card_data(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_151")
        self.assertEqual(a.quest._quest_races, frozenset({Race.MURLOC,
                                                          Race.BEAST}))

    def test_buy_matching_race_counts_other_race_does_not(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_151")
        for i in range(4):
            cid = MURLOC if i % 2 == 0 else BEAST
            a.gold = 10
            m = tavern_m(g, a, cid)
            self.assertTrue(g.buy_from_tavern(a, m))
        self.assertTrue(a._quest_completed)
        self.assertEqual(a._quest_progress, 4)

    def test_third_race_not_counted(self):
        """负对照: 非两族购买不推进。"""
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_151")
        a.gold = 50
        m = tavern_m(g, a, QUILBOAR)
        g.buy_from_tavern(a, m)
        self.assertEqual(a._quest_progress, 0)

    def test_all_race_counts(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_151")
        a.gold = 50
        # 37.0: 旧 ALL 角色卡 `Motley Phalanx` 已退出池；用 37.0 新池内
        # ALL 随从 `Dark Paradox`（BG36_360）验证 "Any minion type" 族计数。
        m = tavern_m(g, a, minion_id("Dark Paradox"))
        g.buy_from_tavern(a, m)
        self.assertEqual(a._quest_progress, 1)

    def test_opponent_buy_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_151")
        b.gold = 50
        m = tavern_m(g, b, MURLOC)
        g.buy_from_tavern(b, m)
        self.assertEqual(a._quest_progress, 0)


class TestQuest311CryForHelp(unittest.TestCase):
    def test_battlecry_minion_counts(self):
        """4 个**不同**、无定向/选择分支的 BATTLECRY 随从（避免三连与
        `PendingChoice` 分母干扰）。"""
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_311")
        ids = [d.id for d in get_db().pool_minions()
               if "battlecry" in d.keywords
               and not getattr(REGISTRY.get(d.id), "needs_target", False)
               and not getattr(REGISTRY.get(d.id), "choose_options", None)][:4]
        self.assertEqual(len(ids), 4)
        for cid in ids:
            m = put_in_hand(g, a, cid)
            while len(a.board) >= 7:
                g.sell_minion(a, a.board[-1])
            g.play_minion(a, m)
        self.assertEqual(a._quest_progress, 4)
        self.assertTrue(a._quest_completed)

    def test_non_battlecry_minion_not_counted(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_311")
        m = put_in_hand(g, a, NO_BATTLECRY)
        g.play_minion(a, m)
        self.assertEqual(a._quest_progress, 0)

    def test_opponent_battlecry_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_311")
        m = put_in_hand(g, b, BATTLECRY)
        g.play_minion(b, m)
        self.assertEqual(a._quest_progress, 0)


class TestQuest313InviteGuests(unittest.TestCase):
    def test_buy_minions_complete(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_313")
        for i in range(6):
            a.gold = 10
            m = tavern_m(g, a, MURLOC)
            g.buy_from_tavern(a, m)
        self.assertTrue(a._quest_completed)

    def test_opponent_buy_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_313")
        b.gold = 10
        m = tavern_m(g, b, MURLOC)
        g.buy_from_tavern(b, m)
        self.assertEqual(a._quest_progress, 0)


class TestQuest314DustForPrints(unittest.TestCase):
    def test_add_to_hand_counts(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_314")
        for _ in range(23):
            if a.hand_full():
                a.hand.pop()
            put_in_hand(g, a, MURLOC)
        self.assertTrue(a._quest_completed)

    def test_opponent_draw_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_314")
        put_in_hand(g, b, MURLOC)
        self.assertEqual(a._quest_progress, 0)


class TestQuest318WitnessProtection(unittest.TestCase):
    def test_taunted_defender_counts(self):
        g = make_game(seed=77)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_318")
        m = put(g, b, MURLOC)           # 对手攻击者（攻高，必然攻击）
        m.set(GameTag.BASE_ATK, 1)
        m.set(GameTag.HEALTH, 50)
        t = put(g, a, TAUNT)
        t.set(GameTag.BASE_ATK, 0)
        t.set(GameTag.HEALTH, 50)
        g.run_combat(a, b)
        self.assertGreaterEqual(a._quest_progress, 1)

    def test_non_taunt_defender_not_counted(self):
        """负对照: 非嘲讽被攻击不推进。"""
        g = make_game(seed=78)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_318")
        m = put(g, b, MURLOC)
        m.set(GameTag.BASE_ATK, 1)
        m.set(GameTag.HEALTH, 50)
        t = put(g, a, MURLOC)           # 无 TAUNT
        t.set(GameTag.BASE_ATK, 0)
        t.set(GameTag.HEALTH, 50)
        g.run_combat(a, b)
        self.assertEqual(a._quest_progress, 0)

    def test_opponent_taunt_not_counted(self):
        g = make_game(seed=79)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_318")
        m = put(g, a, MURLOC)
        m.set(GameTag.BASE_ATK, 1)
        m.set(GameTag.HEALTH, 50)
        t = put(g, b, TAUNT)
        t.set(GameTag.BASE_ATK, 0)
        t.set(GameTag.HEALTH, 50)
        g.run_combat(a, b)
        self.assertEqual(a._quest_progress, 0)


class TestQuest320ExhumeBones(unittest.TestCase):
    def test_deathrattle_trigger_counts(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_320")
        for _ in range(6):
            m = put(g, a, DEATHRATTLE)
            g.destroy_minion(m, hero=a)
        self.assertTrue(a._quest_completed)

    def test_opponent_deathrattle_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG24_Quest_320")
        m = put(g, b, DEATHRATTLE)
        g.destroy_minion(m, hero=b)
        self.assertEqual(a._quest_progress, 0)


class TestQuest351HireInvestigator(unittest.TestCase):
    def test_turn_end_with_unspent_gold_counts(self):
        g = make_game(n_heroes=3)
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_351")
        for _ in range(3):
            a.gold = 2
            g.events.fire(g, "turn_end", turn=g.turn)
        self.assertTrue(a._quest_completed)

    def test_zero_gold_turn_not_counted(self):
        """负对照: 花光金币的回合不计。"""
        g = make_game(n_heroes=3)
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_351")
        for _ in range(3):
            a.gold = 0
            g.events.fire(g, "turn_end", turn=g.turn)
        self.assertEqual(a._quest_progress, 0)

    def test_other_hero_gold_irrelevant(self):
        g = make_game(n_heroes=3)
        a, b = g.heroes[0], g.heroes[1]
        attach(g, a, "BG24_Quest_351")
        a.gold = 0
        b.gold = 5
        g.events.fire(g, "turn_end", turn=g.turn)
        self.assertEqual(a._quest_progress, 0)


class TestQuest352CrackTheCase(unittest.TestCase):
    def test_friendly_attacks_count(self):
        g = make_game(seed=80)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_352")
        for _ in range(3):
            for m in list(a.board):
                g.sell_minion(a, m)
            for m in list(b.board):
                g.sell_minion(b, m)
            x = put(g, a, MURLOC)
            x.set(GameTag.BASE_ATK, 1)
            x.set(GameTag.HEALTH, 60)
            y = put(g, b, MURLOC)
            y.set(GameTag.BASE_ATK, 1)
            y.set(GameTag.HEALTH, 60)
            g.run_combat(a, b)
            g.events.fire(g, "combat_end", hero_a=a, hero_b=b,
                          result=None)
        self.assertGreaterEqual(a._quest_progress, 3)

    def test_opponent_attacks_not_counted(self):
        """负对照: 对手攻击不推进本人。"""
        g = make_game(seed=81)
        a, b = g.heroes
        attach(g, a, "BG24_Quest_352")
        for m in list(a.board):
            g.sell_minion(a, m)
        y = put(g, b, MURLOC)
        y.set(GameTag.BASE_ATK, 1)
        y.set(GameTag.HEALTH, 60)
        g.run_combat(a, b)
        self.assertEqual(a._quest_progress, 0)


class TestQuest800BurnEvidence(unittest.TestCase):
    def test_sell_counts(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG27_Quest_800")
        for i in range(6):
            m = put(g, a, MURLOC)
            g.sell_minion(a, m)
        self.assertTrue(a._quest_completed)

    def test_opponent_sell_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG27_Quest_800")
        m = put(g, b, MURLOC)
        g.sell_minion(b, m)
        self.assertEqual(a._quest_progress, 0)


class TestQuest801PressureAuthorities(unittest.TestCase):
    def test_threshold_completed_by_total_attack(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG27_Quest_801")
        m = put(g, a, MURLOC)
        m.set(GameTag.BASE_ATK, 20)
        m.set(GameTag.HEALTH, 20)
        # 任意一次重算事件
        m.add_buff(Enchant(atk=8, health=0))
        self.assertEqual(a._quest_progress, 28)
        self.assertTrue(a._quest_completed)

    def test_below_threshold_not_completed(self):
        """负对照: 27 < 28 不完成。"""
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG27_Quest_801")
        m = put(g, a, MURLOC)
        m.set(GameTag.BASE_ATK, 20)
        m.set(GameTag.HEALTH, 20)
        m.add_buff(Enchant(atk=7, health=0))
        self.assertEqual(a._quest_progress, 27)
        self.assertFalse(a._quest_completed)

    def test_opponent_high_attack_does_not_complete(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG27_Quest_801")
        m = put(g, b, MURLOC)
        m.set(GameTag.BASE_ATK, 40)
        m.add_buff(Enchant(atk=1, health=0))
        self.assertEqual(a._quest_progress, 0)

    def test_summon_path_recomputes(self):
        """`summon` 也是重算生产点（打出高攻随从凑够）。"""
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG27_Quest_801")
        m = put_in_hand(g, a, MURLOC)
        g.play_minion(a, m)
        m.set(GameTag.BASE_ATK, 28)
        m2 = put(g, a, MURLOC)          # summon → recompute
        self.assertTrue(a._quest_completed)

    def test_progress_never_decreases(self):
        """阈值式任务"曾经达到过" —— `set_quest_progress` 只升不降。

        真实路径: 先经 `buff_applied` 重算到 25; 再降低 warband 总攻击
        （BASE_ATK 20→1）并触发同一条重算事件，把 6 写回。单调闸必须
        拒绝。变异探针: 删除 `set_quest_progress` 的
        `if value <= hero._quest_progress: return False` 守卫 →
        `_quest_progress` 被改写成 6 → 本测试失败（对抗审查 2026-09-18
        发现的"允许下降"变异此前存活）。
        """
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG27_Quest_801")
        m = put(g, a, MURLOC)
        m.set(GameTag.BASE_ATK, 20)
        m.set(GameTag.HEALTH, 20)
        m.add_buff(Enchant(atk=5, health=0))       # 重算 → 25
        self.assertEqual(a._quest_progress, 25)
        m.set(GameTag.BASE_ATK, 1)                 # warband 总攻击降到 6
        m.add_buff(Enchant(atk=0, health=1))       # 重算事件 → set(6)
        self.assertEqual(a._quest_progress, 25)    # 不得回退
        self.assertFalse(a._quest_completed)
        # 直接真实 API: 更低的显式值同样被拒（返回 False）
        self.assertFalse(g.set_quest_progress(a, 4))
        self.assertEqual(a._quest_progress, 25)
        # 正对照: 更高的值仍可写入
        self.assertFalse(g.set_quest_progress(a, 27))
        self.assertEqual(a._quest_progress, 27)


class TestQuest802RoundUpSuspects(unittest.TestCase):
    def test_destroy_enemy_counts(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG27_Quest_802")
        for _ in range(17):
            m = put(g, b, MURLOC)
            g.destroy_minion(m, hero=a)
        self.assertTrue(a._quest_completed)

    def test_destroy_own_not_counted(self):
        """负对照: 摧毁自己随从不算 "enemy"。"""
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG27_Quest_802")
        m = put(g, a, MURLOC)
        g.destroy_minion(m, hero=a)
        self.assertEqual(a._quest_progress, 0)


class TestQuest500FillCauldron(unittest.TestCase):
    def test_cast_spell_counts(self):
        """真实 `play_spell` ×11（11 张不同已注册、无需选择/定向的法术）。"""
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG28_Quest_500")

        def castable(cid):
            sc = REGISTRY[cid]
            return (not getattr(sc, "needs_target", False)
                    and not getattr(sc, "choose_options", None))

        ids = [d.id for d in get_db().pool_spells()
               if d.id in REGISTRY and castable(d.id)][:11]
        self.assertEqual(len(ids), 11)
        for cid in ids:
            s = g.create_spell(cid, controller=a)
            a.add_to_hand(s)
            g.play_spell(a, s)
            self.assertEqual(g.pending_choices, [])
        self.assertEqual(a._quest_progress, 11)
        self.assertTrue(a._quest_completed)

    def test_effect_cast_also_counts(self):
        """效果施法（`cast_spell_effect`）走同一 `spell_resolved` 生产点。"""
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG28_Quest_500")
        self.assertTrue(g.cast_spell_effect(a, "BG28_603"))   # Boon of Beetles
        self.assertEqual(a._quest_progress, 1)

    def test_opponent_cast_not_counted(self):
        g = make_game()
        a, b = g.heroes
        attach(g, a, "BG28_Quest_500")
        s = g.create_spell("BG28_603", controller=b)
        b.add_to_hand(s)
        g.play_spell(b, s)
        self.assertEqual(a._quest_progress, 0)


class TestPendingChoiceOfferRealPath(unittest.TestCase):
    """真实 `_offer_quests` → PendingChoice → resolve → **事件接线**生效。

    本类必须对"任务脚本是否存在"敏感（`audit_vacuous_tests --strict` 的
    类级全空转判据）: 断言 resolve 之后**事件总线上确有任务实体拥有的
    监听器**（= 脚本 `on_bind` 真的注册了），再用真实事件推进 1 步。
    """

    def test_offer_resolves_to_a_progressible_quest(self):
        g = make_game(seed=82, n_heroes=2)
        a = g.heroes[0]
        # 直接调引擎发放（真实 T4 由 _begin_recruit_for 调）
        g._offer_quests(a)
        ch = [c for c in g.pending_choices if c.kind == "quest_offer"]
        self.assertEqual(len(ch), 1)
        self.assertEqual(len(ch[0].options), 3)
        qid, rid = ch[0].options[0]
        self.assertIn(qid, REGISTERED)
        ch[0].resolve_callback((qid, rid))
        self.assertEqual(a.quest.card_id, qid)
        self.assertIsNotNone(g.quest_target(a))

    def test_resolve_wires_the_script_listener_and_advances(self):
        """定向用例: 指定任务 → `on_bind` 注册监听器 → 真实事件推进。

        变异（把 `batch_quests` 的任一 hook 换成 no-op）会去掉该监听器
        → 本测试失败（`TestQuest…` 类之外的第二重保险; 也是空转门禁
        要求的"非空转"证据）。
        """
        g = make_game(seed=82, n_heroes=2)
        a = g.heroes[0]
        g._offer_quests(a)
        ch = [c for c in g.pending_choices if c.kind == "quest_offer"][0]
        # 用池内真实奖励 id（不必是 offer 抽中的那一张）
        ch.resolve_callback(("BG24_Quest_112", REWARD))
        self.assertEqual(a.quest.card_id, "BG24_Quest_112")
        listeners = [l for l in g.events._listeners.get("tavern_refresh", [])
                     if l.owner is a.quest]
        self.assertEqual(len(listeners), 1,
                         "任务 on_bind 未注册 tavern_refresh 监听器")
        a.gold = 10
        g.refresh_tavern(a, auto=False)
        self.assertEqual(a._quest_progress, 1)

    def test_offer_candidates_never_unregistered(self):
        g = make_game(seed=83, n_heroes=2)
        a = g.heroes[0]
        g._offer_quests(a)
        ch = [c for c in g.pending_choices if c.kind == "quest_offer"][0]
        for qid, rid in ch.options:
            self.assertIn(qid, REGISTRY)
            self.assertIsNotNone(get_db().get(qid).quest_progress_total)


class TestCompletionGuards(unittest.TestCase):
    """唯一发奖入口 / 二次计分闸。"""

    def test_advance_after_completion_is_noop(self):
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_112")
        a.gold = 50
        for _ in range(8):
            g.refresh_tavern(a, auto=False)
        self.assertTrue(a._quest_completed)
        before = a._quest_progress
        n = len(a.quest_rewards)
        g.advance_quest_progress(a, 5)
        self.assertEqual(a._quest_progress, before)
        self.assertEqual(len(a.quest_rewards), n)

    def test_no_quest_no_progress(self):
        g = make_game()
        a = g.heroes[0]
        self.assertFalse(g.advance_quest_progress(a, 1))

    def test_complete_quest_is_idempotent(self):
        g = make_game()
        a = g.heroes[0]
        a._quest_reward_id = REWARD
        g.complete_quest(a)
        g.complete_quest(a)
        self.assertEqual(len(a.quest_rewards), 1)


if __name__ == "__main__":
    unittest.main()
