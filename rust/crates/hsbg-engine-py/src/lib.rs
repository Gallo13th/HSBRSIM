//! Python bindings (`hsbg_engine._core`). Thin wrappers: all logic lives in `hsbg-engine`.
//! Arrays cross the boundary as little-endian bytes owned by Python; `python/hsbg_engine`
//! wraps them in numpy arrays.

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBytes};

use hsbg_engine::actions::{Action, N_ACTIONS};
use hsbg_engine::batch::{BatchEnv, SlotResult};
use hsbg_engine::bot;
use hsbg_engine::cards::db;
use hsbg_engine::obs::{OBS_CARDS, OBS_FLOATS};
use hsbg_engine::search::{SearchConfig, search as rust_search};
use hsbg_engine::turn_search::{
    ActionAggregate, TurnSearchConfig, turn_search as rust_turn_search,
};
use hsbg_engine::{Game, RulesConfig, SoloEnv};

mod collector;

fn parse_config(config_json: Option<&str>) -> PyResult<RulesConfig> {
    match config_json {
        None => Ok(RulesConfig::default()),
        // Unknown keys are an error and the result is validated (`RulesConfig::from_json`).
        Some(s) => RulesConfig::from_json(s).map_err(PyValueError::new_err),
    }
}

/// A seat index of a running game, as a Python `ValueError` instead of a Rust panic.
fn check_seat(g: &Game, p: usize) -> PyResult<()> {
    if p < g.players.len() {
        Ok(())
    } else {
        Err(PyValueError::new_err(format!(
            "seat {p} out of range (0..{})",
            g.players.len()
        )))
    }
}

fn mask_bytes<'py>(py: Python<'py>, mask: &[bool]) -> Bound<'py, PyBytes> {
    let v: Vec<u8> = mask.iter().map(|b| *b as u8).collect();
    PyBytes::new(py, &v)
}

fn f32_bytes<'py>(py: Python<'py>, v: &[f32]) -> Bound<'py, PyBytes> {
    let b: Vec<u8> = v.iter().flat_map(|x| x.to_le_bytes()).collect();
    PyBytes::new(py, &b)
}

fn i32_bytes<'py>(py: Python<'py>, v: &[i32]) -> Bound<'py, PyBytes> {
    let b: Vec<u8> = v.iter().flat_map(|x| x.to_le_bytes()).collect();
    PyBytes::new(py, &b)
}

type ObsBytes<'py> = (Bound<'py, PyBytes>, Bound<'py, PyBytes>);

fn obs_bytes<'py>(py: Python<'py>, o: &hsbg_engine::obs::Observation) -> ObsBytes<'py> {
    (f32_bytes(py, &o.floats), i32_bytes(py, &o.cards))
}

/// A full eight-player game; every seat is driven explicitly (self-play, search, tests).
#[pyclass(name = "Game", skip_from_py_object)]
#[derive(Clone)]
struct PyGame {
    g: Game,
}

#[pymethods]
impl PyGame {
    #[new]
    #[pyo3(signature = (seed, config_json=None))]
    fn new(seed: u64, config_json: Option<&str>) -> PyResult<Self> {
        Ok(PyGame {
            g: Game::new(seed, parse_config(config_json)?),
        })
    }

