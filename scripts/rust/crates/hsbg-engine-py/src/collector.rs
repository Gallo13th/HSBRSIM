//! Rust 全采集器（spike）：N 局同步推进 + 记录 SoA 打包全在 Rust。
//!
//! Python 侧只剩「批量 NN 前向 + 采样」：每次 `pending()` 取待决策行，回传
//! `record_actions(actions, logprobs, values)`，Rust 完成回合守卫、记录写入、
//! 引擎 step、对手 bot 推进、名次回填。`finish()` 一次性返回 SoA 记录数组。
//!
//! 语义与 Python `collect_ppo_lockstep` 对齐：
//! - 学习座位每回合决策数守卫（`limit`）：超限且 EndTurn 合法 → action=0/logprob=0/forced=1；
//! - 每局一条 episode，结束后自动开新局（BatchEnv 行为），本采集器在「该局结束后」
//!   不再记录该局（只统计一次名次）；
//! - 未结束（guard 截断）的局 rank=-1，与 Python 路径一致（下游按 rank>=1 过滤）。

use std::collections::HashMap;

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

use hsbg_engine::batch::BatchEnv;
use hsbg_engine::config::RulesConfig;

use crate::{f32_bytes, i32_bytes, parse_config, N_ACTIONS, OBS_CARDS, OBS_FLOATS};

/// Rust 全采集器。
#[pyclass(name = "RustCollector")]
pub struct PyRustCollector {
    env: BatchEnv,
    n_slots: usize,
    seat: usize,
    limit: u32,
    cap: usize,
    cnt: usize,
    // SoA 记录缓冲
    feats: Vec<f32>,
    cards: Vec<i32>,
    masks: Vec<u8>,
    acts: Vec<i64>,
    logps: Vec<f32>,
    vals: Vec<f32>,
    ranks: Vec<i64>,
    seats: Vec<i32>,
    gids: Vec<i64>,
    turns: Vec<i32>,
    forced: Vec<u8>,
    // 回合守卫 / 名次回填 / 完成状态
    turn_counts: HashMap<(i64, i64), u32>,
    first: Vec<i64>,
    last: Vec<i64>,
    finished: Vec<bool>,
    placements: Vec<i64>,
    // 本轮待决策槽位
    pending_slots: Vec<usize>,
    pending_turns: Vec<u32>,
    pending_masks: Vec<u8>,
    pending_feats: Vec<f32>,
    pending_cards: Vec<i32>,
    rounds: u64,
    illegal: u64,
    max_steps: usize,
    steps: Vec<usize>,
}

impl PyRustCollector {
    fn push_row(&mut self, slot: usize, turn: u32, features: &[f32], cards: &[i32],
                mask: &[u8], action: i64, logp: f32, value: f32, forced: bool) {
        if self.cnt >= self.cap {
            self.grow();
        }
        let i = self.cnt;
        let base_f = i * OBS_FLOATS;
        self.feats[base_f..base_f + OBS_FLOATS].copy_from_slice(features);
        let base_c = i * OBS_CARDS;
        self.cards[base_c..base_c + OBS_CARDS].copy_from_slice(cards);
        let base_m = i * N_ACTIONS;
        self.masks[base_m..base_m + N_ACTIONS].copy_from_slice(mask);
        self.acts[i] = action;
        self.logps[i] = logp;
        self.vals[i] = value;
        self.ranks[i] = -1;
        self.seats[i] = self.seat as i32;
        self.gids[i] = slot as i64;
        self.turns[i] = turn as i32;
        self.forced[i] = forced as u8;
        if self.first[slot] < 0 {
            self.first[slot] = i as i64;
        }
        self.last[slot] = i as i64;
        self.cnt += 1;
    }

    fn grow(&mut self) {
        let cap = self.cap * 2;
        self.feats.resize(cap * OBS_FLOATS, 0.0);
        self.cards.resize(cap * OBS_CARDS, 0);
        self.masks.resize(cap * N_ACTIONS, 0);
        self.acts.resize(cap, 0);
        self.logps.resize(cap, 0.0);
        self.vals.resize(cap, 0.0);
        self.ranks.resize(cap, -1);
        self.seats.resize(cap, 0);
        self.gids.resize(cap, 0);
        self.turns.resize(cap, 0);
        self.forced.resize(cap, 0);
        self.cap = cap;
    }
}

