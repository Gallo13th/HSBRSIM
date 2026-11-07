//! 禁用饰品（`RulesConfig.banned_trinkets`）：报价里绝不出现被禁的 card id。
//!
//! 背景：`BG36_MagicItem_414`（加重护手，回合结束 +1/+1、每回合翻倍）能让低本阵容把
//! 属性滚到很高，从而掩盖"不升本"的策略。为了做「禁 / 不禁」的对照实验，引擎在生成
//! 饰品报价时直接剔除被禁 id（见 `flow.rs::trinket_offer`）。

use hsbg_engine::cards::{cid, db};
use hsbg_engine::cards::CardKind;
use hsbg_engine::{Game, RulesConfig};

fn fresh(seed: u64, banned: Vec<String>) -> Game {
    let mut g = Game::new(
        seed,
        RulesConfig {
            banned_trinkets: banned,
            ..Default::default()
        },
    );
    for p in 0..8 {
        g.players[p].pending.clear();
    }
    g
}

#[test]
fn banned_trinket_never_offered() {
    const BAN: &str = "BG36_MagicItem_414";
    let banned_index = db()
        .find(BAN)
        .expect("加重护手必须在卡表里");
    let mut seen_any = false;
    for seed in 0..24u64 {
        let mut g = fresh(seed, vec![BAN.to_string()]);
        // 给足金币/等级，保证报价不会被"买不起"过滤掉
        for p in 0..8 {
            g.players[p].gold = 40;
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
fn banning_every_lesser_trinket_yields_empty_offer() {
    // 枚举卡表里所有 lesser 饰品并全部禁掉：报价必须退化为空（引擎既有逻辑会跳过报价），
    // 且不能 panic。
    let mut banned = Vec::new();
    for i in 0..db().len() {
        let c = db().get(hsbg_engine::cards::CardId(i as u16));
        if c.kind == CardKind::TrinketLesser {
            banned.push(c.id.clone());
        }
    }
    assert!(banned.len() > 3, "卡表里的 lesser 饰品太少：{}", banned.len());
    let mut g = Game::new(
        7,
        RulesConfig {
            banned_trinkets: banned,
            ..Default::default()
        },
    );
    for p in 0..8 {
        g.players[p].pending.clear();
        g.players[p].gold = 40;
    }
    let offer = g.trinket_offer(0, CardKind::TrinketLesser);
    assert!(offer.is_empty(), "全禁之后仍有报价：{offer:?}");
}
