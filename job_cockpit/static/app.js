const state = {
  data: null,
  selectedJobId: null,
  currentView: "dashboard",
  hiddenStatuses: new Set(["applied", "skipped", "rejected"]),
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const STATUS_LABELS = {
  new: "Not applied",
  scored: "Scored",
  ready_to_apply: "Ready",
  applied: "Applied",
  skipped: "Skipped",
  rejected: "Rejected",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    try {
      const payload = JSON.parse(text);
      throw new Error(payload.error || payload.message || response.statusText);
    } catch (error) {
      if (error instanceof SyntaxError) {
        throw new Error(text || response.statusText);
      }
      throw error;
    }
  }
  return response.json();
}

async function refresh() {
  state.data = await api("/api/state");
  render();
}

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.add("show");
  window.setTimeout(() => el.classList.remove("show"), 2800);
}

async function openExternalUrl(url) {
  if (!url) return;
  try {
    await api("/api/open-url", {
      method: "POST",
      body: JSON.stringify({url}),
    });
    toast("Opened in default browser");
  } catch (error) {
    window.open(url, "_blank", "noreferrer");
    toast(error.message || "Opened in this browser");
  }
}

function render() {
  renderStats();
  renderStatusExclusions();
  renderApplyQueue();
  renderJobs();
  renderDetail();
  renderProfile();
  renderSources();
  renderWorkflow();
  renderMeetings();
  renderActivity();
  renderAutoApplies();
}

function renderStats() {
  const jobs = state.data.jobs || [];
  const ready = jobs.filter((job) => job.status === "ready_to_apply").length;
  const avg = jobs.length ? Math.round(jobs.reduce((sum, job) => sum + Number(job.match_score || 0), 0) / jobs.length) : 0;
  $("#stat-jobs").textContent = jobs.length;
  $("#stat-ready").textContent = ready;
  $("#stat-score").textContent = avg;
}

function renderApplyQueue() {
  const summary = $("#apply-queue-summary");
  if (!summary) return;
  const jobs = applyQueue();
  const installed = Boolean(state.data.assisted_apply?.playwright_installed);
  const autoSubmit = Boolean(state.data.workflow?.auto_submit_allowed);
  summary.textContent = `${jobs.length} ready with URL${autoSubmit ? " - auto ON" : ""}${installed ? "" : " - setup needed"}`;
  summary.classList.toggle("needs-setup", !installed);
  summary.classList.toggle("auto-on", autoSubmit && installed);
}

function renderJobs() {
  const list = $("#job-list");
  const filter = $("#status-filter").value;
  const jobs = rankJobs((state.data.jobs || []).filter((job) => {
    const status = job.status || "new";
    const matchesStatus = filter === "all" || status === filter;
    const visibleByExclude = filter !== "all" || !state.hiddenStatuses.has(status);
    return matchesStatus && visibleByExclude;
  }));
  if (!jobs.length) {
    list.innerHTML = `<div class="empty-state"><div><h2>No jobs yet</h2><p>Add a job description or configure sources, then run Daily Review.</p></div></div>`;
    return;
  }
  list.innerHTML = jobs.map((job) => {
    const score = Number(job.match_score || 0);
    const scoreClass = score < 55 ? "low" : score < 75 ? "mid" : "";
    const selected = job.id === state.selectedJobId ? "selected" : "";
    const meta = [job.company, job.location, job.remote, job.salary].filter(Boolean).join(" - ");
    return `
      <article class="job-row ${selected}" data-job-id="${job.id}">
        <div class="score ${scoreClass}">${score}</div>
        <div class="job-main">
          <div class="job-title">${escapeHtml(job.title)}</div>
          <div class="job-meta">${escapeHtml(meta || "No company/location yet")}</div>
          <div class="job-notes">${escapeHtml(job.match_notes || "")}</div>
        </div>
        <div class="${statusClass(job.status)}">${escapeHtml(statusLabel(job.status))}</div>
      </article>
    `;
  }).join("");
  $$(".job-row").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedJobId = Number(row.dataset.jobId);
      renderJobs();
      renderDetail();
    });
  });
}

