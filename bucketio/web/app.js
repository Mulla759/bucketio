"use strict";

/* BucketIO static frontend — vanilla ES2020, no dependencies.
   Talks to the FastAPI app from bucketio serve (Pass 4 backend). */

const FILE_MODE = typeof location !== "undefined" && location.protocol === "file:";
const FILE_MODE_MESSAGE =
  "This page was opened directly from disk, so the API is unreachable. " +
  "Run `bucketio serve` and open http://127.0.0.1:8080/ instead.";

const STATUS_CLASS = {
  valid: "valid",
  invalid: "invalid",
  catch_all: "catch-all",
  risky: "risky",
  pattern_guess: "pattern-guess",
  unverified: "grey",
  unknown: "grey",
  no_domain: "grey",
  not_found: "grey",
  error: "grey",
};

const state = {
  q: "",
  status: "",
  limit: 25,
  offset: 0,
  total: 0,
  rows: [],
  selectedId: null,
};

let bannerTimer = null;

/* ---------- tiny DOM helpers (textContent only, no innerHTML) ---------- */

function $id(id) {
  return document.getElementById(id);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function clear(node) {
  if (node) node.textContent = "";
}

/* ---------- formatting ---------- */

function fmtText(value) {
  if (value === undefined || value === null || value === "") return "-";
  return String(value);
}

function fmtInt(value) {
  const n = Number(value);
  return Number.isFinite(n) ? String(Math.trunc(n)) : "-";
}

function fmtConfidence(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(0)}%` : "-";
}

function fmtUsd(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `$${n.toFixed(2)}` : "-";
}

function fmtWhen(value) {
  if (value === undefined || value === null || value === "") return "-";
  let raw = String(value);
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(raw)) raw = `${raw.replace(" ", "T")}Z`;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function statusClass(status) {
  const key = String(status === undefined || status === null ? "" : status).toLowerCase();
  return STATUS_CLASS[key] || "grey";
}

function pill(status) {
  const label = status === undefined || status === null || status === "" ? "unknown" : String(status);
  return el("span", `pill pill-${statusClass(label)}`, label);
}

function contactName(row) {
  if (!row) return "-";
  if (row.name) return String(row.name);
  const parts = [];
  for (const key of ["first_name", "middle_name", "last_name"]) {
    if (row[key]) parts.push(String(row[key]));
  }
  if (parts.length) return parts.join(" ");
  if (row.full_name) return String(row.full_name);
  return "-";
}

function companyName(row) {
  if (!row) return "-";
  return fmtText(row.company_name || row.company);
}

function contactRoute(row) {
  if (!row) return "-";
  return fmtText(row.route || row.last_route);
}

/* ---------- banner ---------- */

function showBanner(message, kind) {
  const banner = $id("banner");
  if (!banner) return;
  const text = $id("banner-message");
  if (text) text.textContent = String(message);
  banner.className = `banner banner-${kind || "info"}`;
  banner.hidden = false;
  if (bannerTimer) clearTimeout(bannerTimer);
  if (kind === "ok") bannerTimer = setTimeout(hideBanner, 4000);
}

function hideBanner() {
  const banner = $id("banner");
  if (!banner) return;
  banner.hidden = true;
  const text = $id("banner-message");
  if (text) text.textContent = "";
}

/* ---------- API ---------- */

async function api(path, opts) {
  if (FILE_MODE) throw new Error(FILE_MODE_MESSAGE);
  const options = opts || {};
  const init = {
    method: options.method || "GET",
    headers: { Accept: "application/json" },
  };
  if (options.body !== undefined && options.body !== null) {
    init.body = options.body;
    if (!(options.body instanceof FormData)) {
      init.headers["Content-Type"] = "application/json";
    }
  }
  if (options.signal) init.signal = options.signal;

  let response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    throw new Error(`Network error calling ${path}: ${err && err.message ? err.message : err}`);
  }

  let text = "";
  try {
    text = await response.text();
  } catch (err) {
    throw new Error(`Could not read the response from ${path}.`);
  }

  let json = null;
  if (text) {
    try {
      json = JSON.parse(text);
    } catch (err) {
      json = null;
    }
  }

  if (!response.ok) {
    let detail = "";
    if (json && typeof json === "object") {
      detail = json.detail || json.error || json.message || "";
    }
    if (!detail && text) detail = text.slice(0, 300);
    throw new Error(detail ? String(detail) : `HTTP ${response.status} ${response.statusText || ""}`.trim());
  }

  return json;
}

/* ---------- fetch result card (spec 2.5 keys) ---------- */

function renderResult(json) {
  const box = $id("result");
  if (!box) return;
  clear(box);
  if (!json || typeof json !== "object") {
    box.hidden = true;
    return;
  }

  const card = el("div", "result-card");

  const head = el("div", "result-head");
  head.append(el("h3", "result-title", `${fmtText(json.name)} · ${fmtText(json.company)}`));
  if (json.contact_id !== undefined && json.contact_id !== null) {
    head.append(el("span", "result-id", `#${fmtInt(json.contact_id)}`));
  }
  card.append(head);

  const emailRow = el("div", "result-email");
  emailRow.append(el("span", "result-email-value", fmtText(json.email)));
  emailRow.append(pill(json.verification_status));
  card.append(emailRow);

  const grid = el("dl", "result-grid");
  const add = (label, value) => {
    grid.append(el("dt", "", label));
    grid.append(el("dd", "", value));
  };

  add("Domain", fmtText(json.domain));
  add("High-pattern email", fmtText(json.high_pattern_email));
  add("Confidence", fmtConfidence(json.confidence));
  add("Route", fmtText(json.route));

  const calls = json.treg_calls && typeof json.treg_calls === "object" ? json.treg_calls : {};
  add("Treg calls", `find ${fmtInt(calls.find)} · verify ${fmtInt(calls.verify)}`);
  add("Seen", fmtInt(json.seen_count));
  add("Est. cost saved", fmtUsd(json.est_cost_saved));

  grid.append(el("dt", "", "Alternates"));
  const altDd = el("dd", "");
  const alternates = Array.isArray(json.alternates) ? json.alternates : [];
  if (!alternates.length) {
    altDd.textContent = "-";
  } else {
    for (const alt of alternates) altDd.append(el("span", "chip", String(alt)));
  }
  grid.append(altDd);

  card.append(grid);
  box.append(card);
  box.hidden = false;
}

