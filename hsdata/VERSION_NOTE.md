# hsdata 255130 版本说明（37.0.0 / build 255130）

## 口径
本目录的 `CardDefs.xml` 是 255130 官方客户端拆分数据的**合并口径**：

- `reversed/hsdata_255130/CardDefs.xml`（构筑 23,452 实体）
- `reversed/hsdata_255130/CardDefs.Bacon.xml`（酒馆战棋 5,787 实体，本项目核心）

两者按 CardID 合并为单个 `<CardDefs build="37.0.0.255130.254477">`
（29,239 实体），由 `reversed/data_255130_input/CardDefs.merged.xml`
（sha256 见 `reversed/hsdata_255130/source.json`）原样复制。

> 255130 起官方数据**拆分**：只喂 `CardDefs.xml` 会得到 0 张 BG 卡。
> 本项目 `tools/generate_bg_data.py` 只读单个 `hsdata/CardDefs.xml`，
> 因此交付合并口径；完整官方拆分文件仍保留在 `reversed/hsdata_255130/`。

## 文件
| 文件 | 来源 | 说明 |
|------|------|------|
| `CardDefs.xml` | 官方 255130 拆分合并 | 数值唯一权威（84 MB / 29,239 实体）|
| `RaceTagMap.xml` | 官方 255130 | 新增 `<Race race="ABERRATION" tag="4756"/>` |
| `README.md` | 官方 255130 | `Version: 37.0.0.255130` |

## 版本口径
- 客户端完整版本（`.product.db`）：`37.0.0.255130.254477`（= CardDefs 根 build 属性）
- HearthSim 版本（README `Version:` 行）：`37.0.0.255130`
- `data/bg_summary.json` 的 `patch` = **37.0.0.255130**（生成器读 README 的
  HearthSim 口径，与旧基线 `36.2.2.249896` 同格式；`reversed/
  data_255130_generator_report.json` 用的是客户端完整 5 段版本，仅展示差异）
