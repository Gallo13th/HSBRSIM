# 人类对战 UI 设计规格（审校版）

## 0. 范围、证据与状态定义
- 目标：支持连续手打几十局；仅设计，不改引擎、动作契约或训练代码。基线为 37.0.0.255790。
- 已核对：[现实现](<../scripts/human_arena.py>)、[使用说明](<HUMAN_ARENA.md>)、[动作](<../hsbg/env/action_space_std.py>)、[观测](<../hsbg/env/obs_std.py>)、[卡表](<../rust/crates/hsbg-engine/data/cards.json>)、[引擎视图](<../rust/crates/hsbg-engine/src/debug.rs>)及[编码](<../rust/crates/hsbg-engine/src/obs.rs>)。
- [主界面截图](<assets/human_arena_ui.png>)与[选择截图](<assets/human_arena_pending.png>)为视觉验收基线；本次模型不支持图像输入，未完成像素级审阅，不宣称已验证截图布局。
- 下文 O = 标准 obs；C = 同构建卡表；V = 现有 `Game.view(seat)`；A = `legal_mask` 与标准动作；U = UI 自身状态。每行的来源是实现依据。
- **现**：现有 `/state` 已有数据，补渲染即可；**接**：O/C/V 已有，补 Python 白名单字段即可，无需改引擎；**补**：现有公开接口不足，需引擎补充；**禁**：不得泄露或伪造。
- 审校纠正：当前实现并非完全没有对手、战斗、费用、种族、金卡或关键词字段；主要问题是展示不足及裁剪丢字段。`_card_brief` 的 `golden` 是实例布尔值，不能直接套用 C 的同名字符串。

## 1. 信息架构（桌面固定主战区，小屏纵向堆叠）
| 区块 / 优先级 | 必须展示的字段与行为 | 数据来源 / 状态 |
|---|---|---|
| 顶部 HUD / P0 | 英雄与技能摘要、当前生命与护甲分列、金币/上限、回合、阶段、剩余人数、本局种族；技能价格与可用性 | O `SLICE_GLOBAL`、`SLICE_CARD_HERO/POWERS`；V `me.health/armor/max_gold/hero_powers`；现 |
| 商店 / P0 | 8 槽稳定编号、完整卡片、实际购买价格与支付货币、冻结/保留标识、已有数量/三连条件 | O `SLICE_SHOP` + `SLICE_CARD_SHOP`；V `me.shop[].price/costs_health/owned/triple_need`；现 |
| 商店操作条 / P0 | 刷新费用/免费次数、冻结状态、当前星级→下一星级、升本费用、不可用提示 | O global `tier/upgrade_price/refresh_price/free_refreshes/frozen`；V `can_upgrade_tier`；A `[1..3]`；现/接 |
| 战场 / P0 | 7 槽、完整卡片、明确左右位置、出售/发动/移动、附件详情；Σ 显示为“Σ(攻击+当前生命)”而非胜率 | O `SLICE_BOARD` + `SLICE_CARD_BOARD`；V `me.board`；A；现/接 |
| 手牌 / P0 | 10 槽、完整卡片、锁定剩余回合/临时牌、打出位置、磁力目标；队列数量及详情另列 | O `SLICE_HAND` + `SLICE_CARD_HAND`、global `hand_queue_len`；V `me.hand/hand_queue/hand_limit`；现/接 |
| 饰品/持续效果栏 / P0 | 已有小/大饰品卡片、黑暗之赐状态及实际归属、宝石/法术等全局增益 | O `SLICE_CARD_TRINKETS`、global `gem_atk/gem_hp/spell_atk/spell_hp`；V `me.trinkets/effects/dark_gift`；接 |
| 选择面板 / P0 | Discover/英雄/饰品等类型、来源卡、选项效果、价格、目标位置、可取消提示；不遮挡自己的阵容 | O `SLICE_PENDING/CHOICES/CARD_CHOICES/CARD_PENDING_SOURCE`；V `me.pending`；A Choose/Cancel；现/接 |
| 对手栏 / P1 | 英雄、血/甲、星级、存活/淘汰名次、下位对手与幽灵标记、上次看见回合及阵容展开 | O `SLICE_OPPONENTS/OPP_BOARDS/CARD_OPP_HEROES/CARD_OPP_BOARDS`；V `seen_turn/seen_board`、`me.next_is_ghost`；现/接 |
| 战斗结果条 / P1 | 自己上一战的对手、胜/负/平、伤害、回合、截断警告；可展开战斗帧 | O global `won_last/lost_last`；V `combats[].turn/a/b/winner/damage/truncated/frames`；现/接 |
| 日志与状态 / P1 | 动作成功/拒绝、购买/三连/回合事件、处理中、回合耗时/总用时、重连；下载 replay | V `me.turn_events/stats`；U HTTP 结果/时间戳；现/接 |

