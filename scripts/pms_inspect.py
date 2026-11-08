import json
d=json.load(open(r"C:\Users\letgao\firestone_replays\pms.json",encoding="utf-8"))
print("top keys:",list(d))
for k,v in d.items():
    if isinstance(v,list): print(k,"list",len(v), (list(v[0]) if v and isinstance(v[0],dict) else type(v[0]).__name__ if v else ""))
    elif isinstance(v,dict): print(k,"dict",list(v)[:12])
    else: print(k,repr(v)[:200])
bh=d.get("boardHistory") or []
print("boardHistory n",len(bh),"turns",[b.get("turn") for b in bh])
if bh:
    print("entry keys",list(bh[0]))
    b=bh[-1]
    print("last turn",b.get("turn"),"nboard",len(b.get("board") or []))
    for m in (b.get("board") or [])[:3]: print(m.get("cardID"), {k:v for k,v in (m.get("tags") or {}).items() if k in ("ATK","HEALTH","TECH_LEVEL","ZONE_POSITION","CONTROLLER","PREMIUM","TAUNT","DIVINE_SHIELD","WINDFURY","REBORN","POISONOUS","VENOMOUS","STEALTH","MAGNETIC","DAMAGE")})
