# TradingAgents L0 System Architecture Freeze v1.0.0

**Status: FROZEN**

This file is the top-level product/system architecture authority after the owner-approved
architecture reconciliation on 2026-08-09.

## Frozen structure

TradingAgents has **three independent selection systems**:

1. **Traditional**
2. **Pradeep**
3. **Technology**

They may share current facts through a Shared Intelligence Plane, but they do **not**
share screening standards or collapse into one cross-system scoring formula.

### Traditional
Traditional selection remains independent from Pradeep. Existing Traditional/TradingAgents
analysis capabilities must be mechanically mapped before a scanner/rule contract is frozen.

### Pradeep
Pradeep Phase 9 v1 is **complete for the current point-in-time mission**.

- Phase 9 v1: `COMPLETE_WITH_DECLARED_SOURCE_GAP`
- inventory: `1270` files / `48833946` bytes
- inventory SHA-256: `e300b7c54e52b79dec0a7ce31e76f6e376bb18d08c25c93bf43272a6af067126`
- source records: `596`
- quality: `13/13` gates
- declared gap: `wiki/setups/simple_9.md`
- Simple 9 active search: `STOP`

No broad recrawl is required to proceed.

Pradeep Scanner remains part of the Pradeep stock-selection funnel. The architecture
reserves Momentum Burst, Episodic Pivot, EP 9 Million, MAGNA/MAGNA53, and Breakout
Anticipation as future scanner families. **Executable scanner rules must later be derived
from frozen first-party Pradeep evidence. Old UI placeholder rules are not authority.**

The current Phase10B.1 detached candidate has verified Stockbee grounding for:
`stockbee_momentum_burst` and `stockbee_episodic_pivot`. This freeze does not falsely
declare that detached candidate merged into mainline.

### Technology
Technology is **interface-reserved only** at this stage.

No Technology KB exists yet, therefore this freeze does **not** invent:
- Technology scanner rules,
- a Technology scanner contract,
- a detailed tracking contract,
- company-analysis standards.

The architecture reserves only the integration position: a future Technology system may
publish candidate/evidence objects into the Unified Candidate Layer and may provide
Technology analysis context to the shared analysis orchestrator.

The accepted high-level dynamic pattern is:

`Recent Signal Cache -> Material Event Index -> Company State Timeline`

This is an architecture pattern only, not a frozen implementation schema.

## Knowledge and dynamic evidence are separate

Static/versioned methodology knowledge and dynamic/current evidence must remain separate.
Real-time news streams are not a permanent methodology database.

## Unified Candidate Layer

Outputs from Traditional, Pradeep, and Technology converge without losing origin:
the UI must be able to answer **why this company was selected and by which system**.

A single cross-system black-box total score is not authorized.

## UI

UI information architecture is frozen now, while feature connectivity is staged.

Discovery presents:
- Traditional
- Pradeep
- Technology

Downstream shared surfaces:
- Unified Candidate Board
- Compare
- Analysis
- Results / Run

Not-yet-connected capabilities must be labeled truthfully as not connected.

## Change control

L0 may change only after:
1. new mechanical evidence contradicts it or the owner makes a new business decision,
2. the contradiction/change is explicitly documented,
3. the owner approves a new architecture version.

Implementation convenience is never sufficient authority.

## Next stage

`L1_CURRENT_STATE_GAP_MAPPING`