/* ---------- contacts table ---------- */

function renderTable(rows) {
  const body = $id("contacts-body");
  if (!body) return;
  clear(body);
  const items = Array.isArray(rows) ? rows : [];

  for (const row of items) {
    const tr = el("tr", "contact-row");
    const id = row && row.id !== undefined && row.id !== null ? String(row.id) : "";
    tr.dataset.id = id;
    tr.tabIndex = 0;
    if (state.selectedId !== null && String(state.selectedId) === id) {
      tr.classList.add("is-selected");
    }

    tr.append(el("td", "", contactName(row)));
    tr.append(el("td", "", companyName(row)));
    tr.append(el("td", "email", fmtText(row && row.email)));
    tr.append(el("td", "email", fmtText(row && row.high_pattern_email)));

    const statusTd = el("td", "");
    statusTd.append(pill(row && row.verification_status));
    tr.append(statusTd);

    tr.append(el("td", "", fmtConfidence(row && row.confidence)));
    tr.append(el("td", "", fmtInt(row && row.seen_count)));
    tr.append(el("td", "", fmtWhen(row && row.last_verified_at)));
    tr.append(el("td", "", contactRoute(row)));

    body.append(tr);
  }

  const empty = $id("table-empty");
  if (empty) empty.hidden = items.length > 0;
}

