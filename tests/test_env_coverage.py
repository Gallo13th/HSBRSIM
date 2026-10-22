"""``tests/test_env_coverage.py`` —— RL 环境接口覆盖度/完整性测试。

对齐 `docs/ENV_INTERFACE_GAPS.md` 与 `scripts/audit_env_coverage.py`：

1. **目标枚举完整性**
   - 池内 22 张定向法术：每个在真实引擎状态里都生成 target 变体且可执行
   - 池内 5 张定向战吼：入场后目标集（含「以自身为目标」）与引擎
     `PendingChoice` 候选一致
   - 双目标英雄技能（Vol'jin Spirit Swap）：经 choice 步选满 2 个目标并生效
   - Choose One：两个分支都可达且效果不同
   - 磁力吸附扩展（Prosthetic Hand → Undead 宿主；非机械/亡灵宿主不生成）
2. **槽位一致性**：每个候选的 src/tgt 槽位与观测槽位同源（hunter bug 回归）
3. **统计/观测补全**：env.stats 覆盖度计数；info["obs_extra"] 契约
4. **覆盖率门禁**：N 局内每类动作/目标变体至少出现一次、0 invalid /
   0 engine_rejected / 0 槽位不一致 / 0 手牌组被裁
5. **多人数**：2/4/8 人局均可推进且 rank 合法
"""

from __future__ import annotations

import pickle
import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.agents.random_agent import RandomPolicy
from hsbg.env import BattlegroundsEnv, driver, observation
from hsbg.env import spec as env_spec
from hsbg.env.spec import (CANDIDATE_MAX, PHASE_GAME_OVER, ActionKind,
                          CandidateAction)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 7, hero_ids=("TEST_A", "TEST_B")) -> Game:
    heroes = [Hero(hid, name) for hid, name in zip(hero_ids,
                                                   ("A", "B"))]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, hero: Hero, card_id: str,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def hand_card(game: Game, hero: Hero, card_id: str,
              golden: bool = False):
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert hero.add_to_hand(m)
    return m


def hand_spell(game: Game, hero: Hero, card_id: str):
    s = game.create_spell(card_id, controller=hero)
    assert hero.add_to_hand(s)
    return s


def _custom_minion(game, hero, name, race, atk=2, health=2):
    m = Minion(f"TEST_{name}", name, atk=atk, health=health, race=race)
    m.game = game
    m.controller = hero
    return m


#: 三种"宽覆盖"种族组合（棋盘 6 + 手牌 2）——定向目标按种族过滤的卡在
#: 其中至少一种状态下有合法目标。棋盘容量 7，故每种组合只放 6 个。
_RACE_SETS = (
    ((Race.DEMON, Race.UNDEAD, Race.BEAST, Race.PIRATE, Race.DRAGON,
      Race.ELEMENTAL), (Race.DEMON, Race.BEAST)),
    ((Race.MECH, Race.MURLOC, Race.QUILBOAR, Race.NAGA, Race.DEMON,
      Race.UNDEAD), (Race.DEMON, Race.MURLOC)),
    ((Race.BEAST, Race.DEMON, Race.DRAGON, Race.MECH, Race.PIRATE,
      Race.MURLOC), (Race.QUILBOAR, Race.NAGA)),
)


#: race → 池内真实随从卡 id（目标必须是"真实实体"，法术效果常按
#: card_id 重新 create_minion；自定义 Minion 无 CardDef 会 KeyError）。
_RACE_POOL: dict = {}


def _race_pool_card(race) -> str:
    if not _RACE_POOL:
        db = get_db()
        for d in db.pool_minions():
            for r in d.races:
                _RACE_POOL.setdefault(r, d.id)
    cid = _RACE_POOL.get(race)
    if cid is not None:
        return cid
    # 兜底：池内首个随从（记录在此，避免静默 None）
    return next(d.id for d in get_db().pool_minions())


def _broad_started_game(seed: int = 7, race_set: int = 0):
    """真实 start_game 状态 + 宽种族覆盖的棋盘/手牌（目标审计用）。"""
    game = make_game(seed)
    game.start_game()
    driver.resolve_pending_choices(game, None)
    a, b = game.heroes
    a.gold = 60
    put(game, a, "BG36_112")                # 带战吼随从（TB_HP_022 需要）
    board_races, hand_races = _RACE_SETS[race_set % len(_RACE_SETS)]
    for race in board_races[:5]:                 # 留 1 格给"打出随从"
        m = game.create_minion(_race_pool_card(race), controller=a)
        assert game.summon(a, m)
    for race in hand_races:
        h = game.create_minion(_race_pool_card(race), controller=a)
        assert a.add_to_hand(h)
    return game, a, b


def _broad_states():
    return [_broad_started_game(seed=7 + i, race_set=i)
            for i in range(len(_RACE_SETS))]


def _targeted_pool_spells():
    return [d.id for d in get_db().pool_spells()
            if REGISTRY.get(d.id) is not None
            and getattr(REGISTRY.get(d.id), "needs_target", False)]


def _targeted_pool_minions():
    return [d.id for d in get_db().pool_minions()
            if REGISTRY.get(d.id) is not None
            and getattr(REGISTRY.get(d.id), "needs_target", False)]


