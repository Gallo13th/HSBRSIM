//! P3 系统类内容回归：Queen Azshara 主技能（`BG22_HERO_007p/+p2`）+ Dark Paradox 37 决策
//! （**保持 AT 5 形态机制**，证据见 `rust/FORK.md` §7 与 `docs/RUST_ENGINE.md` §8）。
//!
//! 运行：`cargo test --release -p hsbg-engine --test p3_systems`

use std::collections::HashSet;

use hsbg_engine::actions::Action;
use hsbg_engine::cards::{CardId, cid, db};
use hsbg_engine::flow::PARADOX_VARIANTS;
use hsbg_engine::script::{flag, script};
use hsbg_engine::state::{Minion, Pending};
use hsbg_engine::types::{PlayerId, Races};
use hsbg_engine::{Game, RulesConfig};

const AZSHARA: &str = "BG22_HERO_007";
const AMBITION: &str = "BG22_HERO_007p";
const CONQUEST: &str = "BG22_HERO_007p2";

// ══════════════════════════════════════════════════════════════════════
// 工具
// ══════════════════════════════════════════════════════════════════════

fn minion(g: &mut Game, p: PlayerId, id: &str) -> Minion {
    g.with_recruit(p, |c| c.new_minion(0, cid(id)))
}

fn set_board(g: &mut Game, p: PlayerId, ids: &[&str]) {
    let b: Vec<Minion> = ids.iter().map(|id| minion(g, p, id)).collect();
    g.players[p].board = b;
}

fn power_cards(g: &Game, p: PlayerId) -> Vec<CardId> {
    g.players[p].powers.iter().map(|h| h.card).collect()
}

/// 8 个座位全部是 Queen Azshara 的游戏（`hero_pool` 强制），过英雄选择、进入第 1 回合。
fn azshara_game(seed: u64) -> Game {
    let cfg = RulesConfig {
        hero_pool: vec![AZSHARA.to_string()],
        ..RulesConfig::default()
    };
    let mut g = Game::new(seed, cfg);
    for p in 0..8 {
        g.apply(p, Action::Choose(0)).unwrap();
    }
    assert_eq!(g.turn, 1);
    for p in 0..8 {
        assert_eq!(g.players[p].hero, Some(cid(AZSHARA)));
    }
    g
}

fn end_turn_all(g: &mut Game) {
    for p in 0..8 {
        while g.players[p].pending.last().is_some() {
            g.apply(p, Action::Choose(0)).unwrap();
        }
        if g.needs_action(p) {
            g.apply(p, Action::EndTurn).unwrap();
        }
    }
}

// ══════════════════════════════════════════════════════════════════════
// 1. Queen Azshara 主技能：注册 / 英雄可抽到
// ══════════════════════════════════════════════════════════════════════

#[test]
fn azshara_hero_and_powers_are_registered() {
    let d = db();
    let hero = d.get(cid(AZSHARA));
    assert!(hero.pools.hero);
    assert_eq!(hero.hero_power, Some(cid(AMBITION)));
    // 37.0.0 卡面：主技能 0 费被动、Naga Conquest 1 费主动。
    assert_eq!(d.get(cid(AMBITION)).cost, 0);
    assert_eq!(d.get(cid(CONQUEST)).cost, 1);

    let amb = script(cid(AMBITION)).expect("主技能脚本已注册");
    assert!(amb.flags & flag::PASSIVE != 0, "主技能是被动");
    assert_eq!(amb.hero_power_uses, 0);
    assert!(amb.hero_power.is_none(), "被动技能不可点击");
    assert!(
        amb.on_event.is_some() && amb.listens != 0,
        "总攻检查点监听器"
    );

    let conq = script(cid(CONQUEST)).expect("Naga Conquest 脚本已注册");
    assert!(conq.hero_power.is_some());
    assert_eq!(conq.hero_power_uses, 1, "每回合 1 次");
}

#[test]
fn azshara_is_offered_in_naga_lobbies() {
    // 37 大厅类型 = 10 种随机 5 种（含 Naga）；Azshara 的 assoc=NAGA，只在 Naga 大厅
    // 进入英雄池（`hero_fits` 类型过滤）。
    let cfg = RulesConfig {
        lobby_types: vec!["NAGA".to_string()],
        ..RulesConfig::default()
    };
    let g = Game::new(0, cfg);
    assert!(g.lobby_races.intersects(Races::NAGA));
    assert!(
        g.lobby_heroes().any(|c| c.id == AZSHARA),
        "Naga 大厅的英雄池应含 Azshara"
    );

    // 随机大厅（种子固定，结果确定）：Azshara 应能在某局被抽到。
    let mut offered = false;
    for seed in 0..200 {
        let g = Game::new(seed, RulesConfig::default());
        offered |= g.players.iter().any(|p| {
            matches!(
                p.pending.last(),
                Some(Pending::HeroSelect { options }) if options.contains(&cid(AZSHARA))
            )
        });
        if offered {
            break;
        }
    }
    assert!(offered, "Azshara 应可被随机大厅抽到");
}

