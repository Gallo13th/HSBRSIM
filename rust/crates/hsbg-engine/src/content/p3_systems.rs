//! HSBRSIM P3（P1-C + 系统项）：37.0.0 主英雄技能 + Dark Paradox 37 机制。
//!
//! 1) `BG22_HERO_007p` Queen Azshara 主技能（“Azshara's Ambition → Naga Conquest”）：
//!    hsrl2 参考 `hsrl2/scripts/batches/batch_hero_combat3.py::AzsharaScript /
//!    NagaConquestScript`；37.0.0 卡面（`data/cards.json`）：
//!    - `BG22_HERO_007p`  “When your warband reaches 30 total Attack, begin your Naga
//!      Conquest.”（cost 0，passive）
//!    - `BG22_HERO_007p2` “Discover a Naga.”（cost 1，active，每回合 1 次）
//!    语义：己方战队（存活随从攻击力之和）首次达到 30 时，把主技能替换为 Naga Conquest；
//!    之后可花 1 金 Discover 一张 Naga（池感知三选一）。
//! 2) `BG36_360` Dark Paradox 的 37 重做：当前数据 schema 只提供 base 卡（tier 1/1/1 的
//!    占位壳，不在池）+ 5 个 36.6.3 形态 token（tier/属性/效果各不同）；`flow.rs` 每局随机
//!    抽出 1 个形态放进本局池。**评估结论：保持 5 形态机制**（37 卡面声明的“每局不同的
//!    Dark Gift/属性/Tier”在可观察玩法上已被该机制覆盖；单卡 id 动态化的收益仅是表征，
//!    成本要改 pool/shop/triple/obs/state_json 的 CardId 语义，属高风险）——证据、差异与
//!    P3 后续项见 `rust/FORK.md` §7 与 `docs/RUST_ENGINE.md` §8，决策测试在
//!    `tests/p3_systems.rs`。
//! 3) 本文件只提供脚本注册；需要的系统原语（`Ctx::set_hero_power` / `discover_minion` /
//!    `power_cards` 事件分发）复用现有引擎能力，未改引擎默认行为。

use super::*;

/// Queen Azshara 主技能的总攻阈值：37.0.0 卡面 “…reaches 30 total Attack…”（数据字面量）。
/// AT 数据 schema 没有 hsrl2 的 `script_data_num_2` / `evolution_card_id` 字段链，所以这里
/// 按卡面字面量 + hsrl2 `AzsharaScript` 的数据链结论（30 / 进化到 `BG22_HERO_007p2`）实现。
const AZSHARA_ATTACK_THRESHOLD: i32 = 30;
/// “Naga Conquest”（37.0.0 `BG22_HERO_007p2`，cost 1）。
const NAGA_CONQUEST: &str = "BG22_HERO_007p2";

/// 主技能检查点：能改变“己方战队总攻”的引擎事件 + 回合开始/结束兜底。
///
/// 覆盖论证（与 hsrl2 `AzsharaScript` 的检查点集同构）：总攻变化来源 = 新随从入板
/// （`PLAYED`/`SUMMONED`/`BOUGHT`/`DISCOVERED` 后的入板）/ 离板（`SOLD`/`DIED`/`CONSUMED`）/
/// 属性变化（`SPELL_CAST`、`BATTLECRY`、`GEM_PLAYED`、`MAGNETIZED`、英雄技能自身等）。
/// 回合开始/结束兜底覆盖 EoT 增益与战斗内永久化（下一检查点收口；技能使用窗口是招募期，
/// 时点差异不影响可用性）。重复触发无副作用（替换后旧技能的监听器随技能移除）。
const AZSHARA_CHECKPOINTS: u32 = ev::PLAYED
    | ev::SUMMONED
    | ev::BOUGHT
    | ev::SOLD
    | ev::DIED
    | ev::MAGNETIZED
    | ev::DISCOVERED
    | ev::CARD_PLAYED
    | ev::SPELL_CAST
    | ev::GEM_PLAYED
    | ev::CONSUMED
    | ev::BATTLECRY;

/// 己方战队（存活随从）总攻击力。
///
/// 必须读 `Ctx::boards[side]` 而不是 `Player::board`：招募期 `Game::with_recruit` 会把
/// 行动方的战队本体挪进 Ctx 的 side 0（`Player::board` 暂时为空），战斗期两边是克隆
/// 战场；`content::check_total_attack`（Pressure the Authorities 任务）同款口径。
fn warband_attack(c: &Ctx, side: Side) -> i32 {
    c.boards[side]
        .iter()
        .filter(|m| m.alive())
        .fold(0i32, |total, m| total.saturating_add(m.atk))
}

/// 达到 30 总攻 → 把该英雄技能槽替换成 Naga Conquest（一次性；旧技能移除后监听器失效）。
fn azshara_check(c: &mut Ctx, me: Me) {
    if warband_attack(c, me.side) < AZSHARA_ATTACK_THRESHOLD {
        return;
    }
    let Some(slot) = c
        .player_ref(me.side)
        .and_then(|p| p.powers.iter().position(|h| h.card == me.card))
    else {
        return;
    };
    c.set_hero_power(me.side, slot, cid(NAGA_CONQUEST));
}

fn azshara_on_event(c: &mut Ctx, me: Me, _e: &Event) {
    azshara_check(c, me);
}

fn azshara_turn_hook(c: &mut Ctx, me: Me) {
    azshara_check(c, me);
}

fn azshara_ambition() -> Script {
    Script {
        on_event: Some(azshara_on_event),
        listens: AZSHARA_CHECKPOINTS,
        start_of_turn: Some(azshara_turn_hook),
        end_of_turn: Some(azshara_turn_hook),
        // 被动技能：不可点击（hero_power hook 为空 → `hero_power_price` 返回 None）。
        flags: flag::PASSIVE,
        hero_power_uses: 0,
        ..E
    }
}

fn naga_conquest() -> Script {
    Script {
        hero_power: Some(|c, me, _| {
            // “Discover a Naga”：池感知三选一。ALL 种族随从天然命中 `intersects(NAGA)`；
            // 卡面无 tier 限定（同 hsrl2 `Discover(race=NAGA)` 口径：常规上限 Tier 6，
            // 仅当该玩家已解锁 Tier 7 时把 Tier 7 Naga 纳入）。
            let tier7 = c.player_ref(me.side).is_some_and(|p| p.tier7);
            let max_tier = if tier7 { 7 } else { c.g.cfg.max_regular_tier };
            c.discover_minion(me.side, me.card, 3, |d| {
                d.races.intersects(Races::NAGA) && d.tier <= max_tier
            });
        }),
        ..E
    }
}

pub fn scripts() -> Vec<(&'static str, Script)> {
    vec![
        ("BG22_HERO_007p", azshara_ambition()),
        (NAGA_CONQUEST, naga_conquest()),
    ]
}