    #[getter]
    fn turn(&self) -> u32 {
        self.g.turn
    }
    #[getter]
    fn num_players(&self) -> usize {
        self.g.players.len()
    }
    fn is_over(&self) -> bool {
        self.g.is_over()
    }
    fn needs_action(&self, p: usize) -> PyResult<bool> {
        check_seat(&self.g, p)?;
        Ok(self.g.needs_action(p))
    }
    /// Legal-action mask as bytes (one u8 per action).
    fn legal_mask<'py>(&self, py: Python<'py>, p: usize) -> PyResult<Bound<'py, PyBytes>> {
        check_seat(&self.g, p)?;
        Ok(mask_bytes(py, &self.g.legal_mask(p)))
    }
    /// Apply a flat action index; raises ValueError if illegal.
    fn step(&mut self, py: Python<'_>, p: usize, action: usize) -> PyResult<()> {
        check_seat(&self.g, p)?;
        py.detach(|| self.g.apply_index(p, action))
            .map_err(PyValueError::new_err)
    }
    /// (float32 features bytes, int32 card-index bytes) of seat `p`: what that player sees.
    fn observe<'py>(&self, py: Python<'py>, p: usize) -> PyResult<ObsBytes<'py>> {
        check_seat(&self.g, p)?;
        Ok(obs_bytes(py, &hsbg_engine::obs::observe(&self.g, p)))
    }
    /// The scripted bot's choice for seat `p` (the game's random stream is not moved).
    fn bot_action(&mut self, p: usize) -> PyResult<usize> {
        check_seat(&self.g, p)?;
        let rng = self.g.rng.clone();
        let a = bot::choose_action(&mut self.g, p).encode();
        self.g.rng = rng;
        Ok(a)
    }
    /// Let the scripted bot play seat `p` until it stops needing to act.
    fn bot_play(&mut self, py: Python<'_>, p: usize) -> PyResult<()> {
        check_seat(&self.g, p)?;
        py.detach(|| bot::play_turn(&mut self.g, p));
        Ok(())
    }
    fn placements(&self) -> Vec<u8> {
        self.g.players.iter().map(|p| p.placement).collect()
    }
    /// Combats of this game cut short by a simulator guard (they end as ties).
    #[getter]
    fn truncated_combats(&self) -> u32 {
        self.g.truncated_combats
    }
    /// Whether the game was ended by the `max_turns` guard instead of by the rules.
    #[getter]
    fn turn_limit_end(&self) -> bool {
        self.g.turn_limit_end
    }
    fn health(&self) -> Vec<i32> {
        self.g.players.iter().map(|p| p.health).collect()
    }
    /// The complete state as JSON (exact: `from_json` continues the same game).
    fn state_json(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| serde_json::to_string(&self.g))
            .map_err(|e| PyValueError::new_err(e.to_string()))
    }
    #[staticmethod]
    fn from_json(py: Python<'_>, s: &str) -> PyResult<Self> {
        let g: Game = py
            .detach(|| serde_json::from_str(s))
            .map_err(|e: serde_json::Error| PyValueError::new_err(e.to_string()))?;
        // A state written with another card table or an impossible configuration is
        // refused here instead of failing at the first step.
        g.check_loaded().map_err(PyValueError::new_err)?;
        Ok(PyGame { g })
    }
    fn log(&self) -> Vec<String> {
        self.g.log.clone()
    }
    /// Independent deep copy (for search / rollouts).
    fn copy(&self, py: Python<'_>) -> Self {
        py.detach(|| self.clone())
    }
    /// Human-readable JSON view of seat `p` (`hsbg_engine::debug::view`).
    fn view(&self, py: Python<'_>, p: usize) -> PyResult<String> {
        check_seat(&self.g, p)?;
        Ok(py.detach(|| hsbg_engine::debug::view(&self.g, p).to_string()))
    }
    /// Run a debug command given as JSON (`{"cmd": "set_player", ...}`); returns JSON.
    fn debug(&mut self, py: Python<'_>, cmd_json: &str) -> PyResult<String> {
        let cmd: hsbg_engine::debug::DebugCmd = serde_json::from_str(cmd_json)
            .map_err(|e| PyValueError::new_err(format!("bad command: {e}")))?;
        // A combat preview runs thousands of combats: not under the interpreter lock.
        py.detach(|| hsbg_engine::debug::run_debug(&mut self.g, cmd).map(|v| v.to_string()))
            .map_err(PyValueError::new_err)
    }
    /// Toggle the event log / combat replay recording.
    fn set_record_log(&mut self, on: bool) {
        self.g.cfg.record_log = on;
    }
}

/// One learning seat against scripted bots.
#[pyclass(name = "SoloEnv")]
struct PySoloEnv {
    env: SoloEnv,
}

