"""hsbg — 酒馆战棋智能体（环境 + 策略 + 训练）。

分层（自下而上）:

* ``hsrl2``  — 已冻结/校验的模拟引擎（vendored，机制精度权威）。
* ``hsbg.env``      — 对接强化学习的环境层（观测/动作/奖励/对局循环）。
* ``hsbg.policy``   — 实体 Transformer 策略网络（候选动作打分 + 价值头）。
* ``hsbg.train``    — BC / PPO 训练管线。
* ``hsbg.eval``     — 评测与锦标赛。
* ``hsbg.agents``   — 脚本对手 / 启发式教师。
* ``hsbg.bridge``   — 真实对局数据桥（Power.log / AgenticAssistant 资产）。
"""

__version__ = "0.1.0"
