//! HSBRSIM P3（P1-B/P1-D 批次 B）：37.0.0 池内缺失随从 + 池内酒馆法术的 Rust content 移植。
//!
//! 负责人：content-delta-analyst（写范围：本文件 + `tests/p3_cards_b.rs`）。
//! 卡表/取值/参考：`docs/PORTING_37_PLAN.md` §4.1/§4.3/§5.2。
//! 数值/文本以 37 数据为准（data/cards.json meta 37.0.0.255130）；本批 8 张均无
//! `script_data_num` 导出（AT schema 无该字段），故数值按卡面文本字面量，金色行为用
//! `me.g()` 表达（金色独立 CardDef 的文本差异：twice / 4 次 / +4/+6 等）。
//!
//! 批次 B 卡（6 随从 + 2 池内法术，全部 M 级）：
//! - `BG33_319` Rimescale Priestess（Spellcraft：随机获取一张“给属性”的酒馆法术；
//!   随从本体 `E`——法术由引擎 `Ctx::give_spellcraft` 发放；令牌法术
//!   `BG33_319t/_Gt` 由本文件实现）
//! - `BG34_925` Seafloor Recruiter（Rally：对右侧随从施放 Chef's Choice；金色两次）
//! - `BG35_921` Abyssal Bruiser（圣盾；本局每施放一个酒馆法术 +2/+1；金色 +4/+2）
//! - `BG36_508` Cagey Conjurer（Activate (1)：随机施放 2 个酒馆法术，尽可能以本随从
//!   为目标；金色 4 个）
//! - `BG36_622` Torrential Ruiner（每当你对纳迦施放法术，使你的随从 +2/+3；金色 +4/+6）
//! - `BG36_921` Fleeing Fugitive（每当你对本随从施放法术，获得 +1 生命；金色 +2）
//! - `BG32_815` Shifting Tide（使一个随从 +1/+1 两次；若是纳迦，重复一次 = 共 4 次）
//! - `BG35_922` Queen's Command（使你的随从 +2/+2；使你的纳迦再 +2/+2）
//!
//! 语义参考（hsrl2 legacy，只读 oracle）：`batches/batch_unfreeze.py::CageyConjurerScript`、
//! `batch_rally2.py::SeafloorRecruiterScript`、`batch_counters.py::AbyssalBruiserScript`、
//! `batch_econ_misc2.py::{TorrentialRuinerScript,FleeingFugitiveScript}`、
//! `batch_spells4.py::ShiftingTideScript`、`batch_spells_final.py::QueensCommandScript`；
//! `BG33_319` 在 hsrl2 无脚本（按卡面新写；AT `content/buddies_c.rs` Lantern Tender
//! 提供“随机获取给属性酒馆法术”的同款口径与 STAT_SPELLS 清单）。
//!
//! 与 AT 引擎原语的对齐（P3 起以 AT 为权威）：
//! - “Cast X”（`BG34_925`/`BG36_508`）按 `Ctx::you_cast` 语义——卡面文本让“你”施放：
//!   计入法术计数、触发 after-you-cast、受 spells-cast-extra-time 影响（引擎注释同口径）；
//! - “Whenever you cast a spell on …” 用 `ev::SPELL_CAST` + `aimed_at_me`/`cast_from_hand`
//!   （AT `content/mod.rs::aimed_at_me` 的“从手牌瞄准”口径；效果施法不算，hsrl2 同裁定）；
//! - `BG35_921` 的“本局每施放酒馆法术 +2/+1”是自光环：引擎 `bonus_of` 只硬编码了部分
//!   卡 id（改动属引擎核心，不在本任务写范围），故按 AT Script 原语实现为
//!   `ev::SPELL_CAST` 递增 + `ev::SUMMONED` 入场回溯补算；数值与 “Has +X/+Y” 等效
//!   （不使用 `flag::IMPROVES`——那是显示计数器语义）。

use super::*;

// ── 卡 id ────────────────────────────────────────────────────────────
const CHEFS_CHOICE: &str = "BG28_518";
/// Rimescale Priestess 的 Spellcraft 法术（普通/金色是独立卡 id，见数据 spellcraft 字段）。
const RIME_OR_REASON: &str = "BG33_319t";
const RIME_OR_REASON_G: &str = "BG33_319_Gt";

