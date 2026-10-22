"""批次 trinkets9 — 饰品第九批: 非商店授予/替换族（作业单 2026-09-11）。

引擎协议依据: RULES §7.4.3「饰品获取协议（商店购买 / 直接授予 / 替换）」——
`game.grant_trinket(hero, id, source=)`（唯一直接授予入口: 跨局去重 +
入 `hero.trinkets` + 跑 `on_bind` + 广播 `trinket_granted`）、
`game.grant_random_trinket(hero, kind="lesser"/"greater")`、
`game.replace_trinket(hero, old, new_id)`（移除旧实体/注销监听器后授予）;
商店购买广播 `trinket_bought(hero, trinket, kind)`。

注册 4 张
═══════════════════════════════════════════════════════════════════════
  BG35_MagicItem_816  Orb of the Unknown     — on_bind: 随机授予一张未获得
                                               的 Lesser 饰品
                                               （`grant_random_trinket`）
  BG36_MagicItem_305  Rune of Transmutation  — 施放 num(0)=15 个法术后，
                                               用一张随机 Greater Naga 饰品
                                               替换自身
                                               （`replace_trinket` +
                                               `subset_naga` 过滤）
  BG30_MagicItem_703  Mystery Cube           — on_bind + 每回合开始:
                                               2 选 1 张未获得的 Lesser 饰品
                                               免费替换自身
                                               （PendingChoice +
                                               `replace_trinket`）
  BG30_MagicItem_891  Trip Vouchers          — num(0)=2 个回合后，开放一次
                                               Greater 饰品三选一（付费购买，
                                               复用引擎 `_offer_trinkets`），
                                               买到即以该饰品替换自身
                                               （`trinket_bought` 监听 +
                                               `replace_trinket`）

DEFERRED（本批评估后放弃；附具体引擎依赖）
═══════════════════════════════════════════════════════════════════════
  - （已清空）BG30_MagicItem_888 Souvenir Stand 曾因「引擎缺"复制/重复
    授予一张**已获得**饰品"的通道」而 DEFERRED（`grant_trinket` 以
    `_trinkets_granted` 去重，商店 resolve 又在广播 `trinket_bought`
    之前就记账 → "copy of it" 无法落地）。**2026-09-02 副本原语落地后
    已解冻**（RULES §7.4.3 副本条款）:
      * `game.grant_trinket(hero, id, duplicate=True)` —— 跳过跨局去重
      * `game.copy_trinket(hero, id, replace=实体)` —— "transforms into
        a copy of it" 的完整语义（本体 + 副本两份同时生效）
      实现见 `hsrl2/scripts/batches/batch_trinkets13.py`
      `SouvenirStandScript`（本批不再持有该卡的 DEFERRED 台账）。
    同一缺口亦曾阻塞 BG35_Anomaly_007t/008t（Crystal Ball 族）——已由
    `batch_anomalies6` + `game.set_second_slot_trinket` 解决。

数值口径: 一律 `CardDef.num(0/1)`; 文本无占位符的量（"2 new"/
"random Greater Naga Trinket"/"In 2 turns" 之外的措辞）按 SOP §3 以文本
字面量实现并在各类 `Params:` 行声明。随机一律 `game.rng`。全部状态写在
hero 作用域 / 脚本闭包 / source 实体（无 game 级 flag——SOP §12 item 9）。

已知的引擎读取点（供接线审计）: 本批读取 `game._trinkets_granted`
（`grant_trinket`/`_offer_trinkets`/`grant_random_trinket` 共用的
"跨局不重复"记账集）以计算 "new/un-granted" 候选——引擎未提供公开查询
入口（`grant_random_trinket` 只暴露 kind 过滤）。
"""

from __future__ import annotations

from typing import List

from hsrl2.events import CARD_PLAYED, TURN_START, Listener
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.spell import Spell as SpellType

# 饰品档位（数据权威: spell_school 11=Lesser / 12=Greater——RULES §7.4.2）
LESSER_SCHOOL = 11
GREATER_SCHOOL = 12

# "Choose from 2 new Lesser Trinkets"（BG30_MagicItem_703 文本字面量;
# CardDef 无 {0}/{1} 占位符——num(0)/num(1) 均为 None）
LESSER_CHOICE_COUNT = 2

# 默认 PendingChoice kind（"n 选 1 免费替换自身"协议）
TRINKET_REPLACE_KIND = "trinket_replace"


