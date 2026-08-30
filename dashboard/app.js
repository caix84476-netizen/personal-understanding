const state = {
  data: null,
  view: "overview",
  query: "",
  salience: "all",
  entityType: "all",
  contextKind: "all",
  sourceGroup: "All",
  filePath: "",
};

const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
}[char]));
const short = (value, max = 180) => {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1).trim()}…` : text;
};
const kindNames = { event: "Event", state: "State", decision: "Decision", entity: "Entity", model: "Understanding", preference: "Preference", fact: "Fact", rule: "Rule", heuristic: "Heuristic", value: "Value" };
const statusNames = { current: "Current", superseded: "Superseded", archived: "Archived", uncertain: "Uncertain", deleted: "Deleted" };
const salienceNames = { 3: "Spine", 2: "Key", 1: "Related", 0: "Mentioned" };
const viewNames = { overview: "Overview", timeline: "Timeline", entities: "Entities", contexts: "Context cards", sources: "Verbatim & sources", followups: "Follow-ups", diagnostics: "Diagnostics", files: "Files" };

function v2() {
  const value = state.data?.v2 || {};
  return {
    events: value.events || [],
    entities: value.entities || [],
    contexts: value.contexts || [],
    knowledge: value.knowledge || [],
    fragments: value.fragments || [],
    followups: value.followups || [],
    hypotheses: value.hypotheses || [],
    currentState: value.current_state || {},
    audit: value.audit || {},
    manifest: value.manifest || {},
  };
}

function record(id) { return state.data?.records?.find((item) => item.id === id); }
function event(id) { return v2().events.find((item) => item.id === id || item.record_id === id); }
function entity(id) { return v2().entities.find((item) => item.id === id); }
function context(id) { return v2().contexts.find((item) => item.id === id); }
function fragment(id) { return v2().fragments.find((item) => item.id === id); }
function source(path) { return state.data?.sources?.find((item) => item.path === path); }
function canonicalId(id) { return v2().manifest?.entity_redirects?.[id] || id; }
function entityLabel(id) { return entity(canonicalId(id))?.label || id || "Unnamed entity"; }
function routeTo(view, extra = {}) { Object.assign(state, { view, ...extra }); render(); window.scrollTo({ top: 0, behavior: "smooth" }); }
function queryText(item) { return JSON.stringify(item).toLowerCase(); }
function matches(item) { return !state.query.trim() || queryText(item).includes(state.query.trim().toLowerCase()); }
function sortDateDesc(a, b) { return (b.date_start || "0000-00-00").localeCompare(a.date_start || "0000-00-00") || Number(b.salience || 0) - Number(a.salience || 0); }
function sortDateAsc(a, b) { return (a.date_start || "9999-99-99").localeCompare(b.date_start || "9999-99-99") || Number(b.salience || 0) - Number(a.salience || 0); }
function pendingFollowups() { return v2().followups.filter((item) => ["pending", "due", "overdue"].includes(item.status || "pending")); }
function redirectEntries() { return Object.entries(v2().manifest?.entity_redirects || {}); }
function linkedContextsForEvent(eventId) { return v2().contexts.filter((item) => (item.entry_refs || []).includes(eventId)); }
function linkedKnowledgeForEvent(item) {
  const refs = new Set(item.entity_refs || []);
  return v2().knowledge.filter((card) => (card.entity_refs || []).some((id) => refs.has(id)));
}
function linkedSourceRefs(refs) {
  return (refs || []).map((ref) => source(ref)).filter(Boolean);
}

async function load() {
  try {
    const response = await fetch(`/api/snapshot?x=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Read failed: ${response.status}`);
    state.data = await response.json();
    render();
  } catch (error) {
    $("#stage").innerHTML = `<section class="error-state"><h2>Dashboard failed to load</h2><p>${esc(error.message)}</p><button class="action-button" data-reload>Retry</button></section>`;
    bindInteractive();
  }
}

function render() {
  if (!state.data) return;
  $("#route-label").textContent = viewNames[state.view] || "Overview";
  $("#context-bar").innerHTML = `<span>${esc(viewNames[state.view] || "Overview")}</span><span>${state.query ? `Filter: ${esc(state.query)}` : `Generated at ${esc(v2().manifest.generated_at || state.data.generated_at || "unknown")}`}</span>`;
  const renderers = { overview: renderOverview, timeline: renderTimeline, entities: renderEntities, contexts: renderContexts, sources: renderSources, followups: renderFollowups, diagnostics: renderDiagnostics, files: renderFiles };
  (renderers[state.view] || renderOverview)();
}

function metricCard(view, number, label, detail, tone = "plain") {
  return `<button class="metric-card ${tone}" type="button" data-view="${view}"><span class="metric-number">${esc(number)}</span><span class="metric-label">${esc(label)}</span><span class="metric-detail">${esc(detail)}</span><span class="metric-arrow">↗</span></button>`;
}

function renderOverview() {
  const data = v2();
  const audit = data.audit;
  const events = data.events.filter((item) => item.status !== "deleted" && matches(item)).sort(sortDateDesc);
  const recent = events.slice(0, 8);
  const pending = pendingFollowups();
  const verbatimCount = data.fragments.filter((item) => item.fidelity === "verbatim").length;
  const warningCount = audit.metrics?.warnings ?? audit.warnings?.length ?? 0;
  const pipeline = [
    ["Sources", `${state.data.sources?.length || 0}`, "sources / conversation"],
    ["Fragments", `${data.fragments.length}`, "verbatim / summary_only"],
    ["Timeline entries", `${data.events.length}`, "timeline.jsonl"],
    ["Entities", `${data.entities.length}`, "entities.jsonl"],
    ["Contexts", `${data.contexts.length}`, "contexts.jsonl"],
  ];
  $("#stage").innerHTML = `<section class="dashboard-page">
    <div class="dashboard-head">
      <div><p class="eyebrow">Archive status</p><h1>Overview</h1><p class="head-note">Current data, audit entry points, source fidelity, and structural risks.</p></div>
      <button class="status-chip ${audit.status === "failed" ? "danger" : audit.status === "warnings" ? "warn" : "ok"}" type="button" data-view="diagnostics"><strong>${esc(audit.status || "unknown")}</strong><span>${warningCount} warnings</span></button>
    </div>
    <div class="metric-grid">
      ${metricCard("timeline", data.events.length, "Timeline", "Browse by date and memory weight", "green")}
      ${metricCard("entities", data.entities.length, "Entity profiles", "People, schools, objects, works, concepts", "blue")}
      ${metricCard("contexts", data.contexts.length, "Context cards", "Shared events and cross-entity links", "amber")}
      ${metricCard("sources", verbatimCount, "Verbatim evidence", `${data.fragments.filter((item) => item.fidelity === "summary_only").length} legacy summary debts`, "red")}
      ${metricCard("followups", pending.length, "Follow-ups", `${pending.filter((item) => !item.due_at).length} missing due dates`, "violet")}
    </div>
    <div class="audit-strip">
      <div class="strip-title"><span class="eyebrow">Data chain</span><strong>Counts and files for every layer, all clickable</strong></div>
      <div class="pipeline">${pipeline.map(([label, count, file], index) => `<button class="pipeline-step" type="button" data-view="${index === 0 ? "sources" : index === 1 ? "sources" : index === 2 ? "timeline" : index === 3 ? "entities" : "contexts"}"><b>${esc(label)}</b><strong>${esc(count)}</strong><small>${esc(file)}</small></button>`).join('<span class="pipeline-arrow">→</span>' )}</div>
    </div>
    <div class="overview-grid">
      <section class="section-block"><div class="section-heading"><div><p class="eyebrow">Timeline</p><h2>Recent entries</h2></div><button class="text-action" type="button" data-view="timeline">View all ↗</button></div><div class="event-table compact">${recent.map(eventRow).join("") || emptyState("No matching entries")}</div></section>
      <aside class="section-block"><div class="section-heading"><div><p class="eyebrow">Audit entry</p><h2>Current risks</h2></div><button class="text-action" type="button" data-view="diagnostics">Open diagnostics ↗</button></div><div class="issue-list">${issueRows(audit).join("") || emptyState("No structural warnings right now")}</div></aside>
    </div>
    <div class="overview-grid lower">
      <section class="section-block"><div class="section-heading"><div><p class="eyebrow">Current state</p><h2>Core, conditions, tensions</h2></div></div><div class="state-list">${stateCards(data.currentState) || emptyState("Current state is empty")}</div></section>
      <section class="section-block"><div class="section-heading"><div><p class="eyebrow">Operating rules</p><h2>The skill at a glance</h2></div><button class="text-action" type="button" data-view="diagnostics">Open rules ↗</button></div><div class="rule-summary">${ruleSummary()}</div></section>
    </div>
  </section>`;
  bindInteractive();
}

function eventRow(item) {
  return `<button class="event-row" type="button" data-event="${esc(item.id)}"><span class="row-date">${esc(item.date_text || "Undated")}</span><span class="row-weight weight-${esc(item.salience)}">${esc(item.salience_label || salienceNames[item.salience] || "Mentioned")}</span><span class="row-main"><b>${esc(item.title || item.record_id)}</b><small>${esc(short(item.summary, 220))}</small></span><span class="row-entities">${esc((item.entity_refs || []).slice(0, 4).map(entityLabel).join(" · ") || "No entity links")}</span><span class="row-arrow">↗</span></button>`;
}

function stateCards(current) {
  const sections = [["Personal core", current.core], ["Current conditions", current.conditions], ["Lived examples", current.lived_examples], ["Active tensions", current.tensions]];
  return sections.filter(([, rows]) => rows?.length).map(([title, rows]) => `<div class="state-group"><h3>${esc(title)}</h3>${rows.slice(0, 4).map((row) => `<button class="state-row" type="button" data-record="${esc(row.record_ref || row.id)}"><b>${esc(row.title || row.id)}</b><span>${esc(short(row.summary, 150))}</span></button>`).join("")}</div>`).join("");
}

function ruleSummary() {
  return `<div class="rule-summary-row"><span>Verbatim capture</span><b>capture → hash → derive</b></div><div class="rule-summary-row"><span>Retrieval levels</span><b>survey → probe → deep</b></div><div class="rule-summary-row"><span>Entity policy</span><b>canonical + redirect + facet</b></div><div class="rule-summary-row"><span>Validation result</span><b>clean / warnings / failed</b></div>`;
}

function issueRows(audit) {
  const rows = [];
  (audit.errors || []).slice(0, 4).forEach((item) => rows.push(`<button class="issue-row danger" type="button" data-view="diagnostics"><span>Failed</span><b>${esc(item.code || item)}</b><small>${esc(item.id || item.note || "structural error")}</small></button>`));
  (audit.warnings || []).slice(0, 5).forEach((item) => rows.push(`<button class="issue-row warn" type="button" data-view="diagnostics"><span>Warning</span><b>${esc(item.code || item)}</b><small>${esc(item.note || item.action || item.count || "needs review")}</small></button>`));
  return rows;
}

function emptyState(text) { return `<div class="empty-state">${esc(text)}</div>`; }
function pageHeader(eyebrow, title, note) { return `<div class="page-heading"><button class="back-button" type="button" data-view="overview">← Overview</button><p class="eyebrow">${esc(eyebrow)}</p><h1>${esc(title)}</h1><p class="head-note">${esc(note)}</p></div>`; }
function filterBar(content) { return `<div class="filter-bar">${content}</div>`; }

function renderTimeline() {
  const rows = v2().events.filter((item) => matches(item) && (state.salience === "all" || String(item.salience) === state.salience)).sort(sortDateAsc);
  const groups = new Map();
  rows.forEach((item) => { const key = item.date_text || "Undated"; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(item); });
  $("#stage").innerHTML = `<section class="detail-page">${pageHeader("timeline.jsonl", "Timeline", "Each row is one explicit entry; click to inspect entities, context cards, evidence, and neighboring entries.")}${filterBar(`<label>Memory weight<select id="salience-filter"><option value="all">All</option><option value="3">Spine</option><option value="2">Key</option><option value="1">Related</option><option value="0">Mentioned</option></select></label><span class="filter-result">${rows.length} entries</span>`)}<div class="event-table timeline-table">${Array.from(groups.entries()).map(([date, items]) => `<div class="date-group"><div class="date-label">${esc(date)}</div><div>${items.map(eventRow).join("")}</div></div>`).join("") || emptyState("No matching entries")}</div></section>`;
  $("#salience-filter").value = state.salience;
  $("#salience-filter").onchange = (event) => { state.salience = event.target.value; renderTimeline(); };
  bindInteractive();
}

function renderEntities() {
  const all = v2().entities.filter((item) => matches(item)).sort((a, b) => (b.mention_count || 0) - (a.mention_count || 0));
  const rows = state.entityType === "all" ? all : all.filter((item) => item.entity_type === state.entityType);
  const types = ["all", ...new Set(v2().entities.map((item) => item.entity_type).filter(Boolean))];
  $("#stage").innerHTML = `<section class="detail-page">${pageHeader("entities.jsonl", "Entities", "Canonical profiles, aliases, related events, shared contexts, and redirect relations.")}${filterBar(`<label>Type<select id="entity-filter">${types.map((type) => `<option value="${esc(type)}">${esc(type === "all" ? "All types" : type)}</option>`).join("")}</select></label><span class="filter-result">${rows.length}</span>`)}<div class="entity-table">${rows.map(entityRow).join("") || emptyState("No matching entities")}</div></section>`;
  $("#entity-filter").value = state.entityType;
  $("#entity-filter").onchange = (event) => { state.entityType = event.target.value; renderEntities(); };
  bindInteractive();
}

function entityRow(item) {
  const redirects = redirectEntries().filter(([, target]) => target === item.id).map(([from]) => from);
  return `<button class="entity-row" type="button" data-entity="${esc(item.id)}"><span class="entity-type">${esc(item.entity_type || "entity")}</span><span class="entity-main"><b>${esc(item.label || item.id)}</b><small>${esc((item.aliases || []).join(" · "))}</small></span><span class="entity-count">${item.event_refs?.length || 0} events<br>${item.context_refs?.length || 0} contexts</span><span class="entity-redirect">${redirects.length ? `merged ${redirects.length}` : "canonical"}</span><span class="row-arrow">↗</span></button>`;
}

function renderContexts() {
  const rows = v2().contexts.filter((item) => matches(item) && (state.contextKind === "all" || item.kind === state.contextKind));
  $("#stage").innerHTML = `<section class="detail-page">${pageHeader("contexts.jsonl", "Context cards", "Cross entry points over shared events, people, places, and objects. Every card leads back to concrete entries.")}${filterBar(`<label>Type<select id="context-filter"><option value="all">All</option><option value="facet">Cross-entity</option><option value="entity-context">Entity context</option></select></label><span class="filter-result">${rows.length} cards</span>`)}<div class="context-table">${rows.map(contextRow).join("") || emptyState("No matching context cards")}</div></section>`;
  $("#context-filter").value = state.contextKind;
  $("#context-filter").onchange = (event) => { state.contextKind = event.target.value; renderContexts(); };
  bindInteractive();
}

function contextRow(item) {
  const ids = item.entity_ids || item.related_entity_ids || [];
  return `<button class="context-row" type="button" data-context="${esc(item.id)}"><span class="context-kind">${esc(item.kind || "context")}</span><span class="context-main"><b>${esc(item.label || item.id)}</b><small>${esc(ids.map(entityLabel).join(" × "))}</small></span><span class="context-count">${item.entry_refs?.length || 0} entries</span><span class="row-arrow">↗</span></button>`;
}

function renderSources() {
  const groups = ["All", ...new Set((state.data.sources || []).map((item) => item.group))];
  const rows = (state.data.sources || []).filter((item) => (state.sourceGroup === "All" || item.group === state.sourceGroup) && matches(item));
  $("#stage").innerHTML = `<section class="detail-page">${pageHeader("sources/", "Verbatim & sources", "Fidelity and linked records for verbatim captures, images, OCR, external material, and legacy summaries.")}${filterBar(`${groups.map((group) => `<button class="filter-pill ${group === state.sourceGroup ? "active" : ""}" type="button" data-source-group="${esc(group)}">${esc(group)}</button>`).join("")}<span class="filter-result">${rows.length} files</span>`)}<div class="source-table">${rows.map((item) => `<button class="source-row" type="button" data-source="${esc(item.path)}"><span class="source-type">${esc(item.group)}</span><span class="source-main"><b>${esc(item.title)}</b><small>${esc(item.path)}</small></span><span class="source-count">${item.record_ids?.length || 0} linked</span><span class="row-arrow">↗</span></button>`).join("") || emptyState("No matching sources")}</div></section>`;
  document.querySelectorAll("[data-source-group]").forEach((button) => { button.onclick = () => { state.sourceGroup = button.dataset.sourceGroup; renderSources(); }; });
  bindInteractive();
}

function renderFollowups() {
  const rows = v2().followups.filter((item) => matches(item));
  $("#stage").innerHTML = `<section class="detail-page">${pageHeader("followups.jsonl", "Follow-ups", "Original questions, context, dates, and check status.") }<div class="followup-table">${rows.map((item) => `<article class="followup-row ${item.due_at && item.due_at <= new Date().toISOString().slice(0, 10) ? "due" : ""}"><div class="followup-meta"><span>${esc(item.status || "pending")}</span><time>${esc(item.due_at || "date pending")}</time></div><h2>${esc(item.prompt || item.question)}</h2><p>${esc(item.context || "")}</p><small>${esc((item.source_refs || []).join(" · "))}</small></article>`).join("") || emptyState("No follow-ups right now")}</div></section>`;
}

function renderDiagnostics() {
  const data = v2();
  const audit = data.audit;
  const rootRows = state.data.root_structure || [];
  const files = ["SKILL.md", "references/architecture-v2.md", "references/retrieval-policy.md", "references/capture-and-verbatim-policy.md", "references/entity-and-context-policy.md", "references/timeline-and-followup-policy.md", "scripts/preflight_context.py", "scripts/catalog_context.py", "scripts/retrieve_v2.py", "scripts/followup_check.py", "scripts/review_v2.py", "scripts/validate_memory.py", "scripts/rebuild_views.py", "memory/v2/manifest.json", "memory/v2/current-state.json"];
  const redirects = redirectEntries();
  $("#stage").innerHTML = `<section class="detail-page">${pageHeader("diagnostics", "Diagnostics", "Inspect the skill's composition, runtime entry points, data chain, entity merges, and actual warnings.")}
    <div class="diagnostic-status ${audit.status === "failed" ? "danger" : audit.status === "warnings" ? "warn" : "ok"}"><strong>${esc(audit.status || "unknown")}</strong><span>Errors ${audit.metrics?.errors || audit.errors?.length || 0} · Warnings ${audit.metrics?.warnings || audit.warnings?.length || 0}</span><span>Legacy summaries ${data.fragments.filter((item) => item.fidelity === "summary_only").length} · Verbatim ${data.fragments.filter((item) => item.fidelity === "verbatim").length}</span></div>
    <div class="diagnostic-grid"><section class="diagnostic-block"><h2>Runtime chain</h2><div class="runtime-list"><div><b>1</b><span>Verbatim capture</span><small>sources/conversation</small></div><div><b>2</b><span>Fragment index</span><small>memory/v2/fragments.jsonl</small></div><div><b>3</b><span>Timeline entries</span><small>memory/v2/timeline.jsonl</small></div><div><b>4</b><span>Entities & contexts</span><small>entities.jsonl / contexts.jsonl</small></div><div><b>5</b><span>Retrieval & follow-ups</span><small>probe / deep / followups</small></div></div></section><section class="diagnostic-block"><h2>Catalog size</h2><div class="count-list"><span>Records <b>${state.data.records?.length || 0}</b></span><span>Sources <b>${state.data.sources?.length || 0}</b></span><span>Timeline entries <b>${data.events.length}</b></span><span>Entities <b>${data.entities.length}</b></span><span>Context cards <b>${data.contexts.length}</b></span><span>Knowledge cards <b>${data.knowledge.length}</b></span></div></section></div>
    <section class="diagnostic-block"><div class="section-heading"><div><p class="eyebrow">Machine audit</p><h2>Errors and warnings</h2></div></div><div class="issue-list large">${issueRows(audit).join("") || emptyState("No errors or warnings")}</div></section>
    <section class="diagnostic-block"><div class="section-heading"><div><p class="eyebrow">Entity merges</p><h2>canonical and redirect</h2></div></div><div class="redirect-table">${redirects.map(([from, to]) => `<button class="redirect-row" type="button" data-entity="${esc(to)}"><code>${esc(from)}</code><span>→</span><b>${esc(entityLabel(to))}</b><small>Open canonical profile</small></button>`).join("") || emptyState("No redirects")}</div></section>
    <section class="diagnostic-block"><div class="section-heading"><div><p class="eyebrow">Rules and entry points</p><h2>Actual files</h2></div></div><div class="file-links">${files.map((path) => `<button class="file-link" type="button" data-file="${esc(path)}"><code>${esc(path)}</code><span>Open ↗</span></button>`).join("")}</div></section>
    <section class="diagnostic-block"><div class="section-heading"><div><p class="eyebrow">Directory structure</p><h2>Skill directories</h2></div></div><div class="root-table">${rootRows.map((row) => `<button class="root-row" type="button" data-folder="${esc(row.name)}"><b>${esc(row.name)}</b><span>${esc(row.role)}</span><strong>${esc(row.files)} files</strong></button>`).join("")}</div></section>
  </section>`;
  bindInteractive();
}

async function renderFiles() {
  const result = await fetch(`/api/tree?path=${encodeURIComponent(state.filePath)}`).then((response) => response.json());
  if (result.error) { $("#stage").innerHTML = `<section class="detail-page">${pageHeader("Files", "Files", "Read failed")}${emptyState(result.error)}</section>`; return; }
  const parent = result.path ? result.path.split("/").slice(0, -1).join("/") : null;
  $("#stage").innerHTML = `<section class="detail-page">${pageHeader("Files", "Files", "Read-only browsing of the skill directory.") }<div class="file-browser"><div class="file-path">/${esc(result.path || "")}</div>${parent !== null ? `<button class="file-row" type="button" data-folder="${esc(parent)}"><span>←</span><b>Up one level</b></button>` : ""}${result.items.map((item) => `<button class="file-row" type="button" ${item.kind === "folder" ? `data-folder="${esc(item.path)}"` : `data-file="${esc(item.path)}"`}><span>${item.kind === "folder" ? "□" : "—"}</span><b>${esc(item.name)}</b><small>${item.kind === "folder" ? "folder" : esc(item.extension || "file")}</small></button>`).join("")}</div></section>`;
  bindInteractive();
}

function detailSection(title, content) { return `<section class="drawer-section"><h3>${esc(title)}</h3>${content || emptyState("Nothing yet")}</section>`; }
function linkButton(attribute, id, label, meta = "") { return `<button class="drawer-link" type="button" data-${attribute}="${esc(id)}"><b>${esc(label)}</b>${meta ? `<small>${esc(meta)}</small>` : ""}</button>`; }
function fragmentBlock(item) { return `<div class="fragment-block ${item.fidelity === "verbatim" ? "verbatim" : "summary-only"}"><span>${item.fidelity === "verbatim" ? "User verbatim" : "Legacy summary"}</span><p>${esc(item.verbatim || "")}</p><small>${esc((item.source_refs || []).join(" · "))}</small></div>`; }

function openEvent(id) {
  const item = event(id); if (!item) return;
  const contexts = linkedContextsForEvent(item.id);
  const knowledge = linkedKnowledgeForEvent(item);
  const fragments = (item.fragment_refs || []).map(fragment).filter(Boolean);
  const prev = (item.before_ids || []).map(event).filter(Boolean);
  const next = (item.after_ids || []).map(event).filter(Boolean);
  showDrawer(`<div class="drawer-inner"><button class="drawer-close" type="button" data-close>×</button><p class="drawer-kicker">${esc(item.entry_kind)} · ${esc(item.salience_label || salienceNames[item.salience] || "Mentioned")}</p><h2>${esc(item.title || item.record_id)}</h2><p class="drawer-meta">${esc(item.date_text || "Undated")} · ${esc(item.phase || "no phase")} · ${esc(item.record_id)}</p><p class="drawer-summary">${esc(item.summary || "")}</p>${detailSection("Related entities", (item.entity_refs || []).map((id) => linkButton("entity", canonicalId(id), entityLabel(id))).join(""))}${detailSection("Context cards", contexts.map((row) => linkButton("context", row.id, row.label, `${row.entry_refs?.length || 0} shared events`)).join(""))}${detailSection("Knowledge cards", knowledge.slice(0, 12).map((row) => linkButton("record", row.record_id, row.title, `${row.kind} · ${row.salience_label || ""}`)).join(""))}${detailSection("Timeline neighbors", [...prev.map((row) => linkButton("event", row.id, `Before: ${row.title}`, row.date_text)), ...next.map((row) => linkButton("event", row.id, `After: ${row.title}`, row.date_text))].join(""))}${detailSection("Verbatim and sources", fragments.map(fragmentBlock).join(""))}</div>`);
  bindDrawer();
}

function openEntity(id) {
  const item = entity(canonicalId(id)); if (!item) return;
  const events = (item.event_refs || []).map(event).filter(Boolean).sort(sortDateDesc);
  const contexts = (item.context_refs || []).map(context).filter(Boolean);
  const fragments = (item.fragment_refs || []).map(fragment).filter(Boolean);
  const redirects = redirectEntries().filter(([, target]) => target === item.id);
  showDrawer(`<div class="drawer-inner"><button class="drawer-close" type="button" data-close>×</button><p class="drawer-kicker">${esc(item.entity_type || "entity")}</p><h2>${esc(item.label || item.id)}</h2><p class="drawer-meta">${esc((item.aliases || []).join(" · "))}</p><p class="drawer-summary">${esc(item.notes?.join(" ") || "canonical profile")}</p>${redirects.length ? detailSection("Merge history", redirects.map(([from]) => linkButton("record", from, from, "redirected to this profile")).join("")) : ""}${detailSection("Related events", events.map((row) => linkButton("event", row.id, row.title, `${row.date_text || "Undated"} · ${row.salience_label || ""}`)).join(""))}${detailSection("Context cards", contexts.map((row) => linkButton("context", row.id, row.label, `${row.entry_refs?.length || 0} shared events`)).join(""))}${detailSection("Verbatim and sources", fragments.map(fragmentBlock).join(""))}</div>`);
  bindDrawer();
}

function openContext(id) {
  const item = context(id); if (!item) return;
  const events = (item.entry_refs || []).map(event).filter(Boolean).sort(sortDateDesc);
  const entities = item.entity_ids || item.related_entity_ids || [];
  showDrawer(`<div class="drawer-inner"><button class="drawer-close" type="button" data-close>×</button><p class="drawer-kicker">${esc(item.kind || "context")}</p><h2>${esc(item.label || item.id)}</h2><p class="drawer-meta">${esc(entities.map(entityLabel).join(" × "))}</p><p class="drawer-summary">${esc(item.note || "")}</p>${detailSection("Shared events", events.map((row) => linkButton("event", row.id, row.title, `${row.date_text || "Undated"} · ${row.salience_label || ""}`)).join(""))}</div>`);
  bindDrawer();
}

function openRecord(id) {
  const item = record(id); if (!item) return;
  const redirects = item.superseded_by ? [linkButton("entity", item.superseded_by, entityLabel(item.superseded_by), "current canonical")].join("") : "";
  showDrawer(`<div class="drawer-inner"><button class="drawer-close" type="button" data-close>×</button><p class="drawer-kicker">${esc(kindNames[item.kind] || item.kind)} · ${esc(statusNames[item.status] || item.status)}</p><h2>${esc(item.title || item.id)}</h2><p class="drawer-meta">${esc(item.id)}</p>${redirects ? detailSection("Current profile", redirects) : ""}${detailSection("Legacy record body", `<div class="raw"><pre>${esc(item.body || "")}</pre></div>`)}</div>`);
  bindDrawer();
}

async function openSource(path) {
  const item = source(path); if (!item) return;
  showDrawer(`<div class="drawer-inner"><button class="drawer-close" type="button" data-close>×</button><p class="drawer-kicker">${esc(item.group || item.type)}</p><h2>${esc(item.title)}</h2><p class="drawer-meta">${esc(item.path)}</p>${detailSection("Linked records", (item.record_ids || []).map((id) => linkButton("record", id, record(id)?.title || id)).join(""))}${detailSection("Source text", `<div class="raw"><pre id="source-content">Loading…</pre></div>`)}</div>`);
  bindDrawer();
  try { const payload = await fetch(`/api/file?path=${encodeURIComponent(path)}`).then((response) => response.json()); const target = $("#source-content"); if (target) target.textContent = payload.content || "Unable to read"; } catch { const target = $("#source-content"); if (target) target.textContent = "Read failed"; }
}

async function openFile(path) {
  const payload = await fetch(`/api/file?path=${encodeURIComponent(path)}`).then((response) => response.json());
  showDrawer(`<div class="drawer-inner"><button class="drawer-close" type="button" data-close>×</button><p class="drawer-kicker">File</p><h2>${esc(path.split("/").pop())}</h2><p class="drawer-meta">${esc(path)}</p><div class="raw"><pre>${esc(payload.content || "This file cannot be displayed as text.")}</pre></div></div>`);
  bindDrawer();
}

function showDrawer(html) { $("#drawer").innerHTML = html; $("#drawer").classList.add("open"); }
function closeDrawer() { $("#drawer").classList.remove("open"); }
function bindDrawer() { bindInteractive($("#drawer")); }
function bindInteractive(scope = document) {
  scope.querySelectorAll("[data-view]").forEach((button) => { button.onclick = () => routeTo(button.dataset.view); });
  scope.querySelectorAll("[data-event]").forEach((button) => { button.onclick = () => openEvent(button.dataset.event); });
  scope.querySelectorAll("[data-entity]").forEach((button) => { button.onclick = () => openEntity(button.dataset.entity); });
  scope.querySelectorAll("[data-context]").forEach((button) => { button.onclick = () => openContext(button.dataset.context); });
  scope.querySelectorAll("[data-record]").forEach((button) => { button.onclick = () => openRecord(button.dataset.record); });
  scope.querySelectorAll("[data-source]").forEach((button) => { button.onclick = () => openSource(button.dataset.source); });
  scope.querySelectorAll("[data-file]").forEach((button) => { button.onclick = () => openFile(button.dataset.file); });
  scope.querySelectorAll("[data-folder]").forEach((button) => { button.onclick = () => { state.filePath = button.dataset.folder; renderFiles(); }; });
  scope.querySelectorAll("[data-close]").forEach((button) => { button.onclick = closeDrawer; });
  scope.querySelectorAll("[data-reload]").forEach((button) => { button.onclick = load; });
}

document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
$("#home").onclick = () => routeTo("overview");
$("#refresh").onclick = load;
$("#search").oninput = (event) => { state.query = event.target.value; render(); };
load();
