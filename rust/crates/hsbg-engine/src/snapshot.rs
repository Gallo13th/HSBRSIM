//! 回合末场面快照镜像（外部快照 / `pool_delta_unknown` 安全版本）。
//!
//! 设计：`docs/MIRROR_SNAPSHOT_DESIGN.md`。本模块只做**引擎侧**注入：把某个座位在
//! 「EOT 完成、combat 尚未开始」时刻的 `Player` 场面，按**字段白名单**搬到当前局的
//! 目标座位，视作外生战团；不重放对手动作、不整体替换 `Player`。
//!
//! 语义要点：
//! - 只允许 `Phase::Recruit`、目标存活、目标 `pending` 为空、目标尚未 `ended_turn`；
//! - 白名单替换：board / hand / hand_queue / shop / tier / 资源字段；大厅簿记
//!   （id / alive / placement / health / armor / 英雄 / 能力 / 统计 / 配对 / 侦察）保持
//!   当前局原值，见 [`Game::apply_one_snapshot`] 里的注释表；
//! - `pool_delta_unknown`：**不**推断共享池差量。被替换区域（board / hand /
//!   hand_queue / shop）里旧 minion 的持有量按 `Minion::visit_pool_parts` 归还共享池，
//!   注入实体一律 `pool_copies = 0`（不占池）。因此总量与逐物种守恒都保持成立；
//! - EID：注入实体一律由 `Game::alloc_eid()` 重新分配；旧实体上的 typed 引用
//!   （`Minion.killed_by`、`HandCard.hid/link/group/src`、`ShopSlot.sid`、
//!   `QueueMark.hid/link/src`）同步映射；出现集合外引用则 fail-closed 拒绝该座位；
//! - 事务：**逐座位**「先完整校验、后一次性提交」；被拒绝的座位不改任何状态
//!   （含 `next_eid` / pool / turn），`state_json` 字节不变；
//! - 注入后目标座位 `ended_turn = true`（本回合不再行动），不会走 `start_turn_player`；
//!   `advance` 为真时整批只统一推进一次（`fight_when_all_ended`）。
//!
//! 已知降级（TODO 见文档「实现状态」）：不导入 `scheduled` / `hats` / `revert_golden` /
//! `discover_targets` / `owed` / `pending`，保留目标座位原值；严格的「池差量已知」模式
//! 尚未实现（`pool_delta_known` 只在接口层留位）。

use std::collections::{HashMap, HashSet};

use crate::actions::N_SHOP;
use crate::cards::{CardId, CardKind, db};
use crate::engine::{Game, Phase};
use crate::invariants;
use crate::state::{Item, Minion, Player, QueueMark};
use crate::types::EntityId;

/// 快照载荷的 schema 版本：Python 采集端写进文件，引擎只做记录（不解析文件）。
pub const SNAPSHOT_SCHEMA_VERSION: u32 = 1;

/// 一次批量注入的结果（Python 侧转成 dict；拒绝原因不抛异常）。
#[derive(Clone, Debug, Default)]
pub struct SnapshotReport {
    /// 成功替换的座位数。
    pub applied: usize,
    /// `(seat, reason)`：被拒绝的座位与原因，**状态未变**。
    pub rejected: Vec<(usize, String)>,
    /// `invariants::pool_balance` 的总量守恒（注入后立刻检查）。
    pub pool_balance_ok: bool,
    /// 逐物种守恒（仅在没有 pending 待选时可判定，否则为 false 但不算失败）。
    pub pool_species_ok: bool,
    /// 注入后 `(held, initial)`，便于调用方打点。
    pub pool_held: u64,
    pub pool_initial: u64,
    /// 是否真的触发了统一推进（`advance=true` 且走了 `fight_when_all_ended`）。
    pub advanced: bool,
}

impl SnapshotReport {
    /// 结构化摘要（日志/manifest 打点用）。
    pub fn summary(&self) -> String {
        format!(
            "applied={} rejected={} pool_balance_ok={} (held={} initial={}) species_ok={} advanced={}",
            self.applied,
            self.rejected.len(),
            self.pool_balance_ok,
            self.pool_held,
            self.pool_initial,
            self.pool_species_ok,
            self.advanced
        )
    }
}

