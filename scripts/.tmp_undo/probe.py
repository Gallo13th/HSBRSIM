import hsbg_engine as E
print(E.game_version())
g = E.Game(seed=1234)
names = [n for n in dir(g) if any(k in n.lower() for k in ("state", "save", "restore", "json", "clone"))]
print(names)
for n in ("save_state", "restore_state", "state_json", "load_state", "save", "restore"):
    if hasattr(g, n):
        print(n, getattr(g, n).__doc__)
