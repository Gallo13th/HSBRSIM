import sys
p = '/home/data/users/gaoletian/projects/HSBRSIM/.tmp_trace/final.py'
raw = open(p, 'rb').read()
for enc in ('utf-8', 'gbk'):
    try:
        s = raw.decode(enc); print('decoded as', enc); break
    except UnicodeDecodeError:
        continue
else:
    raise SystemExit('cannot decode')
n = 0
for old, new in (("g['turn'][str(t)]", "g['turn'][t]"), ("str(t) in g['turn']", "t in g['turn']")):
    n += s.count(old); s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('replacements:', n)