/// 被替换区域里的全部 minion（不可变；顺序：board → hand → shop → hand_queue）。
fn zone_minions(p: &Player) -> Vec<&Minion> {
    let mut v: Vec<&Minion> = Vec::new();
    v.extend(p.board.iter());
    for h in &p.hand {
        if let Item::Minion(m) = &h.item {
            v.push(m);
        }
    }
    for s in &p.shop {
        if let Item::Minion(m) = &s.item {
            v.push(m);
        }
    }
    for it in &p.hand_queue {
        if let Some(m) = it.as_minion() {
            v.push(m);
        }
    }
    v
}

/// 同上，可变版本（用于重映射引用 / 清零 pool_copies）。
fn zone_minions_mut(p: &mut Player) -> Vec<&mut Minion> {
    let mut v: Vec<&mut Minion> = Vec::new();
    v.extend(p.board.iter_mut());
    for h in p.hand.iter_mut() {
        if let Item::Minion(m) = &mut h.item {
            v.push(m);
        }
    }
    for s in p.shop.iter_mut() {
        if let Item::Minion(m) = &mut s.item {
            v.push(m);
        }
    }
    for it in p.hand_queue.iter_mut() {
        if let Item::Minion(m) = it {
            v.push(m);
        }
    }
    v
}

/// 旧持有物：被替换区域里每个 minion 实际占用的共享池副本（`pool_delta_unknown` 归还用）。
fn held_parts(p: &Player) -> Vec<(CardId, u16)> {
    let mut out: Vec<(CardId, u16)> = Vec::new();
    for m in zone_minions(p) {
        m.visit_pool_parts(|c, n| out.push((c, n)));
    }
    out
}

/// 载荷里出现的实体 id（按发现顺序；用于分配新 EID 与引用校验）。
///
/// 引擎约定：hand 里 minion 的 `HandCard.hid` 就是该 minion 的 `eid`；hand_queue 里
/// 等待的 minion 由 `QueueMark.hid` 预留同一个 id（尚在队列时 minion 的 eid 也是它）。
/// 因此每个实体只登记一次，避免自己和自己「重复」。
fn payload_entity_ids(p: &Player) -> Vec<EntityId> {
    let mut v: Vec<EntityId> = Vec::new();
    for m in &p.board {
        v.push(m.eid);
    }
    for h in &p.hand {
        v.push(h.hid);
    }
    for s in &p.shop {
        v.push(s.sid);
    }
    for (i, it) in p.hand_queue.iter().enumerate() {
        let marked = p.hand_queue_marks.get(i).map_or(0, |q| q.hid);
        let id = if marked != 0 {
            marked
        } else {
            it.as_minion().map_or(0, |m| m.eid)
        };
        if id != 0 {
            v.push(id);
        }
    }
    v
}

/// 单个 minion 的合法性（类型/数值/死亡标记），避免把脏帧带进对局。
fn check_minion(m: &Minion, who: &str) -> Result<(), String> {
    let d = db()
        .try_get(m.card)
        .ok_or_else(|| format!("{who}: unknown card id {}", m.card.0))?;
    if d.kind != CardKind::Minion {
        return Err(format!("{who}: {} is not a minion", d.id));
    }
    if m.eid == 0 {
        return Err(format!("{who}: {} has entity id 0", d.id));
    }
    if m.atk < 0 || m.max_hp <= 0 || m.hp <= 0 || m.hp > m.max_hp {
        return Err(format!(
            "{who}: {} is {}/{} (max {})",
            d.name, m.atk, m.hp, m.max_hp
        ));
    }
    if m.destroyed {
        return Err(format!("{who}: {} is a destroyed (combat) body", d.name));
    }
    Ok(())
}

