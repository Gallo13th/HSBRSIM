import json, hsbg_engine as E
cfg = json.loads(E.default_config_json())
print(json.dumps(cfg, ensure_ascii=False, indent=1)[:4000])