function updatePager(shown) {
  const info = $id("page-info");
  const prev = $id("prev-page");
  const next = $id("next-page");
  const total = Number(state.total);
  const count = Number.isFinite(total) ? total : 0;

  if (info) {
    info.textContent = count > 0 ? `Showing ${state.offset + 1}–${state.offset + shown} of ${count}` : "No contacts";
  }
  if (prev) prev.disabled = FILE_MODE || state.offset <= 0;
  if (next) next.disabled = FILE_MODE || state.offset + state.limit >= count;
}

async function loadContacts() {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.status) params.set("status", state.status);
  params.set("limit", String(state.limit));
  params.set("offset", String(state.offset));

  try {
    const data = await api(`/api/contacts?${params.toString()}`);
    let items = [];
    if (data && Array.isArray(data.items)) items = data.items;
    else if (Array.isArray(data)) items = data;
    const total = data && Number(data.total);
    state.total = Number.isFinite(total) ? total : items.length;
    state.rows = items;
    renderTable(items);
    updatePager(items.length);
  } catch (err) {
    showBanner(`Could not load contacts: ${err.message}`, "error");
  }
}

/* ---------- detail panel ---------- */

function renderLookups(lookups) {
  const wrap = el("div", "table-wrap");
  const table = el("table", "lookups-table");
  const thead = el("thead");
  const headRow = el("tr");
  for (const label of ["When", "Route", "Input", "Result email", "Status", "Confidence", "Cost", "Saved", "Latency", "Forced"]) {
    headRow.append(el("th", "", label));
  }
  thead.append(headRow);

  const tbody = el("tbody");
  for (const lookup of lookups) {
    const tr = el("tr");
    tr.append(el("td", "", fmtWhen(lookup && lookup.created_at)));
    tr.append(el("td", "", fmtText(lookup && lookup.route)));
    tr.append(el("td", "", `${fmtText(lookup && lookup.input_name)} @ ${fmtText(lookup && lookup.input_company)}`));
    tr.append(el("td", "email", fmtText(lookup && lookup.result_email)));

    const statusTd = el("td", "");
    statusTd.append(pill(lookup && lookup.result_status));
    tr.append(statusTd);

    tr.append(el("td", "", fmtConfidence(lookup && lookup.confidence)));
    tr.append(el("td", "", fmtUsd(lookup && lookup.cost_usd)));
    tr.append(el("td", "", fmtUsd(lookup && lookup.est_saved_usd)));
    const latency = Number(lookup && lookup.latency_ms);
    tr.append(el("td", "", Number.isFinite(latency) ? `${fmtInt(latency)} ms` : "-"));
    tr.append(el("td", "", lookup && lookup.forced ? "yes" : "no"));
    tbody.append(tr);
  }

  table.append(thead, tbody);
  wrap.append(table);
  return wrap;
}

async function showDetail(id) {
  if (id === undefined || id === null || id === "") return;
  const panel = $id("detail");
  const body = $id("detail-body");
  if (!panel || !body) return;

  try {
    const data = await api(`/api/contacts/${encodeURIComponent(id)}`);
    const contact = (data && data.contact) || {};
    const lookups = data && Array.isArray(data.lookups) ? data.lookups : [];

    clear(body);

    const grid = el("dl", "detail-grid");
    const add = (label, value, node) => {
      grid.append(el("dt", "", label));
      const dd = el("dd", "");
      if (node) dd.append(node);
      else dd.textContent = fmtText(value);
      grid.append(dd);
    };

    add("Name", contactName(contact));
    add("Company", companyName(contact));
    add("Domain", contact.domain || contact.company_domain);
    add("Email", null, (() => {
      const holder = el("span", "");
      holder.append(el("span", "email", fmtText(contact.email)), " ", pill(contact.verification_status));
      return holder;
    })());
    add("High-pattern email", contact.high_pattern_email);
    add("Confidence", fmtConfidence(contact.confidence));
    add("Seen", fmtInt(contact.seen_count));
    add("Email source", contact.email_source);
    add("Pattern", contact.email_pattern);
    add("First seen", fmtWhen(contact.first_seen_at));
    add("Last seen", fmtWhen(contact.last_seen_at));
    add("Last verified", fmtWhen(contact.last_verified_at));
    if (contact.do_not_contact !== undefined) {
      add("Do not contact", contact.do_not_contact ? "yes" : "no");
    }
    body.append(grid);

    body.append(el("h3", "detail-subhead", `Lookup history (${lookups.length})`));
    if (!lookups.length) {
      body.append(el("p", "empty-note", "No lookups recorded for this contact."));
    } else {
      body.append(renderLookups(lookups));
    }

    panel.hidden = false;
    state.selectedId = id;
    highlightSelected(id);
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showBanner(`Could not load contact #${fmtText(id)}: ${err.message}`, "error");
  }
}