/// hand/shop/hand_queue 的一格：minion 或法术，按卡表校验种类。
fn check_item(it: &Item, who: &str) -> Result<(), String> {
    match it {
        Item::Minion(m) => check_minion(m, who),
        Item::Spell { card, .. } => {
            let d = db()
                .try_get(*card)
                .ok_or_else(|| format!("{who}: unknown card id {}", card.0))?;
            if !matches!(d.kind, CardKind::Spell | CardKind::TavernSpell) {
                return Err(format!("{who}: {} is not a spell", d.id));
            }
            Ok(())
        }
    }
}

/// 白名单替换的载荷整体校验（不含 EID 引用；无副作用）。
fn validate_payload(g: &Game, seat: usize, p: &Player) -> Result<(), String> {
    let target = &g.players[seat];
    if !p.pending.is_empty() {
        // 回合末快照定义上 pending 已清空；带 pending 的帧不是 EOT 帧。
        return Err(format!("snapshot_pending({})", p.pending.len()));
    }
    if !(1..=7).contains(&p.tier) {
        return Err(format!("bad_tier({})", p.tier));
    }
    if p.gold < 0 {
        return Err(format!("bad_gold({})", p.gold));
    }
    if p.board.len() > g.cfg.board_size {
        return Err(format!("board_too_large({})", p.board.len()));
    }
    let hand_limit = if g.cfg.experimental_mode {
        g.cfg.hand_size.max(target.timewarp_hand_limit)
    } else {
        g.cfg.hand_size
    };
    if p.hand.len() > hand_limit {
        return Err(format!("hand_too_large({})", p.hand.len()));
    }
    let shop_limit = g.cfg.shop_max_cards.min(N_SHOP);
    if p.shop.len() > shop_limit {
        return Err(format!("shop_too_large({})", p.shop.len()));
    }
    for (i, m) in p.board.iter().enumerate() {
        check_minion(m, &format!("board[{i}]"))?;
    }
    for (i, h) in p.hand.iter().enumerate() {
        check_item(&h.item, &format!("hand[{i}]"))?;
    }
    for (i, s) in p.shop.iter().enumerate() {
        check_item(&s.item, &format!("shop[{i}]"))?;
    }
    for (i, it) in p.hand_queue.iter().enumerate() {
        check_item(it, &format!("hand_queue[{i}]"))?;
    }
    // 引擎约定：hand 里 minion 的 hid 就是它的 eid；队列 mark 预留的 hid 与队列 minion 的
    // eid 相同。不一致的帧无法做 typed EID 重映射，直接拒绝。
    for (i, h) in p.hand.iter().enumerate() {
        if let Item::Minion(m) = &h.item {
            if m.eid != h.hid {
                return Err(format!("hand_hid_mismatch({i})"));
            }
        }
    }
    if p.hand_queue_marks.len() == p.hand_queue.len() {
        for (i, it) in p.hand_queue.iter().enumerate() {
            if let Item::Minion(m) = it {
                let q = &p.hand_queue_marks[i];
                if q.hid != 0 && q.hid != m.eid {
                    return Err(format!("queue_hid_mismatch({i})"));
                }
            }
        }
    }
    Ok(())
}

/// 实体 id 集合：必须非 0 且帧内唯一（全局唯一由 `alloc_eid` 在提交阶段保证）。
fn validate_entity_ids(ids: &[EntityId]) -> Result<HashSet<EntityId>, String> {
    let mut set: HashSet<EntityId> = HashSet::with_capacity(ids.len());
    for &e in ids {
        if e == 0 {
            return Err("zero_entity_id".to_string());
        }
        if !set.insert(e) {
            return Err(format!("duplicate_eid({e})"));
        }
    }
    Ok(set)
}

/// typed 引用校验：所有非 0 引用都必须指向帧内实体，否则 fail-closed。
fn validate_refs(p: &Player, ids: &HashSet<EntityId>) -> Result<(), String> {
    let chk = |e: EntityId, what: &str| -> Result<(), String> {
        if e != 0 && !ids.contains(&e) {
            return Err(format!("unknown_ref:{what}={e}"));
        }
        Ok(())
    };
    for m in zone_minions(p) {
        chk(m.killed_by, "minion.killed_by")?;
    }
    for h in &p.hand {
        chk(h.link, "hand.link")?;
        chk(h.group, "hand.group")?;
        chk(h.src, "hand.src")?;
    }
    for q in &p.hand_queue_marks {
        chk(q.hid, "queue.hid")?;
        chk(q.link, "queue.link")?;
        chk(q.src, "queue.src")?;
    }
    Ok(())
}

