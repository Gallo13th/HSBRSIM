# Verbatim Evidence Report — Battlegrounds Anomalies `BG27_Anomaly_101` / `BG27_Anomaly_102`

Scope: "What Are the Odds?" (`BG27_Anomaly_101`, dbfId 102987) and "How to Even??"
(`BG27_Anomaly_102`, dbfId 102988). Every claim below is tagged `[AUTHORITY: ...]` or
`[NO AUTHORITY FOUND]`. Nothing is inferred and presented as a quote.

## Sources that were fetched (and their status)

| Source | URL | Status |
|---|---|---|
| Hearthstone Wiki (wiki.gg) "What Are the Odds?" | `https://hearthstone.wiki.gg/wiki/Battlegrounds/What_Are_the_Odds%3F` | HTTP 200 |
| Hearthstone Wiki (wiki.gg) "How to Even??" | `https://hearthstone.wiki.gg/wiki/Battlegrounds/How_to_Even%3F%3F` | HTTP 200 |
| Hearthstone Wiki "Anomaly (Battlegrounds)" | `https://hearthstone.wiki.gg/wiki/Battlegrounds/Anomaly` | HTTP 200 |
| Hearthstone Wiki "Triple Reward (What Are the Odds?)" | `https://hearthstone.wiki.gg/wiki/Battlegrounds/Triple_Reward_(What_Are_the_Odds%3F)` | HTTP 200 |
| Hearthstone Wiki "Triple Reward" (generic) | `https://hearthstone.wiki.gg/wiki/Battlegrounds/Triple_Reward` | HTTP 200 |
| Hearthstone Wiki "Tavern Tier" | `https://hearthstone.wiki.gg/wiki/Battlegrounds/Tavern_Tier` (redirect target of `/wiki/Tavern_Tier`) | HTTP 200 |
| Hearthstone Wiki "Big League" | `https://hearthstone.wiki.gg/wiki/Battlegrounds/Big_League` | HTTP 200 |
| Hearthstone Wiki "Little League" | `https://hearthstone.wiki.gg/wiki/Battlegrounds/Little_League` | HTTP 200 |
| Hearthstone Wiki "Secrets of Norgannon" | `https://hearthstone.wiki.gg/wiki/Battlegrounds/Secrets_of_Norgannon` | HTTP 200 |
| Hearthstone Wiki "Patch 27.6.0.187190" | `https://hearthstone.wiki.gg/wiki/Patch_27.6.0.187190` | HTTP 200 |
| Hearthstone Wiki "Patch 27.2.0.183876" | `https://hearthstone.wiki.gg/wiki/Patch_27.2.0.183876` | HTTP 200 |
| Hearthstone Wiki "Discover (Battlegrounds)" | `https://hearthstone.wiki.gg/wiki/Battlegrounds/Discover` | HTTP 200 (no triple/tier rule text) |
| Blizzard official 27.6 Patch Notes | `https://hearthstone.blizzard.com/en-us/news/23989479/27-6-patch-notes` | HTTP 200 |
| Blizzard official 27.2 Patch Notes | `https://hearthstone.blizzard.com/en-us/news/23987537/27-2-patch-notes` | HTTP 200 |
| HearthstoneJSON full card dump (CardDefs-derived) | `https://api.hearthstonejson.com/v1/latest/enUS/cards.json` | HTTP 200 (local copy grepped) |
| Hearthstone Fandom wiki (`hearthstone.fandom.com`) | `https://hearthstone.fandom.com/wiki/What_Are_the_Odds%3F`, `.../How_to_Even%3F%3F`, `.../Battlegrounds/Anomaly` | **FAILED — did not fetch.** DNS resolver error: `URL hostname "hearthstone.fandom.com" resolves to a non-public IP address`. Also failed via the Fandom `api.php`. No Fandom content was inspected. |

**Important pagename correction:** `https://hearthstone.wiki.gg/wiki/What_Are_the_Odds%3F` and
`https://hearthstone.wiki.gg/wiki/How_to_Even%3F%3F` (the URLs in the task) both return **HTTP 404**.
The real pages are under the Battlegrounds namespace: `.../wiki/Battlegrounds/What_Are_the_Odds%3F`
and `.../wiki/Battlegrounds/How_to_Even%3F%3F`. `https://hearthstone.wiki.gg/wiki/Triple` is also a 404
(the mechanic is covered at `https://hearthstone.wiki.gg/wiki/Battlegrounds/Triple_Reward` and
`https://hearthstone.wiki.gg/wiki/Battlegrounds/Golden_minion`).

---

## Q1. Which Tavern Tiers exist, and what is the STARTING Tavern Tier?

### Q1a. Which tiers exist — FOUND

[AUTHORITY: verbatim quote + URL] Card text, "What Are the Odds?":

> "Only Tavern Tiers 1, 3, and 5 exist. Triple Rewards **Discover** a minion of your Tier."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/What_Are_the_Odds%3F`

[AUTHORITY: verbatim quote + URL] Card text, "How to Even??":

> "Only Tavern Tiers 2, 4, and 6 exist. Triple Rewards **Discover** a minion of your Tier."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/How_to_Even%3F%3F`

[AUTHORITY: verbatim quote + URL] Official Blizzard 27.6 patch notes list the same two anomalies:

> "What Are the Odds? | Only Tavern Tiers 1, 3, and 5 exist. Triple rewards Discover a minion of your Tier."
> "How to Even?? | Only Tavern Tiers 2, 4, and 6 exist. Triple rewards Discover a minion of your Tier."

— `https://hearthstone.blizzard.com/en-us/news/23989479/27-6-patch-notes`

[AUTHORITY: verbatim quote + URL] The same two lines also appear on the wiki's transcription of that patch:

