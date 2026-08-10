# E05 Pradeep Scanner Producer Contract

**Status:** `FROZEN`
**Contract ID:** `E05_PRADEEP_SCANNER_PRODUCER`
**Producer version:** `1.0.0`
**Scope:** selection, scanner, and research producer only

## 1. Authority and boundary

E05 produces source-attributed Pradeep/Stockbee selection decisions only. It is not authority for broker actions, orders, portfolio construction, position sizing, stops, exits, account-risk calibration, or trade execution. Those matters may be described by the sources, but are outside this producer's output authority. [risk_control.md; setup_design.md; swing_trading_process.md]

E05 is independent of E04 Traditional selection logic. It neither consumes Traditional rules as Pradeep rules nor combines their results into a score, rank, or selection standard. A company can carry an independent `PRADEEP` selection alongside another system's selection under the external E02 envelope.

This candidate is constrained by the recovered external **E02 Unified Candidate Contract v1.0.0**. The exact external artifact hashes are:

- schema: `d7f47de35c0a61f50be37254ce24dbfa8a8d591acf272221d8bf7994ee56f310`
- policy: `6d58383c781ee3a54de3128dc0fd19bc16cafe69d3677259f8dda2adcd215de7`
- test vectors: `cb28c4ab589d786dba5b0653838083b0e582cd952e105ec3f7f87e520b8e47ee`

The external E02 artifacts define the envelope; this document does not reproduce or replace their schema, policy, or test vectors.

## 2. Supported producer profiles

E05 supports exactly these `setup_id` values:

- `stockbee_momentum_burst`
- `stockbee_episodic_pivot`

`Simple 9` is `STOPPED/UNDEFINED`. It must not be created, inferred, renamed, or emitted as a setup, rule, scanner, or selection. [ep_9_million.md]

`EP 9 Million` is a variation within `stockbee_episodic_pivot` only. It is not `Simple 9`, not a third E05 profile, and not a standalone automatic selection predicate. [ep_9_million.md]

MAGNA/MAGNA53 is source-supported Episodic Pivot candidate-quality and catalyst context only. It is not a third E05 profile and its individual characteristics are not automatically sufficient to select a candidate. [magna.md]

## 3. External E02 selection binding

For every actual E05 selection, emit one selection record in the exact external E02 v1.0.0 envelope with:

- `selection_system` exactly `PRADEEP`;
- `producer_version` set to this producer version;
- `scanner_id` set to `e05_pradeep_scanner`;
- `setup_id` set to one of the two supported values;
- unique `selection_id`, source-attributed `matched_rules`, `failed_rules`, `unknown_rules`, and `evidence_refs`;
- populated `detected_at` and `data_as_of` values; and
- `system_rank: null`.

An actual selected candidate has at least one matched rule and at least one evidence reference. Rule identifiers do not overlap among `matched_rules`, `failed_rules`, and `unknown_rules`. `failed_rules` records only a source-defined condition that was evaluated and not met; unavailable, ambiguous, or source-undefined conditions remain in `unknown_rules`.

`system_rank` remains `null` unless a source-defined, mechanically reproducible rank within the Pradeep system is proven. E05 creates no scanner score, no Pradeep rank without that proof, and no combined, overall, or cross-system score.

Evidence references identify the applicable inventory-bound primary authority page and, where relevant, its linked source note or source-binding ID. Values used for selection retain their source scope and qualifier in the rule/evidence description.

## 4. Momentum Burst production rules

For `stockbee_momentum_burst`, the primary source defines the discovery event as the **first day of range expansion**; daily range-expansion scanning is its primary entry-finding mechanism. A source-backed match may therefore record `MB_FIRST_DAY_RANGE_EXPANSION` when the first-day event is evidenced. [momentum_burst.md; entry_mechanics.md]

The sources state that volume expansion often accompanies range expansion and describe the first day as a breakout with above-average volume, but they provide no universal numeric calculation for either range expansion or above-average volume. Those numeric thresholds remain `UNDEFINED`; E05 must not calibrate them. [momentum_burst.md; entry_mechanics.md]

The cited `3–10 day` burst window, `8–40%` moves, `5–20%` per-move profit potential, rare `8–10 day` runs, and `200 to 1,000 or more` yearly-trade description are source observations or contextual expectations. They are not universal E05 acceptance gates, rankings, or score inputs. [momentum_burst.md]

