//! 回合末场面快照注入（`hsbg_engine::snapshot`）回归测试。
//!
//! 覆盖 `docs/MIRROR_SNAPSHOT_DESIGN.md` §8 的引擎侧验收项：
//! 1. 字段白名单（health/alive/placement/hero 不变，board/tier 替换）；
//! 2. 逐物种池守恒（含异种三连 `pool_parts` 与 `pool_copies=0`）；注入实体不占池；
//! 3. 全局 EID 唯一（`invariants::check` 无 duplicate eid）；
//! 4. 拒绝路径（ending/not alive/未知引用/重复座位/bad json）不改状态（`state_json` 不变、
//!    `next_eid` 不变）；
//! 5. `advance=true` 只统一推进一次；
//! 6. hand_queue 的 `QueueMark.hid` 与手牌 `link` 指向同一实体时映射到同一个新 EID。

mod common;

use common::{cid, set_board, Game};
use hsbg_engine::engine::Phase;
use hsbg_engine::invariants;
use hsbg_engine::state::{Item, Player, QueueMark};
use hsbg_engine::Game as EngineGame;

/// 从某个座位复制一份「场面载荷」（不改变该座位本身），可自由改 board 后再序列化。
fn payload_of(g: &mut Game, seat: usize) -> Player {
    g.players[seat].clone()
}

fn json(p: &Player) -> String {
    serde_json::to_string(p).unwrap()
}

