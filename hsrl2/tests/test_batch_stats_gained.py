"""批次 stats_gained 测试 — "Whenever a [friendly] X gains Attack" 家族
（2026-09-20; 引擎原语 `stats_gained` 落地轮）。

驱动约定（TEST_SOP / 既有批次同款）:
  - 数值期望一律 `CardDef.num(i)` 计算; 字面量处注明
  - 每卡 ≥1 正例 + ≥1 负例; 触发域边界（复制/三连/战后复原不触发）
    单列 `TestTriggerDomain`
  - "真实路径" = 引擎生产入口（`play_minion` / `play_spell` /
    `run_combat` / `run_actions(Buff)` / `copy_buffs_to`），不经测试
    私设通道

变异探针（2026-09-20 实测；运行器 `tools/_mutation_probe_stats_gained.py`，
逐项施加后跑本文件 + `test_batch_trinkets32.py`）:
  1. `add_buff` 不广播 `stats_gained` → **24 项转红**
  2. `copy_buffs_to`/三连去掉抑制窗口 → **2 项转红**
     （`test_copy_buffs_to_does_not_trigger` /
      `test_triple_combine_does_not_trigger`）
  3. 载荷 `atk` 传常量 `1` 而非 `buff.atk` → **27 项转红**
     （含 Stormbringer 数值拷贝 + 全部"仅生命不触发"负例）
  4. 删 `BG21_013` 的 Dragon 类型过滤 → **1 项转红**
     （`test_non_dragon_gain_does_not_trigger`）
  5. 战后复原不抑制（`_restore_no_gain` 恒 False）→ **转红**:
     `TestTriggerDomain::test_combat_incombat_persist_replay_does_not_rebroadcast`
     （2026-09-20 对抗验证纠错——旧记"等价变异存活"**不成立**: 真路径
     `Bewitched Ribbon BG35_MagicItem_923` + Tide Raiser `BG34_920`
     亡语战内施法 + `BG34_Giant_064` 监听器 → 抑制时 6 次广播，去抑制
     7 次。原因: 战内授予的 `Buff(persist=True)` **不在战斗起始快照**里，
     `persist_buffs` 身份去重不跳过它 → 战后经 `add_buff` 重放并广播）。
  6. `_friendly` 去掉 `Zone.PLAY` 过滤 → **转红**:
     `TestTriggerDomain::test_tavern_minion_gain_does_not_trigger`
     （酒馆随从加攻不得触发棋盘监听器）。
  7. Hunter of Gatherers 重新排除自身 → **2 项转红**
     （`test_gain_buffs_all_minions_including_self` /
      `test_golden_grants_four`）。
  8. 快照副本重放不抑制（`batch_trinkets32`）→ **转红**:
     `test_batch_trinkets32.py::TestBoomController::
      test_copy_replay_does_not_trigger_stats_gained_listener`。
  9. `ActionQueue.resolve` 去掉逐动作来源复位 → **转红**:
     `TestPrimitiveContract::test_action_source_does_not_leak_between_actions`。
  10. SirensSong 手动复制循环不抑制 → **转红**:
      `TestTriggerDomain::test_sirens_song_copy_does_not_trigger`。
  **有效变异 10/10 全杀**（M1–M10）。

注: `tools/audit_vacuous_tests.py` 的脚本钩子 no-op 注入对本文件的
`TestPrimitiveContract` / `TestTriggerDomain` 存活——那两个类标注
`@engine-only`，驱动的是**引擎原语**而非本批脚本钩子（该工具的白名单
契约），其信息量由上面的引擎级变异探针（M1–M3）证明。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff
from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 42) -> Game:
    heroes = [Hero("TEST_HERO_A", "A"), Hero("TEST_HERO_B", "B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero, golden: bool = False) -> Minion:
    """真实召唤路径（`create_minion` + `Game.summon` → `on_summon` 接线）。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m)
    return m


def spy(game: Game, hero: Hero) -> list:
    """给 `stats_gained` 挂一个纯观察监听（hero 持有，离场安全）。"""
    seen: list = []
    game.events.register(Listener(
        event="stats_gained", owner=hero,
        callback=lambda g, **kw: seen.append(kw)))
    return seen


