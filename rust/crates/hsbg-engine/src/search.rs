//! 逐步（move-level）MCTS 搜索核（P4-M1）。
//!
//! 设计（详见 `docs/AZ_MCTS_SELFPLAY_DESIGN.md` §3）：
//! - 只对 **`seat` 的动作**建树（动作空间 245，`legal_mask` 精确约束）；其余座位由内置
//!   bot 推进（`bot::play_turn`），即 chance/对手策略在边内折叠，不做对手分支。
//! - 每个节点持完整 `Game`（`Game: Clone`，RNG 随克隆）；PUCT 选择、标量 value 备份
//!   （8 人常和，不做符号翻转）。
//! - 节点首次扩展时调用一次 `eval`（由 Python/NN 注入）：`(prior[245], value)`；
//!   终局节点不调用 eval，utility = `1 - 2*(placement-1)/(n-1)`（`Player::placement`）。
//! - 根可选 Dirichlet 噪声；π = counts^(1/τ) 归一化（τ≤0 → one-hot）；动作从 π 采样。
//! - 全部随机性来自 `SearchConfig::seed`（自带 SplitMix64，可复现）。
//!
//! 该模块是**新增能力**：不改变引擎默认行为（现有调用方不经过 search）。

use std::collections::HashMap;

use crate::actions::N_ACTIONS;
use crate::engine::Game;
use crate::types::PlayerId;

/// 搜索超参（Python 侧 `mcts_search` 同名参数）。
#[derive(Clone, Copy, Debug)]
pub struct SearchConfig {
    /// 每次 `search` 的模拟次数（根节点 eval 不计入；总 eval 次数 ≤ simulations+1）。
    pub simulations: u32,
    /// PUCT 探索系数 `c`。
    pub c_puct: f32,
    /// 根策略温度：π ∝ counts^(1/τ)；τ=0 → 取最多访问（one-hot）。
    pub temperature: f32,
    /// 根 Dirichlet 噪声 α（0 = 关闭）。
    pub dirichlet_alpha: f32,
    /// 根 Dirichlet 混合比例 ε（0 = 关闭）。
    pub dirichlet_epsilon: f32,
    /// 随机种子（Dirichlet 采样 + 根动作采样）。
    pub seed: u64,
}

impl Default for SearchConfig {
    fn default() -> Self {
        SearchConfig {
            simulations: 8,
            c_puct: 1.5,
            temperature: 1.0,
            // 245 动作空间的常用值（AlphaZero 类；HT 用 0.3/0.25 亦可调）
            dirichlet_alpha: 0.3,
            dirichlet_epsilon: 0.25,
            seed: 0,
        }
    }
}

/// `search` 的结果。
#[derive(Clone, Debug)]
pub struct SearchResult {
    /// 根动作访问分布（长度 245；非法动作 = 0；和为 1；空 mask 时全 0）。
    pub pi: Vec<f32>,
    /// 从 π 采样的动作下标（0..245；终局/空 mask 为 0）。
    pub action: u16,
    /// 根节点平均价值（终局为终局 utility）。
    pub root_value: f32,
    /// 根节点总访问数（含根）。
    pub visits: u32,
}

/// 一个搜索节点：该节点 `game` 处于「轮到 `seat` 行动」的状态（或终局）。
struct Node {
    game: Game,
    /// 该节点 eval 给出的先验（长度 245，已按 mask 清零/归一化）。
    prior: Vec<f32>,
    /// 各动作访问数（长度 245）。
    visits: Vec<u32>,
    /// 各动作价值累计（标量、seat 视角；长度 245）。
    wins: Vec<f32>,
    /// 已展开的子节点（按动作下标；None = 未尝试）。
    children: Option<HashMap<u16, Box<Node>>>,
    /// 终局 utility（Some = 终局节点，无需 eval/展开）。
    terminal: Option<f32>,
}

impl Node {
    fn total_visits(&self) -> u32 {
        self.visits.iter().sum()
    }
}