def _hero(ctx):
    return ctx.get("hero") if ctx else None


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def ungranted_lesser_trinkets(game, hero) -> List:
    """**该英雄**尚未获得的 Lesser 饰品（"2 new"/"a random Lesser" 候选）。

    口径与商店完全一致（RULES §7.4.2/§7.4.3）:
      `db.trinket_offer_pool()`（排除内部 token 与升级变体）
      ∩ `spell_school == 11`（Lesser）
      − `hero.trinkets_granted`（**per-player** 记账——官方 "a Trinket
        **you** already have"; 2026-09-02 修复: 旧实现读 game 级并集，
        对手拿到 X 后本人池里的 X 永久消失）
    """
    return [d for d in game.db.trinket_offer_pool()
            if d.spell_school == LESSER_SCHOOL
            and d.id not in hero.trinkets_granted]


def ungranted_greater_naga_trinkets(game, hero) -> List:
    """本局尚未获得的 **Greater Naga** 饰品（BG36_MagicItem_305 文本）。

    `subset_naga` 是数据字段（subset_* 导出; BG36_MagicItem_305 自身即
    `subset_naga=True`），与档位过滤叠加——"random Greater Naga Trinket"
    不接受非 Naga/非 Greater 项。
    """
    return [d for d in game.db.trinket_offer_pool()
            if d.spell_school == GREATER_SCHOOL
            and "naga" in d.subsets
            and d.id not in hero.trinkets_granted]


def offer_lesser_replace(hero, game, source, *,
                         count: int = LESSER_CHOICE_COUNT) -> bool:
    """`Choose from N new Lesser Trinkets to replace this for free.`

    返回 True = 已排队 PendingChoice; False = 无候选（落空，不建选择）。

    契约:
      1. 候选 = `ungranted_lesser_trinkets(game, hero)`（"new" = 本人未获得）;
         `game.rng.sample` 取 count 个互异项（不足则全给）
      2. 选项即**未获得的**饰品 CardDef；resolve 落点在
         `game.replace_trinket(hero, source, pick.id)` —— 移除本饰品实体
         （注销其全部监听器，故 "At the start of each turn, repeat this"
         的节奏随替换自然终止）并授予选中项
      3. **免费**（"for free"）: 不扣金币、不广播 `trinket_bought`
         （非商店购买路径——RULES §7.4.3）
      4. 陈旧防护（SOP §16 item 24）:
         - source 已不在 `hero.trinkets`（本回合内已被替换）→ 落空
         - 选项在结算窗口内已被并发授予 → 落空且**保留** source
           （不白白消耗饰品）
    """
    options = _sample_lesser_options(game, hero, count)
    if not options:
        return False

    def resolve(pick):
        if pick is None:
            return
        if source not in hero.trinkets:
            return
        if pick.id in hero.trinkets_granted:
            return
        game.replace_trinket(hero, source, pick.id)

    game.pending_choices.append(PendingChoice(
        hero, options, TRINKET_REPLACE_KIND, resolve_callback=resolve))
    return True


def _sample_lesser_options(game, hero, count: int) -> List:
    pool = ungranted_lesser_trinkets(game, hero)
    if not pool:
        return []
    return game.rng.sample(pool, min(count, len(pool)),
                           label="lesser_trinket_choice")


# ══════════════ BG35_MagicItem_816 Orb of the Unknown ══════════════

