//! 人类战团（board-only）注入（`Game::inject_board`）回归测试。
//!
//! 覆盖 `docs/HUMAN_BOARD_OPPONENT.md` 的引擎侧验收项：
//! 1. 只替换 `board`（+ `tier`）：hand / shop / gold / health / alive / placement / hero
//!    等全部保留当前局原值，且**不改** `ended_turn`（该座位本回合照常行动）；
//! 2. EID：新随从由 `alloc_eid()` 重新分配（与旧 EID 不重叠），全局无重复；
//! 3. 池：旧 board 持有量按 `visit_pool_parts` 归还，注入实体 `pool_copies = 0`，注入前后
//!    `pool_balance` 与逐物种守恒；异种三连按 `pool_parts` 计；
//! 4. 悬空引用：手牌 `link/group/src`、队列 `hid/link/src`、`hats`/`revert_golden`/
//!    `discover_targets` 指向被移除旧实体时就地清空；
//! 5. 拒绝路径（阶段/座位/存活/已结束/待淘汰/pending/数量/未知卡/非法数值/tier）不改状态
//!    （`state_json` 与 `next_eid` 都不变）；
//! 6. 每回合注入 100 次后仍能正常终局（池守恒 + `invariants::check` 为空）。

mod common;

use common::{cid, set_board};
use hsbg_engine::engine::Phase;
use hsbg_engine::invariants;
use hsbg_engine::state::Pending;
use hsbg_engine::Game as EngineGame;

/// 某座位 board 的 `(card, atk, hp)` 签名（注入结果断言用）。
fn board_sig(g: &EngineGame, seat: usize) -> Vec<(u16, i32, i32)> {
    g.players[seat]
        .board
        .iter()
        .map(|m| (m.card.0, m.atk, m.hp))
        .collect()
}

/// 只改 board 的「人类战团」载荷：两张牌，数值由人类数据给出。
fn human_board() -> Vec<(hsbg_engine::cards::CardId, i32, i32)> {
    vec![(cid("BG36_345"), 5, 7), (cid("BGS_034"), 2, 3)]
}

fn all_eids(g: &EngineGame) -> Vec<u32> {
    let mut v = vec![];
    for p in &g.players {
        v.extend(p.board.iter().map(|m| m.eid));
        v.extend(p.hand.iter().map(|h| h.hid));
        v.extend(p.shop.iter().map(|s| s.sid));
    }
    v
}

#[test]
fn injects_board_and_tier_keeps_other_fields() {
    let mut g = common::game(41);
    // 目标座位先有手牌/商店/资源，用来验证「只替换 board」。
    common::give(&mut g, 1, "BG36_345");
    g.players[1].gold = 7;
    g.players[1].gold_next_turn = 3;
    let before = g.players[1].clone();
    let pb = invariants::pool_balance(&g);
    assert_eq!(pb.0, pb.1, "基线池必须自洽");

    let rep = g.inject_board(1, &human_board(), Some(4));
    assert!(rep.applied, "{}", rep.summary());
    assert_eq!(rep.reason, "ok");
    assert_eq!(rep.board_len, 2);
    assert!(rep.pool_balance_ok, "{}", rep.summary());

    let after = &g.players[1];
    // board / tier：被替换。
    assert_eq!(
        board_sig(&g, 1),
        vec![(cid("BG36_345").0, 5, 7), (cid("BGS_034").0, 2, 3)]
    );
    assert_eq!(after.tier, 4);
    // 其它字段：当前局原值。
    assert_eq!(after.id, before.id);
    assert_eq!(after.health, before.health);
    assert_eq!(after.armor, before.armor);
    assert_eq!(after.alive, before.alive);
    assert_eq!(after.placement, before.placement);
    assert_eq!(after.hero, before.hero);
    assert_eq!(after.gold, before.gold);
    assert_eq!(after.gold_next_turn, before.gold_next_turn);
    assert_eq!(after.hand.len(), before.hand.len());
    assert_eq!(after.shop.len(), before.shop.len());
    assert_eq!(after.ended_turn, before.ended_turn);
    assert!(!after.ended_turn, "注入不结束该座位的回合");
    // 派生：last_board 同步。
    assert_eq!(after.last_board.len(), after.board.len());
    assert_eq!(
        after.last_board.iter().map(|m| m.eid).collect::<Vec<_>>(),
        after.board.iter().map(|m| m.eid).collect::<Vec<_>>()
    );
    // 新实体：满血、不占池、无 killed_by。
    for m in &after.board {
        assert_eq!(m.max_hp, m.hp);
        assert_eq!(m.pool_copies, 0);
        assert!(m.pool_parts.is_empty());
        assert_eq!(m.killed_by, 0);
    }
    // EID：全部是新分配的（旧 board 的 EID 不复用），全局唯一。
    let old: Vec<u32> = before.board.iter().map(|m| m.eid).collect();
    assert!(after.board.iter().all(|m| !old.contains(&m.eid)));
    let eids = all_eids(&g);
    let uniq: std::collections::HashSet<u32> = eids.iter().copied().collect();
    assert_eq!(eids.len(), uniq.len(), "EID 必须全局唯一");
    assert!(invariants::check(&g).is_empty(), "{:?}", invariants::check(&g));
    assert_eq!(invariants::pool_balance(&g), pb);
}

