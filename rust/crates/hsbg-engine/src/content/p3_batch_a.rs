//! HSBRSIM P3（P1-B 批次 A）：37.0.0 池内缺失随从的 Rust content 移植。
//!
//! 负责人：engine-fixer（写范围：本文件 + `tests/p3_cards_a.rs`）。
//! 卡表/取值/参考：`docs/PORTING_37_PLAN.md` §4.1/§5.2；hsrl2 参考脚本见各卡注释。
//! 文本/数值以 37 数据（`crates/hsbg-engine/data/cards.json`，meta 37.0.0.255130）为准。
//!
//! 批次 A 卡（8 张，全部 M 级，均为 Naga/Spellcraft 族）：
//! - `BG23_002` Shell Collector（Battlecry: Get a Tavern Coin；金 2 枚）
//! - `BG26_505` Zesty Shaker（每回合一次：Spellcraft 法术打在本体 → 获得其新副本；金 2 份）
//! - `BG27_514` Sea Witch Zar'jira（Spellcraft：复制酒馆中另一个随从；金 2 份）T7
//! - `BG31_035` Groundbreaker（After you play a Naga +1/+1；每 3 个法术 Improve）
//! - `BG31_920` Darkcrest Strategist（Spellcraft：随机 Tier N Naga，每回合 N+1）
//! - `BG31_925` Showy Cyclist（Deathrattle: 全体己方 Naga +2/+1；每 3 法术 Improve）
//! - `BG32_835` Tranquil Meditative（Spellcraft：酒馆法术额外 +1/+1 this game；金 +2/+2）
//! - `BG32_837` Fauna Whisperer（EoT：对相邻随从施放 Natural Blessing；金两次）
//!
//! 说明（与 hsrl2 legacy oracle 的一处有意口径差异）：hsrl2 的 "Improved by every 3 spells
//! you've cast this game" 用 `TAVERN_SPELLS_CAST_THIS_GAME`（仅酒馆法术，hsrl2 引擎缺口）；
//! AutoTavern 引擎有完整 `PlayerStats::spells_cast`（所有计入的施放，含 Spellcraft），
//! 与官方卡面 "every 3 spells you've cast this game" 一致 → 本移植用 `spells_cast`。

use super::*;

/// "Improved by every 3 spells you've cast this game": multiplier 1,2,3…
fn spell_improve(c: &Ctx, side: Side) -> i32 {
    1 + c.player_ref(side).map_or(0, |p| p.stats.spells_cast).max(0) / 3
}

fn is_naga(d: &crate::cards::CardDef) -> bool {
    d.races.contains(Races::NAGA)
}

// ---------------------------------------------------------------- BG23_002 Shell Collector

/// Battlecry: Get a Tavern Coin（金 "Get 2 Tavern Coins" → me.g() 枚）。
fn shell_collector(c: &mut Ctx, me: Me, _t: EntityId) {
    for _ in 0..me.g() {
        c.give_card(me.side, crate::cardid!("BG28_810"));
    }
}

// ---------------------------------------------------------------- BG26_505 Zesty Shaker

/// 每回合一次（counter 1→0，回合开始重置）：Spellcraft 法术打在本体 →
/// 获得该法术的 me.g() 份新副本（副本是 Spellcraft 法术 → temporary）。
fn zesty_reset(c: &mut Ctx, me: Me) {
    if let Some(m) = c.minion_mut(me.eid) {
        m.counter = 1;
    }
}

fn zesty_on_cast(c: &mut Ctx, me: Me, e: &Event) {
    if let Event::SpellCast {
        side, card, target, ..
    } = e
        && *side == me.side
        && *target == me.eid
        && db().get(*card).spellcraft_spell
    {
        let ready = c.minion(me.eid).is_some_and(|m| m.counter > 0);
        if !ready {
            return;
        }
        if let Some(m) = c.minion_mut(me.eid) {
            m.counter -= 1;
        }
        for _ in 0..me.g() {
            c.give_temp_spell(me.side, *card, me.eid);
        }
    }
}

// ---------------------------------------------------------------- BG27_514 Sea Witch Zar'jira

/// Spellcraft "Siren's Song": choose a Tavern minion (not Zar'jira) → get me.g() copies.
/// 副本保留馆内实体当前属性/附魔（full copy），不占池。
fn sirens_song(c: &mut Ctx, me: Me, target: EntityId) {
    let Some(p) = c.player_ref(me.side) else {
        return;
    };
    let Some(slot) = p.shop.iter().find(|s| s.sid == target) else {
        return;
    };
    let Item::Minion(m) = &slot.item else {
        return;
    };
    let m = m.clone();
    // 卡面 "except Sea Witch Zar'jira"（含金色版本）。
    let is_zarjira = m.is_card("BG27_514") || m.is_card("BG27_514_G");
    if is_zarjira || target == c.cast_src {
        return;
    }
    for _ in 0..sc_g(me) {
        let copy = c.full_copy(&m);
        c.add_to_hand(me.side, Item::Minion(copy));
    }
}

// ---------------------------------------------------------------- BG31_035 Groundbreaker

/// After you play a Naga, gain +1/+1 (golden +2/+2), improved by every 3 spells cast.
fn groundbreaker(c: &mut Ctx, me: Me, e: &Event) {
    if let Event::CardPlayed { side, card, .. } = e
        && *side == me.side
        && db().get(*card).is_minion()
        && is_naga(db().get(*card))
    {
        let k = me.g() * spell_improve(c, me.side);
        c.buff(me.eid, k, k);
    }
}

// ---------------------------------------------------------------- BG31_920 Darkcrest Strategist

/// "Improves each turn!": 起始 Tier 1（counter=1），每个己方回合结束 +1，封顶 T7。
fn strategist_create(m: &mut Minion) {
    m.counter = 1;
}

