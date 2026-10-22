"""差分驱动批 1：TOP 缺脚本卡（679 场官方轨迹分歧频次驱动）。

来源：`runs/diff_report.json.suspect_cards`（2026-10-18 测量口径 v2）。
本批 5 张（按分歧轨迹数排序，语义有权威且可实现的先做）：

1. ``BG30_129`` Catacomb Crasher（23 条分歧）— 溢出召唤触发永久 +num/num
2. ``BG26_199`` Upbeat Duo（18）— 每 2 回合 EoT 获取左侧随从的 plain copy
3. ``BG35_701`` Brazen Buccaneer（17）— EoT 给最左 Pirate 加 num，按本回合
   打出卡数重复
4. ``BG34_926`` Ruthless Queensguard（16）— 战吼/亡语/Rally 施放 Queen's
   Command（战斗内触发，直接影响 679 场战斗结算）
5. ``BG34_694`` Wintergrasp Ghoul（14）— 亡语获取 Tomb Turning

DEFERRED（语义无权威/需新原语，见 ``register()`` 返回与 FIX 说明）：

* ``BG31_171`` Moonsteel Juggernaut — "improve this" 无数值/机制权威，
  无法确定改善的是卫星数值还是自身数值 → 不臆造（SOP §9）。
* ``BG34_922`` Maelstrom Emergent — "Your spells cast an extra time in
  combat" 需要引擎"战斗内施法次数"原语；当前引擎战斗内直施脚本不走
  spell-cast 通道，先 DEFERRED（影响面大，需 Lead 决策）。
* ``BG32_234`` Dastardly Drust — "Whenever you get a Pirate" 的 get 事件
  在引擎内无统一生产点（购买/发现/复制路径不同）→ DEFERRED。
* ``BG34_175`` Junk Jouster — "After you Magnetize a minion" 有 MAGNETIZED
  事件，但"每次磁力吸附"与引擎 attach_magnetic 的多路径语义需先核对
  → 下一批。
* ``BG26_529`` Upbeat Frontdrake — 随机 Dragon 需池感知随机（可做），
  按频次排到下一批。

规则依据（项目权威序）：CardDefs 37.0 文本 + 数值参数（`CardDef.num()`）；
金色独立 CardDef（数值/文本差异由数据体现）；本批未改引擎核心，无新原语。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from hsrl2.actions import Buff
from hsrl2.events import Listener
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ══════════════════════════════════════════════════════════════════════
# 卡 id（普通 + 金色独立 CardDef）
# ══════════════════════════════════════════════════════════════════════

CATACOMB_CRASHER = "BG30_129"
CATACOMB_CRASHER_G = "BG30_129_G"
UPBEAT_DUO = "BG26_199"
UPBEAT_DUO_G = "BG26_199_G"
BRAZEN_BUCCANEER = "BG35_701"
BRAZEN_BUCCANEER_G = "BG35_701_G"
RUTHLESS_QUEENSGUARD = "BG34_926"
RUTHLESS_QUEENSGUARD_G = "BG34_926_G"
WINTERGRASP_GHOUL = "BG34_694"
WINTERGRASP_GHOUL_G = "BG34_694_G"

QUEENS_COMMAND = "BG35_922"     # 法术：全体友方 +{0}/+{1}，Naga 再一份
TOMB_TURNING = "BG34_888"       # 法术（Discover an Undead）

_PIRATE_RACES = (Race.PIRATE, Race.ALL)
_NAGA_RACES = (Race.NAGA, Race.ALL)


def _hero_of(source) -> Optional["Hero"]:
    return getattr(source, "controller", None)


def _living(board) -> list:
    return [m for m in board if not m.dead]


def _card_num(game: "Game", source, index: int) -> Optional[int]:
    """读**该实体当前 CardDef**（金色独立定义）的第 index 个模板参数。"""
    d = game.db.get(source.card_id)
    return d.num(index) if d is not None else None


# ══════════════════════════════════════════════════════════════════════
# BG30_129 Catacomb Crasher
# ══════════════════════════════════════════════════════════════════════


class CatacombCrasherScript:
    """
    Natural language: Whenever you would summon a minion that doesn't fit
    in your warband, give your minions +{0}/+{1} permanently.

    依据: CardDefs 37.0 ``BG30_129``（T5 4/10；NUM_1=2 NUM_2=2）；金色
    ``BG30_129_G``（8/20, NUM_1=4 NUM_2=4，独立 CardDef 自然体现）。

    Formal spec:
      1. on_summon 注册持久监听器 ``minion_overflow``（引擎在
         ``Game.summon`` / ``play_minion`` 判定 ``hero.board_full()`` 后
         广播，payload ``minion=<被拒绝入场的实体>``；owner=source 随本体
         离场自动注销）。
      2. 条件: 被拒绝实体的 ``controller is 本人``（"you would summon"；
         对手溢出不触发）。
      3. 效果: 本人棋盘全部存活随从各 ``Buff(+num(0), +num(1))``
         （文本无 "other"/"random" → 含自身、全体、确定性；"permanently"
         = 普通持久附魔，战斗内触发时随战斗快照回滚——本卡为招募期卡，
         官方溢出主要发生在招募阶段）。
      4. 溢出实体本身不进场（引擎已有行为），效果在拒绝后立即结算。

    Test: test_batch_diff_driven1.py — 满板召唤第 8 只触发 +2/+2（含自身）
    / 金色 +4/+4 / 非溢出召唤不触发 / 对手溢出不触发。
    """

    @staticmethod
    def on_summon(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        atk = _card_num(game, source, 0)
        health = _card_num(game, source, 1)
        if atk is None or health is None:
            return None

        def on_overflow(g, minion=None, **kw):
            if source.dead or minion is None:
                return
            if getattr(minion, "controller", None) is not hero:
                return
            for m in _living(hero.board):
                g.run_actions(Buff(m, atk=atk, health=health, source=source))

        game.events.register(Listener(event="minion_overflow",
                                      owner=source, callback=on_overflow))
        return None


# ══════════════════════════════════════════════════════════════════════
# BG26_199 Upbeat Duo
# ══════════════════════════════════════════════════════════════════════


class UpbeatDuoScript:
    """
    Natural language: At the end of every 2 turns, get a plain copy of the
    minion to the left of this. (X turns left!)

    依据: CardDefs 37.0 ``BG26_199``（T5 6/6；NUM_1=2 = 间隔回合数）；
    金色 ``BG26_199_G``（12/12）文本 "get a plain copy of **adjacent
    minions**"（行为分支：左右各一份）。

    Formal spec:
      1. on_summon 初始化 ``source._upbeat_duo_left = num(0)``（=2；
         文本 "X turns left" 的初始显示值），注册 ``turn_end``
         listener（owner=source，离场自动注销）。
      2. 每次 turn_end: 计数 -1；到 0 时触发并重置为 num(0)
         （"every 2 turns" = 每两次回合结束触发一次；首触发在第 2 个
         EoT——与卡面 "2 turns left" 读法一致）。
      3. 触发: 普通版取本体**左侧相邻**随从，金色版取**左右相邻**
         随从；每份 = **plain copy**（白板、非金色：
         ``create_minion(base_id)``，base_id 取 ``TRIPLE_BASE_CARD_ID``
         回落 ``card_id``），经 ``game.pending_hand_add`` 入手
         （满手排队；"get" 生成副本不走池记账——Lichling Hoarder
         `plain copy` 先例，RULES §2.3/§2.4 副本口径）。
      4. 无相邻随从 → 该次触发落空（不臆造随机目标）；计数照常重置。
      5. 计数存实体 Python 属性（不写 tag）：跨回合保留；离场再入场
         重置为 num(0)；`restore_state` 不回滚（与 Ultraviolet Improve
         计数同口径）。
      6. **B 类迁移（2026-10-18）**: 官方 `TAG_SCRIPT_DATA_NUM_1` 注入
         = 当前 "X turns left"（1..interval）；注入存在时以该值为回放
         窗口前剩余回合基线，无注入 → num(0)（旧行为逐位不变）。

    Test: test_batch_diff_driven1.py — 2 次 EoT 后左侧复制入手（第 1 次
    不触发）/ 金色左右各一份 / plain（无 buff、非金色）/ 左侧无随从落空
    / 非自己回合（对手 EoT）同样计数（turn_end 为全局广播，owner 保证
    只在本体存活时触发）；test_dynamic_state_migration.py — NUM_1=1 →
    下一个 EoT 即触发。
    """

    adjacent = False

    @staticmethod
    def on_summon(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        interval = _card_num(game, source, 0)
        if not interval or interval <= 0:
            return None
        injected = (source.get_script_data(1)
                    if source.is_script_data_injected(1) else None)
        left = int(interval) if injected is None else max(
            1, min(int(injected), int(interval)))
        setattr(source, "_upbeat_duo_left", left)
        # 金色分支在**召唤时**定型（on_summon 由具体注册类调用；listener 内
        # 不能再按基类写死，否则金色也走普通版左侧单份）。
        setattr(source, "_upbeat_duo_adjacent",
                bool(getattr(source.scripts, "adjacent", False)))

        def on_turn_end(g, turn=None, **kw):
            if source.dead or source.zone != Zone.PLAY:
                return
            left = int(getattr(source, "_upbeat_duo_left", int(interval))) - 1
            if left > 0:
                setattr(source, "_upbeat_duo_left", left)
                return
            setattr(source, "_upbeat_duo_left", int(interval))
            UpbeatDuoScript._grant_copies(source, g, interval)

        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_turn_end))
        return None

    @classmethod
    def _grant_copies(cls, source, game: "Game",
                      interval: int = 0) -> None:
        hero = _hero_of(source)
        if hero is None or source.zone != Zone.PLAY:
            return
        adjacent = bool(getattr(source, "_upbeat_duo_adjacent", False))
        board = hero.board
        try:
            index = board.index(source)
        except ValueError:
            return
        neighbors = []
        left = index - 1
        right = index + 1
        if 0 <= left < len(board):
            neighbors.append(board[left])
        if adjacent and 0 <= right < len(board):
            neighbors.append(board[right])
        for neighbor in neighbors:
            if neighbor is None or neighbor is source:
                continue
            base_id = (neighbor.get(GameTag.TRIPLE_BASE_CARD_ID, None)
                       or neighbor.card_id)
            copy = game.create_minion(base_id, controller=hero)
            if copy is None:
                continue
            game.pending_hand_add(hero, copy)


class UpbeatDuoGoldenScript(UpbeatDuoScript):
    """金色 Upbeat Duo：相邻（左右）随从各一份 plain copy。"""

    adjacent = True


# ══════════════════════════════════════════════════════════════════════
# BG35_701 Brazen Buccaneer
# ══════════════════════════════════════════════════════════════════════


class BrazenBuccaneerScript:
    """
    Natural language: At the end of your turn, give your left-most Pirate
    +{0}/+{1}. Repeat for each card you played this turn. ({2})

    依据: CardDefs 37.0 ``BG35_701``（T5 5/6；NUM_1=2 NUM_2=3）；金色
    ``BG35_701_G``（10/12；NUM_1=4 NUM_2=6 —— "Repeat" 次数两版相同）。

    Formal spec:
      1. on_summon 注册 ``turn_end`` listener（owner=source）。
      2. 触发: 取本人棋盘**最左**的 Pirate（board 顺序首个存活且
         ``race ∈ (PIRATE, ALL)``，Amalgam 规则）；无 Pirate → 落空。
      3. 重复次数 = ``1 + 本回合已打出卡数``：
         `CARDS_PLAYED_THIS_TURN`（引擎在 play_minion 累计随从）+
         `TAVERN_SPELLS_CAST_THIS_TURN`（酒馆法术）。文本 "Repeat for
         each card you played this turn" 覆盖两类卡；对手回合的 turn_end
         广播时本英雄计数器已在回合开始时清零（RULES 回合结构），
         owner=source 保证只在本体存活时触发。
      4. 每次重复对同一目标叠一层 ``Buff(+num(0), +num(1))``（"give
         ... Repeat" = 同一目标多次；金色 NUM 已翻倍）。

    Test: test_batch_diff_driven1.py — 本回合 0 张卡 → 1 次 +2/+3 / 2 张
    随从 → 3 次 +6/+9 / 最左 Pirate（不是最左随从）/ 无 Pirate 落空 /
    金色 +4/+6 每次。
    """

    @staticmethod
    def on_summon(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        atk = _card_num(game, source, 0)
        health = _card_num(game, source, 1)
        if atk is None or health is None:
            return None

        def on_turn_end(g, turn=None, **kw):
            if source.dead or source.zone != Zone.PLAY:
                return
            targets = [m for m in hero.board
                       if not m.dead and m.race in _PIRATE_RACES]
            if not targets:
                return
            target = targets[0]     # 最左 Pirate
            played = int(hero.get(GameTag.CARDS_PLAYED_THIS_TURN, 0) or 0)
            spells = int(hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_TURN,
                                  0) or 0)
            times = 1 + played + spells
            for _ in range(times):
                if target.dead:
                    break
                g.run_actions(Buff(target, atk=atk, health=health,
                                  source=source))

        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_turn_end))
        return None


# ══════════════════════════════════════════════════════════════════════
# BG34_926 Ruthless Queensguard
# ══════════════════════════════════════════════════════════════════════


def _cast_queens_command(game: "Game", hero: "Hero", times: int) -> None:
    """施放 Queen's Command（本体效果直施，不经手牌/不占池）。

    Queen's Command 卡面：Give your minions +{0}/+{1}. Give all your Naga
    another +{0}/+{1}. → 先全体存活友方 +num(0)/+num(1)，再对 Naga
    （含 Amalgam）追加一份。与法术脚本 ``QueensCommandScript`` 同口径
    （batch_spells_final），此处用于战斗内 Battlecry/Deathrattle/Rally
    直施。
    """
    d = game.db.get(QUEENS_COMMAND)
    if d is None:
        return
    atk = d.num(0)
    health = d.num(1)
    if atk is None or health is None:
        return
    for _ in range(times):
        living = _living(hero.board)
        for m in living:
            game.run_actions(Buff(m, atk=atk, health=health))
        for m in living:
            if not m.dead and m.race in _NAGA_RACES:
                game.run_actions(Buff(m, atk=atk, health=health))


class RuthlessQueensguardScript:
    """
    Natural language: Battlecry, Deathrattle, and Rally: Cast Queen's
    Command.

    依据: CardDefs 37.0 ``BG34_926``（T6 3/3，keywords = BATTLE_CRY /
    DEATHRATTLE / RALLY）；金色 ``BG34_926_G``（6/6）文本 "Cast Queen's
    Command **twice**"（三个关键词同一行，故三者均 ×2）。

    Formal spec:
      1. 战吼: 打出时（``play_minion`` 的 battlecry 阶段）施放 1 次
         （金色 2 次）。招募期 → buff 持久。
      2. 亡语: 死亡结算时施放 1 次（金色 2 次）；战斗内 → buff 随战斗
         快照回滚（RULES §3.5）。
      3. Rally: 攻击宣告、伤害前施放 1 次（金色 2 次）——本次攻击的
         攻击力快照（``_execute_attack`` 在 run_rally 之后）吃到增益。
      4. 施放 = 本体效果直施（不经 ``play_spell``：不耗手牌/不占池/
         不计施法次数；与 Ring Bearer "cast Shiny Ring" 先例同口径），
         数值取 Queen's Command 的 CardDef num(0)/num(1) = 2/2。
      5. 空棋盘 → 落空（无目标）。

    Test: test_batch_diff_driven1.py — 战吼全体 +2/+2、Naga 额外 +2/+2 /
    金色 ×2（+4/+4、Naga +8/+8）/ 亡语真实 destroy_minion 路径触发 /
    Rally 真实 `_execute_attack` 伤害前生效 / 空板不崩溃。
    """

    casts = 1

    @staticmethod
    def battlecry(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is not None:
            # 金色"Cast twice"由引擎战吼金色双触发实现（play_minion
            # `times *= 2`，SOP 金色战吼纪律）——脚本始终只施放 1 次。
            _cast_queens_command(game, hero, RuthlessQueensguardScript.casts)
        return None

    @staticmethod
    def deathrattle(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is not None:
            # 亡语/ Rally 引擎不做金色双触发 → 脚本按金色文本 ×2。
            times = (RuthlessQueensguardGoldenScript.casts
                     if source.is_golden else RuthlessQueensguardScript.casts)
            _cast_queens_command(game, hero, times)
        return None

    @staticmethod
    def rally(source, game: "Game", ctx=None):
        if source.dead:
            return None
        hero = _hero_of(source)
        if hero is not None:
            times = (RuthlessQueensguardGoldenScript.casts
                     if source.is_golden else RuthlessQueensguardScript.casts)
            _cast_queens_command(game, hero, times)
        return None


class RuthlessQueensguardGoldenScript(RuthlessQueensguardScript):
    """金色：战吼/亡语/Rally 均施放 Queen's Command 两次。"""

    casts = 2