/// 终局 utility：`1 - 2*(placement-1)/(n-1)`（第 1 名 +1、最后一名 -1）；
/// `placement == 0`（未定名次 / 模拟停摆）→ 0。
pub fn placement_utility(placement: u8, num_players: usize) -> f32 {
    if placement == 0 || num_players < 2 {
        return 0.0;
    }
    let p = placement as f32;
    let n = num_players as f32;
    (1.0 - 2.0 * (p - 1.0) / (n - 1.0)).clamp(-1.0, 1.0)
}

/// `seat` 是否已经终局（被淘汰或游戏结束）。返回终局 utility。
fn terminal_utility(g: &Game, seat: usize) -> Option<f32> {
    let p = &g.players[seat];
    if p.placement != 0 {
        return Some(placement_utility(p.placement, g.players.len()));
    }
    if g.is_over() {
        // 游戏结束但名次未写（异常路径）：按存活数给 0，避免误判。
        return Some(0.0);
    }
    None
}

/// 推进其它座位（bot）直到 `seat` 需要行动或终局。返回终局 utility。
fn advance_to_seat(g: &mut Game, seat: usize) -> Option<f32> {
    let mut guard = 0usize;
    loop {
        if let Some(u) = terminal_utility(g, seat) {
            return Some(u);
        }
        if g.needs_action(seat) {
            return None;
        }
        // 其它座位行动（与 PyGame.bot_play 一致：逐个 bot_play 直到无人需要行动）。
        let mut acted = false;
        for p in 0..g.players.len() {
            if p != seat && g.needs_action(p) {
                crate::bot::play_turn(g, p);
                acted = true;
                break;
            }
        }
        if !acted {
            // 引擎停摆（防御性；正常对局不触发）：按未知终局 0 处理。
            return Some(0.0);
        }
        guard += 1;
        if guard > 4000 {
            return Some(0.0);
        }
    }
}

/// 把 eval 的 prior 按合法 mask 做保底处理：非法清零；全零 → 合法动作均分；归一化。
fn sanitize_prior(prior: &mut [f32], legal: &[bool]) {
    let mut sum = 0.0f32;
    for (i, p) in prior.iter_mut().enumerate() {
        if !legal[i] || !p.is_finite() || *p < 0.0 {
            *p = 0.0;
        }
        sum += *p;
    }
    let n_legal = legal.iter().filter(|x| **x).count();
    if sum <= 0.0 || !sum.is_finite() {
        let u = if n_legal > 0 {
            1.0 / n_legal as f32
        } else {
            0.0
        };
        for (i, p) in prior.iter_mut().enumerate() {
            *p = if legal[i] { u } else { 0.0 };
        }
        return;
    }
    for p in prior.iter_mut() {
        *p /= sum;
    }
}

// ── 自带小随机数（SplitMix64 + Marsaglia-Tsang gamma；避免新增依赖） ─────────────

struct Rng64(u64);

impl Rng64 {
    fn new(seed: u64) -> Self {
        Rng64(seed ^ 0x9E37_79B9_7F4A_7C15)
    }
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    fn next_f32(&mut self) -> f32 {
        // [0,1)
        ((self.next_u64() >> 40) as f32) / (1u64 << 24) as f32
    }
    fn next_u32_below(&mut self, n: u32) -> u32 {
        if n == 0 {
            0
        } else {
            (self.next_u64() % n as u64) as u32
        }
    }
    fn normal(&mut self) -> f32 {
        let u1 = self.next_f32().max(1e-7);
        let u2 = self.next_f32();
        (-2.0 * u1.ln()).sqrt() * (std::f32::consts::TAU * u2).cos()
    }
    /// Marsaglia-Tsang gamma(α, 1)（α>0）。
    fn gamma(&mut self, alpha: f32) -> f32 {
        if alpha <= 0.0 {
            return 0.0;
        }
        if alpha < 1.0 {
            let u = self.next_f32().max(1e-7);
            return self.gamma(alpha + 1.0) * u.powf(1.0 / alpha);
        }
        let d = alpha - 1.0 / 3.0;
        let c = 1.0 / (9.0 * d).sqrt();
        loop {
            let mut x;
            let mut v;
            loop {
                x = self.normal();
                v = 1.0 + c * x;
                if v > 0.0 {
                    break;
                }
            }
            let v = v * v * v;
            let u = self.next_f32();
            if u < 1.0 - 0.0331 * x.powi(4) || u.ln() < 0.5 * x * x + d * (1.0 - v + v.ln()) {
                return d * v;
            }
        }
    }
}