class TestPrimitiveContract(unittest.TestCase):
    """@engine-only 引擎原语的单元契约：生产点、载荷字段、来源、免疫。

    不经过 `batch_stats_gained` 的脚本钩子（本批脚本类被 no-op 后仍
    成立），见 ENGINE_BACKLOG §E。
    """

    def test_broadcast_on_real_buff_action(self):
        """真实 `Buff` Action → 广播，载荷字段齐全。"""
        game = make_game(100)
        a = game.heroes[0]
        m = put(game, "BG_OG_221", a)
        seen = spy(game, a)
        game.run_actions(Buff(m, atk=2, health=3))
        self.assertEqual(len(seen), 1)
        ev = seen[0]
        self.assertIs(ev["minion"], m)
        self.assertEqual(ev["atk"], 2)
        self.assertEqual(ev["health"], 3)
        self.assertTrue(ev["permanent"])
        self.assertIsNone(ev["source"])          # 来源未声明 → None

    def test_temporary_buff_marks_not_permanent(self):
        """`permanent` = `not buff.temporary`（RULES §3.5 / §E A4）。"""
        game = make_game(101)
        a = game.heroes[0]
        m = put(game, "BG_OG_221", a)
        seen = spy(game, a)
        game.run_actions(Buff(m, atk=1, temporary=True))
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0]["permanent"])

    def test_no_broadcast_when_enchant_immune(self):
        """`ENCHANT_IMMUNE`（Fishbait）拒绝正值增益 → 不入事件（§E A6）。"""
        game = make_game(102)
        a = game.heroes[0]
        m = put(game, "BG_OG_221", a)
        m.set(GameTag.ENCHANT_IMMUNE, True)
        seen = spy(game, a)
        game.run_actions(Buff(m, atk=5))
        self.assertEqual(seen, [])
        self.assertEqual(m.atk, get_db().get("BG_OG_221").atk)

    def test_source_payload_from_action(self):
        """Action 声明 `source=` → 载荷携带该实体（§E D7）。"""
        game = make_game(103)
        a = game.heroes[0]
        m = put(game, "BG_OG_221", a)
        src = put(game, "BG_OG_221", a)
        seen = spy(game, a)
        game.run_actions(Buff(m, atk=1, source=src))
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0]["source"], src)

    def test_action_source_does_not_leak_between_actions(self):
        """`ActionQueue.resolve` **逐动作复位** `_action_source`（§E D7）。

        `[Buff(dummy, source=ship), Buff(ship)]` 的第二个 buff **未声明**
        `source` → 只继承**调用方作用域**（此处 None），**不得**继承
        **上一个动作**的 `ship`（修复前实测第二个事件被错误归属给
        `ship`）。去掉逐迭代复位时本用例转红。
        """
        game = make_game(105)
        a = game.heroes[0]
        dummy = put(game, "BG_OG_221", a)
        ship = put(game, "BG_OG_221", a)
        self.assertIsNone(getattr(game, "_action_source", None))
        seen = spy(game, a)
        game.run_actions([Buff(dummy, atk=1, source=ship), Buff(ship, atk=1)])
        self.assertEqual(len(seen), 2)
        self.assertIs(seen[0]["source"], ship)      # 显式声明 → ship
        self.assertIsNone(seen[1]["source"])        # 不继承上一个动作

    def test_battlecry_path_carries_source_entity(self):
        """真实 `play_minion` 战吼路径: BG35_140 给 Murloc +Attack，
        载荷 `source` = 触发战吼的随从实体（真实生产路径，非私设通道）。"""
        game = make_game(104)
        a = game.heroes[0]
        target = put(game, "BG_OG_221", a)          # 任意类型 → 不入 Murloc
        target.set(GameTag.RACE, Race.MURLOC)
        mama = game.create_minion("BG35_140", controller=a)
        a.hand.append(mama)
        seen = spy(game, a)
        self.assertTrue(game.play_minion(a, mama))
        gains = [e for e in seen if e["minion"] is target]
        self.assertEqual(len(gains), 1)
        # num(0)=3 + Mrrglton 有效计数 1（自身计入——脚本既有裁定）
        self.assertEqual(gains[0]["atk"], 4)
        # 真实钩子路径: `run_script_hook` 把施动实体置为来源
        self.assertIs(gains[0]["source"], mama)