## 2. 单卡显示规范（商店/手牌/战场/选择共用组件）
| 字段 | 显示与判定规则 | 数据来源 / 状态 |
|---|---|---|
| 名字与效果 | 中文名优先、缺失回退英文/id；卡面常驻效果摘要，展开全文；静态文字标“卡面”，动态数字不得硬套 | C `name_zh/name/text_zh/text/id`；V 同名字段；现 |
| 种族 | 图标旁保留中文：野兽/恶魔/龙/元素/机械/鱼人/海盗/野猪人/亡灵/畸变怪/纳迦；双种族全列，无种族写“无” | O minion `[20:31]` 按 `RACE_NAMES`；V `races`；C `races` 仅静态回退，不能用 `assoc` 代替；现 |
| tier 徽标 | 左上角“★N”，与攻击/费用分开；无星级写“—”，不可伪造一星 | O minion `[4]×6` / spell `[13]×6`；C/V `tier`；现 |
| 金卡 | 金边+“金色”文字；不依靠颜色；使用实例金色状态与对应金卡效果 | O minion `[5]`；V `golden`；C `normal` 指向普通版，`golden` 是升级目标 id，不是“本卡已金色”；现 |
| 攻击/生命 | 常驻当前 atk/hp，展开 max_hp/基础/临时/来源；百万数值允许缩写但悬浮给精确整数，不截断合法 synergy | O minion `[1:4]×10`；V `atk/hp/max_hp/breakdown` 优先保整数；现/接 |
| 动态关键词 | 图标+中文提示：嘲讽、圣盾、风怒、复生、烈毒、剧毒、潜行、磁力、超级风怒、顺劈、免疫、攻击时免疫；烈毒与剧毒分开 | O minion `[8:20]` 按 `KEYWORD_NAMES`；V `keywords` 是当前实例；现 |
| 战吼/亡语等文本关键词 | 使用独立“卡面能力”标记，避免将失去的动态圣盾补回；战吼/亡语不在 O 的 12 位中 | C `keywords` 的 `BATTLECRY/DEATHRATTLE` 等；C/V 效果全文；接 |
| 黑暗之赐 | 赐福卡显示“黑暗之赐”；受赐随从显示赐福附件名称/效果，不把全局 buff、deity 或全部附件统称赐福 | C `kind=dark_gift`；V 随从 `attached[].kind`；O 仅有附件数量，无法识别类型；接 |
| 附件/宝石 | 展开附件名称与说明、数值变化来源；磁力从 `breakdown.mods.kind=magnetic` 显示，不假设 attached 都是磁力 | V `attached/breakdown.mods/temporary/other`；C 附件效果；O `[6]×3` 只有附件计数；接 |
| 价格 | 商店显示实际金币/生命支出；手牌显示实际打出费用（当前 V 为 0）；饰品显示本次 cost；发动单列 activate_cost | O item `[2]×5` 需结合区域；V `shop.price/costs_health`、`hand.play_cost`、`pending.options[].cost`；不可用 C `cost` 当实际买价；现/接 |
| 可操作状态 | 买/打出/磁力/发动分开；禁用不隐藏卡片；目标高亮并保留槽位号 | A 最新掩码；V 对应实体 eid/hid；现 |

## 3. 饰品、赐福与选择流程
| 场景 | 规格 | 数据来源 / 状态 |
|---|---|---|
| 已获饰品 | 常驻名称+小/大类型+效果摘要；可展开全部，不限制恰好两个槽 | O `SLICE_CARD_TRINKETS` 8 个 id；C `kind=trinket_lesser/trinket_greater`；V `me.trinkets`；接 |
| 第 6/9 回合选择 | t6/t9 指**回合**不是酒馆星级；正常四选一并排完整说明/当前价格/基础价；只在 pending 到达时弹出，不按前端计时强行生成 | V `me.pending.kind=trinket/options/free/replace`；O `SLICE_CHOICES`；A `30+i`；现/接 |
| 非标准饰品选择 | 选项数量跟随 API，免费/替换明确显示；weight 是 offer 权重，不可冒充战斗胜率或升本概率 | V `pending.options[].weight/cost/base_cost`；现 |
| 当前赐福 | 按“随从附件 / 持续效果”显示名字、卡面数值、实际修正或 stacks；`deity` 独立显示为神灵，不与赐福混淆 | V `board/hand/shop[].attached`、`me.effects[].card/stacks`、`me.deity`；C `kind/text`；接 |
| 赐福按钮 | 名称统一“黑暗之赐”（兼容原 UI 黑暗赠礼）；费用、已用/上限、解锁回合、本回合已用、当前/下回合可选星级；不可用仍可查看规则 | V `me.dark_gift.{available,cost,uses,max_uses,unlock_turn,used_this_turn,tiers,next_tiers,slots}`；O `can_dark_gift/dark_gift_uses`；A `[6]`；接 |
| Discover/目标 | 来源卡+全文、候选实际属性/种族/金卡/关键词；选择费用与购买费用不能混淆；目标显示“区域+位置+名称”避免同名误选 | O `SLICE_CHOICES/CARD_CHOICES/CARD_PENDING_SOURCE`；V `pending.options/targets`，eid 对照自己 board/shop；A `[30..45]`；现/接 |
| 抉择语义 | `choose_one` 当前 V 返回两个相同源卡，不具备结构化两分支说明；未确认分支映射时写“选项 1/2，说明不可用”，不可猜文本顺序 | V `Pending::ChooseOne`；补（结构化 mode label/text） |