/// 根 Dirichlet 噪声混合（只作用于合法动作）。
fn mix_dirichlet(prior: &mut [f32], legal: &[bool], alpha: f32, eps: f32, rng: &mut Rng64) {
    if alpha <= 0.0 || eps <= 0.0 {
        return;
    }
    let eps = eps.clamp(0.0, 1.0);
    let mut noise = vec![0.0f32; prior.len()];
    let mut sum = 0.0f32;
    for (i, n) in noise.iter_mut().enumerate() {
        if legal[i] {
            *n = rng.gamma(alpha).max(1e-12);
            sum += *n;
        }
    }
    if sum <= 0.0 {
        return;
    }
    for (i, p) in prior.iter_mut().enumerate() {
        if legal[i] {
            *p = (1.0 - eps) * *p + eps * (noise[i] / sum);
        }
    }
}

/// PUCT：`Q(a) + c * P(a) * sqrt(N_total) / (1 + N(a))`（未访问动作 N=0 → 只按 prior 排）。
fn select_action(node: &Node, legal: &[bool], c_puct: f32) -> u16 {
    let total = node.total_visits() as f32;
    let sqrt_total = total.max(1.0).sqrt();
    let mut best = 0u16;
    let mut best_score = f32::NEG_INFINITY;
    for a in 0..N_ACTIONS {
        if !legal[a] {
            continue;
        }
        let n = node.visits[a] as f32;
        let q = if n > 0.0 { node.wins[a] / n } else { 0.0 };
        let u = c_puct * node.prior[a] * sqrt_total / (1.0 + n);
        let score = q + u;
        if score > best_score {
            best_score = score;
            best = a as u16;
        }
    }
    best
}

/// 递归模拟一次：从 `node` 选择/扩展/备份，返回该步价值（seat 视角）。
///
/// 标准 MCTS：一次模拟最多**扩展一个**新节点（叶），然后沿路径备份；
/// 因此 `eval` 调用次数 = 1（根）+ 最多 simulations 次扩展。
fn simulate<F>(
    node: &mut Node,
    seat: usize,
    cfg: &SearchConfig,
    _rng: &mut Rng64,
    eval: &mut F,
) -> f32
where
    F: FnMut(&Game, usize) -> (Vec<f32>, f32),
{
    if let Some(u) = node.terminal {
        return u;
    }
    let legal = node.game.legal_mask(seat);
    if legal.iter().all(|x| !*x) {
        return terminal_utility(&node.game, seat).unwrap_or(0.0);
    }
    let a = select_action(node, &legal, cfg.c_puct);
    let needs_expand = !node
        .children
        .as_ref()
        .expect("non-terminal node has children")
        .contains_key(&a);
    if needs_expand {
        // 扩展：走一步、推进对手、eval 一次，然后用叶价值直接备份（不再向下递归）。
        let mut g = node.game.clone();
        if g.apply_index(seat, a as usize).is_err() {
            node.terminal = Some(0.0);
            return 0.0;
        }
        let term = advance_to_seat(&mut g, seat);
        let (mut prior, value) = match term {
            Some(u) => (vec![0.0; N_ACTIONS], u),
            None => eval(&g, seat),
        };
        if term.is_none() {
            let legal_child = g.legal_mask(seat);
            sanitize_prior(&mut prior, &legal_child);
        }
        node.children.as_mut().unwrap().insert(
            a,
            Box::new(Node {
                game: g,
                prior,
                visits: vec![0u32; N_ACTIONS],
                wins: vec![0.0f32; N_ACTIONS],
                children: if term.is_some() {
                    None
                } else {
                    Some(HashMap::new())
                },
                terminal: term,
            }),
        );
        node.visits[a as usize] += 1;
        node.wins[a as usize] += value;
        return value;
    }
    let value = {
        let child = node
            .children
            .as_mut()
            .unwrap()
            .get_mut(&a)
            .expect("child exists");
        simulate(child, seat, cfg, _rng, eval)
    };
    node.visits[a as usize] += 1;
    node.wins[a as usize] += value;
    value
}