impl Game {
    /// 批量注入回合末场面快照。
    ///
    /// `snaps` 为 `(seat, player_json)`（`player_json` 与 `state_json()["players"][seat]`
    /// 同构）；逐座位独立校验/提交，被拒绝的座位不改任何状态，也不抛异常。
    /// `advance`：`None`/`Some(false)` 只提交注入；`Some(true)` 在整批提交后调用一次
    /// `fight_when_all_ended`（若所有存活座位都 ended，则战斗 + 进入下一回合）。
    pub fn apply_turn_snapshots(
        &mut self,
        snaps: &[(usize, String)],
        advance: Option<bool>,
    ) -> SnapshotReport {
        let mut rep = SnapshotReport::default();
        let mut taken: HashSet<usize> = HashSet::with_capacity(snaps.len());
        for (seat, json) in snaps {
            match self.apply_one_snapshot(*seat, json, &mut taken) {
                Ok(()) => rep.applied += 1,
                Err(reason) => rep.rejected.push((*seat, reason)),
            }
        }
        let (held, initial) = invariants::pool_balance(self);
        rep.pool_held = held;
        rep.pool_initial = initial;
        rep.pool_balance_ok = held == initial;
        // 逐物种守恒。注意：任何座位有 pending 待选（Discover 选项）时会合法地持有区域外的
        // 池副本，此时两条守恒检查都会报 false（与 `invariants` 的文档约定一致）。
        rep.pool_species_ok = invariants::pool_species_violations(self).is_empty();
        if advance.unwrap_or(false) {
            self.fight_when_all_ended();
            rep.advanced = true;
        }
        rep
    }

    /// 单座位注入：先完整校验（无副作用），再一次性提交（提交阶段不再失败）。
    fn apply_one_snapshot(
        &mut self,
        seat: usize,
        json: &str,
        taken: &mut HashSet<usize>,
    ) -> Result<(), String> {
        if self.phase != Phase::Recruit {
            return Err("not_recruit".to_string());
        }
        if seat >= self.players.len() {
            return Err(format!("seat_out_of_range({seat})"));
        }
        if !taken.insert(seat) {
            return Err("duplicate_seat".to_string());
        }
        {
            let pl = &self.players[seat];
            if !pl.alive {
                return Err("not_alive".to_string());
            }
            if pl.ended_turn {
                return Err("already_ended".to_string());
            }
            if pl.health <= 0 {
                // 待淘汰座位：场面没有意义，先让 recruit_deaths 处理。
                return Err(format!("dying(health={})", pl.health));
            }
            if !pl.pending.is_empty() {
                return Err(format!("pending_choice({})", pl.pending.len()));
            }
        }
        // ---- 校验阶段（无副作用：不分配 EID、不动 pool、不改玩家） ----
        let p: Player = serde_json::from_str(json).map_err(|e| format!("bad_json: {e}"))?;
        validate_payload(self, seat, &p)?;
        let ids = payload_entity_ids(&p);
        let id_set = validate_entity_ids(&ids)?;
        validate_refs(&p, &id_set)?;
        // 旧持有物归还：先聚合并检查写回不溢出（聚合在 i64 语义下判定，绝不 saturating）。
        // 索引与 `Pool::put` 一致（`counts[c.0]`），越界即拒绝而不是 panic。
        let old_parts = held_parts(&self.players[seat]);
        let mut delta: HashMap<usize, i64> = HashMap::new();
        for (c, n) in &old_parts {
            *delta.entry(c.0 as usize).or_insert(0) += *n as i64;
        }
        for (idx, n) in &delta {
            let cur = *self
                .pool
                .counts
                .get(*idx)
                .ok_or_else(|| format!("pool_index({idx})"))?;
            let after = cur as i64 + *n;
            if !(0..=u16::MAX as i64).contains(&after) {
                return Err(format!("pool_overflow(card={idx}, {cur}+{n})"));
            }
        }
        // ---- 提交阶段（此后不再失败） ----
        self.commit_snapshot(seat, p, &ids, &old_parts);
        Ok(())
    }

