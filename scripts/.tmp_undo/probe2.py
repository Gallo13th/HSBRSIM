import json
import hsbg_engine as E
g = E.Game(seed=1234)
print("from_json doc:", E.Game.from_json.__doc__)
# advance bots to human turn
for p in range(8):
    if p != 0 and g.needs_action(p):
        g.bot_play(p)
mask0 = bytes(g.legal_mask(0))
sj = g.state_json()
g2 = E.Game.from_json(sj)
print("roundtrip equal:", g2.state_json() == sj, bytes(g2.legal_mask(0)) == mask0,
      bytes(g2.observe(0)[0]) == bytes(g.observe(0)[0]))
print("type", type(g2), "needs", g2.needs_action(0))
# act then restore
a = [i for i,x in enumerate(json.loads(sj) and []) ]
m = list(bytes(g.legal_mask(0)))
acts = [i for i,x in enumerate(g.legal_mask(0)) if x]
print("legal", acts[:6])
g.step(0, acts[0])
print("after act mask diff:", bytes(g.legal_mask(0)) != mask0)
g3 = E.Game.from_json(sj)
print("restored equal:", bytes(g3.legal_mask(0)) == mask0, g3.turn, g.turn)
print("json size", len(sj))
