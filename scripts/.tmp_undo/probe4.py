import importlib.util, os, json
ROOT = "/home/data/users/gaoletian/projects/HSBRSIM"
spec = importlib.util.spec_from_file_location("ha", os.path.join(ROOT, "scripts", "human_arena.py"))
ha = importlib.util.module_from_spec(spec); spec.loader.exec_module(ha)
s = ha.GameSession(seed=1234, seat=0, out_dir="/tmp/ha_play_probe")
st = s.state()
s.act(st["pending"]["options"][0]["action"])
st = s.state()
print("power fields:", [(p.get("name_zh"), (p.get("text") or "")[:40], p.get("passive"), p.get("price")) for p in st["hero_powers"]])
print("hud hero_power keys:", (st["hud"].get("hero_power") or {}).keys())
# start_gold high
s2 = ha.GameSession(seed=1234, seat=0, out_dir="/tmp/ha_play_probe2", config_json={"start_gold": 200, "gold_refill_cap": 200})
st2 = s2.state(); s2.act(st2["pending"]["options"][0]["action"])
st2 = s2.state()
print("gold", st2["hud"]["gold"], "shop", len(st2["shop"]), "hand", len(st2["hand"]))
acts = []
for k in range(13):
    st2 = s2.state()
    if st2.get("pending"):
        acts.append(("pending", st2["pending"]["kind"])); break
    buy = next((c["buy"] for c in st2["shop"] if c["buy"] is not None), None)
    up = next((b for b in st2["buttons"] if b["key"]=="upgrade" and b["enabled"]), None)
    if buy is not None and len(st2["hand"]) < 9:
        a = ("buy", buy)
    elif up is not None:
        a = ("upgrade", up["action"])
    else:
        a = ("refresh", ha.A_REFRESH)
    try:
        s2.act(a[1]); acts.append(a)
    except Exception as e:
        print("fail at", k, a, e); break
print("acts", acts)
print("decisions", s2.decisions, "undo depth", s2.state()["undo"]["depth"])
