//! P3 批次 A（8 张 37 池内缺失随从）机制用例。
//!
//! 卡与实现：`src/content/p3_batch_a.rs`；语义参考 hsrl2 legacy 脚本（见该文件头注释）。
//! 数值以 37 数据为准：Groundbreaker 基础 +1/+1（金 +2/+2）、Showy Cyclist 基础 +2/+1
//! （金 +4/+2）、Natural Blessing BG28_845 +2/+1、Tavern Coin BG28_810。

use hsbg_engine::actions::Action;
use hsbg_engine::cards::{cid, db};
use hsbg_engine::state::{Item, Minion};
use hsbg_engine::types::{PlayerId, Races};
use hsbg_engine::{Game, RulesConfig};

/// 已过英雄选择、第 1 回合招募阶段；所有座位 pin 成 Patchwerk（被动英雄）。
fn game(seed: u64) -> Game {
    let mut g = Game::new(seed, RulesConfig::default());
    for p in 0..8 {
        g.apply(p, Action::Choose(0)).unwrap();
    }
    for p in 0..8 {
        g.players[p].hero = Some(cid("TB_BaconShop_HERO_34"));
        g.players[p].pending.clear();
        g.players[p].hand.clear();
        g.players[p].stats = Default::default();
        g.players[p].effects.clear();
        g.players[p].quests.clear();
        g.players[p].counters.clear();
        g.players[p].max_gold_bonus = 0;
        g.players[p].skipping = false;
        g.players[p].board.clear();
        g.players[p].powers.clear();
        g.players[p].set_hero_power(0, cid("TB_BaconShop_HP_035"));
    }
    g
}

fn minion(g: &mut Game, p: PlayerId, id: &str) -> Minion {
    g.with_recruit(p, |c| c.new_minion(0, cid(id)))
}

/// 建棋盘并返回各 minion 的 eid（顺序同 ids）。
fn board(g: &mut Game, p: PlayerId, ids: &[&str]) -> Vec<u32> {
    let b: Vec<Minion> = ids.iter().map(|id| minion(g, p, id)).collect();
    let eids = b.iter().map(|m| m.eid).collect();
    g.players[p].board = b;
    eids
}

fn hand_card(g: &Game, p: PlayerId, card: &str) -> usize {
    g.players[p]
        .hand
        .iter()
        .filter(|h| h.item.card() == cid(card))
        .count()
}

fn atk_hp(g: &Game, p: PlayerId, eid: u32) -> (i32, i32) {
    let m = g.players[p].board.iter().find(|m| m.eid == eid).unwrap();
    (m.atk, m.max_hp)
}

// ---------------------------------------------------------------- BG23_002 Shell Collector

#[test]
fn shell_collector_battlecry_gets_tavern_coin() {
    let mut g = game(1);
    let e = board(&mut g, 0, &["BG23_002"])[0];
    g.with_recruit(0, |c| c.trigger_battlecry_ext(0, e));
    assert_eq!(
        hand_card(&g, 0, "BG28_810"),
        1,
        "Battlecry: Get a Tavern Coin"
    );

    // 金色 "Get 2 Tavern Coins"：me.g()=2。
    let eg = board(&mut g, 0, &["BG23_002_G"])[0];
    g.with_recruit(0, |c| c.trigger_battlecry_ext(0, eg));
    assert_eq!(hand_card(&g, 0, "BG28_810"), 3, "golden: 2 more coins");
}

// ---------------------------------------------------------------- BG26_505 Zesty Shaker

#[test]
fn zesty_shaker_copies_spellcraft_once_per_turn() {
    let mut g = game(2);
    let e = board(&mut g, 0, &["BG26_505"])[0];
    assert_eq!(g.players[0].board[0].counter, 1, "on_create counter=1");
    // Spellcraft 法术打在本体（Mini-Myrmidon 的 +2 Attack，目标友好随从）。
    g.with_recruit(0, |c| c.you_cast(0, cid("BG23_000t"), 0, e, 0));
    assert_eq!(
        hand_card(&g, 0, "BG23_000t"),
        1,
        "获得该 Spellcraft 法术的副本"
    );
    // 同回合第二次不再复制（Once per turn）。
    g.with_recruit(0, |c| c.you_cast(0, cid("BG23_000t"), 0, e, 0));
    assert_eq!(hand_card(&g, 0, "BG23_000t"), 1, "每回合一次");
    // 回合开始重置后可再次复制。
    g.with_recruit(0, |c| {
        c.run_minion_hook(0, e, |s| s.start_of_turn, 1, "start of turn")
    });
    g.with_recruit(0, |c| c.you_cast(0, cid("BG23_000t"), 0, e, 0));
    assert_eq!(hand_card(&g, 0, "BG23_000t"), 2, "新回合额度恢复");

    // 金色 "get 2 new copies of it"。
    let mut g = game(3);
    let e = board(&mut g, 0, &["BG26_505_G"])[0];
    g.with_recruit(0, |c| c.you_cast(0, cid("BG23_000t"), 0, e, 0));
    assert_eq!(hand_card(&g, 0, "BG23_000t"), 2, "golden: 2 copies");
}

