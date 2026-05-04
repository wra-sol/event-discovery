const REVIEW_LIMIT = 50;
const CAL_LIMIT = 500;

const els = {
  btnAddSource: document.getElementById("btnAddSource"),
  btnRunFullCrawl: document.getElementById("btnRunFullCrawl"),
  siteConfigHeading: document.getElementById("siteConfigHeading"),
  siteConfigKeyReadonly: document.getElementById("siteConfigKeyReadonly"),
  siteConfigKeyCreateWrap: document.getElementById("siteConfigKeyCreateWrap"),
  siteConfigNewKey: document.getElementById("siteConfigNewKey"),
  status: document.getElementById("status"),
  navSites: document.getElementById("navSites"),
  navCalendar: document.getElementById("navCalendar"),
  navReview: document.getElementById("navReview"),
  panelSites: document.getElementById("panelSites"),
  panelCalendar: document.getElementById("panelCalendar"),
  panelReview: document.getElementById("panelReview"),
  sitesTbody: document.getElementById("sitesTbody"),
  sitesCheckAll: document.getElementById("sitesCheckAll"),
  sitesUncheckAll: document.getElementById("sitesUncheckAll"),
  discoveryPrefsForm: document.getElementById("discoveryPrefsForm"),
  discoveryPrefsSave: document.getElementById("discoveryPrefsSave"),
  discoveryPrefsError: document.getElementById("discoveryPrefsError"),
  discPositive: document.getElementById("discPositive"),
  discWard: document.getElementById("discWard"),
  discNegative: document.getElementById("discNegative"),
  discHorizon: document.getElementById("discHorizon"),
  discEnrichEnabled: document.getElementById("discEnrichEnabled"),
  discDelay: document.getElementById("discDelay"),
  discTimeout: document.getElementById("discTimeout"),
  discUserAgent: document.getElementById("discUserAgent"),
  discMaxDetail: document.getElementById("discMaxDetail"),
  calPrev: document.getElementById("calPrev"),
  calNext: document.getElementById("calNext"),
  calTitle: document.getElementById("calTitle"),
  calGrid: document.getElementById("calGrid"),
  calStatus: document.getElementById("calStatus"),
  calDetail: document.getElementById("calDetail"),
  calDetailTitle: document.getElementById("calDetailTitle"),
  calDetailList: document.getElementById("calDetailList"),
  q: document.getElementById("q"),
  source: document.getElementById("source"),
  minScore: document.getElementById("minScore"),
  reviewed: document.getElementById("reviewed"),
  showPastEvents: document.getElementById("showPastEvents"),
  tbody: document.getElementById("tbody"),
  prevPage: document.getElementById("prevPage"),
  nextPage: document.getElementById("nextPage"),
  pageInfo: document.getElementById("pageInfo"),
  siteConfigDialog: document.getElementById("siteConfigDialog"),
  siteConfigForm: document.getElementById("siteConfigForm"),
  siteConfigSourceKey: document.getElementById("siteConfigSourceKey"),
  siteConfigLabel: document.getElementById("siteConfigLabel"),
  siteConfigTypeSelect: document.getElementById("siteConfigTypeSelect"),
  siteConfigTypeSelectWrap: document.getElementById("siteConfigTypeSelectWrap"),
  siteConfigTypeCustomWrap: document.getElementById("siteConfigTypeCustomWrap"),
  siteConfigTypeCustom: document.getElementById("siteConfigTypeCustom"),
  siteConfigDynamicSimple: document.getElementById("siteConfigDynamicSimple"),
  siteConfigDynamicAdvanced: document.getElementById("siteConfigDynamicAdvanced"),
  siteConfigAdvancedBlock: document.getElementById("siteConfigAdvancedBlock"),
  siteConfigExpertBlock: document.getElementById("siteConfigExpertBlock"),
  siteConfigPrefsBlock: document.getElementById("siteConfigPrefsBlock"),
  sitePrefPositive: document.getElementById("sitePrefPositive"),
  sitePrefWard: document.getElementById("sitePrefWard"),
  sitePrefNegative: document.getElementById("sitePrefNegative"),
  sitePrefHorizon: document.getElementById("sitePrefHorizon"),
  sitePrefEnrichEnabled: document.getElementById("sitePrefEnrichEnabled"),
  sitePrefMaxDetail: document.getElementById("sitePrefMaxDetail"),
  sitePrefDelay: document.getElementById("sitePrefDelay"),
  sitePrefTimeout: document.getElementById("sitePrefTimeout"),
  sitePrefUserAgent: document.getElementById("sitePrefUserAgent"),
  sitePrefReset: document.getElementById("sitePrefReset"),
  siteConfigJsonExpert: document.getElementById("siteConfigJsonExpert"),
  siteConfigError: document.getElementById("siteConfigError"),
  siteConfigCancel: document.getElementById("siteConfigCancel"),
  siteConfigSave: document.getElementById("siteConfigSave"),
  siteDeleteDialog: document.getElementById("siteDeleteDialog"),
  siteDeleteLead: document.getElementById("siteDeleteLead"),
  siteDeleteEventsWrap: document.getElementById("siteDeleteEventsWrap"),
  siteDeleteEvents: document.getElementById("siteDeleteEvents"),
  siteDeleteEventsHint: document.getElementById("siteDeleteEventsHint"),
  siteDeleteCancel: document.getElementById("siteDeleteCancel"),
  siteDeleteConfirm: document.getElementById("siteDeleteConfirm"),
  sitesEmptyHint: document.getElementById("sitesEmptyHint"),
  addSourceQuickDialog: document.getElementById("addSourceQuickDialog"),
  addSourceQuickForm: document.getElementById("addSourceQuickForm"),
  addSourceQuickName: document.getElementById("addSourceQuickName"),
  addSourceQuickUrl: document.getElementById("addSourceQuickUrl"),
  addSourceQuickUseLlm: document.getElementById("addSourceQuickUseLlm"),
  addSourceQuickError: document.getElementById("addSourceQuickError"),
  addSourceQuickCancel: document.getElementById("addSourceQuickCancel"),
  addSourceQuickSubmit: document.getElementById("addSourceQuickSubmit"),
  addSourceQuickAdvanced: document.getElementById("addSourceQuickAdvanced"),
};

let config = { read_only: false, advanced_ui: false };
let reviewOffset = 0;
let reviewTotal = 0;
let reviewSearchTimer = null;
/** @type {string} API sort key: relevance | start_at | title | source | reviewed */
let reviewSortKey = "relevance";
/** @type {"asc" | "desc"} */
let reviewSortOrder = "desc";

/** @type {{ y: number, m: number }} month is 0–11 */
let calView = { y: new Date().getFullYear(), m: new Date().getMonth() };
/** @type {Map<string, object[]>} date YYYY-MM-DD to event rows */
let calEventsByDay = new Map();

let sitesDragId = null;
/** @type {object[] | null} */
let lastSitesRows = null;
/** @type {number | null} */
let siteRecheckingId = null;
/** @type {number | null} */
let siteConfigEditingId = null;
let siteConfigIsCreate = false;
/** @type {object | null} */
let accountDiscoveryDefaults = null;
/** @type {HTMLElement | null} */
let siteConfigOpener = null;
/** @type {number | null} */
let siteDeletingId = null;
/** @type {object | null} */
let siteDeletePending = null;
/** @type {object[]} */
let websiteSourceTypes = [];

function writesAllowed() {
  return !config.read_only;
}

async function fetchJson(url, options = {}) {
  const { authRedirect = true, ...fetchOpts } = options;
  const res = await fetch(url, {
    credentials: "include",
    ...fetchOpts,
    headers: {
      "Content-Type": "application/json",
      ...(fetchOpts.headers || {}),
    },
  });
  if (res.status === 401 && authRedirect) {
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const text = await res.text();
    let msg = text || res.statusText;
    try {
      const j = JSON.parse(text);
      if (typeof j.detail === "string") {
        msg = j.detail;
      } else if (Array.isArray(j.detail)) {
        msg = j.detail
          .map((d) => (d && typeof d.msg === "string" ? d.msg : JSON.stringify(d)))
          .join("; ");
      }
    } catch {
      /* keep msg */
    }
    throw new Error(msg);
  }
  return res.json();
}

function formatWhen(iso) {
  if (!iso) return "—";
  const s = String(iso).trim();
  const d = s.slice(0, 10);
  if (d.length === 10 && d[4] === "-" && d[7] === "-") {
    if (s.length > 10 && s[10] === "T") {
      const hm = s.slice(11, 16);
      if (hm && hm !== "00:00") return `${d} ${hm}`;
    }
    return d;
  }
  return s.slice(0, 16).replace("T", " ");
}