> "What Are the Odds? | Only Tavern Tiers 1, 3, and 5 exist. Triple rewards Discover a minion of your Tier."
> "How to Even?? | Only Tavern Tiers 2, 4, and 6 exist. Triple rewards Discover a minion of your Tier."

— `https://hearthstone.wiki.gg/wiki/Patch_27.6.0.187190`

[AUTHORITY: verbatim quote + exact card data + URL] Raw game-card data (CardDefs-derived), exact strings:

> `BG27_Anomaly_101` "What Are the Odds?" — `"[x]Only Tavern Tiers 1, 3,\nand 5 exist. Triple\nRewards <b>Discover</b> a\nminion of your Tier."`
> `BG27_Anomaly_102` "How to Even??" — `"[x]Only Tavern Tiers 2, 4,\nand 6 exist. Triple\nRewards <b>Discover</b> a\nminion of your Tier."`

— `https://api.hearthstonejson.com/v1/latest/enUS/cards.json` (dbfId 102987 / 102988), corroborated by
`https://hearthstone.wiki.gg/wiki/Battlegrounds/What_Are_the_Odds%3F` (card id `BG27_Anomaly_101`, dbfId `102987`)
and `https://hearthstone.wiki.gg/wiki/Battlegrounds/How_to_Even%3F%3F` (card id `BG27_Anomaly_102`, dbfId `102988`).

### Q1b. STARTING Tavern Tier — **NO AUTHORITY FOUND**

[NO AUTHORITY FOUND] Neither the wiki page for "What Are the Odds?"
(`https://hearthstone.wiki.gg/wiki/Battlegrounds/What_Are_the_Odds%3F`) nor "How to Even??"
(`https://hearthstone.wiki.gg/wiki/Battlegrounds/How_to_Even%3F%3F`) contains any statement about the starting
Tavern Tier. Both pages have only these sections: *Availability*, *Related cards* (101 only), *Gallery*,
*Patch changes*, *External links*. There is **no** "Notes" or "Strategy" section and **no** prose body text.

[NO AUTHORITY FOUND] The Blizzard official 27.6 patch notes
(`https://hearthstone.blizzard.com/en-us/news/23989479/27-6-patch-notes`) state only the two sentences quoted
in Q1a. They do not state a starting tier.

[NO AUTHORITY FOUND] The general anomaly page
(`https://hearthstone.wiki.gg/wiki/Battlegrounds/Anomaly`) says only:

> "Anomaly appearance rates vary, with some more common than others."
> "Some minions, minion types, and heroes won't be offered if a particular Anomaly applies to your game."

It contains no per-anomaly starting-tier information.

[NO AUTHORITY FOUND] **"Does How to Even?? start at Tier 2?"** — not stated anywhere I fetched. The *only*
nearby precedent on the wiki is a *different* anomaly that explicitly says so, which shows the wiki does spell
this out when it is the case:

[AUTHORITY: verbatim quote + URL] Finicky Hourglass: "Start at Tavern Tier 2."

— `https://hearthstone.wiki.gg/wiki/Patch_27.2.0.183876` (and
`https://hearthstone.wiki.gg/wiki/Battlegrounds/Finicky_Hourglass`)

[AUTHORITY: verbatim quote + URL] Temperance of Aman'Thul: "Start at Tavern Tier 4. Gain 10 extra Gold on your
first turn only."

— `https://hearthstone.wiki.gg/wiki/Patch_27.6.0.187190`

Neither "What Are the Odds?" nor "How to Even??" has an equivalent "Start at Tavern Tier N" clause in its card
text or its article. Treat "How to Even?? starts at Tier 2" and "What Are the Odds? starts at Tier 1" as
**UNVERIFIED** by the sources fetched.

---

## Q2. Upgrade mechanics — what determines cost and turn gating?

### Q2a. General upgrade rule — FOUND (baseline rule only)

[AUTHORITY: verbatim quote + URL] From the Tavern Tier page:

> "You can access higher-tier minions by upgrading your Tavern Tier. The minions that are offered to you in
> Bob's Tavern come from a pool of shared minions, shared by all players. All minions that are at or below
> your Tavern Tier level are available to be offered to you in Bob's Tavern, with the minions being randomly
> selected from the shared pool."

> "At any time, you can upgrade your Tavern to the next tier. This will improve the quality of minions offered
> and occasionally increase the number of minions for sale. The number of minions offered to the player starts
> at 3 and is increased by 1 at tiers 2, 4 and 6. Taverns start at tier 1 and can be upgraded to tier 6. Your
> current Tavern Tier is displayed on a small flag next to Bob, and is visible to all players when they hover
> over. Upgrading will also notify every other player which tier you currently are."

