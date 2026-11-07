#!/usr/bin/env python3
"""Top2 阵容可视化：把模型打进前二的对局，终局阵容完整画出来。

口径（与 ``scripts/bot_strength_curves.py`` / 训练采集一致）：
  - 8 席，seat 0 = 模型（PPOSelfPlayPolicy，``opponent="bot"``、``behavior="net"``），
    seat 1..7 = 引擎 bot；``game_config_json()`` 同训练；无人类盘面注入。
  - 一局结束（模型死亡或吃鸡）时记录模型座位的名额、终局回合、tavern tier、血量、
    英雄、饰品，以及**按 position 顺序的完整阵容**（含金色/关键词/攻血）。
  - 同时记录"击败它的对手"（或最终冠军）的阵容，便于对照。

输出：
  - ``<out>.json``  原始数据（可复现）
  - ``<out>.png``   可视化表格（每行 = 一局前二，每格 = 一个随从卡）
  - ``<out>.html``  同一份可视化的网页版（更宽的卡面，可放大查看）

用法：
  PYTHONPATH=rust/python:. python scripts/top2_lineups.py \
    --checkpoint runs/az_stage300m_b07/eval/ckpt_110074614.pt \
    --device cuda:7 --games 64 --topk 2 --max-rows 8 --out runs/lineups/b07_110m_top2
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))

import hsbg_engine as E  # noqa: E402

from hsbg.az.train.game_rules import game_config_json  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy  # noqa: E402
from hsbg.env.obs_std import KEYWORD_NAMES, RACE_NAMES  # noqa: E402

MODEL_SEAT = 0

# 关键词位（与 rust Kw::NAMES 顺序一致）
_KW_SHORT = {"TAUNT": "嘲讽", "DIVINE_SHIELD": "圣盾", "WINDFURY": "风怒",
             "REBORN": "复生", "VENOMOUS": "剧毒", "POISONOUS": "剧毒",
             "STEALTH": "潜行", "MAGNETIC": "磁力", "MEGA_WINDFURY": "超级风怒",
             "CLEAVE": "顺劈", "IMMUNE": "免疫", "IMMUNE_ATTACKING": "攻击免疫"}


def _cn(card_id: int) -> str:
    """卡名（中文）；未知 id 回退英文/编号。"""
    try:
        info = E.card_info(int(card_id) + 1)
    except Exception:  # noqa: BLE001
        return f"#{card_id}"
    if not info:
        return f"#{card_id}"
    cid, en, zh, _tier = info
    return zh or en or str(cid)


def _tier(card_id: int) -> int:
    try:
        info = E.card_info(int(card_id) + 1)
    except Exception:  # noqa: BLE001
        return 0
    return int(info[3]) if info else 0


def _kw_list(bits: int) -> list:
    out = []
    for i, name in enumerate(KEYWORD_NAMES):
        if bits & (1 << i):
            out.append(_KW_SHORT.get(name, name))
    return out


def _races(mask: int) -> list:
    out = []
    for i, name in enumerate(RACE_NAMES):
        if mask & (1 << i):
            out.append(name[:4].title())
    return out


def _unit(m: dict) -> dict:
    card = int(m.get("card") or 0)
    return {
        "card": card,
        "name": _cn(card),
        "tier": _tier(card),
        "atk": int(m.get("atk") or 0),
        "hp": int(m.get("hp") or 0),
        "max_hp": int(m.get("max_hp") or 0),
        "golden": bool(m.get("golden")),
        "kw": _kw_list(int(m.get("kw") or 0) | int(m.get("bonus_kw") or 0)),
        "races": _races(int(m.get("races") or 0)),
        "attached": [_cn(int(a.get("card") if isinstance(a, dict) else a))
                     for a in (m.get("attached") or [])],
        "pbonus": [int(m.get("pbonus_atk") or 0), int(m.get("pbonus_hp") or 0)],
    }


def _seat_view(game, seat: int) -> dict:
    pj = json.loads(game.player_json(int(seat)))
    board = [_unit(m) for m in (pj.get("board") or [])]
    return {
        "seat": int(seat),
        "placement": int(pj.get("placement") or 0),
        "alive": bool(pj.get("alive", True)),
        "tier": int(pj.get("tier") or 0),
        "health": int(pj.get("health") or 0),
        "gold": int(pj.get("gold") or 0),
        "hero": _cn(int(pj.get("hero") or 0)),
        "trinkets": [_cn(int(t)) for t in (pj.get("trinkets") or []) if int(t) > 0],
        "board": board,
        "strength": sum(u["atk"] + u["hp"] for u in board),
    }


def play_one(seed: int, policy, max_steps: int = 20000) -> dict:
    game = E.Game(int(seed), game_config_json())
    policy.reset()
    steps = 0
    model_died_turn = None
    while not game.is_over() and steps < max_steps:
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p == MODEL_SEAT:
                if model_died_turn is None and not bool(
                        json.loads(game.player_json(MODEL_SEAT)).get("alive", True)):
                    model_died_turn = int(game.turn)
                a = int(policy.decide(game, MODEL_SEAT).action)
                game.step(MODEL_SEAT, a)
            else:
                game.bot_play(p)
        if not acted and not game.is_over():
            break
    placements = [int(x) for x in game.placements()]
    me = _seat_view(game, MODEL_SEAT)
    # 对手：最终冠军；若模型不是冠军，再记"最后击败它的对手"
    champion_seat = placements.index(1)
    champion = _seat_view(game, champion_seat) if champion_seat != MODEL_SEAT else None
    killer = None
    try:
        pj = json.loads(game.player_json(MODEL_SEAT))
        last_opp = int(pj.get("last_opponent") or -1)
        if 0 <= last_opp < 8 and last_opp != MODEL_SEAT:
            killer = _seat_view(game, last_opp)
    except Exception:  # noqa: BLE001
        pass
    return {
        "seed": int(seed),
        "ok": bool(game.is_over()),
        "steps": int(steps),
        "final_turn": int(game.turn),
        "placements": placements,
        "model": me,
        "champion": champion,
        "killer": killer,
        "model_died_turn": model_died_turn,
    }


# ------------------------------------------------------------------ 渲染
def _tile_text(u: dict, idx: int) -> str:
    star = "★" if u["golden"] else ""
    kw = ("·" + "/".join(u["kw"])) if u["kw"] else ""
    return f"{idx}. {u['name']}{star}  {u['atk']}/{u['hp']}{kw}"


_CJK_CANDIDATES = (
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-DemiLight.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)


def _setup_cjk_font() -> str:
    """给 matplotlib 找一个中文字体（否则中文全是方块）。"""
    import matplotlib
    from matplotlib import font_manager as fm
    names = {f.name for f in fm.fontManager.ttflist}
    for name in ("Noto Sans CJK SC", "Noto Sans CJK JP", "Droid Sans Fallback",
                 "WenQuanYi Zen Hei", "WenQuanYi Micro Hei"):
        if name in names:
            matplotlib.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return name
    for path in _CJK_CANDIDATES:
        if os.path.exists(path):
            try:
                fm.fontManager.addfont(path)
                name = fm.FontProperties(fname=path).get_name()
                matplotlib.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
                matplotlib.rcParams["axes.unicode_minus"] = False
                return name
            except Exception:  # noqa: BLE001
                continue
    return ""


def render_png(rows: list, path: str, title: str) -> None:
    import matplotlib
    _setup_cjk_font()
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    n = max(1, len(rows))
    ncol = 7
    fig_w = 2.05 * ncol + 5.2
    fig_h = 1.35 * n + 0.9
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, ncol * 2.05 + 4.9)
    ax.set_ylim(-0.4, n * 1.35 + 0.5)
    ax.axis("off")
    ax.set_title(title, fontsize=12, pad=10)

    for r, g in enumerate(rows):
        y = (n - 1 - r) * 1.35
        m = g["model"]
        head = (f"#{g['seed'] % 100000:05d}  第{m['placement']}名  "
                f"t{g['final_turn']}  {m['tier']}本  血量{m['health']}  "
                f"强度{m['strength']}")
        ax.text(0.05, y + 1.02, head, fontsize=9, va="bottom", ha="left")
        sub = "英雄：" + m["hero"]
        if m["trinkets"]:
            sub += "   饰品：" + " / ".join(m["trinkets"])
        ax.text(0.05, y + 0.12, sub, fontsize=7.5, va="bottom", ha="left", color="#333333")
        for i, u in enumerate(m["board"][:ncol]):
            x = 4.9 + i * 1.98
            gold = u["golden"]
            face = "#ffe9a8" if gold else "#eef3fb"
            ax.add_patch(FancyBboxPatch((x, y + 0.08), 1.85, 1.06,
                                        boxstyle="round,pad=0.02,rounding_size=0.08",
                                        linewidth=1.0,
                                        edgecolor="#c9a227" if gold else "#7f9cc0",
                                        facecolor=face))
            ax.text(x + 0.09, y + 0.88, u["name"][:9], fontsize=8, va="bottom")
            ax.text(x + 0.09, y + 0.62, f"{u['atk']}/{u['hp']}", fontsize=10.5,
                    va="bottom", fontweight="bold")
            ax.text(x + 0.09, y + 0.36, ("T%d" % u["tier"]) + ("  ★" if gold else ""),
                    fontsize=7, va="bottom", color="#666666")
            if u["kw"]:
                ax.text(x + 0.09, y + 0.13, "/".join(u["kw"])[:14], fontsize=6.5,
                        va="bottom", color="#8a3b3b")

    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def render_html(rows: list, path: str, title: str) -> None:
    def tiles(board):
        out = []
        for i, u in enumerate(board, 1):
            cls = "card golden" if u["golden"] else "card"
            kw = f'<div class="kw">{" · ".join(u["kw"])}</div>' if u["kw"] else ""
            att = (f'<div class="att">+{", ".join(u["attached"])}</div>'
                   if u["attached"] else "")
            out.append(
                f'<div class="{cls}"><div class="nm">{i}. {u["name"]}</div>'
                f'<div class="st">{u["atk"]}/{u["hp"]}</div>'
                f'<div class="t">T{u["tier"]}{" ★" if u["golden"] else ""}</div>'
                f'{kw}{att}</div>')
        return "".join(out)

    body = []
    for g in rows:
        m = g["model"]
        opp = g["champion"] if m["placement"] != 1 else g.get("killer")
        opp_html = ""
        if opp:
            opp_html = (
                f'<div class="opp"><h4>对手（第{opp["placement"]}名 · {opp["hero"]} · '
                f'{opp["tier"]}本 · 强度{opp["strength"]}）</h4>'
                f'<div class="row">{tiles(opp["board"])}</div></div>')
        body.append(f"""
    <section>
      <h3>种子 {g['seed']} · 第 {m['placement']} 名 · 终局 t{g['final_turn']} ·
          {m['tier']} 本 · 血量 {m['health']} · 强度 {m['strength']}</h3>
      <div class="meta">英雄：{m['hero']}　饰品：{' / '.join(m['trinkets']) or '—'}</div>
      <div class="row">{tiles(m['board'])}</div>
      {opp_html}
    </section>""")

    html = f"""<!doctype html><meta charset="utf-8"><title>{title}</title>