#[pymethods]
impl PySoloEnv {
    #[new]
    #[pyo3(signature = (seed, config_json=None, agent=0))]
    fn new(seed: u64, config_json: Option<&str>, agent: usize) -> PyResult<Self> {
        let cfg = parse_config(config_json)?;
        if agent >= cfg.num_players {
            return Err(PyValueError::new_err(format!(
                "agent seat {agent} out of range (0..{})",
                cfg.num_players
            )));
        }
        Ok(PySoloEnv {
            env: SoloEnv::new(seed, cfg, agent),
        })
    }
    fn reset(&mut self, py: Python<'_>, seed: u64) {
        py.detach(|| self.env.reset(seed));
    }
    /// Returns (reward, done, illegal_message_or_None).
    fn step(&mut self, py: Python<'_>, action: usize) -> (f32, bool, Option<&'static str>) {
        let r = py.detach(|| self.env.step(action));
        (r.reward, r.done, r.illegal)
    }
    fn observe<'py>(&self, py: Python<'py>) -> ObsBytes<'py> {
        obs_bytes(py, &self.env.observe())
    }
    fn legal_mask<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        mask_bytes(py, &self.env.legal_mask())
    }
    fn done(&self) -> bool {
        self.env.done()
    }
    #[getter]
    fn placement(&self) -> u8 {
        self.env.placement()
    }
    #[getter]
    fn turn(&self) -> u32 {
        self.env.game.turn
    }
    fn state_json(&self) -> PyResult<String> {
        serde_json::to_string(&self.env.game).map_err(|e| PyValueError::new_err(e.to_string()))
    }
}

type BatchObs<'py> = (
    Bound<'py, PyBytes>,
    Bound<'py, PyBytes>,
    Bound<'py, PyBytes>,
    Bound<'py, PyBytes>,
);

/// Many games stepped together (`hsbg_engine::batch`); see `hsbg-engine.BatchEnv`.
#[pyclass(name = "BatchEnv")]
struct PyBatchEnv {
    env: BatchEnv,
}

#[pymethods]
impl PyBatchEnv {
    #[new]
    #[pyo3(signature = (n_games, seed=0, controlled=vec![0], config_json=None, threads=1))]
    fn new(
        py: Python<'_>,
        n_games: usize,
        seed: u64,
        controlled: Vec<usize>,
        config_json: Option<&str>,
        threads: usize,
    ) -> PyResult<Self> {
        let cfg = parse_config(config_json)?;
        let env = py
            .detach(|| BatchEnv::new(n_games, seed, cfg, controlled, threads))
            .map_err(PyValueError::new_err)?;
        Ok(PyBatchEnv { env })
    }
    #[getter]
    fn n_games(&self) -> usize {
        self.env.n_games()
    }
    #[getter]
    fn n_slots(&self) -> usize {
        self.env.n_slots()
    }
    #[getter]
    fn controlled(&self) -> Vec<usize> {
        self.env.controlled().to_vec()
    }
    #[getter]
    fn illegal_penalty(&self) -> f32 {
        self.env.illegal_penalty
    }
    #[setter]
    fn set_illegal_penalty(&mut self, v: f32) {
        self.env.illegal_penalty = v;
    }
    /// (features f32, cards i32, masks u8, ready u8) as bytes, one row per slot.
    fn observe<'py>(&self, py: Python<'py>) -> PyResult<BatchObs<'py>> {
        let n = self.env.n_slots();
        let (mut f, mut c) = (vec![0f32; n * OBS_FLOATS], vec![0i32; n * OBS_CARDS]);
        let (mut m, mut r) = (vec![0u8; n * N_ACTIONS], vec![0u8; n]);
        let env = &self.env;
        py.detach(|| env.observe(&mut f, &mut c, &mut m, &mut r))
            .map_err(PyRuntimeError::new_err)?;
        Ok((
            f32_bytes(py, &f),
            i32_bytes(py, &c),
            PyBytes::new(py, &m),
            PyBytes::new(py, &r),
        ))
    }
    /// One action per slot as little-endian int64 bytes; returns (rewards f32, dones u8,
    /// placements u8, rejected u8) as bytes, one entry per slot.
    fn step<'py>(&mut self, py: Python<'py>, actions: &[u8]) -> PyResult<BatchObs<'py>> {
        let n = self.env.n_slots();
        if actions.len() != n * 8 {
            return Err(PyValueError::new_err(format!(
                "{} bytes of actions, expected {} (int64 per slot)",
                actions.len(),
                n * 8
            )));
        }
        let (chunks, _) = actions.as_chunks::<8>();
        let acts: Vec<i64> = chunks.iter().map(|b| i64::from_le_bytes(*b)).collect();
        let mut out = vec![SlotResult::default(); n];
        let env = &mut self.env;
        py.detach(|| env.step(&acts, &mut out))
            .map_err(PyValueError::new_err)?;
        let rewards: Vec<f32> = out.iter().map(|r| r.reward).collect();
        let dones: Vec<u8> = out.iter().map(|r| r.done as u8).collect();
        let places: Vec<u8> = out.iter().map(|r| r.placement).collect();
        let rejected: Vec<u8> = out.iter().map(|r| r.rejected as u8).collect();
        Ok((
            f32_bytes(py, &rewards),
            PyBytes::new(py, &dones),
            PyBytes::new(py, &places),
            PyBytes::new(py, &rejected),
        ))
    }
    /// 每个 slot 的当前回合数（u32，一行一个 slot）。
    fn turns(&self) -> Vec<u32> {
        self.env.turns()
    }

    /// Game `i` and its episode state as JSON (`load` restores it exactly).
    fn save(&self, py: Python<'_>, i: usize) -> PyResult<String> {
        py.detach(|| self.env.save(i))
            .map_err(PyValueError::new_err)
    }
    fn load(&mut self, py: Python<'_>, i: usize, json: &str) -> PyResult<()> {
        let env = &mut self.env;
        py.detach(|| env.load(i, json))
            .map_err(PyValueError::new_err)
    }
    /// The index of game `i`'s current episode (0 for the first).
    fn episode_index(&self, i: usize) -> PyResult<u64> {
        if i >= self.env.n_games() {
            return Err(PyValueError::new_err(format!("game {i} out of range")));
        }
        Ok(self.env.episode(i).index)
    }
    /// Game `i` as a `Game` (an independent copy).
    fn game(&self, i: usize) -> PyResult<PyGame> {
        if i >= self.env.n_games() {
            return Err(PyValueError::new_err(format!("game {i} out of range")));
        }
        Ok(PyGame {
            g: self.env.game(i).clone(),
        })
    }
}

