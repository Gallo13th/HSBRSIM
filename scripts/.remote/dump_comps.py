#!/usr/bin/env python3
import json
d = json.load(open('data/scaling/comps_top.json', encoding='utf-8'))
for i, c in enumerate(d['comps']):
    st = c.get('stats') or {}
    print(f"[{i}] {c['archetype']} | {c['name']} | tribe={c.get('tribe')} | power={c.get('power_level')} "
          f"| place_all={st.get('place_all')} rank={st.get('rank')} dp={st.get('data_points')}")
    core = '; '.join(f"{x['name_zh']}({x['name']}) {x['id']} t{x['tier']}{'' if x.get('in_engine') else ' [NOT-ENGINE]'}"
                     for x in c.get('core_cards') or [])
    addon = '; '.join(f"{x['name_zh']}({x['id']}) t{x['tier']}{'' if x.get('in_engine') else ' [!]'}"
                      for x in c.get('addon_cards') or [])
    print('   CORE:', core)
    print('   ADDON:', addon)
    print('   MECH:', c.get('growth_mechanism'), '| commit:', (c.get('when_to_commit') or '')[:160])
    print('   GROWTH:', (c.get('growth_text') or '')[:400])
    tr = '; '.join(f"{t['name_zh']}({t['id']},{t['kind']},c{t['cost']})" for t in (c.get('trinkets') or [])[:6])
    print('   TRINKETS:', tr[:400])
    eb = c.get('example_boards') or {}
    print('   BOARDS n=', eb.get('n'), 'sigma_max=', eb.get('sigma_max'), 'keys=', list(eb.keys()))