#[test]
fn pool_conserved_with_mixed_triple_and_zero_copies() {
    let mut g = common::game(42);
    // 从共享池里挑两张真实存在、且池里还有副本的随从（a 至少 3 份、b 至少 2 份），
    // 这样「先借出副本再持有」的基线才自洽（不能依赖某张卡的池计数 > 0）。
    let is_minion = |c: &hsbg_engine::cards::CardId| {
        hsbg_engine::cards::db().get(*c).kind == hsbg_engine::cards::CardKind::Minion
    };
    let a = *g
        .universe
        .iter()
        .find(|c| is_minion(c) && g.pool.counts[c.idx()] >= 3)
        .expect("池里应有 >=3 份的随从");
    let b = *g
        .universe
        .iter()
        .find(|c| **c != a && is_minion(c) && g.pool.counts[c.idx()] >= 2)
        .expect("池里应有 >=2 份的另一张随从");
    // 旧 board：异种三连 a(a:2 + b:1) + b 的普通一份 —— 必须按 pool_parts 归还。
    let m0 = {
        let eid = g.alloc_eid();
        let mut m = hsbg_engine::state::Minion::new(eid, a);
        m.pool_copies = 3;
        m.pool_parts = vec![(a, 2), (b, 1)];
        m
    };
    let m1 = {
        let eid = g.alloc_eid();
        let mut m = hsbg_engine::state::Minion::new(eid, b);
        m.pool_copies = 1;
        m
    };
    g.players[2].board = vec![m0, m1];
    g.pool.counts[a.idx()] -= 2;
    g.pool.counts[b.idx()] -= 1;
    g.pool.counts[b.idx()] -= 1;
    let baseline = invariants::pool_balance(&g);
    assert_eq!(baseline.0, baseline.1, "基线必须自洽");
    assert!(invariants::pool_species_violations(&g).is_empty());
    let pool_before = g.pool.counts.clone();

    let rep = g.inject_board(2, &human_board(), None);
    assert!(rep.applied, "{}", rep.summary());
    assert!(rep.pool_balance_ok, "{}", rep.summary());
    assert_eq!(invariants::pool_balance(&g), baseline);
    assert!(
        invariants::pool_species_violations(&g).is_empty(),
        "{:?}",
        invariants::pool_species_violations(&g)
    );
    // 池计数恰好增加旧持有量（异种三连按 parts：a 2、b 1；再加 b 的 1 份普通持有）。
    assert_eq!(g.pool.counts[a.idx()], pool_before[a.idx()] + 2);
    assert_eq!(g.pool.counts[b.idx()], pool_before[b.idx()] + 2);
    // 注入实体一份都不占。
    assert!(g.players[2]
        .board
        .iter()
        .all(|m| m.pool_copies == 0 && m.pool_parts.is_empty()));
    assert_eq!(rep.returned_parts.iter().map(|(_, n)| *n).sum::<u16>(), 4);
    assert!(invariants::check(&g).is_empty(), "{:?}", invariants::check(&g));
}

#[test]
fn dangling_references_to_removed_minions_are_cleared() {
    let mut g = common::game(43);
    set_board(&mut g, 3, &["BG36_345"]);
    let gone = g.players[3].board[0].eid;
    // 手牌 link/group/src、hats、revert_golden、discover_targets 全部指向那个旧实体。
    common::give(&mut g, 3, "BGS_034");
    let hid = g.players[3].hand[0].hid;
    g.players[3].hand[0].link = gone;
    g.players[3].hand[0].src = gone;
    g.players[3].hats = vec![gone];
    g.players[3].revert_golden = vec![(gone, cid("BG36_345"), 1, 1)];
    g.players[3].discover_targets = vec![(cid("BG36_345"), gone)];

    let rep = g.inject_board(3, &human_board(), None);
    assert!(rep.applied, "{}", rep.summary());
    let p = &g.players[3];
    assert_eq!(p.hand[0].hid, hid, "手牌本身不重映射");
    assert_eq!(p.hand[0].link, 0);
    assert_eq!(p.hand[0].src, 0);
    assert!(p.hats.is_empty());
    assert!(p.revert_golden.is_empty());
    assert!(p.discover_targets.is_empty());
    assert!(invariants::check(&g).is_empty(), "{:?}", invariants::check(&g));
}

