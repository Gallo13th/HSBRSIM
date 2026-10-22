# 数据重建（hsdata → data/）

仓库**不包含**官方原始 `hsdata/CardDefs.xml`（约 82MB，且随客户端 build 变化）。
运行所需的 `data/bg_*.json` 已入库；只有需要**升级/重建**数据时才需要按下面流程重新拉取 hsdata。

## 1. 获取官方数据（build 37.0.0.255130 对应 hsdata tag `255130`）

```bash
# 任选一种
git clone --depth 1 --branch 255130 https://github.com/HearthSim/hsdata tmp_hsdata
# 或直接下载：
# https://raw.githubusercontent.com/HearthSim/hsdata/255130/CardDefs.xml
# https://raw.githubusercontent.com/HearthSim/hsdata/255130/CardDefs.Bacon.xml
```

把 `CardDefs.xml`（以及新版本拆分的 `CardDefs.Bacon.xml`，若存在）放到仓库根目录的
`hsdata/` 下：

```text
C:\HSagent\hsdata\CardDefs.xml
C:\HSagent\hsdata\CardDefs.Bacon.xml   # 可选
```

> `hsdata/` 已在 `.gitignore` 中，不会入库。

## 2. 生成 data/

```powershell
cd C:\HSagent
python tools/generate_bg_data.py --dry-run   # 只打印统计，不写 data/
python tools/generate_bg_data.py             # 写入 data/bg_*.json
```

生成结果应包含：`bg_cards.json`、`bg_pool_minions.json`、`bg_pool_spells.json`、
`bg_heroes.json`、`bg_hero_powers.json`、`bg_trinkets.json`、`bg_anomalies.json`、
`bg_quest_rewards.json`、`bg_tavern_spells.json`、`bg_dark_gifts.json` 等。

## 3. 一键检查/预演/应用（推荐）

项目已封装版本同步流水线：

```powershell
python tools/version_sync.py --check           # 版本信号检查
python tools/version_sync.py --dry-run        # 取数/合并/生成/差分，只写 tmp
python tools/version_sync.py --apply --yes    # 备份→替换 data/→pytest+smoke
```

`--apply` 会先备份到 `data/backup_<old_build>/`；`--dry-run`/`--check` 不修改 `data/`。

## 4. 验证

```powershell
python -m pytest hsrl2/tests tests -q -o addopts='' -p no:cacheprovider
python scripts/verify_all.py
python tools/smoke_random_games.py --games 4 --seed 7
```

## 5. 版本对照

- 当前数据：官方 build **37.0.0.255130**（`data/bg_summary.json` 的 `patch` 字段）；
- 数据权威说明见 `docs/CARD_DEFS_AUTHORITY.md`、`docs/VERSION_SYNC.md`；
- 若 `CardDefs.xml` 版本与客户端不一致，不要直接改引擎，先走 `version_sync.py --dry-run` 差分。
