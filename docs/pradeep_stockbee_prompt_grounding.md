# Pradeep/Stockbee Prompt Grounding Reference

> **Phase 10B.1 — Implemented (prompt-grounding only).** At runtime, `get_active_prompt_grounding()`
> returns a compact profile-level string from `STOCKBEE_PROMPT_GROUNDING` in
> `tradingagents/default_config.py` — one paragraph each for `stockbee_momentum_burst`
> and `stockbee_episodic_pivot`. Three agent nodes prepend this text: market analyst,
> research manager, and trader.
>
> **The role-specific snippets below are design/reference expansions.** They are
> longer, richer expansions of the profile-level grounding and are NOT injected verbatim
> at runtime. See `tradingagents/default_config.py` `STOCKBEE_PROMPT_GROUNDING` for the
> exact runtime text.
>
> Scanner heuristics, structured rules integration, retrieval, vector DB, embeddings,
> full strategy integration, and provider-backed validation are NOT implemented.
> Phase 10B.2B provider-backed sniff is NOT approved and NOT run.

Source knowledge base: `ResearchData/pradeep_stockbee/wiki/`
(4 wiki pages: setups/momentum_burst, setups/episodic_pivots, concepts/setup_design, concepts/entry_mechanics)

---

## Market Analyst — Momentum Burst Evaluation

**[Reference expansion — not injected verbatim; runtime uses STOCKBEE_PROMPT_GROUNDING["stockbee_momentum_burst"]]**

```
STOCKBEE MOMENTUM BURST CONTEXT

You are evaluating this stock for a potential Momentum Burst setup.

Key criteria to address:
1. Has the stock shown a range expansion (wide-range, high-volume day)
   after 4-5 days of weakness or flat action?
2. Is today day 1 of the potential swing move?
   Entries on day 3+ are low-probability per Stockbee methodology.
3. Does volume confirm the range expansion?
   Volume should be above 1.5x the 20-day average.
4. What is the 3-10 day upside potential based on recent burst
   magnitudes in this sector and market cap range?
5. Is the stock lower-priced or low-float?
   These produce the largest bursts.
6. Note: you do NOT need to identify a specific catalyst for this
   setup. Momentum bursts are pattern-and-probability based and
   may not have a clear identifiable catalyst.
```

## Market Analyst — Episodic Pivot Evaluation

**[Reference expansion — not injected verbatim; runtime uses STOCKBEE_PROMPT_GROUNDING["stockbee_episodic_pivot"]]**

```
STOCKBEE EPISODIC PIVOT CONTEXT

You are evaluating whether this stock's recent earnings report
constitutes a potential Episodic Pivot (EP).

Key criteria to address:
1. How surprising was the earnings report?
   Was actual EPS/revenue significantly above consensus?
2. How neglected was the stock prior to this report?
   Check: months/years of low volume, flat/declining price,
   minimal analyst coverage changes.
3. What was the pre-market reaction?
   Gap-up magnitude and pre-market volume (>50k shares minimum).
4. Is this at the beginning of a new market rally?
   EPs at rally starts produce the largest and longest moves.
5. What is the 100-500%+ upside case?
   Best EPs on low-priced, low-volume, deeply neglected stocks
   have produced 100-500%+ moves in weeks/months (IDSA: 800%
   in 17 days, BOOM: 400% in 10 days).
6. Is this a genuine game-changer or just a beat on low expectations?
   Most earnings reports produce day trades, not EPs.
```

## Risk Manager — Entry Quality Assessment

**[Not yet implemented — Phase 10B+]**

```
STOCKBEE ENTRY QUALITY ASSESSMENT

Assess this proposed entry against Stockbee entry discipline rules:

1. Is the proposed entry on day 1 of the swing move?
   Day 1 entries have the mathematical advantage:
   - Easier to withstand shakeouts
   - Lower risk (stops are closer to entry)
   - Higher reward if momentum continues
   Day 3+ entries are explicitly rejected by Stockbee methodology.

2. What is the nearest structural stop level?
   For Momentum Burst: stop at range expansion day low or prior
   day close. For Episodic Pivot: stop at breakout day low.

3. Can the position withstand a normal shakeout without hitting stop?
   Shakeouts almost always occur after entry.

4. If this is an EP trade: is the position sized for 15-20% account
   growth potential? If not, this is not a properly sized EP trade.
```

## Trader — Position Sizing and Exit Discipline

**[Reference expansion — not injected verbatim; runtime uses STOCKBEE_PROMPT_GROUNDING["stockbee_momentum_burst"] or STOCKBEE_PROMPT_GROUNDING["stockbee_episodic_pivot"]]**

```
STOCKBEE POSITION SIZING AND EXIT DISCIPLINE

Position sizing depends on setup type:

MOMENTUM BURST:
- Size for small, uniform positions (compounding approach)
- Target: 5-20% profit per trade
- Exit: during explosive phase, not after reversal
- Frequency: 200-1000 trades/year
- Cut losses ruthlessly if trade does not follow through immediately

EPISODIC PIVOT:
- Size for concentrated, account-moving positions
- Target: 15-20% account growth per trade
- Exit: at predetermined target or stop — do not hold through reversal
- Frequency: 1-12 opportunities/year
- Only 3-5 big EP wins needed to make a year

GENERAL DISCIPLINE:
- Buy near swing start, sell near swing end
- Never enter on day 3+ of a move — patience is essential
- Practice identifying 500 swing start days before trading real capital
```

## News/Sentiment Analyst — Catalyst Quality

**[Not yet implemented — Phase 10B+]**

```
STOCKBEE CATALYST QUALITY ASSESSMENT

For Episodic Pivot candidates, evaluate catalyst quality:

1. Is the news genuinely perception-changing?
   - A stock up in pre-market on sub-50k volume = market has not noticed
   - A large-cap up on 50k volume = not a real game changer

2. Is the catalyst a first or second earnings surprise?
   Later surprises have diminishing impact — the first big surprise
   after years of neglect produces the largest moves.

3. Is there a sector catalyst or macro tailwind?
   Biotech: drug trial data approvals
   Technology: sector momentum in later bull stages
   Earnings: most common and most accessible EP type

4. What is the neglect profile?
   Years of neglect + first big surprise = maximum EP potential
   Recent attention + small beat = not an EP
```

---

## Implementation Status

- **Phase 10B.1 (implemented):** Static prompt grounding wired into market analyst, research manager, and trader nodes for both `stockbee_momentum_burst` and `stockbee_episodic_pivot`. Prompt-grounding only — the three agent nodes call `get_active_prompt_grounding()` at runtime and prepend the active grounding text to their prompt.
- **Phase 10B.2A (passed):** No-provider prompt-capture sniff verified grounding reaches all three agents.
- **Phase 10B.2B (NOT approved, NOT run):** Provider-backed sniff requires separate Architect sign-off.
- **Not implemented:** Scanner heuristics, structured rules integration, retrieval, vector DB, embeddings, full strategy integration, provider-backed validation. Risk manager and news/sentiment analyst wiring not yet done.
