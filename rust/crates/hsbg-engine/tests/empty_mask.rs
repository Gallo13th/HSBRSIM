//! 回归测试：付费饰品单在金币花掉后变贵 → 该座没有任何合法动作（整局卡死）。
//!
//! 现场来自训练采集（`mask 全 False` 崩溃）：玩家 pending 里有一张 `free: false` 的饰品单，
//! 四个选项价格都高于当前金币，`cancellable()` 又是 false，于是 `legal_mask` 全 false。
//! 修复后必须至少给出一个 `A_CANCEL`（放弃该单），且 `apply` 能成功推进。

use hsbg_engine::actions::{A_CANCEL, N_ACTIONS};
use hsbg_engine::engine::Game;

const FIXTURE: &str = include_str!("fixtures/empty_mask_trinket.json");

#[test]
fn unaffordable_pending_trinket_has_cancel_escape() {
    let mut g: Game = serde_json::from_str(FIXTURE).expect("fixture 应能恢复");
    let seat = 0usize;
    assert!(g.needs_action(seat), "该座位确实需要动作");
    let mask = g.legal_mask(seat);
    assert_eq!(mask.len(), N_ACTIONS);
    assert!(mask[A_CANCEL], "买不起的饰品单必须给出 A_CANCEL 逃生口");
    assert!(mask.iter().any(|v| *v), "mask 不能全 False");
    // 放弃该单后应能继续（下一步仍然有合法动作或该座已不需要动作）
    let r = g.apply_index(seat, A_CANCEL);
    assert!(r.is_ok(), "apply(A_CANCEL) 应成功: {r:?}");
    if g.needs_action(seat) {
        assert!(g.legal_mask(seat).iter().any(|v| *v), "放弃后仍必须有合法动作");
    }
}