/// 逐步 MCTS。`eval(game, seat) -> (prior[245], value)` 只在节点**首次扩展**时调用一次；
/// `value` 为 seat 视角的期望 utility。
pub fn search<F>(game: &Game, seat: usize, cfg: &SearchConfig, mut eval: F) -> SearchResult
where
    F: FnMut(&Game, usize) -> (Vec<f32>, f32),
{
    assert!(seat < game.players.len(), "seat out of range");
    let n_actions = N_ACTIONS;
    let mut rng = Rng64::new(cfg.seed);

    let legal = game.legal_mask(seat);
    let n_legal = legal.iter().filter(|x| **x).count();
    if n_legal == 0 {
        // 终局或无需行动：返回空策略（root_value 用终局 utility，否则 0）。
        let u = terminal_utility(game, seat).unwrap_or(0.0);
        return SearchResult {
            pi: vec![0.0; n_actions],
            action: 0,
            root_value: u,
            visits: 0,
        };
    }

    // 根节点：终局则直接返回；否则 eval 一次。
    let terminal = terminal_utility(game, seat);
    let (mut root_prior, root_eval_value) = match terminal {
        Some(u) => (vec![0.0; n_actions], u),
        None => eval(game, seat),
    };
    let mut legal_root = legal.clone();
    sanitize_prior(&mut root_prior, &legal_root);
    mix_dirichlet(
        &mut root_prior,
        &legal_root,
        cfg.dirichlet_alpha,
        cfg.dirichlet_epsilon,
        &mut rng,
    );
    legal_root.shrink_to_fit();
    let mut root = Node {
        game: game.clone(),
        prior: root_prior,
        visits: vec![0u32; n_actions],
        wins: vec![0.0f32; n_actions],
        children: if terminal.is_some() {
            None
        } else {
            Some(HashMap::new())
        },
        terminal,
    };

    // 终局根：π 全 0，root_value = utility。
    if let Some(u) = root.terminal {
        return SearchResult {
            pi: vec![0.0; n_actions],
            action: 0,
            root_value: u,
            visits: 1,
        };
    }

    for _ in 0..cfg.simulations {
        let _ = simulate(&mut root, seat, cfg, &mut rng, &mut eval);
    }

    // 根策略：π = counts^(1/τ)，归一化；τ≤0 → one-hot。
    let counts: Vec<f32> = root.visits.iter().map(|v| *v as f32).collect();
    let mut pi = vec![0.0f32; n_actions];
    if cfg.temperature <= 0.0 {
        let best = (0..n_actions).max_by(|a, b| {
            counts[*a]
                .partial_cmp(&counts[*b])
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        if let Some(b) = best {
            pi[b] = 1.0;
        }
    } else {
        let inv_t = 1.0 / cfg.temperature;
        let mut sum = 0.0f32;
        for i in 0..n_actions {
            if counts[i] > 0.0 {
                let x = counts[i].powf(inv_t);
                pi[i] = x;
                sum += x;
            }
        }
        if sum > 0.0 && sum.is_finite() {
            for x in pi.iter_mut() {
                *x /= sum;
            }
        } else {
            sanitize_prior(&mut pi, &legal);
        }
    }

    // 从 π 采样动作（seeded）。
    let total_visits: u32 = root.visits.iter().sum();
    let root_value = {
        let n = total_visits as f32;
        if n > 0.0 {
            let s: f32 = root.wins.iter().sum();
            s / n
        } else {
            root_eval_value
        }
    };
    let mut action = 0u16;
    let mut r = rng.next_f32();
    for (i, p) in pi.iter().enumerate() {
        if *p <= 0.0 {
            continue;
        }
        if r < *p {
            action = i as u16;
            break;
        }
        r -= *p;
        action = i as u16;
    }
    SearchResult {
        pi,
        action,
        root_value,
        visits: total_visits.max(1),
    }
}

/// 便捷：不带 eval 回调的 uniform prior + value=0（`mcts_search(eval_fn=None)` fallback）。
pub fn uniform_eval(_game: &Game, _seat: usize) -> (Vec<f32>, f32) {
    (vec![1.0; N_ACTIONS], 0.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::RulesConfig;

    #[test]
    fn placement_utility_range() {
        for p in 1..=8u8 {
            let u = placement_utility(p, 8);
            assert!((-1.0..=1.0).contains(&u));
        }
        assert_eq!(placement_utility(1, 8), 1.0);
        assert_eq!(placement_utility(8, 8), -1.0);
        assert_eq!(placement_utility(0, 8), 0.0);
    }

    #[test]
    fn uniform_search_returns_legal_policy_and_is_seeded() {
        let g = Game::new(7, RulesConfig::default());
        // 过英雄选择：所有座位选 0 号英雄 → 招募期。
        let mut g = g;
        for p in 0..g.players.len() {
            let _ = g.apply_index(p, crate::actions::Action::Choose(0).encode());
        }
        let cfg = SearchConfig {
            simulations: 6,
            seed: 123,
            ..Default::default()
        };
        let r1 = search(&g, 0, &cfg, uniform_eval);
        let r2 = search(&g, 0, &cfg, uniform_eval);
        assert_eq!(r1.pi.len(), N_ACTIONS);
        assert_eq!(r1.action, r2.action);
        assert_eq!(r1.pi, r2.pi);
        let sum: f32 = r1.pi.iter().sum();
        assert!((sum - 1.0).abs() < 1e-4, "pi sum {sum}");
        let legal = g.legal_mask(0);
        for i in 0..N_ACTIONS {
            if !legal[i] {
                assert_eq!(r1.pi[i], 0.0, "illegal action {i} has mass");
            }
        }
        assert!(legal[r1.action as usize], "sampled action must be legal");
        assert!(r1.visits >= 1);
    }

    #[test]
    fn eval_called_once_per_expanded_node() {
        use std::cell::Cell;
        let mut g = Game::new(3, RulesConfig::default());
        for p in 0..g.players.len() {
            let _ = g.apply_index(p, crate::actions::Action::Choose(0).encode());
        }
        let calls = Cell::new(0u32);
        let cfg = SearchConfig {
            simulations: 5,
            seed: 1,
            ..Default::default()
        };
        let _ = search(&g, 0, &cfg, |_g, _s| {
            calls.set(calls.get() + 1);
            (vec![1.0; N_ACTIONS], 0.0)
        });
        // 根 1 次 + 每扩展子节点 1 次（≤ sims）。
        assert!(calls.get() >= 1);
        assert!(calls.get() <= cfg.simulations + 1, "evals {}", calls.get());
    }

    #[test]
    fn terminal_root_has_utility_and_empty_pi() {
        let mut g = crate::bot::run_bot_game(0, RulesConfig::default());
        assert!(g.is_over(), "bot game should end");
        // 让它进入终局：placements 已写。
        let r = search(&g, 0, &SearchConfig::default(), uniform_eval);
        assert_eq!(r.pi.len(), N_ACTIONS);
        assert_eq!(r.pi.iter().sum::<f32>(), 0.0);
        assert!((-1.0..=1.0).contains(&r.root_value));
        let place = g.players[0].placement;
        assert_eq!(r.root_value, placement_utility(place, 8));
        let _ = &mut g;
    }
}