#[pymethods]
impl PyRustCollector {
    #[new]
    #[pyo3(signature = (n_games, seed=0, seat=0, limit=40, max_steps=20000,
                        threads=1, config_json=None))]
    fn new(n_games: usize, seed: u64, seat: usize, limit: u32, max_steps: usize,
           threads: usize, config_json: Option<&str>) -> PyResult<Self> {
        let cfg: RulesConfig = parse_config(config_json)?;
        let env = BatchEnv::new(n_games, seed, cfg, vec![seat], threads)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        // 预分配按「每局 ~160 决策」估；不足时 grow()，避免一开始就 memset 几个 GB
        let cap = n_games * 192;
        Ok(PyRustCollector {
            env, n_slots: n_games, seat, limit, cap, cnt: 0,
            feats: vec![0.0; cap * OBS_FLOATS],
            cards: vec![0; cap * OBS_CARDS],
            masks: vec![0; cap * N_ACTIONS],
            acts: vec![0; cap],
            logps: vec![0.0; cap],
            vals: vec![0.0; cap],
            ranks: vec![-1; cap],
            seats: vec![seat as i32; cap],
            gids: vec![0; cap],
            turns: vec![0; cap],
            forced: vec![0; cap],
            turn_counts: HashMap::new(),
            first: vec![-1; n_games],
            last: vec![-1; n_games],
            finished: vec![false; n_games],
            placements: vec![0; n_games],
            pending_slots: Vec::new(),
            pending_turns: Vec::new(),
            pending_masks: Vec::new(),
            pending_feats: Vec::new(),
            pending_cards: Vec::new(),
            rounds: 0,
            illegal: 0,
            max_steps,
            steps: vec![0; n_games],
        })
    }

    /// 取本轮到期的待决策行：(features f32, cards i32, masks u8, turns u32, slots i64)。
    /// 没有待决策行时返回空 bytes。
    fn pending<'py>(&mut self, py: Python<'py>) -> PyResult<(
        Bound<'py, PyBytes>, Bound<'py, PyBytes>, Bound<'py, PyBytes>,
        Bound<'py, PyBytes>, Bound<'py, PyBytes>)> {
        let n = self.n_slots;
        let (mut f, mut c) = (vec![0f32; n * OBS_FLOATS], vec![0i32; n * OBS_CARDS]);
        let (mut m, mut r) = (vec![0u8; n * N_ACTIONS], vec![0u8; n]);
        self.env.observe(&mut f, &mut c, &mut m, &mut r)
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        let turns = self.env.turns();
        self.pending_slots.clear();
        self.pending_turns.clear();
        for slot in 0..n {
            if r[slot] != 0 && !self.finished[slot] {
                self.pending_slots.push(slot);
                self.pending_turns.push(turns[slot]);
            }
        }
        let k = self.pending_slots.len();
        let mut fo = vec![0f32; k * OBS_FLOATS];
        let mut co = vec![0i32; k * OBS_CARDS];
        let mut mo = vec![0u8; k * N_ACTIONS];
        let mut to = vec![0u32; k];
        let mut so = vec![0i64; k];
        for (j, &slot) in self.pending_slots.iter().enumerate() {
            fo[j * OBS_FLOATS..(j + 1) * OBS_FLOATS]
                .copy_from_slice(&f[slot * OBS_FLOATS..(slot + 1) * OBS_FLOATS]);
            co[j * OBS_CARDS..(j + 1) * OBS_CARDS]
                .copy_from_slice(&c[slot * OBS_CARDS..(slot + 1) * OBS_CARDS]);
            mo[j * N_ACTIONS..(j + 1) * N_ACTIONS]
                .copy_from_slice(&m[slot * N_ACTIONS..(slot + 1) * N_ACTIONS]);
            to[j] = turns[slot];
            so[j] = slot as i64;
        }
        self.pending_masks = mo.clone();
        self.pending_feats = fo.clone();
        self.pending_cards = co.clone();
        Ok((f32_bytes(py, &fo), i32_bytes(py, &co), PyBytes::new(py, &mo),
            PyBytes::new(py, &u32_bytes(&to)), PyBytes::new(py, &i64_bytes(&so))))
    }

    /// 回传本批动作（int64/行）、logprob（f32/行）、value（f32/行）；
    /// 内部完成守卫 + 记录 + step + 名次回填。返回 (rewards, dones, placements, rejected)。
    fn record_actions<'py>(&mut self, py: Python<'py>, actions: &[u8], logprobs: &[u8],
                           values: &[u8]) -> PyResult<(
        Bound<'py, PyBytes>, Bound<'py, PyBytes>, Bound<'py, PyBytes>,
        Bound<'py, PyBytes>)> {
        let k = self.pending_slots.len();
        if actions.len() != k * 8 || logprobs.len() != k * 4 || values.len() != k * 4 {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "expect {k} rows: actions {}B, logprobs {}B, values {}B",
                actions.len(), logprobs.len(), values.len())));
        }
        if self.pending_slots.is_empty() {
            return Ok((f32_bytes(py, &Vec::<f32>::new()), PyBytes::new(py, &[]),
                       PyBytes::new(py, &[]), PyBytes::new(py, &[])));
        }
        let mut step_actions = vec![0i64; self.n_slots];
        let slots = std::mem::take(&mut self.pending_slots);
        let turns = std::mem::take(&mut self.pending_turns);
        let masks = std::mem::take(&mut self.pending_masks);
        let feats = std::mem::take(&mut self.pending_feats);
        let cards = std::mem::take(&mut self.pending_cards);
        for (j, &slot) in slots.iter().enumerate() {
            let a = i64::from_le_bytes(actions[j * 8..(j + 1) * 8].try_into().unwrap());
            let logp = f32::from_le_bytes(logprobs[j * 4..(j + 1) * 4].try_into().unwrap());
            let val = f32::from_le_bytes(values[j * 4..(j + 1) * 4].try_into().unwrap());
            let turn = turns[j];
            let gid = slot as i64;
            let key = (gid, turn as i64);
            let n_turn = self.turn_counts.entry(key).or_insert(0);
            *n_turn += 1;
            let limit = self.limit;
            let mut action = a;
            let mut logprob = logp;
            let mut forced = false;
            if limit > 0 && *n_turn > limit {
                let base = j * N_ACTIONS;
                if masks[base] != 0 {
                    forced = true;
                    action = 0;
                    logprob = 0.0;
                }
            }
            let row = j * N_ACTIONS;
            let legal = action >= 0 && (action as usize) < N_ACTIONS
                && masks[row + action as usize] != 0;
            if !legal {
                self.illegal += 1;
                action = (0..N_ACTIONS).find(|&a| masks[row + a] != 0)
                    .map(|a| a as i64).unwrap_or(0);
                logprob = 0.0;
                forced = true;   // 兜底动作不是策略采样：只参与 value，避免伪造 on-policy ratio
            }
            step_actions[slot] = action;
            self.steps[slot] += 1;
            self.push_row(slot, turn, &feats[j * OBS_FLOATS..(j + 1) * OBS_FLOATS],
                          &cards[j * OBS_CARDS..(j + 1) * OBS_CARDS],
                          &masks[row..row + N_ACTIONS],
                          action, logprob, val, forced);
        }
        let mut out = vec![hsbg_engine::batch::SlotResult::default(); self.n_slots];
        self.env.step(&step_actions, &mut out)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        self.rounds += 1;
        let rewards: Vec<f32> = out.iter().map(|x| x.reward).collect();
        let dones: Vec<u8> = out.iter().map(|x| x.done as u8).collect();
        let places: Vec<u8> = out.iter().map(|x| x.placement).collect();
        let rejected: Vec<u8> = out.iter().map(|x| x.rejected as u8).collect();
        for slot in 0..self.n_slots {
            // max_steps 截断：与 Python 路径一致，超限的局不再继续（rank 保持 -1 → 下游丢弃）
            if !self.finished[slot] && self.max_steps > 0 && self.steps[slot] >= self.max_steps {
                self.finished[slot] = true;
                continue;
            }
            if dones[slot] != 0 && !self.finished[slot] {
                self.finished[slot] = true;
                self.placements[slot] = places[slot] as i64;
                // 记录是按轮交错写入的，first..last 区间里混着其他局的记录：
                // 只给本局（gids == slot）的行回填名次，避免污染其他局甚至未结束的局
                let (a, b) = (self.first[slot], self.last[slot]);
                if a >= 0 && b >= a {
                    for i in a as usize..=b as usize {
                        if self.gids[i] == slot as i64 {
                            self.ranks[i] = places[slot] as i64;
                        }
                    }
                }
            }
        }
        Ok((f32_bytes(py, &rewards), PyBytes::new(py, &dones),
            PyBytes::new(py, &places), PyBytes::new(py, &rejected)))
    }

    /// 是否所有 slot 都结束（应停止采集）。
    fn all_finished(&self) -> bool {
        self.finished.iter().all(|&x| x)
    }

    fn rounds(&self) -> u64 { self.rounds }
    fn decisions(&self) -> usize { self.cnt }
    fn illegal(&self) -> u64 { self.illegal }

    /// 一次性取出 SoA 记录（只含 rank 已验证的行；调用方按需过滤）。
    fn finish<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let n = self.cnt;
        let d = PyDict::new(py);
        d.set_item("features", f32_bytes(py, &self.feats[..n * OBS_FLOATS]))?;
        d.set_item("cards", i32_bytes(py, &self.cards[..n * OBS_CARDS]))?;
        d.set_item("masks", PyBytes::new(py, &self.masks[..n * N_ACTIONS]))?;
        d.set_item("actions", PyBytes::new(py, &i64_bytes(&self.acts[..n])))?;
        d.set_item("old_logprobs", f32_bytes(py, &self.logps[..n]))?;
        d.set_item("values", f32_bytes(py, &self.vals[..n]))?;
        d.set_item("ranks", PyBytes::new(py, &i64_bytes(&self.ranks[..n])))?;
        d.set_item("seats", i32_bytes(py, &self.seats[..n]))?;
        d.set_item("game_ids", PyBytes::new(py, &i64_bytes(&self.gids[..n])))?;
        d.set_item("turns", PyBytes::new(py, &i32_le_bytes(&self.turns[..n])))?;
        d.set_item("forced", PyBytes::new(py, &self.forced[..n]))?;
        d.set_item("count", n)?;
        d.set_item("rounds", self.rounds)?;
        d.set_item("illegal", self.illegal)?;
        Ok(d)
    }
}

fn u32_bytes(v: &[u32]) -> Vec<u8> {
    v.iter().flat_map(|x| x.to_le_bytes()).collect()
}
fn i64_bytes(v: &[i64]) -> Vec<u8> {
    v.iter().flat_map(|x| x.to_le_bytes()).collect()
}
fn i32_le_bytes(v: &[i32]) -> Vec<u8> {
    v.iter().flat_map(|x| x.to_le_bytes()).collect()
}
