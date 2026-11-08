//! 回合内状态枚举 + 两两战斗胜率搜索（Rust 版 TurnSearch）。
//!
//! 与旧的 Python `hsbg/search/turn_search.py` 同形，但不做完整 bot rollout：
//! 1. 从当前合法动作 `a` 出发，执行 `a`（不推进回合）；
//! 2. 用引擎内 bot 完成**当前回合剩余动作**，在 end_turn 前停住；
//! 3. 枚举最多 `states_budget` 个回合末状态；
//! 4. 对状态两两用真实 `simulate_combat` 计算胜率；
//! 5. 每个动作取可达状态的 max/mean 分数，argmax 执行，随后在新状态重搜。
//!
//! 这是“搜索基线”，不是策略网络；没有 eval 回调、没有跨回合预测。

use std::collections::HashSet;

use crate::actions::{A_CHOOSE, Action, N_ACTIONS};
use crate::engine::{Game, Phase};
use crate::rng::Rng;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ActionAggregate {
    Max,
    Mean,
}

#[derive(Clone, Copy, Debug)]
pub struct TurnSearchConfig {
    pub states_budget: usize,
    pub samples_per_action: usize,
    pub combat_samples: usize,
    pub max_steps_per_turn: usize,
    pub seed: u64,
    pub aggregate: ActionAggregate,
}

impl Default for TurnSearchConfig {
    fn default() -> Self {
        TurnSearchConfig {
            states_budget: 24,
            samples_per_action: 1,
            combat_samples: 1,
            max_steps_per_turn: 40,
            seed: 0,
            aggregate: ActionAggregate::Max,
        }
    }
}

impl TurnSearchConfig {
    fn normalized(mut self) -> Self {
        self.states_budget = self.states_budget.max(2);
        self.samples_per_action = self.samples_per_action.max(1);
        self.combat_samples = self.combat_samples.max(1);
        self.max_steps_per_turn = self.max_steps_per_turn.max(1);
        self
    }
}

#[derive(Clone, Debug)]
pub struct TurnSearchResult {
    /// Flat action index (0..N_ACTIONS); 0 (EndTurn) if no move was found.
    pub action: u16,
    /// 每个动作的分数（未评估动作为 0）。
    pub action_scores: Vec<f32>,
    /// 枚举到的回合末状态数。
    pub n_states: usize,
    /// 实际执行的 pairwise 战斗数。
    pub n_combats: usize,
    /// 最好动作的分数。
    pub best_score: f32,
}

#[derive(Clone, Debug)]
struct TurnState {
    game: Game,
}

