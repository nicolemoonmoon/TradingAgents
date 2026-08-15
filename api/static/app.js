(function () {
  "use strict";

  const POLL_INTERVAL_MS = 2000;
  const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
  const STATUS_CLASSES = ["status-queued", "status-running", "status-completed", "status-failed", "status-cancelled"];

  const el = (id) => document.getElementById(id);

  const modeNew = el("mode-new");
  const modeLoad = el("mode-load");
  const modeCandidates = el("mode-candidates");
  const modeCompare = el("mode-compare");
  const modeScanner = el("mode-scanner");
  const newRunForm = el("new-run-form");
  const loadRunForm = el("load-run-form");
  const candidateBoard = el("candidate-board");
  const compareBoard = el("compare-board");
  const scannerBoard = el("scanner-board");
  const startButton = el("start-button");
  const analysisDateInput = el("analysis-date-input");
  const resetButton = el("reset-button");
  const loadRunButton = el("load-run-button");
  const runIdInput = el("run-id-input");
  const candidateTickerInput = el("candidate-ticker-input");
  const candidateAddButton = el("candidate-add-button");
  const candidateTableBody = el("candidate-table-body");
  const compareTableBody = el("compare-table-body");
  const compareEmptyMessage = el("compare-empty-message");
  const errorMessage = el("error-message");
  const runView = el("run-view");
  const runIdLabel = el("run-id-label");
  const statusLabel = el("status-label");
  const strategyProfileLabel = el("strategy-profile-label");
  const eventTimeline = el("event-timeline");
  const agentList = el("agent-list");
  const finalDecision = el("final-decision");
  const legacyDraftRatingGroup = el("legacy-draft-rating-group");
  const legacyTraderActionGroup = el("legacy-trader-action-group");
  const traderActionLabel = el("trader-action-label");
  const draftRatingLabel = el("draft-rating-label");
  const dataQualityFlagsLabel = el("data-quality-flags-label");
  const reportLink = el("report-link");
  const entryDecisionGroup = el("entry-decision-group");
  const entryDecisionLabel = el("entry-decision-label");
  const executionAvailabilityLabel = el("execution-availability-label");
  const waitRationale = el("wait-rationale");
  const whyWaitLabel = el("why-wait-label");
  const whatNeedsToChangeLabel = el("what-needs-to-change-label");
  const recheckTriggerLabel = el("recheck-trigger-label");
  const reviewDueLabel = el("review-due-label");
  const positionDecisionGroup = el("position-decision-group");
  const positionDecisionLabel = el("position-decision-label");
  const exitReasonLabel = el("exit-reason-label");

  function localTodayISO() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  if (!analysisDateInput.value) {
    analysisDateInput.value = localTodayISO();
  }

  let pollTimer = null;
  // Which run_id (if any) has been started/loaded this session. #run-view
  // belongs to the Load Run tab only -- setMode() is the single place that
  // decides run-view.hidden; nothing else may set it directly.
  let currentRunId = null;

  function showError(message) {
    errorMessage.textContent = message;
    errorMessage.hidden = false;
  }

  function clearError() {
    errorMessage.hidden = true;
    errorMessage.textContent = "";
  }

  function stopPolling() {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function setMode(mode) {
    newRunForm.hidden = mode !== "new";
    loadRunForm.hidden = mode !== "load";
    candidateBoard.hidden = mode !== "candidates";
    compareBoard.hidden = mode !== "compare";
    scannerBoard.hidden = mode !== "scanner";
    runView.hidden = mode !== "load" || currentRunId === null;
  }

  modeNew.addEventListener("change", () => setMode("new"));
  modeLoad.addEventListener("change", () => setMode("load"));
  modeCandidates.addEventListener("change", () => setMode("candidates"));
  modeCompare.addEventListener("change", () => setMode("compare"));
  modeScanner.addEventListener("change", () => setMode("scanner"));

  function renderEvents(events) {
    eventTimeline.innerHTML = "";
    for (const event of events) {
      const li = document.createElement("li");
      li.className = "event-row";

      const typeSpan = document.createElement("span");
      typeSpan.className = "event-type";
      typeSpan.textContent = event.event_type;

      const timeSpan = document.createElement("span");
      timeSpan.className = "event-time";
      timeSpan.textContent = event.created_at;

      li.appendChild(typeSpan);
      li.appendChild(timeSpan);
      eventTimeline.appendChild(li);
    }
  }

  function renderAgents(agents) {
    agentList.innerHTML = "";
    for (const [agentId, agentStatus] of Object.entries(agents || {})) {
      const li = document.createElement("li");
      li.className = "agent-row";

      const nameSpan = document.createElement("span");
      nameSpan.className = "agent-name";
      nameSpan.textContent = agentId;

      const statusSpan = document.createElement("span");
      statusSpan.className = "status-badge";
      statusSpan.classList.add(`status-${safeStatusClass(agentStatus)}`);
      statusSpan.textContent = formatStatusLabel(agentStatus);

      li.appendChild(nameSpan);
      li.appendChild(statusSpan);
      agentList.appendChild(li);
    }
  }

  function safeStatusClass(value) {
    return String(value || "unknown")
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-");
  }

  function formatStatusLabel(value) {
    return String(value || "unknown")
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  function setStatusLabel(analysisStatus) {
    statusLabel.textContent = formatStatusLabel(analysisStatus);
    statusLabel.classList.remove(...STATUS_CLASSES);
    statusLabel.classList.add(`status-${safeStatusClass(analysisStatus)}`);
  }

  function formatDataQualityFlags(flags) {
    if (flags === null || flags === undefined) return "—";
    return flags.length ? flags.join(", ") : "(none)";
  }

  // E11 (UI-10): render the already-computed Traditional Structural Disruption
  // six-question assessment and AI Counter-Thesis as compact, auditable prose
  // inside the existing selection/provenance cell -- never a new column, never
  // a score, and only for selections that actually carry them.
  function formatStructuralDisruption(sd) {
    if (!sd) return "";
    const questions = (sd.questions || [])
      .map((q) => `${q.question}: ${q.conclusion}`)
      .join("; ");
    return `structural_disruption (${sd.method_version}): ${questions}`;
  }

  function formatCounterThesis(ct) {
    if (!ct) return "";
    const judgments = (ct.major_judgments || [])
      .map((j) => `${j.judgment_id} [${j.confidence_level}]: ${j.finding}`)
      .join("; ");
    const parts = [];
    if (judgments) parts.push(`judgments: ${judgments}`);
    if (ct.thesis_break_conditions) parts.push(`thesis_break: ${ct.thesis_break_conditions}`);
    return `counter_thesis: ${parts.join(" | ")}`;
  }

  function formatSelectionDisclosure(selection) {
    return [
      formatStructuralDisruption(selection.structural_disruption),
      formatCounterThesis(selection.counter_thesis),
    ]
      .filter(Boolean)
      .join(" | ");
  }

  // E09: renders one candidate's full selection provenance -- system origin,
  // selection/producer identity, scanner/setup identity, matched/failed/
  // unknown rule why-selected evidence, evidence-id provenance, and temporal/
  // rank fields. Selections are stored exactly as the E02 contract returns
  // them (snake_case, unmodified) so this never grows a second, drifting
  // candidate contract. Never combines multiple systems' selections into a
  // single score; each selection is shown on its own.
  function formatProvenance(provenance) {
    if (!provenance || provenance.length === 0) {
      return "Manual — no scanner provenance";
    }
    return provenance
      .map((selection) => {
        const setup = selection.setup_id ? `/${selection.setup_id}` : "";
        const matched =
          selection.matched_rules && selection.matched_rules.length
            ? selection.matched_rules.join(", ")
            : "—";
        const failed =
          selection.failed_rules && selection.failed_rules.length
            ? selection.failed_rules.join(", ")
            : "—";
        const unknown =
          selection.unknown_rules && selection.unknown_rules.length
            ? selection.unknown_rules.join(", ")
            : "—";
        const evidence = (selection.evidence_refs || [])
          .map(
            (ref) =>
              `${ref.evidence_id} [${ref.source_type}] ref=${ref.source_ref}; ` +
              `url=${ref.source_url ?? "null"}; data_as_of=${ref.data_as_of ?? "null"}`
          )
          .join(" || ");
        const rank = selection.system_rank
          ? `; rank: ${selection.system_rank.value} (${selection.system_rank.meaning}; ` +
            `higher_is_better=${selection.system_rank.higher_is_better})`
          : "";
        const disclosure = formatSelectionDisclosure(selection);
        return (
          `${selection.selection_system}${setup} via ${selection.scanner_id} ` +
          `[${selection.selection_id} / ${selection.producer_version}] ` +
          `— matched: ${matched}; failed: ${failed}; unknown: ${unknown}; ` +
          `evidence_refs: ${evidence || "—"}; detected_at: ${selection.detected_at}; ` +
          `data_as_of: ${selection.data_as_of}${rank}` +
          (disclosure ? `; ${disclosure}` : "")
        );
      })
      .join(" | ");
  }

  // E09: displays ticker when present; otherwise falls back to E02's
  // display_name, then company_id. Never substitutes company_id into the
  // ticker field itself -- callers needing the real ticker must still see
  // null so Analyze can fail closed truthfully.
  function formatIdentity(candidate) {
    if (candidate.ticker) return candidate.ticker;
    if (candidate.displayName) return candidate.displayName;
    return candidate.companyId || "(unknown)";
  }

  function renderFinalDecision(runId, manifest) {
    traderActionLabel.textContent = formatStatusLabel(manifest.trader_action);
    traderActionLabel.className = "decision-badge";
    traderActionLabel.classList.add(`decision-${safeStatusClass(manifest.trader_action)}`);
    draftRatingLabel.textContent = manifest.draft_rating ?? "(none)";
    dataQualityFlagsLabel.textContent = formatDataQualityFlags(manifest.data_quality_flags);
    reportLink.href = `/api/runs/${encodeURIComponent(runId)}/reports/complete_report`;

    const hasGovernedDecision =
      manifest.entry_decision != null || manifest.position_decision != null;
    legacyDraftRatingGroup.hidden = hasGovernedDecision;
    legacyTraderActionGroup.hidden = hasGovernedDecision;

    // Governed entry decision (NOT_HELD semantics: BUY | WAIT | REVIEW) and
    // its WAIT rationale -- rendered only when the optional field is present,
    // never merged into the draft rating / trader action groups.
    if (manifest.entry_decision != null) {
      entryDecisionLabel.textContent = formatStatusLabel(manifest.entry_decision);
      executionAvailabilityLabel.textContent =
        manifest.execution_availability != null
          ? formatStatusLabel(manifest.execution_availability)
          : "—";
      whyWaitLabel.textContent = manifest.why_wait ?? "—";
      whatNeedsToChangeLabel.textContent = manifest.what_needs_to_change ?? "—";
      recheckTriggerLabel.textContent = manifest.recheck_trigger ?? "—";
      reviewDueLabel.textContent = manifest.review_due ?? "—";
      waitRationale.hidden = safeStatusClass(manifest.entry_decision) !== "wait";
      entryDecisionGroup.hidden = false;
    } else {
      entryDecisionGroup.hidden = true;
    }

    // Governed position decision (HELD semantics: HOLD | REDUCE | SELL |
    // REVIEW) -- rendered only when the optional field is present.
    if (manifest.position_decision != null) {
      positionDecisionLabel.textContent = formatStatusLabel(manifest.position_decision);
      exitReasonLabel.textContent =
        manifest.exit_reason != null ? formatStatusLabel(manifest.exit_reason) : "—";
      positionDecisionGroup.hidden = false;
    } else {
      positionDecisionGroup.hidden = true;
    }

    finalDecision.hidden = false;
  }

  async function fetchJson(url) {
    const resp = await fetch(url);
    return { resp, body: resp.ok ? await resp.json() : null };
  }

  // Shared by the single-run view and Candidate Board rows: fetch a run's
  // status, plus its manifest once completed. Never fetches events -- only
  // the single-run view needs the timeline.
  async function fetchRunSnapshot(runId) {
    let statusResp, status;
    try {
      const result = await fetchJson(
        `/api/runs/${encodeURIComponent(runId)}/status`
      );
      statusResp = result.resp;
      status = result.body;
    } catch {
      // Network error (fetch itself threw, e.g. connection refused during a
      // server restart) — transient, caller should keep polling.
      return { found: false, statusCode: 0 };
    }
    if (!statusResp.ok) {
      // Distinguish genuine 404 (run directory gone) from transient failures
      // (server restart returning 503, gateway timeout 504, etc.).
      return { found: false, statusCode: statusResp.status };
    }
    let manifest = null;
    if (status.analysis_status === "completed") {
      const { body } = await fetchJson(`/api/runs/${encodeURIComponent(runId)}/manifest`);
      manifest = body;
    }
    return { found: true, status, manifest };
  }

  // G5/R3: derive the exact E02 selection origin from the candidate object the
  // browser already holds (never from the ticker). A single unambiguous
  // selection is a BASELINE_SYSTEM analysis. A candidate with zero selections
  // is manual; a candidate with multiple selections (same or different
  // systems) cannot be disambiguated by the single Analyze button, so it fails
  // closed to no-origin rather than guessing or defaulting to one system.
  function deriveSelectionOrigin(candidate) {
    const selections = candidate.provenance || [];
    if (selections.length !== 1) {
      return null;
    }
    const selection = selections[0];
    return {
      system_scope: selection.selection_system,
      selection_record_ref: {
        selection_id: selection.selection_id,
        selection_system: selection.selection_system,
        company_id: candidate.companyId,
      },
      analysis_purpose: "BASELINE_SYSTEM",
    };
  }

  function formatCandidateDecision(candidate) {
    if (candidate.entryDecision != null) {
      return `Entry: ${formatStatusLabel(candidate.entryDecision)}`;
    }
    if (candidate.positionDecision != null) {
      return `Position: ${formatStatusLabel(candidate.positionDecision)}`;
    }
    return candidate.traderAction != null
      ? `Legacy: ${formatStatusLabel(candidate.traderAction)}`
      : "—";
  }

  // Shared by "Start new analysis" and Candidate Board: every analysis
  // entry point uses the same run settings, only the ticker differs.
  function buildAnalysisPayload(ticker, origin) {
    const analysisDate = analysisDateInput.value;
    if (!analysisDate) {
      throw new Error("Analysis date is required.");
    }
    const strategyProfileValue = el("strategy-profile-input").value.trim();
    const quickValue = el("quick-model-input").value.trim();
    const deepValue = el("deep-model-input").value.trim();
    const payload = {
      ticker,
      analysis_date: analysisDate,
      selected_analysts: collectSelectedAnalysts(),
      quick_model: quickValue || null,
      deep_model: deepValue || null,
      strategy_profile: strategyProfileValue === "" ? null : strategyProfileValue,
    };
    if (origin) {
      payload.system_scope = origin.system_scope;
      payload.selection_record_ref = origin.selection_record_ref;
      payload.analysis_purpose = origin.analysis_purpose;
    }
    return payload;
  }

  async function postAnalysis(ticker, origin) {
    const resp = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildAnalysisPayload(ticker, origin)),
    });
    const body = await resp.json();
    return { resp, body };
  }

  async function refreshRun(runId) {
    const snapshot = await fetchRunSnapshot(runId);
    if (!snapshot.found) {
      // Permanent errors: stop polling and show the reason.
      if (snapshot.statusCode === 404) {
        stopPolling();
        showError(`Run ${runId} not found.`);
        return;
      }
      if (snapshot.statusCode === 400) {
        stopPolling();
        showError("Invalid run ID. Please check the run ID and try again.");
        return;
      }
      // Transient failures (network error 0, server 5xx) — keep polling
      // silently, the next interval will retry automatically.
      return;
    }

    clearError();
    currentRunId = runId;
    runIdLabel.textContent = runId;
    setStatusLabel(snapshot.status.analysis_status);
    strategyProfileLabel.textContent = snapshot.status.strategy_profile ?? "(none)";
    renderAgents(snapshot.status.agents);

    const { body: events } = await fetchJson(`/api/runs/${encodeURIComponent(runId)}/events`);
    if (events) {
      renderEvents(events);
    }

    if (TERMINAL_STATUSES.has(snapshot.status.analysis_status)) {
      stopPolling();
      startButton.hidden = true;
      resetButton.hidden = false;
      if (snapshot.manifest) {
        renderFinalDecision(runId, snapshot.manifest);
      }
    }
  }

  function startPolling(runId) {
    stopPolling();
    refreshRun(runId);
    pollTimer = setInterval(() => refreshRun(runId), POLL_INTERVAL_MS);
  }

  function collectSelectedAnalysts() {
    return Array.from(document.querySelectorAll(".analyst-checkbox:checked")).map(
      (checkbox) => checkbox.value
    );
  }

  async function startAnalysis() {
    clearError();
    startButton.disabled = true;
    try {
      const { resp, body } = await postAnalysis(el("ticker-input").value.trim());
      if (resp.status !== 202) {
        if (resp.status === 409 && body.detail?.active_run_id) {
          showError(
            `Another analysis (${body.detail.active_run_id}) is already running. ` +
              "Only one active analysis is allowed per server process."
          );
        } else {
          showError(`Failed to start analysis: ${JSON.stringify(body.detail ?? body)}`);
        }
        startButton.disabled = false;
        return;
      }
      currentRunId = body.run_id;
      modeLoad.checked = true;
      runIdInput.value = body.run_id;
      setMode("load");
      startPolling(body.run_id);
    } catch (err) {
      showError(`Failed to start analysis: ${err}`);
      startButton.disabled = false;
    }
  }

  startButton.addEventListener("click", startAnalysis);

  resetButton.addEventListener("click", () => {
    stopPolling();
    currentRunId = null;
    modeNew.checked = true;
    setMode("new");
    finalDecision.hidden = true;
    startButton.hidden = false;
    startButton.disabled = false;
    resetButton.hidden = true;
    clearError();
  });

  loadRunButton.addEventListener("click", () => {
    const runId = runIdInput.value.trim();
    if (!runId) {
      showError("Enter a run ID to load.");
      return;
    }
    currentRunId = runId;
    setMode("load");
    startPolling(runId);
  });

  function readRunIdFromUrl() {
    return new URLSearchParams(window.location.search).get("run_id");
  }

  const urlRunId = readRunIdFromUrl();
  if (urlRunId) {
    currentRunId = urlRunId;
    modeLoad.checked = true;
    setMode("load");
    runIdInput.value = urlRunId;
    startPolling(urlRunId);
  }

  // -------------------------------------------------------------------
  // Candidate Board (Phase 2G): in-memory only, never persisted. A
  // candidate only shows results for a run started from its own Analyze
  // button in this session -- there is no lookup of past runs by ticker.
  // -------------------------------------------------------------------

  let candidates = [];
  let candidatePollTimer = null;

  function parseTickerInput(raw) {
    return raw
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t.length > 0);
  }

  function addCandidates(raw) {
    const seen = new Set(
      candidates.filter((c) => c.ticker).map((c) => c.ticker.toUpperCase())
    );
    for (const ticker of parseTickerInput(raw)) {
      const key = ticker.toUpperCase();
      if (seen.has(key)) continue;
      seen.add(key);
      candidates.push({
        ticker,
        // E09: manually-added candidates have no E02 company identity of
        // their own -- only scanner-derived candidates carry companyId.
        companyId: null,
        displayName: null,
        runId: null,
        analysisStatus: null,
        strategyProfile: null,
        traderAction: null,
        entryDecision: null,
        positionDecision: null,
        draftRating: null,
        dataQualityFlags: null,
        errorMessage: null,
        // Phase 2H: Compare Board fields. The four "*Quality"/"*Strength"/
        // "chartSetup" fields are pure placeholders -- nothing in this repo
        // computes them yet, they always stay null. humanNotes is the one
        // real user input, in-memory only.
        catalystQuality: null,
        sectorStrength: null,
        volumeQuality: null,
        chartSetup: null,
        humanNotes: "",
        // E09: manually-added candidates have no scanner provenance --
        // this stays an empty array unless a scanner feed merge (below)
        // finds a matching ticker.
        provenance: [],
      });
    }
    renderCandidates();
  }

  function currentStrategyProfileLabel() {
    const select = el("strategy-profile-input");
    return select.options[select.selectedIndex].text;
  }

  function formatCandidateStrategyProfile(candidate) {
    // Before any run, preview the shared setting's current selection --
    // that's what Analyze would actually send. Once a run exists, show
    // what the API echoed back (the confirmed value), not the live setting,
    // since the shared dropdown may have changed since that run started.
    if (candidate.runId === null) {
      return currentStrategyProfileLabel();
    }
    return candidate.strategyProfile === null ? "None / Manual analysis" : candidate.strategyProfile;
  }

  function renderCandidateTable() {
    candidateTableBody.innerHTML = "";
    for (const candidate of candidates) {
      const row = document.createElement("tr");

      const cells = [
        formatIdentity(candidate),
        formatCandidateStrategyProfile(candidate),
        candidate.analysisStatus ?? "not run",
        formatCandidateDecision(candidate),
        candidate.draftRating ?? "—",
        formatDataQualityFlags(candidate.dataQualityFlags),
        formatProvenance(candidate.provenance),
      ];
      for (const text of cells) {
        const td = document.createElement("td");
        td.textContent = text;
        row.appendChild(td);
      }

      const actionCell = document.createElement("td");
      const analyzeButton = document.createElement("button");
      analyzeButton.type = "button";
      if (candidate.ticker) {
        analyzeButton.textContent = "Analyze";
        analyzeButton.addEventListener("click", () => analyzeCandidate(candidate));
      } else {
        // E09: no ticker -- fail closed rather than fabricating one from
        // company_id or any other identity field.
        analyzeButton.textContent = "Analyze (no ticker)";
        analyzeButton.disabled = true;
        analyzeButton.title = "This candidate has no ticker; Analyze is unavailable.";
      }
      actionCell.appendChild(analyzeButton);
      if (candidate.errorMessage) {
        const errorDiv = document.createElement("div");
        errorDiv.className = "candidate-error";
        errorDiv.textContent = candidate.errorMessage;
        actionCell.appendChild(errorDiv);
      }
      row.appendChild(actionCell);

      candidateTableBody.appendChild(row);
    }
  }

  function ensureCandidatePolling() {
    if (candidatePollTimer !== null) return;
    candidatePollTimer = setInterval(refreshActiveCandidates, POLL_INTERVAL_MS);
  }

  async function refreshActiveCandidates() {
    const active = candidates.filter(
      (c) => c.runId !== null && !TERMINAL_STATUSES.has(c.analysisStatus)
    );
    if (active.length === 0) return;
    for (const candidate of active) {
      const snapshot = await fetchRunSnapshot(candidate.runId);
      if (!snapshot.found) continue;
      candidate.analysisStatus = snapshot.status.analysis_status;
      candidate.strategyProfile = snapshot.status.strategy_profile ?? candidate.strategyProfile;
      if (snapshot.manifest) {
        candidate.traderAction = snapshot.manifest.trader_action;
        candidate.entryDecision = snapshot.manifest.entry_decision;
        candidate.positionDecision = snapshot.manifest.position_decision;
        candidate.draftRating = snapshot.manifest.draft_rating;
        candidate.dataQualityFlags = snapshot.manifest.data_quality_flags;
      }
    }
    renderCandidates();
  }

  async function analyzeCandidate(candidate) {
    candidate.errorMessage = null;
    if (!candidate.ticker) {
      // E09: fail closed -- never send company_id (or any non-ticker
      // identity) to /api/runs as though it were a ticker.
      candidate.errorMessage = "Cannot analyze: this candidate has no ticker.";
      renderCandidates();
      return;
    }
    // BR-3: a scanner-derived candidate must carry exactly one unambiguous
    // selection to start a baseline analysis. Multiple selections (same or
    // different systems) cannot be disambiguated by the single Analyze
    // button, so fail closed: show an error and never POST -- do not silently
    // demote an ambiguous selected-candidate action to a manual review.
    if (candidate.provenance && candidate.provenance.length > 1) {
      candidate.errorMessage =
        "Cannot analyze: this candidate has multiple scanner selections; " +
        "exactly one unambiguous selection is required.";
      renderCandidates();
      return;
    }
    try {
      const origin = deriveSelectionOrigin(candidate);
      const { resp, body } = await postAnalysis(candidate.ticker, origin);
      if (resp.status !== 202) {
        if (resp.status === 409 && body.detail?.active_run_id) {
          candidate.errorMessage =
            `Busy: analysis ${body.detail.active_run_id} already running`;
        } else {
          candidate.errorMessage = `Failed: ${JSON.stringify(body.detail ?? body)}`;
        }
        renderCandidates();
        return;
      }
      candidate.runId = body.run_id;
      candidate.strategyProfile = body.strategy_profile;
      candidate.analysisStatus = body.analysis_status;
      renderCandidates();
      ensureCandidatePolling();
    } catch (err) {
      candidate.errorMessage = `Failed: ${err}`;
      renderCandidates();
    }
  }

  candidateAddButton.addEventListener("click", () => {
    addCandidates(candidateTickerInput.value);
    candidateTickerInput.value = "";
  });

  // -------------------------------------------------------------------
  // Compare Board (Phase 2H): reads the exact same `candidates` array and
  // objects as Candidate Board above -- no separate data source, no fetch
  // of its own. Any update Candidate Board makes to a candidate object is
  // automatically visible here once renderCandidates() runs, since both
  // render functions read the same references.
  // -------------------------------------------------------------------

  let compareNotesFocused = false;

  function renderCandidates() {
    renderCandidateTable();
    if (!compareNotesFocused) {
      renderCompareTable();
    }
  }

  function formatPlaceholder(value) {
    return value === null || value === undefined ? "Not reviewed" : value;
  }

  function renderCompareTable() {
    compareEmptyMessage.hidden = candidates.length > 0;
    compareTableBody.innerHTML = "";
    for (const candidate of candidates) {
      const row = document.createElement("tr");

      const cells = [
        formatIdentity(candidate),
        formatCandidateStrategyProfile(candidate),
        candidate.analysisStatus ?? "not run",
        formatCandidateDecision(candidate),
        candidate.draftRating ?? "—",
        formatDataQualityFlags(candidate.dataQualityFlags),
        formatProvenance(candidate.provenance),
      ];
      for (const text of cells) {
        const td = document.createElement("td");
        td.textContent = text;
        row.appendChild(td);
      }

      for (const value of [
        candidate.catalystQuality,
        candidate.sectorStrength,
        candidate.volumeQuality,
        candidate.chartSetup,
      ]) {
        const td = document.createElement("td");
        td.textContent = formatPlaceholder(value);
        if (value === null || value === undefined) {
          td.className = "placeholder-cell";
        }
        row.appendChild(td);
      }

      const notesCell = document.createElement("td");
      const notesInput = document.createElement("input");
      notesInput.type = "text";
      notesInput.className = "compare-notes-input";
      notesInput.value = candidate.humanNotes;
      notesInput.addEventListener("focus", () => {
        compareNotesFocused = true;
      });
      notesInput.addEventListener("blur", () => {
        compareNotesFocused = false;
        renderCompareTable();
      });
      notesInput.addEventListener("input", (event) => {
        candidate.humanNotes = event.target.value;
      });
      notesCell.appendChild(notesInput);
      row.appendChild(notesCell);

      compareTableBody.appendChild(row);
    }
  }

  // -------------------------------------------------------------------
  // Discovery foundation (E03): the visible Discovery surface declares
  // Traditional, Pradeep, and Technology as independent selection systems.
  // It performs no fetch and does not mutate the Candidate Board. Scanner
  // execution is intentionally staged until each producer contract exists.
  // -------------------------------------------------------------------

  renderCandidates();

  // -------------------------------------------------------------------
  // E09: Unified scanner-candidate feed. Fetches already-selected
  // Traditional/Pradeep UnifiedCandidate envelopes from the process-local
  // API feed and merges them into the exact same in-memory `candidates`
  // array Candidate Board and Compare Board already share -- no second
  // client-side datasource/state store. Manual candidates (added via the
  // ticker input) keep an empty `provenance` array and render as having
  // no scanner provenance. Technology never appears here: the backend
  // feed rejects any envelope carrying an actual TECHNOLOGY selection.
  // -------------------------------------------------------------------

  // E09: E02 allows canonical company identity with a nullable ticker.
  // company_id is never substituted into the ticker field -- a ticker-less
  // envelope is matched/created by company_id alone, so its candidate keeps
  // ticker === null rather than fabricating one.
  function findOrCreateScannerCandidate(envelope) {
    let candidate = null;
    if (envelope.ticker) {
      const key = envelope.ticker.toUpperCase();
      candidate = candidates.find((c) => c.ticker && c.ticker.toUpperCase() === key);
    } else {
      candidate = candidates.find((c) => c.companyId === envelope.company_id);
    }
    if (candidate) {
      candidate.companyId = envelope.company_id;
      candidate.ticker = candidate.ticker || envelope.ticker;
      candidate.displayName = envelope.display_name || candidate.displayName;
      return candidate;
    }
    candidate = {
      ticker: envelope.ticker,
      companyId: envelope.company_id,
      displayName: envelope.display_name,
      runId: null,
      analysisStatus: null,
      strategyProfile: null,
      traderAction: null,
      entryDecision: null,
      positionDecision: null,
      draftRating: null,
      dataQualityFlags: null,
      errorMessage: null,
      catalystQuality: null,
      sectorStrength: null,
      volumeQuality: null,
      chartSetup: null,
      humanNotes: "",
      provenance: [],
    };
    candidates.push(candidate);
    return candidate;
  }

  function mergeScannerCandidates(envelopes) {
    for (const envelope of envelopes) {
      const candidate = findOrCreateScannerCandidate(envelope);
      // E09: keep the full E02 selection mapping exactly as returned --
      // selection_id, producer_version, failed/unknown rules, data_as_of,
      // and system_rank all survive into Candidate/Compare state.
      candidate.provenance = envelope.selections;
    }
    renderCandidates();
  }

  async function fetchScannerCandidates() {
    try {
      const { resp, body } = await fetchJson("/api/scanner-candidates");
      if (resp.ok && Array.isArray(body) && body.length > 0) {
        mergeScannerCandidates(body);
      }
    } catch {
      // Transient network error -- Candidate Board still works with
      // manual entries; nothing else in this page depends on this fetch.
    }
  }

  fetchScannerCandidates();
})();