    /// 提交：分配新 EID → 重映射 typed 引用 → 新实体不占池 → 旧持有物归还 → 白名单替换。
    ///
    /// 白名单（替换）：`tier`、`gold`、`max_gold_bonus`、`upgrade_cost`、`free_refreshes`、
    /// `board`、`hand`、`hand_queue`(+`hand_queue_marks`)、`shop`；
    /// 派生：`last_board = board.clone()`（EOT 语义）、`ended_turn = true`、
    /// `chronum_balance = 0`（与 `end_turn` 一致）；清空 `hats` / `mishmash_seen` /
    /// `revert_golden` / `discover_targets`（它们指向已被整体替换的旧实体）。
    ///
    /// 保留当前局原值：`id`、`alive`、`placement`、`health`、`armor`、`hero`、`powers`、
    /// `stats`、`pending`、`scheduled`、`effects`、`quests`、`rewards`、`trinkets`、
    /// `secrets`、`counters`、`levels`、`owed`、`scouted`、`seen_board`、对手簿记
    /// （`last_opponent`/`recent_opponents`/`next_opponent`/`next_is_ghost`）等。
    fn commit_snapshot(
        &mut self,
        seat: usize,
        mut p: Player,
        ids: &[EntityId],
        old_parts: &[(CardId, u16)],
    ) {
        let mut map: HashMap<EntityId, EntityId> = HashMap::with_capacity(ids.len());
        for old in ids {
            let new = self.alloc_eid();
            map.insert(*old, new);
        }
        let rm = |e: EntityId| -> EntityId {
            if e == 0 {
                return 0;
            }
            match map.get(&e) {
                Some(n) => *n,
                // 校验收敛过：走到这里说明校验有漏洞，保留旧 id 也不会更糟。
                None => e,
            }
        };
        for m in zone_minions_mut(&mut p) {
            m.eid = rm(m.eid);
            m.killed_by = rm(m.killed_by);
        }
        for h in p.hand.iter_mut() {
            h.hid = rm(h.hid);
            h.link = rm(h.link);
            h.group = rm(h.group);
            h.src = rm(h.src);
        }
        for s in p.shop.iter_mut() {
            s.sid = rm(s.sid);
        }
        // marks 与 hand_queue 必须等长（不一致时按引擎约定重建）。
        if p.hand_queue_marks.len() != p.hand_queue.len() {
            p.hand_queue_marks = vec![QueueMark::default(); p.hand_queue.len()];
        }
        for q in p.hand_queue_marks.iter_mut() {
            q.hid = rm(q.hid);
            q.link = rm(q.link);
            q.src = rm(q.src);
        }
        // pool_delta_unknown：注入实体不占共享池（否则会凭空多占/错误归池）。
        for m in zone_minions_mut(&mut p) {
            m.pool_copies = 0;
            m.pool_parts.clear();
        }
        for (c, n) in old_parts {
            self.pool.put(*c, *n);
        }
        let t = &mut self.players[seat];
        t.tier = p.tier;
        t.gold = p.gold;
        t.max_gold_bonus = p.max_gold_bonus;
        t.upgrade_cost = p.upgrade_cost;
        t.free_refreshes = p.free_refreshes;
        t.board = p.board;
        t.hand = p.hand;
        t.shop = p.shop;
        t.hand_queue = p.hand_queue;
        t.hand_queue_marks = p.hand_queue_marks;
        t.last_board = t.board.clone();
        t.ended_turn = true;
        t.chronum_balance = 0;
        t.hats.clear();
        t.mishmash_seen = None;
        t.revert_golden.clear();
        t.discover_targets.clear();
    }
}