class TestTriggerDomain(unittest.TestCase):
    """@engine-only 触发域边界（§E D1/D2）——内部机械**不得**触发。

    驱动的是引擎原语（`add_buff` / `copy_buffs_to` / `run_combat` /
    `SetStats` / `ApplyRaceAura` / `attach_magnetic`），与本批脚本钩子
    无关（脚本类 no-op 后仍成立）。
    """

    def test_copy_buffs_to_does_not_trigger(self):
        """#4 `copy_buffs_to`（副本）不构成"获得" → 不广播。"""
        game = make_game(200)
        a = game.heroes[0]
        src = put(game, "BG_OG_221", a)
        dst = put(game, "BG_OG_221", a)
        game.run_actions(Buff(src, atk=4, health=4))
        seen = spy(game, a)
        src.copy_buffs_to(dst)
        self.assertEqual(dst.atk, get_db().get("BG_OG_221").atk + 4)
        self.assertEqual(seen, [])

    def test_triple_combine_does_not_trigger(self):
        """#5 三连合成走 #4 `copy_buffs_to` → 不构成"获得" → 不广播。

        （BG21_018 非池卡，`check_for_triple` 对非池卡直接跳过——真实
        三连路径见 `test_engine_primitives` 的池卡；此处直接驱动三连
        实际使用的复制原语 `copy_buffs_to`，与 `_combine` 同源。）"""
        game = make_game(201)
        a = game.heroes[0]
        src = put(game, "BG36_206", a)                  # 池卡（有金色定义）
        golden = game.create_minion("BG36_206", controller=a, golden=True)
        game.run_actions(Buff(src, atk=3, health=3))
        seen = spy(game, a)
        src.copy_buffs_to(golden)
        gd = get_db().golden_version(get_db().get("BG36_206"))
        self.assertEqual(golden.atk, gd.atk + 3)
        self.assertEqual(len(golden.buffs), 1)
        self.assertEqual(seen, [])

    def test_combat_restore_does_not_trigger(self):
        """#6 战斗快照复原重放不构成"获得" → 不广播（Tarecgosa 通道）。

        真实驱动 `run_combat` finally 块里**经 `add_buff` 的复原点**:
        战内授予 `Buff(persist=True)`（"give ... permanently" 家族，
        §3.5 例外 4）→ 战后 `persist_buffs` 通道在 `restore_state` 之后
        **用 `add_buff` 重放**该附魔（`game.py` restore 分支
        `m.add_buff(b)`）。

        断言: 战内授予时广播 1 次（真实获得）; 战后复原重放**不再广播**
        （属性确实保住了 = 重放跑过）。若复原重放未抑制，事件会变 2，
        本用例转红。
        """
        game = make_game(202)
        a, b = game.heroes
        m = put(game, "BG_OG_221", a)
        put(game, "BG_OG_221", b)
        before = (m.atk, m.health)
        seen = spy(game, a)
        # 战内授予永久附魔（真实生产路径: Buff action 带 persist=True）
        game.in_combat = True
        game.run_actions(Buff(m, atk=4, health=4, persist=True,
                              source_id="TEST_PERSIST"))
        game.in_combat = False
        self.assertEqual(len(seen), 1)                   # 战内那次广播
        game.run_combat(a, b, alive_count=2)
        # 例外 4 通道在复原后重放（属性保留 = add_buff 跑过），但不广播
        self.assertEqual(m.atk, before[0] + 4)
        self.assertEqual(m.health, before[1] + 4)
        self.assertEqual(len(seen), 1, "复原重放重复广播了 stats_gained")

    def test_combat_incombat_persist_replay_does_not_rebroadcast(self):
        """#6 **真路径回归（M5 变异敏感）**: 战内 `Buff(persist=True)`
        在战后按来源重放时**不**广播。

        2026-09-20 对抗验证纠错: 旧记"`_restore_no_gain` 复原点不可达 /
        等价变异"**不成立**。真路径 = Bewitched Ribbon
        `BG35_MagicItem_923`（on_bind 监听 `spell_resolving` → 给己方
        存活随从 `Buff(persist=True)`）+ Tide Raiser `BG34_920` 亡语
        **战内**施放 Shifting Tide + `BG34_Giant_064` 监听器。战内授予的
        persist 附魔**不在战斗起始快照**里 → `persist_buffs` 的**对象
        身份去重**（`game.py` restore 分支 `if any(b is x ...)`）不会
        跳过它 → 战后经 `m.add_buff(b)` 重放; 若 `_restore_no_gain`
        抑制缺失，该重放**再广播 1 次** `stats_gained`。

        逐次广播（恰好 6）:
          1. 饰品给存活随从 +2/+2（persist，战内）
          2. 监听器（BG34_Giant_064）对该 +攻随从 +3 生命
          3/4. Shifting Tide "give +1/+1 twice" 两次
          5/6. 监听器对 3/4 各 +3 生命
        战后复原重放广播 = 第 7 次 → 抑制缺失时本用例转红。
        """
        game = make_game(210)
        a, b = game.heroes
        game.start_game()
        self.assertIsNotNone(game.grant_trinket(a, "BG35_MagicItem_923"))
        put(game, "BG34_920", a)          # Tide Raiser: Taunt + 亡语施法
        put(game, "BG34_Giant_064", a)    # stats_gained 监听器
        game.summon(b, Minion("TEST_BIG_M5", "BIG", atk=10, health=200))
        seen = spy(game, a)
        game.run_combat(a, b)
        self.assertEqual(len(seen), 6,
                         "战内 persist 附魔的战后重放重复广播了 stats_gained")
        self.assertEqual(sorted(e["atk"] for e in seen), [0, 0, 0, 1, 1, 2])

    def test_tavern_minion_gain_does_not_trigger(self):
        """`_friendly` 边界: **酒馆/手牌**随从加攻不触发棋盘监听器。

        2026-09-20 对抗验证纠错: 旧 `_friendly` 只查 `controller`，一只
        **酒馆**龙被 `TavernBuff` 加攻即触发棋盘上的 Whelp Smuggler 并
        给酒馆随从加生命（文本 "friendly" = 己方**棋盘**随从）。
        去掉 `_friendly` 的 `Zone.PLAY` 过滤时本用例转红。
        """
        game = make_game(207)
        a = game.heroes[0]
        whelp = put(game, "BG21_013", a)
        base_w = whelp.health
        # 酒馆龙（真实入馆路径 `add_tavern_entity`）+ 真实 Buff
        tavern = game.create_minion("BG_OG_221", controller=a)
        tavern.set(GameTag.RACE, Race.DRAGON)
        self.assertTrue(game.add_tavern_entity(a, tavern))
        self.assertEqual(tavern.zone, Zone.TAVERN)
        game.run_actions(Buff(tavern, atk=3))
        self.assertEqual(tavern.atk, get_db().get("BG_OG_221").atk + 3)
        self.assertEqual(tavern.health, get_db().get("BG_OG_221").health)
        self.assertEqual(whelp.health, base_w)
        # 手牌龙同理（`Zone.HAND`）
        hand = game.create_minion("BG_OG_221", controller=a)
        hand.set(GameTag.RACE, Race.DRAGON)
        a.hand.append(hand)
        hand.zone = Zone.HAND
        game.run_actions(Buff(hand, atk=3))
        self.assertEqual(hand.health, get_db().get("BG_OG_221").health)
        self.assertEqual(whelp.health, base_w)

    def test_sirens_song_copy_does_not_trigger(self):
        """手动复制循环（`batch_misc.SirensSongSpellScript`）不得伪造
        "获得"（§E2 #4 副本路径审计，2026-09-20 对抗验证）。

        真实 `play_spell`（BG27_514t "get a copy of a Tavern minion"）:
        副本逐 buff `add_buff` 置于 `suppress_stats_gained()` 窗口内 →
        副本封装的附魔（+4/+4）**不**广播 `stats_gained`。去掉抑制时
        副本的 (4,4) 事件出现 → 本用例转红。
        """
        game = make_game(208)
        a = game.heroes[0]
        game.start_game()
        put(game, "BG34_Giant_064", a)             # 棋盘 stats_gained 监听器
        tavern = game.create_minion("BG_OG_221", controller=a)
        self.assertTrue(game.add_tavern_entity(a, tavern))
        game.run_actions(Buff(tavern, atk=4, health=4))
        seen = spy(game, a)
        sp = game.create_spell("BG27_514t", controller=a)
        a.hand.append(sp)
        sp.zone = Zone.HAND
        self.assertTrue(game.play_spell(a, sp, target=tavern))
        copies = [m for m in a.hand if m.card_id == "BG_OG_221"]
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertEqual(copy.atk, get_db().get("BG_OG_221").atk + 4)  # 保真
        self.assertEqual([e for e in seen if e["minion"] is copy], [],
                         "副本重放被当成'获得'并触发了 stats_gained")

    def test_aura_and_setstats_and_magnetize_do_not_trigger(self):
        """#7/#8/#11 磁力相加 / `SetStats` 覆盖 / 计算式光环 → 不经
        `add_buff`，天然不广播。"""
        game = make_game(203)
        a = game.heroes[0]
        target = put(game, "BG_OG_221", a)
        seen = spy(game, a)
        # #8 SetStats 覆盖（真实 Action，定义于 batch_spells2）
        from hsrl2.scripts.batches.batch_spells2 import SetStats
        game.run_actions(SetStats(target, 20, 20))
        self.assertEqual(target.atk, 20)
        self.assertEqual(seen, [])
        # #11 种族光环（`ApplyRaceAura` 真实 Action——读时计算）
        from hsrl2.actions.racefx import ApplyRaceAura
        game.run_actions(ApplyRaceAura(a, Race.ALL, 5, 0, source_id="TEST"))
        self.assertEqual(target.atk, 25)
        self.assertEqual(seen, [])
        # #7 磁力相加（BASE_ATK 直改）
        host = put(game, "BG_OG_221", a)
        mag = game.create_minion("BG_OG_221", controller=a)
        mag.set(GameTag.MAGNETIC, True)
        game.attach_magnetic(a, mag, host)
        self.assertGreater(host.atk, 0)
        self.assertEqual(seen, [])

    def test_health_only_gain_does_not_trigger_attack_family(self):
        """仅生命增益（`atk == 0`）→ "gain Attack" 家族不触发。"""
        game = make_game(204)
        a = game.heroes[0]
        smug = put(game, "BG21_013", a)
        dragon = put(game, "BG25_027", a)
        base = smug.health
        game.run_actions(Buff(dragon, health=7))
        self.assertEqual(dragon.health, get_db().get("BG25_027").health + 7)
        self.assertEqual(smug.health, base)

    def test_negative_attack_delta_does_not_trigger(self):
        """负向附魔（攻击下降）不构成"获得"（§E D4）。"""
        game = make_game(205)
        a = game.heroes[0]
        smug = put(game, "BG21_013", a)
        dragon = put(game, "BG25_027", a)
        seen = spy(game, a)
        game.run_actions(Buff(dragon, atk=-3))
        self.assertEqual([e for e in seen if e["atk"] > 0], [])
        self.assertEqual(smug.health, get_db().get("BG21_013").health)

    def test_listener_survives_combat_restore(self):
        """接线生命周期: `on_summon`（招募期）注册的监听器在
        `run_combat` 的战斗快照恢复后**仍存活**（`events_snapshot` 含它）
        → 战后仍能触发。"""
        game = make_game(206)
        a, b = game.heroes
        put(game, "BG21_013", a)
        dragon = put(game, "BG_OG_221", a)
        dragon.set(GameTag.RACE, Race.DRAGON)
        put(game, "BG_OG_221", b)                    # 对手有随从供战斗
        before = len(game.events._listeners["stats_gained"])
        self.assertEqual(before, 1)
        game.run_combat(a, b, alive_count=2)
        self.assertEqual(len(game.events._listeners["stats_gained"]), 1)
        base = dragon.health
        game.run_actions(Buff(dragon, atk=1))
        self.assertEqual(dragon.health, base + 1)    # 战后监听仍生效