// ---------------------------------------------------------------- BG27_514 Sea Witch Zar'jira

#[test]
fn zarjira_sirens_song_copies_tavern_minion() {
    let mut g = game(4);
    // 保证馆内有随从：刷新一次。
    g.with_recruit(0, |c| c.refresh_shop(0));
    let target = g.with_recruit(0, |c| c.tavern_minions(0));
    assert!(!target.is_empty());
    let t = target[0];
    let t_card = g.players[0]
        .shop
        .iter()
        .find(|s| s.sid == t)
        .map(|s| s.item.card())
        .unwrap();
    g.with_recruit(0, |c| c.cast_spell(0, cid("BG27_514t"), 0, t, 0));
    assert!(
        g.players[0].hand.iter().any(|h| h.item.card() == t_card),
        "Siren's Song: get a copy of the chosen Tavern minion"
    );

    // 金色 "get 2 copies"：清手牌后重测数量。
    g.players[0].hand.clear();
    let target = g.with_recruit(0, |c| c.tavern_minions(0));
    let t = target[0];
    g.with_recruit(0, |c| c.cast_spell(0, cid("BG27_514t_G"), 0, t, 0));
    assert_eq!(g.players[0].hand.len(), 2, "golden: 2 copies");
}

// ---------------------------------------------------------------- BG31_035 Groundbreaker

#[test]
fn groundbreaker_buffs_on_naga_play_and_improves() {
    let mut g = game(5);
    let e = board(&mut g, 0, &["BG31_035"])[0];
    let naga = minion(&mut g, 0, "BG23_002");
    g.with_recruit(0, |c| c.add_to_hand(0, Item::Minion(naga)));
    g.apply(0, Action::Play { hand: 0, pos: 1 }).unwrap();
    assert_eq!(atk_hp(&g, 0, e), (7, 5), "After you play a Naga: +1/+1");

    // 每 3 个法术 Improve：spells_cast=3 → ×2。
    g.players[0].stats.spells_cast = 3;
    g.players[0].hand.clear();
    let naga2 = minion(&mut g, 0, "BG23_002");
    g.with_recruit(0, |c| c.add_to_hand(0, Item::Minion(naga2)));
    g.apply(0, Action::Play { hand: 0, pos: 2 }).unwrap();
    assert_eq!(atk_hp(&g, 0, e), (9, 7), "3 spells: +2/+2");

    // 金色基础 +2/+2。
    let mut g = game(6);
    let e = board(&mut g, 0, &["BG31_035_G"])[0];
    let naga = minion(&mut g, 0, "BG23_002");
    g.with_recruit(0, |c| c.add_to_hand(0, Item::Minion(naga)));
    g.apply(0, Action::Play { hand: 0, pos: 1 }).unwrap();
    assert_eq!(atk_hp(&g, 0, e), (14, 10), "golden base +2/+2");
}

// ---------------------------------------------------------------- BG31_920 Darkcrest Strategist

#[test]
fn darkcrest_strategist_evolving_strategy_improves_each_turn() {
    let mut g = game(7);
    let e = board(&mut g, 0, &["BG31_920"])[0];
    assert_eq!(g.players[0].board[0].counter, 1, "starts at Tier 1");
    // Spellcraft "Evolving Strategy"：来源随从档位 = 1 → Tier 1 Naga。
    g.with_recruit(0, |c| {
        c.cast_src = e;
        c.cast_spell(0, cid("BG31_920t"), 0, 0, 0);
    });
    assert_eq!(g.players[0].hand.len(), 1);
    let got = g.players[0].hand[0].item.card();
    let d = db().get(got);
    assert!(d.is_minion() && d.races.contains(Races::NAGA) && d.tier == 1);

    // EoT: counter → 2；再施放 → Tier 2 Naga。
    g.with_recruit(0, |c| {
        c.run_minion_hook(0, e, |s| s.end_of_turn, 1, "end of turn")
    });
    assert_eq!(g.players[0].board[0].counter, 2, "Improves each turn");
    g.players[0].hand.clear();
    g.with_recruit(0, |c| {
        c.cast_src = e;
        c.cast_spell(0, cid("BG31_920t"), 0, 0, 0);
    });
    assert_eq!(db().get(g.players[0].hand[0].item.card()).tier, 2);

    // 金色法术 "Get two random Tier 1 Naga" → 2 张。
    let mut g = game(8);
    let e = board(&mut g, 0, &["BG31_920"])[0];
    g.with_recruit(0, |c| {
        c.cast_src = e;
        c.cast_spell(0, cid("BG31_920_Gt"), 0, 0, 0);
    });
    assert_eq!(g.players[0].hand.len(), 2, "golden: two Naga");
}