class TestTargetedSpellEnumeration(unittest.TestCase):
    """(a) 需要目标的法术：每张都枚举 target 变体且可执行。"""

    def test_all_targeted_pool_spells(self):
        cids = _targeted_pool_spells()
        self.assertGreaterEqual(len(cids), 20, cids)
        missing = []
        bad_apply = []
        for cid in cids:
            found = False
            for state_idx in range(len(_RACE_SETS)):
                game, a, b = _broad_started_game(seed=7 + state_idx,
                                                 race_set=state_idx)
                spell = hand_spell(game, a, cid)
                descs = [d for d in driver.enumerate_actions(game, a)
                         if d.kind == ActionKind.PLAY_SPELL.value
                         and d.src_entity is spell]
                with_tgt = [d for d in descs if d.tgt_entity is not None]
                if not with_tgt:
                    continue
                found = True
                res = driver.apply_action(game, a, with_tgt[0])
                if not res.success:
                    bad_apply.append((cid, res.error_type, res.error))
                break
            if not found:
                missing.append(cid)
        self.assertEqual(missing, [], f"no target variant: {missing}")
        self.assertEqual(bad_apply, [], f"apply failed: {bad_apply}")

    def test_no_target_fallback_not_offered_when_targets_exist(self):
        """有可寻址目标时不生成"无目标"回退（避免退化路径）。"""
        checked = 0
        for cid in _targeted_pool_spells():
            for game, a, b in _broad_states():
                spell = hand_spell(game, a, cid)
                descs = [d for d in driver.enumerate_actions(game, a)
                         if d.kind == ActionKind.PLAY_SPELL.value
                         and d.src_entity is spell]
                with_tgt = [d for d in descs if d.tgt_entity is not None]
                netgt = [d for d in descs if d.tgt_entity is None]
                if with_tgt:
                    checked += 1
                    self.assertEqual(netgt, [], cid)
                    break
        self.assertGreater(checked, 15, checked)


class TestTargetedBattlecryEnumeration(unittest.TestCase):
    """(b) 定向战吼：入场后目标集（含自身）与引擎候选一致。"""

    def _variants_in_some_state(self, cid):
        """在若干宽覆盖状态中找该卡（手牌）的 play_minion 变体。"""
        for state_idx in range(len(_RACE_SETS)):
            game, a, b = _broad_started_game(seed=11 + state_idx,
                                             race_set=state_idx)
            m = hand_card(game, a, cid)
            descs = [d for d in driver.enumerate_actions(game, a)
                     if d.kind == ActionKind.PLAY_MINION.value
                     and d.src_entity is m]
            if descs:
                return game, a, b, m, descs
        return None, None, None, None, []

    def test_self_target_now_enumerated(self):
        """曾漏枚举「以自身为目标」（入场后才出现在候选里）的卡。"""
        for cid in ("BG26_814", "BG32_340"):
            game, a, b, m, descs = self._variants_in_some_state(cid)
            self.assertTrue(descs, f"{cid}: no candidate in broad states")
            tgt_entities = [d.tgt_entity for d in descs
                            if d.tgt_entity is not None]
            self.assertIn(m, tgt_entities,
                          f"{cid}: self-target variant missing")

    def test_engine_post_summon_candidates_match(self):
        """我们的目标集合覆盖引擎入场后候选（按 card_id 对齐）。"""
        for cid in _targeted_pool_minions():
            game, a, b, m, descs = self._variants_in_some_state(cid)
            self.assertTrue(descs, f"{cid}: no candidate in broad states")
            our_ids = {getattr(d.tgt_entity, "card_id", None)
                       for d in descs if d.tgt_entity is not None}
            # 引擎真值：同一初始状态真实打出（不带 target）
            state_idx = _RACE_SETS.index(_RACE_SETS[0])  # 占位
            game2, a2, b2 = _broad_started_game(seed=11, race_set=0)
            m2 = hand_card(game2, a2, cid)
            if not game2.play_minion(a2, m2):
                continue
            truth = list(game2.pending_choices[0].options) \
                if game2.pending_choices else []
            for t in truth:
                self.assertIn(getattr(t, "card_id", None), our_ids,
                              f"{cid}: engine candidate missing from driver")

    def test_all_targeted_battlecries_apply(self):
        bad = []
        for cid in _targeted_pool_minions():
            game, a, b, m, descs = self._variants_in_some_state(cid)
            if not descs:
                bad.append((cid, "NoCandidate"))
                continue
            first_tgt = next((d for d in descs
                              if d.tgt_entity is not None), None)
            res = driver.apply_action(game, a, first_tgt or descs[0])
            if not res.success:
                bad.append((cid, res.error_type, res.error))
        self.assertEqual(bad, [], bad)


class TestDualTargetHeroPower(unittest.TestCase):
    """(c) 双目标英雄技能（Vol'jin）: 经两次 choice 步选满目标。"""

    def test_voljin_two_choice_chain(self):
        env = BattlegroundsEnv(num_players=8, opponent="heuristic",
                               hero_id="BG20_HERO_201", seed=11)
        obs = env.reset(seed=11)
        game = env.game
        a = env.agent_hero
        # 给出 2 个可换攻随从（Vol'jin 候选 = 己方棋盘）
        for cid in ("BG25_001", "BGS_119"):
            m = game.create_minion(cid, controller=a)
            game.summon(a, m)
        obs = env._observe()
        dual = [d for d in env._step_actions.descriptors
                if d.kind == ActionKind.HERO_POWER.value
                and getattr(d, "note", "") == "targets=2"]
        self.assertTrue(dual, "dual-target hero power candidate missing")
        before = [m.atk for m in a.board[:2]]
        obs, reward, term, trunc, info = env.step(dual[0].to_candidate())
        self.assertFalse(info.get("invalid"))
        self.assertEqual(obs.phase, "choice")
        self.assertIn(obs.pending_choice.kind, ("hero_power_target",
                                                "target"))
        # 第一次选择
        obs, *_ = env.step(CandidateAction(kind="choose", option=0))
        self.assertEqual(obs.phase, "choice")           # 第二个目标
        # 第二次选择
        obs, reward, term, trunc, info = env.step(
            CandidateAction(kind="choose", option=0))
        self.assertFalse(info.get("invalid"))
        self.assertEqual(obs.phase, "recruit")
        # 两个随从攻击力互换（+对方攻击力），且目标数=2
        buffed = [m for m in a.board if m._buffs]
        self.assertEqual(len(buffed), 2, "expected exactly 2 buffed targets")
        env.close()