fn strategist_eot(c: &mut Ctx, me: Me) {
    if let Some(m) = c.minion_mut(me.eid) {
        m.counter = (m.counter + 1).min(7);
    }
}

/// Spellcraft "Evolving Strategy": 随机 Tier = 来源随从当前档位的 Naga，me.g() 次
/// （金 "Get two random Tier 1 Naga" → sc_g=2）。来源离场 → 回退 Tier 1。
fn evolving_strategy(c: &mut Ctx, me: Me, _t: EntityId) {
    let tier = c.minion(c.cast_src).map_or(1, |m| m.counter.max(1)) as u8;
    for _ in 0..sc_g(me) {
        if let Some(card) = c.random_minion(|d| d.is_minion() && is_naga(d) && d.tier == tier) {
            c.give_card(me.side, card);
        }
    }
}

// ---------------------------------------------------------------- BG31_925 Showy Cyclist

/// Deathrattle: Give all your Naga +2/+1 (golden +4/+2), improved by every 3 spells cast.
fn showy_cyclist(c: &mut Ctx, me: Me) {
    let k = me.g() * spell_improve(c, me.side);
    for m in c.friendly_where(me.side, |m| m.races.contains(Races::NAGA)) {
        c.buff(m, 2 * k, k);
    }
}

// ---------------------------------------------------------------- BG32_835 Tranquil Meditative

/// Spellcraft "Meditation": Your Tavern spells give an extra +1/+1 this game
/// （金法术 +2/+2 → sc_g）。
fn meditation(c: &mut Ctx, me: Me, _t: EntityId) {
    let n = sc_g(me);
    if let Some(p) = c.player(me.side) {
        p.stats.spell_atk = p.stats.spell_atk.saturating_add(n);
        p.stats.spell_hp = p.stats.spell_hp.saturating_add(n);
    }
}

// ---------------------------------------------------------------- BG32_837 Fauna Whisperer

/// At the end of your turn, cast Natural Blessing on adjacent minions
/// （金 "twice" → me.g() 轮；Natural Blessing = BG28_845，+2/+1 / 共享类型）。
fn fauna_whisperer(c: &mut Ctx, me: Me) {
    let targets = c.neighbors(me.eid);
    for _ in 0..me.g() {
        for t in &targets {
            if c.on_board(*t) {
                c.you_cast(me.side, crate::cardid!("BG28_845"), 0, *t, 0);
            }
        }
    }
}

pub fn scripts() -> Vec<(&'static str, Script)> {
    vec![
        // ------------------------------------------------ Shell Collector
        (
            "BG23_002",
            Script {
                battlecry: Some(shell_collector),
                ..E
            },
        ),
        (
            "BG23_002_G",
            Script {
                battlecry: Some(shell_collector),
                ..E
            },
        ),
        // ------------------------------------------------ Zesty Shaker
        (
            "BG26_505",
            Script {
                on_create: Some(|m| m.counter = 1),
                start_of_turn: Some(zesty_reset),
                on_event: Some(zesty_on_cast),
                listens: ev::SPELL_CAST,
                ..E
            },
        ),
        (
            "BG26_505_G",
            Script {
                on_create: Some(|m| m.counter = 1),
                start_of_turn: Some(zesty_reset),
                on_event: Some(zesty_on_cast),
                listens: ev::SPELL_CAST,
                ..E
            },
        ),
        // ------------------------------------------------ Sea Witch Zar'jira
        ("BG27_514", E),
        ("BG27_514_G", E),
        (
            "BG27_514t",
            Script {
                spell: Some(sirens_song),
                spell_target: TargetSpec::Tavern,
                ..E
            },
        ),
        (
            "BG27_514t_G",
            Script {
                spell: Some(sirens_song),
                spell_target: TargetSpec::Tavern,
                ..E
            },
        ),
        // ------------------------------------------------ Groundbreaker
        (
            "BG31_035",
            Script {
                on_event: Some(groundbreaker),
                listens: ev::CARD_PLAYED,
                ..E
            },
        ),
        (
            "BG31_035_G",
            Script {
                on_event: Some(groundbreaker),
                listens: ev::CARD_PLAYED,
                ..E
            },
        ),
        // ------------------------------------------------ Darkcrest Strategist
        (
            "BG31_920",
            Script {
                on_create: Some(strategist_create),
                end_of_turn: Some(strategist_eot),
                ..E
            },
        ),
        (
            "BG31_920_G",
            Script {
                on_create: Some(strategist_create),
                end_of_turn: Some(strategist_eot),
                ..E
            },
        ),
        (
            "BG31_920t",
            Script {
                spell: Some(evolving_strategy),
                ..E
            },
        ),
        (
            "BG31_920_Gt",
            Script {
                spell: Some(evolving_strategy),
                ..E
            },
        ),
        // ------------------------------------------------ Showy Cyclist
        (
            "BG31_925",
            Script {
                deathrattle: Some(showy_cyclist),
                ..E
            },
        ),
        (
            "BG31_925_G",
            Script {
                deathrattle: Some(showy_cyclist),
                ..E
            },
        ),
        // ------------------------------------------------ Tranquil Meditative
        ("BG32_835", E),
        ("BG32_835_G", E),
        (
            "BG32_835t",
            Script {
                spell: Some(meditation),
                ..E
            },
        ),
        (
            "BG32_835_Gt",
            Script {
                spell: Some(meditation),
                ..E
            },
        ),
        // ------------------------------------------------ Fauna Whisperer
        (
            "BG32_837",
            Script {
                end_of_turn: Some(fauna_whisperer),
                ..E
            },
        ),
        (
            "BG32_837_G",
            Script {
                end_of_turn: Some(fauna_whisperer),
                ..E
            },
        ),
    ]
}
