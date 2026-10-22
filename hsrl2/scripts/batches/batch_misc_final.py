"""主线补迁批（2026-09-02）: 新原语直接兑现的两张卡。

| id | 名称 | 依赖原语 |
|----|------|----------|
| `BG30_MagicItem_439` | Designer Eyepatch | `hero.triple_threshold_race`（按种族三连阈值） |
| `BG35_MagicItem_156` | Flaming Portrait | `minion_triggered` + `minion_consumed(stats_*)` 关联 |
| `BG30_MagicItem_821t2` | Fishy Sticker | 金色 token 无脚本 → `Game._script_for` 回落基础卡脚本 |
| `TB_BaconUps_307` | Fish of N'Zoth（金）| 金色载荷"**twice**"重放（2026-09-13 对抗验证证伪后补注册） |

两张卡的特殊性:
- 439 是全卡一句话的**规则修饰**（"You only need 2 copies of a Pirate to
  make it Golden"）——数值 2 为卡面字面量（`CardDef.num` 全 None）
- 156 的 "Whenever your Flaming Enforcers **trigger**, also give the stats
  to their neighbors" 需要区分"自身 EoT 触发"与"被其它卡驱动吞噬"——
  仅凭 `minion_consumed` 会过触发（unlock_final 批已证伪该近似），
  故用 `minion_triggered(hook="end_of_turn")` 作为触发信号、
  `minion_consumed(stats_*)` 作为数值来源（ENGINE_BACKLOG §B2-24）
"""

from __future__ import annotations

from typing import List

from hsrl2.actions import Buff
from hsrl2.events import Listener
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
# 金色 Fish of N'Zoth 复用基础版重放实现（禁止复制粘贴——金色仅覆写次数）
from hsrl2.scripts.batches.batch_hero_econ3 import FishOfNZothScript
from hsrl2.tags import GameTag, Race

# 卡面字面量（CardDef.num 全 None; 文本无 {0}/{1} 占位符）
_PIRATE_THRESHOLD = 2


def _hero(ctx):
    return (ctx or {}).get("hero")


def _is_flaming_enforcer(game, minion) -> bool:
    """是否属于 "Flaming Enforcer"（`BG34_500`）卡家族（金色按基础 id）。"""
    base = minion.get(GameTag.TRIPLE_BASE_CARD_ID, None) or minion.card_id
    d = game.db.get(base)
    return d is not None and d.name == "Flaming Enforcer"


class DesignerEyepatchScript:
    """
    Natural language: You only need 2 copies of a <b>Pirate</b> to make it
    Golden.

    Formal Status: CORRECT

    Formal spec:
      1. on_bind: `hero.triple_threshold_race[Race.PIRATE] = 2`
         （引擎 `check_for_triple` 按被合成卡的种族取最低阈值;
         `Race.ALL` 命中一切; 全局 `TRIPLE_THRESHOLD` 仍为兜底）
      2. 只影响**海盗**（含全种族随从——`Race.ALL` 视为所有类型，RULES §8）;
         非海盗仍按 3 份
      3. 只作用于本人（hero 级字段）; 无模板参数（2 为卡面字面量）

    Test: test_batch_misc_final.py — 绑定后 2 张海盗入手即合成金色
      （正对照: 无饰品时 2 张不合成）/ 非海盗（野兽）2 张不合成 /
      对手不受影响

    Params: 无（卡面字面量 "2 copies of a Pirate"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        h.triple_threshold_race[Race.PIRATE] = _PIRATE_THRESHOLD
        return None


class FlamingPortraitScript:
    """
    Natural language: [x]Get a Flaming Enforcer. Whenever your Flaming
    Enforcers trigger, also give the stats to their neighbors.

    Formal Status: CORRECT

    Formal spec:
      1. on_bind: 数据链交付 **Flaming Enforcer 白板副本**（
         `evolution_card_id` → `db.by_dbf`，`grant_trinket_related_card`）
      2. 两个持久监听（owner=饰品）:
         a) `minion_consumed(consumer=, stats_atk=, stats_health=)`:
            吞噬者属于 Flaming Enforcer 家族且 `controller is 本人` →
            记 `source._fl_stats[consumer.uuid] = (stats_atk, stats_health)`
            （**数值来源** = 吞噬瞬间快照）
         b) `minion_triggered(minion=, hook=)`: `hook == "end_of_turn"`
            且 minion 属于该家族且本人 → 取出该实体最近一次吞噬的数值，
            给它的**左右邻**各 `Buff(atk, health)`（"their neighbors" =
            棋盘相邻两位，越界/已死/自身跳过），并清空记录（每次触发一次）
      3. **只认自身 EoT 触发**: 被其它卡驱动吞噬（`minion_consumed` 无对应
         `end_of_turn` 触发）**不**镜像——这是与"仅监听 consumed"近似的
         关键差别（ENGINE_BACKLOG §B2-24）
      4. 只作用于本人（对手 Flaming Enforcer 触发不镜像）
      5. 无模板参数（"the stats" = 吞噬所得数值，运行时读取）

    Test: test_batch_misc_final.py — 真实 `run_script_hook(enforcer,
      "end_of_turn")` 后左右邻各得受害者数值、本体照常获得;
      被其它卡驱动吞噬（无 EoT 触发）不镜像（负对照）/ 对手触发不镜像 /
      无饰品对照不变 / 邻居已死或不存在时不报错（不越界）

    Params: 无（数值来自运行时吞噬快照）
    """

    FLAMING = "BG34_500"

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        source._fl_stats = {}

        def on_consumed(g, consumer=None, stats_atk=None,
                        stats_health=None, **kw):
            if consumer is None or not isinstance(consumer, Minion):
                return
            if consumer.controller is not h:
                return
            if not _is_flaming_enforcer(g, consumer):
                return
            source._fl_stats[consumer.uuid] = (stats_atk or 0,
                                               stats_health or 0)

        def on_triggered(g, minion=None, hook=None, **kw):
            if hook != "end_of_turn" or not isinstance(minion, Minion):
                return
            if minion.controller is not h \
                    or not _is_flaming_enforcer(g, minion):
                return
            stats = source._fl_stats.pop(minion.uuid, None)
            if stats is None:
                return
            board = h.board
            if minion not in board:
                return
            i = board.index(minion)
            acts = []
            for j in (i - 1, i + 1):
                if 0 <= j < len(board):
                    nb = board[j]
                    if nb is not minion and not nb.dead:
                        acts.append(Buff(nb, atk=stats[0],
                                         health=stats[1]))
            if acts:
                g.run_actions(acts)

        game.events.register(Listener(event="minion_consumed", owner=source,
                                      callback=on_consumed))
        game.events.register(Listener(event="minion_triggered",
                                      owner=source,
                                      callback=on_triggered))
        return None




class FishyStickerScript:
    """
    Natural Language: [x]<b>Start of Combat:</b> Summon a Golden Fish of
    N'Zoth that copies <b>Deathrattles</b>.

    Formal Status: CORRECT

    Formal spec:
      1. `start_of_combat`（饰品 SoC 钩子，先于攻击循环）: 数据链
         `evolution_card_id` 直指**金色** token `TB_BaconUps_307`
         （Fish of N'Zoth 金色变体; `db.golden_version` 对它为 None——它
         本身就是金色定义）→ `create_minion(rel.id, golden=True)`
         （`golden=True` 保证 GOLDEN + TRIPLE_BASE_CARD_ID 齐备）
      2. 该金色 token **无独立脚本** → 引擎 `Game._script_for` 回落基础卡
         脚本 `FishOfNZothScript`（`TB_BaconShop_HP_105t`）——"copies
         Deathrattles" 的行为来自该脚本；数值一律按实体自身金色 CardDef
         读取（ENGINE_BACKLOG §B15 已闭环）
      3. `summon` 入板; 棋盘已满 → 召唤落空（官方召唤失败语义，不报错）
      4. 战斗期召唤物不占池（token 非池卡）; 战后随棋盘复原消失（RULES §3.5）
      5. 只作用于本人（对手 SoC 不召唤）
      6. 数据链断裂 → fail-loud

    Test: test_batch_misc_final.py — 真实 `run_combat` 的
      `start_of_combat` 探针读到金色 `TB_BaconUps_307` 在板上（正对照:
      无饰品同场景无该实体）/ 满板时落空不报错 / 对手不受影响

    Params: 无模板参数（金色 token 由数据链决定）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = getattr(source, "controller", None)
        if h is None:
            return None
        rel = game.trinket_related_card(source.card_id)
        if rel is None:
            raise GameStateError(
                f"{source.card_id}: evolution_card_id broken data chain")
        m = game.create_minion(rel.id, controller=h, golden=True)
        if m is None:
            return None
        game.summon(h, m)          # 满板 → 回落 False（落空，不报错）
        return None


