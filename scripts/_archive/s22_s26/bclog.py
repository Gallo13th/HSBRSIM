import gzip
import json
import re
import sys

path = "/tmp/s22/bcC.log"
pat = re.compile(r"iter (\d+).*")
with open(path, encoding="utf-8", errors="replace") as f:
    lines = f.readlines()
print("log lines", len(lines))
hits = [ln.rstrip() for ln in lines if "rep-bc" in ln or "bc_loss" in ln or "discover_bc" in ln or "triple_bc" in ln]
for ln in hits[:6]:
    print(ln[:300])
print("--- sample iter line ---")
for ln in lines:
    if "[iter 7]" in ln:
        print(ln[:400])
        break