/// 旧 Python `hsbg.agents.heuristic.HeuristicPolicy` 的精简 Rust 移植。
/// 只用于 completion（旧 TurnSearch 的 completion_policy=heuristic），不是最终策略。
fn heuristic_action(game: &Game, seat: usize) -> Option<Action> {
    let mask = game.legal_mask(seat);
    let p = &game.players[seat];
    let playable = |a: Action| mask[a.encode()];
    let board_full = p.board.len() >= game.cfg.board_size;
    let hand_full = p.hand.len() >= game.cfg.hand_size;

    // Pending choice：旧 `choose_option_index` 取价值最高的选项；这里保底选第一个合法项。
    let choices: Vec<usize> = (0..N_ACTIONS)
        .filter(|i| mask[*i])
        .filter(|i| matches!(Action::decode(*i), Some(Action::Choose(_))))
        .collect();
    if !choices.is_empty() {
        return Some(Action::Choose(choices[0] - A_CHOOSE));
    }

    // 1) 打出手牌随从：价值 atk*1.1+hp，优先追加到最右。
    let mut best_play: Option<(f32, Action)> = None;
    for (h, card) in p.hand.iter().enumerate() {
        let Some(m) = card.item.as_minion() else {
            continue;
        };
        if card.locked > 0 {
            continue;
        }
        let val = m.atk as f32 * 1.1 + m.hp as f32;
        for pos in 0..=p.board.len() {
            let a = Action::Play { hand: h, pos };
            if playable(a) {
                let score = val + if pos == p.board.len() { 0.5 } else { 0.0 };
                if best_play.as_ref().is_none_or(|(b, _)| score > *b) {
                    best_play = Some((score, a));
                }
            }
        }
    }
    if let Some((_, a)) = best_play {
        return Some(a);
    }

    // 2) 手牌法术（清手牌，为买随从腾空间）。
    for (h, card) in p.hand.iter().enumerate() {
        if card.item.as_minion().is_some() || card.locked > 0 {
            continue;
        }
        for pos in 0..=p.board.len() {
            let a = Action::Play { hand: h, pos };
            if playable(a) {
                return Some(a);
            }
        }
    }

    // 3) 升级（前中期；留 3 金买牌）。
    if p.tier < 6 && game.turn <= 8 && p.upgrade_cost >= 0 {
        let a = Action::Upgrade;
        if playable(a) && p.gold >= p.upgrade_cost + 3 {
            return Some(a);
        }
    }

    // 4) 买随从：最高价值；满场时只买比最弱随从强的。
    if !hand_full {
        let weakest = p
            .board
            .iter()
            .map(|m| m.atk as f32 * 1.1 + m.hp as f32)
            .fold(f32::INFINITY, f32::min);
        let mut best: Option<(f32, Action)> = None;
        for (i, slot) in p.shop.iter().enumerate() {
            let Some(m) = slot.item.as_minion() else {
                continue;
            };
            let val = m.atk as f32 * 1.1 + m.hp as f32;
            if board_full && val < weakest + 1.5 {
                continue;
            }
            let a = Action::Buy(i);
            if playable(a) && best.as_ref().is_none_or(|(b, _)| val > *b) {
                best = Some((val, a));
            }
        }
        if let Some((_, a)) = best {
            return Some(a);
        }
    }

    // 5) 满场换血：有更强的手牌/酒馆随从时卖掉最弱。
    if board_full {
        let weakest_i = p
            .board
            .iter()
            .enumerate()
            .min_by_key(|(_, m)| m.atk * 11 + m.hp * 10)
            .map(|(i, _)| i);
        if let Some(i) = weakest_i {
            let w = p.board[i].atk as f32 * 1.1 + p.board[i].hp as f32;
            let hand_strong = p
                .hand
                .iter()
                .filter_map(|h| h.item.as_minion())
                .any(|m| m.atk as f32 * 1.1 + m.hp as f32 >= w + 1.5);
            let shop_strong = p
                .shop
                .iter()
                .filter_map(|s| s.item.as_minion())
                .any(|m| m.atk as f32 * 1.1 + m.hp as f32 >= w + 1.5);
            let a = Action::Sell(i);
            if (hand_strong || shop_strong) && playable(a) {
                return Some(a);
            }
        }
    }

    // 6) 一次性的 Activate / Dark Gift / 英雄技能。
    for i in 0..N_ACTIONS {
        let Some(a) = Action::decode(i) else { continue };
        if matches!(
            a,
            Action::Activate(_) | Action::DarkGift | Action::HeroPower(_)
        ) && mask[i]
        {
            return Some(a);
        }
    }

    // 6) 刷新（旧 heuristic 的 reroll）。
    if playable(Action::Refresh) {
        return Some(Action::Refresh);
    }
    Some(Action::EndTurn)
}

/// 不用 `bot::play_turn`，因为它会执行 EndTurn 推进到下一回合；
/// 这里只完成当前回合，遇到 EndTurn 就停在回合末状态。
fn complete_turn(game: &mut Game, seat: usize, max_steps: usize) -> bool {
    for _ in 0..max_steps {
        if game.phase != Phase::Recruit || game.turn == 0 {
            return true;
        }
        if !game.needs_action(seat) {
            return true;
        }
        let action = heuristic_action(game, seat).unwrap_or(Action::EndTurn);
        if action == Action::EndTurn {
            return true;
        }
        if game.apply(seat, action).is_err() {
            return false;
        }
    }
    true
}

fn state_key(game: &Game, seat: usize) -> String {
    let p = &game.players[seat];
    let board: Vec<String> = p
        .board
        .iter()
        .map(|m| {
            format!(
                "{}:{}:{}:{}:{}:{}",
                m.card.0, m.atk, m.hp, m.golden, m.tier, m.kw.0
            )
        })
        .collect();
    let hand: Vec<String> = p
        .hand
        .iter()
        .map(|h| format!("{}:{}", h.item.card().0, h.locked))
        .collect();
    format!(
        "{}|{}|{}|{}|{:?}|{:?}",
        p.gold,
        p.tier,
        p.health,
        p.board.len(),
        board,
        hand
    )
}

fn enemy_seat(seat: usize, game: &Game) -> Option<usize> {
    (0..game.players.len()).find(|p| *p != seat && game.players[*p].alive)
}

