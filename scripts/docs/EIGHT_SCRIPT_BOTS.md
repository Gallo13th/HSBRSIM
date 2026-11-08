# 8 席全脚本对弈：终局冠军阵容强度（2026-11-04）

> 小测试：8 个座位全部由固定阵容脚本驱动（hybrid：阵容动作优先、其余引擎 bot 兜底），
> 跑 50 局，看终局冠军（rank=1）的**终局盘面 Σ(atk+hp)**、盘面构成与阵容归属。
> 引擎 37.0.0.255790；脚本 `scripts/eight_script_bots.py`；原始 JSON
> `runs/eight_script_bots/{script50,script50_noexit,bot50}.json`。

## 1. 设计

- 每局大厅 5 个种族（引擎上限）；给 8 席各分配一个「主族在本局大厅内」的固定阵容
  （`comp_scripts.COMPS`，28 套里筛选），避免脚本因主族缺失直接退化成 bot。
- 每席一个独立 `CompPolicy`，`comp_action` 拿不到阵容动作时回落到引擎 bot。
- 冠军 = `placements()` 里 rank=1 的座位；强度 = 其 `player_json.board` 的 Σ(atk+hp)（终局盘面）。
- 变体：默认允许「抓不到核心→退出阵容」（v2 口径）；`--no-exit` 保持老口径（一直找核心）。
- 基线：8 席全引擎 bot（同 50 seed）。

## 2. 冠军强度（50 局）

| 模式 | p10 | **p50** | p90 | max | mean | 亚军 p50 |
|---|---:|---:|---:|---:|---:|---:|
| 8 scripts（默认，允许回退） | 753 | **1268** | 1960 | 2558 | 1323 | 689 |
| 8 scripts（`--no-exit`） | 719 | **1230** | 1832 | 3042 | 1251 | 745 |
| 8 engine bots（基线） | 732 | **1311** | 3876 | 14576 | 2253 | 683 |

- 冠军盘面大小 p50=7、盘面最高 tier p50=6（三组一致）。
- 脚本冠军的**中位强度与引擎 bot 相当（1.23–1.27k vs 1.31k）**，但**尾部短得多**：
  p90 1.8–2.0k vs bot 3.9k；max 2.5–3.0k vs bot 的 14.6k（50 局里有 2 局 bot 滚到 ~1k 身材/只）。
- 冠军的「分配阵容核心命中」很低：默认 mean core_hit=0.075，no-exit=0.105（15/50 有核心）。
  即**大多数冠军并不是把某一固定阵容执行到底，而是混合/通用盘面**（8 席共享 5 个种族，
  核心卡竞争 + 抓不到就回退/转型）。

## 3. 典型冠军盘面（按强度）

**8 scripts（默认）**
- 2558：`Turbo Hogrider 599/160`、`Cage Gnawer 244/66`、`Bramble Tunneler 243/66`、
  `Fire Baller 234/62`、`Turquoise Skitterer 229/61`、`Tavern Tempest 232/61`、`Eternal Knight 238/63`
  （分配 dragon_shield，实际是混合/转型盘面，core_hit=0）。
- 2374：`Flaming Enforcer 719/717` + `Kalecgos 52/60` + `Holy Vanguard 184/184`（dragon_kalecgos，core_hit=0.5）。
- 2372：`Twisted Wrathguard 463/459`、`Humon'gozz 161/210`（demon_self_damage）。

**8 scripts（no-exit）**
- 3042：`Expert Aviator 666/416`、`Fruit Vendor 220/115`、`Kelp Keeper 222/114`、`Turbo Hogrider 219/116`…
- 3023：`Soulkeeping Jailer 371/383`、`Living Prison 357/358`、`Trapped Clapper 359/358`（E，core_hit=0.25）。
- 1911：`Living Prison 253/240` + `Gormling Gourmet 222/202`（J）。

**8 engine bots（基线）**
- 14576：7 只 ~1030/1030（`Suspicious Prisonguard` / `Treasure Parrot` / `Maritime Extortionist` 组合）。
- 14483：7 只 ~1030/1030（`Joyous` / `Annoy-o-Module` / `Azharan Cutlassier` 组合）。
- 6837：`Crackling Cyclone 513/512`、`Mind Muck 540/538`、`Deathstrider 564/568` …

## 4. 结论

1. **8 脚本局的冠军终局强度中位 ≈1.2–1.3k Σ**，最强单局 2.5–3.0k；盘面 7 只、tier 5–6。
2. 与 8 引擎 bot 相比：中位基本相同，但**脚本局的强度分布更“紧”**（没有 bot 那种 10k+ 的极端滚雪球）；
   即脚本作为对手提供的是**阵容多样性/可预测的强度带**，不是更高上限。
3. 固定阵容在 8 席混战里很难完整执行：冠军只有 7.5–10.5% 的核心命中；要测「单套阵容的强度」
   应用单套探针（`scripts/comp_full_probe.py`，hybrid t15 Σ 62–314），而不是 8 席混战。
4. 复现：`PYTHONPATH=rust/python:. python scripts/eight_script_bots.py --games 50 --mode script [--no-exit]`；
   bot 基线 `--mode bot`。