function rankJobs(jobs) {
  return [...jobs].sort((a, b) => {
    const scoreDelta = Number(b.match_score || 0) - Number(a.match_score || 0);
    if (scoreDelta) return scoreDelta;
    return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
  });
}

function renderDetail() {
  const pane = $("#detail-pane");
  const job = selectedJob();
  if (!job) {
    pane.innerHTML = `
      <div class="empty-detail">
        <h2>Select a job</h2>
        <p>Open a candidate to review score, draft text, and the form filler.</p>
      </div>
    `;
    return;
  }
  const url = job.url
    ? `<a class="external-job-link" href="${escapeAttr(job.url)}" data-action="open-url" rel="noreferrer">${escapeHtml(job.url)}</a>`
    : "No URL";
  const resumeLink = job.resume_variant
    ? `<p class="job-meta">Resume: <a href="/api/resumes/${escapeAttr(resumeFileName(job.resume_variant))}" target="_blank" rel="noreferrer">${escapeHtml(job.resume_variant)}</a></p>`
    : job.resume_attachment
      ? `<p class="job-meta">Resume fallback: ${escapeHtml(job.resume_attachment)}</p>`
      : `<p class="job-meta">Resume: not generated yet</p>`;
  const copyData = buildApplicationData(job);
  pane.innerHTML = `
    <section class="detail-section">
      <h2>${escapeHtml(job.title)}</h2>
      <p class="job-meta">${escapeHtml([job.company, job.location, job.remote].filter(Boolean).join(" - "))}</p>
      <p class="job-meta">${url}</p>
      ${resumeLink}
      <div class="detail-actions">
        <button class="button primary" data-action="assist-apply">Apply Assist</button>
        <button class="button primary" data-action="draft">Generate Package</button>
        <button class="button secondary" data-action="resume">PDF Only</button>
        <button class="button secondary" data-action="filler">Filler</button>
        <button class="button status-action status-ready_to_apply" data-status="ready_to_apply">Ready</button>
        <button class="button status-action status-applied" data-status="applied">Applied</button>
        <button class="button status-action status-rejected" data-status="rejected">Reject</button>
        <button class="button status-action status-skipped" data-status="skipped">Skip</button>
        <button class="button status-action status-new" data-status="new">Not applied</button>
      </div>
      <div class="${statusClass(job.status)}">${escapeHtml(statusLabel(job.status))} - score ${Number(job.match_score || 0)}</div>
    </section>
    <section class="detail-section">
      <h2>Fit Notes</h2>
      <p>${escapeHtml(job.match_notes || "No score notes yet.")}</p>
    </section>
    <section class="detail-section">
      <h2>Cover Letter</h2>
      <textarea class="codebox" readonly>${escapeHtml(job.cover_letter || "Generate a draft first.")}</textarea>
    </section>
    <section class="detail-section">
      <h2>Application Draft</h2>
      <textarea class="codebox" readonly>${escapeHtml(job.draft_text || "Generate a draft first.")}</textarea>
    </section>
    <section class="detail-section">
      <div class="section-title-row">
        <h2>Copy Data</h2>
        <button class="button secondary" id="copy-application-data">Copy</button>
      </div>
      <textarea class="codebox compact" id="application-data" readonly>${escapeHtml(copyData)}</textarea>
    </section>
    <section class="detail-section" id="filler-output" hidden>
      <h2>Safe Filler Script</h2>
      <p class="job-meta">Run this in your browser console on the application page. It fills known fields, pauses on CAPTCHA, and never clicks submit.</p>
      <textarea class="codebox" id="filler-script" readonly></textarea>
      <button class="button secondary" id="copy-filler">Copy Script</button>
    </section>
  `;
  pane.querySelector('[data-action="assist-apply"]').addEventListener("click", () => assistSelected());
  pane.querySelector('[data-action="draft"]').addEventListener("click", () => draftSelected());
  pane.querySelector('[data-action="resume"]').addEventListener("click", () => generateResume());
  pane.querySelector('[data-action="filler"]').addEventListener("click", () => loadFiller());
  const openUrlLink = pane.querySelector('[data-action="open-url"]');
  if (openUrlLink) {
    openUrlLink.addEventListener("click", (event) => {
      event.preventDefault();
      openExternalUrl(job.url);
    });
  }
  pane.querySelector("#copy-application-data").addEventListener("click", async () => {
    await navigator.clipboard.writeText(copyData);
    toast("Application data copied");
  });
  pane.querySelectorAll("[data-status]").forEach((button) => {
    button.addEventListener("click", () => updateStatus(button.dataset.status));
  });
}

