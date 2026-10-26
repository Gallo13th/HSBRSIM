//! P3 批次 B 卡牌契约测试（6 池内随从 + 2 池内酒馆法术）。
//!
//! 每张卡至少一个真实引擎路径用例（`Action::Play` / `Action::Activate` / 直接 hook），
//! 覆盖普通与金色行为差异；随机效果通过收窄 `Game::spell_universe`（引擎真实随机入口）
//! 变成确定性断言，不 mock 随机。
//!
//! 运行：cargo test --release -p hsbg-engine --test p3_cards_b

mod common;

use common::*;
use hsbg_engine::cards::CardKind;
use hsbg_engine::script::{Me, script};

/// Player hand card ids, left to right.
fn hand_cards(g: &Game, p: PlayerId) -> Vec<CardId> {
    g.players[p].hand.iter().map(|h| h.item.card()).collect()
}

/// A `Me` for a minion already on `c`'s board.
fn me_of(c: &hsbg_engine::engine::Ctx, side: usize, eid: u32) -> Me {
    let m = c.minion(eid).unwrap();
    Me {
        side,
        eid,
        card: m.card,
        golden: m.golden,
        opt: 0,
        pos: 0,
        data: 0,
    }
}

// ══════════════════════════════════════════════════════════════════════
// BG33_319 Rimescale Priestess + 其 Spellcraft 法术 BG33_319t/_Gt
// ══════════════════════════════════════════════════════════════════════

#[test]
fn rimescale_priestess_gives_its_spellcraft_spell() {
    // 打出普通随从：引擎按数据 spellcraft 字段直接给 BG33_319t（临时法术）。
    let mut g = game(1101);
    give(&mut g, 0, "BG33_319");
    play_last(&mut g, 0);
    assert_eq!(g.players[0].board.len(), 1);
    assert_eq!(hand_cards(&g, 0), vec![cid("BG33_319t")]);

    // 金色随从给金色法术（数据 spellcraft 字段 = BG33_319_Gt）。打出金色随从本身
    // 还会按规则给三连奖励卡（TB_BaconShop_Triples_01），故用 contains 断言。
    let mut g = game(1102);
    give(&mut g, 0, "BG33_319_G");
    play_last(&mut g, 0);
    let hand = hand_cards(&g, 0);
    assert!(
        hand.contains(&cid("BG33_319_Gt")),
        "golden minion gives the golden spell, hand: {hand:?}"
    );
}

#[test]
fn rime_or_reason_gets_a_stat_giving_tavern_spell() {
    // 收窄法术池到一张“给属性”酒馆法术：普通令牌得 1 张，金色令牌得 2 张。
    let mut g = game(1103);
    g.spell_universe = vec![cid("BG28_897")];
    give(&mut g, 0, "BG33_319t");
    play_last(&mut g, 0);
    assert_eq!(hand_cards(&g, 0), vec![cid("BG28_897")]);

    let mut g = game(1104);
    g.spell_universe = vec![cid("BG28_897")];
    give(&mut g, 0, "BG33_319_Gt");
    play_last(&mut g, 0);
    assert_eq!(hand_cards(&g, 0), vec![cid("BG28_897"), cid("BG28_897")]);
}

// ══════════════════════════════════════════════════════════════════════
// BG32_815 Shifting Tide（池内酒馆法术）
// ══════════════════════════════════════════════════════════════════════

#[test]
fn shifting_tide_repeats_for_a_naga() {
    // 非纳迦目标：+1/+1 两次 = +2/+2。
    let mut g = game(1201);
    set_board(&mut g, 0, &["BG20_100"]);
    let before = stats(&g, 0)[0];
    give(&mut g, 0, "BG32_815");
    cast_on(&mut g, 0, 0);
    assert_eq!(stats(&g, 0)[0], (before.0 + 2, before.1 + 2));

    // 纳迦目标（BG23_004 Deep-Sea Angler）：整套重复 = 共 4 次。
    let mut g = game(1202);
    set_board(&mut g, 0, &["BG23_004"]);
    let before = stats(&g, 0)[0];
    give(&mut g, 0, "BG32_815");
    cast_on(&mut g, 0, 0);
    assert_eq!(stats(&g, 0)[0], (before.0 + 4, before.1 + 4));
}

// ══════════════════════════════════════════════════════════════════════
// BG35_922 Queen's Command（池内酒馆法术）
// ══════════════════════════════════════════════════════════════════════