# ══════════════════════════════════════════════════════════════════════
# BG34_694 Wintergrasp Ghoul
# ══════════════════════════════════════════════════════════════════════


class WintergraspGhoulScript:
    """
    Natural language: Deathrattle: Get a Tomb Turning.

    依据: CardDefs 37.0 ``BG34_694``（T5 5/3，DEATHRATTLE）；金色
    ``BG34_694_G``（10/6）文本 "Get **2** Tomb Turnings"。

    Formal spec:
      1. deathrattle: 本人 controller 获得 ``Tomb Turning``（BG34_888，
         池法术）1 份；金色 2 份。
      2. 入手走 ``game.grant_card_copy_to_hand``（池记账 + 满手队列；
         "Get a <spell>" 族统一入口）；池空 → 落空（官方池规则）。
      3. 战斗内亡语照常触发（"Get" 入手不依赖战斗结束）。

    Test: test_batch_diff_driven1.py — 真实 `destroy_minion` 亡语入手 1
    张 / 金色 2 张 / 手牌中卡 id 正确。
    """

    copies = 1

    @staticmethod
    def deathrattle(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        d = game.db.get(TOMB_TURNING)
        if d is None:
            return None
        copies = (WintergraspGhoulGoldenScript.copies
                  if source.is_golden else WintergraspGhoulScript.copies)
        for _ in range(copies):
            if not game.grant_card_copy_to_hand(hero, d):
                break
        return None


class WintergraspGhoulGoldenScript(WintergraspGhoulScript):
    """金色：亡语获取 2 张 Tomb Turning。"""

    copies = 2


# ══════════════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════════════


def register() -> list[str]:
    """注册本批 10 个 card_id（5 张卡 × 普/金）；0 DEFERRED 在本函数内。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (CATACOMB_CRASHER, CatacombCrasherScript),
        (CATACOMB_CRASHER_G, CatacombCrasherScript),
        (UPBEAT_DUO, UpbeatDuoScript),
        (UPBEAT_DUO_G, UpbeatDuoGoldenScript),
        (BRAZEN_BUCCANEER, BrazenBuccaneerScript),
        (BRAZEN_BUCCANEER_G, BrazenBuccaneerScript),
        (RUTHLESS_QUEENSGUARD, RuthlessQueensguardScript),
        (RUTHLESS_QUEENSGUARD_G, RuthlessQueensguardGoldenScript),
        (WINTERGRASP_GHOUL, WintergraspGhoulScript),
        (WINTERGRASP_GHOUL_G, WintergraspGhoulGoldenScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