#[pyfunction]
fn catalog_json() -> String {
    hsbg_engine::debug::catalog().to_string()
}

#[pyfunction]
fn version() -> &'static str {
    hsbg_engine::VERSION
}

#[pyfunction]
fn game_version() -> &'static str {
    // fork: 由数据 meta 驱动（36.6.3 -> 37.0.0 只换数据文件即可）；API 与上游一致。
    hsbg_engine::game_version()
}

#[pyfunction]
fn server_rules_version() -> &'static str {
    hsbg_engine::server_rules_version()
}

/// What this binary was built from: `(source hash, build profile)`. The source hash is the
/// fingerprint of the engine and binding sources (see `build.rs`); `hsbg_engine.source_hash()`
/// computes the same from a checkout.
#[pyfunction]
fn build_info() -> (&'static str, &'static str) {
    (env!("HSBG_ENGINE_SOURCE_HASH"), env!("HSBG_ENGINE_PROFILE"))
}

/// fork: 卡表概况（一次调用即可核对数据替换是否生效），不改变上游公开 API：
/// `(card_count, client_version, server_patch)`。`card_count` 不含 N_CARDS 的空位。
#[pyfunction]
fn db_info() -> (usize, &'static str, &'static str) {
    let d = db();
    (
        d.len(),
        hsbg_engine::game_version(),
        hsbg_engine::server_rules_version(),
    )
}

/// Human-readable name of a flat action index.
#[pyfunction]
fn action_name(a: usize) -> PyResult<String> {
    Action::decode(a)
        .map(|x| format!("{x:?}"))
        .ok_or_else(|| PyValueError::new_err("bad action index"))
}

/// Card metadata by embedding index (CardId + 1; 0 = empty): (id, enUS name, zhCN name, tier).
#[pyfunction]
fn card_info(index: usize) -> PyResult<(String, String, String, u8)> {
    if index == 0 || index > db().len() {
        return Err(PyValueError::new_err("bad card index"));
    }
    let c = db().get(hsbg_engine::cards::CardId((index - 1) as u16));
    Ok((c.id.clone(), c.name.clone(), c.name_zh.clone(), c.tier))
}

/// Play `n` full bot games with the GIL released; returns each game's final turn.
#[pyfunction]
#[pyo3(signature = (n, seed=0, config_json=None))]
fn run_bot_games(
    py: Python<'_>,
    n: u64,
    seed: u64,
    config_json: Option<&str>,
) -> PyResult<Vec<u32>> {
    let cfg = parse_config(config_json)?;
    let result: Result<Vec<u32>, String> = py.detach(|| {
        (0..n)
            .map(|i| {
                let g = bot::run_bot_game(seed.wrapping_add(i), cfg.clone());
                if let Some(reason) = g.stopped_reason {
                    Err(format!(
                        "simulation stopped ({}), seed {}, turn {}",
                        reason.as_str(),
                        g.seed,
                        g.turn
                    ))
                } else {
                    Ok(g.turn)
                }
            })
            .collect()
    });
    result.map_err(PyRuntimeError::new_err)
}