/// 有效载荷：一个 2 只随从的场面（eid 由引擎分配，帧内唯一）。
fn valid_payload(g: &mut Game, seat: usize, ids: &[&str]) -> String {
    set_board(g, seat, ids);
    json(&g.players[seat])
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
fn replaces_scene_and_keeps_lobby_fields() {
    let mut g = common::game(21);
    let before = g.players[1].clone();
    set_board(&mut g, 2, &["BG36_345", "BGS_034"]);
    g.players[2].tier = 4;
    let snap = json(&g.players[2]);

    let rep = g.apply_turn_snapshots(&[(1, snap)], None);
    assert_eq!(rep.applied, 1, "{}", rep.summary());
    assert!(rep.rejected.is_empty(), "{:?}", rep.rejected);
    assert!(rep.pool_balance_ok, "{}", rep.summary());

    let after = &g.players[1];
    // 白名单外：保持当前局原值。
    assert_eq!(after.id, before.id);
    assert_eq!(after.health, before.health);
    assert_eq!(after.armor, before.armor);
    assert_eq!(after.alive, before.alive);
    assert_eq!(after.placement, before.placement);
    assert_eq!(after.hero, before.hero);
    assert_eq!(after.powers.len(), before.powers.len());
    // 白名单内：场面被替换。
    assert_eq!(after.tier, 4);
    assert_eq!(after.board.len(), 2);
    assert_eq!(after.board[0].card, cid("BG36_345"));
    assert_eq!(after.board[1].card, cid("BGS_034"));
    assert!(after.ended_turn, "注入后本回合不再行动");
    // EID 重新分配（旧座位的 eid 不能被复用）。
    let old: Vec<u32> = before.board.iter().map(|m| m.eid).collect();
    assert!(after.board.iter().all(|m| !old.contains(&m.eid)));
    // last_board 按 EOT 语义由新 board 重建。
    assert_eq!(after.last_board.len(), after.board.len());
}

#[test]
fn pool_conserved_with_mixed_triple_and_zero_copies() {
    let mut g = common::game(22);
    let (a, b) = (cid("BG36_345"), cid("BGS_034"));
    // 旧持有物：异种三连（2+1）——必须按 pool_parts 归还，而不是按 golden×3。
    set_board(&mut g, 1, &["BG36_345", "BGS_034"]);
    g.players[1].board[0].pool_copies = 3;
    g.players[1].board[0].pool_parts = vec![(a, 2), (b, 1)];
    // 模拟这 3 份副本确实是从共享池拿走的（否则基线本身不自洽）。
    g.pool.counts[a.idx()] -= 2;
    g.pool.counts[b.idx()] -= 1;

    // 载荷自身也带非零 pool_copies（注入后必须被清零，不占池）。
    let mut p = payload_of(&mut g, 3);
    p.board = vec![
        {
            let mut m = common::minion(&mut g, 3, "BG36_345");
            m.pool_copies = 3;
            m.pool_parts = vec![(a, 3)];
            m
        },
        {
            let mut m = common::minion(&mut g, 3, "BGS_034");
            m.pool_copies = 1;
            m
        },
    ];
    // 基线在载荷构造之后取（`with_recruit` 的商店维护会改动共享池计数）。
    let baseline = invariants::pool_balance(&g);
    assert_eq!(baseline.0, baseline.1, "基线必须自洽");
    assert!(invariants::pool_species_violations(&g).is_empty());
    // 设计 §4.1 的 H(P_old, c)：被替换区域（board/hand/shop/hand_queue）实际占用的副本。
    // 异种三连必须按 pool_parts 计（a:2 + b:1），而不是 golden×3。
    let mut expect: std::collections::HashMap<usize, i64> = std::collections::HashMap::new();
    let parts_of = |m: &hsbg_engine::state::Minion,
                        e: &mut std::collections::HashMap<usize, i64>| {
        m.visit_pool_parts(|c, n| *e.entry(c.idx()).or_insert(0) += n as i64);
    };
    for m in &g.players[1].board {
        parts_of(m, &mut expect);
    }
    for h in &g.players[1].hand {
        if let Some(m) = h.item.as_minion() {
            parts_of(m, &mut expect);
        }
    }
    for s in &g.players[1].shop {
        if let Some(m) = s.item.as_minion() {
            parts_of(m, &mut expect);
        }
    }
    for it in &g.players[1].hand_queue {
        if let Some(m) = it.as_minion() {
            parts_of(m, &mut expect);
        }
    }
    // 异种三连的持有量：a 至少 2 份（三连里的 2 份），b 至少 1 份（另一半）。
    assert!(expect.get(&a.idx()).copied().unwrap_or(0) >= 2);
    assert!(expect.get(&b.idx()).copied().unwrap_or(0) >= 1);
    let pool_before = g.pool.counts.clone();
    let rep = g.apply_turn_snapshots(&[(1, json(&p))], None);
    assert_eq!(rep.applied, 1, "{}", rep.summary());
    assert!(rep.pool_balance_ok, "{}", rep.summary());
    assert!(rep.pool_species_ok, "{}", rep.summary());
    // 总量与逐物种守恒：池计数恰好增加「旧持有物」，注入实体一份都不占。
    for (idx, n) in &expect {
        assert_eq!(
            g.pool.counts[*idx] as i64,
            pool_before[*idx] as i64 + n,
            "card idx {idx} 的归还量应等于 H(P_old) 的 {n}"
        );
    }
    for (idx, before) in pool_before.iter().enumerate() {
        if !expect.contains_key(&idx) {
            assert_eq!(g.pool.counts[idx], *before, "未涉及物种池计数不应变");
        }
    }
    assert_eq!(invariants::pool_balance(&g), baseline);
    assert!(invariants::pool_species_violations(&g).is_empty());
    // 注入实体不占池。
    assert!(g.players[1]
        .board
        .iter()
        .all(|m| m.pool_copies == 0 && m.pool_parts.is_empty()));
    // 全局 EID 唯一。
    let eids = all_eids(&g);
    let uniq: std::collections::HashSet<u32> = eids.iter().copied().collect();
    assert_eq!(eids.len(), uniq.len());
    assert!(invariants::check(&g).is_empty(), "{:?}", invariants::check(&g));
}

#[test]
fn rejections_leave_state_untouched() {
    let mut g = common::game(23);
    let snap = valid_payload(&mut g, 2, &["BG36_345"]);

    // 已结束回合的座位。
    g.players[1].ended_turn = true;
    let s0 = serde_json::to_string(&g).unwrap();
    let next0 = g.next_eid;
    let rep = g.apply_turn_snapshots(&[(1, snap.clone())], None);
    assert_eq!(rep.applied, 0);
    assert_eq!(rep.rejected, vec![(1, "already_ended".to_string())]);
    assert_eq!(serde_json::to_string(&g).unwrap(), s0);
    assert_eq!(g.next_eid, next0);

    // 未存活座位。
    g.players[2].alive = false;
    let s1 = serde_json::to_string(&g).unwrap();
    let rep = g.apply_turn_snapshots(&[(2, snap.clone())], None);
    assert_eq!(rep.applied, 0);
    assert_eq!(rep.rejected[0].1, "not_alive");
    assert_eq!(serde_json::to_string(&g).unwrap(), s1);

    // 未知 typed 引用（killed_by 指向帧外实体）。
    let mut p: Player = serde_json::from_str(&snap).unwrap();
    p.board[0].killed_by = 999_999;
    let s2 = serde_json::to_string(&g).unwrap();
    let next2 = g.next_eid;
    let rep = g.apply_turn_snapshots(&[(3, json(&p))], None);
    assert_eq!(rep.applied, 0);
    assert!(
        rep.rejected[0].1.starts_with("unknown_ref"),
        "{:?}",
        rep.rejected
    );
    assert_eq!(serde_json::to_string(&g).unwrap(), s2);
    assert_eq!(g.next_eid, next2);

    // 重复座位 / 越界 / bad json。
    let rep = g.apply_turn_snapshots(&[(4, snap.clone()), (4, snap.clone())], None);
    assert_eq!(rep.applied, 1);
    assert_eq!(rep.rejected, vec![(4, "duplicate_seat".to_string())]);
    let rep = g.apply_turn_snapshots(&[(99, snap.clone())], None);
    assert!(rep.rejected[0].1.starts_with("seat_out_of_range"));
    let rep = g.apply_turn_snapshots(&[(5, "{not json".to_string())], None);
    assert!(rep.rejected[0].1.starts_with("bad_json"));

    // 非 recruit 阶段一律拒绝。
    g.phase = Phase::GameOver;
    let s3 = serde_json::to_string(&g).unwrap();
    let rep = g.apply_turn_snapshots(&[(6, snap)], None);
    assert_eq!(rep.rejected[0].1, "not_recruit");
    assert_eq!(serde_json::to_string(&g).unwrap(), s3);
}

#[test]
fn queue_and_link_references_remap_together() {
    let mut g = common::game(25);
    // 载荷：一只在 hand_queue 里等待的 minion（`QueueMark.hid` 预留其 id），
    // 一张手牌 link 指向它 —— 三者必须映射到**同一个**新 EID。
    let hid = common::give(&mut g, 3, "BG36_345");
    let mut p = payload_of(&mut g, 3);
    p.board.clear();
    let mut m = common::minion(&mut g, 3, "BG36_345");
    m.eid = 777_001;
    p.hand_queue = vec![Item::Minion(m)];
    p.hand_queue_marks = vec![QueueMark {
        hid: 777_001,
        ..Default::default()
    }];
    let mut linked = false;
    for h in p.hand.iter_mut() {
        if h.hid == hid {
            h.link = 777_001;
            linked = true;
        }
    }
    assert!(linked, "载荷里应有那张被 link 的手牌");

    let rep = g.apply_turn_snapshots(&[(1, json(&p))], None);
    assert_eq!(rep.applied, 1, "{}", rep.summary());
    let t = &g.players[1];
    assert_eq!(t.hand_queue.len(), 1);
    assert_eq!(t.hand_queue_marks.len(), 1);
    let queued = t.hand_queue[0].as_minion().expect("队列里应是 minion").eid;
    assert_ne!(queued, 777_001, "旧 EID 不得复用");
    assert_eq!(t.hand_queue_marks[0].hid, queued, "预留 hid 必须同步重映射");
    let hand_link = t
        .hand
        .iter()
        .find(|h| h.link != 0)
        .expect("手牌 link 应被重映射而不是被清空")
        .link;
    assert_eq!(hand_link, queued, "link 必须指向重映射后的同一实体");
    assert!(invariants::check(&g).is_empty(), "{:?}", invariants::check(&g));
    assert_eq!(
        invariants::pool_balance(&g).0,
        invariants::pool_balance(&g).1
    );
}

#[test]
fn advance_runs_the_round_once() {
    let mut g = common::game(24);
    // 每个座位都有一点场面，战斗不会空跑。
    for p in 0..8 {
        set_board(&mut g, p, &["BG36_345"]);
    }
    // learner 先结束回合；其余座位由快照注入置 ended_turn。
    g.players[0].ended_turn = true;
    let t0 = g.turn;
    let mut snaps = vec![];
    for seat in 1..8 {
        snaps.push((seat, json(&g.players[seat])));
    }
    let rep = g.apply_turn_snapshots(&snaps, Some(true));
    assert_eq!(rep.applied, 7, "{}", rep.summary());
    assert!(rep.advanced);
    assert_eq!(g.turn, t0 + 1, "整批只推进一次");
    assert!(g.players.iter().all(|p| !p.ended_turn));
    assert!(rep.pool_balance_ok, "{}", rep.summary());
    assert!(invariants::check(&g).is_empty(), "{:?}", invariants::check(&g));

    // advance=false（缺省）不推进：同样的注入只提交。
    let t1 = g.turn;
    let rep = g.apply_turn_snapshots(&[(1, json(&g.players[1]))], None);
    assert_eq!(rep.applied, 1);
    assert!(!rep.advanced);
    assert_eq!(g.turn, t1);
    assert!(g.players[1].ended_turn);
}