/// “给属性”的酒馆法术（AT `content/buddies_c.rs::STAT_SPELLS` 的 36.6.3 口径 29 张，
/// 全部仍在 37 池；另加 37 池内新增的 2 张：`BG32_815`/`BG35_922`——本批同时移植）。
/// 37 数据未导出 CardDefs tag 4254（“gives stats”），沿用上游“显式清单”口径，
/// 不用文本正则猜（避免把 Transform / Consume 类算进来）。
const STAT_SPELLS: [&str; 31] = [
    "BG28_168",
    "BG28_169",
    "BG28_503",
    "BG28_520",
    "BG28_825",
    "BG28_838",
    "BG28_845",
    "BG28_886",
    "BG28_888",
    "BG28_897",
    "BG28_966",
    "BG31_880",
    "BG31_881",
    "BG31_886",
    "BG32_337",
    "BG32_815",
    "BG33_811",
    "BG33_812",
    "BG33_813",
    "BG34_272",
    "BG34_444",
    "BG34_990",
    "BG35_912",
    "BG35_922",
    "BG35_951",
    "BG36_246",
    "BG36_301t",
    "BG36_371",
    "BG36_624",
    "BG36_883",
    "EBG_Spell_032",
];

fn is_naga(c: &Ctx, eid: EntityId) -> bool {
    eid != 0 && c.find_any(eid).is_some_and(|m| m.is(Races::NAGA))
}

/// Get `n` random Tavern spells that give stats (Tier <= your Tavern Tier; the same tier
/// filter as hsrl2 Lantern Tender / Stash of the Scribe).
fn get_stat_spells(c: &mut Ctx, side: Side, n: i32) {
    let tier = c.tier(side);
    for _ in 0..n {
        if let Some(s) = c.random_spell(|d| d.tier <= tier && STAT_SPELLS.contains(&d.id.as_str()))
        {
            c.give_card(side, s);
        }
    }
}

/// Cast `n` random Tavern spells (Tier <= your Tavern Tier). A spell that needs a target
/// prefers `source` when it is legal ("targets this if possible"), else a random legal one;
/// a Choose One spell takes a random mode (AT `content/quests.rs::Untamed Sorcery` 口径).
fn cast_random_tavern_spells(c: &mut Ctx, side: Side, source: EntityId, n: i32) {
    let tier = c.tier(side);
    for _ in 0..n {
        // The source may be gone after an earlier cast (Transform / destroy): stop there
        // (hsrl2 Cagey Conjurer rechecks before every cast).
        if source != 0 && c.find_any(source).is_none() {
            break;
        }
        let Some(s) = c.random_spell(|d| d.tier <= tier) else {
            break;
        };
        let spec = effect_target_spec(s).unwrap_or(TargetSpec::None);
        let target = if spec == TargetSpec::None {
            0
        } else {
            let opts = c.legal_targets(side, spec, source);
            if source != 0 && opts.contains(&source) {
                source
            } else {
                c.g.rng.pick(&opts).copied().unwrap_or(0)
            }
        };
        let choose = script(s).is_some_and(|x| x.choose_one);
        let opt = if choose { c.g.rng.below(2) as u8 } else { 0 };
        c.you_cast(side, s, 0, target, opt);
    }
}

// ── BG34_925 Seafloor Recruiter ──────────────────────────────────────
/// Rally: cast Chef's Choice on the minion to the right (golden: twice). No right neighbor
/// or a dead one -> nothing (hsrl2 `batch_rally2` same edge behavior).
fn seafloor_rally(c: &mut Ctx, me: Me, _defender: EntityId) {
    let Some((side, i)) = c.locate(me.eid) else {
        return;
    };
    let Some(right) = c.boards[side].get(i + 1) else {
        return;
    };
    if !right.alive() {
        return;
    }
    let target = right.eid;
    for _ in 0..me.g() {
        c.you_cast(me.side, cid(CHEFS_CHOICE), 0, target, 0);
    }
}

// ── BG35_921 Abyssal Bruiser ─────────────────────────────────────────
/// "Has +2/+1 for each Tavern spell you've cast this game": catch up when it enters the board
/// (the counter is player-level and may already be non-zero) and grow on every Tavern spell.
fn abyssal_bruiser_event(c: &mut Ctx, me: Me, e: &Event) {
    match e {
        Event::Summoned { side, eid } if *side == me.side && *eid == me.eid => {
            let n = c
                .player_ref(me.side)
                .map_or(0, |p| p.stats.tavern_spells_cast);
            if n > 0 {
                c.buff(me.eid, 2 * me.g() * n, me.g() * n);
            }
        }
        Event::SpellCast {
            side, tavern: true, ..
        } if *side == me.side => {
            c.buff(me.eid, 2 * me.g(), me.g());
        }
        _ => {}
    }
}