## 4. 战斗、对手、操作反馈
| 事项 | 规则 | 来源 / 状态 |
|---|---|---|
| 信息边界 | 后端只白名单输出自己和对手公开字段；禁止转发 debug view 的对手实时 `board/last_board` 或全量 state_json | V `opponents[].seen_board/seen_turn`；禁 |
| 上轮阵容 | 标“上次交战时所见，第 X 回合”，不是“对手当前阵容”；从未见过写“未知”，不可用空棋盘冒充 | O `SLICE_OPP_BOARDS`；V `seen_board/seen_turn`；现 |
| 战斗结果 | 先从完整 combats 过滤 `a==seat || b==seat`，再取最近；当前先截全局末三条可能漏掉自己；winner 按引擎记录语义解码并用胜/负/平夹具校验 | V `combats`、`me.stats`；O `won_last/lost_last` 交叉校验；接 |
| 伤害详情 | 摘要显示战斗记录 damage 与自己 last_damage；血/甲分别列，不以相邻招募状态血差推算纯战斗伤害（可能混入购牌自伤） | V `combats[].damage/me.last_damage/health/armor`；现 |
| 当前排名 | 存活期间只显示“血甲排序（非最终名次）”及存活人数；淘汰/结算显示 placement；不把 placement=0 显示第 0 名 | O `OPP_PLACEMENT×8`、global `alive`；V `me.placement`、`placements()`；现/接 |
| 非法动作 | 请求中锁定提交；HTTP 400 展示原因与 action，刷新状态但不假定动作成功；断线单独标识，不盲目重发购买 | A mask；U `/act` 响应；现/接 |
| 撤销 | `Cancel [7]` 仅取消允许取消的 pending，绝不是撤销买卖；普通对局不提供 undo，防止看牌回滚污染示范数据 | A `A_CANCEL`；现 |
| 时间/结束回合 | 显示回合与累计耗时，注明“无强制倒计时”；结束后显示“bot/战斗结算中”；不可把本地计时器当引擎绳子 | O global `turn`；V phase；U `started`/请求状态；接 |

## 5. 解码与接口建议
| 数据 | 精确解码 / 实现约束 | 来源 |
|---|---|---|
| 二进制与布局 | `features` little-endian f32，3227；`cards` little-endian i32，124；调用 `decode_blocks`，引入 slice 常量，不散落硬编码总偏移 | O `_obs()`、`decode_blocks` |
| 卡 id | 0=空槽；正值 k 对应同构建 C 的 `cards[k-1]`，校验版本和边界；不能将 k 当 dbf 或字符串 id | O `SLICE_CARD_*`；C `meta/cards` |
| global | 按 `GLOBAL_FIELD_INDEX` 查字段，用 `GLOBAL_FIELD_SCALE` 乘回后取整；未列 scale 的布尔/原值直接读；42:53 是大厅种族位 | O `SLICE_GLOBAL` |
| minion | `SLICE_BOARD.reshape(7,31)`；`[0]`存在，[1:4]×10，[4]×6，[5]布尔，[6:8]×3；动态位按表，不 clamp 到 0..1 | O `MINION_*`；引擎 `push_minion` |
| item | hand/shop/choices 分别 reshape `(10,40)/(8,40)/(16,40)`；[0]存在，[1]随从，[2]×5；随从取 [9:40]；法术 [10]×6 是 data，[13]×6 是 tier，不当 atk | O `ITEM_* / SPELL_*`；引擎 `push_item` |
| item 标志 | [3] locked 原值；[4:9] temporary/combined/frozen/kept/marked；手牌 frozen 语义为本回合打出即死亡，不可画成商店冻结 | O `ITEM_*`；区域语义必须区分 |
| 对手 | reshape `(7,9)`；[0:2]存在/存活，[2]×40血，[3]×20甲，[4]×6星，[5]×7所见长度，[6]×8名次，[7:9]上/下个对手 | O `SLICE_OPPONENTS`；阵容 `(7,7,31)`；对应 CARD 切片同序 |
| 数据优先级 | UI 精确整数与丰富效果优先 V；O 为训练口径/回放回退；C 只补静态；不得让静态 atk/hp 覆盖实例；f32 大数非整数真源 | V `minion_json`；O/C |
| 后端增补 | 仅扩 `/state` 白名单：max_hp、附件对象、breakdown、trinkets、effects、dark_gift、队列、自己战斗；不要返回整个 V | V；现实现 `state/_card_brief` |
| 动作映射 | End 0/Refresh 1/Freeze 2/Upgrade 3/Power 4–5/Gift 6/Cancel 7/Buy 8+i/Sell 16+i/Activate 23+i/Choose 30+i | A 标准 245 维 |
| 位置动作 | Play `46+hand*8+pos`；Magnetize `126+hand*7+board`；Move `196+from*7+to`；按钮用最新 mask，无扩展 245+ | A `action_space_std` |