function highlightSelected(id) {
  const body = $id("contacts-body");
  if (!body) return;
  for (const tr of body.querySelectorAll("tr[data-id]")) {
    tr.classList.toggle("is-selected", tr.dataset.id === String(id));
  }
}

/* ---------- report ---------- */

function findCallsAvoided(report, treg) {
  const direct = report.find_calls_avoided;
  if (direct !== undefined && direct !== null) return direct;
  const fetches = Number(report.fetches);
  const finds = Number(treg.find_calls);
  if (Number.isFinite(fetches) && Number.isFinite(finds)) return Math.max(0, fetches - finds);
  return null;
}

function layaAgreement(laya) {
  if (laya.agreement === undefined || laya.agreement === null) return "-";
  const n = Number(laya.agreement);
  const pct = Number.isFinite(n) ? `${(n <= 1 ? n * 100 : n).toFixed(0)}%` : String(laya.agreement);
  const samples = Number(laya.samples);
  return Number.isFinite(samples) ? `${pct} (${samples})` : pct;
}

async function loadReport() {
  const setStat = (id, value) => {
    const node = $id(id);
    if (node) node.textContent = value === undefined || value === null ? "-" : String(value);
  };
  try {
    const report = await api("/api/report");
    const data = report && typeof report === "object" ? report : {};
    const routes = data.routes && typeof data.routes === "object" ? data.routes : {};
    const treg = data.treg && typeof data.treg === "object" ? data.treg : {};
    const laya = data.laya && typeof data.laya === "object" ? data.laya : {};

    setStat("stat-fetches", fmtInt(data.fetches));
    setStat("stat-find-avoided", fmtInt(findCallsAvoided(data, treg)));
    setStat("stat-verify-calls", fmtInt(treg.verify_calls));
    setStat("stat-saved", fmtUsd(data.est_saved_usd));
    setStat("stat-laya", layaAgreement(laya));

    if (Object.keys(routes).length) {
      const summary = Object.keys(routes)
        .map((key) => `${key}: ${fmtInt(routes[key])}`)
        .join(" · ");
      const strip = $id("report");
      if (strip) strip.title = summary;
    }
  } catch (err) {
    showBanner(`Could not load the report: ${err.message}`, "error");
  }
}

/* ---------- CSV import ---------- */

async function importCsv(file) {
  if (!file) {
    showBanner("Choose a CSV file first.", "warn");
    return;
  }
  const form = new FormData();
  form.append("file", file);

  try {
    const result = await api("/api/import", { method: "POST", body: form });
    const data = result && typeof result === "object" ? result : {};
    const imported = data.imported !== undefined ? data.imported : data.count;
    if (imported !== undefined && imported !== null) {
      showBanner(`Imported ${fmtInt(imported)} row(s) from ${file.name}.`, "ok");
    } else {
      showBanner(`Imported ${file.name}.`, "ok");
    }
    const input = $id("csv-file");
    if (input) input.value = "";
    state.offset = 0;
    await Promise.all([loadContacts(), loadReport()]);
  } catch (err) {
    showBanner(`Import failed: ${err.message}`, "error");
  }
}

/* ---------- file:// guard ---------- */