/// P3 系统补齐：37 的 Naga 大厅（10 类随机 5 类）。36.6.3 轮换把 Naga 移出大厅类型，
/// AT 原版 `flow.rs::optional` 只有 9 种；37 数据里 Naga-only 随从在池，必须能在
/// Naga 大厅出现、在非 Naga 大厅不出现（池/英雄过滤共用 `lobby_races`）。
#[test]
fn naga_lobby_gates_naga_pool() {
    let d = db();
    let naga_forms = |g: &Game| {
        g.universe
            .iter()
            .filter(|c| d.get(**c).races == Races::NAGA)
            .count()
    };
    let cfg = RulesConfig {
        lobby_types: vec!["NAGA".to_string()],
        ..RulesConfig::default()
    };
    let g = Game::new(0, cfg);
    assert!(g.lobby_races.intersects(Races::NAGA));
    assert!(naga_forms(&g) > 0, "Naga 大厅应包含已实现的 Naga-only 随从");

    // 强制非 Naga 大厅：Naga-only 随从（races 恰为 NAGA）不在 universe。
    let cfg = RulesConfig {
        lobby_types: vec!["MURLOC".to_string()],
        ..RulesConfig::default()
    };
    let g = Game::new(0, cfg);
    assert!(!g.lobby_races.intersects(Races::NAGA));
    assert_eq!(naga_forms(&g), 0, "非 Naga 大厅不出现 Naga-only 随从");
}

#[test]
fn azshara_conquest_triggers_at_30_total_attack() {
    let mut g = azshara_game(1);
    assert_eq!(power_cards(&g, 0), vec![cid(AMBITION)]);

    // 4 只**不同**随从（同 id 会在回合开始三连合成 → 减员），总攻 7+7+8+7 = 29；
    // 高血量保证战斗不减员，专注于阈值语义。
    set_board(&mut g, 0, &["BG23_000", "BG23_002", "BG23_004", "BG23_007"]);
    for (i, atk) in [7, 7, 8, 7].into_iter().enumerate() {
        let m = &mut g.players[0].board[i];
        m.atk = atk;
        m.max_hp = 200;
        m.hp = 200;
    }
    end_turn_all(&mut g); // 29 < 30：检查点不触发
    assert_eq!(power_cards(&g, 0), vec![cid(AMBITION)]);
    assert_eq!(g.players[0].board.len(), 4, "战斗/三连不应减员");

    // 30 总攻：下一次检查点（回合结束）把主技能替换成 Naga Conquest。
    g.players[0].board[0].atk = 8;
    end_turn_all(&mut g);
    assert_eq!(power_cards(&g, 0), vec![cid(CONQUEST)]);
    // 一次性：再达到更高总攻也不会变出第二个技能。
    assert_eq!(g.players[0].powers.len(), 1);
}

// ══════════════════════════════════════════════════════════════════════
// 2. Naga Conquest：花 1 金 Discover 一张 Naga
// ══════════════════════════════════════════════════════════════════════

#[test]
fn naga_conquest_discovers_a_naga_for_one_gold() {
    let mut g = azshara_game(2);
    g.players[0].set_hero_power(0, cid(CONQUEST));
    g.players[0].gold = 10;
    g.players[0].tier = 4;

    g.apply(0, Action::HeroPower(0))
        .expect("Naga Conquest 可用");
    let Some(Pending::Discover { options, .. }) = g.players[0].pending.last().cloned() else {
        panic!("应打开 Discover 三选一");
    };
    assert_eq!(options.len(), 3);
    let mut offered: Vec<CardId> = vec![];
    for item in &options {
        let m = item.as_minion().expect("Naga Discover 只给随从");
        assert!(
            m.races.intersects(Races::NAGA),
            "{} 不是 Naga",
            db().get(m.card).id
        );
        // 卡面无 tier 限定：标准局上限 Tier 6（Tier 7 需该玩家已解锁 Tier 7）。
        assert!(m.tier <= 6, "{} Tier {}", db().get(m.card).id, m.tier);
        offered.push(m.card);
    }

    let pool_before = g.pool.get(offered[0]);
    g.apply(0, Action::Choose(0)).expect("选择第一张 Naga");
    assert_eq!(g.players[0].gold, 9, "Naga Conquest 花 1 金");

    let picked = &g.players[0].hand.last().expect("Naga 已入手").item;
    let m = picked.as_minion().expect("入手的是随从");
    assert!(m.races.intersects(Races::NAGA));
    assert_eq!(m.card, offered[0], "入手的就是选中的那张");
    assert_eq!(
        g.pool.get(m.card),
        pool_before - 1,
        "选中的随从占用共享池 1 张"
    );

    // 每回合 1 次：同一回合第二次使用被拒绝。
    assert!(g.apply(0, Action::HeroPower(0)).is_err());
}

#[test]
fn naga_conquest_requires_gold() {
    let mut g = azshara_game(4);
    g.players[0].set_hero_power(0, cid(CONQUEST));
    g.players[0].gold = 0;
    assert!(g.apply(0, Action::HeroPower(0)).is_err(), "0 金不可用");
    g.players[0].gold = 1;
    assert!(g.apply(0, Action::HeroPower(0)).is_ok());
}

