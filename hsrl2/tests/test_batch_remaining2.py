"""批次 remaining2 行为层测试（4 张载荷随从: Kaboom Bot / Silver Goose
基础 + 金色）。

全部断言走真实引擎路径:
  - 死亡: 真实 `game._process_single_death`（亡语分发）
  - 战斗: 真实 `game.run_combat`（`CombatScheduler.run` 设置
    `game._active_combat` → 亡语经它定位敌方）+ **战斗内 DAMAGE 探针**
    （战后回滚会把血量复原，故必须战斗内观察; SOP §16 空转判定法）
  - 伤害: 真实 `Hit` → `take_damage` → `fire("damage")` → `check_deaths`
  - 召唤: 真实 `game.summon`（token 经 create_minion，不占池）

覆盖口径: 每个行为方法都有**正效果断言**（hook 换 no-op 后必失败）+
负对照（无战斗 / 敌方空盘 / 无关友方受伤 / 对手来源 / 0 伤害 / 致死）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import GainKeyword, Hit
from hsrl2.db import CardDB
from hsrl2.events import DAMAGE, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# ── 本批 id（CardDB 按名核实——禁止凭记忆写 id） ──
KABOOM = "BG_BOT_606"
KABOOM_G = "TB_BaconUps_028"
SILVER_GOOSE = "BG29_801"
SILVER_GOOSE_G = "BG29_801_G"
FLEDGLING = "BG29_801t"
FLEDGLING_G = "BG29_801_Gt"

_ALL_BATCH_IDS = (KABOOM, KABOOM_G, SILVER_GOOSE, SILVER_GOOSE_G)

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 902) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def put(game: Game, hero: Hero, card_id: str,
        position: int | None = None) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m, position)
    return m


def tank(game: Game, hero: Hero, name: str = "TANK",
         atk: int = 1, health: int = 30) -> Minion:
    """手工实体（探针/受击靶）——不经 REGISTRY，不受空转突变影响。"""
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    assert game.summon(hero, m)
    return m


def slay(game: Game, m: Minion) -> None:
    """真实死亡路径（亡语分发）。"""
    m.health = 0
    game._process_single_death(m)


def decisions(game: Game, label: str) -> list:
    return [d for d in game.rng.decisions if d[0] == label]


def damage_probe(game: Game, victim: Minion) -> list:
    """在 `victim` 上装 DAMAGE 探针，返回 (amount, source_card_id) 记录列表。

    `source_card_id` = 伤害来源卡 id（攻击路径 = 攻击者; 亡语 `Hit` 不传
    source → None）——据此把"亡语伤害实例"与"攻击伤害"分开断言。
    """
    log: list = []

    def cb(g, minion=None, amount=None, source=None, **kw):
        if minion is victim and amount:
            log.append((amount,
                        source.card_id if source is not None else None))

    game.events.register(Listener(event=DAMAGE, owner=victim, callback=cb))
    return log


def own(game: Game, hero: Hero, card_id: str) -> int:
    return sum(1 for m in hero.board if m.card_id == card_id)


class TestRegistryAndCardDefs(unittest.TestCase):
    """@engine-only 结构性: 注册表 / 金色数据链 / 池外前提 / num 纪律。"""

    def test_all_batch_ids_registered(self):
        missing = [cid for cid in _ALL_BATCH_IDS if cid not in REGISTRY]
        self.assertEqual(missing, [])

    def test_golden_ids_match_db_data_chain(self):
        db = get_db()
        for base, expected_golden in ((KABOOM, KABOOM_G),
                                      (SILVER_GOOSE, SILVER_GOOSE_G)):
            g = db.golden_version(db.get(base))
            self.assertIsNotNone(g, base)
            self.assertEqual(g.id, expected_golden, base)

    def test_all_batch_cards_are_out_of_pool(self):
        """本批前提: 4 张本体全部 is_pool_minion=False（池外载荷）。"""
        db = get_db()
        for cid in _ALL_BATCH_IDS:
            self.assertFalse(db.get(cid).is_pool_minion, cid)
            self.assertFalse(db.get(cid).is_pool_spell, cid)

    def test_num_discipline(self):
        """数值纪律: Kaboom num(0)=4（基础/金色同值），其余全 None。"""
        db = get_db()
        for cid in (KABOOM, KABOOM_G):
            self.assertEqual(db.get(cid).num(0), 4, cid)
            self.assertEqual(
                [db.get(cid).num(i) for i in range(1, 5)],
                [None] * 4, cid)
        for cid in (SILVER_GOOSE, SILVER_GOOSE_G):
            self.assertEqual(
                [db.get(cid).num(i) for i in range(5)],
                [None] * 5, cid)

    def test_fledgling_token_carddefs(self):
        """召唤物数值全部来自 token CardDef（脚本零硬编码）——漂移守护。"""
        db = get_db()
        base = db.get(FLEDGLING)
        gold = db.get(FLEDGLING_G)
        self.assertEqual((base.atk, base.health), (2, 2))
        self.assertEqual((gold.atk, gold.health), (4, 4))
        for d in (base, gold):
            self.assertIn("taunt", d.keywords, d.id)
            self.assertFalse(d.is_pool_minion, d.id)


class TestKaboomBot(unittest.TestCase):
    """BG_BOT_606 / TB_BaconUps_028 — 亡语: 对随机敌方随从造成 4 点伤害。"""

    def test_deathrattle_in_real_combat_damages_enemy(self):
        game = make_game(seed=5)
        a, b = game.heroes
        put(game, a, KABOOM)                     # 唯一有亡语的己方随从
        enemy = tank(game, b, "ENEMY", atk=1, health=30)
        ally = tank(game, a, "ALLY", health=9)   # 己方对照（不受伤）
        log = damage_probe(game, enemy)
        game.run_combat(a, b)
        # 正效果: 亡语伤害实例恰 1 次 4 点（source=None = 亡语 Hit）
        dmg = [amt for amt, src in log if src is None]
        self.assertEqual(dmg, [4])
        self.assertEqual(
            len(decisions(game, "kaboom_bot_target")), 1)
        # 负对照: 己方随从不吃自己的亡语伤害
        self.assertEqual(ally.health, 9)

    def test_golden_reselects_among_living_enemies(self):
        """金色 "twice" 的两次实例各自在**当时存活**敌方中重选。

        确定性控制: `rng.choice` 被替换为"取列表中第一个存活者"（若非
        逐实例重选、而是循环外一次性取目标, 第二次必然重复命中已死实体
        → 断言失败）。"""
        from hsrl2.scripts.batches import batch_remaining2 as _b
        game = make_game(seed=3)
        a, b = game.heroes
        bomb = put(game, a, KABOOM_G)
        e1 = tank(game, b, "E1", atk=2, health=1)
        e2 = tank(game, b, "E2", atk=2, health=1)
        game._active_combat = (a, b)
        game.rng.choice = lambda seq, label=None: seq[0]
        hit_targets = []
        real_hit = _b.Hit

        class _StubHit:
            def __init__(self, target, amount):
                self.target, self.amount = target, amount

            def do(self, g):
                hit_targets.append(self.target)
                self.target.health = 0       # 死亡波次即时生效

        _b.Hit = _StubHit
        try:
            _b.KaboomBlast(bomb, 2).do(game)
        finally:
            _b.Hit = real_hit
        self.assertEqual(len(hit_targets), 2, "两个实例未各结算一次")
        self.assertEqual(len({id(t) for t in hit_targets}), 2,
                         "第二实例重复命中已死实体（未按当时存活重选）")

    def test_golden_real_combat_two_instances(self):
        """真实战斗中金色恰两个伤害实例（敌方 30 血, 无一被击杀 → 两次
        都命中存活目标; 战斗内探针观察以免战后回滚掩盖）。"""
        game = make_game(seed=4)
        a, b = game.heroes
        bomb = put(game, a, KABOOM_G)
        bomb.set(GameTag.ATK, 0)
        bomb.set(GameTag.BASE_ATK, 0)
        for i in range(2):
            tank(game, b, f"E{i}", atk=2, health=30)
        log = []
        game.events.register(Listener(
            event=DAMAGE, owner=None,
            callback=lambda g, minion=None, amount=0, source=None, **kw: (
                log.append(amount) if source is None else None)))
        game.run_combat(a, b)
        self.assertEqual(log, [4, 4])

    def test_goose_lethal_damage_in_combat_summons_fledgling(self):
        """Silver Goose 在**战斗内致死伤害**时仍召唤 Fledgling（监听器
        在伤害分发中先于死亡结算运行; 对抗验证指出此前无此项覆盖）。"""
        game = make_game(seed=11)
        a, b = game.heroes
        goose = put(game, a, SILVER_GOOSE)
        tank(game, b, "BIG", atk=10, health=30)
        seen = []
        game.events.register(Listener(
            event=DAMAGE, owner=None,
            callback=lambda g, minion=None, amount=0, **kw: (
                seen.append([m.card_id for m in a.board])
                if (minion is goose and amount > 0) else None)))
        game.run_combat(a, b)
        self.assertTrue(seen, "战斗内 Goose 未受伤（前置条件）")
        self.assertTrue(any(FLEDGLING in ids for ids in seen),
                        "致死伤害时未召唤 Fledgling")

    def test_recruit_death_fizzles_then_positive(self):
        game = make_game(seed=6)
        a, b = game.heroes
        kaboom = put(game, a, KABOOM)
        enemy = tank(game, b, "ENEMY", health=30)
        log = damage_probe(game, enemy)
        slay(game, kaboom)                        # 无战斗 → 无敌方棋盘
        self.assertEqual(log, [])
        self.assertEqual(decisions(game, "kaboom_bot_target"), [])
        # 正对照: 同一 setup 下设 `_active_combat`（引擎在
        # `CombatScheduler.run` 中即如此设置）→ 效果发生
        kaboom2 = put(game, a, KABOOM)
        game._active_combat = (a, b)
        try:
            slay(game, kaboom2)
        finally:
            game._active_combat = None
        self.assertEqual([amt for amt, src in log if src is None], [4])

    def test_no_living_enemy_fizzles(self):
        game = make_game(seed=7)
        a, b = game.heroes
        kaboom = put(game, a, KABOOM)
        game._active_combat = (a, b)              # 对面板空
        try:
            slay(game, kaboom)
        finally:
            game._active_combat = None
        self.assertEqual(decisions(game, "kaboom_bot_target"), [])
        # 正对照: 放一个敌方随从后确有选取与伤害
        enemy = tank(game, b, "ENEMY", health=30)
        log = damage_probe(game, enemy)
        kaboom2 = put(game, a, KABOOM)
        game._active_combat = (a, b)
        try:
            slay(game, kaboom2)
        finally:
            game._active_combat = None
        self.assertEqual([amt for amt, src in log if src is None], [4])

    def test_golden_deals_two_instances(self):
        game = make_game(seed=5)
        a, b = game.heroes
        put(game, a, KABOOM_G, position=0)
        enemy = tank(game, b, "ENEMY", atk=1, health=30)
        log = damage_probe(game, enemy)
        game.run_combat(a, b)
        dmg = [amt for amt, src in log if src is None]
        self.assertEqual(dmg, [4, 4])             # "twice" = 2 个实例
        self.assertEqual(len(decisions(game, "kaboom_bot_target")), 2)

    def test_golden_second_instance_fizzles_when_no_target_left(self):
        """第一实例致死后敌方无存活者 → 第二实例落空（不再打尸体）。"""
        game = make_game(seed=8)
        a, b = game.heroes
        kaboom = put(game, a, KABOOM_G)
        enemy = tank(game, b, "ENEMY", health=4)  # 恰被 4 点伤害打死
        log = damage_probe(game, enemy)
        game._active_combat = (a, b)
        try:
            slay(game, kaboom)
        finally:
            game._active_combat = None
        self.assertEqual([amt for amt, src in log if src is None], [4])
        self.assertTrue(enemy.dead)
        self.assertEqual(len(decisions(game, "kaboom_bot_target")), 1)

    def test_owner_isolation_and_pool_untouched(self):
        game = make_game(seed=9)
        a, b = game.heroes
        before = game.minion_pool.available(KABOOM)
        kaboom = put(game, a, KABOOM)
        mine = tank(game, a, "MINE", health=30)
        enemy = tank(game, b, "ENEMY", health=30)
        my_log = damage_probe(game, mine)
        enemy_log = damage_probe(game, enemy)
        game._active_combat = (a, b)
        try:
            slay(game, kaboom)                    # 我的亡语只打敌方
        finally:
            game._active_combat = None
        self.assertEqual(my_log, [])              # 己方不被自己的亡语命中
        self.assertEqual([amt for amt, src in enemy_log if src is None], [4])
        # 反向: 敌方 Kaboom 的亡语只打我方、不打它自己那侧
        enemy_kaboom = put(game, b, KABOOM)
        enemy_hp = enemy.health
        game._active_combat = (b, a)
        try:
            slay(game, enemy_kaboom)
        finally:
            game._active_combat = None
        self.assertEqual([amt for amt, src in my_log if src is None], [4])
        self.assertEqual(enemy.health, enemy_hp)
        # 池外卡: 生/死均零池操作
        self.assertEqual(game.minion_pool.available(KABOOM), before)

    def test_same_seed_same_target(self):
        """同 seed → 命中的敌方随从（左/右）可复现。"""
        logs = []
        for _ in range(2):
            game = make_game(seed=12)
            a, b = game.heroes
            put(game, a, KABOOM)
            t1 = tank(game, b, "E1", health=30)
            t2 = tank(game, b, "E2", health=30)
            log1 = damage_probe(game, t1)
            log2 = damage_probe(game, t2)
            game.run_combat(a, b)
            logs.append(([amt for amt, src in log1 if src is None],
                         [amt for amt, src in log2 if src is None]))
        # 正效果: 恰一个实例、恰命中两侧之一
        self.assertEqual(logs[0][0] + logs[0][1], [4])
        self.assertEqual(logs[0], logs[1])       # 同 seed 同目标


class TestSilverGoose(unittest.TestCase):
    """BG29_801 / BG29_801_G — 受伤时召唤 Fledgling（2/2 或 4/4 Taunt）。"""

    def test_damage_summons_fledgling(self):
        game = make_game(seed=21)
        a, _b = game.heroes
        goose = put(game, a, SILVER_GOOSE)
        self.assertEqual(own(game, a, FLEDGLING), 0)     # 受伤前无
        pool_before = game.minion_pool.available(FLEDGLING)
        game.run_actions(Hit(goose, 1))
        self.assertEqual(own(game, a, FLEDGLING), 1)     # 正效果
        fled = [m for m in a.board if m.card_id == FLEDGLING][0]
        self.assertEqual((fled.atk, fled.health), (2, 2))
        self.assertTrue(fled.has(GameTag.TAUNT))
        self.assertEqual(game.minion_pool.available(FLEDGLING),
                         pool_before)                    # token 不占池

    def test_other_minion_damage_does_not_trigger(self):
        game = make_game(seed=22)
        a, _b = game.heroes
        put(game, a, SILVER_GOOSE)
        friend = tank(game, a, "FRIEND", health=9)
        game.run_actions(Hit(friend, 1))                 # "this" 以外的受伤
        self.assertEqual(own(game, a, FLEDGLING), 0)
        # 正对照: 同一 setup 下本体受伤确实召唤
        goose = [m for m in a.board if m.card_id == SILVER_GOOSE][0]
        game.run_actions(Hit(goose, 1))
        self.assertEqual(own(game, a, FLEDGLING), 1)

    def test_enemy_goose_does_not_summon_for_us(self):
        game = make_game(seed=23)
        a, b = game.heroes
        enemy_goose = put(game, b, SILVER_GOOSE)
        game.run_actions(Hit(enemy_goose, 1))
        self.assertEqual(own(game, a, FLEDGLING), 0)     # owner 隔离
        self.assertEqual(own(game, b, FLEDGLING), 1)     # 效果确实发生

    def test_zero_damage_does_not_summon(self):
        """圣盾抵消 → actual=0 → 不计（同 VeryHungryWinterfinner 口径）。"""
        game = make_game(seed=24)
        a, _b = game.heroes
        goose = put(game, a, SILVER_GOOSE)
        GainKeyword(goose, GameTag.DIVINE_SHIELD).do(game)
        game.run_actions(Hit(goose, 5))                  # 盾抵消 → 0
        self.assertEqual(own(game, a, FLEDGLING), 0)
        game.run_actions(Hit(goose, 5))                  # 盾破 → 真实伤害
        self.assertEqual(own(game, a, FLEDGLING), 1)

    def test_lethal_damage_still_summons(self):
        game = make_game(seed=25)
        a, _b = game.heroes
        goose = put(game, a, SILVER_GOOSE)
        game.run_actions(Hit(goose, 99))                 # 致死一击
        self.assertTrue(goose.dead)
        self.assertEqual(own(game, a, FLEDGLING), 1)

    def test_two_hits_summon_two_fledglings(self):
        game = make_game(seed=26)
        a, _b = game.heroes
        goose = put(game, a, SILVER_GOOSE)
        game.run_actions(Hit(goose, 1))
        game.run_actions(Hit(goose, 1))
        self.assertEqual(own(game, a, FLEDGLING), 2)

    def test_golden_summons_golden_fledgling(self):
        game = make_game(seed=27)
        a, _b = game.heroes
        goose = put(game, a, SILVER_GOOSE_G)
        game.run_actions(Hit(goose, 1))
        self.assertEqual(own(game, a, FLEDGLING_G), 1)
        self.assertEqual(own(game, a, FLEDGLING), 0)
        fled = [m for m in a.board if m.card_id == FLEDGLING_G][0]
        self.assertEqual((fled.atk, fled.health), (4, 4))
        self.assertTrue(fled.has(GameTag.TAUNT))

    def test_full_board_does_not_crash(self):
        game = make_game(seed=28)
        a, _b = game.heroes
        goose = put(game, a, SILVER_GOOSE)
        tanks = [tank(game, a, f"F{i}", health=5) for i in range(6)]
        self.assertEqual(len(a.board), 7)                # 满场
        game.run_actions(Hit(goose, 1))                  # MINION_OVERFLOW
        self.assertEqual(own(game, a, FLEDGLING), 0)
        self.assertFalse(goose.dead)
        # 正对照: 腾出位置后同一本体受伤确实召唤
        slay(game, tanks[0])
        game.run_actions(Hit(goose, 1))
        self.assertEqual(own(game, a, FLEDGLING), 1)


if __name__ == "__main__":
    unittest.main()