#[test]
fn queens_command_gives_nagas_an_extra_buff() {
    let mut g = game(1301);
    // [纳迦, 野猪人]
    set_board(&mut g, 0, &["BG23_004", "BG20_100"]);
    let before = stats(&g, 0);
    give(&mut g, 0, "BG35_922");
    play_last(&mut g, 0);
    let after = stats(&g, 0);
    assert_eq!((after[0].0 - before[0].0, after[0].1 - before[0].1), (4, 4));
    assert_eq!((after[1].0 - before[1].0, after[1].1 - before[1].1), (2, 2));
}

// ══════════════════════════════════════════════════════════════════════
// BG34_925 Seafloor Recruiter
// ══════════════════════════════════════════════════════════════════════

#[test]
fn seafloor_recruiter_casts_chefs_choice_on_the_right_neighbor() {
    let mut g = game(1401);
    g.players[0].tier = 4;
    // [招募者, 野猪人]：Rally 对右侧野猪人施放 Chef's Choice -> 手牌得到同种族随从。
    set_board(&mut g, 0, &["BG34_925", "BG20_100"]);
    let eid = g.players[0].board[0].eid;
    let rally = script(cid("BG34_925")).unwrap().rally.unwrap();
    {
        let mut c = combat_ctx(&mut g);
        let me = me_of(&c, 0, eid);
        rally(&mut c, me, 0);
    }
    let hand = hand_cards(&g, 0);
    assert_eq!(hand.len(), 1, "expected one card from Chef's Choice");
    let d = db().get(hand[0]);
    assert_eq!(d.kind, CardKind::Minion);
    assert!(d.races.intersects(Races::QUILBOAR), "same type as target");
    assert_ne!(
        hand[0],
        cid("BG20_100"),
        "a different minion, not the target"
    );
}

#[test]
fn seafloor_recruiter_does_nothing_when_rightmost() {
    let mut g = game(1402);
    g.players[0].tier = 4;
    set_board(&mut g, 0, &["BG20_100", "BG34_925"]);
    let eid = g.players[0].board[1].eid;
    let rally = script(cid("BG34_925")).unwrap().rally.unwrap();
    {
        let mut c = combat_ctx(&mut g);
        let me = me_of(&c, 0, eid);
        rally(&mut c, me, 0);
    }
    assert!(hand_cards(&g, 0).is_empty());
}

#[test]
fn golden_seafloor_recruiter_casts_twice() {
    let mut g = game(1403);
    g.players[0].tier = 4;
    set_board(&mut g, 0, &["BG34_925_G", "BG20_100"]);
    let eid = g.players[0].board[0].eid;
    let rally = script(cid("BG34_925")).unwrap().rally.unwrap();
    {
        let mut c = combat_ctx(&mut g);
        let me = me_of(&c, 0, eid);
        rally(&mut c, me, 0);
    }
    assert_eq!(hand_cards(&g, 0).len(), 2, "golden: twice");
}

// ══════════════════════════════════════════════════════════════════════
// BG35_921 Abyssal Bruiser
// ══════════════════════════════════════════════════════════════════════

#[test]
fn abyssal_bruiser_grows_with_each_tavern_spell() {
    let mut g = game(1501);
    give(&mut g, 0, "BG35_921");
    play_last(&mut g, 0);
    assert_eq!(stats(&g, 0)[0], (2, 1));
    assert!(
        g.players[0].board[0].has(Kw::DIVINE_SHIELD),
        "printed Divine Shield"
    );
    // 加一个哑巴随从，法术打它（Bruiser 只吃“本局酒馆法术计数”光环，不吃该法术 buff）。
    let dummy = minion(&mut g, 0, "BG20_100");
    g.players[0].board.push(dummy);
    for _ in 0..2 {
        give(&mut g, 0, "BG28_897");
        cast_on(&mut g, 0, 1);
    }
    assert_eq!(stats(&g, 0)[0], (2 + 2 * 2, 1 + 2), "2 spells: +2/+1 each");
    assert_eq!(stats(&g, 0)[1], (2 + 4, 1 + 4), "dummy took both spells");
}

