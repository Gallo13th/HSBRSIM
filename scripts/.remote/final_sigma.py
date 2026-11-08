#!/usr/bin/env python3
"""缁堝眬韬潗锛坒inal 危锛塸50/p90 瀵规瘮锛氬彛寰勭粺涓€锛圔OT 鏃犲揩鐓э紝鍙兘鐢ㄧ粓灞€锛夈€?""
import json, os
import numpy as np
ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'


def pct(v, q):
    return float(np.percentile(np.asarray(v, float), q)) if len(v) else 0.0


def score(eps):
    f = [e['final'] for e in eps]
    return pct(f, 50), pct(f, 90), max(f) if f else 0


for cfg in ('bot', 'human'):
    bot = json.load(open(f'{ROOT}/runs/comp_scripts/PLACEHOLDER'))['configs'][cfg]
    base = json.load(open(f'{ROOT}/runs/comp_scripts/bot_baseline.json'))['configs'][cfg]['BOT']
    print(f'--- {cfg} 缁堝眬 危 ---')
    print('BOT  %.0f / %.0f / %.0f' % score(base['episodes']))
    rows = []
    for k, v in bot.items():
        p50, p90, mx = score(v['episodes'])
        rows.append((p50, p90, mx, k))
    rows.sort(reverse=True)
    for p50, p90, mx, k in rows:
        print(f'{k:6s} {p50:6.0f} / {p90:6.0f} / {mx:6.0f}')

