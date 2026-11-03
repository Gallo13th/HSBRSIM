#!/usr/bin/env python3
"""Auto chain: keep training 20M blocks from the newest checkpoint until cumulative
decisions reach TARGET_M (default 300M), evaluating each block with eval_panel.sh."""
import json, os, itertools, subprocess, sys, time, glob, re

ROOT="/home/data/users/gaoletian/projects/HSBRSIM"
PY="/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python"
TARGET=int(os.environ.get("TARGET_M","300")); BLOCK=int(os.environ.get("BLOCK_M","5"))
os.chdir(ROOT)
csv_path="runs/CHAIN_300M.csv"
if not os.path.exists(csv_path):
    open(csv_path,"w").write("cum_m,strength,rank,top4,tier4,survive12,run\n")

def running():
    out=subprocess.run(["bash","-lc","ps -eo args | grep 'train_entity_sync.py --checkpoint' | grep -v grep | wc -l"],capture_output=True,text=True)
    return int(out.stdout.strip() or 0)

def latest_run(num):
    d="runs/az_entity_s%d"%num
    ck=sorted(glob.glob(d+"/eval/ckpt_*.pt"))
    return d, (ck[-1] if ck else None)

def hist_args(d):
    p=d+"/history.jsonl"
    if not os.path.exists(p): return None
    return json.loads(next(itertools.islice(open(p),1)))["args"]

def build_cmd(args, ckpt, out, seed, stop):
    skip={"out","seed","stop_at_decisions","minutes","checkpoint","device","gpus","processes","threads"}
    parts=[]
    for k,v in args.items():
        if k in skip or v is None: continue
        if isinstance(v,str) and v.strip()=="": continue
        if isinstance(v,bool):
            if v: parts.append("--"+k.replace("_","-"))
            continue
        if isinstance(v,(list,tuple)): v=",".join(str(x) for x in v)
        parts.append("--%s %s"%(k.replace("_","-"),v))
    return [PY,"scripts/train_entity_sync.py","--checkpoint",ckpt,"--device","cuda:6",
            "--gpus","3,4,5","--processes","24","--threads","3","--minutes","400",
            "--seed",str(seed),"--stop-at-decisions",str(stop),"--out",out]+parts

def ev(tag, ckpt):
    subprocess.run(["bash","scripts/eval_panel.sh",ckpt,tag,"96"],capture_output=True)
    p="runs/eval_panel/%s.json"%tag
    if not os.path.exists(p): return None
    d=json.load(open(p))
    return d.get("death_strength_p50"), d.get("mean_rank"), d.get("top4"), d.get("tier_ge4_ratio"), d.get("survive_t12_ratio")

# wait for any running trainer
while running()>0:
    time.sleep(60)

# figure out where we are: newest sNNN run with a ckpt
nums=sorted(int(re.match(r"runs/az_entity_s(\d+)",p).group(1)) for p in glob.glob("runs/az_entity_s*") if re.match(r"runs/az_entity_s(\d+)$",p))
cur=nums[-1] if nums else 61
d,ck=latest_run(cur)
while ck is None and cur>0:
    cur-=1; d,ck=latest_run(cur)
args=hist_args(d)
if args is None:
    print("no history args in",d); sys.exit(1)
# cumulative estimate: count blocks already done (10 + 20*n)
cum=30
csvd=open(csv_path).read().strip().split("\n")[1:]
if csvd:
    try: cum=max(int(float(l.split(",")[0])) for l in csvd if l.strip())
    except Exception: pass
step=cur+1
while cum < TARGET:
    out="runs/az_entity_s%d"%step
    stop=BLOCK*1000000
    cmd=build_cmd(args, ck, out, 27000+step, stop)
    print("[chain] start",out,"cum",cum,"M",flush=True)
    import threading
    rc=[]
    def _run():
        with open("/tmp/chain_run_%d.log"%step,"w") as f:
            rc.append(subprocess.call(cmd,stdout=f,stderr=subprocess.STDOUT))
    t=threading.Thread(target=_run); t.start()
    hp=out+"/history.jsonl"; last=-1; stall=0
    while t.is_alive():
        time.sleep(120)
        n=sum(1 for _ in open(hp)) if os.path.exists(hp) else 0
        if n<=last: stall+=1
        else: stall=0; last=n
        if stall>=5:  # ~10 分钟无进展
            subprocess.run(["bash","-lc","pkill -9 -f 'az_entity_s%d'"%step])
            open("runs/CHAIN_STALLS.log","a").write("stall in %s at iter %d\n"%(out,n))
            time.sleep(5); break
    t.join()
    cks=sorted(glob.glob(out+"/eval/ckpt_*.pt"))
    cks=[c for c in cks if os.path.abspath(c).startswith(os.path.abspath(out))]
    if not cks:
        print("[chain] FAILED",out,rc,flush=True); time.sleep(120); continue
    mid,final=cks[0],cks[-1]
    for tag,c,a in (("%s_mid"%out.split("_")[-1],mid,cum+10),("%s_end"%out.split("_")[-1],final,cum+BLOCK)):
        r=ev(tag,c)
        if r and r[0] is not None:
            open(csv_path,"a").write("%d,%.1f,%.3f,%.3f,%.3f,%.3f,%s\n"%(a,r[0],r[1] or 0,r[2] or 0,r[3] or 0,r[4] or 0,tag))
            print("[chain]",a,"M -> strength",r[0],"rank",r[1],flush=True)
    ck=final; cum+=BLOCK; step+=1
print("[chain] done at",cum,"M",flush=True)
