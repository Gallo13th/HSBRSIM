"""AutoTavern-style entity transformer for the 3227/124 observation.

参考 arXiv:2610.33845（TavernAgent）的可迁移设计：
- 己方随从(7)/手牌(10)/酒馆(8)/待选(16)/对手(7) 都是 token（+1 global），最多 49 个；
- 卡牌表示 = identity embedding + 静态特征投影 + 规则文本 embedding（字符 n-gram 哈希近似）；
- 牌面附件/全局状态汇入对应 token / global token；
- Transformer trunk（默认 d=384, 8 层, 8 头，本实现实测 14.8M 参数；18M 需单独 ablation）；
- **pointer head** 组合 245 个 masked action logits（Buy/Sell/Activate/Choose/Play/
  Magnetize/Move 用 token 点积 + 位置/类型 embedding；标量动作来自 global）；
- 输出 policy、rank（placement）与 value（可作辅助）；输入做 symmetric log 压缩。

本模块不修改 obs 布局；只读取 `hsbg.env.obs_std` 的固定 slice。torch 惰性导入。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np

from hsbg.env import obs_std as O
from .common import N_ACTIONS, N_PLAYERS, OBS_CARDS, OBS_FLOATS, RANK_UTILITY

# 由 obs_std 导出的固定形状
N_BOARD = O.N_BOARD
N_HAND = O.N_HAND
N_SHOP = O.N_SHOP
N_CHOICE = O.N_CHOICE
N_OPP = O.N_OPP
MINION_F = O.MINION_F
ITEM_F = O.ITEM_F
GLOBAL_F = O.GLOBAL_F
OPP_F = O.OPP_F
TEXT_DIM = 64
CARD_STATIC_DIM = 10 + 5 + 11 + 11 + 12 + 11 + 1 + 4 + 1  # card_static() 列数

# 动作段（与 common.ACTION_SEGMENTS 一致）
SEG = {
    "end_turn": (0, 0), "refresh": (1, 1), "freeze": (2, 2), "upgrade": (3, 3),
    "hero_power": (4, 5), "dark_gift": (6, 6), "cancel": (7, 7),
    "buy": (8, 15), "sell": (16, 22), "activate": (23, 29), "choose": (30, 45),
    "play": (46, 125), "magnetize": (126, 195), "move": (196, 244),
}


def _torch():
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("torch 不可用：entity model 需要 torch") from exc
    return torch


def _hash_text(text: str, dim: int = TEXT_DIM) -> np.ndarray:
    """字符 3-gram hashing（确定性、无外部模型）；用于规则文本的近似 embedding。"""
    v = np.zeros(dim, dtype=np.float32)
    t = (text or "").lower()
    for i in range(max(0, len(t) - 2)):
        h = hashlib.blake2b(t[i:i + 3].encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if h[4] & 1 else -1.0
        v[idx] += sign
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


@dataclass
class CardTables:
    """与卡牌 embedding 下标对齐的静态表（row 0 = 空槽）。"""
    static: np.ndarray       # [N, CARD_STATIC_DIM] f32
    text: np.ndarray         # [N, TEXT_DIM] f32
    n_cards: int


def load_card_tables(engine=None, data_path: Optional[str] = None) -> CardTables:
    """构建卡牌静态特征 + 文本哈希表。

    data_path 默认仓库 `data/p2/cards_37.json`（37.0.0 数据）；找不到时文本表为零。
    """
    if engine is None:
        import hsbg_engine as engine  # type: ignore
    ncols, raw = engine.card_static()
    static = np.frombuffer(raw, dtype="<f4").reshape(-1, int(ncols)).copy()
    n = static.shape[0]
    text = np.zeros((n, TEXT_DIM), dtype=np.float32)
    path = data_path or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "data", "p2", "cards_37.json")
    if os.path.isfile(path):
        try:
            cards = json.load(open(path, encoding="utf-8"))["cards"]
            by_id = {c["id"]: c for c in cards}
            for idx in range(1, n):
                cid = engine.card_info(idx)[0]
                c = by_id.get(cid)
                if c:
                    text[idx] = _hash_text(c.get("text") or "")
        except Exception:  # noqa: BLE001 - 文本可选；失败则零
            pass
    return CardTables(static=static.astype(np.float32), text=text, n_cards=n)


def build_entity_net(*, d_model: int = 384, n_layers: int = 8, n_heads: int = 8,
                     dim_ff: Optional[int] = None, dropout: float = 0.1,
                     card_dim: int = 48, tables: Optional[CardTables] = None,
                     n_extra_tokens: int = 0, pos_size: int = 16,
                     arch: str = "entity", seq_head: bool = False,
                     bc_card_head: bool = False,
                     bc_card_dim: Optional[int] = None):
    """构造 EntityAZNet（torch 模块）。

    ``seq_head=True`` 时在 global token 上加一个 245 维的「动作序列辅助头」
    （``forward_aux()`` 返回其 logits；见 ``docs/ACTION_SEQUENCE_AUX.md``）。
    默认 False：不构建，参数量/前向/checkpoint 与之前完全一致。

    ``bc_card_head=True`` 时在 global token 上加「卡牌身份头」（3983 类，分层 BC）；
    默认 False：不构建（``bc_coef=0`` 逐位等价）。
    """
    torch = _torch()
    nn = torch.nn
    d = int(d_model)
    n_heads = int(n_heads)
    dim_ff = int(dim_ff or 4 * d)
    if bc_card_head and bc_card_dim is None:
        from .bc_aux import bc_card_head_size
        bc_card_dim = int(bc_card_head_size())
    card_head_dim = int(bc_card_dim or 0)
    tables = tables or load_card_tables()
    n_cards = int(tables.n_cards)
    model_arch = str(arch)
    static_t = torch.from_numpy(tables.static.copy())
    text_t = torch.from_numpy(tables.text.copy())

    # 固定 slice（来自 obs_std）
    S = {
        "global": O.SLICE_GLOBAL, "quests": O.SLICE_QUESTS, "pending": O.SLICE_PENDING,
        "board": O.SLICE_BOARD, "hand": O.SLICE_HAND, "shop": O.SLICE_SHOP,
        "choices": O.SLICE_CHOICES, "opponents": O.SLICE_OPPONENTS,
        "opp_boards": O.SLICE_OPP_BOARDS,
    }
    C = {
        "powers": O.SLICE_CARD_POWERS, "deity": O.SLICE_CARD_DEITY,
        "board": O.SLICE_CARD_BOARD, "hand": O.SLICE_CARD_HAND,
        "shop": O.SLICE_CARD_SHOP, "choices": O.SLICE_CARD_CHOICES,
        "trinkets": O.SLICE_CARD_TRINKETS, "opp_heroes": O.SLICE_CARD_OPP_HEROES,
        "opp_boards": O.SLICE_CARD_OPP_BOARDS,
    }

    class EntityAZNet(nn.Module):
        uses_cards = True
        arch = model_arch

        def __init__(self):
            super().__init__()
            self.d_model = d
            self.n_cards = n_cards
            self.register_buffer("card_static", static_t)
            self.register_buffer("card_text", text_t)
            self.card_id = nn.Embedding(n_cards, card_dim, padding_idx=0)
            self.card_static_proj = nn.Linear(int(tables.static.shape[1]), card_dim)
            self.card_text_proj = nn.Linear(TEXT_DIM, card_dim)
            self.card_to_d = nn.Linear(card_dim, d)
            self.n_extra = int(n_extra_tokens)
            self.type_emb = nn.Embedding(7 if self.n_extra else 6, d)
            self.pos_emb = nn.Embedding(int(pos_size), d)
            self.extra_proj = (nn.Linear(GLOBAL_F + 1, d) if self.n_extra else None)
            self.global_proj = nn.Linear(GLOBAL_F + 3 * O.QUEST_F + O.PENDING_KINDS, d)
            self.minion_proj = nn.Linear(MINION_F, d)
            self.item_proj = nn.Linear(ITEM_F, d)
            self.opp_proj = nn.Linear(OPP_F + 2 * MINION_F, d)
            self.drop = nn.Dropout(float(dropout))
            layer = nn.TransformerEncoderLayer(
                d_model=d, nhead=n_heads, dim_feedforward=dim_ff,
                dropout=float(dropout), activation="gelu", batch_first=True,
                norm_first=True)
            self.trunk = nn.TransformerEncoder(layer, num_layers=int(n_layers))
            # 标量动作 0..7（EndTurn/Refresh/Freeze/Upgrade/HeroPower0/1/DarkGift/Cancel）
            self.scalar_head = nn.Linear(d, 8)
            # pointer 查询/位置
            self.q_buy = nn.Linear(d, d)
            self.q_board = nn.Linear(d, d)
            self.buy_bias = nn.Parameter(torch.zeros(N_SHOP))
            self.sell_bias = nn.Parameter(torch.zeros(N_BOARD))
            self.activate_bias = nn.Parameter(torch.zeros(N_BOARD))
            self.choose_bias = nn.Parameter(torch.zeros(N_CHOICE))
            self.play_bias = nn.Parameter(torch.zeros(N_HAND, 8))
            self.magnetize_bias = nn.Parameter(torch.zeros(N_HAND, N_BOARD))
            self.move_bias = nn.Parameter(torch.zeros(N_BOARD, N_BOARD))
            self.pos_play = nn.Parameter(torch.zeros(8, d))
            self.pointer_scale = 1.0 / math.sqrt(float(d))
            self.rank_head = nn.Linear(d, N_PLAYERS)
            self.value_head = nn.Linear(d, 1)
            # 动作序列辅助头（turn 内动作 multi-hot）：默认 None = 不构建、不计算
            self.seq_head = nn.Linear(d, N_ACTIONS) if seq_head else None
            # 卡牌身份头（分层 BC）：默认 None = 不构建、参数/checkpoint 不变
            self.card_head = (nn.Linear(d, int(card_head_dim))
                              if bc_card_head else None)
            if self.card_head is not None:
                # 零初始化 = 初始均匀先验：card CE 起点 = ln(3983)，梯度稳定
                nn.init.zeros_(self.card_head.weight)
                nn.init.zeros_(self.card_head.bias)
            self.bc_card_dim = int(card_head_dim) if bc_card_head else 0

        def _card_repr(self, idx):
            # idx [B, ...] long; 返回 [B, ..., d]
            i = idx.clamp(0, self.n_cards - 1)
            emb = self.card_id(i) + self.card_static_proj(self.card_static[i]) \
                + self.card_text_proj(self.card_text[i])
            return self.card_to_d(emb)

        def forward(self, features, cards, mask=None):
            logits, rank, value, _g = self._forward_impl(features, cards, mask)
            return logits, rank, value

        def forward_aux(self, features, cards, mask=None):
            """``(logits, rank, value, seq_logits|None)``：只在训练损失里取 seq logits。

            ``seq_head`` 未构建时最后一项为 None（默认关闭 = 全程不调用本方法）。
            """
            logits, rank, value, g = self._forward_impl(features, cards, mask)
            seq = None if self.seq_head is None else self.seq_head(g)
            return logits, rank, value, seq

        def forward_bc(self, features, cards, mask=None):
            """分层 BC 用的一次前向：``(policy_logits, card_logits|None)``。

            只在 ``bc_coef>0`` 的 BC 分支调用；``card_head`` 未构建时第二项为 None。
            """
            logits, _rank, _value, g = self._forward_impl(features, cards, mask)
            card = None if self.card_head is None else self.card_head(g)
            return logits, card

        def _forward_impl(self, features, cards, mask=None):
            B = features.shape[0]
            dev = features.device
            x = features.float()
            # symmetric log 压缩（AutoTavern 设计）
            x = torch.sign(x) * torch.log1p(torch.abs(x))
            c = cards.long().clamp(0, self.n_cards - 1)

            def flat(name, shape):
                return x[:, S[name]].reshape(B, *shape)

            board = flat("board", (N_BOARD, MINION_F))
            hand = flat("hand", (N_HAND, ITEM_F))
            shop = flat("shop", (N_SHOP, ITEM_F))
            choices = flat("choices", (N_CHOICE, ITEM_F))
            opp = flat("opponents", (N_OPP, OPP_F))
            ob = flat("opp_boards", (N_OPP, N_BOARD, MINION_F))
            glob = torch.cat([x[:, S["global"]], x[:, S["quests"]],
                              x[:, S["pending"]]], dim=-1)

            # global token + 英雄/技能/饰品/秘密卡牌表示（直接加和到 global）
            g = self.global_proj(glob)
            g = g + self._card_repr(c[:, C["powers"]]).sum(dim=1)
            g = g + self._card_repr(c[:, C["deity"]]).sum(dim=1)
            g = g + self._card_repr(c[:, C["trinkets"]]).sum(dim=1)

            def card_of(name, shape):
                return self._card_repr(c[:, C[name]].reshape(B, *shape))

            tok = []
            tok.append((g + self.pos_emb(torch.zeros(B, dtype=torch.long, device=dev))
                        + self.type_emb(torch.zeros(B, dtype=torch.long, device=dev))).unsqueeze(1))
            # board 7
            b = self.minion_proj(board) + card_of("board", (N_BOARD,))
            b = b + self.type_emb(torch.ones(B, N_BOARD, dtype=torch.long, device=dev)) \
                + self.pos_emb(torch.arange(N_BOARD, device=dev).view(1, -1))
            tok.append(b)
            # hand 10
            hnd = self.item_proj(hand) + card_of("hand", (N_HAND,))
            hnd = hnd + self.type_emb(torch.full((B, N_HAND), 2, dtype=torch.long, device=dev)) \
                + self.pos_emb(torch.arange(N_HAND, device=dev).view(1, -1))
            tok.append(hnd)
            # shop 8
            sh = self.item_proj(shop) + card_of("shop", (N_SHOP,))
            sh = sh + self.type_emb(torch.full((B, N_SHOP), 3, dtype=torch.long, device=dev)) \
                + self.pos_emb(torch.arange(N_SHOP, device=dev).view(1, -1))
            tok.append(sh)
            # choices 16
            ch = self.item_proj(choices) + card_of("choices", (N_CHOICE,))
            ch = ch + self.type_emb(torch.full((B, N_CHOICE), 4, dtype=torch.long, device=dev)) \
                + self.pos_emb(torch.arange(N_CHOICE, device=dev).view(1, -1))
            tok.append(ch)
            # opponents 7: public + mean/max of last seen board
            ob_mean = ob.mean(dim=2)
            ob_max = ob.max(dim=2).values
            op = self.opp_proj(torch.cat([opp, ob_mean, ob_max], dim=-1))
            op = op + card_of("opp_heroes", (N_OPP,))
            op = op + self.type_emb(torch.full((B, N_OPP), 5, dtype=torch.long, device=dev)) \
                + self.pos_emb(torch.arange(N_OPP, device=dev).view(1, -1))
            tok.append(op)
            # entity18m: 8 pending-context tokens -> 56 entity tokens + global
            if self.n_extra:
                pend = x[:, S["pending"]]
                for i in range(self.n_extra):
                    ex = self.extra_proj(torch.cat([x[:, S["global"]],
                                                    pend[:, i:i + 1]], dim=-1))
                    ex = ex + self.type_emb(torch.full((B,), 6, dtype=torch.long,
                                                       device=dev)) \
                        + self.pos_emb(torch.full((B,), 16 + i, dtype=torch.long,
                                                  device=dev))
                    tok.append(ex.unsqueeze(1))

            tokens = torch.cat(tok, dim=1)  # entity 49 / entity18m 57
            hs = self.trunk(self.drop(tokens))
            g = hs[:, 0]
            base = 1
            hb = hs[:, base:base + N_BOARD]; base += N_BOARD
            hh = hs[:, base:base + N_HAND]; base += N_HAND
            hs_shop = hs[:, base:base + N_SHOP]; base += N_SHOP
            hc = hs[:, base:base + N_CHOICE]; base += N_CHOICE
            # ho = hs[:, base:base+N_OPP]  # opponent tokens currently unused in heads

            logits = torch.zeros(B, N_ACTIONS, device=dev)
            scalar = self.scalar_head(g)  # 0..7
            logits[:, 0:8] = scalar
            # buy 8..15
            logits[:, 8:16] = self.pointer_scale * (hs_shop * self.q_buy(g).unsqueeze(1)).sum(-1) + self.buy_bias
            # sell/activate 16..22 / 23..29
            qb = self.q_board(g).unsqueeze(1)
            logits[:, 16:23] = self.pointer_scale * (hb * qb).sum(-1) + self.sell_bias
            logits[:, 23:30] = self.pointer_scale * (hb * qb).sum(-1) + self.activate_bias
            # choose 30..45
            logits[:, 30:46] = self.pointer_scale * (hc * self.q_buy(g).unsqueeze(1)).sum(-1) + self.choose_bias
            # play 46..125: hand 10 × pos 8
            play = torch.einsum("bhd,pd->bhp", hh, self.pos_play)
            logits[:, 46:126] = self.pointer_scale * play.reshape(B, N_HAND * 8) + self.play_bias.reshape(1, -1)
            # magnetize 126..195: hand 10 × board 7
            mag = torch.einsum("bhd,bjd->bhj", hh, hb)
            logits[:, 126:196] = self.pointer_scale * mag.reshape(B, N_HAND * N_BOARD) + self.magnetize_bias.reshape(1, -1)
            # move 196..244: board from × board to
            mv = torch.einsum("bid,bjd->bij", hb, hb)
            logits[:, 196:245] = self.pointer_scale * mv.reshape(B, N_BOARD * N_BOARD) + self.move_bias.reshape(1, -1)
            if mask is not None:
                logits = logits.masked_fill(~mask.bool(), -1e9)
            rank = self.rank_head(g)
            value = torch.tanh(self.value_head(g)).squeeze(-1)
            return logits, rank, value, g

    return EntityAZNet()