/** YYYY-MM-DD from Eventbrite-style listing snippets when structured start_at is missing. */
function approxDateFromSnippet(snippet) {
  if (!snippet) return null;
  const m = String(snippet).match(/Approx\.\s*date\s*hint:\s*(\d{4}-\d{2}-\d{2})/i);
  return m ? m[1] : null;
}

function formatWhenRange(startAt, endAt) {
  if (!startAt) return "—";
  const s = String(startAt).trim();
  const startFmt = formatWhen(s);
  if (!endAt || !String(endAt).trim()) return startFmt;
  const sDay = s.slice(0, 10);
  const eDay = String(endAt).trim().slice(0, 10);
  if (eDay.length === 10 && eDay !== sDay) {
    return `${startFmt} – ${formatWhen(String(endAt).trim())}`;
  }
  const et = String(endAt).trim();
  if (et.length > 10 && et[10] === "T") {
    const endHm = et.slice(11, 16);
    if (endHm && endHm !== "00:00") {
      const st = s;
      const startHm = st.length > 10 && st[10] === "T" ? st.slice(11, 16) : "";
      if (startHm && startHm !== "00:00") {
        if (startHm === endHm) return startFmt;
        return `${s.slice(0, 10)} ${startHm}–${endHm}`;
      }
      return `${startFmt} – ${endHm}`;
    }
  }
  return startFmt;
}

/** When / approx label for review table and meta line. */
function reviewWhenDisplay(ev) {
  const rawStart = ev.start_at && String(ev.start_at).trim();
  if (rawStart) {
    return { text: formatWhenRange(rawStart, ev.end_at), approx: false };
  }
  const hint = approxDateFromSnippet(ev.raw_snippet || "");
  if (hint) {
    let text = hint;
    const end = ev.end_at && String(ev.end_at).trim();
    if (end) {
      const eDay = end.slice(0, 10);
      if (eDay.length === 10 && eDay !== hint) {
        text = `${hint} – ${formatWhen(end)}`;
      }
    }
    return { text, approx: true };
  }
  return { text: "—", approx: false };
}

function setStatus(msg, isError = false) {
  els.status.textContent = msg;
  els.status.classList.toggle("error", isError);
}