#[test]
fn rejections_leave_state_untouched() {
    let mut g = common::game(44);
    let payload = human_board();
    let check_noop = |rep: &hsbg_engine::snapshot::BoardInjectReport, want: &str| {
        assert!(!rep.applied, "{}", rep.summary());
        assert!(
            rep.reason.starts_with(want),
            "want {want:?} got {:?}",
            rep.reason
        );
    };

    // 已结束回合（镜像快照占用同一座位/回合时就是这种状态）。
    g.players[1].ended_turn = true;
    let s0 = serde_json::to_string(&g).unwrap();
    let next0 = g.next_eid;
    let rep = g.inject_board(1, &payload, None);
    check_noop(&rep, "already_ended");
    assert_eq!(serde_json::to_string(&g).unwrap(), s0);
    assert_eq!(g.next_eid, next0);
    g.players[1].ended_turn = false;

    // 未存活 / 待淘汰（health <= 0）。
    g.players[2].alive = false;
    let rep = g.inject_board(2, &payload, None);
    check_noop(&rep, "not_alive");
    g.players[2].alive = true;
    g.players[2].health = 0;
    let rep = g.inject_board(2, &payload, None);
    check_noop(&rep, "dying");
    g.players[2].health = 30;

    // pending 待选（饰品回合 / Discover）。
    g.players[4].pending = vec![Pending::Trinket {
        options: vec![],
        free: true,
        replace: None,
    }];
    let s_pending = serde_json::to_string(&g).unwrap();
    let rep = g.inject_board(4, &payload, None);
    check_noop(&rep, "pending_choice");
    assert_eq!(serde_json::to_string(&g).unwrap(), s_pending);
    g.players[4].pending.clear();

    // 座位越界 / 数量超限 / tier 越界 / 未知卡 / 非法数值。
    let rep = g.inject_board(99, &payload, None);
    check_noop(&rep, "seat_out_of_range");
    let too_many: Vec<_> = (0..8).map(|_| (cid("BG36_345"), 1, 1)).collect();
    let s_many = serde_json::to_string(&g).unwrap();
    let rep = g.inject_board(1, &too_many, None);
    check_noop(&rep, "too_many_minions");
    assert_eq!(serde_json::to_string(&g).unwrap(), s_many);
    let rep = g.inject_board(1, &payload, Some(0));
    check_noop(&rep, "bad_tier");
    let rep = g.inject_board(1, &[(hsbg_engine::cards::CardId(65500), 1, 1)], None);
    check_noop(&rep, "unknown_card");
    let rep = g.inject_board(1, &[(cid("BG36_345"), -1, 1)], None);
    check_noop(&rep, "bad_stats");
    let rep = g.inject_board(1, &[(cid("BG36_345"), 1, 0)], None);
    check_noop(&rep, "bad_stats");
    // 非 minion 卡（法术）也必须被拒。
    let spell = hsbg_engine::cards::db()
        .iter()
        .find(|d| matches!(d.kind, hsbg_engine::cards::CardKind::Spell))
        .map(|d| d.cid)
        .expect("卡表里应有法术");
    let s_spell = serde_json::to_string(&g).unwrap();
    let rep = g.inject_board(1, &[(spell, 1, 1)], None);
    check_noop(&rep, "not_minion");
    assert_eq!(serde_json::to_string(&g).unwrap(), s_spell);

    // 非 recruit 阶段。
    g.phase = Phase::GameOver;
    let s3 = serde_json::to_string(&g).unwrap();
    let rep = g.inject_board(1, &payload, None);
    check_noop(&rep, "not_recruit");
    assert_eq!(serde_json::to_string(&g).unwrap(), s3);
}

#[test]
fn injection_keeps_games_playable_and_terminal() {
    // 每回合开始给所有非 learner 座位注入（同一份人类战团）：两局合计 100+ 次注入后
    // 仍能正常终局，且注入前后共享池始终守恒、`invariants::check` 始终为空。
    let payload = human_board();
    let mut injected = 0;
    for seed in [45, 46] {
        let mut g = common::game(seed);
        let mut turn = 0;
        let mut guard = 0;
        while !g.is_over() && guard < 200_000 {
            guard += 1;
            if g.turn != turn {
                turn = g.turn;
                if g.phase == Phase::Recruit {
                    for seat in 1..8 {
                        let rep = g.inject_board(seat, &payload, Some(3));
                        if rep.applied {
                            injected += 1;
                        }
                    }
                    let (held, initial) = invariants::pool_balance(&g);
                    assert_eq!(held, initial, "seed {seed} turn {turn}: 池不守恒");
                    assert!(invariants::pool_species_violations(&g).is_empty());
                    assert!(invariants::check(&g).is_empty());
                }
            }
            let mut acted = false;
            for p in 0..8 {
                if g.needs_action(p) {
                    hsbg_engine::bot::play_turn(&mut g, p);
                    acted = true;
                }
            }
            if !acted {
                break;
            }
        }
        assert!(g.is_over(), "seed {seed}: 注入后必须能正常终局");
        let (held, initial) = invariants::pool_balance(&g);
        assert_eq!(held, initial);
        assert!(invariants::pool_species_violations(&g).is_empty());
        assert!(
            invariants::check(&g).is_empty(),
            "{:?}",
            invariants::check(&g)
        );
    }
    assert!(injected >= 100, "只注入了 {injected} 次（应 >= 100）");
}