class TestChooseOneBranches(unittest.TestCase):
    """(d) Choose One 两个分支都可达且效果不同（经环境 choice 步）。"""

    SCARAB = "BG27_084"     # Give a Beast +{0}/+{1} and Reborn /
                            # Give a Beast +{2} Attack and Windfury

    def _play_and_choose(self, option: int):
        env = BattlegroundsEnv(seed=31)
        obs = env.reset(seed=31)
        game = env.game
        a = env.agent_hero
        beast = _custom_minion(game, a, "Beast", Race.BEAST, atk=2, health=2)
        game.summon(a, beast)
        scarab = game.create_minion(self.SCARAB, controller=a)
        a.add_to_hand(scarab)
        obs = env._observe()
        descs = [d for d in env._step_actions.descriptors
                 if d.kind == ActionKind.PLAY_MINION.value
                 and d.src_entity is scarab]
        self.assertTrue(descs, "no play_minion candidate for Scarab")
        obs, _r, _t, _tr, info = env.step(descs[0].to_candidate())
        self.assertFalse(info.get("invalid"))
        self.assertEqual(obs.phase, "choice")
        self.assertEqual(obs.pending_choice.kind, "choose_one")
        self.assertGreaterEqual(len(obs.pending_choice.options), 2)
        # 选择分支 key
        choice_idx = 0 if option == 0 else 1
        obs, _r, _t, _tr, info = env.step(
            CandidateAction(kind="choose", option=choice_idx))
        self.assertFalse(info.get("invalid"))
        # 引擎脚本对 choose_one 分支再挂一个 battlecry_target（缺省目标
        # 选择）——环境必须继续暴露为 choice 步
        if obs.phase == "choice":
            self.assertEqual(obs.pending_choice.kind, "battlecry_target")
            opts = [o.card_id for o in obs.pending_choice.options]
            idx = args = 0
            for i, cid in enumerate(opts):
                if cid == "TEST_Beast":
                    idx = i
                    break
            obs, _r, _t, _tr, info = env.step(
                CandidateAction(kind="choose", option=idx))
            self.assertFalse(info.get("invalid"))
        return env, beast

    def test_reborn_branch(self):
        env, beast = self._play_and_choose(0)
        self.assertTrue(beast.has(GameTag.REBORN))
        self.assertEqual(beast.atk, 3)          # +1/+1
        env.close()

    def test_windfury_branch(self):
        env, beast = self._play_and_choose(1)
        self.assertTrue(beast.has(GameTag.WINDFURY))
        self.assertFalse(beast.has(GameTag.REBORN))
        self.assertEqual(beast.atk, 6)          # +4 Attack
        env.close()


class TestMagneticTargets(unittest.TestCase):
    """(e) 磁力目标扩展（Prosthetic Hand: 机械或亡灵宿主）。"""

    def _mb(self):
        # Prosthetic Hand 是"纯关键词"卡（Magnetic/Reborn，无脚本——
        # 磁力合法宿主由引擎 `_magnetic_valid` 的数据例外实现）
        return "BG_DEEP_015"

    def test_undead_host_enumerated_and_applied(self):
        cid = self._mb()
        game = make_game(seed=41)
        a, b = game.heroes
        host = put(game, a, "BG25_001")            # Undead
        m = hand_card(game, a, cid)
        descs = [d for d in driver.enumerate_actions(game, a)
                 if d.kind == ActionKind.PLAY_MINION.value
                 and d.src_entity is m and d.tgt_entity is host]
        self.assertTrue(descs, "Prosthetic Hand → Undead host not enumerated")
        self.assertTrue(descs[0].magnetic)
        res = driver.apply_action(game, a, descs[0])
        self.assertTrue(res.success, res.error)
        self.assertTrue(host.has(GameTag.REBORN) or host.atk > 2)

    def test_non_allowed_host_not_enumerated(self):
        cid = self._mb()
        game = make_game(seed=42)
        a, b = game.heroes
        dragon = put(game, a, "BG34_630t")         # Dragon whelp
        m = hand_card(game, a, cid)
        descs = [d for d in driver.enumerate_actions(game, a)
                 if d.kind == ActionKind.PLAY_MINION.value
                 and d.src_entity is m and getattr(d, "magnetic", False)]
        self.assertFalse(any(d.tgt_entity is dragon for d in descs))


class TestSlotConsistency(unittest.TestCase):
    """观测槽位与候选槽位必须同源（hero_power 目标曾漏映射的回归）。"""

    @staticmethod
    def _inconsistencies(step_actions) -> list:
        bad = []
        zones = step_actions.zones
        for d, cand in zip(step_actions.descriptors, step_actions.candidates):
            for ent, zone, slot in (
                    (d.src_entity, cand.src_zone, cand.src_slot),
                    (d.tgt_entity, cand.tgt_zone, cand.tgt_slot)):
                if ent is None:
                    continue
                loc = zones.locate(ent)
                if loc is not None and (zone, slot) != loc:
                    bad.append((d.kind, getattr(ent, "card_id", None),
                                (zone, slot), loc))
        return bad

    def test_all_steps_slot_consistent(self):
        policy = HeuristicPolicy()
        env = BattlegroundsEnv(seed=5)
        obs = env.reset(seed=5)
        for _ in range(120):
            bad = self._inconsistencies(env._step_actions)
            self.assertEqual(bad, [], bad)
            if obs.phase == "choice":
                action = CandidateAction(
                    kind="choose", option=policy.choose_option_index(obs))
            else:
                desc = policy.choose(env.game, env.agent_hero)
                action = CandidateAction(kind="end_turn") if desc is None \
                    else desc.to_candidate()
            obs, _r, term, trunc, _i = env.step(action)
            if term or trunc:
                break
        env.close()

    def test_hero_power_target_slots_mapped(self):
        """所有带目标的英雄技能候选都必须有 tgt_zone/tgt_slot。"""
        db = get_db()
        seen = 0
        for hd in db._by_id.values():
            pid = getattr(hd, "hero_power_id", None)
            sc = REGISTRY.get(pid) if pid else None
            if sc is None or not getattr(sc, "needs_target", False):
                continue
            if int(getattr(sc, "target_count", 1)) > 1:
                continue
            game = Game([Hero(hd.id, "A"), Hero("TEST_B", "B")], db, seed=3)
            game.start_game()
            driver.resolve_pending_choices(game, None)
            game.turn = 6
            a = game.heroes[0]
            a.set(GameTag.TAVERN_TIER, 4)
            a.gold = 40
            put(game, a, "BG25_001")
            put(game, a, "BG36_112")
            game.refresh_tavern(a)
            descs = [d for d in driver.enumerate_actions(game, a)
                     if d.kind == ActionKind.HERO_POWER.value]
            with_tgt = [d for d in descs if d.tgt_entity is not None]
            if not with_tgt:
                continue
            seen += 1
            for d in with_tgt:
                self.assertNotEqual(d.tgt_zone, "", (hd.id, pid))
                self.assertGreaterEqual(d.tgt_slot, 0)
        self.assertGreaterEqual(seen, 15, f"only {seen} targeted powers seen")


