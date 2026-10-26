# HSbg Engine（rust/）

HSBRSIM 的主模拟引擎 —— [TavernGym](https://github.com/MCG-NJU/AutoTavern) 的 vendored fork
（AutoTavern v1.0.0, commit `fb61201`, MIT）。Rust 实现 + PyO3 扩展，Python 包名
`hsbg_engine`；公开 API 与行为与上游 `taverngym` 1.0.0 逐位一致，只改了包名。

- 目录说明、重命名映射、与上游同步策略、构建步骤、已知差异：见 [FORK.md](FORK.md)
- 整体架构/安装/用法/与 `hsrl2` 的关系/基准：见 [../docs/RUST_ENGINE.md](../docs/RUST_ENGINE.md)

快速开始（macOS/Linux，需 Rust 1.98 + maturin）：

```bash
cd rust
python3 -m pip install -e .      # 构建并安装 hsbg_engine（首次需编译 release 扩展）
python3 -c "import hsbg_engine; print(hsbg_engine.version(), hsbg_engine.game_version())"
```

上游版权与许可归因见同目录 `LICENSE` / `NOTICE` / `CITATION.cff`。