class OrbOfTheUnknownScript:
    """
    Natural language: Get a random Lesser <b>Trinket</b>.

    Formal spec:
      1. on_bind（`trinket_granted` 唯一的授予入口钩子——RULES §7.4.3）:
         `game.grant_random_trinket(hero, kind="lesser")` —— 从
         `db.trinket_offer_pool()` 中**未获得**的 Lesser 饰品里随机一张
         （`game.rng`; 已获得项被 `_trinkets_granted` 排除——Orb 自身也
         在该集合内，故不会重复授予自己）
      2. 授予走引擎协议: 实体入 `hero.trinkets` + 跑其 `on_bind` +
         广播 `trinket_granted`
      3. 池内 Lesser 全部已获得 → 落空（`grant_random_trinket` 返回 None）
      4. 只作用于本人

    Test: test_batch_trinkets9.py — 真实 `_offer_trinkets` 购买后
      `hero.trinkets` 多出一张 spell_school==11 且此前未获得的饰品 /
      对手棋盘与饰品栏不变 / 强制单候选（预记账其余 Lesser）时必得该候选

    Params: kind="lesser"（"a random Lesser Trinket" 文本——档位由
              spell_school=11 表达）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_random_trinket(h, kind="lesser",
                                  source="orb_of_the_unknown")
        return None


# ══════════════ BG36_MagicItem_305 Rune of Transmutation ══════════════

class RuneOfTransmutationScript:
    """
    Natural language: [x]After you cast 15 spells, replace this with a
    random Greater Naga <b>Trinket</b>. <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `card_played`（card=）——
         引擎在法术**结算后**广播并携带施放者（`card.controller`）;
         计数条件 = `isinstance(card, Spell)` 且 `card.controller is 本人`
      2. 计数跨回合累积（文本无 "this turn"）; 达 num(0)=15 → 清零并
         以一张 **未获得** 的 Greater Naga 饰品替换自身
         （`ungranted_greater_naga_trinkets`: spell_school==12 +
         subset_naga + 未获得; `game.rng.choice` →
         `game.replace_trinket`）
      3. 池内 Greater Naga 耗尽 → 本次落空且**保留计数**（下个法术重试），
         Rune 不被消耗
      4. `replace_trinket` 移除 Rune 实体并注销本监听器——替换后不再计数
      5. 只作用于本人（对手施法不计数）

    Test: test_batch_trinkets9.py — 前 num(0)-1 个法术不替换 / 第 num(0)
      个恰好替换为 Greater+Naga 且 `_trinkets_granted` 记账 / 替换后
      再施法不产生第二张 / 对手施放同数法术不触发（正对照: 本人第
      num(0) 个确实触发）/ 预占全部 Greater Naga 时池耗尽不替换

    Params: {0}=15（BG36_MagicItem_305 num(0)，即文本 "15 spells"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0)
        state = {"n": 0}

        def on_cast(g, card=None, **kw):
            if card is None or card.controller is not h:
                return
            if not isinstance(card, SpellType):
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            if source not in h.trinkets:
                return
            pool = ungranted_greater_naga_trinkets(g, h)
            if not pool:
                return      # 池耗尽: 保留计数，下个法术重试
            pick = g.rng.choice(pool, label="rune_of_transmutation")
            state["n"] = 0
            g.replace_trinket(h, source, pick.id)

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_cast))
        return None


# ══════════════ BG30_MagicItem_703 Mystery Cube ══════════════