class TestEnvStatsAndObsExtra(unittest.TestCase):
    def test_env_stats_instrumentation(self):
        policy = HeuristicPolicy()
        env = BattlegroundsEnv(seed=13)
        obs = env.reset(seed=13)
        while True:
            if obs.phase == "choice":
                action = CandidateAction(
                    kind="choose", option=policy.choose_option_index(obs))
            else:
                desc = policy.choose(env.game, env.agent_hero)
                action = CandidateAction(kind="end_turn") if desc is None \
                    else desc.to_candidate()
            obs, _r, term, trunc, _i = env.step(action)
            if term or trunc:
                break
        stats = env.stats
        self.assertGreater(stats["candidates_generated"], 0)
        self.assertGreaterEqual(stats["candidates_trimmed"], 0)
        self.assertLessEqual(stats["max_candidates"], CANDIDATE_MAX)
        self.assertGreater(stats["choice_steps"], 0)
        self.assertEqual(stats["invalid"], 0)
        self.assertEqual(stats["engine_errors"], 0)
        env.close()

    def test_obs_extra_contract(self):
        """v2: obs.extra 存在、与 info["obs_extra"] 同源、纯数据。"""
        env = BattlegroundsEnv(seed=17)
        obs = env.reset(seed=17)
        self.assertIn("obs_extra", env._make_info())
        freeze = [d for d in env._step_actions.descriptors
                  if d.kind == ActionKind.FREEZE.value]
        if freeze:
            obs, _r, _t, _tr, info = env.step(freeze[0].to_candidate())
            self.assertTrue(obs.extra["frozen_tavern"])
            self.assertTrue(info["obs_extra"]["frozen_tavern"])
        env.close()

    def test_obs_extra_quest_progress_after_choice(self):
        """任务/饰品选择后，obs.extra 能读到进度与奖励。"""
        policy = HeuristicPolicy()
        env = BattlegroundsEnv(seed=19)
        obs = env.reset(seed=19)
        reached = False
        for _ in range(400):
            if obs.phase == "choice":
                if obs.pending_choice.kind == "quest_offer":
                    obs, _r, term, trunc, info = env.step(
                        CandidateAction(kind="choose", option=0))
                    extra = obs.extra
                    self.assertIsNotNone(extra.get("quest"))
                    self.assertIn("quest_progress", extra)
                    self.assertIsInstance(extra["quest_progress"], int)
                    self.assertEqual(extra["quest"]["progress"],
                                     extra["quest_progress"])
                    reached = True
                    break
                obs, _r, term, trunc, info = env.step(
                    CandidateAction(kind="choose", option=0))
                continue
            desc = policy.choose(env.game, env.agent_hero)
            action = CandidateAction(kind="end_turn") if desc is None \
                else desc.to_candidate()
            obs, _r, term, trunc, info = env.step(action)
            if term or trunc:
                break
        if reached:
            self.assertTrue(obs.extra["quest"]["card_id"])
        env.close()


#: 观测 v2 `extra` 契约键（与 scripts/audit_env_coverage.py 一致）
EXTRA_REQUIRED_KEYS = (
    "version", "turn", "frozen_tavern", "free_refresh_left", "refresh_cost",
    "gold_spent_this_turn", "cards_played_this_turn",
    "powers", "power_uses_left", "second_power_id",
    "dark_gift", "dark_gift_uses_left",
    "quest", "quest_progress", "quest_target", "quest_reward_ids",
    "trinkets", "trinket_ids", "board_states", "hand_states",
    "minion_flags", "pending_hand_queue", "pending_hand_card_ids",
    "next_opponent", "last_opponent", "next_opponent_info",
    "last_opponent_info", "elimination", "elimination_order",
    "last_combat", "deaths_by_card_id",
)

_PLAIN_TYPES = (bool, int, float, str, type(None))


def _assert_plain_data(testcase, value, path=""):
    """递归断言 extra 只含纯数据（可 pickle、无引擎对象）。"""
    if isinstance(value, _PLAIN_TYPES):
        return
    if isinstance(value, dict):
        for k, v in value.items():
            testcase.assertIsInstance(k, (str, int), path)
            _assert_plain_data(testcase, v, f"{path}.{k}")
        return
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _assert_plain_data(testcase, v, f"{path}[{i}]")
        return
    testcase.fail(f"non-plain extra value at {path}: {type(value)}")


