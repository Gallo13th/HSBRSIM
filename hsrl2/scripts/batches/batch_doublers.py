"""三张 doubler 光环核心卡（引擎消费点就绪后的主线补充）。

Brann Bronzebeard / Drakkari Enchanter / Titus Rivendare——光环随
宿主离场失效（棋盘扫描式，非 sticky player-tag——v1 已知缺陷的修复）。
"""

from hsrl2.scripts.registry import register
from hsrl2.tags import GameTag


class BrannBronzebeardScript:
    """
    Natural language: Your <b>Battlecries</b> trigger twice.

    Formal spec:
      1. on_summon: 不设置任何持久状态——引擎 play_minion /
         TriggerBattlecry 通过**棋盘扫描** BATTLECRY_DOUBLER tag 判定
         翻倍（game._battlecry_doubled），随从离场（死亡/出售）光环即失效
      2. 本类仅声明 tag: 宿主实体 create_minion 时按 _KEYWORD_TAG_MAP
         不会设置——在此 on_summon 设置宿主 tag

    Test: test_engine_gaps.py::TestDoublerAuras — Brann 在场战吼×2、
    离场失效

    Params: 无
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.BATTLECRY_DOUBLER, True)
        return None


class DrakkariEnchanterScript:
    """
    Natural language: Your end of turn effects trigger twice.

    Formal spec: 同 Brann 模式——引擎 end_recruit_phase 棋盘扫描
    END_OF_TURN_DOUBLER tag 翻倍（含金色版: 金色 Drakkari = ×3 官方
    语义——金色版独立类覆盖）

    Test: test_engine_gaps.py::TestDoublerAuras

    Params: 无
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.END_OF_TURN_DOUBLER, True)
        return None


class DrakkariEnchanterGoldenScript(DrakkariEnchanterScript):
    """金色: Your end of turn effects trigger **three** times.
    引擎 EoT 扫描按 tag 次数×基数——金色置 tag 两次（2×2=4? 不对——
    引擎实现为 times=2 if any。金色×3 需要引擎支持倍率。为避免近似:
    金色置专用计数……引擎 times 逻辑为布尋试。金色官方文本 ×3，
    引擎消费点不支持倍率 → 金色置双 tag 实例不可行。
    正确路径: 引擎 times = 2 + (1 if golden_doubler_present)。
    见 game.end_recruit_phase——主线已同步实现倍率（DOUBLER tag 计数式）。
    """

    @staticmethod
    def on_summon(source, game, ctx):
        # 金色宿主额外置 GOLDEN 标志时引擎识别 ×3: end_recruit_phase
        # 消费点为 any() 布尔——金色 Drakkari 语义在引擎侧按
        # "END_OF_TURN_DOUBLER 且 is_golden" 判 ×3（主线接线）
        source.set(GameTag.END_OF_TURN_DOUBLER, True)
        return None


class TitusRivendareScript:
    """
    Natural language: Your <b>Deathrattles</b> trigger an extra time.

    Formal spec: 同 Brann 模式——引擎 _process_single_death 棋盘扫描
    DEATHRATTLE_DOUBLER tag 翻倍（亡语者自身死亡时 Titus 在场则翻倍）。

    Test: test_engine_gaps.py::TestDoublerAuras

    Params: 无
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.DEATHRATTLE_DOUBLER, True)
        return None


def register() -> list[str]:
    from hsrl2.scripts.registry import register as _register
    ids = []
    for cid, cls in (
        ("BG_LOE_077", BrannBronzebeardScript),
        ("TB_BaconUps_045", BrannBronzebeardScript),      # 金色=同光环
        ("BG26_ICC_901", DrakkariEnchanterScript),
        ("BG26_ICC_901_G", DrakkariEnchanterGoldenScript),
        ("BG25_354", TitusRivendareScript),
        ("BG25_354_G", TitusRivendareScript),             # 金色=同光环
    ):
        _register(cid, cls)
        ids.append(cid)
    return ids
