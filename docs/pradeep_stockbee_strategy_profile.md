# Pradeep/Stockbee Strategy Profiles

> **Phase 10B.1 — Partially implemented.** Prompt grounding for `stockbee_momentum_burst`
> and `stockbee_episodic_pivot` is now wired into the market analyst, research manager,
> and trader nodes (via ContextVar `get_active_prompt_grounding()`). Scanner heuristics,
> KB-file access, structured rules integration, retrieval, vector DB, embeddings,
> and the full prompt-grounding pipeline remain future work (Phase 10B+). Phase 10B.2B
> provider-backed sniff is NOT approved and NOT run.

Source knowledge base: `ResearchData/pradeep_stockbee/`
(Phase 9C.1 crawl, 9D curation, 9E wiki build — 4 curated posts, 15 KB entries)

---

## Profile: stockbee_momentum_burst

**Source:** `wiki/setups/momentum_burst.md`
**KB entries:** concept_momentum_burst_sequence, concept_momentum_burst_duration, rule_buy_range_expansion_day, rule_momentum_burst_frequency

### Summary

Short-term momentum burst swing trading. Entry on range expansion day (wide range + high volume after 4–5 days of weakness/flat action). 3–10 day hold period capturing 5–20% per trade. 200–1,000 trades/year compounding small gains. Mechanical, pattern-and-probability based.

### Scanner Heuristics (Design Only — Not Implemented)

- **Range expansion scan:** Daily scan across all stocks for range expansion (today's range > recent average range) with volume confirmation
- **Prior weakness filter:** Stock must have shown 4–5 days of weakness or flat action before the expansion day
- **Breakout confirmation:** Price breaking above recent resistance or 20-day high
- **Volume threshold:** Volume on expansion day > 1.5× 20-day average volume
- **Float preference:** Lower-priced and low-float stocks produce larger bursts

### Risk Rules (Design Only — Not Implemented)

- **Stop placement:** Stop at range expansion day low or prior day close (whichever is tighter)
- **Cut losses:** Ruthlessly cut if trade does not follow through immediately after entry
- **Exit signal:** Exit when momentum exhausts — do not wait for reversal. After 3–10 days, stocks typically give back all burst gains
- **Position sizing:** Small, uniform position sizes. Risk per trade is consistent; edge comes from frequency and compounding, not bet sizing

### Analyst Prompt Focus

Market Analyst evaluates: range expansion quality, volume confirmation, prior weakness pattern, sector context, and 3–10 day upside potential. Risk Manager evaluates: stop placement tightness, entry timeliness (day 1 vs day 3+), and shakeout resilience. Trader evaluates: exit timing (not too early, not after reversal).

---

## Profile: stockbee_episodic_pivot

**Source:** `wiki/setups/episodic_pivots.md`
**KB entries:** concept_episodic_pivot_pattern, concept_game_changing_catalyst, rule_daily_catalyst_process, rule_ep_position_sizing

### Summary

Post-earnings catalyst breakout on neglected stocks. A genuinely surprising earnings report changes Wall Street perception, triggering a buying frenzy. Stocks move 100–500%+ in weeks or months. 1–12 opportunities per year. Concentrated, account-moving position sizing. 14 such trades delivered 80% of Pradeep's profits over 14 years.

### Scanner Heuristics (Design Only — Not Implemented)

- **Pre-market gap-up scan:** Stocks gapping up >4% in pre-market after earnings
- **Volume threshold:** Pre-market volume >50,000 shares (sub-50k is not meaningful — market hasn't noticed)
- **Neglect filter:** Stock must show months or years of neglect: low prior volume, flat or declining price, no recent analyst coverage surges
- **Surprise magnitude:** Actual EPS or revenue significantly above consensus estimates
- **Sector check:** Earnings EPs are most common. Biotech (drug trial data) and tech (sector momentum) EPs also valid but less frequent
- **Rally context:** Best EPs occur when the surprise lands at the beginning of a new market rally

### Risk Rules (Design Only — Not Implemented)

- **Position sizing:** Risk big enough for 15–20% account growth in a single trade. This is the opposite of momentum burst sizing: few large bets, not many small ones
- **Stop placement:** Stop at breakout day low. Trail stops upward as stock moves
- **Exit signal:** Exit when stock hits pre-determined target or stop. Do not hold through a reversal expecting a second leg
- **Selectivity:** During peak earnings season, most reports produce day trades or short swings — not real game changers. Be extremely selective

### Analyst Prompt Focus

Market Analyst evaluates: earnings surprise quality, prior neglect (months/years, not days), pre-market volume magnitude, and rally context. Fundamentals Analyst evaluates: whether the earnings surprise is genuinely perception-changing (not just a beat on low expectations). Risk Manager evaluates: position sizing adequacy for account-moving impact, stop placement, and concentration risk.

---

## Profile Selection Guidance

| Factor | Momentum Burst | Episodic Pivot |
|--------|---------------|----------------|
| Trade frequency | 200–1,000/year | 1–12/year |
| Per-trade return | 5–20% | 50–500%+ |
| Account impact | Steady compounding | Concentrated, step-change |
| Drawdown risk | Very low per trade | Higher per trade |
| Time commitment | Daily scanning, active management | Pre-market focus, episodic monitoring |
| Best for | Consistent income, small accounts | Account growth, patient traders |
| Both can coexist | Yes — allocate capital to both | Yes — different parts of portfolio |

---

## Implementation Status

- **Phase 10B.1 (implemented):** Prompt grounding wired for `stockbee_momentum_burst` and `stockbee_episodic_pivot`. Grounding is injected into market analyst, research manager, and trader node prompts when a known Stockbee profile is active.
- **Phase 10B.2A (passed):** No-provider prompt-capture sniff confirmed grounding reaches all three agents.
- **Phase 10B.2B (NOT approved, NOT run):** Provider-backed sniff.
- **Not implemented:** Scanner heuristics, KB-file integration, structured rules pipeline, full validation, provider-backed sniff.