/// Sizes that define the observation layout (`hsbg_engine::obs`) and the action layout
/// (`hsbg_engine::actions`), so Python code can slice observations without copying numbers.
#[pyfunction]
fn layout() -> Vec<(&'static str, usize)> {
    use hsbg_engine::actions as a;
    use hsbg_engine::obs as o;
    vec![
        ("MINION_F", o::MINION_F),
        ("ITEM_F", o::ITEM_F),
        ("GLOBAL_F", o::GLOBAL_F),
        ("N_QUESTS", o::N_QUESTS),
        ("QUEST_F", o::QUEST_F),
        ("N_SECRETS", o::N_SECRETS),
        ("OPP_F", o::OPP_F),
        ("N_OPP", o::N_OPP),
        ("PENDING_KINDS", o::PENDING_KINDS),
        ("N_SHOP", a::N_SHOP),
        ("N_BOARD", a::N_BOARD),
        ("N_HAND", a::N_HAND),
        ("N_CHOICE", a::N_CHOICE),
        ("N_POS", a::N_POS),
        ("N_POWERS", a::N_POWERS),
        ("A_END", a::A_END),
        ("A_REFRESH", a::A_REFRESH),
        ("A_FREEZE", a::A_FREEZE),
        ("A_UPGRADE", a::A_UPGRADE),
        ("A_HERO_POWER", a::A_HERO_POWER),
        ("A_DARK_GIFT", a::A_DARK_GIFT),
        ("A_CANCEL", a::A_CANCEL),
        ("A_BUY", a::A_BUY),
        ("A_SELL", a::A_SELL),
        ("A_ACTIVATE", a::A_ACTIVATE),
        ("A_CHOOSE", a::A_CHOOSE),
        ("A_PLAY", a::A_PLAY),
        ("A_MAGNETIZE", a::A_MAGNETIZE),
        ("A_MOVE", a::A_MOVE),
        ("N_ACTIONS", a::N_ACTIONS),
        ("OBS_FLOATS", o::OBS_FLOATS),
        ("OBS_CARDS", o::OBS_CARDS),
    ]
}

/// Static numeric features of every card, row = embedding index (row 0 = empty slot):
/// (number of columns, little-endian f32 bytes). Columns: 10 card-kind flags, tier, attack,
/// health, cost, armor, 11 type bits, 11 hero-association type bits, 12 keyword bits,
/// 11 mechanic bits, Golden, in the minion / hero / spell / trinket pool, quest goal.
#[pyfunction]
fn card_static<'py>(py: Python<'py>) -> (usize, Bound<'py, PyBytes>) {
    use hsbg_engine::cards::CardKind as K;
    const F: usize = 10 + 5 + 11 + 11 + 12 + 11 + 1 + 4 + 1;
    let d = db();
    let mut out: Vec<f32> = vec![0.0; (d.len() + 1) * F];
    for c in d.iter() {
        let row = &mut out[(c.cid.idx() + 1) * F..(c.cid.idx() + 2) * F];
        let kind = match c.kind {
            K::Minion => 0,
            K::TavernSpell => 1,
            K::Spell => 2,
            K::Hero => 3,
            K::HeroPower => 4,
            K::TrinketLesser => 5,
            K::TrinketGreater => 6,
            K::DarkGift => 7,
            K::Quest => 8,
            K::QuestReward => 9,
        };
        row[kind] = 1.0;
        let mut i = 10;
        for v in [c.tier as i32, c.atk, c.hp, c.cost, c.armor] {
            row[i] = v as f32;
            i += 1;
        }
        for bits in [
            (c.races.0 as u32, 11),
            (c.assoc.0 as u32, 11),
            (c.kw.0, 12),
            (c.mech.0, 11),
        ] {
            for k in 0..bits.1 {
                row[i] = (bits.0 >> k & 1) as f32;
                i += 1;
            }
        }
        for flag in [
            c.is_golden(),
            c.pools.minion,
            c.pools.hero,
            c.pools.spell,
            c.pools.trinket,
        ] {
            row[i] = flag as u8 as f32;
            i += 1;
        }
        row[i] = c.quest_goal as f32;
        debug_assert_eq!(i + 1, F);
    }
    (F, f32_bytes(py, &out))
}