class TestWhelpSmuggler(unittest.TestCase):
    """BG21_013 / _G — friendly Dragon gains Attack → give it +1/2 Health。"""

    def test_dragon_gain_grants_health(self):
        """真实路径: 友方龙 +3 攻击 → **该龙** +num(0) 生命。"""
        game = make_game(300)
        a = game.heroes[0]
        put(game, "BG21_013", a)
        dragon = put(game, "BG_OG_221", a)
        dragon.set(GameTag.RACE, Race.DRAGON)
        base = dragon.health
        game.run_actions(Buff(dragon, atk=3))
        self.assertEqual(dragon.health,
                         base + get_db().get("BG21_013").num(0))

    def test_non_dragon_gain_does_not_trigger(self):
        game = make_game(301)
        a = game.heroes[0]
        put(game, "BG21_013", a)
        beast = put(game, "BG_OG_221", a)
        base = beast.health
        game.run_actions(Buff(beast, atk=3))
        self.assertEqual(beast.health, base)

    def test_opponent_dragon_does_not_trigger(self):
        game = make_game(302)
        a, b = game.heroes
        put(game, "BG21_013", a)
        foe = put(game, "BG_OG_221", b)
        foe.set(GameTag.RACE, Race.DRAGON)
        base = foe.health
        game.run_actions(Buff(foe, atk=3))
        self.assertEqual(foe.health, base)

    def test_golden_grants_two(self):
        game = make_game(303)
        a = game.heroes[0]
        put(game, "BG21_013", a, golden=True)
        dragon = put(game, "BG_OG_221", a)
        dragon.set(GameTag.RACE, Race.DRAGON)
        base = dragon.health
        self.assertEqual(get_db().get("BG21_013_G").num(0), 2)
        game.run_actions(Buff(dragon, atk=1))
        self.assertEqual(dragon.health, base + 2)

    def test_all_race_amalgam_counts_as_dragon(self):
        game = make_game(304)
        a = game.heroes[0]
        put(game, "BG21_013", a)
        amalgam = put(game, "BG30_102", a)          # All
        self.assertEqual(amalgam.race, Race.ALL)
        d = get_db().get("BG30_102")
        self.assertEqual((d.atk, d.health), (6, 7))   # 数据核实
        game.run_actions(Buff(amalgam, atk=2))
        # 6/7 +2 攻 → +2 攻 +num(0) 生命
        self.assertEqual(amalgam.atk, 8)
        self.assertEqual(amalgam.health, 7 + 1)

    def test_wiring_idempotent_on_resummon(self):
        """`on_summon` 重入（同实体）不重复接线。"""
        game = make_game(305)
        a = game.heroes[0]
        put(game, "BG21_013", a)
        game.run_script_hook(a.board[0], "on_summon")   # 重入
        self.assertEqual(len(game.events._listeners["stats_gained"]), 1)
        dragon = put(game, "BG_OG_221", a)
        dragon.set(GameTag.RACE, Race.DRAGON)
        base = dragon.health
        game.run_actions(Buff(dragon, atk=1))
        self.assertEqual(dragon.health, base + 1)


