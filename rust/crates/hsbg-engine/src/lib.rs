#![recursion_limit = "256"]
//! HSbg Engine: a Hearthstone Battlegrounds solo-mode simulator engine with a
//! reinforcement-learning interface. This is the vendored fork of the TavernGym engine
//! (AutoTavern, MIT; see `FORK.md`): public API and behaviour are identical to upstream,
//! only the crate/package names differ. The reported game-data version is read from
//! `data/cards.json`'s `meta` (so replacing the data file updates it).
//!
//! Module map:
//! - `cards`   static card database (`data/cards.json`)
//! - `config`  rules configuration and simulator options
//! - `state`   minions, hand/shop items, players, pool, pending choices
//! - `engine`  `Game` container and the effect context `Ctx` (summon/buff/damage/death...)
//! - `recruit` tavern and player actions; `combat` automatic combat; `flow` turn lifecycle
//! - `script`  card behaviour hooks; `content` the implemented cards
//! - `actions` flat action space and legality masks; `obs` observation encoding
//! - `env`     single-agent environment (one seat against scripted bots, `bot`)
//! - `batch`   batched environment: many games, any set of controlled seats
//! - `debug`   JSON views of a game, the card catalog and debug commands
//! - `invariants` state checks for fuzzing (`examples/fuzz.rs`)

pub mod actions;
pub mod batch;
pub mod bot;
pub mod cards;
pub mod combat;
pub mod config;
pub mod content;
pub mod debug;
pub mod engine;
pub mod env;
pub mod event;
pub mod experimental;
pub mod flow;
pub mod guard;
pub mod invariants;
pub mod obs;
pub mod recruit;
pub mod rng;
pub mod script;
// P4-M1：逐步 MCTS 搜索核（新增能力，不改变默认行为；见 rust/FORK.md §7）。
pub mod search;
pub mod turn_search;
pub mod state;
pub mod types;
pub mod workers;

pub use actions::{Action, N_ACTIONS};
pub use batch::{BatchEnv, SlotResult};
pub use config::RulesConfig;
pub use engine::Game;
pub use env::SoloEnv;

/// Simulator library version.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
/// Hearthstone client build the simulator replicates, as a **fallback**: the authoritative
/// value is `meta.client_version` of the embedded card data (`data/cards.json`), see
/// [`game_version`]. The constant keeps upstream's value so a data file without `meta` still
/// reports a sane version.
pub const GAME_VERSION: &str = "36.6.3.253932";
/// Server-side rule overlay, as a **fallback**: the authoritative value is
/// `meta.server_patch` of the embedded card data, see [`server_rules_version`].
pub const SERVER_RULES_VERSION: &str = "36.6.3";

/// Hearthstone client build the embedded card data replicates (`meta.client_version` of
/// `data/cards.json`), or [`GAME_VERSION`] when the data file carries none.
///
/// Data-driven on purpose: HSBRSIM 替换卡牌数据（36.6.3 -> 37.0.0.255130）不必改引擎代码，
/// 上报的版本自动跟随数据文件。
pub fn game_version() -> &'static str {
    let v = crate::cards::db().client_version.as_str();
    if v.is_empty() { GAME_VERSION } else { v }
}

/// Server-side rule overlay of the embedded card data (`meta.server_patch` of
/// `data/cards.json`), or [`SERVER_RULES_VERSION`] when the data file carries none.
pub fn server_rules_version() -> &'static str {
    let v = crate::cards::db().server_patch.as_str();
    if v.is_empty() {
        SERVER_RULES_VERSION
    } else {
        v
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn versions() {
        // 版本由数据 meta 驱动，常量只是数据缺 meta 时的 fallback（见 rust/FORK.md）。
        let d = crate::cards::db();
        assert_eq!(game_version(), d.client_version.as_str());
        assert_eq!(server_rules_version(), d.server_patch.as_str());
        assert!(!game_version().is_empty());
        assert!(!server_rules_version().is_empty());
        assert!(game_version().split('.').count() >= 3, "{}", game_version());
        assert!(!VERSION.is_empty());
    }
}