#[pyfunction]
fn default_config_json() -> String {
    serde_json::to_string_pretty(&RulesConfig::default()).unwrap()
}

/// P4-M1：逐步 MCTS 搜索（Rust 核，PUCT）。
///
/// `eval_fn(features_bytes, cards_bytes, mask_bytes, seat) -> (policy_bytes, value)`：
/// - `features_bytes` = `observe(seat)` 的 f32[3227] 小端字节；`cards_bytes` = i32[124]；
/// - `mask_bytes` = u8[245] 合法动作 mask；
/// - `policy_bytes` = f32[245] 先验（Rust 侧会按 mask 兜底清零/归一化）；
/// - `value` = seat 视角期望 utility（终局名次口径）。
///
/// 返回 `(pi_bytes f32[245], action: int, root_value: float, visits: int)`。
/// `eval_fn=None` 时使用 uniform prior + value=0（fallback，便于无 NN 冒烟）。
/// `rollout=True`（P4-B 纯搜索模式）：叶节点**不调用** `eval_fn`（可传 None），先验=合法
/// 动作均匀，价值=用内置 bot 打到终局的 placement utility；适合无 NN 的搜索能力测试。
/// 注意：搜索期间持有 GIL（回调是 Python/NN 推理）；批量评估/异步待 P4 后续。
#[pyfunction]
#[pyo3(signature = (game, seat, simulations=8, c_puct=1.5, temperature=1.0, eval_fn=None,
                    seed=0, dirichlet_alpha=0.3, dirichlet_epsilon=0.25, rollout=false))]
fn mcts_search<'py>(
    py: Python<'py>,
    game: &PyGame,
    seat: usize,
    simulations: u32,
    c_puct: f32,
    temperature: f32,
    eval_fn: Option<Py<PyAny>>,
    seed: u64,
    dirichlet_alpha: f32,
    dirichlet_epsilon: f32,
    rollout: bool,
) -> PyResult<(Bound<'py, PyBytes>, u16, f32, u32)> {
    let start = game.g.clone();
    if seat >= start.players.len() {
        return Err(PyValueError::new_err(format!(
            "seat {seat} out of range (0..{})",
            start.players.len()
        )));
    }
    let cfg = SearchConfig {
        simulations,
        c_puct,
        temperature,
        dirichlet_alpha,
        dirichlet_epsilon,
        seed,
        rollout,
    };
    // rollout 模式且无 eval 回调：搜索全程不需要 GIL → 释放 GIL，便于多进程/多线程并行。
    if rollout && eval_fn.is_none() {
        let result = py.detach(|| {
            rust_search(&start, seat, &cfg, |_g: &Game, _s: usize| {
                (vec![1.0; N_ACTIONS], 0.0)
            })
        });
        let pi_bytes: Vec<u8> = result.pi.iter().flat_map(|x| x.to_le_bytes()).collect();
        return Ok((
            PyBytes::new(py, &pi_bytes),
            result.action,
            result.root_value,
            result.visits,
        ));
    }
    // 回调异常：先记下，搜索结束后转成 Python 异常（search 的签名不收 Result）。
    let err: std::cell::RefCell<Option<PyErr>> = std::cell::RefCell::new(None);
    let result = rust_search(&start, seat, &cfg, |g: &Game, s: usize| {
        if err.borrow().is_some() {
            return (vec![1.0; N_ACTIONS], 0.0);
        }
        let Some(cb) = &eval_fn else {
            return (vec![1.0; N_ACTIONS], 0.0);
        };
        match call_eval_fn(py, cb, g, s) {
            Ok(x) => x,
            Err(e) => {
                *err.borrow_mut() = Some(e);
                (vec![1.0; N_ACTIONS], 0.0)
            }
        }
    });
    if let Some(e) = err.into_inner() {
        return Err(e);
    }
    let pi_bytes: Vec<u8> = result.pi.iter().flat_map(|x| x.to_le_bytes()).collect();
    Ok((
        PyBytes::new(py, &pi_bytes),
        result.action,
        result.root_value,
        result.visits,
    ))
}