class TestDefiantShipwright(unittest.TestCase):
    """BG21_018 / _G — this gains Attack **from other sources** → +1 Health
    （金色 "twice" = 两次触发）。"""

    def test_other_source_spell_triggers(self):
        """真实法术路径（BG33_812 "Give four friendly minions +Attack"）。

        棋盘只有本体一只（唯一目标，规避随机取 4 的采样不确定）→
        法术给本体 +num(0) 攻，`source` = 法术实体（"other sources"）
        → 本体 +num(1) 生命。"""
        game = make_game(400)
        a = game.heroes[0]
        ship = put(game, "BG21_018", a)
        base = ship.health
        # 真实"效果施法"入口（`cast_spell_effect`）——目标显式给出，
        # 规避 BG33_812 的 "four random" 采样不确定性
        self.assertTrue(game.cast_spell_effect(a, "BG33_812", target=ship))
        n = get_db().get("BG33_812").num(0)
        self.assertEqual(ship.atk, get_db().get("BG21_018").atk + n)
        self.assertEqual(ship.health, base + get_db().get("BG21_018").num(1))

    def test_self_source_does_not_trigger(self):
        """`source is 本体` → "from other sources" 排除（负对照）。"""
        game = make_game(401)
        a = game.heroes[0]
        ship = put(game, "BG21_018", a)
        base = ship.health
        game.run_actions(Buff(ship, atk=2, source=ship))
        self.assertEqual(ship.atk, get_db().get("BG21_018").atk + 2)
        self.assertEqual(ship.health, base)

    def test_unattributed_source_triggers(self):
        """来源不可判定（`source is None`）→ 计（不臆造来源）。"""
        game = make_game(402)
        a = game.heroes[0]
        ship = put(game, "BG21_018", a)
        base = ship.health
        game.run_actions(Buff(ship, atk=2))
        self.assertEqual(ship.health, base + get_db().get("BG21_018").num(1))

    def test_other_minion_gain_does_not_trigger_self_listener(self):
        """本体监听"this"——别的随从获得攻击不触发。"""
        game = make_game(403)
        a = game.heroes[0]
        ship = put(game, "BG21_018", a)
        other = put(game, "BG_OG_221", a)
        game.run_actions(Buff(other, atk=2, source=ship))
        self.assertEqual(ship.health, get_db().get("BG21_018").health)

    def test_health_only_does_not_trigger(self):
        game = make_game(404)
        a = game.heroes[0]
        ship = put(game, "BG21_018", a)
        game.run_actions(Buff(ship, health=5))
        self.assertEqual(ship.health, get_db().get("BG21_018").health + 5)

    def test_golden_triggers_twice(self):
        game = make_game(405)
        a = game.heroes[0]
        ship = put(game, "BG21_018", a, golden=True)
        base = ship.health
        game.run_actions(Buff(ship, atk=1))
        self.assertEqual(ship.health, base + 2 * get_db().get(
            "BG21_018_G").num(1))