class TestObservationV2Extra(unittest.TestCase):
    """Lead 契约 v2：Observation.extra 接线完整性。"""

    def _new_env(self, seed: int = 23):
        env = BattlegroundsEnv(seed=seed)
        obs = env.reset(seed=seed)
        return env, obs

    @staticmethod
    def _end_turn(obs):
        for i, cand in enumerate(obs.candidates):
            if cand.kind == ActionKind.END_TURN.value:
                return CandidateAction(kind="end_turn")
        raise AssertionError("no end_turn candidate")

    def test_version_and_required_keys(self):
        env, obs = self._new_env()
        self.assertEqual(obs.version, 2)
        default_version = int(
            env_spec.Observation.__dataclass_fields__["version"].default)
        self.assertEqual(obs.version, default_version)
        self.assertEqual(env.observation_space["version"], 2)
        for key in EXTRA_REQUIRED_KEYS:
            self.assertIn(key, obs.extra, f"extra missing key: {key}")
        self.assertEqual(obs.extra["version"], obs.version)
        self.assertEqual(obs.get_extra("turn"), obs.turn)
        self.assertEqual(obs.get_extra("not_a_key", 7), 7)
        self.assertIsInstance(obs.extra["minion_flags"], dict)
        env.close()

    def test_extra_picklable_and_plain_data(self):
        env, obs = self._new_env()
        for _ in range(3):
            obs, _r, _t, _tr, _i = env.step(self._end_turn(obs))
            payload = pickle.dumps(obs)
            self.assertIsInstance(payload, (bytes, bytearray))
            restored = pickle.loads(payload)
            self.assertEqual(restored.extra, obs.extra)
            self.assertEqual(restored.version, 2)
            _assert_plain_data(self, obs.extra, "extra")
        env.close()

    def test_obs_extra_same_source_as_info(self):
        env, obs = self._new_env()
        obs, _r, _t, _tr, info = env.step(self._end_turn(obs))
        self.assertEqual(info["obs_extra"], obs.extra)
        self.assertIs(info["obs_extra"], obs.extra)   # 同源（不重复构建）
        # 每次观测的 extra 是独立拷贝：改一个不影响另一个
        freeze = [d for d in env._step_actions.descriptors
                  if d.kind == ActionKind.FREEZE.value]
        if freeze:
            obs2, *_ = env.step(freeze[0].to_candidate())
            before = obs.extra["frozen_tavern"]
            obs2.extra["frozen_tavern"] = "mutated"
            self.assertEqual(obs.extra["frozen_tavern"], before)
        env.close()

    def test_repeated_build_no_side_effects(self):
        env, obs = self._new_env()
        game = env.game
        agent = env.agent_hero
        fp = (int(agent.gold), int(agent.health), int(agent.armor),
              bool(agent.frozen_tavern), len(agent.hand), len(agent.board),
              len(agent.tavern))
        z = driver.collect_zones(game, agent)
        cands = obs.candidates
        a = observation.build_observation(game, agent, cands, zones=z)
        b = observation.build_observation(game, agent, cands, zones=z)
        fp2 = (int(agent.gold), int(agent.health), int(agent.armor),
               bool(agent.frozen_tavern), len(agent.hand), len(agent.board),
               len(agent.tavern))
        self.assertEqual(fp, fp2)
        self.assertEqual(a.extra, b.extra)
        self.assertIsNot(a.extra, b.extra)
        # 传入 extra 时也会深拷贝，不共享可变引用
        c = observation.build_observation(game, agent, cands, zones=z,
                                          extra=obs.extra)
        c.extra["frozen_tavern"] = "mutated"
        self.assertNotEqual(obs.extra["frozen_tavern"], "mutated")
        env.close()

    def test_extra_dynamic_fields(self):
        env, obs = self._new_env()
        # 棋盘/手牌状态：直接放一个随从再构建观测
        game = env.game
        agent = env.agent_hero
        m = game.create_minion("BG25_001", controller=agent)
        game.summon(agent, m)
        h = game.create_minion("BG25_001", controller=agent)
        agent.add_to_hand(h)
        obs = env._observe()
        self.assertTrue(obs.extra["board_states"])
        state = obs.extra["board_states"][0]
        for key in ("entity_id", "card_id", "exhausted", "frozen",
                    "activate_used_this_turn", "windfury_attacks",
                    "divine_shield_hits", "venomous_consumed"):
            self.assertIn(key, state)
        self.assertTrue(obs.extra["minion_flags"])
        self.assertEqual(obs.extra["hand_states"][0]["card_id"], "BG25_001")
        # 英雄技能/黑暗赠礼/对手身份字段类型
        self.assertIsInstance(obs.extra["power_uses_left"], dict)
        for pid, uses in obs.extra["power_uses_left"].items():
            self.assertIsInstance(pid, str)
            self.assertGreaterEqual(int(uses), 0)
        self.assertIsInstance(obs.extra["second_power_id"], str)
        self.assertIsInstance(obs.extra["dark_gift_uses_left"], int)
        self.assertGreaterEqual(obs.extra["dark_gift_uses_left"], 0)
        self.assertTrue(obs.extra["next_opponent"] is None
                        or isinstance(obs.extra["next_opponent"], str))
        env.close()

    def test_vec_env_multiprocess_extra(self):
        """VecEnv(spawn) 跨进程返回的 obs.extra 完整且可 pickle。"""
        from hsbg.env import VecEnv
        vec = VecEnv(2, env_kwargs={"num_players": 8,
                                    "opponent": "heuristic"},
                     seed=4242, multiprocess=True)
        try:
            obs_list = vec.reset()
            self.assertEqual(len(obs_list), 2)
            for obs in obs_list:
                self.assertEqual(obs.version, 2)
                for key in EXTRA_REQUIRED_KEYS:
                    self.assertIn(key, obs.extra, f"vec extra missing: {key}")
            actions = []
            for obs in obs_list:
                idx = next(i for i, c in enumerate(obs.candidates)
                           if c.kind == ActionKind.END_TURN.value)
                actions.append(CandidateAction(kind="end_turn"))
            obs_list, rewards, dones, infos = vec.step(actions)
            for obs, info in zip(obs_list, infos):
                self.assertEqual(obs.version, 2)
                self.assertEqual(info.get("obs_extra"), obs.extra)
        finally:
            vec.close()


