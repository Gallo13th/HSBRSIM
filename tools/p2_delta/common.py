"""P2-C 内容移植缺口分析 —— 公共工具。

本模块只做**只读**数据装载与文本规范化，供
``extract_at_content.py`` / ``compare_37.py`` / ``probe_ops.py`` 复用。

口径（重要，写进 docs/PORTING_37_PLAN.md）:
  1. AutoTavern 侧“已实现” = ① ``content/*.rs`` 的 ``scripts()`` 里注册了
     card id（scripted），或 ② 卡面文本在去掉关键词后为空（keyword-only，
     复刻上游 ``crates/taverngym/src/script.rs::implemented_uncached``）。
  2. 37.0.0 侧“现有卡”集合一律来自 `data/bg_*.json`（官方数据升级产物，
     patch 37.0.0.255130），池子集合用 ``is_pool_minion`` / ``is_pool_spell``
     等标志，不按 id 前缀猜。
  3. 37 数据 ``text`` 字段可能含 ``@``：上游 CardDefs 对同一 card id 存了
     第二段文本（Duos 模式变体；证据：仅 37 新卡出现 "or Pass" 且只出现在
     ``@`` 之后的一段，AutoTavern 的 ``tools/gen_carddb.py`` 与 hsrl2 的
     F-08 裁定都只取第一段）。本工具统一取 ``text.split('@')[0]``。
  4. 卡面文本比较前先做**标记规范化**：去 ``[x]``/HTML 标签/换行、
     折叠空白、小写；``{0}``..``{5}`` 视为数值占位符。

所有输出 JSON 均为确定性（无时间戳、固定排序），可逐字节复算。
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# ── 路径 ──────────────────────────────────────────────────────────────
TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent.parent
DATA_DIR = REPO_ROOT / "data"
HSRL2_SCRIPTS_DIR = REPO_ROOT / "hsrl2" / "scripts"
RUNS_DIR = REPO_ROOT / "runs" / "p2_delta"

#: AutoTavern 参照仓库（Task 指定路径；可用环境变量覆盖）。
DEFAULT_AT_ROOT = Path("/Users/letiangao/HSAgent/repos/AutoTavern")

MARKUP_RE = re.compile(r"<[^>]+>")
PLACEHOLDER_RE = re.compile(r"\{\d+\}")
NUM_RE = re.compile(r"\d+")
WS_RE = re.compile(r"\s+")
CARD_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def at_root(cli_value: Optional[str] = None) -> Path:
    """AutoTavern 仓库根目录（只读）。"""
    import os

    if cli_value:
        return Path(cli_value).resolve()
    env = os.environ.get("P2_AT_ROOT")
    if env:
        return Path(env).resolve()
    return DEFAULT_AT_ROOT


# ── JSON ─────────────────────────────────────────────────────────────
def read_json(path: Path | str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path | str, obj: Any) -> None:
    """确定性写出：sort_keys + 固定缩进 + UTF-8 + 末尾换行。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def sha256_of(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 文本规范化 ────────────────────────────────────────────────────────
_WORD_RE = re.compile(r"[a-z]{3,}")


def solo_text(text: Optional[str]) -> str:
    """37 数据 text → 单人模式文本。

    ``@`` 在 37 数据里两种用途（见模块 docstring 口径 3）：
      1. **动态数值占位符**：如 "( Gold left!)" / "Tier  minion"——前后两段是
         同一句话被数字占位符切开，拼起来（把 ``@`` 记作 ``#``）；
      2. **Duos 文本变体分隔符**：``@`` 后是第二段完整文本（目前仅 5 个 37 新卡
         带 "or Pass" 变体）——取第一段。
    判别：两段词集 Jaccard ≥ 0.5 视为变体（取第一段），否则视为占位符拼接。
    """
    if not text:
        return ""
    if "@" not in text:
        return text
    seg1, seg2 = text.split("@", 1)
    w1 = set(_WORD_RE.findall(seg1.lower()))
    w2 = set(_WORD_RE.findall(seg2.lower()))
    if len(w1) >= 3 and len(w2) >= 3:
        jac = len(w1 & w2) / len(w1 | w2)
        if jac >= 0.5:
            return seg1
    return seg1 + "#" + seg2


PUNCT_RE = re.compile(r"[^a-z0-9+#/ ]")
#: 37 复数/变体标记 ``|4(Gem,Gems)`` → 取复数形式（AT 数据里就是复数）
PLURAL_RE = re.compile(r"_?\|\d+\(([^,()]+),([^()]*)\)")
#: 动态计数器 ``(2 left!)`` / ``(# left!)``：显示态，不是效果数值
COUNTER_RE = re.compile(r"\(\s*[#\d]+[^()]*?left!\)", re.I)


def pre_clean(text: Optional[str]) -> str:
    """比较前清洗：展开复数标记、去掉动态计数器。"""
    if not text:
        return ""
    t = PLURAL_RE.sub(lambda m: m.group(2), text)
    t = COUNTER_RE.sub("", t)
    return t


def normalize_text(text: Optional[str]) -> str:
    """去标记/标点后的小写文本（用于跨版本卡面比较）。

    37 数据文本用 ``{0}``..``{4}`` 占位 ``script_data_num_1..5``；AT 文本直接写
    数字。调用方若已把占位符替换成数值，这里只保留数字；未替换的占位符统一
    记作 ``#``（结构比较用）。
    """
    if not text:
        return ""
    t = solo_text(text).replace("[x]", "")
    t = pre_clean(t)
    t = MARKUP_RE.sub("", t)
    t = t.replace("_", " ")  # 37 数据里 "extra_minion" 是分词占位下划线
    t = t.lower()
    t = t.replace("-", " ")  # AT 的 "left- most" 与 37 的 "left-most" 归一
    t = PLACEHOLDER_RE.sub("#", t)  # 未解析的 {n} → 数值占位符
    t = PUNCT_RE.sub(" ", t)
    return WS_RE.sub(" ", t).strip()


def resolve_text_numbers(text: Optional[str], nums: Sequence[Optional[int]]) -> str:
    """把 37 文本里的 ``{i}`` 用 ``script_data_num_{i+1}`` 还原成数字。"""
    if not text:
        return ""
    t = text

    def repl(m: "re.Match[str]") -> str:
        idx = int(m.group(0)[1:-1])
        val = nums[idx] if idx < len(nums) else None
        return str(val) if val is not None else m.group(0)

    return PLACEHOLDER_RE.sub(repl, t)


def ds37_nums(card: Dict[str, Any]) -> List[Optional[int]]:
    return [card.get(f"script_data_num_{i}") for i in range(1, 6)]


KEYWORDS = (
    "Divine Shield",
    "Taunt",
    "Reborn",
    "Windfury",
    "Venomous",
    "Stealth",
    "Magnetic",
)


def keyword_only(text: Optional[str]) -> bool:
    """复刻 AutoTavern ``implemented_uncached`` 的 keyword-only 判定。

    原文（``crates/taverngym/src/script.rs``）: 去掉 6 个关键词与 ``,.\\ ``以及
    空格后为空即“纯关键词随从”。这里对 37 数据先做标记规范化（去 HTML/[x]）。
    """
    if not text:
        return True
    t = solo_text(text).replace("[x]", "")
    t = MARKUP_RE.sub("", t)
    for kw in KEYWORDS:
        t = t.replace(kw, "")
    t = re.sub(r"[,.\s]", "", t)
    return t == ""


# ── 数值抽取 ──────────────────────────────────────────────────────────
def numbers_of(text: Optional[str]) -> List[int]:
    """文本中按出现顺序的数字（未解析的 ``{n}`` 占位符不算数字）。"""
    t = PLACEHOLDER_RE.sub("", solo_text(text))
    return [int(x) for x in NUM_RE.findall(t)]


def plural_variants(text: Optional[str]) -> List[str]:
    """37 复数标记 ``|4(sing, plur)`` 的两种展开（无标记则原样）。"""
    if not text or not PLURAL_RE.search(text):
        return [text or ""]
    return [
        PLURAL_RE.sub(lambda m: m.group(1), text),
        PLURAL_RE.sub(lambda m: m.group(2), text),
    ]


def compare_texts(
    text_a: Optional[str],
    text_b: Optional[str],
    nums_b: Optional[Sequence[Optional[int]]] = None,
) -> Dict[str, Any]:
    """跨版本卡面文本比较（含 37 复数标记两种展开）。

    返回 ``{text_same, structure_same, numbers_state, resolved_b}``。
    """
    base = resolve_text_numbers(text_b, nums_b) if nums_b else (text_b or "")
    variants = plural_variants(base)
    norm_a = normalize_text(text_a)
    text_same = any(normalize_text(v) == norm_a for v in variants)
    structure_a = NUM_RE.sub("#", norm_a)
    structure_same = any(NUM_RE.sub("#", normalize_text(v)) == structure_a for v in variants)
    # 未解析占位符：{n} 残留 / `@` 动态数值
    unresolved = any(bool(PLACEHOLDER_RE.search(v)) or "@" in v for v in variants)
    numbers_state = "same"
    if numbers_of(pre_clean(text_a)) != numbers_of(pre_clean(variants[-1])):
        numbers_state = "unverified" if unresolved else "changed"
    return {
        "text_same": text_same,
        "structure_same": structure_same,
        "numbers_state": numbers_state,
        "unresolved_placeholders": unresolved,
        "resolved_b": variants[-1],
        "resolved_b_singular": variants[0],
    }


def number_comparison(
    text_a: Optional[str],
    text_b: Optional[str],
    nums_b: Optional[Sequence[Optional[int]]] = None,
) -> Dict[str, Any]:
    """跨版本卡面文本比较（结构 / 数字 / 占位符可解性）。

    * structure_same = 数字替换为 ``#`` 后规范化文本相等；
    * numbers_state: ``same`` / ``changed``（37 占位符全部可解且数字不同）/
      ``unverified``（37 有解不出的占位符，无法断言数字是否变化）。
    """
    raw_b = text_b or ""
    resolved = resolve_text_numbers(raw_b, nums_b) if nums_b else raw_b
    structure_same = NUM_RE.sub("#", normalize_text(text_a)) == NUM_RE.sub(
        "#", normalize_text(text_b)
    )
    # 未解析占位符：{n} 残留、`@` 动态数值、`#` 占位
    unresolved = bool(PLACEHOLDER_RE.search(resolved)) or "@" in resolved
    numbers_state = "same"
    if numbers_of(pre_clean(text_a)) != numbers_of(pre_clean(resolved)):
        numbers_state = "unverified" if unresolved else "changed"
    return {
        "structure_same": structure_same,
        "numbers_state": numbers_state,
        "unresolved_placeholders": unresolved,
        "resolved_b": resolved,
    }


# ── 37 卡面能力标志（数据 flag + 文本触发词） ─────────────────────────
#: 数据字段已给出的钩子标志 → AT Script hook 名
DATA_FLAG_HOOKS = {
    "battlecry": "battlecry",
    "deathrattle": "deathrattle",
    "start_of_combat": "start_of_combat",
    "rally": "rally",
    "avenge": "avenge",
    "activate": "activate",
    "choose_one": "choose_one",
    "magnetic": "magnetic",
}

#: 文本触发词 → hook 家族（只在数据 flag 缺失时用作补充）
TEXT_HOOK_MARKERS: Sequence[Tuple[str, str]] = (
    ("Battlecry", "battlecry"),
    ("Deathrattle", "deathrattle"),
    ("Start of Combat", "start_of_combat"),
    ("Rally", "rally"),
    ("Avenge", "avenge"),
    ("Activate", "activate"),
    ("Choose One", "choose_one"),
    ("Spellcraft", "spellcraft"),
    ("At the end of your turn", "end_of_turn"),
    ("At the start of your turn", "start_of_turn"),
    ("When you sell this", "on_sell"),
    ("Whenever", "on_event"),
    ("After you", "on_event"),
    ("After a friendly", "on_event"),
    ("After this attacks", "after_attack"),
    ("When your Deity awakens", "deity_awakened"),
)


def hook_families(card: Dict[str, Any]) -> List[str]:
    """由数据 flag + 文本触发词推断该卡需要的效果钩子家族（确定性）。"""
    text = solo_text(card.get("text"))
    hooks: Set[str] = set()
    for flag, hook in DATA_FLAG_HOOKS.items():
        if card.get(flag):
            hooks.add(hook)
    for marker, hook in TEXT_HOOK_MARKERS:
        if marker in text:
            hooks.add(hook)
    return sorted(hooks)


#: 「AT 无对应原语」候选系统词（用于跨引擎原语对照；命中即标注）
#: 说明：Deity/discard/Buddy/Quest/Timewarp/Trinket/Spellcraft/Aberration
#: 在 AT 36.6.3 引擎里都有系统实现（见 docs/PORTING_37_PLAN.md §4 对照表），
#: 这里只保留经源码核实**确实不存在**的系统词。
AT_MISSING_SYSTEM_WORDS: Sequence[Tuple[str, str]] = (
    ("Anomaly", "AT 无 anomaly 系统（grep crates/taverngym/src 0 命中）"),
)


def at_missing_primitives(card: Dict[str, Any]) -> List[str]:
    text = solo_text(card.get("text"))
    out: List[str] = []
    for word, why in AT_MISSING_SYSTEM_WORDS:
        if word in text:
            out.append(f"{word}: {why}")
    return out


# ── 37 数据装载 ───────────────────────────────────────────────────────
#: 37 数据 card_race 数值 → 种族名（与 hsrl2/tags.py Race 枚举一致）
RACE_CODE = {
    11: "UNDEAD",
    14: "MURLOC",
    15: "DEMON",
    17: "MECHANICAL",
    18: "ELEMENTAL",
    20: "BEAST",
    23: "PIRATE",
    24: "DRAGON",
    26: "ALL",
    43: "QUILBOAR",
    92: "NAGA",
    126: "ABERRATION",
}


def race_name(code: Optional[int]) -> str:
    if code is None:
        return "NONE"
    return RACE_CODE.get(int(code), f"UNKNOWN_{code}")


def ds37_races(card: Dict[str, Any]) -> List[str]:
    """37 卡的种族集合：主类型 card_race ∪ race_tags（多类型随从的第二/第三类型）。"""
    out: Set[str] = set()
    if card.get("card_race") is not None:
        r = race_name(card.get("card_race"))
        if r != "NONE":
            out.add(r)
    for tag in card.get("race_tags") or []:
        if isinstance(tag, str):
            out.add("MECHANICAL" if tag == "MECH" else tag)
    return sorted(out)


def load_ds37() -> Dict[str, Any]:
    """装载 37.0.0 全部 data/bg_*.json 并建立索引。"""
    fnames = (
        "bg_cards",
        "bg_pool_minions",
        "bg_pool_spells",
        "bg_tavern_spells",
        "bg_heroes",
        "bg_hero_powers",
        "bg_trinkets",
        "bg_quest_rewards",
        "bg_dark_gifts",
        "bg_anomalies",
    )
    raw = {name: read_json(DATA_DIR / f"{name}.json") for name in fnames}
    by_id: Dict[str, Dict[str, Any]] = {}
    source: Dict[str, List[str]] = {}
    for name, arr in raw.items():
        for card in arr:
            cid = card["id"]
            if cid not in by_id:
                by_id[cid] = dict(card)
            else:
                # 合并：bg_cards 是主表，专用文件（池/英雄技能/饰品）补齐其缺失字段
                for k, v in card.items():
                    if k not in by_id[cid] or by_id[cid][k] is None:
                        by_id[cid][k] = v
            source.setdefault(cid, []).append(name)
    summary = {}
    if (DATA_DIR / "bg_summary.json").exists():
        summary = read_json(DATA_DIR / "bg_summary.json")
    return {
        "raw": raw,
        "by_id": by_id,
        "source": source,
        "summary": summary,
    }


def is_golden_like(cid: str) -> bool:
    """37 数据里的金色/升级变体 id（用于“卡面本体”集合归一）。"""
    return "_G" in cid or cid.endswith("t") and "_t" in cid


def normal_form(cid: str) -> str:
    """把 ``_G`` / ``_Gt`` / ``_t`` 变体归一到本体 id（尽力而为）。"""
    if cid.endswith("_Gt"):
        return cid[: -len("_Gt")] + "t"
    if cid.endswith("_G"):
        return cid[: -len("_G")]
    return cid


# ── hsrl2 侧参考：REGISTRY + id→脚本文件映射 ─────────────────────────
def _load_registry_ids() -> Tuple[Optional[Set[str]], Optional[str]]:
    """运行时导入 hsrl2.scripts.REGISTRY（唯一权威口径）；失败时降级。"""
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from hsrl2.scripts import REGISTRY  # type: ignore

        return set(REGISTRY), None
    except Exception as exc:  # pragma: no cover - 依赖缺失时降级
        return None, f"{type(exc).__name__}: {exc}"


def load_hsrl2_registry() -> Tuple[Optional[Set[str]], Dict[str, List[str]], Optional[str]]:
    """返回 (REGISTRY id 集合, id→脚本文件列表, 错误信息)。

    REGISTRY 由运行时导入得到（权威）；文件映射用 AST 静态解析
    ``hsrl2/scripts/**/*.py`` 的卡 id 字面量/模块常量/注册元组。
    """
    ids, err = _load_registry_ids()
    files = map_hsrl2_files()
    return ids, files, err


def _py_files() -> List[Path]:
    if not HSRL2_SCRIPTS_DIR.exists():
        return []
    return sorted(p for p in HSRL2_SCRIPTS_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _module_string_constants(tree: ast.Module) -> Dict[str, str]:
    consts: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    consts[tgt.id] = node.value.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                consts[node.target.id] = node.value.value
    return consts


def _resolve(node: ast.AST, consts: Dict[str, str]) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def map_hsrl2_files() -> Dict[str, List[str]]:
    """card_id → 注册/定义它的 hsrl2 脚本文件（相对仓库路径，排序稳定）。

    方法：
      1. AST 解析每个文件的模块级字符串常量；
      2. 收集 ``register("ID", cls)`` / ``reg(ID, cls)`` 调用的首参；
      3. 收集 ``(ID 或 常量, Class)`` 二元组（batch 文件的 ``pairs`` 表）；
      4. 兜底：对仍未映射的 REGISTRY id 做逐文件字面量扫描（罕见路径）。
    """
    id_to_files: Dict[str, Set[str]] = {}

    def add(cid: Optional[str], path: Path) -> None:
        if not cid or not CARD_ID_RE.match(cid):
            return
        id_to_files.setdefault(cid, set()).add(str(path.relative_to(REPO_ROOT)))

    file_consts: Dict[Path, Dict[str, str]] = {}
    trees: Dict[Path, ast.Module] = {}
    for path in _py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        trees[path] = tree
        consts = _module_string_constants(tree)
        file_consts[path] = consts
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else (
                    fn.attr if isinstance(fn, ast.Attribute) else None
                )
                if name in {"register", "reg"} and node.args:
                    add(_resolve(node.args[0], consts), path)
        # 二元组 (id, Class)：batch 文件的 pairs 表 / 直接注册表
        for node in ast.walk(tree):
            if isinstance(node, ast.Tuple) and len(node.elts) == 2:
                first = _resolve(node.elts[0], consts)
                second = node.elts[1]
                if first and isinstance(second, (ast.Name, ast.Attribute, ast.Call)):
                    add(first, path)

    ids, _ = _load_registry_ids()
    if ids:
        missing = sorted(cid for cid in ids if cid not in id_to_files)
        if missing:
            # 兜底：单次遍历所有文件内容做字面量匹配（仅对缺失 id）
            wanted = set(missing)
            pat = re.compile(r"[\"']([A-Za-z][A-Za-z0-9_]*)[\"']")
            for path in _py_files():
                text = path.read_text(encoding="utf-8", errors="ignore")
                for hit in pat.findall(text):
                    if hit in wanted:
                        add(hit, path)
    return {cid: sorted(files) for cid, files in sorted(id_to_files.items())}


# ── AT 侧数据装载 ─────────────────────────────────────────────────────
def load_at_cards(at: Path) -> Dict[str, Any]:
    path = at / "crates" / "taverngym" / "data" / "cards.json"
    data = read_json(path)
    cards = {c["id"]: c for c in data["cards"]}
    return {"path": str(path), "meta": data.get("meta", {}), "cards": cards}
