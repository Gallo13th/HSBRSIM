#!/usr/bin/env python
"""接线审计 — 捕获"已注册但引擎从不触发"的脚本（no-op / 近似实现）。

背景（2026-09-01 发现）: `audit_card_registry_v2.py` 只验证"有效果的卡
有脚本"，无法发现**第三态**——脚本类存在、注册成功、测试通过，但引擎
从不调用或标记无人读取，效果实际为 0。已确认的实例:

  - `BG31_Anomaly_111` OnlyYourTier: 设 `hero._tavern_offer_tier_only`，
    引擎从不读取 → 完全空转
  - `BG36_Anomaly_002` DarkGiftDiscover: 异变只有 `on_bind` 被分发，
    却定义了 `available/cost/hero_power`（英雄技能协议）→ 整类空转
  - `BG27_Anomaly_504` Tier7Exists: 直接改写模块级
    `constants.TAVERN_MAX_TIER = 7` → 跨局全局污染
  - `BG27_Anomaly_718` UpgradeRefreshCommonType: 算了 most-common race
    却调用无参数的 refresh → 与文本不符

检查项:
  W1 钩子契约 — 按卡类别的引擎分发集合校验脚本方法名（死钩子）
  W2 事件存在 — `Listener(event=…)` 的事件名必须被引擎/脚本 fire
  W3 契约标记 — 脚本写入的私有属性必须被脚本之外的代码读取（空转标记）

用法: python tools/audit_script_wiring.py [--strict]
退出码: 0=通过（或仅 WARNING 且非 strict）, 1=有 ERROR
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HSRL2 = ROOT / "hsrl2"
SCRIPTS = HSRL2 / "scripts"

# ── W1: 引擎真正分发的钩子（来源: game.py/combat.py/hero.py/actions 的
#    run_script_hook/call_script 实参——改动引擎请同步本表）──
ENGINE_HOOKS = {
    "battlecry", "deathrattle", "start_of_combat", "avenge", "rally",
    "start_of_turn", "end_of_turn", "on_sell", "on_summon", "on_play",
    "activate", "atk", "health", "on_enter_hand", "on_bind",
    # F-08 Discard 子系统: Game.discard_card 分发的"被弃置"钩子
    "on_discard",
}
# 英雄技能协议方法（game.use_hero_power/_finish_hero_power 读取）
HERO_POWER_PROTOCOL = {"hero_power", "available", "cost_override",
                       "target_candidates"}
# 每类卡允许的钩子集合（None=不检查）
ALLOWED_HOOKS: dict[str, set[str]] = {
    # targeted 战吼/法术协议: game.play_minion/play_spell 读取
    "minion": (ENGINE_HOOKS - {"on_bind"}) | {"target_candidates"},
    # 手牌法术同样接收 start_of_turn（game._begin_recruit_for 对
    # hero.hand 内的实体统一分发 run_script_hook(card, "start_of_turn")
    # ——Evolving Scroll 类"手牌持续转换"效果路径）。注意 end_of_turn
    # **不**分发给手牌（仅饰品/任务奖励/棋盘随从），故不在白名单。
    "spell": {"on_play", "target_candidates", "start_of_turn", "on_discard"},
    "hero_power": {"on_bind"} | HERO_POWER_PROTOCOL,
    # 饰品/任务奖励: 引擎 _process_single_death 的 Avenge 计数覆盖
    # 棋盘随从 + 饰品 + 任务奖励（脚本以 `avenge_threshold` 声明阈值）
    "trinket": {"on_bind", "start_of_turn", "end_of_turn", "start_of_combat",
                "avenge"},
    "quest_reward": {"on_bind", "start_of_turn", "end_of_turn",
                     "start_of_combat", "avenge"},
    "quest": {"on_bind"},
    "anomaly": {"on_bind"},
}
CHECKED_HOOK_NAMES = ENGINE_HOOKS | HERO_POWER_PROTOCOL


def _iter_py(root: Path):
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ══════════════ W2 事件名解析 ══════════════

def collect_fired_events() -> set[str]:
    """全部 fire 调用的事件名（字面量 + 模块级常量解析）。"""
    consts: dict[str, str] = {}
    fires: list[tuple[str, str]] = []
    for p in _iter_py(HSRL2):
        txt = _read(p)
        for m in re.finditer(r"^([A-Z][A-Z0-9_]{2,})\s*=\s*[\"']([a-z_]+)[\"']",
                            txt, re.M):
            consts.setdefault(m.group(1), m.group(2))
        for m in re.finditer(
                r"\.fire\(\s*[^,]+,\s*([\"'])([a-z_]+)\1", txt):
            fires.append((p.name, m.group(2)))
        for m in re.finditer(r"\.fire\(\s*[^,]+,\s*([A-Z][A-Z0-9_]{2,})\s*[,)]",
                             txt):
            fires.append((p.name, m.group(1)))
    fired: set[str] = set()
    for _where, token in fires:
        if token in consts:
            fired.add(consts[token])
        elif token.islower():
            fired.add(token)
    return fired


def _local_consts(txt: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r"^([A-Z][A-Z0-9_]{2,})\s*=\s*[\"']([a-z_]+)[\"']",
                         txt, re.M):
        out.setdefault(m.group(1), m.group(2))
    return out


# ══════════════ W3 私有属性读写扫描 ══════════════

_ATTR_ASSIGN = re.compile(r"\b(?:game|g|hero|h)\.(_[a-zA-Z]\w*)\s*=(?!=)")


def script_attr_assignments() -> dict[str, list[str]]:
    """脚本对 game/hero 写入的私有属性 → 出现的脚本文件。"""
    out: dict[str, list[str]] = defaultdict(list)
    for p in _iter_py(SCRIPTS):
        txt = _read(p)
        for m in _ATTR_ASSIGN.finditer(txt):
            out[m.group(1)].append(p.name)
    return out


def engine_attr_mentions() -> set[str]:
    """脚本目录之外的代码提到的全部私有属性名。"""
    mentions: set[str] = set()
    for p in _iter_py(HSRL2):
        if SCRIPTS in p.parents or p.parent == SCRIPTS:
            continue
        mentions.update(re.findall(r"\b(_[a-zA-Z]\w*)\b", _read(p)))
    return mentions


def script_attr_mentions() -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for p in _iter_py(SCRIPTS):
        for name in re.findall(r"\b(_[a-zA-Z]\w*)\b", _read(p)):
            counts[name] += 1
    return counts


# ══════════════ 主检查 ══════════════

def category_of(db, card_id: str) -> str:
    from hsrl2.tags import CardType
    from hsrl2.game import is_quest_card
    d = db.get(card_id)
    # 任务卡: **与引擎 `Game.quest_defs()` 同源**（`hsrl2.game.is_quest_card`
    # / `quest_defs_from_db`）。2026-09-18 对抗审查订正: 旧实现先按
    # tag 535 + id 含 quest 判一次，再 `startswith("BG24_Quest_")` 兜底 →
    # 把公告 token `BG24_Quest_Bob` 重新计为 quest（口径与
    # `audit_card_registry_v2._quest_defs` 的 id 正则**互异**: 后者含
    # `BG33_Anomaly_008_Quest`、前者含 Bob）。现两处共用唯一谓词。
    if is_quest_card(d):
        return "quest"
    if d is None:
        return "unknown"
    ct = d.card_type
    if ct == CardType.MINION:
        return "minion"
    if ct == CardType.SPELL:
        return "spell"
    if ct == CardType.HERO_POWER:
        return "hero_power"
    if ct == CardType.BACON_TRINKET:
        return "trinket"
    if ct == CardType.BACON_QUEST_REWARD:
        return "quest_reward"
    if ct == CardType.BACON_ANOMALY:
        return "anomaly"
    return f"other:{int(ct)}"


def check_hooks(db, registry) -> list[str]:
    errors: list[str] = []
    for card_id, cls in registry.items():
        cat = category_of(db, card_id)
        allowed = ALLOWED_HOOKS.get(cat)
        if allowed is None:
            continue
        defined = set()
        for node in cls.__dict__:
            if callable(getattr(cls, node, None)) or isinstance(
                    getattr(cls, node, None), property):
                defined.add(node)
        for dead in sorted((defined & CHECKED_HOOK_NAMES) - allowed):
            errors.append(
                f"W1 [{cat}] {card_id} {cls.__name__}: 定义了引擎不为此类"
                f"分发的钩子 {dead}()（{cat} 仅分发 {sorted(allowed)}）")
    return errors


def check_events() -> list[str]:
    fired = collect_fired_events()
    errors: list[str] = []
    for p in _iter_py(SCRIPTS):
        txt = _read(p)
        consts = _local_consts(txt)
        import hsrl2.events as E
        for k, v in vars(E).items():
            if isinstance(v, str) and k.isupper():
                consts.setdefault(k, v)
        # Listener(event="literal" | event=CONST, ...)
        for m in re.finditer(
                r"Listener\(\s*event\s*=\s*(?:([\"'])([a-z_]+)\1|"
                r"([A-Z][A-Z0-9_]{2,}))", txt):
            literal = m.group(2)
            token = m.group(3)
            if literal is None:
                literal = consts.get(token)
            if literal is None:
                continue   # 动态事件名——不判定
            if literal not in fired:
                errors.append(
                    f"W2 {p.name}: 监听事件 {literal!r}（引擎/脚本中无 "
                    f"fire 调用）→ 永不触发")
    return errors


def check_attrs() -> list[str]:
    engine = engine_attr_mentions()
    script_counts = script_attr_mentions()
    errors: list[str] = []
    for attr, files in sorted(script_attr_assignments().items()):
        if attr in engine:
            continue
        n_assign = len(files)
        if script_counts.get(attr, 0) <= n_assign:
            errors.append(
                f"W3 {sorted(set(files))}: 写入 {attr} 但脚本之外无任何读取 "
                f"→ 空转标记")
    return errors


def check_buff_class() -> list[str]:
    """W4: `x.add_buff(Buff(...))` 里的 Buff 必须是 entity.Buff（附魔），
    不能是 hsrl2.actions.Buff（Action——需要 target 且不接受 source_id）。

    2026-09-01 全对局压测命中 5 处（Onyxia 第二次 avenge、Wagtoggle、
    SellGiveStats 等），静态测试无法发现（只在特定触发路径崩溃）。
    """
    errors: list[str] = []
    for p in _iter_py(SCRIPTS):
        txt = _read(p)
        try:
            tree = ast.parse(txt)
        except SyntaxError:
            continue
        action_buff = entity_buff = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            mod = node.module or ""
            for a in node.names:
                if a.name != "Buff" or a.asname is not None:
                    continue
                if mod in ("hsrl2.actions", "hsrl2.actions.stats"):
                    action_buff = True
                elif mod == "hsrl2.entity":
                    entity_buff = True
        if not action_buff or entity_buff:
            continue
        for m in re.finditer(r"add_buff\(\s*Buff\(", txt):
            line = txt[:m.start()].count("\n") + 1
            errors.append(
                f"W4 {p.name}:{line}: add_buff(Buff(...)) 用的是 "
                f"actions.Buff（Action）——附魔应使用 entity.Buff")
    return errors


def check_imports() -> list[str]:
    """W5: `from <hsrl2 模块> import <符号>` 的符号必须真实存在。

    2026-09-01 审计命中: `give_gem`（batch_bloodgem 无此函数）、
    `_pool_spell_ids`（batch_spells1 无此符号）——两者都在 TURN_START
    才执行，回合直接 ImportError 崩溃。
    """
    import importlib
    errors: list[str] = []
    for p in _iter_py(SCRIPTS):
        txt = _read(p)
        try:
            tree = ast.parse(txt)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            mod = node.module or ""
            if not mod.startswith("hsrl2"):
                continue
            try:
                target = importlib.import_module(mod)
            except Exception as e:                       # noqa: BLE001
                errors.append(
                    f"W5 {p.name}:{node.lineno}: 无法导入模块 {mod}: {e}")
                continue
            for a in node.names:
                if a.name == "*":
                    continue
                if not hasattr(target, a.name):
                    # 允许导入子模块（from pkg import submodule）
                    try:
                        importlib.import_module(f"{mod}.{a.name}")
                        continue
                    except Exception:                    # noqa: BLE001
                        pass
                    errors.append(
                        f"W5 {p.name}:{node.lineno}: {mod} 无符号 "
                        f"{a.name!r} → 运行期 ImportError")
    return errors


def main() -> int:
    strict = "--strict" in sys.argv
    from hsrl2.db import CardDB
    from hsrl2.scripts import REGISTRY

    db = CardDB.load(ROOT / "data")
    hook_errs = check_hooks(db, REGISTRY)
    event_errs = check_events()
    attr_errs = check_attrs()
    buff_errs = check_buff_class()
    import_errs = check_imports()

    print(f"Registry entries: {len(REGISTRY)}")
    for title, errs in (("W1 死钩子（引擎不为此类分发）", hook_errs),
                        ("W2 死监听（事件从不 fire）", event_errs),
                        ("W3 空转标记（写入后无人读取）", attr_errs),
                        ("W4 Buff 类混淆（Action vs 附魔）", buff_errs),
                        ("W5 不存在的导入符号（运行期 ImportError）",
                         import_errs)):
        print(f"\n{title}: {len(errs)}")
        for e in errs[:60]:
            print(f"  [FAIL] {e}")
        if len(errs) > 60:
            print(f"  ... and {len(errs) - 60} more")

    total = (len(hook_errs) + len(event_errs) + len(attr_errs)
             + len(buff_errs) + len(import_errs))
    if total:
        print(f"\n接线审计失败: {total} 项")
        return 1 if strict else 0
    print("\nPASS: 全部脚本钩子/监听/标记/Buff 类/导入均有引擎接线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
