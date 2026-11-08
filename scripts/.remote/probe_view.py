#!/usr/bin/env python3
"""探测 view(0) 的 pending / shop / board 结构，以及可在脚本里用的动作位。"""
import json, sys, time
sys.path.insert(0, '/home/data/users/gaoletian/projects/HSBRSIM')
import numpy as np
import hsbg_engine as E
from hsbg.az import env_api as EA
from hsbg.az.train.common import mask_from_bytes

A_END, A_REFRESH, A_FREEZE, A_UPGRADE, A_HERO_POWER = 0, 1, 2, 3, 4
A_BUY, A_SELL, A_ACTIVATE, A_CHOOSE, A_PLAY, A_MAGNETIZE, A_MOVE = 8, 16, 23, 30, 46, 126, 196
N_CHOICE, N_SHOP, N_POS, N_BOARD = 16, 8, 8, 7

g = E.Game(4242)
EA.finish_hero_select(g)
pend_seen = 0
view0 = None
spells_played = 0
while not g.is_over() and int(g.turn) <= 12:
    t = int(g.turn)
    for p in range(8):
        if g.is_over():
            break
        if not g.needs_action(p):
            continue
        if p != 0:
            g.bot_play(p)
            continue
        m = mask_from_bytes(g.legal_mask(0))
        v = json.loads(g.view(0))
        me = v.get('me') or {}
        if t == 4 and view0 is None:
            view0 = v
        if m[A_CHOOSE:A_CHOOSE + N_CHOICE].any() and pend_seen < 25:
            pend = me.get('pending')
            print(f'[pend t{t}] kind={ (pend[0] if isinstance(pend,list) else pend) }')
            print('   raw:', json.dumps(pend, ensure_ascii=False)[:900])
            pend_seen += 1
        # 策略：买得起就买，能打就打（法术优先），否则刷新/结束
        a = None
        if m[A_CHOOSE:A_CHOOSE + N_CHOICE].any():
            a = A_CHOOSE + int(np.flatnonzero(m[A_CHOOSE:A_CHOOSE + N_CHOICE])[0])
        else:
            shop = me.get('shop') or []
            hand = [h for h in (me.get('hand') or [])]
            gold = int(me.get('gold') or 0)
            # 法术优先打
            for h, it in enumerate(hand):
                if it.get('type') != 'minion' and gold >= 0:
                    for pos in range(8):
                        if m[A_PLAY + h * N_POS + pos]:
                            a = A_PLAY + h * N_POS + pos
                            spells_played += 1
                            break
                if a is not None:
                    break
            if a is None and len(me.get('board') or []) < 7:
                for h, it in enumerate(hand):
                    if it.get('type') == 'minion':
                        for pos in range(8):
                            if m[A_PLAY + h * N_POS + pos]:
                                a = A_PLAY + h * N_POS + pos
                                break
                    if a is not None:
                        break
            if a is None:
                for i in range(N_SHOP):
                    if m[A_BUY + i] and i < len(shop):
                        a = A_BUY + i
                        break
            if a is None and gold >= int(me.get('upgrade_price') or 99) and m[A_UPGRADE]:
                a = A_UPGRADE
            if a is None and m[A_REFRESH] and gold >= 2:
                a = A_REFRESH
            if a is None and m[A_END]:
                a = A_END
        if a is None:
            nz = np.flatnonzero(m)
            a = int(nz[0]) if nz.size else 0
        g.step(0, a)

print('game over', g.is_over(), 'turn', g.turn, 'spells_played', spells_played)
print('=== view keys ===', list(view0.keys()))
me = view0['me']
print('me keys:', list(me.keys()))
print('board[0]:', json.dumps((me.get('board') or [{}])[0], ensure_ascii=False)[:700])
print('shop[0]:', json.dumps((me.get('shop') or [{}])[0], ensure_ascii=False)[:700])
print('hand[0]:', json.dumps((me.get('hand') or [{}])[0], ensure_ascii=False)[:700])
print('--- top-level non-me keys:', {k: (type(val).__name__) for k, val in view0.items() if k != 'me'})