// ══════════════════════════════════════════════════════════════════════
// 3. Dark Paradox 37 决策：保持 AT 5 形态机制（单卡动态 id 不做）
// ══════════════════════════════════════════════════════════════════════

/// 37 数据里 Dark Paradox 的 base 卡是**占位壳**（tier 1/1/1、不在池、无脚本），
/// 真正可玩的是 5 个 AT 36.6.3 形态 token；`flow.rs` 每局随机抽 1 个形态放进本局池。
/// 本测试把“保持 5 形态机制”的决策固化为数据/行为不变式（证据与后续项见 FORK §7）。
#[test]
fn dark_paradox_37_data_and_mapping_invariants() {
    let d = db();

    // (a) base 卡：37 官方单卡，但 AT schema 只有占位字段，不可直接入池。
    let base = d.get(cid("BG36_360"));
    assert_eq!((base.tier, base.atk, base.hp), (1, 1, 1), "占位壳");
    assert!(!base.pools.minion && !base.pools.tier7, "base 不在池");
    assert!(
        script(cid("BG36_360")).is_none(),
        "base 无脚本（非本次实现）"
    );
    assert_eq!(
        d.get(cid("BG36_360_G")).normal,
        Some(cid("BG36_360")),
        "base 的 golden 链接"
    );
    assert!(
        base.text
            .contains("different Dark Gift, stats, and Tier each game")
    );

    // (b) 5 个形态 token：每局随机 1 个；tier/属性/效果各不同，均有脚本与 golden。
    let expect: [&str; 5] = [
        "BG36_360t3",
        "BG36_360t4",
        "BG36_360t5",
        "BG36_360t6",
        "BG36_360t9",
    ];
    assert_eq!(PARADOX_VARIANTS, expect, "形态集合随上游/数据固定");
    let mut tiers = Vec::new();
    for id in PARADOX_VARIANTS {
        let def = d.get(cid(id));
        assert!(def.pools.minion, "{id} 应在单人池");
        assert!(script(cid(id)).is_some(), "{id} 需要脚本（形态效果）");
        assert_ne!(d.golden_of(cid(id)), cid(id), "{id} 需要 golden 形态");
        assert!((1..=6).contains(&def.tier), "{id} Tier {}", def.tier);
        tiers.push(def.tier);
    }
    tiers.sort_unstable();
    assert_eq!(tiers, vec![2, 3, 4, 5, 6], "5 形态覆盖 Tier 2..6");

    // (c) 行为不变式：每局恰好 1 个形态入池、base 永不入池、形态由 seed 决定且跨局不同。
    let mut seen: HashSet<CardId> = HashSet::new();
    for seed in 0..200 {
        let g = Game::new(seed, RulesConfig::default());
        let forms: Vec<CardId> = g
            .universe
            .iter()
            .copied()
            .filter(|c| d.get(*c).id.starts_with("BG36_360"))
            .collect();
        assert_eq!(forms.len(), 1, "seed {seed}: 每局恰好 1 个黑悖形态");
        assert!(
            !forms.contains(&cid("BG36_360")),
            "seed {seed}: base 不入池"
        );
        assert_eq!(g.paradox, Some(forms[0]), "seed {seed}: 抽取的形态");
        seen.insert(forms[0]);
    }
    assert_eq!(seen.len(), 5, "5 个形态都能作为某局的本局形态出现");

    // (d) 存档/回放：本局形态随 Game 精确序列化。
    let g = Game::new(11, RulesConfig::default());
    let form = g.paradox.expect("每局都有形态");
    let mut restored: Game = serde_json::from_str(&serde_json::to_string(&g).unwrap()).unwrap();
    assert_eq!(restored.paradox, Some(form));
    // 该形态的随从可以正常购买/入板/三连（golden 链接来自 token 自己的数据）。
    restored.players[0].board = vec![minion(&mut restored, 0, d.get(form).id.as_str())];
    let golden = d.golden_of(form);
    assert_ne!(golden, form);
    assert_eq!(d.get(golden).normal, Some(form));
}

// ══════════════════════════════════════════════════════════════════════
// 4. 英雄技能系统原语（P3 批次 A/B 可能复用的最小能力）
// ══════════════════════════════════════════════════════════════════════

/// 被动技能替换（`set_hero_power`）在招募期可用，且新技能的可点击性/费用立即生效。
#[test]
fn hero_power_replacement_takes_effect_immediately() {
    let mut g = azshara_game(5);
    g.players[0].gold = 10;
    // 被动技能没有 hero_power hook：不可点击。
    assert!(g.apply(0, Action::HeroPower(0)).is_err());
    // 替换成主动版本后立即可以点击（费用取数据 cost=1）。
    g.players[0].set_hero_power(0, cid(CONQUEST));
    assert_eq!(g.hero_power_price(0, 0), Some(1));
    assert!(g.apply(0, Action::HeroPower(0)).is_ok());
}
