"""``tests/test_env_dark_gift_obs.py`` —— v3 Dark Gift 选项语义进观测。

背景：Dark Gift 的 PendingChoice options 是 ``(minion_id, gift_id)`` 二元组；
``EntityToken`` 只保留主 id，旧实现把 gift_id 拼进调试字段 ``name``（策略不得
依赖）。v3 兼容方案：选择步 ``obs.extra["pending_choice_options"]`` 给出与
``CandidateAction(kind="choose", option=i)`` 一一对应的结构化元数据
（``card_id / secondary_id / label / cost``）。

覆盖：
- 真实引擎路径（``driver.apply_action(USE_DARK_GIFT)``）产生的 dark_gift 选择：
  gift_id 出现在 ``extra``（而非只有 name），且与引擎 options 完全一致；
- ``choose`` 结算后确实授予带 DARK_GIFT tag 的随从；
- extra 为纯数据、可 pickle、与 ``info["obs_extra"]`` 同源；
- 其它二元组/一维选项（quest_offer、trinket 跳过项 None、choose_one key）
  的元数据结构正确；
- 引擎提供 ``labels`` 属性时 label 自动透传（前向兼容）。
"""

from __future__ import annotations

import pickle

import hsrl2.constants as C
from hsrl2.game import PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import GameTag

from tests.test_env_support import make_engine_game

from hsbg.env import BattlegroundsEnv, driver, observation
from hsbg.env.spec import ActionKind, CandidateAction

GIFT_ACTION = ActionKind.USE_DARK_GIFT.value


# ══════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════


def _open_engine_dark_gift(seed: int = 101):
    """engine 层：第 3 回合 + 3 金，使用一次 Dark Gift 并返回待决选择。"""
    game, heroes = make_engine_game(seed=seed)
    hero = heroes[0]
    game.turn = max(int(game.turn), int(C.DARK_GIFT_START_TURN))
    hero.gold = max(int(hero.gold), int(C.DARK_GIFT_COST) + 5)
    desc = next((d for d in driver.enumerate_actions(game, hero)
                 if d.kind == GIFT_ACTION), None)
    assert desc is not None, "Dark Gift 门槛满足时应生成 use_dark_gift 候选"
    res = driver.apply_action(game, hero, desc)
    assert res.success, res.error
    assert game.pending_choices, "use_dark_gift 应产生 dark_gift 待决选择"
    choice = game.pending_choices[0]
    assert choice.kind == "dark_gift"
    return game, hero, choice


def _obs_for_choice(game, hero, choice):
    zones = driver.collect_zones(game, hero)
    descs = driver.enumerate_choice(game, choice, zones)
    cands = tuple(d.to_candidate() for d in descs)
    return observation.build_observation(
        game, hero, cands, phase="choice", pending=choice, zones=zones)


# ══════════════════════════════════════════════════════════════════════
# 核心：gift_id 进入观测
# ══════════════════════════════════════════════════════════════════════


def test_gift_id_exposed_in_extra_and_matches_engine_options():
    game, hero, choice = _open_engine_dark_gift()
    raw = list(choice.options)
    assert raw and all(isinstance(o, tuple) and len(o) == 2 for o in raw)

    obs = _obs_for_choice(game, hero, choice)
    assert obs.version == 3
    meta = obs.extra["pending_choice_options"]
    assert len(meta) == len(raw)
    for i, (card_id, gift_id) in enumerate(raw):
        assert meta[i]["index"] == i
        assert meta[i]["card_id"] == str(card_id)
        assert meta[i]["secondary_id"] == str(gift_id)
        # 旧实现的 EntityToken 只保留主 id（回归保护：不再只有 name 可用）
        assert obs.pending_choice.options[i].card_id == str(card_id)
        assert "label" in meta[i] and "cost" in meta[i]
    # 同一批 options 的 gift 互不相同（引擎 _pair_gifts 契约）
    gifts = [m["secondary_id"] for m in meta]
    assert len(gifts) == len(set(gifts))
    # choose 候选 option 下标与 extra 下标严格对齐
    assert [c.option for c in obs.candidates] == list(range(len(raw)))
    for cand in obs.candidates:
        assert cand.kind == "choose"
        assert meta[cand.option]["secondary_id"] == str(raw[cand.option][1])


def test_dark_gift_extra_is_plain_picklable_and_same_source_as_info():
    game, hero, choice = _open_engine_dark_gift(seed=102)
    obs = _obs_for_choice(game, hero, choice)
    # 纯数据 + pickle 往返
    payload = pickle.dumps(obs)
    restored = pickle.loads(payload)
    assert restored.extra == obs.extra
    restored_meta = restored.extra["pending_choice_options"]
    assert [m["secondary_id"] for m in restored_meta] == \
           [m["secondary_id"] for m in obs.extra["pending_choice_options"]]
    # 不得含引擎对象（遍历类型面）
    _assert_plain(obs.extra["pending_choice_options"])


def _assert_plain(value) -> None:
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, dict):
        for k, v in value.items():
            assert isinstance(k, (str, int, float, bool)), type(k)
            _assert_plain(v)
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _assert_plain(v)
        return
    raise AssertionError(f"extra 含非纯数据类型: {type(value)!r}")


