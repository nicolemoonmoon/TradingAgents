(function () {
  "use strict";

  const POLL_INTERVAL_MS = 2000;
  const TERMINAL_STATUSES = new Set(["completed", "failed"]);
  const STATUS_CLASSES = ["status-queued", "status-running", "status-completed", "status-failed"];

  const el = (id) => document.getElementById(id);

  const modeNew = el("mode-new");
  const modeLoad = el("mode-load");
  const newRunForm = el("new-run-form");
  const loadRunForm = el("load-run-form");
  const startButton = el("start-button");
  const resetButton = el("reset-button");
  const loadRunButton = el("load-run-button");
  const runIdInput = el("run-id-input");
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
  }

  modeNew.addEventListener("change", () => setMode("new"));
  modeLoad.addEventListener("change", () => setMode("load"));

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

  function renderFinalDecision(runId, manifest) {
    traderActionLabel.textContent = manifest.trader_action ?? "(none)";
    draftRatingLabel.textContent = manifest.draft_rating ?? "(none)";
    dataQualityFlagsLabel.textContent =
      manifest.data_quality_flags && manifest.data_quality_flags.length
        ? manifest.data_quality_flags.join(", ")
        : "(none)";
    reportLink.href = `/api/runs/${encodeURIComponent(runId)}/reports/complete_report`;
    finalDecision.hidden = false;
  }

  async function fetchJson(url) {
    const resp = await fetch(url);
    return { resp, body: resp.ok ? await resp.json() : null };
  }

  async function refreshRun(runId) {
    const { resp: statusResp, body: status } = await fetchJson(
      `/api/runs/${encodeURIComponent(runId)}/status`
    );
    if (!statusResp.ok) {
      stopPolling();
      showError(`Run ${runId} not found.`);
      return;
    }

    clearError();
    runView.hidden = false;
    runIdLabel.textContent = runId;
    setStatusLabel(status.analysis_status);
    strategyProfileLabel.textContent = status.strategy_profile ?? "(none)";
    renderAgents(status.agents);

    const { body: events } = await fetchJson(`/api/runs/${encodeURIComponent(runId)}/events`);
    if (events) {
      renderEvents(events);
    }

    if (TERMINAL_STATUSES.has(status.analysis_status)) {
      stopPolling();
      startButton.hidden = true;
      resetButton.hidden = false;
      if (status.analysis_status === "completed") {
        const { body: manifest } = await fetchJson(
          `/api/runs/${encodeURIComponent(runId)}/manifest`
        );
        if (manifest) {
          renderFinalDecision(runId, manifest);
        }
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
      const strategyProfileValue = el("strategy-profile-input").value.trim();
      const payload = {
        ticker: el("ticker-input").value.trim(),
        analysis_date: el("analysis-date-input").value,
        selected_analysts: collectSelectedAnalysts(),
        quick_model: el("quick-model-input").value.trim(),
        deep_model: el("deep-model-input").value.trim(),
        strategy_profile: strategyProfileValue === "" ? null : strategyProfileValue,
      };
      const resp = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await resp.json();
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
})();
