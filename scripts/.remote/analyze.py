#!/usr/bin/env python3
"""把 runs/comp_scripts/*.json 汇总成文档表格（不训练、纯统计）。"""
import json, os
import numpy as np

ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'


def load(name):
    return json.load(open(os.path.join(ROOT, 'runs/comp_scripts', name), encoding='utf-8'))


def pct(v, q):
    return float(np.percentile(np.asarray(v, dtype=float), q)) if len(v) else 0.0


def row(label, eps, name=''):
    s15 = [e['sigma_t15'] for e in eps]
    s12 = [e['sigma_t12'] for e in eps]
    surv = [e['survival'] for e in eps]
    core = [e['core_turn'] for e in eps if e['core_turn'] > 0]
    car = [e['carrier_turn'] for e in eps if e['carrier_turn'] > 0]
    both = sum(1 for e in eps if e['core_turn'] > 0 and e['carrier_turn'] > 0)
    return {
        'label': label, 'name': name, 'n': len(eps),
        't12': pct(s12, 50), 't15_50': pct(s15, 50), 't15_90': pct(s15, 90),
        't15_max': max(s15) if s15 else 0,
        'core_t': pct(core, 50) if core else -1.0,
        'core_rate': len(core) / max(1, len(eps)),
        'carrier_rate': len(car) / max(1, len(eps)),
        'both_rate': both / max(1, len(eps)),
        'cast': float(np.mean([e['cast_share'] for e in eps])),
        'body': float(np.mean([e['body_share'] for e in eps])),
        'spells': float(np.mean([e['spells'] for e in eps])),
        'r12': pct([e['r12_15'] for e in eps], 50),
        'place': float(np.mean([e['placement'] for e in eps])),
        'top4': float(np.mean([1.0 if 0 < e['placement'] <= 4 else 0.0 for e in eps])),
        'surv15': float(np.mean([1.0 if s >= 15 else 0.0 for s in surv])),
        'ill': int(sum(e['illegal'] for e in eps)),
    }


HDR = ('| 阵容 | n | t12 Σ | **t15 Σ p50** | t15 p90 | t15 max | 核心到手 | 核心率 | '
       '载体率 | 齐套率 | 落点% | 身材% | 法术/局 | r12_15 | 名次 | 活到15 | 非法 |')
SEP = '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|'


def table(rows, title):
    print('\n### ' + title + '\n')
    print(HDR)
    print(SEP)
    for r in rows:
        print(f"| {r['label']} {r['name']} | {r['n']} | {r['t12']:.0f} | **{r['t15_50']:.0f}** | "
              f"{r['t15_90']:.0f} | {r['t15_max']:.0f} | {r['core_t']:.1f} | "
              f"{r['core_rate']:.2f} | {r['carrier_rate']:.2f} | {r['both_rate']:.2f} | "
              f"{100*r['cast']:.0f} | {100*r['body']:.0f} | {r['spells']:.1f} | "
              f"{r['r12']:.2f} | {r['place']:.2f} | {100*r['surv15']:.0f}% | {r['ill']} |")


def main():
    bot = load('bot30.json')
    hum = load('human30.json')
    base = load('bot_baseline.json')
    for cfgkey, title, d in (('bot', 'bot（8 席引擎 bot）', bot),
                             ('human', 'human（5 席人类战团 p0.9）', hum)):
        rows = []
        for key in d['configs'][cfgkey]:
            rep = d['configs'][cfgkey][key]
            spec = d['specs'].get(key, {})
            rows.append(row(key, rep['episodes'], spec.get('name', '')))
        rows.sort(key=lambda r: -r['t15_50'])
        table(rows, f'{title}：t15 汇总（按 p50 排序）')
    for cfg in ('bot', 'human'):
        r = row('BOT', base['configs'][cfg]['BOT']['episodes'], '（引擎内置 bot 基线）')
        print(f"\n基线 [{cfg}] 引擎 bot：t15 Σ p50={r['t15_50']:.0f} p90={r['t15_90']:.0f} "
              f"t12={r['t12']:.0f} 名次={r['place']:.2f} "
              f"法术/局={r['spells']:.1f} 活到15={100*r['surv15']:.0f}%")


if __name__ == '__main__':
    main()