class TestHunterOfGatherers(unittest.TestCase):
    """BG25_027 / _G — this gains Attack → 你的**全部**随从 +2/4 Health
    （官方 31.4.2 + 卡页 + 数据: "your minions"，无 "other" → 含自身）。

    **纠错记录（2026-09-20 对抗验证）**: 旧用例
    `test_gain_buffs_other_minions_not_self` 断言本体**不**被加生命
    （"other"）——该断言固化了 `f0426d5` 的错误实现（依据仅一条 wiki
    patch 文章 revid=892585 的孤立笔误）。已改为断言**含自身**，证据见
    `batch_stats_gained.py` 模块 docstring「BG25_027 权威复核」。
    """

    def test_gain_buffs_all_minions_including_self(self):
        """真实路径: 本体获得攻击 → 己方全部存活随从（**含本体**）+2。"""
        game = make_game(500)
        a = game.heroes[0]
        hunter = put(game, "BG25_027", a)
        other = put(game, "BG_OG_221", a)
        base_h, base_o = hunter.health, other.health
        game.run_actions(Buff(hunter, atk=3))
        self.assertEqual(hunter.health, base_h + 2)      # "your minions"
        self.assertEqual(other.health, base_o + 2)

    def test_health_only_does_not_trigger(self):
        game = make_game(501)
        a = game.heroes[0]
        hunter = put(game, "BG25_027", a)
        other = put(game, "BG_OG_221", a)
        game.run_actions(Buff(hunter, health=4))
        self.assertEqual(other.health, get_db().get("BG_OG_221").health)

    def test_opponent_board_unaffected(self):
        game = make_game(502)
        a, b = game.heroes
        hunter = put(game, "BG25_027", a)
        foe = put(game, "BG_OG_221", b)
        game.run_actions(Buff(hunter, atk=2))
        self.assertEqual(foe.health, get_db().get("BG_OG_221").health)

    def test_dead_minion_excluded(self):
        game = make_game(503)
        a = game.heroes[0]
        hunter = put(game, "BG25_027", a)
        dead = put(game, "BG_OG_221", a)
        dead.set(GameTag.HEALTH, 0)
        hunter.set(GameTag.HEALTH, 100)
        game.run_actions(Buff(hunter, atk=2))
        self.assertEqual(dead.health, 0)

    def test_golden_grants_four(self):
        game = make_game(504)
        a = game.heroes[0]
        hunter = put(game, "BG25_027", a, golden=True)
        other = put(game, "BG_OG_221", a)
        base_h, base_o = hunter.health, other.health
        game.run_actions(Buff(hunter, atk=2))
        self.assertEqual(other.health, base_o + 4)
        self.assertEqual(hunter.health, base_h + 4)      # 含自身