# ══════════════════════════════════════════════════════════════════════
# env 全链路：step(use_dark_gift) → choice 观测 → choose → 附魔生效
# ══════════════════════════════════════════════════════════════════════


def test_env_dark_gift_choice_step_and_gift_applied():
    env = BattlegroundsEnv(seed=103)
    obs = env.reset(seed=103)
    driver.resolve_pending_choices(env.game, None)
    game, hero = env.game, env.agent_hero
    game.turn = max(int(game.turn), int(C.DARK_GIFT_START_TURN))
    hero.gold = int(C.DARK_GIFT_COST) + 7
    gold_before = int(hero.gold)

    obs = env._observe()                       # 重新枚举（门槛已满足）
    gift_cands = [c for c in obs.candidates if c.kind == GIFT_ACTION]
    assert len(gift_cands) == 1, [c.kind for c in obs.candidates]

    obs2, _r, term, trunc, info = env.step(gift_cands[0])
    assert not term and not trunc
    assert info["invalid"] is False, info
    assert obs2.phase == "choice"
    assert obs2.pending_choice is not None
    assert obs2.pending_choice.kind == "dark_gift"
    meta = obs2.extra["pending_choice_options"]
    raw = list(game.pending_choices[0].options)
    assert [m["secondary_id"] for m in meta] == [str(o[1]) for o in raw]
    # 观测与 info 同源
    info = env._make_info()
    assert info["obs_extra"]["pending_choice_options"] == meta
    assert int(hero.gold) == gold_before - int(C.DARK_GIFT_COST)

    # 选择一个（option 0）→ 入手带对应 DARK_GIFT tag 的随从
    gift_id = meta[0]["secondary_id"]
    obs3, _r, term, trunc, info = env.step(
        CandidateAction(kind="choose", option=0))
    assert not term and not trunc
    assert info["invalid"] is False, info
    minions = [e for e in hero.hand if isinstance(e, Minion)]
    assert minions, "Dark Gift 选择后应有随从入手"
    got = [m for m in minions if str(m.get(GameTag.DARK_GIFT, "")) == gift_id]
    assert got, f"未找到带 DARK_GIFT={gift_id} 的随从: " \
                f"{[(m.card_id, m.get(GameTag.DARK_GIFT, None)) for m in minions]}"
    env.close()


# ══════════════════════════════════════════════════════════════════════
# 其它选项类型 / 前向兼容
# ══════════════════════════════════════════════════════════════════════


def test_quest_offer_pair_and_pass_option_meta():
    game, heroes = make_engine_game(seed=104)
    hero = heroes[0]
    choice = PendingChoice(
        hero, [("QUEST_X", "REWARD_Y"), None], "quest_offer",
        resolve_callback=lambda pick: None)
    game.pending_choices.append(choice)
    obs = _obs_for_choice(game, hero, choice)
    meta = obs.extra["pending_choice_options"]
    assert meta[0]["card_id"] == "QUEST_X"
    assert meta[0]["secondary_id"] == "REWARD_Y"
    assert meta[1]["card_id"] == ""
    assert meta[1]["secondary_id"] is None


def test_choose_one_key_options_have_no_secondary():
    game, heroes = make_engine_game(seed=105)
    hero = heroes[0]
    choice = PendingChoice(hero, ["reborn", "windfury"], "choose_one",
                           resolve_callback=lambda key: None)
    game.pending_choices.append(choice)
    obs = _obs_for_choice(game, hero, choice)
    meta = obs.extra["pending_choice_options"]
    assert [m["card_id"] for m in meta] == ["reborn", "windfury"]
    assert all(m["secondary_id"] is None for m in meta)


def test_engine_labels_are_forwarded_when_available():
    """若引擎未来给 PendingChoice 加 labels，extra.label 自动透传。"""
    game, heroes = make_engine_game(seed=106)
    hero = heroes[0]
    choice = PendingChoice(hero, ["k1", "k2"], "choose_one",
                           resolve_callback=lambda key: None)
    choice.labels = ["分支一", "分支二"]           # 前向兼容属性
    game.pending_choices.append(choice)
    obs = _obs_for_choice(game, hero, choice)
    meta = obs.extra["pending_choice_options"]
    assert [m["label"] for m in meta] == ["分支一", "分支二"]


def test_trinket_offer_option_cost_in_meta():
    game, heroes = make_engine_game(seed=107)
    hero = heroes[0]
    trinket_def = next(iter(game.db.trinket_offer_pool()))
    choice = PendingChoice(hero, [trinket_def, None], "trinket_offer",
                           resolve_callback=lambda pick: None)
    game.pending_choices.append(choice)
    obs = _obs_for_choice(game, hero, choice)
    meta = obs.extra["pending_choice_options"]
    assert meta[0]["card_id"] == str(trinket_def.id)
    assert meta[0]["cost"] == int(getattr(trinket_def, "cost", 0) or 0)
    assert meta[1]["card_id"] == "" and meta[1]["cost"] == -1