class MysteryCubeScript:
    """
    Natural language: [x]Choose from 2 new Lesser <b><b>Trinket</b>s</b>
    to replace this for free. At the start of each turn, repeat this.

    Formal spec:
      1. on_bind（商店购买或非商店授予时）: 立即可选一次——
         `offer_lesser_replace(hero, game, source)` 产生
         PendingChoice(kind="trinket_replace", 2 个**未获得**的 Lesser
         饰品 CardDef); 选中 → `replace_trinket` 免费替换自身
      2. start_of_turn（饰品 SoT 钩子，`game._begin_recruit_for` 分发）:
         同款再可选一次——"At the start of each turn, repeat this"
      3. 每次触发 per-hero 独立（选择 owner=本人）; 一旦选中，Mystery Cube
         实体被移除且 `replace_trinket` 注销其监听器 → 节奏自然终止
      4. 无未获得 Lesser（候选空）→ 该次不建选择（Cube 保留，下回合重试）
      5. 免费: 全程不扣金币、不广播 `trinket_bought`

    Test: test_batch_trinkets9.py — 购买后恰 1 个本人 owner 的
      trinket_replace、2 个互异且未获得的 Lesser 选项 / 选中后 Cube 消失、
      选中饰品入栏、金币不变、`_trinkets_granted` 记账 / 真实推进回合
      （end_recruit_phase）后 SoT 再产生一个选择 / 对手无选择且饰品栏不变
      （正对照: 本人有）/ 候选耗尽不建选择 / 陈旧选择重复结算只授予一张

    Params: count=2（"Choose from 2" 文本字面量——CardDef 无占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        offer_lesser_replace(h, game, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        offer_lesser_replace(h, game, source)
        return None


# ══════════════ BG30_MagicItem_891 Trip Vouchers ══════════════

class TripVouchersScript:
    """
    Natural language: [x]In 2 turns, choose a Greater <b>Trinket</b> to buy
    and replace this. <i>(2 turns left!)</i>

    Formal spec:
      1. on_bind 注册持久 TURN_START 监听器（owner=饰品; 按 hero 过滤——
         闭包默认绑定防晚绑定）: 每次本人回合开始计数 +1
      2. 计数达 num(0)=2（"In 2 turns"）→ 开放一次 **Greater 饰品三选一
         购买**（`game._offer_trinkets(hero, "greater")`——复用引擎商店
         协议: 3 选 1 + 放弃、类型关联/低价保证、扣费、`trinket_bought`
         广播）。**不写** `hero._trinket_early`: 文本无 "instead of
         Turn 9" 措辞，本券是 T9 之外的**额外**一次 Greater 购买机会，
         不得占用 `(hero, "greater")` 商店档位记账（Ornate Clock
         `BG32_MagicItem_271` 才有 "instead of Turn 9"）
      3. 开放 offer 后包装**本次选择的 resolve_callback**（不用
         `trinket_bought` once 监听器——对抗审查 MAJOR: 无 condition 的
         once 监听器会被对手/无关购买消费）: 选中即
         `replace_trinket(hero, 本券, pick.id)`——商店 resolve 已把所选
         记入 `_trinkets_granted` 并入栏，故 `grant_trinket` 去重返回
         None，replace 的净效果 = 本券被所选 Greater 饰品取代
         （不产生第二份，亦不丢失已购饰品）
      4. 放弃（商店 `None` 选项）不广播 `trinket_bought` → 本券保留
      5. 只作用于本人（对手买到 Greater 不消费本券）

    Test: test_batch_trinkets9.py — 第 1 个回合开始无 offer、第 num(0) 个
      恰好出现仅 Greater 档的 trinket_offer（owner=本人）/ 真实选择后
      本券移出饰品栏、所选 Greater 入栏恰一份、扣其费用 / 选择放弃时
      本券保留且金币不变 / 对手无 offer（正对照: 本人有）

    Params: {0}=2（BG30_MagicItem_891 num(0)，即 "In 2 turns"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        turns = _num(game, source.card_id, 0)
        state = {"n": 0, "fired": False}

        def on_sot(g, hero=None, _h=h, **kw):
            if hero is not _h or state["fired"]:
                return
            state["n"] += 1
            if state["n"] < turns:
                return
            state["fired"] = True
            _open_greater_offer(g, _h, source)

        game.events.register(Listener(
            event=TURN_START, owner=source, callback=on_sot,
            condition=lambda hero=None, _h=h, **kw: hero is _h))
        return None


def _open_greater_offer(game, hero, source) -> None:
    """开放一次 Greater 三选一购买，并在**本次选择**成交时替换 source。

    用本次 offer 的 `PendingChoice.resolve_callback` 包装实现，而**不用**
    `trinket_bought` 一次性监听器（2026-09-02 对抗审查 MAJOR）:
      - `EventBus.fire` 对 `once=True` 且无 condition 的监听器一律消费 →
        对手买到任何 Greater 饰品就会烧掉本券（owner 隔离失败），回调内
        `hero is not _h` 早退救不回来;
      - 放弃 offer 后残留的监听器还会被之后**无关**的 T9 商店购买顺手
        销毁（本券凭空消失）。
    包装 resolve 后只有本券自己开出的这次选择才消费本券; 放弃（None）
    时本券保留。
    """
    n_before = len(game.pending_choices)
    game._offer_trinkets(hero, "greater")
    if len(game.pending_choices) <= n_before:
        return                       # 池空 → 未开放选择，本券保留
    choice = game.pending_choices[-1]
    if choice.owner is not hero or choice.kind != "trinket_offer":
        return
    inner = choice.resolve_callback

    def resolve(pick, _inner=inner, _h=hero, _src=source, _g=game):
        _inner(pick)
        if pick is None:
            return                   # 放弃 → 本券保留（RULES §7.4.2）
        if _src not in _h.trinkets:
            return                   # 券已不在（并发消费）→ 不重复处理
        card_id = getattr(pick, "id", None)
        if card_id is None:
            return
        # 商店 resolve 已把所购饰品授予并入栏/记账（去重集含其 id）→
        # replace 只消费本券，净效果 = 本券被所购饰品取代（不产生第二份）
        _g.replace_trinket(_h, _src, card_id)

    choice.resolve_callback = resolve


# ══════════════ 注册 ══════════════

def register() -> list[str]:
    """注册饰品第九批 4 张（DEFERRED 台账见模块 docstring: 888）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG35_MagicItem_816", OrbOfTheUnknownScript),
        ("BG36_MagicItem_305", RuneOfTransmutationScript),
        ("BG30_MagicItem_703", MysteryCubeScript),
        ("BG30_MagicItem_891", TripVouchersScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