class TestStormbringer(unittest.TestCase):
    """BG26_966 / _G — a different friendly Dragon gains Attack → this
    also gains it（金色 twice）。"""

    def test_copies_attack_delta(self):
        game = make_game(600)
        a = game.heroes[0]
        storm = put(game, "BG26_966", a)
        dragon = put(game, "BG25_027", a)
        base = storm.atk
        game.run_actions(Buff(dragon, atk=4))
        self.assertEqual(storm.atk, base + 4)

    def test_self_gain_does_not_trigger(self):
        game = make_game(601)
        a = game.heroes[0]
        storm = put(game, "BG26_966", a)
        base = storm.atk
        game.run_actions(Buff(storm, atk=5))
        self.assertEqual(storm.atk, base + 5)            # 只有自己的那份

    def test_non_dragon_does_not_trigger(self):
        game = make_game(602)
        a = game.heroes[0]
        storm = put(game, "BG26_966", a)
        beast = put(game, "BG_OG_221", a)
        base = storm.atk
        game.run_actions(Buff(beast, atk=4))
        self.assertEqual(storm.atk, base)

    def test_opponent_dragon_does_not_trigger(self):
        game = make_game(603)
        a, b = game.heroes
        storm = put(game, "BG26_966", a)
        foe = put(game, "BG25_027", b)
        base = storm.atk
        game.run_actions(Buff(foe, atk=4))
        self.assertEqual(storm.atk, base)

    def test_golden_twice(self):
        game = make_game(604)
        a = game.heroes[0]
        storm = put(game, "BG26_966", a, golden=True)
        dragon = put(game, "BG25_027", a)
        base = storm.atk
        game.run_actions(Buff(dragon, atk=3))
        self.assertEqual(storm.atk, base + 6)

    def test_health_only_does_not_trigger(self):
        game = make_game(605)
        a = game.heroes[0]
        storm = put(game, "BG26_966", a)
        dragon = put(game, "BG25_027", a)
        base = storm.atk
        game.run_actions(Buff(dragon, health=6))
        self.assertEqual(storm.atk, base)