// ---------------------------------------------------------------- BG31_925 Showy Cyclist

#[test]
fn showy_cyclist_deathrattle_buffs_nagas() {
    let mut g = game(9);
    let eids = board(&mut g, 0, &["BG31_925", "BG23_002"]);
    let (showy, naga) = (eids[0], eids[1]);
    g.with_recruit(0, |c| {
        c.destroy(showy);
        c.resolve_deaths();
    });
    assert_eq!(
        atk_hp(&g, 0, naga),
        (4 + 2, 3 + 1),
        "Deathrattle: Naga +2/+1"
    );

    // Improve ×2（spells_cast=3）。
    let mut g = game(10);
    let eids = board(&mut g, 0, &["BG31_925", "BG23_002"]);
    let (showy, naga) = (eids[0], eids[1]);
    g.players[0].stats.spells_cast = 3;
    g.with_recruit(0, |c| {
        c.destroy(showy);
        c.resolve_deaths();
    });
    assert_eq!(atk_hp(&g, 0, naga), (4 + 4, 3 + 2), "3 spells: +4/+2");

    // 金色基础 +4/+2。
    let mut g = game(11);
    let eids = board(&mut g, 0, &["BG31_925_G", "BG23_002"]);
    let (showy, naga) = (eids[0], eids[1]);
    g.with_recruit(0, |c| {
        c.destroy(showy);
        c.resolve_deaths();
    });
    assert_eq!(atk_hp(&g, 0, naga), (4 + 4, 3 + 2), "golden: +4/+2");
}

// ---------------------------------------------------------------- BG32_835 Tranquil Meditative

#[test]
fn tranquil_meditative_adds_tavern_spell_bonus() {
    let mut g = game(12);
    board(&mut g, 0, &["BG23_002"]);
    g.with_recruit(0, |c| c.cast_spell(0, cid("BG32_835t"), 0, 0, 0));
    let st = &g.players[0].stats;
    assert_eq!((st.spell_atk, st.spell_hp), (1, 1), "+1/+1 this game");
    // 经酒馆法术 Buff 出口生效：Natural Blessing +2/+1 → 每个共享类型随从 +3/+2。
    let e = g.players[0].board[0].eid;
    g.with_recruit(0, |c| c.you_cast(0, cid("BG28_845"), 0, e, 0));
    let m = g.players[0].board.iter().find(|m| m.eid == e).unwrap();
    assert_eq!(
        (m.atk, m.max_hp),
        (4 + 1 + 2, 3 + 1 + 1),
        "+1/+1 extra applies"
    );

    // 金色冥想 +2/+2。
    let mut g = game(13);
    board(&mut g, 0, &["BG23_002"]);
    g.with_recruit(0, |c| c.cast_spell(0, cid("BG32_835_Gt"), 0, 0, 0));
    let st = &g.players[0].stats;
    assert_eq!((st.spell_atk, st.spell_hp), (2, 2), "golden: +2/+2");
}

// ---------------------------------------------------------------- BG32_837 Fauna Whisperer

#[test]
fn fauna_whisperer_casts_natural_blessing_on_neighbors() {
    let mut g = game(14);
    // [Shell Collector, Fauna Whisperer, Shell Collector]，均为 Naga。
    let eids = board(&mut g, 0, &["BG23_002", "BG32_837", "BG23_002"]);
    let fauna = eids[1];
    g.with_recruit(0, |c| {
        c.run_minion_hook(0, fauna, |s| s.end_of_turn, 1, "end of turn")
    });
    // 每个相邻目标各施放一次 Natural Blessing（+2/+1），共享类型的 3 只都吃到 → +4/+2。
    assert_eq!(atk_hp(&g, 0, eids[0]), (4 + 4, 3 + 2), "Shell: two casts");
    assert_eq!(
        atk_hp(&g, 0, eids[1]),
        (4 + 4, 9 + 2),
        "Fauna itself: two casts"
    );
    assert_eq!(atk_hp(&g, 0, eids[2]), (4 + 4, 3 + 2), "Shell: two casts");

    // 金色 "twice"：每相邻目标施放 2 次 → +8/+4。
    let mut g = game(15);
    let eids = board(&mut g, 0, &["BG23_002", "BG32_837_G", "BG23_002"]);
    let fauna = eids[1];
    g.with_recruit(0, |c| {
        c.run_minion_hook(0, fauna, |s| s.end_of_turn, 1, "end of turn")
    });
    assert_eq!(
        atk_hp(&g, 0, eids[0]),
        (4 + 8, 3 + 4),
        "golden Shell: +8/+4"
    );
    assert_eq!(
        atk_hp(&g, 0, eids[1]),
        (8 + 8, 18 + 4),
        "golden Fauna: +8/+4"
    );
    assert_eq!(
        atk_hp(&g, 0, eids[2]),
        (4 + 8, 3 + 4),
        "golden Shell: +8/+4"
    );
}