function panelFromHash() {
  const h = (location.hash || "").replace(/^#/, "").toLowerCase();
  if (h === "sites" || h === "calendar" || h === "review") return h;
  return "review";
}

function showPanel(name) {
  const order = ["sites", "calendar", "review"];
  const panels = { sites: els.panelSites, calendar: els.panelCalendar, review: els.panelReview };
  const tabs = { sites: els.navSites, calendar: els.navCalendar, review: els.navReview };
  for (const k of order) {
    const el = panels[k];
    const tab = tabs[k];
    const active = k === name;
    el.hidden = !active;
    tab.classList.toggle("nav-tab-active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
    tab.tabIndex = active ? 0 : -1;
  }
  if (name === "sites") {
    void loadSites();
    void loadDiscoveryPrefs();
  }
  if (name === "calendar") loadCalendarMonth();
  if (name === "review") loadReviewEvents();
}

function navigateToPanel(name) {
  const nextHash = `#${name}`;
  if (location.hash !== nextHash) location.hash = nextHash;
  else showPanel(name);
}

async function loadConfig() {
  try {
    config = await fetchJson("/api/config");
    document.body.classList.toggle("advanced-ui", Boolean(config.advanced_ui));
    if (config.read_only) {
      const meta = document.querySelector(".global-meta");
      if (meta && !meta.querySelector(".readonly-banner")) {
        const banner = document.createElement("div");
        banner.className = "readonly-banner";
        banner.textContent =
          "This server is read-only (EVENTS_WEB_READ_ONLY). Writes to sites and reviews are disabled.";
        meta.insertBefore(banner, meta.firstChild);
      }
    }
    if (!config.auth_disabled) {
      const meta = document.querySelector(".global-meta");
      if (meta && !meta.querySelector(".logout-row")) {
        const row = document.createElement("p");
        row.className = "logout-row";
        const a = document.createElement("a");
        a.href = "#";
        a.className = "logout-link";
        a.textContent = "Log out";
        a.addEventListener("click", async (e) => {
          e.preventDefault();
          await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
          window.location.href = "/login";
        });
        row.appendChild(a);
        meta.appendChild(row);
      }
    }
  } catch (e) {
    setStatus(`Config failed: ${e.message}`, true);
  }
  refreshReadOnlyFormState();
}

function refreshReadOnlyFormState() {
  const ro = config.read_only;
  const discEls = [
    els.discPositive,
    els.discWard,
    els.discNegative,
    els.discHorizon,
    els.discEnrichEnabled,
    els.discDelay,
    els.discTimeout,
    els.discUserAgent,
    els.discMaxDetail,
    els.sitePrefPositive,
    els.sitePrefWard,
    els.sitePrefNegative,
    els.sitePrefHorizon,
    els.sitePrefEnrichEnabled,
    els.sitePrefMaxDetail,
    els.sitePrefDelay,
    els.sitePrefTimeout,
    els.sitePrefUserAgent,
  ];
  for (const el of discEls) {
    if (el) el.disabled = ro;
  }
  if (els.discoveryPrefsSave) els.discoveryPrefsSave.disabled = ro;
  if (els.sitePrefReset) els.sitePrefReset.disabled = ro;
  if (els.sitesCheckAll) els.sitesCheckAll.disabled = ro;
  if (els.sitesUncheckAll) els.sitesUncheckAll.disabled = ro;
}

async function loadSources() {
  try {
    const sources = await fetchJson("/api/sources");
    while (els.source && els.source.options.length > 1) {
      els.source.remove(1);
    }
    for (const s of sources) {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      els.source.appendChild(opt);
    }
  } catch {
    /* optional */
  }
}

// ——— Sites ———

function siteLabel(w) {
  const sl = w.source_label && String(w.source_label).trim();
  return sl || w.source_key;
}

function splitKeywords(s) {
  return String(s || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function joinKeywords(arr) {
  return Array.isArray(arr) ? arr.join(", ") : "";
}

function deepEqualDiscover(a, b) {
  if (a === b) return true;
  if (a == null || b == null) return a === b;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    const sa = [...a].map(String).sort();
    const sb = [...b].map(String).sort();
    return sa.every((v, i) => v === sb[i]);
  }
  if (typeof a === "number" && typeof b === "number") {
    return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) < 1e-9;
  }
  if (typeof a === "boolean" && typeof b === "boolean") return a === b;
  if (typeof a === "string" && typeof b === "string") return a === b;
  return false;
}

/** Deep-merge optional website `preferences` overlay onto /api/discovery-settings shape. */
function mergeDiscoveryEffective(defaults, overlay) {
  const o = overlay && typeof overlay === "object" && !Array.isArray(overlay) ? overlay : {};
  function deepMerge(a, b) {
    if (!b || typeof b !== "object" || Array.isArray(b)) return a;
    const out = { ...a };
    for (const [k, v] of Object.entries(b)) {
      if (
        v &&
        typeof v === "object" &&
        !Array.isArray(v) &&
        out[k] &&
        typeof out[k] === "object" &&
        !Array.isArray(out[k])
      ) {
        out[k] = deepMerge(out[k], v);
      } else {
        out[k] = v;
      }
    }
    return out;
  }
  return deepMerge(JSON.parse(JSON.stringify(defaults)), o);
}

function readSitePrefsFromForm() {
  const hz = parseInt(els.sitePrefHorizon?.value || "0", 10);
  const delay = parseFloat(els.sitePrefDelay?.value || "0");
  const timeout = parseFloat(els.sitePrefTimeout?.value || "0");
  const maxDetail = parseInt(els.sitePrefMaxDetail?.value || "0", 10);
  return {
    scoring: {
      positive_keywords: splitKeywords(els.sitePrefPositive?.value),
      ward_keywords: splitKeywords(els.sitePrefWard?.value),
      negative_keywords: splitKeywords(els.sitePrefNegative?.value),
      horizon_days: Number.isFinite(hz) ? Math.max(0, hz) : 120,
    },
    http: {
      delay_seconds: Number.isFinite(delay) && delay > 0 ? delay : 0.75,
      timeout_seconds: Number.isFinite(timeout) && timeout > 0 ? timeout : 45,
      user_agent: (els.sitePrefUserAgent?.value || "").trim(),
    },
    enrichment: {
      enabled: !!els.sitePrefEnrichEnabled?.checked,
      max_urls: Number.isFinite(maxDetail) ? Math.max(0, maxDetail) : 100,
    },
  };
}

function buildPrefsDiff(defaults, edited) {
  const out = {};
  for (const block of ["http", "scoring", "enrichment"]) {
    const patch = {};
    const d = defaults[block] || {};
    const e = edited[block] || {};
    for (const k of Object.keys(e)) {
      if (!deepEqualDiscover(e[k], d[k])) {
        patch[k] = e[k];
      }
    }
    if (Object.keys(patch).length) out[block] = patch;
  }
  return out;
}

function fillSitePrefsFromEffective(eff) {
  if (!eff) return;
  if (els.sitePrefPositive)
    els.sitePrefPositive.value = joinKeywords(eff.scoring?.positive_keywords);
  if (els.sitePrefWard) els.sitePrefWard.value = joinKeywords(eff.scoring?.ward_keywords);
  if (els.sitePrefNegative) els.sitePrefNegative.value = joinKeywords(eff.scoring?.negative_keywords);
  if (els.sitePrefHorizon) els.sitePrefHorizon.value = String(eff.scoring?.horizon_days ?? 120);
  if (els.sitePrefEnrichEnabled) els.sitePrefEnrichEnabled.checked = !!eff.enrichment?.enabled;
  if (els.sitePrefMaxDetail) els.sitePrefMaxDetail.value = String(eff.enrichment?.max_urls ?? 100);
  if (els.sitePrefDelay) els.sitePrefDelay.value = String(eff.http?.delay_seconds ?? 0.75);
  if (els.sitePrefTimeout) els.sitePrefTimeout.value = String(eff.http?.timeout_seconds ?? 45);
  if (els.sitePrefUserAgent) els.sitePrefUserAgent.value = eff.http?.user_agent ?? "";
}

function setDiscoveryPrefsError(msg) {
  if (!els.discoveryPrefsError) return;
  if (!msg) {
    els.discoveryPrefsError.hidden = true;
    els.discoveryPrefsError.textContent = "";
    return;
  }
  els.discoveryPrefsError.hidden = false;
  els.discoveryPrefsError.textContent = msg;
}

async function ensureWebsiteSourceTypes() {
  if (websiteSourceTypes.length) return;
  websiteSourceTypes = await fetchJson("/api/website-source-types");
}

async function loadDiscoveryPrefs() {
  if (!els.discoveryPrefsForm) return;
  setDiscoveryPrefsError("");
  try {
    const d = await fetchJson("/api/discovery-settings");
    els.discPositive.value = joinKeywords(d.scoring.positive_keywords);
    els.discWard.value = joinKeywords(d.scoring.ward_keywords);
    els.discNegative.value = joinKeywords(d.scoring.negative_keywords);
    els.discHorizon.value = String(d.scoring.horizon_days ?? 120);
    els.discEnrichEnabled.checked = !!d.enrichment.enabled;
    els.discDelay.value = String(d.http.delay_seconds ?? 0.75);
    els.discTimeout.value = String(d.http.timeout_seconds ?? 45);
    els.discUserAgent.value = d.http.user_agent ?? "";
    els.discMaxDetail.value = String(d.enrichment.max_urls ?? 100);
  } catch (e) {
    setDiscoveryPrefsError(e.message || "Could not load preferences.");
  }
}

async function submitDiscoveryPrefs(ev) {
  ev.preventDefault();
  if (!writesAllowed() || !els.discoveryPrefsForm) return;
  setDiscoveryPrefsError("");
  const hz = parseInt(els.discHorizon.value, 10);
  const delay = parseFloat(els.discDelay.value);
  const timeout = parseFloat(els.discTimeout.value);
  const maxDetail = parseInt(els.discMaxDetail.value, 10);
  const body = {
    scoring: {
      positive_keywords: splitKeywords(els.discPositive.value),
      ward_keywords: splitKeywords(els.discWard.value),
      negative_keywords: splitKeywords(els.discNegative.value),
      horizon_days: Number.isFinite(hz) ? Math.max(0, hz) : 120,
    },
    http: {
      delay_seconds: Number.isFinite(delay) && delay > 0 ? delay : 0.75,
      timeout_seconds: Number.isFinite(timeout) && timeout > 0 ? timeout : 45,
      user_agent: els.discUserAgent.value.trim(),
    },
    enrichment: {
      enabled: els.discEnrichEnabled.checked,
      max_urls: Number.isFinite(maxDetail) ? Math.max(0, maxDetail) : 100,
    },
  };
  try {
    els.discoveryPrefsSave.disabled = true;
    await fetchJson("/api/discovery-settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    setStatus("Discovery preferences saved.");
    await loadDiscoveryPrefs();
  } catch (e) {
    setDiscoveryPrefsError(e.message || "Save failed.");
  } finally {
    els.discoveryPrefsSave.disabled = false;
  }
}

function schemaFieldIds(typeId) {
  const meta = websiteSourceTypes.find((t) => t.id === typeId);
  if (!meta) return new Set();
  return new Set(meta.fields.map((f) => f.id));
}

function buildExpertJsonText(typeId, cfg) {
  const ids = schemaFieldIds(typeId);
  const extra = {};
  for (const [k, v] of Object.entries(cfg)) {
    if (!ids.has(k)) extra[k] = v;
  }
  return JSON.stringify(extra, null, 2);
}

function renderSiteDynamicFields(typeId) {
  if (!els.siteConfigDynamicSimple || !els.siteConfigDynamicAdvanced) return;
  els.siteConfigDynamicSimple.innerHTML = "";
  els.siteConfigDynamicAdvanced.innerHTML = "";
  const meta = websiteSourceTypes.find((t) => t.id === typeId);
  if (!meta) return;

  for (const f of meta.fields) {
    const wrap = document.createElement("label");
    wrap.className = "field field-grow";
    const span = document.createElement("span");
    span.textContent = f.label;
    wrap.appendChild(span);
    let input;
    if (f.kind === "url_list") {
      input = document.createElement("textarea");
      input.rows = 4;
      input.spellcheck = false;
    } else if (f.kind === "int") {
      input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.step = "1";
      if (f.default_hint) input.placeholder = `Default: ${f.default_hint}`;
    } else {
      input = document.createElement("input");
      input.type = f.kind === "url" ? "url" : "text";
      if (f.placeholder) input.placeholder = f.placeholder;
      else if (f.default_hint) input.placeholder = `Default: ${f.default_hint}`;
    }
    input.dataset.fieldId = f.id;
    if (f.help) input.title = f.help;
    wrap.appendChild(input);
    if (f.help) {
      const p = document.createElement("p");
      p.className = "field-hint";
      p.textContent = f.help;
      wrap.appendChild(p);
    }
    if (f.tier === "simple") els.siteConfigDynamicSimple.appendChild(wrap);
    else els.siteConfigDynamicAdvanced.appendChild(wrap);
  }
}

function fillDynamicFields(typeId, cfg) {
  const meta = websiteSourceTypes.find((t) => t.id === typeId);
  if (!meta) return;
  for (const f of meta.fields) {
    const el = document.querySelector(`#siteConfigDialog [data-field-id="${f.id}"]`);
    if (!el) continue;
    const v = cfg[f.id];
    if (f.kind === "url_list") {
      const arr = Array.isArray(v) ? v : v ? [v] : [];
      el.value = arr.map((x) => String(x).trim()).filter(Boolean).join("\n");
    } else if (f.kind === "int") {
      el.value = v !== undefined && v !== null && String(v).trim() !== "" ? String(v) : "";
    } else {
      el.value = v !== undefined && v !== null ? String(v) : "";
    }
  }
}

function collectDynamicConfig(typeId) {
  const meta = websiteSourceTypes.find((t) => t.id === typeId);
  if (!meta) return {};
  const out = {};
  for (const f of meta.fields) {
    const el = document.querySelector(`#siteConfigDialog [data-field-id="${f.id}"]`);
    if (!el) continue;
    if (f.kind === "url_list") {
      const lines = String(el.value)
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      if (lines.length) out[f.id] = lines;
    } else if (f.kind === "int") {
      const t = el.value.trim();
      if (t === "") continue;
      const n = parseInt(t, 10);
      if (Number.isFinite(n)) out[f.id] = n;
    } else {
      const t = el.value.trim();
      if (t) out[f.id] = t;
    }
  }
  return out;
}

function fillTypeSelect(currentType) {
  const sel = els.siteConfigTypeSelect;
  if (!sel) return false;
  sel.innerHTML = "";
  for (const t of websiteSourceTypes) {
    const o = document.createElement("option");
    o.value = t.id;
    o.textContent = t.title;
    sel.appendChild(o);
  }
  if (config.advanced_ui) {
    const oCustom = document.createElement("option");
    oCustom.value = "__custom__";
    oCustom.textContent = "Custom type…";
    sel.appendChild(oCustom);
  }

  const known = websiteSourceTypes.some((t) => t.id === currentType);
  if (known) {
    sel.value = currentType;
    els.siteConfigTypeCustomWrap.hidden = true;
    els.siteConfigTypeSelectWrap.hidden = false;
    sel.required = true;
    els.siteConfigTypeCustom.required = false;
    return true;
  }
  if (config.advanced_ui) {
    sel.value = "__custom__";
    els.siteConfigTypeCustomWrap.hidden = false;
    els.siteConfigTypeSelectWrap.hidden = false;
    sel.required = false;
    els.siteConfigTypeCustom.required = true;
    els.siteConfigTypeCustom.value = currentType || "";
    return false;
  }
  const fallback = websiteSourceTypes[0]?.id || "json_ld_events";
  sel.value = fallback;
  els.siteConfigTypeCustomWrap.hidden = true;
  els.siteConfigTypeSelectWrap.hidden = false;
  sel.required = true;
  els.siteConfigTypeCustom.required = false;
  return true;
}

function onSiteTypeSelectChange() {
  const v = els.siteConfigTypeSelect.value;
  if (v === "__custom__") {
    els.siteConfigTypeCustomWrap.hidden = false;
    els.siteConfigTypeSelect.required = false;
    els.siteConfigTypeCustom.required = true;
    els.siteConfigDynamicSimple.innerHTML = "";
    els.siteConfigDynamicAdvanced.innerHTML = "";
    if (els.siteConfigJsonExpert) els.siteConfigJsonExpert.value = "{}";
  } else {
    els.siteConfigTypeCustomWrap.hidden = true;
    els.siteConfigTypeSelect.required = true;
    els.siteConfigTypeCustom.required = false;
    renderSiteDynamicFields(v);
    if (els.siteConfigJsonExpert) els.siteConfigJsonExpert.value = "{}";
  }
}

async function sitesBulkEnabled(enabled) {
  if (!writesAllowed()) return;
  try {
    setStatus(enabled ? "Enabling all sites…" : "Disabling all sites…");
    await fetchJson("/api/websites/bulk-enabled", {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
    setStatus(enabled ? "All sites enabled." : "All sites disabled.");
    await loadSites({ quietStatus: true });
  } catch (e) {
    setStatus(e.message || "Bulk update failed.", true);
    await loadSites({ quietStatus: true });
  }
}

async function loadSites(opts = {}) {
  const quiet = opts.quietStatus === true;
  if (!quiet) setStatus("Loading sites…");
  try {
    await ensureWebsiteSourceTypes();
    const rows = await fetchJson("/api/websites");
    lastSitesRows = rows;
    renderSites(rows);
    if (!quiet) setStatus(`${rows.length} site(s).`);
  } catch (e) {
    if (!quiet) {
      setStatus(`Sites failed: ${e.message}`, true);
      els.sitesTbody.innerHTML = "";
    } else if (lastSitesRows) {
      renderSites(lastSitesRows);
    }
  }
}

function renderSites(rows) {
  els.sitesTbody.innerHTML = "";
  if (els.sitesEmptyHint) {
    els.sitesEmptyHint.hidden = rows.length > 0;
  }
  const allowWrite = writesAllowed();
  for (const w of rows) {
    const tr = document.createElement("tr");
    tr.dataset.id = String(w.id);
    tr.draggable = allowWrite;
    if (allowWrite) {
      tr.addEventListener("dragstart", onSiteDragStart);
      tr.addEventListener("dragend", onSiteDragEnd);
      tr.addEventListener("dragover", onSiteDragOver);
      tr.addEventListener("drop", onSiteDrop);
    }

    const tdDrag = document.createElement("td");
    tdDrag.className = "col-drag";
    const grip = document.createElement("span");
    grip.className = "drag-handle";
    grip.textContent = "⋮⋮";
    grip.setAttribute("aria-hidden", "true");
    grip.title = "Drag to reorder";
    tdDrag.appendChild(grip);

    const tdName = document.createElement("td");
    tdName.textContent = siteLabel(w);

    const tdType = document.createElement("td");
    tdType.className = "col-type";
    const tl = websiteSourceTypes.find((t) => t.id === w.type);
    tdType.textContent = tl ? tl.title : w.type || "—";

    const tdEn = document.createElement("td");
    tdEn.className = "col-enabled";
    const label = document.createElement("label");
    label.className = "review-toggle";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = w.enabled;
    cb.disabled = !allowWrite;
    cb.addEventListener("change", () => patchWebsiteEnabled(w.id, cb.checked, cb));
    label.appendChild(cb);
    label.appendChild(document.createTextNode(w.enabled ? "On" : "Off"));
    tdEn.appendChild(label);

    const tdAct = document.createElement("td");
    tdAct.className = "col-activity";
    tdAct.textContent = formatWhen(w.last_event_activity_at);

    const tdCfg = document.createElement("td");
    tdCfg.className = "col-config";
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn secondary btn-site-config";
    editBtn.textContent = "Edit…";
    editBtn.title = "Edit display name, source type, and URLs";
    editBtn.disabled = !allowWrite;
    editBtn.addEventListener("click", () => void openSiteConfigDialog(w, editBtn));
    tdCfg.appendChild(editBtn);

    const tdRecheck = document.createElement("td");
    tdRecheck.className = "col-recheck";
    const recheckBtn = document.createElement("button");
    recheckBtn.type = "button";
    recheckBtn.className = "btn secondary btn-recheck";
    recheckBtn.textContent = siteRecheckingId === w.id ? "…" : "Re-check";
    recheckBtn.title = "Crawl this site only and merge events into the database";
    recheckBtn.disabled = !allowWrite || siteRecheckingId !== null;
    recheckBtn.addEventListener("click", () => void runSiteRecheck(w.id));
    tdRecheck.appendChild(recheckBtn);

    const tdRemove = document.createElement("td");
    tdRemove.className = "col-remove";
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "btn danger btn-site-delete";
    delBtn.textContent = "Remove";
    delBtn.title = "Remove this site from your account";
    delBtn.disabled = !allowWrite || siteDeletingId !== null;
    delBtn.addEventListener("click", () => void openSiteDeleteDialog(w));
    tdRemove.appendChild(delBtn);

    tr.append(tdDrag, tdName, tdType, tdEn, tdAct, tdCfg, tdRecheck, tdRemove);
    els.sitesTbody.appendChild(tr);
  }
}

function setSiteConfigError(msg) {
  if (!msg) {
    els.siteConfigError.hidden = true;
    els.siteConfigError.textContent = "";
    return;
  }
  els.siteConfigError.hidden = false;
  els.siteConfigError.textContent = msg;
}

function setAddSourceQuickError(msg) {
  if (!els.addSourceQuickError) return;
  if (!msg) {
    els.addSourceQuickError.hidden = true;
    els.addSourceQuickError.textContent = "";
    return;
  }
  els.addSourceQuickError.hidden = false;
  els.addSourceQuickError.textContent = msg;
}

function closeAddSourceQuickDialog() {
  setAddSourceQuickError("");
  els.addSourceQuickDialog?.close();
}

async function openAddSourceQuickDialog() {
  if (!writesAllowed() || !els.addSourceQuickDialog) return;
  setAddSourceQuickError("");
  if (els.addSourceQuickName) els.addSourceQuickName.value = "";
  if (els.addSourceQuickUrl) els.addSourceQuickUrl.value = "";
  if (els.addSourceQuickUseLlm) els.addSourceQuickUseLlm.checked = true;
  els.addSourceQuickDialog.showModal();
  requestAnimationFrame(() => els.addSourceQuickName?.focus());
}

async function submitAddSourceQuick(ev) {
  ev.preventDefault();
  if (!writesAllowed()) return;
  setAddSourceQuickError("");
  const name = (els.addSourceQuickName && els.addSourceQuickName.value.trim()) || "";
  const url = (els.addSourceQuickUrl && els.addSourceQuickUrl.value.trim()) || "";
  if (!name) {
    setAddSourceQuickError("Enter a name.");
    return;
  }
  if (!url) {
    setAddSourceQuickError("Enter a calendar or events page URL.");
    return;
  }
  const use_llm = els.addSourceQuickUseLlm ? !!els.addSourceQuickUseLlm.checked : true;
  try {
    if (els.addSourceQuickSubmit) els.addSourceQuickSubmit.disabled = true;
    const res = await fetchJson("/api/websites/quick-add", {
      method: "POST",
      body: JSON.stringify({ url, name, use_llm }),
    });
    const label = res.website?.source_label || name;
    closeAddSourceQuickDialog();
    setStatus(`Added “${label}” (starts disabled). Use Re-check on that row to pull events.`);
    await loadSites({ quietStatus: true });
  } catch (e) {
    setAddSourceQuickError(e.message || "Could not add source.");
  } finally {
    if (els.addSourceQuickSubmit) els.addSourceQuickSubmit.disabled = false;
  }
}

async function openAddSourceQuickAdvanced() {
  if (!writesAllowed()) return;
  closeAddSourceQuickDialog();
  await openAddSourceDialog();
}

async function openSiteConfigDialog(w, opener) {
  if (!writesAllowed() || !els.siteConfigDialog) return;
  try {
    await ensureWebsiteSourceTypes();
  } catch (e) {
    setSiteConfigError(e.message || "Could not load source types.");
    return;
  }
  siteConfigOpener = opener && opener instanceof HTMLElement ? opener : null;
  siteConfigIsCreate = false;
  siteConfigEditingId = w.id;
  if (els.siteConfigKeyReadonly) els.siteConfigKeyReadonly.hidden = false;
  if (els.siteConfigKeyCreateWrap) els.siteConfigKeyCreateWrap.hidden = true;
  if (els.siteConfigHeading) els.siteConfigHeading.textContent = "Edit site";
  if (els.siteConfigExpertBlock) {
    els.siteConfigExpertBlock.style.display = config.advanced_ui ? "" : "none";
  }
  accountDiscoveryDefaults = null;
  try {
    accountDiscoveryDefaults = await fetchJson("/api/discovery-settings");
  } catch (e) {
    setSiteConfigError(e.message || "Could not load default discovery settings.");
    return;
  }
  const overlay =
    w.preferences && typeof w.preferences === "object" && !Array.isArray(w.preferences)
      ? w.preferences
      : {};
  const effective = mergeDiscoveryEffective(accountDiscoveryDefaults, overlay);
  fillSitePrefsFromEffective(effective);
  els.siteConfigSourceKey.textContent = w.source_key;
  els.siteConfigLabel.value = (w.source_label && String(w.source_label)) || "";
  const cfg = w.config && typeof w.config === "object" && !Array.isArray(w.config) ? w.config : {};
  const curType = (w.type && String(w.type).trim()) || "";
  const known = fillTypeSelect(curType);
  if (known) {
    renderSiteDynamicFields(curType);
    fillDynamicFields(curType, cfg);
    els.siteConfigJsonExpert.value = buildExpertJsonText(curType, cfg);
  } else {
    els.siteConfigDynamicSimple.innerHTML = "";
    els.siteConfigDynamicAdvanced.innerHTML = "";
    els.siteConfigJsonExpert.value = JSON.stringify(cfg, null, 2);
  }
  if (els.siteConfigAdvancedBlock) els.siteConfigAdvancedBlock.open = false;
  if (els.siteConfigPrefsBlock) els.siteConfigPrefsBlock.open = false;
  if (els.siteConfigExpertBlock) els.siteConfigExpertBlock.open = false;
  setSiteConfigError("");
  els.siteConfigDialog.showModal();
  requestAnimationFrame(() => {
    els.siteConfigLabel?.focus();
  });
}

function closeSiteConfigDialog() {
  siteConfigEditingId = null;
  siteConfigIsCreate = false;
  if (els.siteConfigKeyReadonly) els.siteConfigKeyReadonly.hidden = false;
  if (els.siteConfigKeyCreateWrap) els.siteConfigKeyCreateWrap.hidden = true;
  if (els.siteConfigHeading) els.siteConfigHeading.textContent = "Edit site";
  accountDiscoveryDefaults = null;
  els.siteConfigDialog?.close();
  setSiteConfigError("");
  const opener = siteConfigOpener;
  siteConfigOpener = null;
  opener?.focus();
}

async function openAddSourceDialog() {
  if (!writesAllowed() || !els.siteConfigDialog) return;
  try {
    await ensureWebsiteSourceTypes();
  } catch (e) {
    setSiteConfigError(e.message || "Could not load source types.");
    return;
  }
  siteConfigIsCreate = true;
  siteConfigEditingId = null;
  siteConfigOpener = els.btnAddSource;
  if (els.siteConfigHeading) els.siteConfigHeading.textContent = "Add source";
  if (els.siteConfigKeyReadonly) els.siteConfigKeyReadonly.hidden = true;
  if (els.siteConfigKeyCreateWrap) els.siteConfigKeyCreateWrap.hidden = false;
  if (els.siteConfigNewKey) els.siteConfigNewKey.value = "";
  try {
    accountDiscoveryDefaults = await fetchJson("/api/discovery-settings");
  } catch (e) {
    setSiteConfigError(e.message || "Could not load default discovery settings.");
    return;
  }
  fillSitePrefsFromEffective(accountDiscoveryDefaults);
  const first = websiteSourceTypes[0]?.id || "json_ld_events";
  fillTypeSelect(first);
  renderSiteDynamicFields(first);
  fillDynamicFields(first, {});
  els.siteConfigJsonExpert.value = "{}";
  els.siteConfigLabel.value = "";
  if (els.siteConfigExpertBlock) {
    els.siteConfigExpertBlock.style.display = config.advanced_ui ? "" : "none";
  }
  if (els.siteConfigAdvancedBlock) els.siteConfigAdvancedBlock.open = false;
  if (els.siteConfigPrefsBlock) els.siteConfigPrefsBlock.open = false;
  setSiteConfigError("");
  els.siteConfigDialog.showModal();
  requestAnimationFrame(() => {
    els.siteConfigNewKey?.focus();
  });
}

function resolveSiteTypeFromForm() {
  if (!els.siteConfigTypeSelect) return "";
  if (els.siteConfigTypeSelect.value === "__custom__") {
    return (els.siteConfigTypeCustom.value || "").trim();
  }
  return els.siteConfigTypeSelect.value;
}

async function submitSiteConfig(ev) {
  ev.preventDefault();
  if (!writesAllowed()) return;
  if (!siteConfigIsCreate && siteConfigEditingId === null) return;
  setSiteConfigError("");
  const siteType = resolveSiteTypeFromForm();
  if (!siteType) {
    setSiteConfigError("Source type cannot be empty.");
    return;
  }
  const known = websiteSourceTypes.some((t) => t.id === siteType);
  let parsed;
  try {
    parsed = JSON.parse(els.siteConfigJsonExpert.value);
  } catch {
    setSiteConfigError("Expert JSON must be valid.");
    return;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    setSiteConfigError("Expert JSON must be an object.");
    return;
  }
  let configOut;
  if (known) {
    const dynamic = collectDynamicConfig(siteType);
    configOut = { ...parsed, ...dynamic };
  } else {
    configOut = parsed;
  }
  let defaults = accountDiscoveryDefaults;
  if (!defaults) {
    try {
      defaults = await fetchJson("/api/discovery-settings");
    } catch (e) {
      setSiteConfigError(e.message || "Could not load defaults to compare preferences.");
      return;
    }
  }
  const prefsDiff = buildPrefsDiff(defaults, readSitePrefsFromForm());
  try {
    els.siteConfigSave.disabled = true;
    if (siteConfigIsCreate) {
      const sk = (els.siteConfigNewKey && els.siteConfigNewKey.value.trim()) || "";
      if (!sk) {
        setSiteConfigError("Please choose a short source id (letters, numbers, dashes).");
      } else {
        await fetchJson("/api/websites", {
          method: "POST",
          body: JSON.stringify({
            source_key: sk,
            type: siteType,
            source_label: els.siteConfigLabel.value || null,
            config: configOut,
            enabled: false,
          }),
        });
        setStatus("Source added (starts disabled). Use Re-check when you are ready.");
        closeSiteConfigDialog();
        await loadSites();
      }
    } else {
      await fetchJson(`/api/websites/${siteConfigEditingId}`, {
        method: "PATCH",
        body: JSON.stringify({
          type: siteType,
          source_label: els.siteConfigLabel.value,
          config: configOut,
          preferences: prefsDiff,
        }),
      });
      setStatus("Site config saved.");
      closeSiteConfigDialog();
      await loadSites();
    }
  } catch (e) {
    setSiteConfigError(e.message || "Save failed.");
  } finally {
    els.siteConfigSave.disabled = false;
  }
}

if (els.siteConfigForm) {
  els.siteConfigForm.addEventListener("submit", (ev) => void submitSiteConfig(ev));
}
if (els.siteConfigCancel) {
  els.siteConfigCancel.addEventListener("click", () => closeSiteConfigDialog());
}
if (els.siteConfigDialog) {
  els.siteConfigDialog.addEventListener("cancel", (ev) => {
    ev.preventDefault();
    closeSiteConfigDialog();
  });
}
if (els.siteConfigTypeSelect) {
  els.siteConfigTypeSelect.addEventListener("change", () => onSiteTypeSelectChange());
}
if (els.sitePrefReset) {
  els.sitePrefReset.addEventListener("click", () => {
    if (!writesAllowed() || !accountDiscoveryDefaults) return;
    fillSitePrefsFromEffective(accountDiscoveryDefaults);
  });
}
if (els.discoveryPrefsForm) {
  els.discoveryPrefsForm.addEventListener("submit", (ev) => void submitDiscoveryPrefs(ev));
}
if (els.sitesCheckAll) {
  els.sitesCheckAll.addEventListener("click", () => void sitesBulkEnabled(true));
}
if (els.sitesUncheckAll) {
  els.sitesUncheckAll.addEventListener("click", () => void sitesBulkEnabled(false));
}
if (els.btnAddSource) {
  els.btnAddSource.addEventListener("click", () => void openAddSourceQuickDialog());
}
if (els.addSourceQuickForm) {
  els.addSourceQuickForm.addEventListener("submit", (ev) => void submitAddSourceQuick(ev));
}
if (els.addSourceQuickCancel) {
  els.addSourceQuickCancel.addEventListener("click", () => closeAddSourceQuickDialog());
}
if (els.addSourceQuickDialog) {
  els.addSourceQuickDialog.addEventListener("cancel", (ev) => {
    ev.preventDefault();
    closeAddSourceQuickDialog();
  });
}
if (els.addSourceQuickAdvanced) {
  els.addSourceQuickAdvanced.addEventListener("click", () => void openAddSourceQuickAdvanced());
}
if (els.btnRunFullCrawl) {
  els.btnRunFullCrawl.addEventListener("click", () => void runFullCrawl());
}

/** Poll crawl job until terminal state or timeout. */
async function pollCrawlJob(jobId) {
  const maxMs = 120000;
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    const j = await fetchJson(`/api/crawl-jobs/${jobId}`);
    if (j.status === "succeeded" || j.status === "failed") return j;
    await new Promise((res) => setTimeout(res, 700));
  }
  throw new Error("Timed out waiting for crawl to finish.");
}

async function runFullCrawl() {
  if (!writesAllowed() || siteRecheckingId !== null) return;
  siteRecheckingId = -1;
  if (lastSitesRows) renderSites(lastSitesRows);
  setStatus("Starting full crawl…");
  try {
    const r = await fetchJson("/api/crawl-jobs", {
      method: "POST",
      body: JSON.stringify({ kind: "full" }),
    });
    const job = await pollCrawlJob(r.job_id);
    if (job.status === "failed") throw new Error(job.error_message || "Crawl failed");
    const ec = job.summary?.event_count ?? job.event_count;
    setStatus(`Full crawl finished: ${ec ?? "?"} event(s).`);
  } catch (e) {
    setStatus(`Full crawl failed: ${e.message}`, true);
  } finally {
    siteRecheckingId = null;
    await loadSites({ quietStatus: true });
    await loadReviewEvents();
    await loadCalendarMonth();
  }
}

async function runSiteRecheck(id) {
  if (!writesAllowed() || siteRecheckingId !== null) return;
  siteRecheckingId = id;
  if (lastSitesRows) renderSites(lastSitesRows);
  setStatus("Re-checking site…");
  try {
    const r = await fetchJson(`/api/websites/${id}/recheck`, { method: "POST" });
    const job = await pollCrawlJob(r.job_id);
    if (job.status === "failed") throw new Error(job.error_message || "Crawl failed");
    const ec = job.summary?.event_count ?? job.event_count;
    setStatus(`Re-check finished: ${ec ?? "?"} event(s).`);
  } catch (e) {
    setStatus(`Re-check failed: ${e.message}`, true);
  } finally {
    siteRecheckingId = null;
    await loadSites({ quietStatus: true });
    await loadReviewEvents();
    await loadCalendarMonth();
  }
}

function onSiteDragStart(e) {
  const tr = e.target.closest("tr");
  if (!tr) return;
  sitesDragId = tr.dataset.id;
  tr.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", sitesDragId);
}

function onSiteDragEnd(e) {
  const tr = e.target.closest("tr");
  if (tr) tr.classList.remove("dragging");
  sitesDragId = null;
}

function onSiteDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
}

async function onSiteDrop(e) {
  e.preventDefault();
  const tr = e.target.closest("tr");
  if (!tr || !sitesDragId) return;
  const tbody = els.sitesTbody;
  const dragRow = tbody.querySelector(`tr[data-id="${sitesDragId}"]`);
  if (!dragRow || dragRow === tr) return;
  const rect = tr.getBoundingClientRect();
  const before = e.clientY < rect.top + rect.height / 2;
  if (before) tbody.insertBefore(dragRow, tr);
  else tbody.insertBefore(dragRow, tr.nextSibling);
  await persistSiteOrder();
}

async function persistSiteOrder() {
  if (!writesAllowed()) return;
  const ids = [...els.sitesTbody.querySelectorAll("tr[data-id]")].map((r) => Number(r.dataset.id));
  try {
    await fetchJson("/api/websites/reorder", {
      method: "PUT",
      body: JSON.stringify({ ids }),
    });
    setStatus("Site order saved.");
  } catch (e) {
    setStatus(`Reorder failed: ${e.message}`, true);
    await loadSites();
  }
}

async function patchWebsiteEnabled(id, enabled, checkboxEl) {
  if (!writesAllowed()) return;
  try {
    await fetchJson(`/api/websites/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
    setStatus("Site updated.");
  } catch (e) {
    setStatus(`Update failed: ${e.message}`, true);
    checkboxEl.checked = !enabled;
  }
}

async function openSiteDeleteDialog(w) {
  if (!writesAllowed() || !els.siteDeleteDialog || siteDeletingId !== null) return;
  siteDeletePending = w;
  els.siteDeleteLead.textContent = `Remove “${siteLabel(w)}” from this account? It will no longer appear in the site list or full crawls.`;
  els.siteDeleteEvents.checked = false;
  try {
    const page = await fetchJson(`/api/events?website_id=${w.id}&limit=1&offset=0`);
    const n = typeof page.total === "number" ? page.total : 0;
    if (n > 0) {
      els.siteDeleteEventsWrap.hidden = false;
      els.siteDeleteEventsHint.textContent = `Also permanently delete all ${n} event(s) stored for this site. This cannot be undone.`;
    } else {
      els.siteDeleteEventsWrap.hidden = true;
    }
    els.siteDeleteDialog.showModal();
  } catch (e) {
    siteDeletePending = null;
    setStatus(`Could not load events for this site: ${e.message}`, true);
  }
}

function closeSiteDeleteDialog() {
  siteDeletePending = null;
  els.siteDeleteDialog?.close();
}

async function confirmSiteDelete() {
  if (!writesAllowed() || siteDeletePending === null || siteDeletingId !== null) return;
  const w = siteDeletePending;
  const id = w.id;
  const deleteEvents =
    els.siteDeleteEventsWrap &&
    !els.siteDeleteEventsWrap.hidden &&
    Boolean(els.siteDeleteEvents?.checked);
  siteDeletePending = null;
  els.siteDeleteDialog?.close();
  siteDeletingId = id;
  if (lastSitesRows) renderSites(lastSitesRows);
  setStatus("Removing site…");
  try {
    const r = await fetchJson(`/api/websites/${id}?delete_events=${deleteEvents}`, {
      method: "DELETE",
    });
    const removed = typeof r.events_removed === "number" ? r.events_removed : 0;
    if (deleteEvents) {
      setStatus(`Site removed. ${removed} event(s) deleted.`);
    } else {
      setStatus("Site removed. Linked events were kept (no longer tied to this site).");
    }
    await loadSources();
    await loadReviewEvents();
    await loadSites({ quietStatus: true });
  } catch (e) {
    setStatus(`Remove failed: ${e.message}`, true);
  } finally {
    siteDeletingId = null;
    await loadSites({ quietStatus: true });
  }
}

if (els.siteDeleteCancel) {
  els.siteDeleteCancel.addEventListener("click", () => closeSiteDeleteDialog());
}
if (els.siteDeleteConfirm) {
  els.siteDeleteConfirm.addEventListener("click", () => void confirmSiteDelete());
}
if (els.siteDeleteDialog) {
  els.siteDeleteDialog.addEventListener("cancel", (ev) => {
    ev.preventDefault();
    closeSiteDeleteDialog();
  });
}

// ——— Calendar ———

function pad2(n) {
  return String(n).padStart(2, "0");
}

function monthRange(y, m0) {
  const start = `${y}-${pad2(m0 + 1)}-01`;
  const lastDay = new Date(y, m0 + 1, 0).getDate();
  const end = `${y}-${pad2(m0 + 1)}-${pad2(lastDay)}`;
  return { start, end };
}

function monthTitle(y, m0) {
  return new Date(y, m0, 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

/** Accessible label for a calendar day button (month grid). */
function calendarDayAriaLabel(y, m0, day, eventCount) {
  const d = new Date(y, m0, day);
  const long = d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
  if (eventCount === 0) {
    return `${long}. No confirmed events.`;
  }
  return `${long}. ${eventCount} confirmed event${eventCount === 1 ? "" : "s"}.`;
}

async function loadCalendarMonth() {
  const { y, m } = calView;
  els.calTitle.textContent = monthTitle(y, m);
  const { start, end } = monthRange(y, m);
  els.calStatus.textContent = "Loading…";
  els.calDetail.hidden = true;
  try {
    const p = new URLSearchParams({
      start_from: start,
      start_to: end,
      sort: "start_at",
      reviewed: "true",
      rejected: "false",
      limit: String(CAL_LIMIT),
      offset: "0",
    });
    const data = await fetchJson(`/api/events?${p}`);
    calEventsByDay = new Map();
    for (const ev of data.events) {
      const d = ev.start_at && ev.start_at.slice(0, 10);
      if (!d || d.length !== 10) continue;
      if (!calEventsByDay.has(d)) calEventsByDay.set(d, []);
      calEventsByDay.get(d).push(ev);
    }
    renderCalendarGrid(y, m);
    const extra = data.total > data.events.length ? ` Showing ${data.events.length} of ${data.total}.` : "";
    els.calStatus.textContent = `${data.events.length} confirmed event(s) with dates this month.${extra}`;
  } catch (e) {
    els.calStatus.textContent = `Failed to load: ${e.message}`;
    els.calGrid.innerHTML = "";
  }
}

function renderCalendarGrid(y, m0) {
  const dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  els.calGrid.innerHTML = "";
  for (const d of dow) {
    const h = document.createElement("div");
    h.className = "cal-dow";
    h.textContent = d;
    els.calGrid.appendChild(h);
  }

  const first = new Date(y, m0, 1);
  const startPad = first.getDay();
  const daysInMonth = new Date(y, m0 + 1, 0).getDate();
  const prevMonthDays = new Date(y, m0, 0).getDate();

  const today = new Date();
  const isThisMonth = today.getFullYear() === y && today.getMonth() === m0;
  const todayNum = isThisMonth ? today.getDate() : null;

  for (let i = 0; i < startPad; i++) {
    const dayNum = prevMonthDays - startPad + i + 1;
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cal-cell cal-cell-out";
    cell.disabled = true;
    cell.setAttribute("aria-hidden", "true");
    cell.tabIndex = -1;
    cell.innerHTML = `<span class="cal-cell-num">${dayNum}</span>`;
    els.calGrid.appendChild(cell);
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const iso = `${y}-${pad2(m0 + 1)}-${pad2(d)}`;
    const list = calEventsByDay.get(iso) || [];
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cal-cell";
    if (todayNum === d) cell.classList.add("cal-cell-today");
    cell.setAttribute("aria-label", calendarDayAriaLabel(y, m0, d, list.length));
    cell.innerHTML = `<span class="cal-cell-num" aria-hidden="true">${d}</span>`;
    if (list.length) {
      const c = document.createElement("span");
      c.className = "cal-cell-count";
      c.setAttribute("aria-hidden", "true");
      c.textContent = `${list.length} event${list.length === 1 ? "" : "s"}`;
      cell.appendChild(c);
    }
    cell.addEventListener("click", () => showCalDayDetail(iso, list));
    els.calGrid.appendChild(cell);
  }

  const tail = (7 - ((startPad + daysInMonth) % 7)) % 7;
  for (let i = 0; i < tail; i++) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cal-cell cal-cell-out";
    cell.disabled = true;
    cell.setAttribute("aria-hidden", "true");
    cell.tabIndex = -1;
    cell.innerHTML = `<span class="cal-cell-num">${i + 1}</span>`;
    els.calGrid.appendChild(cell);
  }
}

function showCalDayDetail(iso, list) {
  els.calDetail.hidden = false;
  els.calDetailTitle.textContent = formatWhen(iso);
  els.calDetailList.innerHTML = "";
  requestAnimationFrame(() => els.calDetailTitle.focus());
  if (!list.length) {
    const li = document.createElement("li");
    li.textContent = "No events with this start date.";
    els.calDetailList.appendChild(li);
    return;
  }
  for (const ev of list) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = ev.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = ev.title;
    li.appendChild(a);
    if (ev.source) {
      li.appendChild(document.createTextNode(` · ${ev.source}`));
    }
    els.calDetailList.appendChild(li);
  }
}

// ——— Review ———

function defaultReviewSortOrder(sortKey) {
  return sortKey === "relevance" ? "desc" : "asc";
}

function sortButtonPlainLabel(btn) {
  const clone = btn.cloneNode(true);
  clone.querySelector(".th-sort-ind")?.remove();
  return clone.textContent.replace(/\s+/g, " ").trim();
}

function updateReviewSortHeaders() {
  const table = els.panelReview.querySelector("table.events");
  if (!table) return;
  for (const th of table.querySelectorAll("thead th")) {
    const btn = th.querySelector(".th-sort");
    if (!btn) continue;
    const key = btn.dataset.sort;
    const ind = btn.querySelector(".th-sort-ind");
    const plain = sortButtonPlainLabel(btn);
    th.removeAttribute("aria-sort");
    btn.classList.remove("th-sort-active");
    if (key === reviewSortKey) {
      th.setAttribute("aria-sort", reviewSortOrder === "asc" ? "ascending" : "descending");
      btn.classList.add("th-sort-active");
      if (ind) ind.textContent = reviewSortOrder === "asc" ? " \u2191" : " \u2193";
      btn.setAttribute(
        "aria-label",
        `Sorted by ${plain}, ${reviewSortOrder === "asc" ? "ascending" : "descending"}. Click to reverse.`,
      );
    } else {
      if (ind) ind.textContent = "";
      btn.setAttribute("aria-label", `Sort by ${plain}`);
    }
  }
}

function onReviewSortHeaderClick(sortKey) {
  if (!sortKey) return;
  if (sortKey === reviewSortKey) {
    reviewSortOrder = reviewSortOrder === "asc" ? "desc" : "asc";
  } else {
    reviewSortKey = sortKey;
    reviewSortOrder = defaultReviewSortOrder(sortKey);
  }
  reviewOffset = 0;
  updateReviewSortHeaders();
  loadReviewEvents();
}

function reviewQueryParams() {
  const p = new URLSearchParams();
  const q = els.q.value.trim();
  if (q) p.set("q", q);
  const src = els.source.value;
  if (src) p.set("source", src);
  const ms = els.minScore.value.trim();
  if (ms !== "") p.set("min_score", ms);
  const rv = els.reviewed.value;
  if (rv === "pending") {
    p.set("reviewed", "false");
    p.set("rejected", "false");
  } else if (rv === "accepted") {
    p.set("reviewed", "true");
    p.set("rejected", "false");
  } else if (rv === "rejected") {
    p.set("rejected", "true");
  }
  if (els.showPastEvents) {
    if (els.showPastEvents.checked) {
      p.set("include_past", "true");
    } else {
      p.set("include_past", "false");
      const d = new Date();
      p.set(
        "as_of",
        `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`,
      );
    }
  }
  p.set("sort", reviewSortKey);
  p.set("order", reviewSortOrder);
  p.set("limit", String(REVIEW_LIMIT));
  p.set("offset", String(reviewOffset));
  return p;
}

function renderReviewRows(events) {
  els.tbody.innerHTML = "";
  const writesDisabled = config.read_only;
  const allowTriage = !writesDisabled && writesAllowed();

  for (const ev of events) {
    const tr = document.createElement("tr");
    tr.dataset.id = String(ev.id);

    const tdRev = document.createElement("td");
    const wrap = document.createElement("div");
    wrap.className = "review-actions";
    const rejected = Boolean(ev.rejected);
    const accepted = Boolean(ev.reviewed) && !rejected;

    const triageBtn = (label, className, body) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = className;
      b.textContent = label;
      b.disabled = !allowTriage;
      b.addEventListener("click", async () => {
        const ok = await patchReview(ev.id, body);
        if (ok) await loadReviewEvents();
      });
      return b;
    };

    if (accepted) {
      const st = document.createElement("span");
      st.className = "triage-status triage-accepted";
      st.textContent = "Accepted";
      wrap.appendChild(st);
      wrap.appendChild(
        triageBtn("Clear", "btn-triage btn-triage-clear", { reviewed: false, rejected: false }),
      );
    } else if (rejected) {
      const st = document.createElement("span");
      st.className = "triage-status triage-rejected";
      st.textContent = "Rejected";
      wrap.appendChild(st);
      wrap.appendChild(
        triageBtn("Clear", "btn-triage btn-triage-clear", { reviewed: false, rejected: false }),
      );
    } else {
      wrap.appendChild(
        triageBtn("Accept", "btn-triage btn-triage-accept", { reviewed: true, rejected: false }),
      );
      wrap.appendChild(
        triageBtn("Reject", "btn-triage btn-triage-reject", { reviewed: false, rejected: true }),
      );
    }
    tdRev.appendChild(wrap);

    const tdScore = document.createElement("td");
    tdScore.className = "score";
    tdScore.textContent = Number(ev.relevance_score).toFixed(1);

    const tdWhen = document.createElement("td");
    const whenDisp = reviewWhenDisplay(ev);
    tdWhen.textContent = whenDisp.approx ? `${whenDisp.text} (approx.)` : whenDisp.text;

    const tdEvent = document.createElement("td");
    const title = document.createElement("p");
    title.className = "event-title";
    const a = document.createElement("a");
    a.href = ev.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = ev.title;
    title.appendChild(a);
    tdEvent.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "event-meta";
    const loc = (ev.venue || "").trim();
    const whenPart = whenDisp.approx
      ? `When: ${whenDisp.text} (approx.)`
      : `When: ${whenDisp.text}`;
    meta.textContent = loc ? `${whenPart} · Where: ${loc}` : `${whenPart} · Where: —`;
    tdEvent.appendChild(meta);

    const snip = (ev.raw_snippet || "").trim();
    if (snip) {
      const ex = document.createElement("p");
      ex.className = "event-snippet";
      ex.textContent = snip;
      tdEvent.appendChild(ex);
    }
    if (ev.relevance_reasons?.length) {
      const ul = document.createElement("ul");
      ul.className = "reasons";
      for (const r of ev.relevance_reasons) {
        const li = document.createElement("li");
        li.textContent = r;
        ul.appendChild(li);
      }
      tdEvent.appendChild(ul);
    }
    const notes = document.createElement("textarea");
    notes.className = "notes-field";
    notes.placeholder = "Notes…";
    notes.value = ev.notes || "";
    notes.disabled = writesDisabled || !writesAllowed();
    let noteTimer = null;
    notes.addEventListener("input", () => {
      clearTimeout(noteTimer);
      noteTimer = setTimeout(() => {
        patchReview(ev.id, { notes: notes.value });
      }, 600);
    });
    tdEvent.appendChild(notes);

    const tdSrc = document.createElement("td");
    tdSrc.textContent = ev.source;

    tr.append(tdRev, tdScore, tdWhen, tdEvent, tdSrc);
    els.tbody.appendChild(tr);
  }
}

async function patchReview(id, body) {
  if (config.read_only || !writesAllowed()) return false;
  try {
    await fetchJson(`/api/events/${id}/review`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    setStatus("Saved.");
    return true;
  } catch (e) {
    setStatus(`Save failed: ${e.message}`, true);
    await loadReviewEvents();
    return false;
  }
}

async function loadReviewEvents() {
  setStatus("Loading…");
  try {
    const data = await fetchJson(`/api/events?${reviewQueryParams()}`);
    reviewTotal = data.total;
    renderReviewRows(data.events);
    const from = reviewTotal === 0 ? 0 : reviewOffset + 1;
    const to = Math.min(reviewOffset + data.events.length, reviewTotal);
    els.pageInfo.textContent = reviewTotal ? `${from}–${to} of ${reviewTotal}` : "No events";
    els.prevPage.disabled = reviewOffset <= 0;
    els.nextPage.disabled = reviewOffset + REVIEW_LIMIT >= reviewTotal;
    setStatus(`${data.events.length} shown.`);
  } catch (e) {
    setStatus(`Failed to load: ${e.message}`, true);
    els.tbody.innerHTML = "";
  }
}

function scheduleReviewSearch() {
  clearTimeout(reviewSearchTimer);
  reviewSearchTimer = setTimeout(() => {
    reviewOffset = 0;
    loadReviewEvents();
  }, 280);
}

// ——— Init ———

els.navSites.addEventListener("click", () => navigateToPanel("sites"));
els.navCalendar.addEventListener("click", () => navigateToPanel("calendar"));
els.navReview.addEventListener("click", () => navigateToPanel("review"));

const appNav = document.querySelector(".app-nav");
if (appNav) {
  const tabOrder = ["sites", "calendar", "review"];
  const tabEls = { sites: els.navSites, calendar: els.navCalendar, review: els.navReview };
  appNav.addEventListener("keydown", (e) => {
    const current = tabOrder.find((k) => tabEls[k].classList.contains("nav-tab-active"));
    const i = tabOrder.indexOf(current);
    if (i < 0) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const next =
        e.key === "ArrowRight"
          ? (i + 1) % tabOrder.length
          : (i - 1 + tabOrder.length) % tabOrder.length;
      navigateToPanel(tabOrder[next]);
      tabEls[tabOrder[next]].focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      navigateToPanel(tabOrder[0]);
      tabEls[tabOrder[0]].focus();
    } else if (e.key === "End") {
      e.preventDefault();
      navigateToPanel(tabOrder[tabOrder.length - 1]);
      tabEls[tabOrder[tabOrder.length - 1]].focus();
    }
  });
}

window.addEventListener("hashchange", () => {
  showPanel(panelFromHash());
});

els.calPrev.addEventListener("click", () => {
  if (calView.m === 0) {
    calView = { y: calView.y - 1, m: 11 };
  } else {
    calView = { y: calView.y, m: calView.m - 1 };
  }
  loadCalendarMonth();
});

els.calNext.addEventListener("click", () => {
  if (calView.m === 11) {
    calView = { y: calView.y + 1, m: 0 };
  } else {
    calView = { y: calView.y, m: calView.m + 1 };
  }
  loadCalendarMonth();
});

els.q.addEventListener("input", scheduleReviewSearch);
els.source.addEventListener("change", () => {
  reviewOffset = 0;
  loadReviewEvents();
});
els.minScore.addEventListener("change", () => {
  reviewOffset = 0;
  loadReviewEvents();
});
els.reviewed.addEventListener("change", () => {
  reviewOffset = 0;
  loadReviewEvents();
});
if (els.showPastEvents) {
  els.showPastEvents.addEventListener("change", () => {
    reviewOffset = 0;
    loadReviewEvents();
  });
}
els.prevPage.addEventListener("click", () => {
  reviewOffset = Math.max(0, reviewOffset - REVIEW_LIMIT);
  loadReviewEvents();
});
els.nextPage.addEventListener("click", () => {
  reviewOffset += REVIEW_LIMIT;
  loadReviewEvents();
});
const reviewEventsTable = els.panelReview.querySelector("table.events");
if (reviewEventsTable) {
  reviewEventsTable.addEventListener("click", (e) => {
    const btn = e.target.closest(".th-sort");
    if (!btn || !reviewEventsTable.contains(btn)) return;
    onReviewSortHeaderClick(btn.dataset.sort);
  });
}

const meRes = await fetch("/api/auth/me", { credentials: "include" });
if (meRes.status === 401) {
  window.location.href = "/login";
} else if (!meRes.ok) {
  setStatus(`Session check failed: ${meRes.statusText}`, true);
} else {
  await loadConfig();
  await loadSources();
  updateReviewSortHeaders();
  showPanel(panelFromHash());
}