> "Upgrading starts at 5 Coins, and each upgrade costs more than the last. However, at the start of each round,
> the cost of upgrading reduces by 1."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Tavern_Tier`
(that page is the redirect target of the task's `https://hearthstone.wiki.gg/wiki/Tavern_Tier` URL)

[AUTHORITY: verbatim quote + URL] From the Gold page:

> "The three main functions of Bob's Tavern, Tavern Tier upgrades, Refreshing, and Freezing, cost Gold."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Gold`

**Note on the general rule as written:** it is phrased for the standard 1→6 ladder ("Taverns start at tier 1
and can be upgraded to tier 6", "increased by 1 at tiers 2, 4 and 6"). It does not describe a three-tier ladder.

### Q2b. Is the 1→3 / 2→4 upgrade priced as the next INTEGER tier, the next EXISTING tier, or a fixed
number of upgrades? — **NO AUTHORITY FOUND**

[NO AUTHORITY FOUND] There is **no** upgrade-path table, no "Summary"/"Notes" section, and no mention of
upgrade cost or turn gating on either
`https://hearthstone.wiki.gg/wiki/Battlegrounds/What_Are_the_Odds%3F` or
`https://hearthstone.wiki.gg/wiki/Battlegrounds/How_to_Even%3F%3F`.
Verified by fetching the raw wikitext through the MediaWiki API — the entire article body of each page is a
single card-data template invocation and nothing else:

> `{{Card template v2\n|dbfId=102987\n|derived_relatedCardDbfIds=103188\n}}` (What Are the Odds?)
> `{{Card template v2\n|dbfId=102988\n}}` (How to Even??)

— `https://hearthstone.wiki.gg/api.php?action=parse&page=Battlegrounds/What_Are_the_Odds%3F&prop=wikitext&format=json`
and `https://hearthstone.wiki.gg/api.php?action=parse&page=Battlegrounds/How_to_Even%3F%3F&prop=wikitext&format=json`

[NO AUTHORITY FOUND] The Blizzard official 27.2 and 27.6 patch notes contain no upgrade-cost or
upgrade-path statement for these anomalies. Likewise the wiki's "Anomaly (Battlegrounds)" page.

[NO AUTHORITY FOUND] No "start at Tavern Tier" / upgrade-cost interaction is documented for these two
anomalies anywhere I fetched. The only anomaly I found whose *text* modifies upgrade cost is a different one:

[AUTHORITY: verbatim quote + URL] Uncompensated Upset: "Start at 1 Gold. Minions cost (1) but sell for (0).
Upgrading the Tavern costs (2) less."

— `https://hearthstone.wiki.gg/wiki/Patch_27.2.0.183876`

---

## Q3. Are Tavern offers restricted to existing tiers only? Can a non-existing tier be seen another way?

### Q3a. "Only Tavern Tiers X exist" — card text only

[AUTHORITY: verbatim quotes + URL] The only authoritative wording is the "exist" phrasing already quoted in
Q1a (card text and official patch notes). That is the full extent of what the card data says.

[AUTHORITY: verbatim quote + URL] The wiki's general offer rule (standard ladder) reads:

> "All minions that are at or below your Tavern Tier level are available to be offered to you in Bob's Tavern,
> with the minions being randomly selected from the shared pool."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Tavern_Tier`

### Q3b. Is there explicit wiki/Blizzard prose that the Tavern never offers a non-existing tier minion under
101/102? — **NO AUTHORITY FOUND**

[NO AUTHORITY FOUND] No fetched page states, in prose, that Tavern offers under "What Are the Odds?" contain
no Tier 2/4 minions, or that Tavern offers under "How to Even??" contain no Tier 1/3/5 minions.

### Q3c. Big League / Little League — FOUND (with a correction to the task's premise)

[AUTHORITY: verbatim quote + URL] Big League card text is **not** the text given in the task. It reads:

> "Only Tavern Tiers 3, 4, 5, and 6 exist. Start with 10 extra Armor."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Big_League` (card id `BG27_Anomaly_100`, dbfId `102986`)

[AUTHORITY: verbatim quote + URL] Historic change to that text:

> "Now reads: '*Only Tavern Tiers 3, 4, 5, and 6 exist. Start with 10 extra Armor.*' (previously: '*Only
> Tavern Tiers 3, 4, 5, and 6 exist.*')"

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Big_League` (Patch 27.4.2.186852, 2023-09-28)

[AUTHORITY: verbatim quote + URL] Little League card text is **not** "Only Tavern Tiers 1 and 2 exist" as
stated in the task; it is:

> "Only Tavern Tiers 1, 2, 3, and 4 exist."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Little_League` (card id `BG27_Anomaly_800`, dbfId `102006`)

[AUTHORITY: verbatim quote + URL] Original announcement wording for both:

> "Big League | Only Tavern Tiers 3, 4, 5, and 6 exist."
> "Little League | Only Tavern Tiers 1, 2, 3, and 4 exist."

— `https://hearthstone.blizzard.com/en-us/news/23987537/27-2-patch-notes` and
`https://hearthstone.wiki.gg/wiki/Patch_27.2.0.183876`

### Q3d. Discover / "Tier N or lower" rewards reaching a non-existing tier — **NO AUTHORITY FOUND**

[NO AUTHORITY FOUND] No fetched source describes interaction between these two anomalies and any
Discover effect, "Tier N or lower" reward, or other anomaly. The wiki's Battlegrounds Discover page contains
no tier-restriction or triple-reward rule text at all — it defines only:

> "**Discover** — Choose one of three cards to add to your hand."
> "**Discover** in Battlegrounds works exactly like how it would work in any other game mode, except is
> limited to Battlegrounds cards."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Discover`

---

## Q4. "Triple Rewards Discover a minion of your Tier" — exact rule

### Q4a. The anomaly's own wording — FOUND

[AUTHORITY: verbatim quote + URL] "Triple Rewards **Discover** a minion of your Tier." — see Q1a sources
(`https://hearthstone.wiki.gg/wiki/Battlegrounds/What_Are_the_Odds%3F`,
`https://hearthstone.wiki.gg/wiki/Battlegrounds/How_to_Even%3F%3F`,
`https://hearthstone.blizzard.com/en-us/news/23989479/27-6-patch-notes`).

### Q4b. The concrete "What Are the Odds?" Triple Reward token — FOUND, and it is surprising

[AUTHORITY: verbatim quote + URL] The related token page reads:

> "**Discover** a minion from **Tier 0**."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Triple_Reward_(What_Are_the_Odds%3F)`
(card id `BG27_Anomaly_101t`, dbfId `103188`, type Spell)

[AUTHORITY: verbatim quote + exact card data + URL] Confirmed against raw game data:

> `BG27_Anomaly_101t` "Triple Reward" — `"<b>Discover</b> a minion\nfrom <b>Tier 0</b>."`

— `https://api.hearthstonejson.com/v1/latest/enUS/cards.json`

**Corroborating analogue (same engineer-facing idiom, different card):**

[AUTHORITY: verbatim quotes + URL] Generic Triple Reward token: "**Discover** a minion from **Tier 0**."
— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Triple_Reward` (card id `TB_BaconShop_Triples_01`, dbfId `59604`)

[AUTHORITY: verbatim quote + URL] Lead Explorer (hero power): "**Discover** a minion from your Tier. Costs (1)
more after each use." — and its token Recruitment Map: "**Discover** a minion from **Tier 0**."
— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Discover` (listing), corroborated in raw data at
`https://api.hearthstonejson.com/v1/latest/enUS/cards.json` (`TB_BaconShop_HP_047` / `TB_BaconShop_HP_047t`)

### Q4c. Does the Discover tier equal the player's CURRENT Tavern Tier instead of minion-tier+1? — **NO
AUTHORITY FOUND** (as an explicit statement)

[NO AUTHORITY FOUND] No fetched wiki or Blizzard page states that the Discover tier equals the player's current
Tavern Tier, nor that it replaces a "minion's tier + 1" rule. The wiki has **no** prose page for the triple
mechanic: `https://hearthstone.wiki.gg/wiki/Triple` returns **HTTP 404**. The closest pages are
`https://hearthstone.wiki.gg/wiki/Battlegrounds/Triple_Reward` (card data only, no notes) and
`https://hearthstone.wiki.gg/wiki/Battlegrounds/Golden_minion` (not fetched as a rules text source).

[NO AUTHORITY FOUND for the "usual minion-tier+1" rule] I could not find any fetched source that states the
baseline triple rule as "Discover a minion one tier above the tripled minion", so the *contrast* the question
asks about is itself unquoted here.

### Q4d. Is the Discover tier frozen/snapshotted when the triple counter fills? — **NO AUTHORITY FOUND**

[NO AUTHORITY FOUND] Nothing in any fetched wiki page, wiki patch-change list, or Blizzard patch notes
addresses snapshotting/freezing of the tier for this Discover.

### Q4e. Asymmetry worth flagging: "How to Even??" has no dedicated Triple Reward token page

[AUTHORITY: verbatim card data + URL] In the full card dump there is a token `BG27_Anomaly_101t` for "What Are
the Odds?", but **no** `BG27_Anomaly_102t` (or any other `BG27_Anomaly_102*` token) exists. The command used was
a scan of every card id starting with `BG27_Anomaly_10`, which returned exactly
`BG27_Anomaly_100, _101, _101t, _102, _103, _104t, _104t2, _104t3, _104t4, _104t5, _104t6, _104t7, _104t8,
_104t9, _104t10`. The API query
`https://hearthstone.wiki.gg/api.php?action=parse&page=Battlegrounds/Triple_Reward_(How_to_Even%3F%3F)&prop=wikitext&format=json`
returns `"code":"missingtitle"` ("The page you specified doesn't exist."). And the "How to Even??" wiki page's
*Related cards* section is absent, whereas the 101 page carries
`derived_relatedCardDbfIds=103188` in its raw wikitext. I make **no** claim about what this implies
mechanically — I only report that the token does not exist in the data I fetched.

---

## Q5. Known interactions/bugs in patch notes or wiki bug-fix sections

### Q5a. Full bug-fix / change history for both anomalies — FOUND (complete as listed by the wiki)

[AUTHORITY: verbatim quotes + URL] "What Are the Odds?" patch changes:

> "**Patch 31.6.0.216423 (2025-02-18):**
> - Removed from the pool of available Anomalies in Battlegrounds.
> - Now banned in Elemental lobbies in Battlegrounds.
> - Now banned in Naga lobbies in Battlegrounds."
> "**Patch 28.0.0.189384 (2023-11-10):**
> - The following heroes are now banned from this Anomaly: Patches the Pirate, Cap'n Hoggarr, Dinotamer Brann, Rock Master Voone, Ysera
> - **2023-11-17:** Will now appear less frequently."
> "**Patch 27.6.0.187190 (2023-10-17):**
> - Added."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/What_Are_the_Odds%3F`

[AUTHORITY: verbatim quotes + URL] "How to Even??" patch changes:

> "**Patch 31.6.0.216423 (2025-02-18):**
> - Removed from the pool of available Anomalies in Battlegrounds.
> - Now banned in Quilboar lobbies in Battlegrounds.
> - Now banned in Demon lobbies in Battlegrounds."
> "**Patch 28.2.0.190416 (2023-12-05):**
> - Now banned in Mech lobbies in Battlegrounds."
> "**Patch 28.0.3.190145 (2023-11-28):**
> - Now banned in Mech lobbies in Battlegrounds."
> "**Patch 28.0.0.189384 (2023-11-10):**
> - The following heroes are now banned from this Anomaly: Millificent Manastorm, C'Thun, Ragnaros the Firelord, Overlord Saurfang, Onyxia, Millhouse Manastorm, Lich Baz'hial
> - This Anomaly will no longer appear in games with Mechs.
> - **2023-11-17:** Will now appear less frequently."
> "**Patch 27.6.0.187190 (2023-10-17):**
> - Added."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/How_to_Even%3F%3F`

**Note:** neither page has a "Bug fixes and other changes" subsection. The 101 page has a *Card changes*
subsection only. Contrast with Little League, which does:

[AUTHORITY: verbatim quote + URL] Little League:

> "**Bug fixes and other changes**
> - **Patch 27.4.0.185749 (2023-09-19):** **2023-09-22:** Reduced chance to appear."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Little_League`

### Q5b. Interaction with Tier 7 / "Secrets of Norgannon" — **NO AUTHORITY FOUND**

[NO AUTHORITY FOUND] No fetched page documents any interaction, bug, or fix between "What Are the Odds?" /
"How to Even??" and "Secrets of Norgannon" or Tavern Tier 7.

The relevant facts that *are* on the record (separately, with no bridging statement):

[AUTHORITY: verbatim quote + URL] "Tavern Tier 7 exists. Start with 10 extra Armor." — Secrets of Norgannon,
`https://hearthstone.wiki.gg/wiki/Battlegrounds/Secrets_of_Norgannon`

[AUTHORITY: verbatim quote + URL] From the official 27.2 patch notes:

> "Tier 7 Minions are only accessible through Thorim's Hero Power or in games with the Secrets of Norgannon
> Anomaly. In games with the Secrets of Norgannon Anomaly active, Tier 7 can be accessed through any normal
> means (upgrading the Tavern, getting triples, Patient Scout, etc.). When Tier 7 is active, there are five
> copies of each Tier 7 minion that's in that game's minion pool."

— `https://hearthstone.blizzard.com/en-us/news/23987537/27-2-patch-notes` (also transcribed at
`https://hearthstone.wiki.gg/wiki/Patch_27.2.0.183876`)

[AUTHORITY: verbatim quote + URL] Secrets of Norgannon's only documented bug fix is unrelated to tiers:

> "**Bug fixes and other changes**
> - **Patch 31.6.2.217489 (2025-02-27):** **2025-03-04:** Fixed a bug where rerolling a Hero while Secrets of
> Norgannon was active would result in the new Hero losing the bonus Armor."

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Secrets_of_Norgannon`

### Q5c. Interaction with "Tier 6 or lower" rewards — **NO AUTHORITY FOUND**

[NO AUTHORITY FOUND] No fetched page mentions "Tier 6 or lower" (or "Tier N or lower") rewards in connection
with either anomaly.

### Q5d. Patch-note bug sections mentioning these anomalies — **NO AUTHORITY FOUND**

[NO AUTHORITY FOUND] The Blizzard official 27.6 patch notes' "Bug Fixes and Game Improvements" section
(`https://hearthstone.blizzard.com/en-us/news/23989479/27-6-patch-notes`) lists Battlegrounds fixes for Shifter
Zerus, Spellcraft+Magnetic, and Taunt Magnetic Mech/Iron Groundskeeper only — neither anomaly is mentioned in a
bug-fix context. Blizzard 27.2 patch notes (`https://hearthstone.blizzard.com/en-us/news/23987537/27-2-patch-notes`)
mention these anomalies only in the "additional Anomalies coming throughout Patch 27.2" / 27.6 tables (the
27.2 note lists Big League and Little League only; 101/102 appear in the 27.6 note).

---

## Discrepancy: are these anomalies in the current (Patch 36.2.2) pool?

The task premise says both are "still in Patch 36.2.2 pool". The sources I fetched say otherwise:

[AUTHORITY: verbatim quote + URL] "This anomaly is currently **not** available in the pool."
— `https://hearthstone.wiki.gg/wiki/Battlegrounds/What_Are_the_Odds%3F` (Availability section)

[AUTHORITY: verbatim quote + URL] "This anomaly is currently **not** available in the pool."
— `https://hearthstone.wiki.gg/wiki/Battlegrounds/How_to_Even%3F%3F` (Availability section)

[AUTHORITY: verbatim quote + URL] The current-pool listing on the Anomaly (Battlegrounds) page, generated by
the wiki's live Cargo card query, does **not** include either card. Its query filter is:

> "These are the Anomalies that are currently available."
> `{{Card query|layout=image|where=CardTag.typeId=43 AND {{HoldsForFake|CardTag.stringTags|2=2900=1|3= }}|orderBy=Card.name ASC}}`
> "===Unused Anomalies==="
> "These Anomalies can be found in the game data, but are archived, removed from the pool, or unused."

Both cards appear in the **Unused Anomalies** table on that page, and both carry the string tag `2900=0`
(Secrets of Norgannon, which is in the active table, carries `2900=1`).

— `https://hearthstone.wiki.gg/wiki/Battlegrounds/Anomaly`

Caveat: I could not open a Patch 36.2.2 patch-notes article or any current-pool snapshot to test the premise
directly. The most recent patch note I successfully retrieved was 27.6 (2023). The 28.x Blizzard URLs I tried
returned HTTP 403 to `curl` and a 404 via the fetch tool for the path I guessed; note also that
`https://hearthstone.wiki.gg/wiki/Battlegrounds/Secrets_of_Norgannon` itself claims "This anomaly is currently
available in the pool" while not appearing in the Anomaly page's live generated table, so the wiki's own
Availability bullets and its generated table can disagree.

---

## Explicit list of what could NOT be found

1. Any statement of the **starting Tavern Tier** for `BG27_Anomaly_101` or `BG27_Anomaly_102`.
2. Any statement that "How to Even??" starts at Tier 2, or that "What Are the Odds?" starts at Tier 1.
3. Any **upgrade path / cost table** for a three-tier ladder (1→3, 2→4), and any statement of whether the
   upgrade is priced as the next integer tier, the next existing tier, or a fixed number of upgrades.
4. Any **turn gating** specific to these anomalies' upgrades.
5. Any prose confirming Tavern offers are restricted to the existing tiers under these anomalies.
6. Any statement about Discover or "Tier N or lower" rewards reaching a non-existing tier.
7. Any explicit statement that the Triple Reward Discover tier equals the player's **current** Tavern Tier, or
   that it replaces a "minion tier + 1" rule.
8. Any statement on **snapshotting/freezing** the tier when the triple counter fills.
9. Any documented **interaction or bug** involving these anomalies and Secrets of Norgannon / Tavern Tier 7.
10. Any documented interaction with "Tier 6 or lower" rewards.
11. **Hearthstone Fandom** content of any kind — `hearthstone.fandom.com` failed to resolve (non-public IP) via
    both the wiki HTML fetch and its `api.php`. No Fandom text was read; nothing from Fandom is quoted here.
12. A **Patch 36.2.2** (or any 36.x) patch note. Not retrieved.

Additionally, the wiki pages the task supplied for the two anomalies
(`https://hearthstone.wiki.gg/wiki/What_Are_the_Odds%3F` and
`https://hearthstone.wiki.gg/wiki/How_to_Even%3F%3F`) are **404**; the live pages live under
`/wiki/Battlegrounds/`. `https://hearthstone.wiki.gg/wiki/Triple` is also **404**.

---

# 最终裁定（2026-09-20）— 逐问结论与实现口径

**结论: 两张均 REGISTERED。** 引擎新增两个原语（`hsrl2/game.py`）:
`game._tavern_tier_ladder`（存在档集合：升级落点 / 酒馆随从+法术抽取 /
Discover 候选三处读取）与 `game._triple_reward_of_own_tier`（三连奖励档
= 本人当前档）。注册于 `hsrl2/scripts/batches/batch_anomalies3.py`
（`WhatAreTheOddsAnomaly` / `HowToEvenAnomaly`）；测试
`hsrl2/tests/test_batch_anomalies3.py::TestTierLadderAnomalies`。

**再次抓取的 wiki 状态（与上文 2026-09-16 一致，仍无 Notes）:**

| 页面 | revid | 最后编辑 | 内容 |
|---|---|---|---|
| `https://hearthstone.wiki.gg/wiki/Battlegrounds/What_Are_the_Odds%3F` | 836162 | 2025-01-22 | 仅 `{{Card template v2\|dbfId=102987\|derived_relatedCardDbfIds=103188}}`；节: Availability / Related cards / Gallery / Patch changes |
| `https://hearthstone.wiki.gg/wiki/Battlegrounds/How_to_Even%3F%3F` | 805286 | 2024-07-05 | 仅 `{{Card template v2\|dbfId=102988}}`；无 Related cards 节 |
| `https://hearthstone.wiki.gg/wiki/Battlegrounds/Triple_Reward_(What_Are_the_Odds%3F)` | 887357 | 2026-01-17 | 渲染文本 "**Discover** a minion from **Tier 0**."（见下方订正） |
| `https://hearthstone.wiki.gg/wiki/Battlegrounds/Tavern_Tier` | 762299 | 2023-10-07 | 通用升级/展示规则（下文引用） |
| `https://hearthstone.wiki.gg/wiki/Battlegrounds/Tavern_spell` | 916040 | 2026-07-15 | 酒馆法术的 Tier 语义（下文引用） |

**订正（上文的 Q4b 误读）:** wiki 与 HearthstoneJSON 显示 token
`BG27_Anomaly_101t` 文本为 "Discover a minion from **Tier 0**"，但本地
`hsdata/CardDefs.xml`（dbfId 103188）原文是
`"<b>Discover</b> a minion\nfrom <b>Tier @</b>."` —— `@` 是**动态值占位
符**（同族先例: `BG27_Anomaly_302t` "Gain @ Gold."），渲染器把未解析的
`@` 显示为 0。该 `@` 的取值由异常卡自身第二句定义（"a minion of **your
Tier**"），故 Q4 的"Tier 0"不是数值证据。

## Q1. 存在档集合 + 起手档

- **存在档集合 — FOUND（卡面 + 16 语言）**: `{1,3,5}` / `{2,4,6}`。
  实现: `game._tavern_tier_ladder = (1,3,5)` / `(2,4,6)`。
- **起手档 101 = T1 — wiki silent；自然语言解读**: 标准起手即 T1
  （wiki Tavern Tier revid 762299: "Taverns start at tier 1"），而 T1 在
  101 中存在 → 起手 T1（引擎默认值，on_bind 显式写入）。
  被否决的替代: "起手 T3/T5"（跳档）——卡面无 "Start at Tavern Tier N"；
  对照: Finicky Hourglass 明确写 "Start at Tavern Tier 2."，Blizzard 在
  需要非常规起手时会明说。
- **起手档 102 = T2 — wiki silent；自然语言解读（含项目内先例）**:
  T1 **不存在** → 玩家不能处于非存在档，起手 = 最低存在档 2。
  同规则先例: `BG27_Anomaly_100` Big League（"Only Tavern Tiers 3, 4, 5,
  and 6 exist."，wiki revid 805249）在引擎中即起始 T3（
  `batch_anomalies3.BigLeagueAnomaly`）；Little League 的 docstring 亦
  记录"起始档 = 最低存在档"（T1 存在 → 起始 T1）。
  被否决的替代: 起手 T1 再跳到 T2——起手处于"不存在"的档位，且首个
  酒馆在 T1 无任何存在档随从可展示（空馆）。

## Q2. 升级语义

- **落点 — wiki silent；自然语言解读**: "next tier" 在存在档集合上取
  **严格高一档的最小存在档**（101: 1→3→5；102: 2→4→6），末档不可再升
  （T6/T7 在 101 中不存在，T7 在 102 中不存在）。实现:
  `Game._next_existing_tier`；`upgrade_tavern` 与 `upgrade_tavern_free`
  同一落点函数 → 他卡 "Unlock Tier 7"（`max_tavern_tier=7`）不改变
  存在档集合。
- **费用 — 按升级步数计价（wiki 通用规则，逐字引用）**:
  > "Upgrading starts at 5 Coins, and each upgrade costs more than the
  > last. However, at the start of each round, the cost of upgrading
  > reduces by 1."

  — `https://hearthstone.wiki.gg/wiki/Battlegrounds/Tavern_Tier`，revid
  **762299**（2023-10-07）。

  首次升级 = 5 金（"starts at 5 Coins"），第 k 次升级用标准序列第 k 档
  基价 → 101: 1→3 付 5，之后基价 = `BASE_UPGRADE_COSTS[3] = 7`；
  102: 2→4 付 5，之后基价 7。实现: `Game._upgrade_cost_after`
  （`BASE_UPGRADE_COSTS[2 + 阶梯下标]`——标准阶梯下与旧式
  `BASE_UPGRADE_COSTS[new_tier + 1]` 恒等，**无新数值表**）。
  **被否决**: 目标档计价（1→3 付 T3 的 7 金）——与 "starts at 5 Coins"
  冲突（该读法下首次升级 = 7），且 "each **upgrade** costs more than the
  last" 按**升级次数**而非目标档号递进。回合衰减（每回合 −1，下限 0）
  沿用引擎既有机制，卡面未改。
- **展示位数量 — moot**: wiki 通用规则按档号递增（"starts at 3 and is
  increased by 1 at tiers 2, 4 and 6"），引擎 `C.TAVERN_OFFERS` 即按
  Tier 号取键；101/102 不改变该表（T1=3 / T3=4 / T5=5；T2=4 / T4=5 /
  T6=6）。

## Q3. 展示/发现档位

- **随从 — wiki silent（针对本异变）；自然语言解读 + 通用规则**:
  > "All minions that are at or below your Tavern Tier level are
  > available to be offered to you in Bob's Tavern, with the minions
  > being randomly selected from the shared pool."

  — Tavern Tier, revid 762299。存在档覆写后 = `[下限, 本人档] ∩ 存在档
  集合`（101 在 T3 → {1,3}；102 在 T4 → {2,4}）。实现:
  `Game._ladder_tier_filter` → `MinionPool.candidates/draw_tavern(tiers=)`
  （同时覆盖 Ice Block 式 per-slot 白名单、Innkeeper's Stein 额外档位、
  关键词位、种族保证位——它们共用同一 `draw_tavern`）。
- **酒馆法术 — wiki 有通用权威，本异变按同一"存在"语义**:
  > "Like minions, Tavern spells have Tiers, and can only be found in
  > the Tavern once that Tier has been reached."
  > "Each time the player Refreshes the Tavern, it will include a Tavern
  > spell of their Tier or lower on top of the normal number of minion
  > offerings for their Tier."

  — `https://hearthstone.wiki.gg/wiki/Battlegrounds/Tavern_spell`，revid
  **916040**（2026-07-15）。故酒馆法术展示同样受存在档白名单约束
  （`SpellPool.draw_tavern(tiers=)`；101 在 T3 → {1,3}）。
  注: 既有 Big League/Little League **未**对法术施加白名单（仅随从
  `_tavern_min_tier`/`max_tavern_tier`），本批未改动那两张，属遗留口径
  （见"边界"）。
- **Discover / "Tier N or lower" — wiki silent；自然语言解读**: 非存在档
  随从在当局**不存在**，故 `actions/discover._pool_candidates` 与
  `Discover` 的显式候选路径都排除非存在档（token `tech_level<=0` 不受
  约束——token 不是酒馆档位随从）。实现: `game._tavern_tier_ladder` 过滤。

## Q4. 三连奖励档 = 本人当前档（**卡面权威**）

- [AUTHORITY: 卡面 + 数据 + URL] 两张异变第二句:
  > "Triple Rewards **Discover** a minion of your Tier."
  （`https://hearthstone.wiki.gg/wiki/Battlegrounds/What_Are_the_Odds%3F`
  revid 836162 / `.../How_to_Even%3F%3F` revid 805286；
  `https://hearthstone.blizzard.com/en-us/news/23989479/27-6-patch-notes`）
- [AUTHORITY: 卡面数据 `hsdata/CardDefs.xml` dbfId 103188] token 文本
  `"<b>Discover</b> a minion\nfrom <b>Tier @</b>."` = 参数化档位（`@` 由
  本异变的 "your Tier" 赋值）。实现: `_grant_triple_reward` 在
  `game._triple_reward_of_own_tier` 时取 `hero.tavern_tier`（缺省口径
  `min(全并随从档 + 1, max_tavern_tier)` 不变）。
- **快照时序 — moot**: 引擎在"三连成立"当刻同步发奖
  （`check_for_triple` → `_grant_triple_reward`，或金色打出路径），档位
  在两者之间不可能变化，无需冻结/快照语义。
- **102 无专属 token（Q4e）— 不影响**: 两句逐字相同，同一实现覆盖两张;
  数据缺失只说明 102 复用共享/内联文案。

## Q5. 他卡交互

- **T7 / Secrets of Norgannon — wiki silent；自然语言解读**: 101 的 T6/T7
  与 102 的 T7 均"不存在" → 阶梯末档即上限（即使他卡
  `game.max_tavern_tier = 7`，如任务奖励 R010 "Unlock Tier 7"）。
  且一局只有一个异变，101/102 与 Secrets of Norgannon 不可能同局。
- **"Tier N or lower" 奖励**: 见 Q3 的 Discover 裁定（非存在档排除）。

## 边界（显式记录，未实现的部分与理由）

1. **脚本级"随机/发现酒馆法术"候选已收口（2026-09-02 对抗验证
   must-fix 修复）**: 原先约 25 处脚本自建 `db.pool_spells()` 候选不做
   存在档过滤（101 的 T3 曾给出含 T2 的选项——Book of Medivh
   `BG30_MagicItem_420` 实测 `[3,2,1]`）。现统一经
   `Game.tavern_spell_candidates(min_tier=None, max_tier=None,
   pool_aware=True)`（`hsrl2/game.py`；内部施加 `_ladder_tier_filter`）
   ——`min_tier/max_tier=None` = 该侧不设区间（沿用调用点既有口径，
   标准局行为逐位不变），"≤ 酒馆等级"显式传 `max_tier=hero.tavern_tier`，
   "恰好 Tier N" 传 min=max=N。**已改路径**:
   `batch_spells4.DiscoverTavernSpellOfTier`（联动 Book of Medivh
   `batch_trinkets11` / Rising Current `batch_anomalies3`）、
   `batch_activate.CleverCastawayScript`、`batch_hero_actives.
   HollidaeScript` + `ArcaneAlterationScript`、`batch_hero_actives2.
   YoggScript`、`batch_hero_rewards_final._tavern_spell_candidates`、
   `batch_trinkets3._random_spell_from_pool`、
   `batch_trinkets7/8/12._random_tavern_spell`、
   `batch_trinkets21._tavern_spell_candidates`（只读
   `pool_aware=False`）、`batch_unfreeze.CageyConjurerScript`、
   `batch_unlock_final._random_tavern_spell`、
   `batch_misc.RodeoPerformerScript`、
   `batch_quest_rewards/2._random_pool_spell`、
   `batch_eot_sot._gain_random_pool_spells`、引擎
   `game._gift_mystic_essence`。
   **仍为可达例外（显式记录）**:
   (a) 固定卡 id 集合（不受档位影响、非"池内随机酒馆法术"）:
   `bloodgem.random_bounty_card_id` / `batch_trinkets7._grant_bounties` /
   `batch_deathrattle2._bounty_ids` / `CHOOSE_ONE_SPELL_IDS` 族
   （batch_rally / batch_rally2 / batch_trinkets20 / batch_unfreeze）;
   (b) 特定 card_id 的池占用判断（batch_deathrattle / batch_avenge_misc /
   batch_trinkets6 / batch_trinkets8 / batch_hero_actives2 的"手中这张
   法术"）;
   (c) DEFERRED 未实现路径（batch_trinkets27 Marine Signet 等）——
   不注册即无运行时路径。
   注: `pool_spells()` 中确有 T7 条目（4 张）——无区间调用点
   （min=max=None）在标准局保持"全池"（含 T7）语义不变；101/102 下
   经白名单收敛到存在档。
2. **"高一档"算术 — 白名单"移除"而非重映射（含 Toki 技能）**:
   例如 Innkeeper's Stein `TAVERN_EXTRA_TIER = tavern_tier + 1`
   （101 在 T1 时 = 2）。白名单使其**抽不到**（该位落空），而非改成
   "下一存在档 T3"。2026-09-02 对抗验证 must-fix 将 Toki
   `TB_BaconShop_HP_028`（"Include two minions from a Tier higher than
   yours"）纳入同一裁定: `tier+1` 先经 `_ladder_tier_filter`，
   非存在档 → 注入落空，且**只移出实际可注入的数量**（不缩小酒馆——
   旧实现"移出 2 只、注入 0 只"会让酒馆小于正常刷新）。被否决的替代:
   "下一存在档"（101 在 T1 → T3）——卡面无跳档措辞，且与
   `test_extra_tier_slot_respects_ladder` 的 Stein 裁定相左（"落空"
   方向永不产出非存在档）。
3. **Big League / Little League 的法术展示**未加白名单（既有注册口径
   保持不动；本批不改他批）。
4. **卡池可用性**: 两张自 Patch 31.6.0.216423 起已移出异变池
   （wiki revid 836162 / 805286 "This anomaly is currently **not**
   available in the pool."）。引擎注册历史卡不受影响（同库其他已移出
   异变同样注册）。

## 实现清单（本次改动）

- `hsrl2/game.py`: `_tavern_tier_ladder` / `_triple_reward_of_own_tier`
  状态 + `_ladder_tier_filter` / `_next_existing_tier` /
  `_upgrade_cost_after` 三个读取点 + `refresh_tavern`（随从+法术）、
  `upgrade_tavern`、`upgrade_tavern_free`、`_grant_triple_reward` 接线。
- `hsrl2/pools.py`: `MinionPool.candidates/draw_tavern(tiers=)`、
  `SpellPool.draw_tavern(tiers=)`。
- `hsrl2/actions/discover.py`: `_pool_candidates` 与显式候选路径的存在档
  过滤。
- `hsrl2/scripts/batches/batch_anomalies3.py`: 注册 2 张 + 台账订正。
- `hsrl2/scripts/batches/batch_anomalies_final.py`: DEFERRED 台账 F 组
  撤出 2 张（37 → 35）。
- `hsrl2/tests/test_batch_anomalies3.py` / `test_batch_anomalies_final.py`:
  注册/DEFERRED 台账同步 + `TestTierLadderAnomalies` 9 条真实路径测试。

## 实现清单（2026-09-02 对抗验证 must-fix 收口）

- `hsrl2/game.py`: 新增 `Game.tavern_spell_candidates(min_tier, max_tier,
  pool_aware)`（`_ladder_tier_filter` 收口脚本层酒馆法术候选）;
  `_gift_mystic_essence` 改走该入口。
- `hsrl2/scripts/batches/batch_hero_actives.py`:
  `_weighted_exact_tier_draws(..., tiers=)` + `TokiScript` 注入档
  `tier+1` 经白名单（非存在档落空、不缩小酒馆）。
- 酒馆法术候选改走统一入口的脚本（17 文件）: `batch_spells4`、
  `batch_activate`、`batch_hero_actives`、`batch_hero_actives2`、
  `batch_hero_rewards_final`、`batch_trinkets3/7/8/11/12/14/21`、
  `batch_unfreeze`、`batch_unlock_final`、`batch_misc`、
  `batch_quest_rewards`、`batch_quest_rewards2`、`batch_eot_sot`。
- 测试（真实路径 + 变异探针）:
  `test_batch_hero_actives.TestToki`（101 T1 / 102 T2 / 101 T3 +
  标准局正对照）、`test_batch_trinkets11.TestBookOfMedivh`（101 T3 /
  102 T4 + 标准局正对照）。