/// 调用 Python eval 回调：传观测/mask 字节，解析 policy bytes + value。
fn call_eval_fn(
    py: Python<'_>,
    cb: &Py<PyAny>,
    g: &Game,
    seat: usize,
) -> PyResult<(Vec<f32>, f32)> {
    let obs = hsbg_engine::obs::observe(g, seat);
    let features: Vec<u8> = obs.floats.iter().flat_map(|x| x.to_le_bytes()).collect();
    let cards: Vec<u8> = obs.cards.iter().flat_map(|x| x.to_le_bytes()).collect();
    let mask: Vec<u8> = g.legal_mask(seat).iter().map(|b| *b as u8).collect();
    let out = cb.call1(
        py,
        (
            PyBytes::new(py, &features),
            PyBytes::new(py, &cards),
            PyBytes::new(py, &mask),
            seat,
        ),
    )?;
    let out = out.bind(py);
    let (policy, value): (Bound<'_, PyBytes>, f32) = out.extract()?;
    let raw = policy.as_bytes();
    if raw.len() != N_ACTIONS * 4 {
        return Err(PyValueError::new_err(format!(
            "policy bytes must be f32[{}] ({} bytes), got {}",
            N_ACTIONS,
            N_ACTIONS * 4,
            raw.len()
        )));
    }
    let prior: Vec<f32> = raw
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect();
    Ok((prior, value))
}

/// 回合内 TurnSearch（Rust 版）：当前回合状态枚举 + pairwise 战斗，不做完整 bot rollout。
#[pyfunction]
#[pyo3(signature = (game, seat, states_budget=24, samples_per_action=1, combat_samples=1,
                    max_steps_per_turn=40, seed=0, aggregate="max"))]
fn turn_search<'py>(
    py: Python<'py>,
    game: &PyGame,
    seat: usize,
    states_budget: usize,
    samples_per_action: usize,
    combat_samples: usize,
    max_steps_per_turn: usize,
    seed: u64,
    aggregate: &str,
) -> PyResult<(Bound<'py, PyBytes>, u16, f32, u32, u32)> {
    if seat >= game.g.players.len() {
        return Err(PyValueError::new_err(format!(
            "seat {seat} out of range (0..{})",
            game.g.players.len()
        )));
    }
    let agg = match aggregate.to_ascii_lowercase().as_str() {
        "max" => ActionAggregate::Max,
        "mean" => ActionAggregate::Mean,
        other => {
            return Err(PyValueError::new_err(format!(
                "aggregate must be max/mean, got {other}"
            )));
        }
    };
    let cfg = TurnSearchConfig {
        states_budget,
        samples_per_action,
        combat_samples,
        max_steps_per_turn,
        seed,
        aggregate: agg,
    };
    let start = game.g.clone();
    let result = py.detach(|| rust_turn_search(&start, seat, cfg));
    let scores: Vec<u8> = result
        .action_scores
        .iter()
        .flat_map(|x| x.to_le_bytes())
        .collect();
    Ok((
        PyBytes::new(py, &scores),
        result.action,
        result.best_score,
        result.n_states as u32,
        result.n_combats as u32,
    ))
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("N_ACTIONS", N_ACTIONS)?;
    m.add("OBS_FLOATS", OBS_FLOATS)?;
    m.add("OBS_CARDS", OBS_CARDS)?;
    m.add("N_CARDS", db().len() + 1)?;
    m.add_class::<PyGame>()?;
    m.add_class::<PySoloEnv>()?;
    m.add_class::<PyBatchEnv>()?;
    m.add_class::<collector::PyRustCollector>()?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(game_version, m)?)?;
    m.add_function(wrap_pyfunction!(server_rules_version, m)?)?;
    m.add_function(wrap_pyfunction!(db_info, m)?)?;
    m.add_function(wrap_pyfunction!(build_info, m)?)?;
    m.add_function(wrap_pyfunction!(action_name, m)?)?;
    m.add_function(wrap_pyfunction!(card_info, m)?)?;
    m.add_function(wrap_pyfunction!(run_bot_games, m)?)?;
    m.add_function(wrap_pyfunction!(default_config_json, m)?)?;
    m.add_function(wrap_pyfunction!(layout, m)?)?;
    m.add_function(wrap_pyfunction!(card_static, m)?)?;
    m.add_function(wrap_pyfunction!(catalog_json, m)?)?;
    m.add_function(wrap_pyfunction!(mcts_search, m)?)?;
    m.add_function(wrap_pyfunction!(turn_search, m)?)?;
    Ok(())
}
