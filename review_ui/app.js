const $ = (id) => document.getElementById(id);
const SOURCES = { yahooauction: "Yahoo Auctions", mercari: "Mercari", surugaya: "Surugaya" };
const FEEDBACK = { relevant: "Relevant", wrong_product: "Wrong product", accessory: "Accessory", bundle: "Bundle", unsure: "Unsure" };
const VERDICTS = { accepted: "Allowed", filtered: "Filtered", review: "Needs review" };
const NORMALIZATION = [
  ["nfkc", "Character width", "Unify full-width and half-width characters."],
  ["casefold", "Letter case", "Treat uppercase and lowercase as equivalent."],
  ["collapse_whitespace", "Whitespace", "Merge repeated spaces and line breaks."],
  ["kana_fold", "Kana", "Treat equivalent hiragana and katakana alike."],
];
const PAGE_SIZE = 24;
const clone = (value) => JSON.parse(JSON.stringify(value));
const defaultRules = () => ({ version: 1, normalization: { nfkc: true, casefold: true, collapse_whitespace: true, kana_fold: false }, include_legacy: true, groups: [], price: { min: null, max: null }, sources: [] });
const state = { alerts: [], selected: null, active: null, versions: [], legacy: [], draft: defaultRules(), baseline: defaultRules(), drafts: new Map(), candidates: [], total: 0, offset: 0, tab: "listings", view: "grid", replay: null, revision: 0, replayRevision: null, selectionRequest: 0, candidateRequest: 0, candidateAbort: null, authenticated: false, rulesReady: false, replaying: false, previewRequest: 0 };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}
function button(text, callback, className = "button secondary small", iconName) {
  const node = element("button", className);
  node.type = "button";
  if (iconName) node.append(icon(iconName));
  node.append(document.createTextNode(text));
  node.addEventListener("click", callback);
  return node;
}
function safeUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}
function date(value, short = false) {
  if (!value) return "Date unavailable";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "Date unavailable";
  return new Intl.DateTimeFormat(undefined, short ? { month: "short", day: "numeric" } : { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(parsed);
}
function money(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value)) ? `¥${Number(value).toLocaleString()}` : "Price unavailable";
}
function showToast(message, error = false) {
  clearTimeout(showToast.timer);
  $("toast").textContent = message;
  $("toast").className = `toast${error ? " error" : ""}`;
  $("toast").hidden = false;
  showToast.timer = setTimeout(() => { $("toast").hidden = true; }, 6500);
}
function notice(message) {
  $("workspace-notice").textContent = message || "";
  $("workspace-notice").hidden = !message;
}
async function api(path, { method = "GET", body, signal } = {}) {
  const response = await fetch(path, { method, credentials: "same-origin", headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) }, ...(body !== undefined ? { body: JSON.stringify(body) } : {}), signal });
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/login") showLogin();
    const error = new Error(data.message || (typeof data.error === "string" ? data.error : null) || `The request could not be completed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return data;
}
async function withBusy(node, task) {
  const disabled = node.disabled;
  node.disabled = true;
  node.setAttribute("aria-busy", "true");
  try { return await task(); }
  catch (error) { if (error.name !== "AbortError") showToast(error.message, true); }
  finally { node.disabled = disabled; node.removeAttribute("aria-busy"); updateActions(); }
}
function updateActions() {
  const ready = Boolean(state.selected && state.rulesReady);
  $("publish-rules").disabled = !ready || $("publish-rules").getAttribute("aria-busy") === "true";
  for (const id of ["run-replay", "replay-from-rules"]) $(id).disabled = !ready || state.replaying;
}
function emptyState(title, description, iconName = "search", action) {
  const node = element("div", "empty-state");
  node.append(icon(iconName), element("h3", "", title), element("p", "", description));
  if (action) node.append(action);
  return node;
}
function showLogin() {
  state.authenticated = false;
  state.candidateAbort?.abort();
  state.selectionRequest += 1;
  state.candidateRequest += 1;
  state.rulesReady = false;
  state.previewRequest += 1;
  $("app").hidden = true;
  $("login-screen").hidden = false;
  $("initial-loading").hidden = true;
  $("title-dialog").close();
  state.drafts.clear();
  state.alerts = [];
  state.candidates = [];
  state.selected = null;
  state.draft = defaultRules();
  state.active = null;
  state.replay = null;
}
async function openWorkspace() {
  state.authenticated = true;
  $("login-screen").hidden = true;
  $("app").hidden = false;
  $("initial-loading").hidden = true;
  setTab("listings");
  const result = await api("/api/alerts");
  state.alerts = result.alerts || [];
  $("all-count").textContent = result.archived_count ?? "";
  renderAlerts();
  await selectAlert(state.alerts[0]?.id ?? null);
}
function channelLabel(alert) {
  return alert.channel_name || `Channel ${String(alert.channel_id ?? "unknown").slice(-6)}`;
}
function renderAlerts() {
  const search = $("alert-search").value.toLocaleLowerCase();
  const alerts = state.alerts.filter((alert) => `${alert.search_query} ${alert.channel_id} ${alert.channel_name || ""}`.toLocaleLowerCase().includes(search)).sort((left, right) => String(left.channel_id).localeCompare(String(right.channel_id)) || left.search_query.localeCompare(right.search_query));
  $("alert-count").textContent = String(state.alerts.length);
  $("all-records").classList.toggle("active", state.selected === null);
  const nodes = [];
  let channel;
  for (const alert of alerts) {
    if (String(alert.channel_id) !== channel) {
      channel = String(alert.channel_id);
      nodes.push(element("div", "channel-label", channelLabel(alert)));
    }
    const item = button("", () => selectAlert(alert.id).catch((error) => showToast(error.message, true)), `alert-item${String(state.selected?.id) === String(alert.id) ? " active" : ""}`);
    item.append(element("span", "", alert.search_query));
    item.title = `${alert.search_query} · ${channelLabel(alert)}`;
    if (String(state.selected?.id) === String(alert.id)) item.setAttribute("aria-current", "true");
    nodes.push(item);
  }
  if (!nodes.length) nodes.push(element("div", "sidebar-empty", state.alerts.length ? "No searches match your search." : "No monitored searches yet. Register a search in Discord to start a lab for it. You can still test a title here."));
  $("alert-list").replaceChildren(...nodes);
}
async function selectAlert(id) {
  if (state.rulesReady) state.drafts.set(state.selected ? String(state.selected.id) : "standalone", clone(state.draft));
  const request = ++state.selectionRequest;
  state.candidateRequest += 1;
  state.candidateAbort?.abort();
  state.selected = id === null ? null : state.alerts.find((alert) => String(alert.id) === String(id));
  state.active = null;
  state.versions = [];
  state.legacy = [];
  state.offset = 0;
  state.replay = null;
  state.replayRevision = null;
  state.rulesReady = !state.selected;
  state.previewRequest += 1;
  $("panel-rules").inert = !state.rulesReady;
  $("panel-versions").inert = !state.rulesReady;
  $("open-title-test").disabled = !state.rulesReady;
  updateActions();
  $("candidate-list").replaceChildren(element("div", "loading-state", "Loading this workspace…"));
  notice("");
  renderAlerts();
  $("workspace-title").textContent = state.selected?.search_query || "All saved listings";
  $("workspace-subtitle").textContent = state.selected ? `${channelLabel(state.selected)} · Review the match, then refine the signal.` : "Review your matches. Make room for better finds.";
  if (state.selected) {
    try {
      const data = await api(`/api/alerts/${encodeURIComponent(state.selected.id)}/rules`);
      if (request !== state.selectionRequest) return;
      setRulesData(data);
    } catch (error) {
      if (request === state.selectionRequest) notice("This search's rules could not be loaded. Select it again to retry; its draft cannot be published until loading succeeds.");
      throw error;
    }
  } else {
    state.baseline = defaultRules();
  }
  const key = state.selected ? String(state.selected.id) : "standalone";
  state.draft = clone(state.drafts.get(key) || state.baseline);
  state.rulesReady = true;
  $("panel-rules").inert = false;
  $("panel-versions").inert = false;
  $("open-title-test").disabled = false;
  state.revision += 1;
  renderRules();
  renderVersions();
  renderReplay();
  await loadCandidates();
}
function setRulesData(data) {
  state.active = data.active_version || null;
  state.versions = data.versions || [];
  state.legacy = data.legacy_filters || [];
  state.baseline = clone(state.active?.ruleset || data.default_ruleset || defaultRules());
}
async function refreshRules(preserveDraft = false) {
  if (!state.selected) return;
  const id = state.selected.id;
  const selection = state.selectionRequest;
  const data = await api(`/api/alerts/${encodeURIComponent(id)}/rules`);
  if (selection !== state.selectionRequest) return;
  setRulesData(data);
  if (!preserveDraft) state.draft = clone(state.baseline);
  markDraft();
  renderRules();
  renderVersions();
}
function setTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".tab").forEach((node) => {
    const active = node.dataset.tab === tab;
    node.classList.toggle("active", active);
    node.setAttribute("aria-current", active ? "page" : "false");
  });
  document.querySelectorAll(".tab-panel").forEach((node) => { node.hidden = node.id !== `panel-${tab}`; });
}
function verdictBadge(decision) {
  const verdict = decision?.verdict;
  const node = element("span", `decision-badge ${VERDICTS[verdict] ? verdict : ""}`);
  node.append(icon(verdict === "accepted" ? "check" : verdict === "filtered" ? "close" : "info"), document.createTextNode(VERDICTS[verdict] || "Not recorded"));
  return node;
}
function explanation(decision) {
  const details = element("details", "candidate-explanation");
  details.append(element("summary", "", "Why this decision?"));
  const reasons = decision?.reasons || [];
  const list = element("ul");
  for (const reason of reasons) list.append(element("li", "", typeof reason === "string" ? reason : reason.message || reason.code || "Match information unavailable."));
  if (!reasons.length) list.append(element("li", "", "No explanation was saved for this record."));
  details.append(list);
  return details;
}
function imagePanel(candidate) {
  const panel = element("div", "candidate-image");
  panel.append(icon("image"));
  const url = safeUrl(candidate.payload?.image_url || candidate.image_url);
  if (url) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    image.alt = "";
    image.src = url;
    image.addEventListener("error", () => { image.remove(); panel.append(element("span", "image-unavailable", "Image unavailable")); }, { once: true });
    panel.append(image);
  } else panel.append(element("span", "image-unavailable", "No saved image"));
  panel.append(element("span", "source-tag", SOURCES[candidate.source] || candidate.source || "Unknown marketplace"));
  return panel;
}
function linkedTitle(candidate, className = "candidate-title") {
  const title = element("h3", className);
  const text = candidate.title || candidate.payload?.title || "Untitled listing";
  const url = safeUrl(candidate.payload?.url || candidate.url);
  if (url) {
    const link = element("a", "", text);
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    title.append(link);
  } else title.textContent = text;
  return title;
}
function renderCandidate(candidate) {
  const card = element("article", "candidate-card");
  const main = element("div", "candidate-main");
  const heading = element("div", "candidate-heading");
  heading.append(verdictBadge(candidate.decision), element("time", "candidate-date", date(candidate.observed_at, true)));
  const normalized = element("div", "normalized-line");
  normalized.append(element("span", "normalized-label", "Normalized"), element("span", "", candidate.normalized_title || candidate.decision?.normalized_title || "Not saved"));
  const meta = element("div", "candidate-meta");
  meta.append(element("span", "candidate-price", money(candidate.payload?.price ?? candidate.price)), element("span", "query-tag", candidate.search_query || "Unassigned listing"));
  if (["delivery_import", "item_import"].includes(candidate.origin)) main.append(element("span", "import-origin", "Imported saved history"));
  const feedbackRow = element("div", "candidate-label-row");
  const feedback = element("select", "feedback-select");
  feedback.setAttribute("aria-label", `Relevance label for ${candidate.title || "this listing"}`);
  feedback.append(new Option("Add a label…", ""));
  Object.entries(FEEDBACK).forEach(([value, label]) => feedback.append(new Option(label, value)));
  feedback.value = candidate.feedback || "";
  feedback.addEventListener("change", () => withBusy(feedback, async () => {
    const previous = candidate.feedback;
    try {
      await api(`/api/candidates/${encodeURIComponent(candidate.id)}/feedback`, { method: "POST", body: { label: feedback.value || null } });
      candidate.feedback = feedback.value || null;
      showToast(candidate.feedback ? `Labeled ${FEEDBACK[candidate.feedback].toLowerCase()}.` : "Label cleared.");
    } catch (error) { feedback.value = previous || ""; throw error; }
  }));
  feedbackRow.append(element("span", "feedback-label", "Your relevance label"), feedback);
  main.append(heading, linkedTitle(candidate), normalized, meta, explanation(candidate.decision), feedbackRow);
  card.append(imagePanel(candidate), main);
  return card;
}
function renderStats() {
  const counts = { accepted: 0, filtered: 0, review: 0 };
  state.candidates.forEach((candidate) => { if (Object.hasOwn(counts, candidate.decision?.verdict)) counts[candidate.decision.verdict] += 1; });
  const values = [
    ["Matching saved records", state.total, "For the current search and filters", "", "grid"],
    ["Allowed", counts.accepted, "Recorded decisions on this page", "allowed", "check"],
    ["Filtered", counts.filtered, "Recorded decisions on this page", "filtered", "filter"],
    ["Needs review", counts.review, "Recorded decisions on this page", "review", "info"],
  ];
  $("stats").replaceChildren(...values.map(([label, count, caption, kind, iconName]) => {
    const node = element("div", `stat-card ${kind}`);
    const title = element("div", "stat-label", label);
    title.append(icon(iconName));
    node.append(title, element("div", "stat-value", Number(count || 0).toLocaleString()), element("div", "stat-caption", caption));
    return node;
  }));
  $("listing-tab-count").textContent = state.total.toLocaleString();
}
async function loadCandidates() {
  const request = ++state.candidateRequest;
  state.candidateAbort?.abort();
  state.candidateAbort = new AbortController();
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(state.offset) });
  if (state.selected) params.set("alert_id", state.selected.id);
  for (const [id, key] of [["candidate-search", "search"], ["candidate-source", "source"], ["candidate-verdict", "verdict"], ["candidate-feedback", "feedback"]]) if ($(id).value) params.set(key, $(id).value);
  $("candidate-list").replaceChildren(element("div", "loading-state", "Loading your saved listings…"));
  try {
    const data = await api(`/api/candidates?${params}`, { signal: state.candidateAbort.signal });
    if (request !== state.candidateRequest) return;
    state.candidates = data.items || [];
    state.total = Number(data.total || 0);
    renderStats();
    $("candidate-list").replaceChildren(...(state.candidates.length ? state.candidates.map(renderCandidate) : [emptyState("A clean slate", $("candidate-search").value || $("candidate-source").value || $("candidate-verdict").value || $("candidate-feedback").value ? "No saved listings match these filters. Try a broader view." : "New listing snapshots will appear here as your bot checks its searches. You can also import saved history or test a title now.", "image", button("Test a title", openTitleTest, "button secondary small", "spark"))]));
    $("candidate-range").textContent = state.total ? `${state.offset + 1}–${Math.min(state.offset + state.candidates.length, state.total)} of ${state.total.toLocaleString()} records` : "No saved records in this view";
    $("candidate-prev").disabled = state.offset === 0;
    $("candidate-next").disabled = state.offset + state.candidates.length >= state.total;
  } catch (error) {
    if (request !== state.candidateRequest) return;
    if (error.name !== "AbortError") {
      $("candidate-list").replaceChildren(emptyState("Listings could not be loaded", error.message, "info", button("Try again", () => loadCandidates(), "button secondary small", "repeat")));
      showToast(error.message, true);
    }
  }
}
function markDraft() {
  state.revision += 1;
  state.drafts.set(state.selected ? String(state.selected.id) : "standalone", clone(state.draft));
  const changed = JSON.stringify(state.draft) !== JSON.stringify(state.baseline);
  $("draft-indicator").hidden = !changed;
  $("draft-state").textContent = changed ? "Unpublished changes" : state.active ? "Matches published rules" : "Unpublished draft";
  $("draft-detail").textContent = state.selected ? "Changes apply to future checks after publishing." : "Choose a monitored search to publish. You can test this draft now.";
  if (document.activeElement !== $("rules-json")) $("rules-json").value = JSON.stringify(state.draft, null, 2);
  renderReplayStatus();
}
function addGroup(kind) {
  if (state.draft.groups.length >= 20) { showToast("A ruleset can have up to 20 groups.", true); return; }
  const label = { subject: "Subject", product: "Product type", exclude: "Accessories / bundles" }[kind];
  state.draft.groups.push({ id: `${kind}_${crypto.randomUUID()}`, label, policy: kind === "exclude" ? "exclude" : "require", match: "any", normalize: true, terms: [{ method: "contains", value: "" }] });
  markDraft();
  renderGroups();
}
function renderGroups() {
  const nodes = state.draft.groups.map((group, groupIndex) => {
    const card = element("section", `rule-group ${group.policy}`);
    const top = element("div", "group-topline");
    const title = element("div", "group-title");
    const label = element("input", "group-label");
    label.value = group.label || "Match group";
    label.maxLength = 100;
    label.setAttribute("aria-label", "Group name");
    label.addEventListener("input", () => { group.label = label.value; markDraft(); });
    title.append(element("span", "group-index", String(groupIndex + 1).padStart(2, "0")), label);
    const policy = element("select", "group-policy");
    policy.setAttribute("aria-label", "Group policy");
    [["require", "Required"], ["exclude", "Exclude"], ["review", "Needs review"]].forEach(([value, text]) => policy.append(new Option(text, value)));
    policy.value = group.policy;
    policy.addEventListener("change", () => { group.policy = policy.value; markDraft(); renderGroups(); });
    const remove = button("", () => { state.draft.groups.splice(groupIndex, 1); markDraft(); renderGroups(); }, "icon-button", "close");
    remove.setAttribute("aria-label", "Remove group");
    top.append(title, policy, remove);
    card.append(top);
    group.terms.forEach((term, termIndex) => {
      const row = element("div", "term-row");
      const method = element("select");
      method.setAttribute("aria-label", "Term match method");
      [["contains", "Contains"], ["exact", "Exact title"], ["regex", "Regex"]].forEach(([value, text]) => method.append(new Option(text, value)));
      method.value = term.method;
      const value = element("input");
      value.value = term.value;
      value.type = "text";
      value.maxLength = term.method === "regex" ? 256 : 1000;
      value.placeholder = group.policy === "exclude" ? "An accessory or bundle phrase…" : "Add a name, alias, or product term…";
      value.setAttribute("aria-label", "Term value");
      value.addEventListener("input", () => { term.value = value.value; markDraft(); });
      method.addEventListener("change", () => { term.method = method.value; value.maxLength = term.method === "regex" ? 256 : 1000; markDraft(); });
      const removeTerm = button("", () => { group.terms.splice(termIndex, 1); markDraft(); renderGroups(); }, "icon-button", "close");
      removeTerm.setAttribute("aria-label", "Remove alias");
      row.append(method, value, removeTerm);
      card.append(row);
    });
    const bottom = element("div", "group-bottom");
    const add = button(group.match === "all" ? "Add a term" : "Add an alternative", () => {
      if (group.terms.length >= 20 || state.draft.groups.reduce((sum, item) => sum + item.terms.length, 0) >= 100) { showToast("Use at most 20 terms per group and 100 terms in total.", true); return; }
      group.terms.push({ method: "contains", value: "" }); markDraft(); renderGroups();
    }, "add-alias", "plus");
    const normalize = element("label", "group-normalize");
    const checkbox = element("input"); checkbox.type = "checkbox"; checkbox.checked = group.normalize !== false;
    checkbox.addEventListener("change", () => { group.normalize = checkbox.checked; markDraft(); });
    normalize.title = "Apply the normalization settings to this group. Turn off to match the original title.";
    normalize.append(checkbox, document.createTextNode("Use normalized text"));
    bottom.append(add, normalize);
    const allTerms = group.match === "all";
    card.append(bottom, element("p", "group-description", group.policy === "exclude" ? (allTerms ? "All phrases in this group must match to exclude the listing." : "Any matching phrase excludes the listing, even if required groups match.") : group.policy === "review" ? (allTerms ? "All phrases in this group must match to send the listing to review." : "A matching phrase sends the listing to review.") : allTerms ? "Every term in this group must match. Other required groups must match too." : "At least one alias in this group must match. Other required groups must match too."));
    return card;
  });
  if (!nodes.length) nodes.push(emptyState("Start with what matters", "Add a subject, a product type, or explicit exclusions. An empty draft adds no title rules of its own; enabled Discord filters still apply.", "filter"));
  $("rule-groups").replaceChildren(...nodes);
}
function renderRules() {
  renderGroups();
  $("normalization-controls").replaceChildren(...NORMALIZATION.map(([key, title, description]) => {
    const label = element("label", "checkbox-label settings-toggle");
    const input = element("input"); input.type = "checkbox"; input.checked = Boolean(state.draft.normalization[key]);
    input.addEventListener("change", () => { state.draft.normalization[key] = input.checked; markDraft(); });
    const text = element("span", "", title); text.append(element("small", "", description));
    label.append(input, text); return label;
  }));
  $("source-controls").replaceChildren(...Object.entries(SOURCES).map(([source, title]) => {
    const label = element("label", "checkbox-label settings-toggle");
    const input = element("input"); input.type = "checkbox"; input.checked = state.draft.sources.includes(source);
    input.addEventListener("change", () => { state.draft.sources = input.checked ? [...state.draft.sources, source] : state.draft.sources.filter((value) => value !== source); markDraft(); });
    label.append(input, element("span", "", title)); return label;
  }));
  $("price-min").value = state.draft.price.min ?? "";
  $("price-max").value = state.draft.price.max ?? "";
  $("include-legacy").checked = state.draft.include_legacy !== false;
  $("legacy-summary").textContent = `Existing Discord filters (${state.legacy.length})`;
  $("legacy-filter-list").replaceChildren(...(state.legacy.length ? state.legacy.map((filter) => {
    const row = element("div", "legacy-item");
    row.append(element("strong", "", `${filter.method || "Unspecified method"} · ${filter.type || filter.policy || "Filter"}${filter.enabled === false ? " · disabled" : ""}`), element("p", "", filter.value || "No value saved"));
    return row;
  }) : [element("p", "muted", "No existing Discord filters for this search.")]));
  updateActions();
  $("version-badge").replaceChildren(element("span", "status-dot"), element("span", "", state.active ? `Published · v${state.active.version}` : state.selected ? "No published ruleset" : "Review workspace"));
  markDraft();
}
function renderReplayStatus() {
  $("replay-status").textContent = state.replay && state.replayRevision !== state.revision ? "Your draft has changed since this replay. Run it again to compare the latest draft." : state.replay ? "Recorded decisions preserve what happened at the time. Published and draft decisions are re-evaluated against the same saved snapshot." : "";
}
function renderReplay() {
  $("replay-summary").hidden = !state.replay;
  renderReplayStatus();
  if (!state.replay) {
    $("replay-results").replaceChildren(emptyState(state.selected ? "See the difference before publishing" : "Choose a search to replay", state.selected ? "Replay your draft to see which saved listings become allowed, filtered, or need review." : "Select a monitored search in the sidebar. You can still test a title without a search.", "repeat"));
    return;
  }
  const summary = state.replay.summary || {};
  const metrics = [["Snapshots checked", summary.total], ["Draft allowed", summary.accepted], ["Draft filtered", summary.filtered], ["Needs review", summary.review], ["Newly filtered", summary.newly_blocked], ["Newly allowed", summary.newly_allowed], ["Same outcome", summary.unchanged], ["Labeled records", summary.labeled]];
  if (summary.labeled) metrics.push(["Relevant allowed", summary.relevant_allowed], ["Relevant filtered", summary.relevant_blocked], ["Unwanted allowed", summary.unwanted_allowed], ["Unwanted filtered", summary.unwanted_blocked]);
  $("replay-summary").replaceChildren(...metrics.map(([label, value]) => {
    const node = element("div", "replay-stat"); node.append(element("span", "", label), element("strong", "", Number(value || 0).toLocaleString())); return node;
  }));
  const records = state.replay.items || [];
  const nodes = records.map((result) => {
    const candidate = result.candidate;
    const row = element("article", "replay-item");
    const url = safeUrl(candidate.payload?.image_url || candidate.image_url);
    const thumb = url ? element("img", "replay-thumbnail") : element("div", "replay-thumbnail");
    if (url) { thumb.src = url; thumb.alt = ""; thumb.loading = "lazy"; thumb.referrerPolicy = "no-referrer"; thumb.addEventListener("error", () => { thumb.removeAttribute("src"); thumb.alt = "Image unavailable"; }, { once: true }); }
    const main = element("div"); main.append(linkedTitle(candidate));
    const meta = element("div", "candidate-meta"); meta.append(element("span", "candidate-price", money(candidate.payload?.price ?? candidate.price)), element("span", "query-tag", SOURCES[candidate.source] || candidate.source));
    if (FEEDBACK[candidate.feedback]) meta.append(element("span", "query-tag", FEEDBACK[candidate.feedback]));
    main.append(meta);
    const decisions = element("div", "replay-decisions");
    for (const [title, decision] of [["Recorded then", result.original_decision], ["Published now", result.active_decision], ["Your draft", result.draft_decision]]) {
      const node = element("div", "replay-decision"); node.append(element("span", "", title), verdictBadge(decision), explanation(decision)); decisions.append(node);
    }
    main.append(decisions, element("span", `change-badge ${result.change || ""}`, ({ newly_blocked: "Newly filtered", newly_allowed: "Newly allowed", unchanged: "Same outcome", changed: "Changed outcome" })[result.change] || String(result.change || "Same outcome")));
    row.append(thumb, main); return row;
  });
  if (!nodes.length) nodes.push(emptyState("No saved snapshots to replay yet", "New polling snapshots will appear as your bot runs. You can import saved history, or test a title against the draft.", "image"));
  $("replay-results").replaceChildren(...nodes);
  if (summary.truncated) $("replay-status").textContent += ` Evaluated ${Number(summary.total || 0).toLocaleString()} of ${Number(summary.available ?? summary.total ?? 0).toLocaleString()} saved snapshots within the configured replay limit and processing budget.`;
}
async function runReplay(buttonNode) {
  if (!state.rulesReady) { showToast("Wait for this search's rules to load before replaying."); return; }
  if (!state.selected) { showToast("Choose a monitored search to replay."); return; }
  if (state.replaying) return;
  setTab("replay");
  const alertId = state.selected.id;
  const revision = state.revision;
  const selection = state.selectionRequest;
  state.replaying = true;
  updateActions();
  try { await withBusy(buttonNode, async () => {
    $("replay-status").textContent = "Checking the same saved snapshots against published and draft rules…";
    try {
      const data = await api("/api/replay", { method: "POST", body: { alert_id: alertId, ruleset: clone(state.draft) } });
      if (selection !== state.selectionRequest) return;
      state.replay = data;
      state.replayRevision = revision;
      renderReplay();
      showToast(`Replay complete: ${Number(data.summary?.total || 0).toLocaleString()} snapshots checked.`);
    } catch (error) {
      if (selection === state.selectionRequest) $("replay-status").textContent = `Replay could not be completed: ${error.message}`;
      throw error;
    }
  }); } finally { state.replaying = false; updateActions(); }
}
function renderVersions() {
  const nodes = state.versions.map((version) => {
    const active = String(version.id) === String(state.active?.id);
    const card = element("article", `version-card${active ? " active" : ""}`);
    const info = element("div");
    const title = element("div", "version-title", `Version ${version.version}`);
    if (active) title.append(element("span", "decision-badge accepted", "Published"));
    const count = version.ruleset?.groups?.length || 0;
    info.append(title, element("p", "", `${date(version.created_at)} · ${count} match group${count === 1 ? "" : "s"} · Discord filters ${version.ruleset?.include_legacy !== false ? "included" : "off"}`));
    const actions = element("div");
    actions.append(button("Load as draft", () => { state.draft = clone(version.ruleset); markDraft(); renderRules(); setTab("rules"); showToast(`Version ${version.version} loaded as an unpublished draft.`); }));
    if (!active) {
      const restore = button("Restore version", () => withBusy(restore, async () => {
        const alertId = state.selected?.id;
        const selection = state.selectionRequest;
        try {
          await api(`/api/alerts/${encodeURIComponent(alertId)}/rollback`, { method: "POST", body: { version_id: version.id, expected_version_id: state.active?.id ?? null } });
          if (selection !== state.selectionRequest) return;
          await refreshRules(); state.replay = null; renderReplay(); showToast("Version restored. Future checks use its rules.");
        } catch (error) {
          if (error.status === 409 && selection === state.selectionRequest) { await refreshRules(true); notice("Published rules changed in another session. Your draft is preserved; review the current version before restoring."); }
          throw error;
        }
      }));
      actions.append(restore);
    }
    card.append(info, actions); return card;
  });
  if (!nodes.length) nodes.push(emptyState(state.selected ? "Your rule history starts here" : "Choose a search to see its history", state.selected ? "Publish a ruleset to save its first version. Every published change remains available to load or restore." : "Versions belong to a monitored search. Select one in the sidebar.", "clock"));
  $("version-list").replaceChildren(...nodes);
}
function openTitleTest() {
  if (!state.rulesReady) { showToast("Wait for this search's rules to load before testing."); return; }
  $("title-test-result").replaceChildren(); $("title-dialog").showModal(); $("test-title").focus();
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.currentTarget.querySelector("button[type=submit]");
  $("login-error").hidden = true;
  await withBusy(submit, async () => {
    try { await api("/api/login", { method: "POST", body: { token: $("access-key").value } }); $("access-key").value = ""; await openWorkspace(); }
    catch (error) { $("login-error").textContent = error.message; $("login-error").hidden = false; throw error; }
  });
});
$("logout").addEventListener("click", () => withBusy($("logout"), async () => { await api("/api/session", { method: "DELETE", body: {} }); showLogin(); }));
$("alert-search").addEventListener("input", renderAlerts);
$("all-records").addEventListener("click", () => selectAlert(null).catch((error) => showToast(error.message, true)));
document.querySelectorAll(".tab").forEach((node) => node.addEventListener("click", () => setTab(node.dataset.tab)));
$("open-title-test").addEventListener("click", openTitleTest);
$("close-title-test").addEventListener("click", () => $("title-dialog").close());
$("title-dialog").addEventListener("click", (event) => { if (event.target === $("title-dialog")) { const bounds = $("title-dialog").getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) $("title-dialog").close(); } });
let searchTimer;
$("candidate-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.offset = 0; loadCandidates(); }, 250); });
for (const id of ["candidate-source", "candidate-verdict", "candidate-feedback"]) $(id).addEventListener("change", () => { state.offset = 0; loadCandidates(); });
$("candidate-prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - PAGE_SIZE); loadCandidates(); });
$("candidate-next").addEventListener("click", () => { state.offset += PAGE_SIZE; loadCandidates(); });
for (const view of ["grid", "list"]) $("view-" + view).addEventListener("click", () => { state.view = view; $("candidate-list").classList.toggle("list-view", view === "list"); $("view-grid").classList.toggle("active", view === "grid"); $("view-list").classList.toggle("active", view === "list"); });
$("add-subject").addEventListener("click", () => addGroup("subject"));
$("add-product").addEventListener("click", () => addGroup("product"));
$("add-exclusions").addEventListener("click", () => addGroup("exclude"));
$("include-legacy").addEventListener("change", () => { state.draft.include_legacy = $("include-legacy").checked; markDraft(); });
for (const [id, key] of [["price-min", "min"], ["price-max", "max"]]) $(id).addEventListener("input", () => { state.draft.price[key] = $(id).value === "" ? null : $(id).valueAsNumber; markDraft(); });
$("example-rules").addEventListener("click", () => {
  if (state.draft.groups.length) { showToast("The example starts from an empty draft. Reset or remove its groups first."); return; }
  state.draft.groups = [
    { id: "subject", label: "Subject", policy: "require", match: "any", normalize: true, terms: [{ method: "contains", value: "BABYMETAL" }, { method: "contains", value: "ベビーメタル" }] },
    { id: "product", label: "Product type", policy: "require", match: "any", normalize: true, terms: [{ method: "contains", value: "poster" }, { method: "contains", value: "ポスター" }] },
    { id: "exclude", label: "Accessories / bundles", policy: "exclude", match: "any", normalize: true, terms: [{ method: "contains", value: "箱のみ" }, { method: "contains", value: "まとめ売り" }] },
  ];
  markDraft(); renderGroups(); showToast("An example poster search was added to your draft. Edit the terms for your own search.");
});
$("reset-draft").addEventListener("click", () => { state.draft = clone(state.baseline); renderRules(); showToast("Draft reset to the published rules, or empty defaults if none exist."); });
$("apply-json").addEventListener("click", () => {
  try {
    const parsed = JSON.parse($("rules-json").value);
    const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
    if (!isObject(parsed) || !Array.isArray(parsed.groups) || !Array.isArray(parsed.sources) || !isObject(parsed.normalization) || !isObject(parsed.price) || parsed.groups.some((group) => !isObject(group) || !Array.isArray(group.terms) || group.terms.some((term) => !isObject(term) || typeof term.value !== "string"))) throw new Error("Include normalization, groups with term values, price, and sources. Use Test a title to validate matching rules.");
    state.draft = parsed; renderRules(); showToast("JSON applied to the draft. Test or replay it before publishing.");
  } catch (error) { showToast(`Could not apply JSON: ${error.message}`, true); }
});
$("replay-from-rules").addEventListener("click", () => runReplay($("replay-from-rules")));
$("run-replay").addEventListener("click", () => runReplay($("run-replay")));
$("publish-rules").addEventListener("click", () => withBusy($("publish-rules"), async () => {
  if (!state.selected || !state.rulesReady) return;
  const alertId = state.selected.id;
  const selection = state.selectionRequest;
  const revision = state.revision;
  try {
    await api(`/api/alerts/${encodeURIComponent(alertId)}/publish`, { method: "POST", body: { ruleset: clone(state.draft), expected_version_id: state.active?.id ?? null } });
    if (selection !== state.selectionRequest) return;
    const keepEdits = revision !== state.revision;
    await refreshRules(keepEdits); state.replay = null; renderReplay(); showToast(keepEdits ? "Rules published. Your newer edits remain in the draft." : "Rules published. Future checks will use this version.");
  } catch (error) {
    if (error.status === 409 && selection === state.selectionRequest) { await refreshRules(true); notice("Published rules changed in another session. Your draft is preserved; review the current version and replay your draft again."); }
    throw error;
  }
}));
$("import-history").addEventListener("click", () => withBusy($("import-history"), async () => {
  const result = await api("/api/history/import", { method: "POST", body: {} });
  const counts = result.counts || result;
  const values = Object.entries(counts).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · ");
  showToast(values ? `Saved history imported · ${values}` : "Saved history imported. Existing records are kept.");
  notice("Imported history mostly contains previously posted listings. It is useful for review, but does not represent everything earlier filters rejected.");
  await loadCandidates();
}));
$("title-test-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const submit = event.currentTarget.querySelector("button[type=submit]");
  withBusy(submit, async () => {
    const request = ++state.previewRequest;
    const title = $("test-title").value;
    $("title-test-result").replaceChildren(element("p", "muted", "Testing this title against your draft…"));
    let result;
    try { result = await api("/api/preview", { method: "POST", body: { ruleset: clone(state.draft), title, source: $("test-source").value, price: Number($("test-price").value), stock: Number($("test-stock").value), ...(state.selected ? { alert_id: state.selected.id } : {}) } }); }
    catch (error) { if (request === state.previewRequest) $("title-test-result").replaceChildren(element("p", "form-error", error.message)); throw error; }
    if (request !== state.previewRequest) return;
    const decision = result.decision;
    const node = element("div", "preview-result");
    node.append(verdictBadge(decision));
    const original = element("div", "normalized-line"); original.append(element("span", "normalized-label", "Tested original title"), document.createTextNode(title)); node.append(original);
    const normalized = element("div", "normalized-line"); normalized.append(element("span", "normalized-label", "Normalized title"), document.createTextNode(decision.normalized_title || title)); node.append(normalized);
    const reasons = element("ul"); for (const reason of decision.reasons || []) reasons.append(element("li", "", typeof reason === "string" ? reason : reason.message || reason.code));
    if (!reasons.childNodes.length) reasons.append(element("li", "", "No additional title restrictions matched."));
    node.append(reasons); $("title-test-result").replaceChildren(node);
  });
});

try {
  const session = await api("/api/session");
  if (session.authenticated) await openWorkspace(); else showLogin();
} catch (error) { showLogin(); $("login-error").textContent = error.message; $("login-error").hidden = false; }