// ── BG36_622 Torrential Ruiner ───────────────────────────────────────
/// Whenever you cast a spell on a Naga, give your minions +2/+3 (golden +4/+6). "You cast"
/// = a spell aimed from hand (AT `aimed_at_me` 口径; effect casts don't count).
fn torrential_ruiner_event(c: &mut Ctx, me: Me, e: &Event) {
    let Event::SpellCast { side, target, .. } = e else {
        return;
    };
    if *side != me.side || !c.cast_from_hand || !is_naga(c, *target) {
        return;
    }
    for eid in c.friendly(me.side) {
        c.buff(eid, 2 * me.g(), 3 * me.g());
    }
}

// ── BG36_508 Cagey Conjurer ──────────────────────────────────────────
/// Activate (1): cast 2 random Tavern spells (golden: 4), targets this if possible.
fn cagey_conjurer_activate(c: &mut Ctx, me: Me, _target: EntityId) {
    let n = 2 * me.g();
    cast_random_tavern_spells(c, me.side, me.eid, n);
}

// ── BG36_921 Fleeing Fugitive ────────────────────────────────────────
/// Whenever you cast a spell on this, gain +1 Health (golden: +2).
fn fleeing_fugitive_event(c: &mut Ctx, me: Me, e: &Event) {
    if aimed_at_me(c, me, e) {
        c.buff(me.eid, 0, me.g());
    }
}

pub fn scripts() -> Vec<(&'static str, Script)> {
    vec![
        // ------------------------------------------------------------ 随从
        // Spellcraft minion: the spell is given by the engine (`Ctx::give_spellcraft`).
        ("BG33_319", E), // Rimescale Priestess
        (
            "BG34_925", // Seafloor Recruiter
            Script {
                rally: Some(seafloor_rally),
                ..E
            },
        ),
        (
            "BG35_921", // Abyssal Bruiser
            Script {
                on_event: Some(abyssal_bruiser_event),
                listens: ev::SUMMONED | ev::SPELL_CAST,
                ..E
            },
        ),
        (
            "BG36_508", // Cagey Conjurer
            Script {
                activate: Some((1, TargetSpec::None, cagey_conjurer_activate)),
                ..E
            },
        ),
        (
            "BG36_622", // Torrential Ruiner
            Script {
                on_event: Some(torrential_ruiner_event),
                listens: ev::SPELL_CAST,
                ..E
            },
        ),
        (
            "BG36_921", // Fleeing Fugitive
            Script {
                on_event: Some(fleeing_fugitive_event),
                listens: ev::SPELL_CAST,
                ..E
            },
        ),
        // ------------------------------------------------------------ Rimescale Priestess 的
        // Spellcraft 法术：Get a random Tavern spell that gives stats (golden: 2).
        (
            RIME_OR_REASON,
            Script {
                spell: Some(|c, me, _| get_stat_spells(c, me.side, sc_g(me))),
                ..E
            },
        ),
        (
            RIME_OR_REASON_G,
            Script {
                spell: Some(|c, me, _| get_stat_spells(c, me.side, sc_g(me))),
                ..E
            },
        ),
        // ------------------------------------------------------------ 池内酒馆法术
        // Shifting Tide: give a minion +1/+1 twice; a Naga repeats it (four times in total).
        (
            "BG32_815",
            Script {
                spell_target: TargetSpec::Friendly,
                spell: Some(|c, me, t| {
                    let times = if is_naga(c, t) { 4 } else { 2 };
                    for _ in 0..times {
                        spell_buff(c, me, t, 1, 1);
                    }
                }),
                ..E
            },
        ),
        // Queen's Command: give your minions +2/+2; give all your Naga another +2/+2.
        (
            "BG35_922",
            Script {
                spell: Some(|c, me, _| {
                    for t in c.friendly(me.side) {
                        spell_buff(c, me, t, 2, 2);
                    }
                    for t in c.friendly_where(me.side, |m| m.is(Races::NAGA)) {
                        spell_buff(c, me, t, 2, 2);
                    }
                }),
                ..E
            },
        ),
    ]
}