class TestTerminationContract(unittest.TestCase):
    """step() 终止契约（阻断 bug 回归）：任何分支都必须正确收口。

    旧 bug：自伤类英雄技能在**非 end_turn** 分支把智能体打死 → 返回
    ``(obs, r, False, False)``；随后 candidates 为空，继续 step 只会
    ``invalid=True`` 无限循环（实测 seed=24 第 67 步）。
    """

    @staticmethod
    def _heuristic_action(policy, env, obs):
        if obs.phase == "choice":
            return CandidateAction(
                kind=ActionKind.CHOOSE.value,
                option=policy.choose_option_index(obs))
        desc = policy.choose(env.game, env.agent_hero)
        if desc is None:
            return CandidateAction(kind="end_turn")
        return desc.to_candidate()

    def _run_until_agent_dead(self, env, policy, max_steps: int = 200):
        obs = env.reset(seed=env.config.seed if env.config.seed else 0) \
            if env._obs is None else env._obs
        last = None
        for step in range(1, max_steps + 1):
            action = self._heuristic_action(policy, env, obs)
            obs, reward, term, trunc, info = env.step(action)
            last = (step, action, obs, reward, term, trunc, info)
            if not env.agent_hero.is_alive or term or trunc:
                break
        return last

    def test_self_elimination_terminates_replay_seed24(self):
        """真实复现：seed=24 非 end_turn 英雄技能自伤致死必须 terminated。"""
        policy = HeuristicPolicy()
        env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=24)
        obs = env.reset(seed=24)
        hit = None
        for step in range(1, 200):
            action = self._heuristic_action(policy, env, obs)
            obs, reward, term, trunc, info = env.step(action)
            if not env.agent_hero.is_alive:
                hit = (step, action, obs, reward, term, trunc, info)
                break
            self.assertFalse(term or trunc, "unexpected early terminal")
        self.assertIsNotNone(hit, "seed=24 未复现自伤致死路径")
        step, action, obs, reward, term, trunc, info = hit
        self.assertTrue(term, "自伤致死必须 terminated=True")
        self.assertFalse(trunc)
        self.assertTrue(env._done)
        self.assertEqual(obs.phase, PHASE_GAME_OVER)
        self.assertEqual(tuple(obs.candidates), ())
        self.assertEqual(info["terminated_reason"], "eliminated")
        self.assertGreaterEqual(int(info["rank"]), 1)
        self.assertLessEqual(int(info["rank"]), 8)
        self.assertEqual(int(info["agent_rank"]), int(info["rank"]))
        self.assertIsInstance(info["elimination_order"], list)
        # 之后继续 step 不得再返回 invalid 循环
        steps_before = int(info["episode_steps"])
        for _ in range(3):
            obs2, r2, term2, trunc2, info2 = env.step(action)
            self.assertTrue(term2)
            self.assertFalse(info2.get("invalid"))
            self.assertEqual(int(info2["episode_steps"]), steps_before)
        env.close()

    def test_self_elimination_minimal_hero_power(self):
        """最小构造：1 血用 TB_BaconShop_HP_049（Take 2 damage）自伤致死。"""
        env = BattlegroundsEnv(num_players=8, opponent="heuristic",
                               hero_id="TB_BaconShop_HERO_25", seed=7)
        obs = env.reset(seed=7)
        agent = env.agent_hero
        agent.take_damage(int(agent.health) + int(agent.armor) - 1)
        self.assertEqual(int(agent.health) + int(agent.armor), 1)
        obs = env._observe()
        hp = [c for c in obs.candidates
              if c.kind == ActionKind.HERO_POWER.value]
        self.assertTrue(hp, "英雄技能候选缺失")
        obs, reward, term, trunc, info = env.step(hp[0])
        self.assertFalse(agent.is_alive)
        self.assertTrue(term)
        self.assertFalse(trunc)
        self.assertTrue(env._done)
        self.assertEqual(obs.phase, PHASE_GAME_OVER)
        self.assertEqual(info["terminated_reason"], "eliminated")
        self.assertEqual(int(info["rank"]), int(info["agent_rank"]))
        self.assertEqual(float(reward), float(env.config.reward.placement) * (
            1.0 - 2.0 * (int(info["rank"]) - 1) / 7.0)
            + float(env.config.reward.step_penalty))
        env.close()

    def test_no_invalid_loop_after_game_over(self):
        """兜底契约：obs 已 game_over 而 _done=False 时 step 必须立即收口。"""
        env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=5)
        env.reset(seed=5)
        # 模拟旧 bug 残留状态：观测终局、done 未置位（智能体仍存活）
        env._obs = env._observe(phase=PHASE_GAME_OVER)
        self.assertFalse(env._done)
        self.assertEqual(env._obs.phase, PHASE_GAME_OVER)
        before = int(env._step_count)
        action = CandidateAction(kind="end_turn")
        obs, reward, term, trunc, info = env.step(action)
        self.assertTrue(term)
        self.assertFalse(trunc)
        self.assertFalse(info.get("invalid"))
        self.assertTrue(env._done)
        self.assertEqual(obs.phase, PHASE_GAME_OVER)
        self.assertEqual(int(env._step_count), before)
        self.assertEqual(info["terminated_reason"], "game_over")
        # 再来一次：仍 terminated，不增长
        obs2, r2, term2, trunc2, info2 = env.step(action)
        self.assertTrue(term2)
        self.assertFalse(info2.get("invalid"))
        self.assertEqual(int(env._step_count), before)
        env.close()

    def test_max_steps_truncates_any_branch(self):
        """非 end_turn 动作同样受 max_steps 约束（旧实现只在 end_turn 检查）。"""
        env = BattlegroundsEnv(num_players=8, opponent="heuristic",
                               max_steps=5, seed=9)
        obs = env.reset(seed=9)
        hit = None
        for _ in range(12):
            non_end = [c for c in obs.candidates
                       if c.kind != ActionKind.END_TURN.value]
            self.assertTrue(non_end)
            action = non_end[0].signature()
            obs, reward, term, trunc, info = env.step(action)
            if trunc or term:
                hit = (obs, term, trunc, info)
                break
        self.assertIsNotNone(hit, "max_steps 未在非 end_turn 分支触发截断")
        obs, term, trunc, info = hit
        self.assertTrue(trunc)
        self.assertFalse(term)
        self.assertEqual(info["terminated_reason"], "max_steps")
        self.assertTrue(info["truncated"])
        self.assertTrue(env._done)
        self.assertEqual(obs.phase, PHASE_GAME_OVER)
        self.assertLessEqual(int(info["episode_steps"]), 5)
        obs2, r2, term2, trunc2, info2 = env.step(
            CandidateAction(kind="end_turn"))
        self.assertTrue(term2)
        self.assertTrue(trunc2)
        env.close()

    def test_terminated_info_has_rank_and_reason(self):
        policy = HeuristicPolicy()
        env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=24)
        obs = env.reset(seed=24)
        info = {}
        for _ in range(200):
            action = self._heuristic_action(policy, env, obs)
            obs, reward, term, trunc, info = env.step(action)
            if term or trunc:
                break
        self.assertTrue(term or trunc)
        for key in ("rank", "agent_rank", "terminated_reason", "truncated",
                    "episode_steps", "alive_count", "health", "armor"):
            self.assertIn(key, info)
        self.assertGreaterEqual(int(info["rank"]), 1)
        self.assertLessEqual(int(info["rank"]), 8)
        self.assertIsInstance(info["terminated_reason"], str)
        self.assertTrue(info["terminated_reason"])
        self.assertIsInstance(info["truncated"], bool)
        self.assertEqual(info["obs_extra"], obs.extra)
        env.close()