function disableApiControls() {
  for (const node of document.querySelectorAll("[data-api]")) {
    if (node.tagName === "A") {
      node.removeAttribute("href");
      node.classList.add("is-disabled");
      node.setAttribute("aria-disabled", "true");
    } else {
      node.disabled = true;
    }
  }
  for (const node of document.querySelectorAll('input[type="file"], input[type="search"], select')) {
    node.disabled = true;
  }
}

/* ---------- wiring ---------- */

function debounce(fn, wait) {
  let timer = null;
  return function debounced(...args) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn.apply(this, args);
    }, wait);
  };
}

function init() {
  const bannerClose = $id("banner-close");
  if (bannerClose) bannerClose.addEventListener("click", hideBanner);

  const fetchForm = $id("fetch-form");
  const nameInput = $id("fetch-name");
  const companyInput = $id("fetch-company");
  const forceInput = $id("fetch-force");
  const fetchSubmit = $id("fetch-submit");

  if (fetchForm) {
    fetchForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = nameInput ? nameInput.value.trim() : "";
      const company = companyInput ? companyInput.value.trim() : "";
      if (!name || !company) {
        showBanner("Name and company are both required.", "warn");
        return;
      }
      if (fetchSubmit) {
        fetchSubmit.disabled = true;
        fetchSubmit.textContent = "Fetching…";
      }
      try {
        const json = await api("/api/fetch", {
          method: "POST",
          body: JSON.stringify({ name, company, force: !!(forceInput && forceInput.checked) }),
        });
        renderResult(json);
        showBanner(`Fetched ${name} at ${company}.`, "ok");
        state.offset = 0;
        await Promise.all([loadContacts(), loadReport()]);
      } catch (err) {
        showBanner(`Fetch failed: ${err.message}`, "error");
      } finally {
        if (fetchSubmit) {
          fetchSubmit.disabled = FILE_MODE;
          fetchSubmit.textContent = "Fetch";
        }
      }
    });
  }

  const search = $id("search");
  if (search) {
    search.addEventListener("input", debounce(() => {
      state.q = search.value.trim();
      state.offset = 0;
      loadContacts();
    }, 200));
  }

  const statusFilter = $id("status-filter");
  if (statusFilter) {
    statusFilter.addEventListener("change", () => {
      state.status = statusFilter.value;
      state.offset = 0;
      loadContacts();
    });
  }

  const prev = $id("prev-page");
  if (prev) {
    prev.addEventListener("click", () => {
      if (state.offset <= 0) return;
      state.offset = Math.max(0, state.offset - state.limit);
      loadContacts();
    });
  }

  const next = $id("next-page");
  if (next) {
    next.addEventListener("click", () => {
      if (state.offset + state.limit >= state.total) return;
      state.offset += state.limit;
      loadContacts();
    });
  }

  const tbody = $id("contacts-body");
  if (tbody) {
    const activate = (event) => {
      const tr = event.target.closest ? event.target.closest("tr[data-id]") : null;
      if (!tr || !tr.dataset.id) return;
      showDetail(tr.dataset.id);
    };
    tbody.addEventListener("click", activate);
    tbody.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      activate(event);
    });
  }

  const detailClose = $id("detail-close");
  if (detailClose) {
    detailClose.addEventListener("click", () => {
      const panel = $id("detail");
      if (panel) panel.hidden = true;
      state.selectedId = null;
      highlightSelected("");
    });
  }

  const importForm = $id("import-form");
  if (importForm) {
    importForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const input = $id("csv-file");
      const file = input && input.files && input.files[0] ? input.files[0] : null;
      importCsv(file);
    });
  }

  const reportRefresh = $id("report-refresh");
  if (reportRefresh) reportRefresh.addEventListener("click", loadReport);

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event && event.reason;
    showBanner(`Unexpected error: ${reason && reason.message ? reason.message : reason}`, "error");
  });

  if (FILE_MODE) {
    disableApiControls();
    showBanner(FILE_MODE_MESSAGE, "warn");
    return;
  }

  loadContacts();
  loadReport();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
