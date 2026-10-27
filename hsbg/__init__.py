"""hsbg — AutoTavern 引擎上的酒馆战棋 AlphaZero 项目。

唯一模拟器：``hsbg_engine``（``rust/``，AutoTavern/TavernGym 的 fork）。
唯一训练/搜索栈：``hsbg.az``（不完全信息 MCTS + 8 座自对弈 + PPO）。
标准动作/观测：245 动作 / 3227 floats + 124 cards（与 AutoTavern 逐位对齐）。

全仓库只保留 AutoTavern 引擎 + 不完全信息 MCTS + 自对弈 + PPO 这一条路径。
"""

__version__ = "1.0.0"