The source advises against entering on the third or fifth day; this describes the source's setup timing and does not authorize E05 to infer an unprovided numeric scanner threshold. [entry_mechanics.md]

## 5. Episodic Pivot production rules

For `stockbee_episodic_pivot`, a source-backed selection concerns a post-earnings or other catalyst-driven change in attention, assessed in context rather than as a chart pattern alone. The primary source identifies a genuinely surprising earnings report and a big gap up with huge pre-market volume as the two game-changing-catalyst signals. [episodic_pivots.md]

Within the source's daily EP discovery process, pre-market volume **above 50k shares** is an explicit numeric discovery condition alongside neglect, a significant first or second earnings surprise, and a gap up. E05 may record `EP_PREMARKET_VOLUME_GT_50000_SHARES` only with evidence for that scoped condition; it is not a universal predicate, a guarantee, a rank, or a score. The source separately cautions that sub-50k volume is not meaningful in that context and that 50k volume for a large-cap is similarly insignificant. [episodic_pivots.md]

The source's `1–12` typical annual opportunities, `100–500%` weeks-or-months move description, and `15–20%` account-growth objective remain source descriptions, not E05 selection gates or calibration. [episodic_pivots.md]

### 5.1 EP 9 Million qualifier preservation

EP 9 Million records **roughly 9–10 million shares traded** as an empirical discovery/catalyst proxy for many common stocks in the modern market. It can surface potential EP-like candidates only after contextual evaluation of meaningful change in attention/catalyst. It does not guarantee an EP, a successful trade, or an automatic selection. Its approximate `roughly 9–10 million` qualifier must be retained; E05 must not convert it into an exact universal threshold. [ep_9_million.md; p1_video_semantic_enrichment_notes.md]

### 5.2 MAGNA/MAGNA53 qualifier preservation

MAGNA/MAGNA53 contributes only as evidence-bearing Episodic Pivot context: massive earnings/sales acceleration or surprise, earnings-day gap, neglect, and sales acceleration. `5` means short-interest ratio/days short **greater than about five** and is useful but not essential; `3` means **three or more** analyst upgrades/price-target raises and is useful rather than mandatory. [magna.md]

The source examples of acceleration **above roughly 100%** on meaningful bases, two consecutive quarters **above roughly 29%** with non-trivial annual sales, sales acceleration **around 25%+** as preferred, and an earnings-day gap **at least roughly 4%** with meaningful volume are approximate/supporting candidate-discovery evidence. They retain those qualifiers, are never universal exact E05 gates, and do not become a standalone MAGNA selection profile. [magna.md]

## 6. Source-undefined and excluded production behavior

Do not infer a numeric threshold merely because an input can be computed. Any source-undefined threshold remains `UNDEFINED` and, if relevant to a decision, is reported as an unknown rule rather than silently hardened, scored, or treated as generic qualitative context.

E05 does not ingest Stockbee 50 or Market Monitor daily data, paid/login-gated material, or unbound source material. It does not use network retrieval as producer authority. [ep_9_million.md; magna.md; watchlist_building.md]

Candidate selection preserves the cited source's distinctions: exact numeric discovery conditions are recorded only in their stated setup scope; approximate/supporting figures remain approximate/supporting evidence; and all source qualifiers travel with the rule/evidence reference.

## 7. Primary authority references

The compact references in this candidate refer only to inventory-bound E05B primary authority:

- `authority_pages/setups/momentum_burst.md` and `source_notes/blog_2014_08_005_notes.md`
- `authority_pages/concepts/entry_mechanics.md` and `source_notes/blog_2014_09_002_notes.md`
- `authority_pages/setups/episodic_pivots.md` and `source_notes/blog_2014_09_004_notes.md`
- `authority_pages/setups/ep_9_million.md` and `source_notes/p1_video_semantic_enrichment_notes.md`
- `authority_pages/setups/magna.md` and source bindings `p9e_83522827cec8`, `p9e_06458387fe86`
- `authority_pages/concepts/risk_control.md`, `authority_pages/concepts/setup_design.md`, `authority_pages/concepts/anticipation.md`, `authority_pages/process/watchlist_building.md`, and `authority_pages/process/swing_trading_process.md`

This document is the frozen E05 contract. It does not authorize E06 work.
