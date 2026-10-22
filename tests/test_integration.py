"""端到端集成测试：环境 ↔ RL 接口契约（Lead 验收层）。

覆盖：
* 单局闭环 + info 契约 + 名次范围
* 同 seed 确定性（观测/动作序列逐位一致）
* 2/4/8 人多人数
* PendingChoice 选择步契约
* 非法动作防护（状态不推进）
* 纯 placement 奖励 = 名次映射公式
* VecEnv（Sync）自动 reset / dones / infos
* Gymnasium 包装（若安装）
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path
from typing import List, Tuple

from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env import BattlegroundsEnv
from hsbg.env.spec import (ActionKind, CandidateAction, RewardConfig)

INFO_KEYS = ("turn", "rank", "health", "armor",
             "alive_count", "combat", "invalid", "terminated_reason",
             "seed", "episode_steps")


def _obs_sig(obs) -> Tuple:
    hero = obs.hero
    return (
        obs.turn, obs.phase, obs.alive_count, obs.rank,
        None if hero is None else (hero.hero_id, hero.health, hero.armor,
                                   hero.tier, hero.gold, hero.upgrade_cost),
        tuple((t.card_id, t.atk, t.health) for t in obs.board),
        tuple(t.card_id for t in obs.hand),
        tuple(t.card_id for t in obs.tavern),
        tuple(c.signature() for c in obs.candidates),
    )


def _play(env, seed: int, record: bool = False):
    """用启发式跑一局，返回 (steps, rank, total_reward, sig, truncated, info)。"""
    policy = HeuristicPolicy()
    obs = env.reset(seed=seed)
    sig: List[Tuple] = []
    total = 0.0
    steps = 0
    info = {}
    truncated = False
    while True:
        steps += 1
        if not obs.candidates:
            break
        if record:
            sig.append(_obs_sig(obs))
        if obs.phase == "choice":
            action = CandidateAction(kind=ActionKind.CHOOSE.value,
                                     option=policy.choose_option_index(obs))
        else:
            desc = policy.choose(env.game, env.agent_hero)
            action = (CandidateAction(kind=ActionKind.END_TURN.value)
                      if desc is None else desc.to_candidate())
        obs, reward, terminated, truncated, info = env.step(action)
        total += reward
        if terminated or truncated:
            break
    return steps, int(info.get("rank", 0)), total, sig, truncated, info


class TestEnvIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = BattlegroundsEnv(num_players=8, opponent="heuristic",
                                   seed=1000)

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def test_episode_completes_with_info_contract(self):
        for seed in (2001, 2002):
            env = BattlegroundsEnv(num_players=8, opponent="heuristic",
                                   seed=seed)
            steps, rank, total, _sig, truncated, info = _play(env, seed)
            env.close()
            for k in INFO_KEYS:
                self.assertIn(k, info)
            self.assertGreater(steps, 0)
            self.assertFalse(truncated)
            self.assertTrue(1 <= rank <= 8, f"rank={rank}")
            self.assertTrue(math.isfinite(total))

    def test_determinism_same_seed(self):
        a = _play(BattlegroundsEnv(num_players=8, seed=3033), 3033,
                  record=True)
        b = _play(BattlegroundsEnv(num_players=8, seed=3033), 3033,
                  record=True)
        self.assertEqual(a[0], b[0])          # steps
        self.assertEqual(a[1], b[1])          # rank
        self.assertEqual(a[3], b[3])          # 观测/候选签名序列
        self.assertAlmostEqual(a[2], b[2])    # total reward

    def test_multi_player_counts(self):
        for players in (2, 4, 8):
            env = BattlegroundsEnv(num_players=players, seed=4000 + players)
            steps, rank, _t, _s, truncated, info = _play(env, 4000 + players)
            env.close()
            self.assertFalse(truncated)
            self.assertTrue(1 <= rank <= players)
            self.assertLessEqual(int(info["alive_count"]), players)

    def test_choice_phase_contract(self):
        """有选择步时：phase=choice，候选全是 choose 且能推进。"""
        env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=5)
        policy = HeuristicPolicy()
        obs = env.reset(seed=5)
        seen_choice = 0
        for _ in range(600):
            if not obs.candidates:
                break
            if obs.phase == "choice":
                seen_choice += 1
                self.assertIsNotNone(obs.pending_choice)
                for c in obs.candidates:
                    self.assertEqual(c.kind, ActionKind.CHOOSE.value)
                action = CandidateAction(
                    kind=ActionKind.CHOOSE.value,
                    option=policy.choose_option_index(obs))
            else:
                desc = policy.choose(env.game, env.agent_hero)
                action = (CandidateAction(kind=ActionKind.END_TURN.value)
                          if desc is None else desc.to_candidate())
            before = obs.turn
            obs, _r, term, trunc, info = env.step(action)
            if term or trunc:
                break
            self.assertTrue(obs.turn >= before)
        env.close()
        self.assertGreater(seen_choice, 0, "本 seed 未出现选择步，调整 seed")

    def test_invalid_action_does_not_advance(self):
        env = BattlegroundsEnv(num_players=8, seed=77)
        obs = env.reset(seed=77)
        n_before = len(obs.candidates)
        fake = CandidateAction(kind="play_spell", src_zone="hand",
                               src_slot=0, tgt_zone="board", tgt_slot=0)
        obs2, reward, term, trunc, info = env.step(fake)
        self.assertTrue(info.get("invalid"))
        self.assertFalse(term or trunc)
        self.assertEqual(len(obs2.candidates), n_before)
        env.close()

    def test_placement_only_reward_matches_formula(self):
        cfg = RewardConfig(placement=1.0, health_delta=0.0,
                           combat_damage=0.0, board_power_delta=0.0,
                           survival=0.0, timeout=0.0, step_penalty=0.0)
        env = BattlegroundsEnv(num_players=8, seed=91, reward=cfg)
        steps, rank, total, _sig, truncated, _info = _play(env, 91)
        env.close()
        self.assertFalse(truncated)
        expected = 1.0 - 2.0 * (rank - 1) / 7.0
        self.assertAlmostEqual(total, expected, places=6,
                               msg=f"rank={rank} total={total} expected={expected}")


class TestVecEnvContract(unittest.TestCase):
    def test_sync_vec_env_auto_reset_and_infos(self):
        from hsbg.env.vec_env import SyncVecEnv
        import random
        rng = random.Random(0)
        vec = SyncVecEnv(num_envs=2, env_kwargs={"num_players": 4}, seed=600)
        obs_list = vec.reset()
        self.assertEqual(len(obs_list), 2)
        ended = 0
        for _ in range(400):
            actions = []
            for obs in obs_list:
                idx = rng.randrange(len(obs.candidates))
                actions.append(obs.candidates[idx])
            obs_list, rewards, dones, infos = vec.step(actions)
            self.assertEqual(len(obs_list), 2)
            self.assertEqual(len(rewards), 2)
            self.assertEqual(len(dones), 2)
            self.assertEqual(len(infos), 2)
            for done, info in zip(dones, infos):
                if done:
                    ended += 1
                    self.assertIn("terminal_observation", info)
            if ended >= 2:
                break
        vec.close()
        self.assertGreaterEqual(ended, 1)


class TestGymWrapperIfAvailable(unittest.TestCase):
    def test_gym_wrapper(self):
        try:
            import gymnasium  # noqa: F401
            from hsbg.rl.gym_wrapper import GymBattlegroundsEnv  # noqa: F401
        except ImportError:
            self.skipTest("gymnasium / hsbg.rl 未就绪")
        env = GymBattlegroundsEnv(num_players=4, seed=700)
        obs, info = env.reset(seed=700)
        self.assertIsNotNone(obs)
        mask = env.action_masks()
        self.assertEqual(len(mask), env.action_space.n)
        env.step(int(mask.index(True)) if hasattr(mask, "index")
                 else max(range(len(mask)), key=lambda i: mask[i]))
        env.close()


if __name__ == "__main__":
    unittest.main()