#[test]
fn abyssal_bruiser_counts_spells_cast_before_it_was_played() {
    let mut g = game(1502);
    set_board(&mut g, 0, &["BG20_100"]);
    // 先在它入场前施放 2 个酒馆法术（计数是 player-level，需回溯补算）。
    for _ in 0..2 {
        give(&mut g, 0, "BG28_897");
        cast_on(&mut g, 0, 0);
    }
    give(&mut g, 0, "BG35_921");
    play_last(&mut g, 0);
    let bruiser = g.players[0].board.last().unwrap();
    assert_eq!((bruiser.atk, bruiser.hp), (2 + 4, 1 + 2));
}

// ══════════════════════════════════════════════════════════════════════
// BG36_622 Torrential Ruiner
// ══════════════════════════════════════════════════════════════════════

#[test]
fn torrential_ruiner_buffs_only_for_spells_on_a_naga() {
    // [毁灭者(纳迦), 野猪人, 纳迦]
    let mut g = game(1601);
    set_board(&mut g, 0, &["BG36_622", "BG20_100", "BG23_004"]);
    let before = stats(&g, 0);
    // 对非纳迦（第 2 格）施法：不触发。
    give(&mut g, 0, "BG28_897");
    cast_on(&mut g, 0, 1);
    let mid = stats(&g, 0);
    assert_eq!(mid[0], before[0], "non-Naga target: no Ruiner buff");
    // 对纳迦（第 3 格）施法：所有随从 +2/+3（目标另有法术本身 +2/+2）。
    give(&mut g, 0, "BG28_897");
    cast_on(&mut g, 0, 2);
    let after = stats(&g, 0);
    assert_eq!((after[0].0 - mid[0].0, after[0].1 - mid[0].1), (2, 3));
    assert_eq!((after[1].0 - mid[1].0, after[1].1 - mid[1].1), (2, 3));
    assert_eq!(
        (after[2].0 - mid[2].0, after[2].1 - mid[2].1),
        (2 + 2, 3 + 2)
    );
}

// ══════════════════════════════════════════════════════════════════════
// BG36_921 Fleeing Fugitive
// ══════════════════════════════════════════════════════════════════════

#[test]
fn fleeing_fugitive_gains_health_only_when_aimed_at() {
    let mut g = game(1701);
    set_board(&mut g, 0, &["BG36_921", "BG20_100"]);
    let before = stats(&g, 0);
    // 法术打本随从：+2/+2（法术）+ 0/+1（触发）。
    give(&mut g, 0, "BG28_897");
    cast_on(&mut g, 0, 0);
    assert_eq!(stats(&g, 0)[0], (before[0].0 + 2, before[0].1 + 3));
    // 法术打别的随从：不再获得生命。
    let after = stats(&g, 0);
    give(&mut g, 0, "BG28_897");
    cast_on(&mut g, 0, 1);
    assert_eq!(stats(&g, 0)[0], after[0]);

    // 金色：+2 生命。
    let mut g = game(1702);
    set_board(&mut g, 0, &["BG36_921_G"]);
    let before = stats(&g, 0)[0];
    assert_eq!(before, (10, 4));
    give(&mut g, 0, "BG28_897");
    cast_on(&mut g, 0, 0);
    assert_eq!(stats(&g, 0)[0], (12, 4 + 2 + 2));
}

// ══════════════════════════════════════════════════════════════════════
// BG36_508 Cagey Conjurer
// ══════════════════════════════════════════════════════════════════════

#[test]
fn cagey_conjurer_activate_casts_two_tavern_spells_at_itself() {
    // 收窄法术池到一张定向统计法术：两次施放必须都落在本随从。
    let mut g = game(1801);
    g.spell_universe = vec![cid("BG28_897")];
    set_board(&mut g, 0, &["BG36_508"]);
    let gold = g.players[0].gold;
    g.apply(0, Action::Activate(0)).expect("activate");
    assert_eq!(g.players[0].gold, gold - 1, "Activate (1)");
    assert_eq!(g.players[0].stats.tavern_spells_cast, 2);
    let after = stats(&g, 0)[0];
    assert_eq!(after, (5 + 2 * 2, 3 + 2 * 2), "both casts target this");
}

#[test]
fn golden_cagey_conjurer_casts_four_tavern_spells() {
    let mut g = game(1802);
    g.spell_universe = vec![cid("BG28_897")];
    set_board(&mut g, 0, &["BG36_508_G"]);
    g.apply(0, Action::Activate(0)).expect("activate");
    assert_eq!(g.players[0].stats.tavern_spells_cast, 4);
    let after = stats(&g, 0)[0];
    assert_eq!(after, (10 + 4 * 2, 6 + 4 * 2));
}
