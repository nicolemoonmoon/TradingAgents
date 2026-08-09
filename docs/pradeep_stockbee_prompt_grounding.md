# Pradeep/Stockbee Prompt Grounding Reference

> **Phase 10B.1 — Frozen-KB retrieval implementation.**
>
> TradingAgents keeps the existing `strategy_profile` feature gate and the existing three prompt-injection points: **Market Analyst → Research Manager → Trader**. The former hard-coded methodology strings are no longer the source of truth.

## Runtime knowledge authority

Runtime Stockbee grounding is resolved locally from `~/ResearchData/pradeep_stockbee` through the frozen authority chain:

1. `manifests/batch6_phase9_v1_closure.json`
2. `manifests/batch6_phase9_v1_inventory.json`
3. selected inventory-bound `wiki/` pages
4. linked `wiki/source_notes/` files for original public source URLs

A supported profile fails closed if the closure is not frozen, the inventory hash drifts, a selected file is missing/symlinked, or a selected file no longer matches the frozen inventory. Unknown profiles and `None` preserve the previous behavior: no Stockbee grounding is injected.

## Supported profiles

`stockbee_momentum_burst` uses Momentum Burst, Entry Mechanics, Risk Control, Swing Trading Process, and Watchlist Building.

`stockbee_episodic_pivot` uses Episodic Pivots, MAGNA/MAGNA53, EP 9 Million, Anticipation, Risk Control, Setup Design, and Watchlist Building.

`EP 9 Million` is explicitly separate from the unresolved `Simple 9` target.

## Grounding envelope

The deterministic grounding text includes the `strategy_profile`, frozen KB `knowledge_inventory_sha256`, selected `context_ids`, recoverable original public `source_urls`, and bounded wiki methodology text. The complete grounding string is capped at **12,000 characters**.

Current market/fundamental/news tools remain the source of truth for live facts. The Pradeep KB contributes methodology context only.

## Explicit runtime exclusions

The retrieval path does **not** read `raw/`, the 6,628-comment processed corpus, the 22-video transcript corpus, Stockbee 50 daily dynamic data, Market Monitor/MM daily dynamic data, or paid/login-gated materials. It performs no network request, embedding, vector-database lookup, provider call, server/worker action, broker/order action, or `.env` read.

## Existing injection seam retained

`api/main.py::_build_graph()` still calls `get_stockbee_grounding()` and writes the returned string to the existing ContextVar/config path. The Market Analyst, Research Manager, and Trader files remain byte-identical in this phase.

Whether additional agents need direct methodology grounding is deferred to the Agent Grounding Eval rather than assumed in advance.

## Simple 9 policy

Active search is stopped. Runtime retrieval must not create or infer a `Simple 9` definition. The gap is reopened only under the owner-approved conditions recorded in the frozen Phase 9 closure.

## Phase 10B.1 root-source repair

Runtime now binds the frozen Phase 9 v1 inventory SHA `e300b7c54e52b79dec0a7ce31e76f6e376bb18d08c25c93bf43272a6af067126` as an explicit trust anchor; a rewritten closure cannot bless a rewritten inventory. The owner Simple 9 reopen policy and permanent data exclusions are also checked at retrieval time.

The 12,000-character body budget is divided across every selected context; oversized pages retain both their definition/front and later enrichment/tail, so a listed context ID cannot silently contribute zero prompt text.

Implementation verification no longer guesses a dependency-bearing system Python. Changed retrieval behavior is verified with a Python>=3.10 standard-library-only synthetic KB suite, while the byte-identical API/Market Analyst/Research Manager/Trader seam is verified by SHA-256 and AST. A complete project runtime is provisioned explicitly before Agent Grounding Eval.