## 6. 无需改引擎与真正缺口
| 请求字段 | 结论与降级（避免返工） | 依据 |
|---|---|---|
| 种族/金卡/关键词/完整效果/费用/饰品/赐福/对手/战果/数值拆解 | 全部基础展示可立即落地；多数只需保留 V 字段；不能因 O 无字段就要求改引擎 | O+C+V |
| 升本“概率” | 升本动作不是概率判定：展示费用与可用性；若指升本后刷出各星级/指定牌概率，O/V 无现成分布，UI 写“不可用”，不得猜均匀分布 | O `upgrade_price`、A Upgrade；补：公开口径的商店分布 API（不得暴露他人隐藏持牌） |
| 精确赐福/宝石历史次数与全部动态效果解释 | 附件名称、当前 stacks、已记录 mods 能显示；未记录来源、`breakdown.other` 的归因不能恢复；不把属性差反算成宝石次数 | V `attached/effects/breakdown`；补：缺失来源的结构化效果/事件计数 |
| 通用抉择两分支说明 | C 全文可读，但缺 mode id→label/text 的稳定映射 | V `choose_one` 同源卡两份；补：选项语义字段 |
| 精确伤害口径/护甲吸收拆分 | 基础胜负伤害已有；若要求战斗原始值、伤害上限裁剪后值、护甲吸收、生命损失的并列权威值，现有摘要无完整结构 | V `combat_json`；补：结算 damage breakdown |
| 战斗动画、撤销、计时 | V 已有 frames，可后续接线；正式对局不做撤销；本地耗时可做，不需引擎；强制倒计时属于新增玩法 | V `combats.frames`；U；不是 P0 引擎阻塞项 |

## 7. 视觉参考与验收
| 项目 | 可复用点 / 限制 | 来源 |
|---|---|---|
| 布局与命名 | 参考“英雄/随从/酒馆法术/饰品”分类、名称+头像+种族的紧凑卡片；本 UI 仍以战场与动作优先，不搬运平均名次推荐 | [bgbuddy 中文主页](<https://bgbuddy.gg/zh-CN>)（已 fetch） |
| 图片 URL | 已观察 `https://art.hearthstonejson.com/v1/orig/{card_id}.png`；如 `BG20_HERO_103.png`、`BGS_121.png`；按 C.id 请求，失败显示文字占位，不阻塞操作 | [实测页面引用的头像](<https://art.hearthstonejson.com/v1/orig/BG20_HERO_103.png>)；仅证明页面引用，未逐图验可用性 |
| 配色与图标 | 文本抓取不能确认 CSS 颜色/种族图标资源：精确色值与专用图标 URL **不可用**；建议深色中性底、金色金卡、紫色赐福、红血/灰甲，并保持文字冗余 | bgbuddy fetch（非像素证据）；本规格视觉建议 |
| 素材与离线 | 图片版权属于相应权利人，不承诺可再分发；本地文字/自绘符号为默认降级，在线图只增强外观 | bgbuddy 页脚的 Blizzard/HSJSON 归属说明 |
| 验收用例 | 普通/金卡/双种族/动态圣盾、法术、百万属性、受赐附件、磁力、饰品免费/替换、Discover、同名目标、从未交战/旧阵容、胜负平/淘汰、HTTP 400/断线均不得误导 | O/C/V/A/U 各表契约 |
| 交付顺序 | P0 先做卡片信息→选择说明→费用/血甲→饰品与赐福；P1 再做自己战果/公开对手/日志；P2 才加图片和动画 | 手打决策的信息价值；无需等待“补”项 |