class TestCoverageGate(unittest.TestCase):
    """N 局覆盖率门禁（与 scripts/audit_env_coverage.py 同口径）。

    历史教训：本测试曾只靠"4 局随机对局"断言 11 种动作都出现；引擎新增卡
    脚本改变 RNG 流后，某些低频类（activate / use_dark_gift / upgrade /
    定向变体）可能整段采样不到 → 全量红、单跑绿。因此**结构类覆盖改为
    确定性构造**（`_synthetic_kinds/_synthetic_target_variants`），随机对局
    只负责"0 invalid / 0 engine_rejected / 槽位一致 / 手牌组不被裁"。
    """

    @staticmethod
    def _synthetic_magnetic_variants() -> int:
        """确定性的磁力吸附候选（Prosthetic Hand → Undead 宿主）。"""
        game = make_game(seed=51)
        a = game.heroes[0]
        host = put(game, a, "BG25_001")             # Undead 宿主
        m = hand_card(game, a, "BG_DEEP_015")       # Prosthetic Hand
        return sum(1 for d in driver.enumerate_actions(game, a)
                   if d.kind == ActionKind.PLAY_MINION.value
                   and d.src_entity is m and d.tgt_entity is host
                   and getattr(d, "magnetic", False))

    @staticmethod
    def _synthetic_kinds() -> set:
        """确定性构造 11 类动作（不依赖随机对局采样）。"""
        import hsrl2.constants as C
        kinds = set()
        game = make_game(seed=71)
        game.start_game()
        driver.resolve_pending_choices(game, None)
        a = game.heroes[0]
        a.gold = 200
        put(game, a, "BG25_001")                    # sell
        hand_card(game, a, "BG25_001")              # play_minion
        pool_spell = next(d.id for d in get_db().pool_spells())
        hand_spell(game, a, pool_spell)             # play_spell
        act = Minion("TEST_ACT", "Act", atk=1, health=1)
        act.game = game
        act.controller = a
        act.set(GameTag.ACTIVATE, True)
        act.set(GameTag.ACTIVATE_COST, 1)
        game.summon(a, act)                         # activate
        game.turn = max(int(game.turn), int(C.DARK_GIFT_START_TURN))
        for d in driver.enumerate_actions(game, a):  # buy/reroll/upgrade/
            kinds.add(d.kind)                        # freeze/dark_gift/end_turn
        # hero_power：用带定向技能的英雄构造（Maiev → 酒馆卡为目标）
        hp_game = make_game(seed=72,
                            hero_ids=("TB_BaconShop_HERO_62", "TEST_B"))
        hp_game.start_game()
        driver.resolve_pending_choices(hp_game, None)
        hp_a = hp_game.heroes[0]
        hp_a.gold = 100
        hp_game.refresh_tavern(hp_a)
        for d in driver.enumerate_actions(hp_game, hp_a):
            kinds.add(d.kind)
        return kinds

    @classmethod
    def _synthetic_target_variants(cls) -> dict:
        """确定性构造 4 类目标变体（不依赖随机对局采样）。"""
        out = {"play_spell": 0, "play_minion": 0, "hero_power": 0,
               "magnetic": cls._synthetic_magnetic_variants()}
        game = make_game(seed=73)
        game.start_game()
        driver.resolve_pending_choices(game, None)
        a = game.heroes[0]
        a.gold = 100
        put(game, a, "BG25_001")                    # Undead 目标
        spell = hand_spell(game, a, "BG28_518")     # Chef's Choice（任意随从）
        maw = hand_card(game, a, "BG32_340")        # Maw Caster（Undead 目标）
        for d in driver.enumerate_actions(game, a):
            if d.kind == ActionKind.PLAY_SPELL.value \
                    and d.src_entity is spell and d.tgt_entity is not None:
                out["play_spell"] += 1
            if d.kind == ActionKind.PLAY_MINION.value \
                    and d.src_entity is maw and d.tgt_entity is not None:
                out["play_minion"] += 1
        hp_game = make_game(seed=74,
                            hero_ids=("TB_BaconShop_HERO_62", "TEST_B"))
        hp_game.start_game()
        driver.resolve_pending_choices(hp_game, None)
        hp_a = hp_game.heroes[0]
        hp_a.gold = 100
        hp_game.refresh_tavern(hp_a)
        out["hero_power"] = sum(
            1 for d in driver.enumerate_actions(hp_game, hp_a)
            if d.kind == ActionKind.HERO_POWER.value
            and d.tgt_entity is not None)
        return out

    def test_minimum_coverage_and_zero_errors(self):
        policy = HeuristicPolicy()
        kinds = set()
        target_variants = self._synthetic_target_variants()
        invalid = rejected = 0
        slot_bad = 0
        dropped = 0
        for seed in range(4):
            env = BattlegroundsEnv(seed=seed)
            obs = env.reset(seed=seed)
            while True:
                for cand in obs.candidates:
                    kinds.add(cand.kind)
                    if cand.kind == "play_spell" and cand.tgt_zone:
                        target_variants["play_spell"] += 1
                    if cand.kind == "play_minion" and cand.tgt_zone:
                        target_variants["play_minion"] += 1
                    if cand.kind == "hero_power" and cand.tgt_zone:
                        target_variants["hero_power"] += 1
                sa = env._step_actions
                for d, cand in zip(sa.descriptors, sa.candidates):
                    if getattr(d, "magnetic", False) and cand.tgt_zone:
                        target_variants["magnetic"] += 1
                    for ent, zone, slot in (
                            (d.src_entity, cand.src_zone, cand.src_slot),
                            (d.tgt_entity, cand.tgt_zone, cand.tgt_slot)):
                        if ent is None:
                            continue
                        loc = sa.zones.locate(ent)
                        if loc is not None and (zone, slot) != loc:
                            slot_bad += 1
                if obs.phase == "choice":
                    action = CandidateAction(
                        kind="choose",
                        option=policy.choose_option_index(obs))
                else:
                    desc = policy.choose(env.game, env.agent_hero)
                    action = CandidateAction(kind="end_turn") \
                        if desc is None else desc.to_candidate()
                obs, _r, term, trunc, info = env.step(action)
                if info.get("invalid"):
                    invalid += 1
                    if info.get("action_error_type") == "Rejected":
                        rejected += 1
                if term or trunc:
                    break
            dropped += env.stats["plays_dropped"]
            env.close()
        kinds |= self._synthetic_kinds()
        for kind in ("buy", "sell", "play_minion", "play_spell", "reroll",
                     "upgrade", "freeze", "hero_power", "activate",
                     "use_dark_gift", "end_turn"):
            self.assertIn(kind, kinds, f"kind never offered (含构造态): {kind}")
        for key, count in target_variants.items():
            self.assertGreater(count, 0, f"no target variants: {key}")
        self.assertEqual(invalid, 0)
        self.assertEqual(rejected, 0)
        self.assertEqual(slot_bad, 0)
        self.assertEqual(dropped, 0)


