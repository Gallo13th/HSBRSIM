//! P4-M1：逐步 MCTS 搜索核（`hsbg_engine::search`）集成测试。
//!
//! 统一用 uniform eval（prior=全 1、value=0）验证：策略只在合法动作上、和为 1、
//! 同 seed 结果一致、终局 utility 公式、eval 调用次数上限。

use hsbg_engine::actions::Action;
use hsbg_engine::config::RulesConfig;
use hsbg_engine::search::{SearchConfig, placement_utility, search, uniform_eval};
use hsbg_engine::{Game, N_ACTIONS};

/// 过英雄选择、进入第 1 回合招募期的 Game（所有座位选 0 号英雄）。
fn game(seed: u64) -> Game {
    let mut g = Game::new(seed, RulesConfig::default());
    for p in 0..g.players.len() {
        g.apply_index(p, Action::Choose(0).encode())
            .expect("hero choice");
    }
    g
}

#[test]
fn uniform_search_policy_is_legal_and_normalized() {
    let g = game(7);
    let cfg = SearchConfig {
        simulations: 8,
        seed: 11,
        ..Default::default()
    };
    let r = search(&g, 0, &cfg, uniform_eval);
    assert_eq!(r.pi.len(), N_ACTIONS);
    let sum: f32 = r.pi.iter().sum();
    assert!((sum - 1.0).abs() < 1e-4, "sum {sum}");
    let legal = g.legal_mask(0);
    for i in 0..N_ACTIONS {
        if !legal[i] {
            assert_eq!(r.pi[i], 0.0, "illegal action {i}");
        }
    }
    assert!(legal[r.action as usize], "sampled action illegal");
    assert!((-1.0..=1.0).contains(&r.root_value));
    assert!(r.visits >= 1);
}

#[test]
fn same_seed_same_policy_and_temperature_zero_is_one_hot() {
    let g = game(3);
    let cfg = SearchConfig {
        simulations: 6,
        seed: 42,
        ..Default::default()
    };
    let a = search(&g, 0, &cfg, uniform_eval);
    let b = search(&g, 0, &cfg, uniform_eval);
    assert_eq!(a.pi, b.pi);
    assert_eq!(a.action, b.action);

    // τ=0：one-hot 到“访问最多”的动作。
    let cfg0 = SearchConfig {
        simulations: 6,
        temperature: 0.0,
        seed: 42,
        ..Default::default()
    };
    let r = search(&g, 0, &cfg0, uniform_eval);
    let ones = r.pi.iter().filter(|x| **x == 1.0).count();
    assert_eq!(ones, 1);
    assert_eq!(r.pi[r.action as usize], 1.0);
}

#[test]
fn zero_simulations_returns_eval_prior() {
    let g = game(5);
    let cfg = SearchConfig {
        simulations: 0,
        seed: 0,
        ..Default::default()
    };
    let r = search(&g, 0, &cfg, uniform_eval);
    let legal = g.legal_mask(0);
    let n_legal = legal.iter().filter(|x| **x).count();
    for i in 0..N_ACTIONS {
        if legal[i] {
            assert!((r.pi[i] - 1.0 / n_legal as f32).abs() < 1e-5);
        } else {
            assert_eq!(r.pi[i], 0.0);
        }
    }
}

#[test]
fn terminal_root_utility_matches_placement() {
    let g = hsbg_engine::bot::run_bot_game(0, RulesConfig::default());
    assert!(g.is_over());
    let r = search(&g, 0, &SearchConfig::default(), uniform_eval);
    assert_eq!(r.pi.iter().sum::<f32>(), 0.0);
    assert_eq!(r.root_value, placement_utility(g.players[0].placement, 8));
    assert!((-1.0..=1.0).contains(&r.root_value));
}

#[test]
fn eval_call_count_is_bounded() {
    use std::cell::Cell;
    let g = game(9);
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
    assert!(calls.get() >= 1, "root eval");
    assert!(calls.get() <= cfg.simulations + 1, "evals {}", calls.get());
}
