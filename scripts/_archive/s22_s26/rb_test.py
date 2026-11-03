import sys
sys.path.insert(0, "/home/data/users/gaoletian/projects/HSBRSIM")
from hsbg.az.train.ppo import _ReplicationBias, CollectConfig
b = _ReplicationBias(3.0, 3.0)
print("ok stats", b.stats, "flags", len(b._flags))
cfg = CollectConfig(collect_discover_bias=3.0, collect_triple_bias=3.0)
print("cfg", cfg.collect_discover_bias, cfg.collect_triple_bias)
print("default", CollectConfig().collect_discover_bias, CollectConfig().collect_triple_bias)