function renderProfile() {
  const form = $("#profile-form");
  const profile = state.data.profile || {};
  for (const el of Array.from(form.elements)) {
    if (!el.name) continue;
    const value = profile[el.name];
    if (Array.isArray(value)) {
      el.value = value.join("\n");
    } else {
      el.value = value || "";
    }
  }
}

function renderSources() {
  $("#sources-json").value = JSON.stringify(state.data.sources || [], null, 2);
}

function renderWorkflow() {
  const form = $("#workflow-form");
  const workflow = state.data.workflow || {};
  for (const el of Array.from(form.elements)) {
    if (!el.name) continue;
    if (el.type === "checkbox") {
      el.checked = Boolean(workflow[el.name]);
    } else if (Array.isArray(workflow[el.name])) {
      el.value = workflow[el.name].join("\n");
    } else {
      el.value = workflow[el.name] ?? "";
    }
  }
}

function renderMeetings() {
  const list = $("#meeting-list");
  const meetings = state.data.meetings || [];
  if (!meetings.length) {
    list.innerHTML = `<div class="stack-item">No meetings yet. Add interview times here or export/import ICS into Google Calendar.</div>`;
    return;
  }
  list.innerHTML = meetings.map((meeting) => `
    <div class="stack-item">
      <strong>${escapeHtml(meeting.title)}</strong>
      <div class="job-meta">${escapeHtml([meeting.company, meeting.starts_at, meeting.location].filter(Boolean).join(" - "))}</div>
      <p>${escapeHtml(meeting.notes || "")}</p>
    </div>
  `).join("");
}

function renderActivity() {
  const list = $("#activity-list");
  if (!list) return;
  const activity = state.data.activity || [];
  if (!activity.length) {
    list.innerHTML = `<div class="activity-item">No activity yet.</div>`;
    return;
  }
  list.innerHTML = activity.slice(0, 12).map((item) => {
    const meta = item.meta || {};
    const details = [
      meta.job_id ? `job #${meta.job_id}` : "",
      meta.submitted !== undefined ? `submitted ${meta.submitted}` : "",
      meta.skipped !== undefined ? `needs review ${meta.skipped}` : "",
      meta.pid ? `pid ${meta.pid}` : "",
    ].filter(Boolean).join(" - ");
    return `
      <div class="activity-item level-${escapeAttr(item.level || "info")}">
        <div>
          <strong>${escapeHtml(item.message || "")}</strong>
          <span>${escapeHtml(details)}</span>
        </div>
        <time>${escapeHtml(formatActivityTime(item.ts))}</time>
      </div>
    `;
  }).join("");
}