/// 把 `b` 的目标座位战团复制到 `a` 的对应座位，然后打一场真实战斗。
/// 返回 side-a 的胜率（0.5=平局）。
fn combat_winrate(a: &Game, b: &Game, seat: usize, seconds: usize, seed: u64) -> f32 {
    let Some(other) = enemy_seat(seat, a) else {
        return 0.5;
    };
    let mut wins = 0.0f32;
    let n = seconds.max(1);
    for k in 0..n {
        let mut g = a.clone();
        // 只替换战斗对手的战团/等级：用**状态 b 中 seat 自己的战团**作为对手。
        // （状态 b 的 `other` 座位不是我们要比较的 warband。）
        g.players[other].board = b.players[seat].board.clone();
        g.players[other].tier = b.players[seat].tier;
        g.players[other].health = b.players[seat].health;
        // 每个比较用独立 seed，避免同一状态重复战斗完全相同。
        g.rng = Rng::new(seed ^ (k as u64).wrapping_mul(0xD1B5_4A32_D192_ED03));
        let out = g.simulate_combat(seat, Some(other), None);
        if out.winner == 0 {
            wins += 1.0;
        } else if out.winner == 2 {
            wins += 0.5;
        }
    }
    wins / n as f32
}

fn collect_action_states(
    root: &Game,
    seat: usize,
    action: Action,
    cfg: &TurnSearchConfig,
    remaining: usize,
) -> Vec<TurnState> {
    if remaining == 0 {
        return Vec::new();
    }
    // EndTurn 本身：当前状态是候选回合末状态。
    if action == Action::EndTurn {
        return vec![TurnState { game: root.clone() }];
    }
    let mut out = Vec::new();
    for sample in 0..cfg.samples_per_action {
        if out.len() >= remaining {
            break;
        }
        let mut g = root.clone();
        if cfg.samples_per_action > 1 {
            g.rng = Rng::new(
                cfg.seed
                    ^ (action.encode() as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15)
                    ^ (sample as u64).wrapping_mul(0xD1B5_4A32_D192_ED03),
            );
        }
        if g.apply(seat, action).is_err() {
            continue;
        }
        if g.phase == Phase::GameOver || g.turn != root.turn {
            continue;
        }
        if !complete_turn(&mut g, seat, cfg.max_steps_per_turn) {
            continue;
        }
        if g.phase == Phase::GameOver || g.turn != root.turn {
            continue;
        }
        out.push(TurnState { game: g });
    }
    out
}

fn unique_states(
    by_action: &[(u16, Vec<TurnState>)],
    seat: usize,
    budget: usize,
) -> (Vec<TurnState>, Vec<(u16, Vec<usize>)>) {
    // 保留动作分组；状态去重是全局的，避免同一战团重复增加 pairwise 权重。
    let mut seen = HashSet::new();
    let mut flat: Vec<TurnState> = Vec::new();
    let mut grouped: Vec<(u16, Vec<usize>)> = Vec::new();
    for (action, states) in by_action {
        let mut ids = Vec::new();
        for state in states {
            if flat.len() >= budget {
                break;
            }
            let key = state_key(&state.game, seat);
            if !seen.insert(key) {
                continue;
            }
            ids.push(flat.len());
            flat.push(state.clone());
        }
        if !ids.is_empty() {
            grouped.push((*action, ids));
        }
    }
    (flat, grouped)
}

fn action_rank(action: &Action) -> u8 {
    // 对齐旧 Python driver.enumerate_actions 的顺序：
    // buys → plays → sells → moves → powers → activate → upgrade → reroll → freeze
    // → dark gift → end_turn。小 states_budget 时顺序会直接决定哪些动作进入搜索。
    match action {
        Action::Buy(_) => 0,
        Action::Play { .. } | Action::Magnetize { .. } => 1,
        Action::Sell(_) => 2,
        Action::Move { .. } => 3,
        Action::HeroPower(_) => 4,
        Action::Activate(_) => 5,
        Action::Upgrade => 6,
        Action::Refresh => 7,
        Action::Freeze => 8,
        Action::DarkGift => 9,
        Action::Choose(_) | Action::Cancel => 10,
        Action::EndTurn => 11,
    }
}