class TestBuyAffordability(unittest.TestCase):
    """购买报价/支付方式必须与引擎一致（强制生命购买：金币再多也不够）。"""

    HEALTH_SPELL = "BG28_571"   # Hasty Excavation: costs Health to buy

    def _game_with_tavern_card(self):
        game = make_game(seed=61)
        game.start_game()
        driver.resolve_pending_choices(game, None)
        a, b = game.heroes
        a.gold = 20
        ent = game.create_spell(self.HEALTH_SPELL, controller=a)
        game.add_tavern_entity(a, ent)
        return game, a, ent

    def _buy_candidates(self, game, a, ent):
        return [d for d in driver.enumerate_actions(game, a)
                if d.kind == ActionKind.BUY.value and d.src_entity is ent]

    def test_forced_health_buy_requires_health_not_gold(self):
        game, a, ent = self._game_with_tavern_card()
        a.gold = 0
        self.assertGreater(a.health + a.armor, 3)
        descs = self._buy_candidates(game, a, ent)
        self.assertTrue(descs, "health-paid buy should be enumerated")
        res = driver.apply_action(game, a, descs[0])
        self.assertTrue(res.success, res.error)

    def test_forced_health_buy_not_enumerated_without_health(self):
        game, a, ent = self._game_with_tavern_card()
        a.gold = 20
        a.take_damage(max(0, a.health + a.armor - 2))
        self.assertEqual(a.health + a.armor, 2)
        self.assertEqual(self._buy_candidates(game, a, ent), [],
                         "must not offer buy the engine will reject")
        # 引擎证据：金币充足也会拒绝
        self.assertFalse(game.buy_from_tavern(a, ent))


class TestPoolCardOperability(unittest.TestCase):
    """池内全部可打出卡都能生成合法候选（"无候选卡"零容忍门禁）。

    这是 ``scripts/audit_env_coverage.py`` 的 ``pool_*_no_candidate_BUG``
    门禁的测试版：每张池内随从（手牌可打出 / 酒馆可购买）与池内法术
    （手牌可施放）都必须至少生成 1 个候选且 apply 成功。
    """

    def test_all_pool_minions_operable(self):
        from scripts.audit_env_coverage import _synthetic_operable
        bad = []
        for d in get_db().pool_minions():
            ok = _synthetic_operable(d.id)
            if ok is False:
                bad.append(d.id)
        self.assertEqual(bad, [], f"pool minions with no candidate: {bad}")

    def test_all_pool_spells_operable(self):
        from scripts.audit_env_coverage import _synthetic_operable
        bad = []
        for d in get_db().pool_spells():
            ok = _synthetic_operable(d.id)
            if ok is False:
                bad.append(d.id)
        self.assertEqual(bad, [], f"pool spells with no candidate: {bad}")


class TestPlayerCounts(unittest.TestCase):
    def test_two_four_eight_players(self):
        for players in (2, 4, 8):
            env = BattlegroundsEnv(num_players=players, seed=101)
            obs = env.reset(seed=101)
            self.assertEqual(len(obs.lobby), players)
            self.assertEqual(obs.total_players, players)
            self.assertGreaterEqual(obs.rank, 1)
            self.assertLessEqual(obs.rank, players)
            self.assertIn("obs_extra", env._make_info())
            # 走一步 end_turn 验证整局循环可推进
            end = next((i for i, c in enumerate(obs.candidates)
                        if c.kind == "end_turn"), None)
            if end is not None:
                obs, _r, term, trunc, _i = env.step(end)
                self.assertIsNotNone(obs)
            env.close()


if __name__ == "__main__":                              # pragma: no cover
    unittest.main()