function renderAutoApplies() {
  const list = $("#auto-apply-list");
  if (!list) return;
  const applications = state.data.auto_applications || [];
  const submitted = applications.filter((item) => item.outcome === "submitted").length;
  const needsReview = applications.filter((item) => item.outcome === "needs_review").length;
  $("#auto-stat-submitted").textContent = submitted;
  $("#auto-stat-review").textContent = needsReview;
  $("#auto-stat-total").textContent = applications.length;

  const filter = $("#auto-apply-filter").value;
  const visible = applications.filter((item) => filter === "all" || item.outcome === filter);
  if (!visible.length) {
    list.innerHTML = `
      <div class="empty-state">
        <div>
          <h2>No auto applies here</h2>
          <p>Run Auto Queue, then submitted and review-needed applications will appear here.</p>
        </div>
      </div>
    `;
    return;
  }
  list.innerHTML = visible.map((item) => {
    const selected = item.job_id === state.selectedJobId ? "selected" : "";
    const reason = item.outcome === "submitted"
      ? "Safe auto-submit clicked"
      : item.reason || "Needs manual review";
    const auditLink = item.audit_url
      ? `<a class="audit-link" href="${escapeAttr(item.audit_url)}" target="_blank" rel="noreferrer" data-no-row-select="true">Audit JSON</a>`
      : "";
    const meta = [
      item.company,
      `score ${Number(item.match_score || 0)}`,
      statusLabel(item.job_status),
      formatActivityTime(item.ts),
    ].filter(Boolean).join(" - ");
    return `
      <article class="auto-apply-row ${selected}" data-auto-job-id="${Number(item.job_id || 0)}">
        <div class="auto-apply-outcome ${autoOutcomeClass(item.outcome)}">${escapeHtml(autoOutcomeLabel(item.outcome))}</div>
        <div class="auto-apply-main">
          <div class="job-title">${escapeHtml(item.title || `Job #${item.job_id}`)}</div>
          <div class="job-meta">${escapeHtml(meta)}</div>
          <div class="job-notes">${escapeHtml(reason)} ${auditLink}</div>
        </div>
        <div class="${statusClass(item.job_status)}">${escapeHtml(statusLabel(item.job_status))}</div>
      </article>
    `;
  }).join("");
  $$(".auto-apply-row").forEach((row) => {
    row.addEventListener("click", () => {
      const jobId = Number(row.dataset.autoJobId);
      if (jobId) state.selectedJobId = jobId;
      renderAutoApplies();
      renderJobs();
      renderDetail();
    });
  });
  $$("[data-no-row-select]").forEach((link) => {
    link.addEventListener("click", (event) => event.stopPropagation());
  });
}

function selectedJob() {
  return (state.data.jobs || []).find((job) => job.id === state.selectedJobId);
}

function applyQueue() {
  return rankJobs((state.data.jobs || []).filter((job) => {
    const status = job.status || "new";
    return status === "ready_to_apply" && job.url && !state.hiddenStatuses.has(status);
  }));
}

function loadHiddenStatuses() {
  try {
    const saved = JSON.parse(localStorage.getItem("jobCockpitHiddenStatuses") || "null");
    if (Array.isArray(saved)) {
      state.hiddenStatuses = new Set([...saved, "applied", "skipped", "rejected"]);
    }
  } catch {
    state.hiddenStatuses = new Set(["applied", "skipped", "rejected"]);
  }
}

function saveHiddenStatuses() {
  localStorage.setItem("jobCockpitHiddenStatuses", JSON.stringify([...state.hiddenStatuses]));
}

function renderStatusExclusions() {
  $$("[data-hide-status]").forEach((input) => {
    input.checked = state.hiddenStatuses.has(input.dataset.hideStatus);
  });
}

function statusLabel(status) {
  return STATUS_LABELS[status || "new"] || status || "Not applied";
}

function statusClass(status) {
  const clean = String(status || "new").replace(/[^a-z0-9_-]/gi, "_");
  return `status-pill status-${clean}`;
}

function autoOutcomeLabel(outcome) {
  return outcome === "submitted" ? "Submitted" : "Needs review";
}

function autoOutcomeClass(outcome) {
  return outcome === "submitted" ? "submitted" : "needs-review";
}

function buildApplicationData(job) {
  const profile = state.data.profile || {};
  const name = [profile.first_name, profile.last_name].filter(Boolean).join(" ");
  const resume = job.resume_variant
    ? job.resume_variant
    : job.resume_attachment
      ? job.resume_attachment
      : profile.resume_path || "";
  return [
    `Name: ${name}`,
    `Email: ${profile.email || ""}`,
    `Phone: ${profile.phone || ""}`,
    `Location: ${profile.location || ""}`,
    `LinkedIn: ${profile.linkedin_url || ""}`,
    `GitHub: ${profile.github_url || ""}`,
    `Portfolio: ${profile.portfolio_url || ""}`,
    `Work authorization: ${profile.work_authorization || ""}`,
    `Salary expectation: ${profile.salary_expectation || ""}`,
    `Notice period: ${profile.notice_period || ""}`,
    `Target role: ${job.title || ""}`,
    `Company: ${job.company || ""}`,
    `Resume: ${resume}`,
  ].join("\n");
}

async function draftSelected() {
  const job = selectedJob();
  if (!job) return;
  const response = await api(`/api/jobs/${job.id}/draft`, {
    method: "POST",
    body: JSON.stringify({force_generate: true}),
  });
  state.data = response.state;
  toast("Application package generated");
  render();
}

async function loadFiller() {
  const job = selectedJob();
  if (!job) return;
  const response = await api(`/api/jobs/${job.id}/filler`, {method: "POST", body: "{}"});
  $("#filler-output").hidden = false;
  $("#filler-script").value = response.script;
  $("#copy-filler").addEventListener("click", async () => {
    await navigator.clipboard.writeText(response.script);
    toast("Filler script copied");
  }, {once: true});
}

async function assistSelected() {
  const job = selectedJob();
  if (!job) return;
  try {
    const response = await api(`/api/jobs/${job.id}/assist_apply`, {
      method: "POST",
      body: "{}",
    });
    state.data = response.state;
    state.selectedJobId = response.job.id;
    toast("Assisted browser launched");
    render();
  } catch (error) {
    toast(error.message || "Could not launch assisted apply");
  }
}

async function assistNext() {
  try {
    const response = await api("/api/apply/next", {
      method: "POST",
      body: "{}",
    });
    state.data = response.state;
    state.selectedJobId = response.job.id;
    toast("Next ready job opened in assisted browser");
    render();
  } catch (error) {
    toast(error.message || "No ready job to apply");
  }
}

async function autoQueue() {
  try {
    const response = await api("/api/apply/auto_queue", {
      method: "POST",
      body: "{}",
    });
    state.data = response.state;
    toast(response.message || "Safe auto-apply queue started");
    render();
    pollQueueProgress();
  } catch (error) {
    toast(error.message || "Could not start auto queue");
  }
}

function pollQueueProgress() {
  let attempts = 0;
  const timer = window.setInterval(async () => {
    attempts += 1;
    try {
      await refresh();
      const latest = (state.data.activity || [])[0];
      if (latest && /queue finished/i.test(latest.message || "")) {
        const meta = latest.meta || {};
        toast(`Auto queue finished: ${meta.submitted || 0} applied, ${meta.skipped || 0} need review`);
        window.clearInterval(timer);
      }
    } catch {
      window.clearInterval(timer);
    }
    if (attempts >= 30) {
      window.clearInterval(timer);
    }
  }, 3000);
}

async function generateResume() {
  const job = selectedJob();
  if (!job) return;
  const response = await api(`/api/jobs/${job.id}/resume`, {method: "POST", body: "{}"});
  state.data = response.state;
  state.selectedJobId = job.id;
  toast("Tailored resume generated");
  render();
  window.open(`/api/resumes/${resumeFileName(response.resume.relative_path)}`, "_blank", "noreferrer");
}

async function updateStatus(status) {
  const job = selectedJob();
  if (!job) return;
  const response = await api(`/api/jobs/${job.id}/status`, {
    method: "POST",
    body: JSON.stringify({status}),
  });
  state.data = response.state;
  toast(`Status set to ${status}`);
  render();
}

function resumeFileName(path) {
  return String(path || "").split(/[\\/]/).pop();
}

function formToProfile(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  for (const key of ["target_titles", "target_locations", "skills", "avoid_keywords"]) {
    data[key] = splitLines(data[key]);
  }
  return data;
}

function splitLines(value) {
  return String(value || "")
    .split(/\n|,|;/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formToObject(form) {
  const data = {};
  for (const el of Array.from(form.elements)) {
    if (!el.name) continue;
    if (el.type === "checkbox") {
      data[el.name] = el.checked;
    } else if (el.type === "number") {
      data[el.name] = Number(el.value);
    } else {
      data[el.name] = el.value;
    }
  }
  return data;
}

function workflowToObject(form) {
  const data = formToObject(form);
  data.search_queries = splitLines(data.search_queries);
  data.search_locations = splitLines(data.search_locations);
  data.target_seniority = splitLines(data.target_seniority);
  data.focus_role_families = splitLines(data.focus_role_families);
  data.auto_submit_safe_only = true;
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function formatActivityTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
}

function setupEvents() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.currentView = button.dataset.view;
      $$(".nav-item").forEach((item) => item.classList.toggle("active", item === button));
      $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${state.currentView}`));
    });
  });

  $("#status-filter").addEventListener("change", renderJobs);
  $("#auto-apply-filter").addEventListener("change", renderAutoApplies);

  $$("[data-hide-status]").forEach((input) => {
    input.addEventListener("change", () => {
      const status = input.dataset.hideStatus;
      if (input.checked) {
        state.hiddenStatuses.add(status);
      } else {
        state.hiddenStatuses.delete(status);
      }
      saveHiddenStatuses();
      renderJobs();
    });
  });

  $$(".segmented button").forEach((button) => {
    button.addEventListener("click", async () => {
      button.classList.add("active");
      try {
        const response = await api("/api/agents/run", {
          method: "POST",
          body: JSON.stringify({mode: button.dataset.agent}),
        });
        state.data = response.state;
        toast(response.message);
        render();
      } finally {
        button.classList.remove("active");
      }
    });
  });

  $("#apply-next").addEventListener("click", async () => {
    const button = $("#apply-next");
    button.classList.add("active");
    try {
      await assistNext();
    } finally {
      button.classList.remove("active");
    }
  });

  $("#refresh-state").addEventListener("click", () => refresh());
  $("#auto-applies-refresh").addEventListener("click", () => refresh());

  $("#auto-queue").addEventListener("click", async () => {
    const button = $("#auto-queue");
    button.classList.add("active");
    try {
      await autoQueue();
    } finally {
      button.classList.remove("active");
    }
  });

  $("#auto-applies-queue").addEventListener("click", async () => {
    const button = $("#auto-applies-queue");
    button.classList.add("active");
    try {
      await autoQueue();
    } finally {
      button.classList.remove("active");
    }
  });

  $("#open-add-job").addEventListener("click", () => $("#add-job-dialog").showModal());

  $("#add-job-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToObject(event.currentTarget);
    const response = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.data = response.state;
    state.selectedJobId = response.job.id;
    $("#add-job-dialog").close();
    event.currentTarget.reset();
    toast("Job added");
    render();
  });

  $("#profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.data = await api("/api/profile", {
      method: "POST",
      body: JSON.stringify(formToProfile(event.currentTarget)),
    });
    toast("Profile saved");
    render();
  });

  $("#save-sources").addEventListener("click", async () => {
    const sources = JSON.parse($("#sources-json").value || "[]");
    state.data = await api("/api/sources", {
      method: "POST",
      body: JSON.stringify({sources}),
    });
    toast("Sources saved");
    render();
  });

  $("#workflow-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.data = await api("/api/workflow", {
      method: "POST",
      body: JSON.stringify(workflowToObject(event.currentTarget)),
    });
    toast("Workflow saved");
    render();
  });

  $("#meeting-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const response = await api("/api/meetings", {
      method: "POST",
      body: JSON.stringify(formToObject(event.currentTarget)),
    });
    state.data = response.state;
    event.currentTarget.reset();
    toast("Meeting added");
    render();
  });
}

loadHiddenStatuses();
setupEvents();
refresh().catch((error) => {
  console.error(error);
  toast("Could not load Job Cockpit");
});