/// 执行一次 TurnSearch 决策；返回动作分数和状态/战斗计数。
pub fn turn_search(game: &Game, seat: usize, cfg: TurnSearchConfig) -> TurnSearchResult {
    let cfg = cfg.normalized();
    let n = game.players.len();
    let mut fallback = TurnSearchResult {
        action: Action::EndTurn.encode() as u16,
        action_scores: vec![0.0; N_ACTIONS],
        n_states: 0,
        n_combats: 0,
        best_score: 0.0,
    };
    if seat >= n || game.phase == Phase::GameOver {
        return fallback;
    }
    let mask = game.legal_mask(seat);
    let mut candidates: Vec<(u8, usize)> = Vec::new();
    for (i, legal) in mask.iter().enumerate().take(N_ACTIONS) {
        if *legal {
            if let Some(action) = Action::decode(i) {
                // Cancel 只用于回退 targeting；TurnSearch 不应该把回退当动作。
                if matches!(action, Action::Cancel) {
                    continue;
                }
                // 旧 driver 只在“当前未冻结”时生成 Freeze；Rust 动作空间里
                // 冻结后仍可再次按 Freeze（切回未冻结），会形成 no-op 循环。
                if matches!(action, Action::Freeze) && game.players[seat].is_frozen() {
                    continue;
                }
                candidates.push((action_rank(&action), i));
            }
        }
    }
    candidates.sort_by_key(|(rank, idx)| (*rank, *idx));
    let mut remaining = cfg.states_budget;
    let mut by_action: Vec<(u16, Vec<TurnState>)> = Vec::new();
    for (_, i) in candidates {
        if remaining == 0 {
            break;
        }
        let Some(action) = Action::decode(i) else {
            continue;
        };
        let states = collect_action_states(game, seat, action, &cfg, remaining);
        if states.is_empty() {
            continue;
        }
        remaining = remaining.saturating_sub(states.len().min(remaining));
        by_action.push((i as u16, states));
    }
    let (flat, grouped) = unique_states(&by_action, seat, cfg.states_budget);
    if grouped.is_empty() {
        return fallback;
    }
    let n_states = flat.len();
    let mut mat = vec![0.0f32; n_states * n_states];
    let mut n_combats = 0usize;
    for i in 0..n_states {
        for j in (i + 1)..n_states {
            let wr = combat_winrate(
                &flat[i].game,
                &flat[j].game,
                seat,
                cfg.combat_samples,
                cfg.seed ^ (i as u64).wrapping_mul(1009) ^ (j as u64).wrapping_mul(9176),
            );
            mat[i * n_states + j] = wr;
            mat[j * n_states + i] = 1.0 - wr;
            n_combats += cfg.combat_samples;
        }
    }
    let mut state_scores = vec![0.0f32; n_states];
    for i in 0..n_states {
        let mut sum = 0.0f32;
        for j in 0..n_states {
            if i != j {
                sum += mat[i * n_states + j];
            }
        }
        state_scores[i] = sum / (n_states.saturating_sub(1).max(1) as f32);
    }
    let mut best_action = Action::EndTurn.encode() as u16;
    let mut best_score = f32::NEG_INFINITY;
    for (action, ids) in grouped {
        let vals: Vec<f32> = ids.iter().map(|i| state_scores[*i]).collect();
        let score = match cfg.aggregate {
            ActionAggregate::Max => vals.into_iter().fold(f32::NEG_INFINITY, f32::max),
            ActionAggregate::Mean => vals.iter().sum::<f32>() / vals.len().max(1) as f32,
        };
        if action < N_ACTIONS as u16 {
            fallback.action_scores[action as usize] = score;
        }
        if score > best_score {
            best_score = score;
            best_action = action;
        }
    }
    fallback.action = best_action;
    fallback.n_states = n_states;
    fallback.n_combats = n_combats;
    fallback.best_score = best_score;
    fallback
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::RulesConfig;

    fn started_game(seed: u64) -> Game {
        let mut g = Game::new(seed, RulesConfig::default());
        for p in 0..g.players.len() {
            if g.phase == Phase::HeroSelect {
                let _ = g.apply_index(p, Action::Choose(0).encode());
            }
        }
        g
    }

    #[test]
    fn returns_legal_action_and_budgeted_states() {
        let g = started_game(11);
        let legal = g.legal_mask(0);
        let r = turn_search(
            &g,
            0,
            TurnSearchConfig {
                states_budget: 6,
                samples_per_action: 1,
                combat_samples: 1,
                max_steps_per_turn: 12,
                seed: 3,
                ..Default::default()
            },
        );
        assert!(r.action < N_ACTIONS as u16);
        assert!(
            legal[r.action as usize],
            "action {} must be legal",
            r.action
        );
        assert!(r.n_states > 0);
        assert!(r.n_states <= 6);
        assert!(r.action_scores.len() == N_ACTIONS);
        assert!(r.action_scores[r.action as usize].is_finite());
    }

    #[test]
    fn is_deterministic_with_same_seed() {
        let g = started_game(12);
        let cfg = TurnSearchConfig {
            states_budget: 4,
            samples_per_action: 1,
            combat_samples: 1,
            max_steps_per_turn: 8,
            seed: 9,
            ..Default::default()
        };
        let a = turn_search(&g, 0, cfg);
        let b = turn_search(&g, 0, cfg);
        assert_eq!(a.action, b.action);
        assert_eq!(a.n_states, b.n_states);
        assert_eq!(a.action_scores, b.action_scores);
    }
}
