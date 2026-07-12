# Pradeep/Stockbee Trading Rules Reference

> **Phase 10A — Documentation only.** Extracted from Phase 9D curation (15 KB entries, 7 rules).
> Design reference for future scanner heuristics and structured rules integration.
> Phase 10B.1 prompt grounding uses profile-level snippets from `default_config.py`, not
> the individual rules documented here. Scanner heuristics, structured rules parsing,
> and the full rules pipeline are NOT implemented.

Source: `ResearchData/pradeep_stockbee/curated/kb_seed_entries.jsonl`

---

## Rule Index

| # | Rule ID | Rule Summary | Setup | Concept Tags |
|---|---------|-------------|-------|---------------|
| 1 | rule_buy_range_expansion_day | Buy on the first day of range expansion. Scan for range expansion daily. Entering on day 3 or 5 is low-probability. Range expansion day attracts breakout traders, momentum players, and quants — their participation drives continuation. | MB | momentum_burst, entry, breakout_mechanics, volume_analysis |
| 2 | rule_momentum_burst_frequency | Execute 200–1,000 momentum burst trades per year. Compounding small gains (5–20% each) produces returns. Exit during the explosive phase — after 3–10 days, stocks give back burst gains and may not burst again for weeks or months. | MB | momentum_burst, swing_trading_process, risk_management |
| 3 | rule_daily_catalyst_process | Primary pre-market focus: find big game-changing earnings or catalyst stocks. Look for stocks with neglect, significant first or second earnings surprise, pre-market volume above 50k shares, and gap up. Best EPs occur when the surprise lands at the start of a new market rally. | EP | catalyst, episodic_pivot, swing_trading_process, watchlist_building |
| 4 | rule_ep_position_sizing | 3–5 big 50%+ movers post EPs can make your year — if you risk sufficiently on them. Target a position that delivers 15–20% account growth in one trade. EP trades are concentrated, infrequent, and account-moving. | EP | episodic_pivot, position_sizing, risk_management |
| 5 | rule_hunt_detailed_setups | New or struggling traders: hunt for detailed setup ideas and templates, not vague strategies or indicators. A complete setup covers entry, exit, position sizing, stop placement, expected profit, trade frequency, and market conditions. Master one setup before adding others. | General | swing_trading_process, entry, exit, risk_control |
| 6 | rule_low_risk_entry_mechanics | Better entry provides three advantages: (1) easier to withstand shakeouts, (2) lower risk with closer stops, (3) higher reward if momentum continues — and you can risk more with closer stops. Practice identifying 500 swing start days before trading real capital. | General | entry, risk_control, risk_management |
| 7 | rule_entry_patience | In a universe of 10,000 stocks, the question is whether you have the patience to wait and take only the best setups. Never enter on the 3rd or 5th day of a move. Both beginners and experienced traders struggle with this — do the right thing and wait for day one. | General | entry, risk_management, swing_trading_process |

### Setup Legend
- **MB** — Momentum Burst
- **EP** — Episodic Pivot
- **General** — Applies to all setups

---

## Rule → Scanner Mapping (Design Only)

| Rule | Scanner Signal | Phase |
|------|---------------|-------|
| rule_buy_range_expansion_day | Range expansion + volume scan | 10B |
| rule_daily_catalyst_process | Pre-market gap-up + volume > 50k | 10B |
| rule_ep_position_sizing | Position size calculator (account % target) | 10B |
| rule_low_risk_entry_mechanics | Entry quality score (day count, stop distance) | 10B+ |
| rule_entry_patience | Entry timing validator (reject day 3+ entries) | 10B+ |
| rule_hunt_detailed_setups | Setup completeness checklist gate | 10B+ |
| rule_momentum_burst_frequency | Trade frequency tracker / exposure monitor | 10B+ |

---

## Coverage Gaps (4-Post MVP)

| Missing Area | Impact | Remedy |
|-------------|--------|--------|
| Anticipation setups | No anticipation-specific rules | Expand crawl (Phase 9C.2) |
| Short-selling / bearish setups | No short-side rules | Expand crawl |
| Market timing / breadth | No market-context rules beyond "new rally" mention | Expand crawl |
| Position context (existing holdings) | No portfolio-overlap rules | Expand crawl |
| Advanced EP variations (biotech, tech) | Shallow coverage | Expand crawl |

These gaps are acceptable for MVP validation (Phase 10A/10B). Full coverage requires corpus expansion via a separately approved Phase 9C.Full plan — after Phase 10B proves the integration path is valuable.

---

## Implementation Status

- **Phase 10B.1 (implemented):** Prompt grounding uses profile-level snippets (see `default_config.py` `STOCKBEE_PROMPT_GROUNDING`) — NOT the individual rules listed above. Grounding is wired into market analyst, research manager, and trader nodes.
- **Phase 10B+ (not implemented):** Structured rules parsing, scanner heuristics wiring, risk manager prompt grounding, full rules pipeline. Individual rule items above remain design reference only.
