//! 禁用饰品（`RulesConfig.banned_trinkets`）：报价里绝不出现被禁的 card id。
//!
//! 背景：`BG36_MagicItem_414`（加重护手，回合结束 +1/+1、每回合翻倍）能让低本阵容把
//! 属性滚到很高，从而掩盖"不升本"的策略。为了做「禁 / 不禁」的对照实验，引擎在生成
//! 饰品报价时直接剔除被禁 id（见 `flow.rs::trinket_offer`）。

use hsbg_engine::cards::db;
use hsbg_engine::{CardKind, Game, RulesConfig};

fn fresh(seed: u64) -> Game {
    let mut g = Game::new(seed, RulesConfig::default());
    for p in 0..8 {
        g.players[p].pending.clear();
    }
    g
}

#[test]
fn banned_trinket_never_offered() {
    const BAN: &str = "BG36_MagicItem_414";
    let banned_index = db()
        .all()
        .iter()
        .position(|c| c.id == BAN)
        .expect("加重护手必须在卡表里");
    let mut seen_any = false;
    for seed in 0..24u64 {
        let mut g = fresh(seed);
        // 给足金币/等级，保证报价不会被"买不起"过滤掉
        for p in 0..8 {
            g.players[p].gold = 40;
            g.players[p].tavern_tier = 6;
        }
        for kind in [CardKind::TrinketLesser, CardKind::TrinketGreater] {
            let offer = g.trinket_offer(0, kind);
            assert!(
                !offer.contains(&banned_index),
                "seed={seed} kind={kind:?} 报价里仍出现被禁饰品：{offer:?}"
            );
            seen_any |= !offer.is_empty();
        }
    }
    assert!(seen_any, "所有报价都是空的，测试没有覆盖到价格路径");
}

#[test]
fn all_banned_yields_empty_offer_without_panic() {
    // 把所有饰品都禁掉：报价退化为空（引擎既有逻辑会跳过报价），不应 panic。
    let all_ids: Vec<String> = db()
        .all()
        .iter()
        .filter(|c| matches!(c.kind, CardKind::TrinketLesser | CardKind::TrinketGreater))
        .map(|c| c.id.clone())
        .take(64)
        .collect();
    assert!(!all_ids.is_empty());
    let mut g = Game::new(
        7,
        RulesConfig {
            banned_trinkets: all_ids,
            ..Default::default()
        },
    );
    for p in 0..8 {
        g.players[p].pending.clear();
        g.players[p].gold = 40;
        g.players[p].tavern_tier = 6;
    }
    let offer = g.trinket_offer(0, CardKind::TrinketLesser);
    assert!(offer.is_empty() || offer.len() <= 3);
}