class TestSpacefarer(unittest.TestCase):
    """BG31_820 / _G — another friendly Pirate gains Attack → +2/4 Health。"""

    def test_another_pirate_triggers(self):
        game = make_game(700)
        a = game.heroes[0]
        space = put(game, "BG31_820", a)
        mate = put(game, "BG_OG_221", a)
        mate.set(GameTag.RACE, Race.PIRATE)
        game.run_actions(Buff(mate, atk=2))
        self.assertEqual(space.health, get_db().get("BG31_820").health + 2)

    def test_self_gain_does_not_trigger(self):
        game = make_game(701)
        a = game.heroes[0]
        space = put(game, "BG31_820", a)
        base = space.health
        game.run_actions(Buff(space, atk=3))
        self.assertEqual(space.health, base)

    def test_non_pirate_does_not_trigger(self):
        game = make_game(702)
        a = game.heroes[0]
        space = put(game, "BG31_820", a)
        naga = put(game, "BG_OG_221", a)
        naga.set(GameTag.RACE, Race.NAGA)
        game.run_actions(Buff(naga, atk=2))
        self.assertEqual(space.health, get_db().get("BG31_820").health)

    def test_opponent_pirate_does_not_trigger(self):
        game = make_game(703)
        a, b = game.heroes
        space = put(game, "BG31_820", a)
        foe = put(game, "BG_OG_221", b)
        foe.set(GameTag.RACE, Race.PIRATE)
        game.run_actions(Buff(foe, atk=2))
        self.assertEqual(space.health, get_db().get("BG31_820").health)

    def test_golden_grants_four(self):
        game = make_game(704)
        a = game.heroes[0]
        space = put(game, "BG31_820", a, golden=True)
        mate = put(game, "BG_OG_221", a)
        mate.set(GameTag.RACE, Race.PIRATE)
        game.run_actions(Buff(mate, atk=1))
        self.assertEqual(space.health, get_db().get("BG31_820_G").health + 4)


class TestTimewarpedWhelpSmuggler(unittest.TestCase):
    """BG34_Giant_064 / _G — friendly minion gains Attack → give it
    +num(1) Health。"""

    def test_typeless_minion_triggers(self):
        game = make_game(800)
        a = game.heroes[0]
        smug = put(game, "BG34_Giant_064", a)
        target = put(game, "BG_OG_221", a)          # 无类型
        game.run_actions(Buff(target, atk=2))
        self.assertEqual(target.health,
                         get_db().get("BG_OG_221").health
                         + get_db().get("BG34_Giant_064").num(1))

    def test_health_only_does_not_trigger(self):
        game = make_game(801)
        a = game.heroes[0]
        smug = put(game, "BG34_Giant_064", a)
        target = put(game, "BG_OG_221", a)
        game.run_actions(Buff(target, health=5))
        self.assertEqual(target.health, get_db().get("BG_OG_221").health + 5)

    def test_opponent_minion_does_not_trigger(self):
        game = make_game(802)
        a, b = game.heroes
        smug = put(game, "BG34_Giant_064", a)
        foe = put(game, "BG_OG_221", b)
        game.run_actions(Buff(foe, atk=2))
        self.assertEqual(foe.health, get_db().get("BG_OG_221").health)

    def test_golden_uses_num1(self):
        game = make_game(803)
        a = game.heroes[0]
        smug = put(game, "BG34_Giant_064", a, golden=True)
        target = put(game, "BG_OG_221", a)
        game.run_actions(Buff(target, atk=1))
        self.assertEqual(target.health, get_db().get("BG_OG_221").health + 6)

    def test_self_gain_counts(self):
        """文本是 "a friendly minion"（含本体）。"""
        game = make_game(804)
        a = game.heroes[0]
        smug = put(game, "BG34_Giant_064", a)
        base = smug.health
        game.run_actions(Buff(smug, atk=2))
        self.assertEqual(smug.health, base + 3)


class TestDeferred(unittest.TestCase):
    """DEFERRED 台账守卫（不注册 = 不得出现在 REGISTRY）。"""

    def test_deferred_not_registered(self):
        from hsrl2.scripts import REGISTRY
        for cid in ("BG34_111", "BG34_111_G",
                    "TB_BaconShop_HERO_52_Buddy",
                    "TB_BaconShop_HERO_52_Buddy_G"):
            self.assertIsNone(REGISTRY.get(cid), cid)
            self.assertIsNotNone(get_db().get(cid), cid)

    def test_registered_family_bound(self):
        from hsrl2.scripts import REGISTRY
        expected = {
            "BG21_013": 1, "BG21_013_G": 2,
            "BG21_018": 1, "BG21_018_G": 1,
            "BG25_027": 2, "BG25_027_G": 4,
            "BG26_966": None, "BG26_966_G": None,
            "BG31_820": 2, "BG31_820_G": 4,
            "BG34_Giant_064": 3, "BG34_Giant_064_G": 6,
        }
        for cid in expected:
            self.assertIsNotNone(REGISTRY.get(cid), cid)

    def test_sepulchral_improve_amount_absent(self):
        """BG34_111 阻塞证据: 提升量无参数（num(1..4) 全 None）。"""
        d = get_db().get("BG34_111")
        self.assertEqual(d.num(0), 2)                # 亡语基础值
        for i in (1, 2, 3, 4):
            self.assertIsNone(d.num(i), i)


if __name__ == "__main__":
    unittest.main()
