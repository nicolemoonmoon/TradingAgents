(function () {
  "use strict";

  const POLL_INTERVAL_MS = 2000;
  const TERMINAL_STATUSES = new Set(["completed", "failed"]);
  const STATUS_CLASSES = ["status-queued", "status-running", "status-completed", "status-failed"];

  const el = (id) => document.getElementById(id);

  const modeNew = el("mode-new");
  const modeLoad = el("mode-load");
  const modeCandidates = el("mode-candidates");
  const newRunForm = el("new-run-form");
  const loadRunForm = el("load-run-form");
  const candidateBoard = el("candidate-board");
  const startButton = el("start-button");
  const resetButton = el("reset-button");
  const loadRunButton = el("load-run-button");
  const runIdInput = el("run-id-input");
  const candidateTickerInput = el("candidate-ticker-input");
  const candidateAddButton = el("candidate-add-button");
  const candidateTableBody = el("candidate-table-body");
  const errorMessage = el("error-message");
  const runView = el("run-view");
  const runIdLabel = el("run-id-label");
  const statusLabel = el("status-label");
  const strategyProfileLabel = el("strategy-profile-label");
  const eventTimeline = el("event-timeline");
  const agentList = el("agent-list");
  const finalDecision = el("final-decision");
  const traderActionLabel = el("trader-action-label");
  const draftRatingLabel = el("draft-rating-label");
  const dataQualityFlagsLabel = el("data-quality-flags-label");
  const reportLink = el("report-link");

  let pollTimer = null;

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
  }

  modeNew.addEventListener("change", () => setMode("new"));
  modeLoad.addEventListener("change", () => setMode("load"));
  modeCandidates.addEventListener("change", () => setMode("candidates"));

  function renderEvents(events) {
    eventTimeline.innerHTML = "";
    for (const event of events) {
      const li = document.createElement("li");
      li.textContent = `${event.event_type} @ ${event.created_at}`;
      eventTimeline.appendChild(li);
    }
  }

  function renderAgents(agents) {
    agentList.innerHTML = "";
    for (const [agentId, agentStatus] of Object.entries(agents || {})) {
      const li = document.createElement("li");
      li.textContent = `${agentId}: ${agentStatus}`;
      agentList.appendChild(li);
    }
  }

  function setStatusLabel(analysisStatus) {
    statusLabel.textContent = analysisStatus;
    statusLabel.classList.remove(...STATUS_CLASSES);
    statusLabel.classList.add(`status-${analysisStatus}`);
  }

  function formatDataQualityFlags(flags) {
    if (flags === null || flags === undefined) return "—";
    return flags.length ? flags.join(", ") : "(none)";
  }

  function renderFinalDecision(runId, manifest) {
    traderActionLabel.textContent = manifest.trader_action ?? "(none)";
    draftRatingLabel.textContent = manifest.draft_rating ?? "(none)";
    dataQualityFlagsLabel.textContent = formatDataQualityFlags(manifest.data_quality_flags);
    reportLink.href = `/api/runs/${encodeURIComponent(runId)}/reports/complete_report`;
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
    const { resp: statusResp, body: status } = await fetchJson(
      `/api/runs/${encodeURIComponent(runId)}/status`
    );
    if (!statusResp.ok) {
      return { found: false };
    }
    let manifest = null;
    if (status.analysis_status === "completed") {
      const { body } = await fetchJson(`/api/runs/${encodeURIComponent(runId)}/manifest`);
      manifest = body;
    }
    return { found: true, status, manifest };
  }

  // Shared by "Start new analysis" and Candidate Board: every analysis
  // entry point uses the same run settings, only the ticker differs.
  function buildAnalysisPayload(ticker) {
    const strategyProfileValue = el("strategy-profile-input").value.trim();
    return {
      ticker,
      analysis_date: el("analysis-date-input").value,
      selected_analysts: collectSelectedAnalysts(),
      quick_model: el("quick-model-input").value.trim(),
      deep_model: el("deep-model-input").value.trim(),
      strategy_profile: strategyProfileValue === "" ? null : strategyProfileValue,
    };
  }

  async function postAnalysis(ticker) {
    const resp = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildAnalysisPayload(ticker)),
    });
    const body = await resp.json();
    return { resp, body };
  }

  async function refreshRun(runId) {
    const snapshot = await fetchRunSnapshot(runId);
    if (!snapshot.found) {
      stopPolling();
      showError(`Run ${runId} not found.`);
      return;
    }

    clearError();
    runView.hidden = false;
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
        showError(`Failed to start analysis: ${JSON.stringify(body.detail ?? body)}`);
        startButton.disabled = false;
        return;
      }
      startPolling(body.run_id);
    } catch (err) {
      showError(`Failed to start analysis: ${err}`);
      startButton.disabled = false;
    }
  }

  startButton.addEventListener("click", startAnalysis);

  resetButton.addEventListener("click", () => {
    stopPolling();
    runView.hidden = true;
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
    startPolling(runId);
  });

  function readRunIdFromUrl() {
    return new URLSearchParams(window.location.search).get("run_id");
  }

  const urlRunId = readRunIdFromUrl();
  if (urlRunId) {
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
    const seen = new Set(candidates.map((c) => c.ticker.toUpperCase()));
    for (const ticker of parseTickerInput(raw)) {
      const key = ticker.toUpperCase();
      if (seen.has(key)) continue;
      seen.add(key);
      candidates.push({
        ticker,
        runId: null,
        analysisStatus: null,
        strategyProfile: null,
        traderAction: null,
        draftRating: null,
        dataQualityFlags: null,
        errorMessage: null,
      });
    }
    renderCandidateTable();
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
        candidate.ticker,
        formatCandidateStrategyProfile(candidate),
        candidate.analysisStatus ?? "not run",
        candidate.traderAction ?? "—",
        candidate.draftRating ?? "—",
        formatDataQualityFlags(candidate.dataQualityFlags),
      ];
      for (const text of cells) {
        const td = document.createElement("td");
        td.textContent = text;
        row.appendChild(td);
      }

      const actionCell = document.createElement("td");
      const analyzeButton = document.createElement("button");
      analyzeButton.type = "button";
      analyzeButton.textContent = "Analyze";
      analyzeButton.addEventListener("click", () => analyzeCandidate(candidate));
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
        candidate.draftRating = snapshot.manifest.draft_rating;
        candidate.dataQualityFlags = snapshot.manifest.data_quality_flags;
      }
    }
    renderCandidateTable();
  }

  async function analyzeCandidate(candidate) {
    candidate.errorMessage = null;
    try {
      const { resp, body } = await postAnalysis(candidate.ticker);
      if (resp.status !== 202) {
        candidate.errorMessage = `Failed: ${JSON.stringify(body.detail ?? body)}`;
        renderCandidateTable();
        return;
      }
      candidate.runId = body.run_id;
      candidate.strategyProfile = body.strategy_profile;
      candidate.analysisStatus = body.analysis_status;
      renderCandidateTable();
      ensureCandidatePolling();
    } catch (err) {
      candidate.errorMessage = `Failed: ${err}`;
      renderCandidateTable();
    }
  }

  candidateAddButton.addEventListener("click", () => {
    addCandidates(candidateTickerInput.value);
    candidateTickerInput.value = "";
  });
})();