<style>
 body {{ font-family: -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
        background:#f6f7f9; color:#1c1f23; margin:18px; }}
 h1 {{ font-size:18px; }} h3 {{ font-size:13px; margin:14px 0 4px; }}
 h4 {{ font-size:12px; margin:8px 0 4px; color:#555; }}
 section {{ background:#fff; border:1px solid #e3e6ea; border-radius:10px;
            padding:10px 12px; margin-bottom:12px; }}
 .meta {{ font-size:12px; color:#555; margin-bottom:8px; }}
 .row {{ display:flex; flex-wrap:wrap; gap:8px; }}
 .card {{ width:118px; border:1px solid #8aa4c8; border-radius:9px; padding:6px 7px;
          background:#eef3fb; }}
 .card.golden {{ border-color:#c9a227; background:#ffe9a8; }}
 .nm {{ font-size:12px; font-weight:600; line-height:1.25; }}
 .st {{ font-size:16px; font-weight:700; }}
 .t  {{ font-size:11px; color:#666; }}
 .kw {{ font-size:10px; color:#8a3b3b; }}
 .att {{ font-size:10px; color:#2f6b3a; }}
 .opp .card {{ background:#f2f2f2; border-color:#bbb; }}
</style>
<h1>{title}</h1>
<p style="font-size:12px;color:#666">口径：8 席，seat 0 = 模型，其余 7 席引擎 bot；
无人类盘面注入；金色=★；右上角为攻/血。</p>
{''.join(body)}
"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--device", default="cuda:1")
    ap.add_argument("--games", type=int, default=64)
    ap.add_argument("--seed-base", type=int, default=840000)
    ap.add_argument("--topk", type=int, default=2, help="只展示名次 <= topk 的对局")
    ap.add_argument("--max-rows", type=int, default=8)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--from-json", default="", help="跳过对局，直接从已有 json 重渲染")
    ap.add_argument("--out", default="runs/lineups/ckpt_top2")
    args = ap.parse_args(argv)

    if args.from_json:
        d = json.load(open(args.from_json, encoding="utf-8"))
        rows = d.get("rows") or []
        title = (f"{os.path.basename(args.checkpoint)}  top{args.topk} 阵容 "
                 f"（{d.get('games')} 局中 {len(rows)} 局进前{args.topk}）")
        render_png(rows, args.out + ".png", title)
        render_html(rows, args.out + ".html", title)
        print(f"[out] {args.out}.png\n[out] {args.out}.html")
        return 0

    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    ev = PPOEvaluator(model, device=args.device,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=int(args.seed_base), opponent="bot", behavior="net",
                        max_steps=int(args.max_steps), move_guard=True,
                        move_cap=3, move_repeat_limit=2)
    policy = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=ev,
                               seed=int(args.seed_base), move_model=False)

    games = []
    for i in range(int(args.games)):
        g = play_one(int(args.seed_base) + i, policy, max_steps=int(args.max_steps))
        games.append(g)
        if (i + 1) % 8 == 0:
            print(f"[lineups] {i + 1}/{args.games}  "
                  f"top{args.topk}={sum(1 for x in games if 0 < x['model']['placement'] <= args.topk)}",
                  flush=True)

    picked = [g for g in games
              if 0 < int(g["model"]["placement"]) <= int(args.topk)]
    picked.sort(key=lambda g: (g["model"]["placement"], -g["model"]["strength"]))
    rows = picked[: int(args.max_rows)]
    counts = {}
    for g in games:
        counts[int(g["model"]["placement"])] = counts.get(int(g["model"]["placement"]), 0) + 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    out_json = args.out + ".json"
    json.dump({"checkpoint": args.checkpoint, "games": args.games, "topk": args.topk,
               "placement_counts": counts, "rows": rows, "all": games},
              open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    title = (f"{os.path.basename(args.checkpoint)}  top{args.topk} 阵容 "
             f"（{args.games} 局中 {len(picked)} 局进前{args.topk}）")
    render_png(rows, args.out + ".png", title)
    render_html(rows, args.out + ".html", title)

    print(f"[lineups] placement_counts={counts}")
    for g in rows:
        m = g["model"]
        names = " / ".join(f"{u['name']}{'★' if u['golden'] else ''} {u['atk']}/{u['hp']}"
                           for u in m["board"])
        print(f"  seed={g['seed']} 第{m['placement']}名 t{g['final_turn']} "
              f"{m['tier']}本 强度{m['strength']} | {names}")
    print(f"[out] {out_json}\n[out] {args.out}.png\n[out] {args.out}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
