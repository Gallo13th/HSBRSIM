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

use crate::actions::{Action, N_ACTIONS};
use crate::bot;
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
        let action = bot::choose_action(game, seat);
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
        // 纯 no-op（Freeze/Refresh/Cancel 等）不产生可比较的回合末状态；跳过，
        // 否则 pairwise 分数会因“completion 帮买牌”而反复选它。
        if action != Action::EndTurn && state_key(&g, seat) == state_key(root, seat) {
            continue;
        }
        // Freeze/Refresh 是“不消耗回合”的界面动作；不要把 bot 补完的后续买牌
        // 算进它们的价值，否则基线会反复 Freeze/Refresh 来“借”completion 买牌。
        if !matches!(action, Action::Freeze | Action::Refresh)
            && !complete_turn(&mut g, seat, cfg.max_steps_per_turn)
        {
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
    let mut remaining = cfg.states_budget;
    let mut by_action: Vec<(u16, Vec<TurnState>)> = Vec::new();
    for (i, legal) in mask.iter().enumerate().take(N_ACTIONS) {
        if !legal || remaining == 0 {
            continue;
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
        // 避免“完成本回合”的评估把纯无进展动作（Freeze/Refresh）排到 Buy/Play 前：
        // 这些动作的 completion 可能由 bot 买牌，但真实执行这一帧并没有买。
        let score = score
            + match Action::decode(action as usize) {
                Some(Action::Freeze) | Some(Action::Refresh) => -0.05,
                Some(Action::EndTurn) => -0.02,
                _ => 0.0,
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