class GoldenFishOfNZothScript(FishOfNZothScript):
    """
    Natural Language: [x]After a different friendly <b>Deathrattle</b>
    minion dies in combat, gain its <b>Deathrattle</b> twice.

    Evidence: 金色独立卡定义 `TB_BaconUps_307`（`data/bg_cards.json` 文本
    "gain its **Deathrattle twice**"，基础版 `TB_BaconShop_HP_105t` 无
    "twice"）；`db.golden_version(TB_BaconShop_HP_105t)` = `TB_BaconUps_307`。

    Formal Status: CORRECT

    Formal spec:
      1. `on_summon`（**继承** `FishOfNZothScript`）: 登记 `_gained_drs`
         为空 + `death` 监听（owner=本体）——战斗内每张不同的友方亡语
         随从死亡各记一次（`g.in_combat` 守卫）
      2. `deathrattle`（本类覆写）: 对每张获得的亡语重放 **2** 次
         （金色文本 "twice"）——复用 `FishOfNZothScript.deathrattle`
         同一实现（宿主 card_id/scripts 临时替换 + 还原语义一致），
         禁止复制粘贴
      3. 数值/属性按实体自身金色 CardDef（4/4）读取

    Test: test_batch_misc_final.py::TestFishySticker —
      金色 Fish 战斗内获得 1 张亡语后死亡 → 亡语效果结算 **2** 次;
      正对照: 基础版 `TB_BaconShop_HP_105t` 同场景 1 次;
      负对照: 无友方亡语死亡 → 0 次

    Params: 无模板参数（重放次数 = 金色文本字面量 2）
    """

    #: 金色文本 "gain its Deathrattle **twice**" 的字面量
    _DEATHRATTLE_REPEATS = 2

    @staticmethod
    def deathrattle(source, game, ctx):
        for _ in range(GoldenFishOfNZothScript._DEATHRATTLE_REPEATS):
            FishOfNZothScript.deathrattle(source, game, ctx)


def register() -> List[str]:
    from hsrl2.scripts.registry import register as _register
    out: List[str] = []
    for cid, cls in (
        ("BG30_MagicItem_439", DesignerEyepatchScript),
        ("BG35_MagicItem_156", FlamingPortraitScript),
        ("BG30_MagicItem_821t2", FishyStickerScript),
        ("TB_BaconUps_307", GoldenFishOfNZothScript),
    ):
        _register(cid, cls)
        out.append(cid)
    return out
