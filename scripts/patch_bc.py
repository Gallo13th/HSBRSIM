from pathlib import Path
p=Path('ppo.remote.txt')
s=p.read_text(encoding='utf-8')
s=s.replace('    triple_bc_coef: float = 0.0\n', '    triple_bc_coef: float = 0.0\n    # epoch 内自适应辅助系数；0 关闭，scale 跨 update 保留且不影响 warmup。\n    bc_guard_ratio: float = 0.0\n    discover_bc_scale: float = 1.0\n    triple_bc_scale: float = 1.0\n',1)
a=s.index('    _dbc = float(getattr(config, "discover_bc_coef"',s.index('def ppo_losses'))
b=s.index('    # ── 过程价值辅助头',a)
s=s[:a]+'''    _dbc = float(config.discover_bc_coef) * float(config.discover_bc_scale)
    _tbc = float(config.triple_bc_coef) * float(config.triple_bc_scale)
    # 使用 PPO 同一份 masked logp；即使外部标签损坏也不能给非法位梯度。
    if _dbc > 0.0:
        _di, _dw = getattr(batch, "discover_bc_idx", None), getattr(batch, "discover_bc_w", None)
        if _di is not None and _dw is not None:
            _i = torch.as_tensor(np.asarray(_di)[idx], dtype=torch.long, device=dev)
            _w = torch.as_tensor(np.asarray(_dw)[idx], dtype=torch.float32, device=dev)
            _ce, discover_bc_n = replication_bc_ce(logp, m, _i, _w, valid,
                                                   normalize=config.bc_ce_norm)
            if discover_bc_n:
                total = total + _dbc * _ce
                discover_bc_loss = _ce.detach()
    if _tbc > 0.0:
        _ta = getattr(batch, "triple_bc_action", None)
        if _ta is not None:
            _tv = torch.as_tensor(np.asarray(_ta)[idx], dtype=torch.long, device=dev)
            _tw = getattr(batch, "triple_bc_w", None)
            _tw = (torch.ones_like(_tv, dtype=torch.float32) if _tw is None else
                   torch.as_tensor(np.asarray(_tw)[idx], dtype=torch.float32, device=dev))
            _ce_t, triple_bc_n = replication_bc_ce(logp, m, _tv[:, None], _tw[:, None],
                                                   valid, normalize=config.bc_ce_norm,
                                                   row_weight=True)
            if triple_bc_n:
                total = total + _tbc * _ce_t
                triple_bc_loss = _ce_t.detach()
'''+s[b:]
# Add independently testable functions before loss.
a=s.index('def ppo_losses(')
s=s[:a]+'''def replication_bc_ce(logp, mask, indices, weights, valid, *, normalize=False,
                      row_weight=False):
    """合法目标上的加权 -log p；可选除以 log(合法动作数)，均匀策略基线为 1。

    不除以选项数：那会随动作空间增大任意缩小梯度。Discover 行内归一化目标价值，
    triple 则保留行间 2:1 权重；非法/越界/forced 标签均不参与。
    """
    torch = _torch()
    inside = (indices >= 0) & (indices < logp.shape[1])
    safe = indices.clamp(0, logp.shape[1] - 1)
    legal = inside & mask.gather(1, safe)
    w = torch.where(legal & torch.isfinite(weights), weights.clamp_min(0),
                    torch.zeros_like(weights))
    mass = w.sum(dim=1)
    rows = (mass > 0) & (valid > 0)
    count = int(rows.sum().item())
    if not count:
        return logp.sum() * 0.0, 0
    selected = logp.gather(1, safe)
    per = -(selected * w).sum(dim=1) / mass.clamp_min(1e-8)
    if normalize:
        per = per / mask.sum(dim=1).clamp_min(2).to(logp.dtype).log()
    rw = mass[rows] if row_weight else torch.ones_like(mass[rows])
    return (per[rows] * rw).sum() / rw.sum(), count


def replication_bc_guard(coef, bc_loss, policy_loss, *, ratio=0.3, eps=1e-8):
    """每 epoch 调整一次；PPO surrogate 可为负，因此比较其绝对量级。"""
    if coef <= 0 or ratio <= 0:
        return float(coef), 0.0
    r = float(coef) * max(0.0, float(bc_loss)) / max(abs(float(policy_loss)), eps)
    if r > ratio:
        coef = max(1e-6, coef * 0.5)
    elif r < 0.05:
        coef = min(1e-3, coef * 1.5)
    return float(coef), r


'''+s[a:]
needle='        rec["elapsed_s"] = time.time() - t0\n'
s=s.replace(needle,'''        # 当前 epoch 已用的有效系数与比率；调整只作用下一 epoch/update。
        _ratios, _scales = [], []
        for _side in ("discover", "triple"):
            _key = _side + "_bc"
            if _key + "_loss" not in rec:
                continue
            _base = float(getattr(cfg, _key + "_coef"))
            _scale = float(getattr(cfg, _key + "_scale"))
            _eff = _base * _scale
            _new, _r = replication_bc_guard(_eff, rec[_key + "_loss"],
                                            rec["policy_loss"], ratio=cfg.bc_guard_ratio)
            rec[_key + "_scale"] = _scale
            rec[_key + "_r"] = _r
            rec[_key + "_next_coef"] = _new
            _ratios.append(_r)
            _scales.append(_scale)
            if cfg.bc_guard_ratio > 0 and _base > 0:
                setattr(cfg, _key + "_scale", _new / _base)
        if _ratios:
            rec["bc_scale"] = max(_scales)
            rec["r"] = sum(_ratios)
'''+needle,1)
needle='    # 搜索行为混合（μ='
a=s.index(needle,s.index('    stats: Dict[str, Any] = {',s.index('    for epoch in range(epochs):')))
s=s[:a]+'''    # 提升 epoch 指标，供训练入口/history 使用；缺标签的 epoch 不以 0 稀释。
    for _key in ("policy_loss", "discover_bc_loss", "triple_bc_loss", "bc_scale", "r",
                 "discover_bc_scale", "triple_bc_scale", "discover_bc_r", "triple_bc_r",
                 "discover_bc_coef", "triple_bc_coef", "discover_bc_next_coef", "triple_bc_next_coef"):
        _vals = [rec[_key] for rec in logs if _key in rec]
        if _vals:
            stats[_key] = float(np.mean(_vals))
'''+s[a:]
p.write_text(s,encoding='utf-8')
p=Path('entity.remote.txt');s=p.read_text(encoding='utf-8')
s=s.replace('多选项时 uniform 加权', '多选项按 tier×放大器优先级加权')
s=s.replace('    flags = _rep_card_flags()\n','    flags = _rep_card_flags()\n',1)
s=s.replace('            w = 1.0 / float(len(hits))\n','            # 目标标志 2 表示放大器，1 表示引擎；按星级×放大器 2 倍估值。\n            values = {j: max(1, flags[int(ch[j])][1]) *\n                      (2.0 if flags[int(ch[j])][2] == 2 else 1.0) for j in hits}\n            denom = sum(values.values())\n',1)
s=s.replace('                d_w[i, j] = w\n','                d_w[i, j] = values[j] / denom\n',1)
s=s.replace('        bc_ce_norm=bool(int(args.bc_ce_norm)),','        bc_ce_norm=bool(int(args.bc_ce_norm)),\n        bc_guard_ratio=float(args.bc_guard_ratio),',1)
a=s.index('            # 辅助 BC 的 guard：');b=s.index('\n',s.index('print(f"[bc-guard]',a))+1
s=s[:a]+s[b:]
p.write_text(s,encoding='utf-8')
# 保持布尔用法兼容，区分目标类型用于标签估值。
p=Path('ppo.remote.txt');s=p.read_text(encoding='utf-8');s=s.replace('is_target = 1 if (sid in _REP_AMP_IDS or sid in _REP_ENGINE_IDS) else 0','is_target = 2 if sid in _REP_AMP_IDS else (1 if sid in _REP_ENGINE_IDS else 0)');p.write_text(s,encoding='utf-8')
