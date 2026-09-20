const API_BASE = window.UKA_API_BASE || "http://127.0.0.1:8877";
const LIBRARY_PAGE_SIZE = 5;
const GAP_PAGE_SIZE = 3;
const $ = (id) => document.getElementById(id);

const state = {
  health: null,
  pendingThread: null,
  pendingReview: null,
  events: [],
  knowledge: [],
  gaps: [],
  graph: { nodes: [], edges: [], clusters: [], explorations: [] },
  graphType: "all",
  graphQuery: "",
  selectedGraphNode: null,
  hoveredGraphNode: null,
  graphPositions: new Map(),
  graphTransform: { x: 0, y: 0, k: 1 },
  graphAnimationFrame: null,
  graphSimulationAlpha: 0,
  graphMotionEnabled: true,
  graphColorMode: "community",
  graphDraggingNode: null,
  graphPositionCacheSaved: false,
  libraryLimit: LIBRARY_PAGE_SIZE,
  gapLimit: GAP_PAGE_SIZE,
};

function context() {
  return {
    tenant_id: $("tenant-id").value.trim() || "demo-ui",
    security_scope_id: $("security-scope").value.trim() || "private",
    actor_id: $("actor-id").value.trim() || "control-room",
  };
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[char]);
}

function compact(value, limit = 38) {
  const text = String(value ?? "");
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function percentage(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function humanizeCode(value) {
  const labels = {
    independent_approval_required: "需要独立人工确认",
    experience_context_incomplete: "经验上下文不完整",
    provider_or_contract_failure: "模型或结构化合同异常",
    high_risk_requires_review: "高风险内容需要复核",
    knowledge_gap_preserved: "证据不足，已拒绝形成结论并保留待补方向",
  };
  return labels[value] || String(value || "未说明").replaceAll("_", " ");
}

function setConnection(kind, label) {
  const pill = $("connection-pill");
  pill.className = `connection-pill ${kind}`;
  $("connection-label").textContent = label;
}

function notice(message, kind = "") {
  const element = $("ingest-notice");
  element.textContent = message;
  element.className = `notice ${kind}`;
  element.classList.remove("hidden");
}

function clearNotice() {
  $("ingest-notice").classList.add("hidden");
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`${response.status} · ${body?.detail?.error_type || body?.detail || "API request failed"}`);
  }
  return body;
}

function addEvent(title, detail, status = "COMMITTED") {
  state.events.unshift({
    title,
    detail,
    status,
    time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
  });
  state.events = state.events.slice(0, 7);
  renderEvents();
}

function renderEvents() {
  const element = $("event-list");
  if (!state.events.length) {
    element.innerHTML = `<div class="timeline-empty">还没有活动记录<br /><span>完成一次入库或检索后，这里会出现证据链。</span></div>`;
    return;
  }
  element.innerHTML = state.events.map((event) => `
    <div class="event-item">
      <div class="event-rail"></div>
      <div class="event-copy">
        <strong>${escapeHtml(event.title)}</strong>
        <small class="event-state">${escapeHtml(event.status)} · ${escapeHtml(event.time)}</small>
        <small>${escapeHtml(event.detail)}</small>
      </div>
    </div>`).join("");
}

function relationLabel(value) {
  return ({
    causes: "导致",
    condition: "前提",
    sequence: "随后",
    contrast: "对比",
    exception: "例外",
    supports: "支持",
    enables: "使能",
  })[value] || value || "关联";
}

function locatorLabel(locator) {
  const position = locator?.position || {};
  if (position.start_line) {
    return `行 ${position.start_line}${position.end_line && position.end_line !== position.start_line ? `–${position.end_line}` : ""}`;
  }
  if (position.row) return `第 ${position.row} 行`;
  if (position.pointer) return position.pointer;
  if (position.selector) return position.selector;
  return locator?.locator_type || "原文片段";
}

function highestRisk(scopes) {
  const order = { normal: 0, sensitive: 1, high: 2, prohibited: 3 };
  return (scopes || []).reduce((highest, scope) => (
    (order[scope.risk] || 0) > (order[highest] || 0) ? scope.risk : highest
  ), "normal");
}

function renderApproval(review) {
  const candidates = review.candidates || [];
  const candidate = candidates[0] || {};
  const scopes = review.scopes || [];
  const primaryScope = scopes.find((scope) => (candidate.scope_ids || []).includes(scope.scope_id)) || scopes[0] || {};
  const evidence = review.evidence || [];
  const risk = highestRisk(scopes);
  const riskElement = $("approval-risk");

  state.pendingReview = review;
  $("approval-title").textContent = candidate.title || "待审批知识候选";
  $("approval-copy").textContent = candidates.length
    ? `请核对模型理解、适用边界和 ${review.evidence_count || evidence.length} 条原始证据，再决定是否激活。`
    : "审批数据未完整解析，请谨慎处理或拒绝候选。";
  riskElement.textContent = `RISK ${String(risk).toUpperCase()}`;
  riskElement.className = `approval-risk risk-${risk}`;
  $("approval-thread").textContent = `thread ${review.thread_id || state.pendingThread || "—"}`;

  const lineage = candidate.derived_from_knowledge_ids || [];
  const resolvingGaps = candidate.resolves_gap_ids || [];
  $("approval-overview").innerHTML = `
    <div class="decision-overview-top">
      <div><span>候选经验</span><code>${escapeHtml(candidate.candidate_id || "candidate unavailable")}</code></div>
      <strong>${percentage(candidate.confidence)} confidence</strong>
    </div>
    <h3>${escapeHtml(candidate.title || "没有可用标题")}</h3>
    <p>${escapeHtml(candidate.content || "当前响应没有提供候选概览。")}</p>
    <div class="decision-provenance">
      <span>${escapeHtml(review.classification || candidate.classification || "internal")}</span>
      <span>Experience v${escapeHtml(candidate.experience_schema_version || 1)}</span>
      <span>${escapeHtml(candidate.knowledge_delta || "new")}</span>
      <span>${lineage.length ? `${lineage.length} 条既有经验参与理解` : "首次沉淀"}</span>
      ${resolvingGaps.length ? `<span>拟关闭 ${resolvingGaps.length} 条知识缺口</span>` : ""}
    </div>`;

  const logicSteps = [
    ["背景", candidate.context],
    ["问题", candidate.problem],
    ["机制", candidate.mechanism],
    ["行动", candidate.action],
    ["结果", candidate.outcome],
    ["理解依据", candidate.rationale],
  ].filter(([, value]) => value);
  $("approval-logic").innerHTML = logicSteps.length
    ? logicSteps.map(([label, value], index) => `
      <div class="approval-logic-step">
        <span>${String(index + 1).padStart(2, "0")}</span>
        <div><strong>${escapeHtml(label)}</strong><p>${escapeHtml(value)}</p></div>
      </div>`).join("")
    : `<p class="approval-empty">没有可供判断的理解链，建议拒绝并重新生成。</p>`;

  const relations = candidate.logical_relations || [];
  $("approval-relations-block").classList.toggle("hidden", !relations.length);
  $("approval-relations").innerHTML = relations.map((relation) => `
    <div><p>${escapeHtml(relation.source)}</p><span>${escapeHtml(relationLabel(relation.relation))} →</span><p>${escapeHtml(relation.target)}</p></div>`).join("");

  const scopeTags = [
    ...(primaryScope.domain_labels || primaryScope.domain_ids || []),
    ...(primaryScope.subjects || []),
    ...(primaryScope.tasks || []),
  ].filter(Boolean);
  $("approval-scope").innerHTML = `
    <div class="scope-score"><strong>${percentage(primaryScope.confidence)}</strong><span>范围置信度</span></div>
    <div class="approval-tag-list">${scopeTags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("") || "<span>未分类</span>"}</div>
    ${(primaryScope.preconditions || []).map((value) => `<p><b>前提</b>${escapeHtml(value)}</p>`).join("")}
    ${(primaryScope.exclusions || []).map((value) => `<p><b>排除</b>${escapeHtml(value)}</p>`).join("")}`;

  const reviewFlags = [
    ...(review.errors || []).map((value) => ["error", humanizeCode(value)]),
    ...(review.warnings || []).map((value) => ["warning", humanizeCode(value)]),
    ...(candidate.unknowns || []).map((value) => ["unknown", value]),
    ...(primaryScope.unknowns || []).map((value) => ["unknown", value]),
    ...(candidate.caveats || []).map((value) => ["caveat", value]),
    ...(review.knowledge_gaps || []).map((gap) => [
      "gap-link",
      `拟关联 ${gap.gap_id}：${gap.question}`,
    ]),
  ];
  $("approval-warning-block").classList.toggle("hidden", !reviewFlags.length);
  $("approval-warnings").innerHTML = reviewFlags.map(([kind, value]) => `
    <p class="flag-${escapeHtml(kind)}"><span>${escapeHtml(kind)}</span>${escapeHtml(value)}</p>`).join("");

  $("approval-evidence-count").textContent = `${review.evidence_count || evidence.length} 条原文`;
  $("approval-evidence").innerHTML = evidence.length
    ? evidence.map((source, index) => `
      <details class="approval-source" ${index === 0 ? "open" : ""}>
        <summary><span>${escapeHtml(locatorLabel(source.locator))}</span><code>${escapeHtml(compact(source.evidence_id, 24))}</code></summary>
        <blockquote>${escapeHtml(source.excerpt || "该证据片段无法读取。")}</blockquote>
        <small>SHA-256 · ${escapeHtml(compact(source.content_hash, 32))}</small>
      </details>`).join("")
    : `<p class="approval-empty">没有可显示的原始证据，建议拒绝并检查数据链。</p>`;

  $("approval-loading").classList.add("hidden");
  $("approval-review-body").classList.remove("hidden");
}

async function showApproval(result) {
  const interrupts = result.__interrupt__ || result.interrupts || [];
  const thread = result.thread_id || result.values?.thread_id || result.config?.thread_id;
  if (!thread || (!result.approval_context && !interrupts.length)) return false;

  state.pendingThread = thread;
  $("approval-thread").textContent = `thread ${thread}`;
  $("approval-title").textContent = "正在准备审批信息";
  $("approval-copy").textContent = "系统正在解析候选经验、适用范围与原始证据。";
  $("approval-loading").classList.remove("hidden");
  $("approval-review-body").classList.add("hidden");
  $("approval-drawer").classList.remove("hidden");
  $("approval-drawer").setAttribute("aria-busy", "true");
  requestAnimationFrame(() => $("approval-drawer").scrollIntoView({ behavior: "smooth", block: "start" }));

  try {
    let review = result.approval_context;
    if (!review) {
      const params = new URLSearchParams({
        tenant_id: context().tenant_id,
        security_scope_id: context().security_scope_id,
      });
      const snapshot = await api(`/v1/threads/${encodeURIComponent(thread)}?${params}`);
      review = snapshot.approval_context;
    }
    renderApproval(review || { thread_id: thread, candidates: [], scopes: [], evidence: [] });
  } catch (error) {
    renderApproval({
      thread_id: thread,
      candidates: [],
      scopes: [],
      evidence: [],
      errors: [`审批信息加载失败：${error.message}`],
    });
  } finally {
    $("approval-drawer").setAttribute("aria-busy", "false");
  }
  return true;
}

function hideApproval() {
  state.pendingThread = null;
  state.pendingReview = null;
  $("approval-drawer").classList.add("hidden");
}

async function loadHealth() {
  setConnection("", "连接检查中");
  try {
    const health = await api("/health?connect=true");
    state.health = health;
    const safe = health.safe_status || health;
    $("metric-mode").textContent = String(safe.provider_mode || "—").toUpperCase();
    $("metric-model").textContent = safe.llm_model || "deterministic provider";
    $("metric-version").textContent = safe.graph_version || "0.3.1";
    setConnection("ok", "API 已连接");
    addEvent("Provider handshake", `${safe.llm_provider || "local"} · ${safe.llm_model || "deterministic"}`, "HEALTHY");
  } catch (error) {
    setConnection("error", "API 未连接");
    $("metric-mode").textContent = "OFFLINE";
    $("metric-model").textContent = "请启动 8877 端口后刷新";
    notice(`无法连接 ${API_BASE}：${error.message}`, "error");
  }
}

async function ingest() {
  clearNotice();
  const text = $("source-text").value.trim();
  if (!text) {
    notice("请先粘贴一段原始材料。", "warn");
    $("source-text").focus();
    return;
  }
  const button = $("ingest-button");
  button.disabled = true;
  button.querySelector("span").textContent = "路由与理解中…";
  try {
    const result = await api("/v1/ingest", {
      method: "POST",
      body: JSON.stringify({
        ...context(),
        text,
        classification: $("classification").value,
        auto_approve: false,
      }),
    });
    const thread = result.thread_id || result.values?.thread_id;
    const outcome = result.status || result.values?.status || result.next_action || "review";
    addEvent("Knowledge intake", `${outcome} · ${compact(thread || result.operation_id || "evidence staged")}`, "REVIEW_REQUIRED");
    if (await showApproval(result)) {
      notice(`审批决策单已生成：${thread}`, "warn");
    } else if (outcome === "abstained" || result.response?.reason === "knowledge_gap_preserved") {
      const gapCount = (result.knowledge_gap_ids || result.response?.knowledge_gap_ids || []).length;
      notice(`证据不足，Agent 已拒绝形成结论；${gapCount} 条可能方向已进入待补知识。`, "warn");
      addEvent("Epistemic abstention", `${gapCount} gap${gapCount === 1 ? "" : "s"} preserved`, "ABSTAINED");
      await loadKnowledge();
    } else {
      notice(`入库完成：${compact(JSON.stringify(result), 150)}`);
    }
  } catch (error) {
    notice(`入库失败：${error.message}`, "error");
    addEvent("Knowledge intake", error.message, "FAILED");
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "送入知识图谱";
  }
}

function renderRetrieval(result) {
  const payload = result.response || result;
  const pack = payload.evidence_pack || {};
  const items = pack.items || [];
  const gaps = pack.knowledge_gaps || [];
  const unknowns = pack.unknowns || [];
  const answer = payload.answer || pack.answer || "unknown";
  const status = payload.status || result.status || pack.status || "unknown";
  const evidenceCards = items.map((item) => {
    const experience = item.experience || {};
    const evidence = item.evidence || [];
    return `<article class="retrieved-experience">
      <div><strong>${escapeHtml(experience.title || item.knowledge_id || "经验词条")}</strong><span>${percentage(item.confidence)} confidence</span></div>
      <p>${escapeHtml(item.content || "")}</p>
      ${experience.rationale ? `<small><b>为什么：</b>${escapeHtml(experience.rationale)}</small>` : ""}
      <details><summary>查看 ${evidence.length} 条原文证据</summary>${evidence.map((source) => `<blockquote>${escapeHtml(source.excerpt || source.evidence_id || "evidence")}</blockquote>`).join("")}</details>
    </article>`;
  }).join("");
  const gapCards = gaps.map((gap) => `<article class="retrieved-gap">
    <div><strong>${escapeHtml(gap.question || gap.gap_id)}</strong><span>${escapeHtml(gapStatusLabel(gap.research_status || gap.status))}</span></div>
    <p>${escapeHtml(gap.reason_unresolved || "现有证据不足以安全回答。")}</p>
    ${(gap.possible_directions || []).length ? `<small><b>可补方向：</b>${escapeHtml(gap.possible_directions.join(" · "))}</small>` : ""}
  </article>`).join("");
  $("retrieval-result").innerHTML = `<div class="answer-card">
    <div class="answer-status"><span>${escapeHtml(({ answered: "已回答", answered_with_gaps: "回答并保留缺口", abstained: "已拒答", review_required: "需要复核", unknown: "未知" })[String(status).toLowerCase()] || String(status))}</span><span>${gaps.length ? `${gaps.length} 条待补缺口` : `${items.length} 条经验`}</span></div>
    <div class="answer-text">${gaps.length ? "当前证据不足，Agent 已主动拒绝给出确定答案。" : escapeHtml(answer)}</div>
    ${unknowns.length ? `<div class="unknown-line">未知项：${escapeHtml(unknowns.join(" · "))}</div>` : ""}
    <div class="retrieved-list">${gapCards || evidenceCards || `<div class="evidence-item"><span>evidence pack empty</span><b>UNKNOWN</b></div>`}</div>
  </div>`;
}

async function retrieve() {
  const query = $("query-text").value.trim();
  if (!query) return;
  const button = $("retrieve-button");
  button.disabled = true;
  button.textContent = "检索中…";
  try {
    const scope = $("domain-scope").value.trim();
    const result = await api("/v1/retrieve", {
      method: "POST",
      body: JSON.stringify({
        ...context(),
        query,
        query_scope: scope ? { domain: scope } : {},
        limit: 5,
      }),
    });
    renderRetrieval(result);
    const payload = result.response || result;
    const retrievalStatus = String(payload.status || result.status || payload.evidence_pack?.status || "unknown").toUpperCase();
    addEvent("Scoped retrieval", `${retrievalStatus} · ${compact(query, 30)}`, retrievalStatus);
  } catch (error) {
    $("retrieval-result").innerHTML = `<div class="notice error">检索失败：${escapeHtml(error.message)}</div>`;
    addEvent("Scoped retrieval", error.message, "FAILED");
  } finally {
    button.disabled = false;
    button.innerHTML = `运行检索 <span>⌘ ↵</span>`;
  }
}

async function resume(decision) {
  const thread = state.pendingThread;
  if (!thread) return;
  const buttons = [$("approve-button"), $("reject-button")];
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const result = await api(`/v1/threads/${encodeURIComponent(thread)}/resume?tenant_id=${encodeURIComponent(context().tenant_id)}&security_scope_id=${encodeURIComponent(context().security_scope_id)}`, {
      method: "POST",
      body: JSON.stringify({ value: { decision } }),
    });
    addEvent("Human gate", `${decision.toUpperCase()} · ${compact(thread)}`, decision === "approve" ? "APPROVED" : "REJECTED");
    if (result.__interrupt__?.length) {
      await showApproval(result);
    } else {
      hideApproval();
    }
    notice(decision === "approve" ? "已批准，知识进入沉淀流程。" : "已拒绝，候选保持非活动且可追溯。", decision === "approve" ? "" : "warn");
    await refreshThreadEvents(thread);
    if (decision === "approve") await loadKnowledge();
  } catch (error) {
    notice(`审批失败：${error.message}`, "error");
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function refreshThreadEvents(thread) {
  try {
    const events = await api(`/v1/threads/${encodeURIComponent(thread)}/events?tenant_id=${encodeURIComponent(context().tenant_id)}&security_scope_id=${encodeURIComponent(context().security_scope_id)}&limit=10`);
    (Array.isArray(events) ? events : []).slice(0, 3).forEach((event) => addEvent(
      event.event_type || "thread event",
      `${event.status || "recorded"} · ${compact(event.event_id || "")}`,
      String(event.status || "RECORDED").toUpperCase(),
    ));
  } catch (_) {
    // Timeline failure must not invalidate an already completed approval decision.
  }
}

function libraryScope(entry) {
  return entry.domain_labels?.[0] || entry.domain_ids?.[0] || "unclassified";
}

function libraryTags(entry) {
  return [...(entry.subjects || []), ...(entry.tasks || [])].filter(Boolean).slice(0, 4);
}

function libraryQuery(entry) {
  const anchor = entry.source_identifiers?.[0] || entry.subjects?.[0] || libraryScope(entry);
  const task = entry.tasks?.[0] || "关键注意事项";
  return `${anchor} ${task}`;
}

function experienceSteps(entry) {
  return [
    ["背景", entry.context],
    ["问题", entry.problem],
    ["机制", entry.mechanism],
    ["行动", entry.action],
    ["结果", entry.outcome],
    ["理解依据", entry.rationale],
  ].filter(([, value]) => value);
}

function gapStatusLabel(status) {
  return ({
    open: "待补证",
    research_exhausted: "搜索后仍待补",
    research_unavailable: "搜索不可用",
    partially_resolved: "部分解决",
    resolved: "已解决",
    blocked: "已阻止外发",
    completed: "已完成",
    no_results: "无结果",
  })[String(status || "open").toLowerCase()] || String(status || "待补证");
}

function domainUiLabel(domain) {
  const normalized = String(domain || "unknown").trim().toLowerCase().replace(/[\s-]+/g, "_");
  return ({
    general: "通用知识",
    mechanical_engineering: "机械工程",
    finance: "财务",
    medicine: "医疗",
    legal: "法律合规",
    software_engineering: "软件工程",
    agriculture: "农业",
    education: "教育",
    astrophysics: "天体物理",
    logistics: "物流",
    linguistics: "语言学",
    cybersecurity: "网络安全",
    electrical_engineering: "电气工程",
    civil_engineering: "土木工程",
    materials_science: "材料科学",
    manufacturing: "制造",
    energy: "能源",
    environment: "环境科学",
    physics: "物理学",
    chemistry: "化学",
    biology: "生物学",
    mathematics: "数学",
    economics: "经济学",
    business: "商业管理",
    psychology: "心理学",
    social_science: "社会科学",
    history: "历史",
    arts: "艺术",
    unknown: "未分类",
    unclassified: "未分类",
  })[normalized] || String(domain || "未分类");
}

function renderKnowledge(entries) {
  const grid = $("knowledge-grid");
  const moreButton = $("library-more");
  const filter = $("library-filter").value.trim().toLowerCase();
  const visible = (entries || []).filter((entry) => !filter || JSON.stringify(entry).toLowerCase().includes(filter));
  const displayed = visible.slice(0, state.libraryLimit);
  $("library-summary").textContent = `${visible.length} 条 active knowledge · 默认显示 ${Math.min(displayed.length, visible.length)} 条`;

  if (!visible.length) {
    grid.innerHTML = `<div class="library-empty"><span class="empty-glyph">⌁</span><div><strong>${filter ? "没有匹配的知识词条" : "当前作用域还没有 active knowledge"}</strong><p>${filter ? "换一个领域、主题或关键词试试。" : "完成一次入库并批准后，词条会出现在这里。"}</p></div></div>`;
    moreButton.classList.add("hidden");
    return;
  }

  grid.innerHTML = displayed.map((entry) => {
    const tags = libraryTags(entry);
    const query = libraryQuery(entry);
    const steps = experienceSteps(entry);
    const relations = entry.logical_relations || [];
    const sources = entry.source_evidence || [];
    const caveats = entry.caveats || [];
    const learning = entry.learning || {};
    const evolution = entry.evolution;
    return `<details class="knowledge-card compact-knowledge-card">
      <summary class="knowledge-summary">
        <div class="knowledge-summary-main">
          <div class="knowledge-card-top"><div><span class="domain-badge">${escapeHtml(libraryScope(entry))}</span><span class="schema-badge">EXPERIENCE v${escapeHtml(entry.experience_schema_version || 1)}</span></div><span class="knowledge-state">${escapeHtml(String(entry.status || "active").toUpperCase())}</span></div>
          <h3>${escapeHtml(entry.title || entry.subjects?.[0] || entry.source_identifiers?.[0] || "Knowledge entry")}</h3>
          <p class="knowledge-content">${escapeHtml(entry.content || "")}</p>
        </div>
        <div class="knowledge-summary-meta"><span><b>${percentage(entry.confidence)}</b> confidence</span><span>${escapeHtml((entry.evidence_ids || []).length)} evidence</span><i aria-hidden="true">⌄</i></div>
      </summary>
      <div class="knowledge-detail">
        ${steps.length ? `<div class="experience-logic">${steps.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><p>${escapeHtml(value)}</p></div>`).join("")}</div>` : ""}
        ${relations.length ? `<div class="relation-chain"><span>原文逻辑关系</span>${relations.map((relation) => `<p><b>${escapeHtml(relation.source || "")}</b><em>${escapeHtml(relationLabel(relation.relation))} →</em><b>${escapeHtml(relation.target || "")}</b></p>`).join("")}</div>` : ""}
        <div class="knowledge-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("") || `<span>general</span>`}</div>
        ${caveats.length || (entry.preconditions || []).length || (entry.exclusions || []).length ? `<div class="boundary-box"><span>适用边界</span>${(entry.preconditions || []).map((value) => `<p>前提 · ${escapeHtml(value)}</p>`).join("")}${(entry.exclusions || []).map((value) => `<p>排除 · ${escapeHtml(value)}</p>`).join("")}${caveats.map((value) => `<p>注意 · ${escapeHtml(value)}</p>`).join("")}</div>` : ""}
        <details class="source-compare"><summary>原文对照 · ${sources.length} 个证据片段 · ${escapeHtml(entry.evidence_integrity || "unknown")}</summary>${sources.map((source) => `<div><code>${escapeHtml(source.evidence_id || "evidence")}</code><blockquote>${escapeHtml(source.excerpt || "")}</blockquote></div>`).join("") || (entry.source_excerpts || []).map((excerpt) => `<blockquote>${escapeHtml(excerpt)}</blockquote>`).join("")}</details>
        ${learning.mode ? `<div class="learning-line"><span>知识演进</span><p>${escapeHtml(learning.knowledge_delta || "new")} · ${escapeHtml((learning.derived_from_knowledge_ids || []).length)} 条既有经验参与理解 · ${escapeHtml((learning.resolves_gap_ids || []).length)} 条缺口被此版本关闭 · 自动激活 ${learning.automatic_activation ? "开启" : "关闭"}</p>${evolution ? `<small>${escapeHtml(String(evolution.status || "candidate").toUpperCase())} · 需经过 ${(evolution.required_gates || []).map(escapeHtml).join(" → ")}</small>` : ""}</div>` : ""}
        <div class="knowledge-meta"><span>rev ${escapeHtml(entry.revision || 1)}</span><span>${escapeHtml(entry.source_identifiers?.[0] || "no source id")}</span><span>${escapeHtml(entry.knowledge_id || "knowledge")}</span></div>
        <div class="knowledge-footer"><span>完整详情已展开</span><button class="knowledge-query-button" type="button" data-query="${escapeHtml(query)}" data-domain="${escapeHtml(entry.domain_ids?.[0] || "")}">用这条经验检索 ↗</button></div>
      </div>
    </details>`;
  }).join("");

  grid.querySelectorAll(".compact-knowledge-card").forEach((card) => card.addEventListener("toggle", () => {
    if (!card.open) return;
    grid.querySelectorAll(".compact-knowledge-card[open]").forEach((other) => {
      if (other !== card) other.open = false;
    });
  }));
  grid.querySelectorAll(".knowledge-query-button").forEach((button) => button.addEventListener("click", () => {
    $("query-text").value = button.dataset.query || "";
    $("domain-scope").value = button.dataset.domain || "";
    $("scope-chip").textContent = button.dataset.domain || context().security_scope_id;
    $("retrieval-result").scrollIntoView({ behavior: "smooth", block: "center" });
    $("query-text").focus();
  }));

  moreButton.classList.toggle("hidden", visible.length <= LIBRARY_PAGE_SIZE);
  if (visible.length > LIBRARY_PAGE_SIZE) {
    moreButton.textContent = state.libraryLimit < visible.length
      ? `显示更多 · 还有 ${visible.length - displayed.length} 条`
      : `收起到前 ${LIBRARY_PAGE_SIZE} 条`;
  }
}

function renderGaps(entries) {
  const grid = $("gap-grid");
  const moreButton = $("gap-more");
  const visible = entries || [];
  const displayed = visible.slice(0, state.gapLimit);
  $("gap-summary").textContent = `${visible.length} 条开放缺口 · 默认显示 ${Math.min(displayed.length, visible.length)} 条`;
  if (!visible.length) {
    grid.innerHTML = `<div class="library-empty gap-empty"><span class="empty-glyph">✓</span><div><strong>当前没有待补知识</strong><p>明确经验会进入 Active Knowledge；已解决的缺口会保留谱系但不再阻断检索。</p></div></div>`;
    moreButton.classList.add("hidden");
    return;
  }
  grid.innerHTML = displayed.map((gap) => {
    const attempts = gap.research_attempts || [];
    const directions = gap.possible_directions || [];
    const missing = gap.missing_evidence || [];
    const keys = gap.linking_keys || [];
    const rawDomain = gap.domain_ids?.[0] || "unknown";
    const domain = domainUiLabel(rawDomain);
    return `<details class="gap-card">
      <summary class="gap-summary-row">
        <div class="gap-summary-main">
          <div><span class="gap-state">${escapeHtml(gapStatusLabel(gap.research_status || gap.status))}</span><span class="domain-badge">${escapeHtml(domain)}</span></div>
          <h3>${escapeHtml(gap.question || "未命名知识缺口")}</h3>
          <p>${escapeHtml(gap.reason_unresolved || "现有证据不足以形成结论。")}</p>
        </div>
        <div class="gap-summary-meta"><b>${escapeHtml(attempts.length)}</b><span>次研究尝试</span><i>⌄</i></div>
      </summary>
      <div class="gap-detail">
        <div class="gap-track"><span class="done">拒答</span><i>→</i><span class="done">${attempts.length ? "已搜索" : "搜索不可用"}</span><i>→</i><span>待补证</span><i>→</i><span>链接关闭</span></div>
        <div class="gap-columns">
          <div><strong>还缺什么</strong>${missing.map((value) => `<p>${escapeHtml(value)}</p>`).join("") || "<p>需要补充可核验证据</p>"}</div>
          <div><strong>可能方向</strong>${directions.map((value) => `<p>${escapeHtml(value)}</p>`).join("") || "<p>等待后续材料</p>"}</div>
        </div>
        ${attempts.length ? `<details class="gap-research"><summary>联网研究记录 · ${attempts.length} 次</summary>${attempts.map((attempt) => `<p><b>${escapeHtml(gapStatusLabel(attempt.status))}</b><span>${escapeHtml(attempt.query || "")}</span><small>${escapeHtml(attempt.result_count || 0)} 条结果</small></p>`).join("")}</details>` : ""}
        <div class="gap-keys"><span>回链关键词</span>${keys.map((key) => `<code>${escapeHtml(key)}</code>`).join("") || "<code>等待补充</code>"}</div>
        <div class="knowledge-footer gap-actions"><span>${escapeHtml(gap.gap_id || "gap")}</span><div><button class="gap-query-button" type="button" data-query="${escapeHtml(keys.join(" ") || gap.question || "")}" data-domain="${escapeHtml(rawDomain)}">按缺口检索</button><button class="gap-supplement-toggle" type="button" data-gap-id="${escapeHtml(gap.gap_id || "")}">手工补证 ↗</button></div></div>
        <form class="gap-supplement-form hidden" data-gap-id="${escapeHtml(gap.gap_id || "")}">
          <div class="gap-supplement-heading"><strong>为这个缺口补充证据</strong><span>提交后仍需审批，不会直接关闭</span></div>
          <label>补充的事实、定义或完整解释<textarea name="evidence_text" required maxlength="1000000" placeholder="请写清术语定义、适用条件、机制和可核验结果。不要只写“我确认”。"></textarea></label>
          <label>来源说明（可选）<input name="source_note" maxlength="2000" placeholder="例如：设备手册第 4.2 节、现场负责人确认、实验记录编号"></label>
          <div class="gap-supplement-submit"><small>系统会把材料精确绑定到当前缺口；证据仍不足时，缺口会继续保留。</small><button type="submit">生成补证候选</button></div>
        </form>
      </div>
    </details>`;
  }).join("");
  grid.querySelectorAll(".gap-card").forEach((card) => card.addEventListener("toggle", () => {
    if (!card.open) return;
    grid.querySelectorAll(".gap-card[open]").forEach((other) => {
      if (other !== card) other.open = false;
    });
  }));
  grid.querySelectorAll(".gap-query-button").forEach((button) => button.addEventListener("click", () => {
    $("query-text").value = button.dataset.query || "";
    $("domain-scope").value = ["unknown", "unclassified", "未分类"].includes(button.dataset.domain) ? "" : button.dataset.domain || "";
    $("scope-chip").textContent = domainUiLabel(button.dataset.domain) || context().security_scope_id;
    $("retrieval-result").scrollIntoView({ behavior: "smooth", block: "center" });
    $("query-text").focus();
  }));
  grid.querySelectorAll(".gap-supplement-toggle").forEach((button) => button.addEventListener("click", () => {
    const form = grid.querySelector(`.gap-supplement-form[data-gap-id="${CSS.escape(button.dataset.gapId || "")}"]`);
    if (!form) return;
    form.classList.toggle("hidden");
    button.textContent = form.classList.contains("hidden") ? "手工补证 ↗" : "收起补证";
    if (!form.classList.contains("hidden")) form.elements.evidence_text.focus();
  }));
  grid.querySelectorAll(".gap-supplement-form").forEach((form) => form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitGapSupplement(form);
  }));
  moreButton.classList.toggle("hidden", visible.length <= GAP_PAGE_SIZE);
  if (visible.length > GAP_PAGE_SIZE) {
    moreButton.textContent = state.gapLimit < visible.length
      ? `显示更多缺口 · 还有 ${visible.length - displayed.length} 条`
      : `收起到前 ${GAP_PAGE_SIZE} 条`;
  }
}

async function submitGapSupplement(form) {
  clearNotice();
  const gapId = form.dataset.gapId || "";
  const evidenceText = form.elements.evidence_text.value.trim();
  const sourceNote = form.elements.source_note.value.trim();
  if (!gapId || !evidenceText) {
    notice("请先填写能够解释这个缺口的事实或证据。", "warn");
    form.elements.evidence_text.focus();
    return;
  }
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  button.textContent = "分析补证中…";
  try {
    const threadId = `gap-supplement-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    const result = await api(`/v1/knowledge-gaps/${encodeURIComponent(gapId)}/supplements`, {
      method: "POST",
      body: JSON.stringify({
        ...context(),
        evidence_text: evidenceText,
        source_note: sourceNote || null,
        classification: $("classification").value,
        thread_id: threadId,
      }),
    });
    const outcome = result.status || result.values?.status || "review";
    addEvent("人工补证", `${outcome} · ${compact(gapId, 28)}`, outcome === "abstained" ? "仍待补证" : "待审批");
    if (await showApproval(result)) {
      notice("补证候选已生成。请在审批区核对模型理解和原始证据；批准后才会关闭这个缺口。", "warn");
    } else if (outcome === "abstained") {
      notice("这次补充仍不足以形成可靠结论，缺口已保留并更新。", "warn");
    } else {
      notice(`补证处理完成：${outcome}`);
    }
    await loadKnowledge();
  } catch (error) {
    notice(`手工补证失败：${error.message}`, "error");
    addEvent("人工补证", error.message, "失败");
  } finally {
    button.disabled = false;
    button.textContent = "生成补证候选";
  }
}

const GRAPH_TYPE_LABELS = {
  domain: "领域",
  cluster: "聚类",
  knowledge: "知识",
  knowledge_gap: "缺口",
};

const GRAPH_RELATION_LABELS = {
  belongs_to_domain: "属于领域",
  member_of_cluster: "属于聚类",
  supports: "支持",
  refines: "细化",
  contradicts: "冲突",
  requires: "依赖",
  enables: "促成",
  analogous_to: "类比",
  applies_to: "适用于",
  bridges: "跨域桥梁",
  shares_domain_context: "共享领域语境",
  has_open_gap: "存在缺口",
};

const GRAPH_COMMUNITY_COLORS = [
  "#0e8f87", "#3478d4", "#8a62d3", "#dc6b70", "#d6932f", "#3f9f68",
  "#397f99", "#b45f9b", "#7d8f36", "#cc7650", "#5e70c9", "#2f9c9f",
];
const GRAPH_TYPE_COLORS = {
  domain: "#507780",
  cluster: "#0e8f87",
  knowledge: "#4b78c2",
  knowledge_gap: "#d18a2d",
};
const GRAPH_VIEW = { width: 1000, height: 620, cx: 500, cy: 310 };

function graphHash(value) {
  let hash = 2166136261;
  for (const char of String(value || "")) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function graphDegreeMap() {
  const degrees = new Map((state.graph.nodes || []).map((node) => [String(node.node_id), 0]));
  (state.graph.edges || []).forEach((edge) => {
    const source = String(edge.source_id);
    const target = String(edge.target_id);
    degrees.set(source, (degrees.get(source) || 0) + 1);
    degrees.set(target, (degrees.get(target) || 0) + 1);
  });
  return degrees;
}

function graphCommunityMap() {
  const communities = new Map();
  (state.graph.nodes || []).forEach((node) => {
    const id = String(node.node_id);
    if (node.node_type === "cluster") communities.set(id, id);
    if (node.node_type === "domain") communities.set(id, `domain:${id}`);
  });
  (state.graph.edges || [])
    .filter((edge) => edge.relation === "member_of_cluster")
    .sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0))
    .forEach((edge) => {
      const source = String(edge.source_id);
      const target = String(edge.target_id);
      const clusterId = graphClusterMap().has(target) ? target : graphClusterMap().has(source) ? source : null;
      const memberId = clusterId === target ? source : target;
      if (clusterId && !communities.has(memberId)) communities.set(memberId, clusterId);
    });
  return communities;
}

function graphNodeColor(node, communities = graphCommunityMap()) {
  if (state.graphColorMode === "type") return GRAPH_TYPE_COLORS[node.node_type] || "#507780";
  const community = communities.get(String(node.node_id)) || `${node.node_type}:${node.node_id}`;
  return GRAPH_COMMUNITY_COLORS[graphHash(community) % GRAPH_COMMUNITY_COLORS.length];
}

function graphNodeRadius(node, degree = 0) {
  const base = { domain: 8, cluster: 10, knowledge: 5.5, knowledge_gap: 7 }[node.node_type] || 6;
  return Math.min(22, base + Math.sqrt(Math.max(0, degree)) * 1.7);
}

function graphNodeMap() {
  return new Map((state.graph.nodes || []).map((node) => [String(node.node_id), node]));
}

function graphClusterMap() {
  return new Map((state.graph.clusters || []).map((cluster) => [String(cluster.cluster_id), cluster]));
}

function graphConnectedIds(nodeId) {
  const connected = new Set([nodeId]);
  (state.graph.edges || []).forEach((edge) => {
    if (String(edge.source_id) === nodeId) connected.add(String(edge.target_id));
    if (String(edge.target_id) === nodeId) connected.add(String(edge.source_id));
  });
  return connected;
}

function layoutGraph() {
  if (state.graphAnimationFrame) cancelAnimationFrame(state.graphAnimationFrame);
  state.graphAnimationFrame = null;
  const degrees = graphDegreeMap();
  const cacheKey = `uka-graph-layout:${context().tenant_id}:${context().security_scope_id}`;
  let cached = {};
  try {
    cached = JSON.parse(localStorage.getItem(cacheKey) || "{}");
  } catch (_error) {
    cached = {};
  }
  const positions = new Map();
  (state.graph.nodes || []).forEach((node) => {
    const id = String(node.node_id);
    const seed = graphHash(id);
    const angle = ((seed % 10000) / 10000) * Math.PI * 2;
    const jitter = ((seed >>> 8) % 48) - 24;
    const radiusByType = { cluster: 105, knowledge: 215, domain: 305, knowledge_gap: 285 };
    const radial = (radiusByType[node.node_type] || 220) + jitter;
    const prior = cached[id];
    positions.set(id, {
      x: Number.isFinite(prior?.x) ? prior.x : GRAPH_VIEW.cx + Math.cos(angle) * radial,
      y: Number.isFinite(prior?.y) ? prior.y : GRAPH_VIEW.cy + Math.sin(angle) * radial * 0.66,
      vx: 0,
      vy: 0,
      r: graphNodeRadius(node, degrees.get(id) || 0),
      seed,
    });
  });
  state.graphPositions = positions;
  state.graphPositionCacheSaved = false;
}

function graphEdgeControl(source, target, key = "") {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const bend = (((graphHash(key) % 200) / 200) - 0.5) * Math.min(38, distance * 0.14);
  return {
    x: (source.x + target.x) / 2 - (dy / distance) * bend,
    y: (source.y + target.y) / 2 + (dx / distance) * bend,
  };
}

function graphEdgePath(source, target, key = "") {
  const control = graphEdgeControl(source, target, key);
  return `M ${source.x} ${source.y} Q ${control.x} ${control.y} ${target.x} ${target.y}`;
}

function graphEdgePoint(source, target, key, t) {
  const control = graphEdgeControl(source, target, key);
  const oneMinus = 1 - t;
  return {
    x: oneMinus * oneMinus * source.x + 2 * oneMinus * t * control.x + t * t * target.x,
    y: oneMinus * oneMinus * source.y + 2 * oneMinus * t * control.y + t * t * target.y,
  };
}

function graphNodeMarkup(node, degree, anchor, communities) {
  const id = escapeHtml(node.node_id);
  const type = node.node_type || "knowledge";
  const title = compact(node.title || node.node_id, type === "cluster" ? 22 : 18);
  const radius = graphNodeRadius(node, degree);
  const color = graphNodeColor(node, communities);
  return `<g class="graph-node graph-node-${escapeHtml(type)}${anchor ? " is-anchor" : ""}" data-node-id="${id}" data-degree="${escapeHtml(degree)}" tabindex="0" role="button" aria-label="${escapeHtml(GRAPH_TYPE_LABELS[type] || type)}：${escapeHtml(node.title || node.node_id)}" style="--node-color:${color}">
    <circle class="graph-node-halo" r="${radius + 9}"></circle>
    <circle class="graph-node-orbit" r="${radius + 4}"></circle>
    <circle class="graph-node-core" r="${radius}"></circle>
    <circle class="graph-node-spark" r="${Math.max(2.2, radius * 0.28)}" cx="${-radius * 0.22}" cy="${-radius * 0.24}"></circle>
    <text class="graph-node-label" x="${radius + 9}" y="-1">${escapeHtml(title)}</text>
    <text class="graph-node-score" x="${radius + 9}" y="12">${escapeHtml(GRAPH_TYPE_LABELS[type] || type)} · ${escapeHtml(degree)} 连接</text>
    <title>${escapeHtml(node.title || node.node_id)}</title>
  </g>`;
}

function graphDisplayPosition(id, position, now = 0) {
  if (!position) return null;
  if (!state.graphMotionEnabled || state.graphDraggingNode === id || state.graphSimulationAlpha > 0.025) return position;
  const phase = now / 1350 + (position.seed % 628) / 100;
  const amplitude = 1.4 + (position.seed % 7) * 0.18;
  return { ...position, x: position.x + Math.sin(phase) * amplitude, y: position.y + Math.cos(phase * 0.86) * amplitude };
}

function refreshGraphGeometry(now = performance.now()) {
  const edges = $("graph-edges");
  const nodes = $("graph-nodes");
  if (!edges || !nodes) return;
  const displayed = new Map();
  nodes.querySelectorAll(".graph-node").forEach((element) => {
    const position = graphDisplayPosition(element.dataset.nodeId, state.graphPositions.get(element.dataset.nodeId), now);
    if (position) displayed.set(element.dataset.nodeId, position);
    if (position) element.setAttribute("transform", `translate(${position.x} ${position.y})`);
  });
  edges.querySelectorAll(".graph-edge").forEach((element) => {
    const source = displayed.get(element.dataset.sourceId) || state.graphPositions.get(element.dataset.sourceId);
    const target = displayed.get(element.dataset.targetId) || state.graphPositions.get(element.dataset.targetId);
    if (source && target) element.setAttribute("d", graphEdgePath(source, target, element.dataset.edgeId));
  });
  $("graph-particles")?.querySelectorAll(".graph-flow-particle").forEach((particle) => {
    const source = displayed.get(particle.dataset.sourceId) || state.graphPositions.get(particle.dataset.sourceId);
    const target = displayed.get(particle.dataset.targetId) || state.graphPositions.get(particle.dataset.targetId);
    if (!source || !target) return;
    const speed = Number(particle.dataset.speed || 0.00016);
    const phase = Number(particle.dataset.phase || 0);
    const point = graphEdgePoint(source, target, particle.dataset.edgeId, (now * speed + phase) % 1);
    particle.setAttribute("cx", point.x);
    particle.setAttribute("cy", point.y);
  });
}

function applyGraphTransform() {
  const viewport = $("graph-viewport");
  const { x, y, k } = state.graphTransform;
  viewport.setAttribute("transform", `translate(${x} ${y}) scale(${k})`);
}

function graphTargetRadius(type) {
  return { cluster: 105, knowledge: 215, domain: 305, knowledge_gap: 285 }[type] || 220;
}

function saveGraphPositionCache() {
  if (state.graphPositionCacheSaved || !state.graphPositions.size) return;
  const payload = {};
  state.graphPositions.forEach((position, id) => { payload[id] = { x: Math.round(position.x * 10) / 10, y: Math.round(position.y * 10) / 10 }; });
  try {
    localStorage.setItem(`uka-graph-layout:${context().tenant_id}:${context().security_scope_id}`, JSON.stringify(payload));
    state.graphPositionCacheSaved = true;
  } catch (_error) {
    state.graphPositionCacheSaved = true;
  }
}

function graphSimulationStep(now) {
  const visible = graphVisibilitySet();
  const nodeMap = graphNodeMap();
  const active = [...state.graphPositions.entries()].filter(([id]) => visible.has(id));
  const alpha = state.graphSimulationAlpha;
  if (alpha > 0.025) {
    for (let index = 0; index < active.length; index += 1) {
      const [idA, a] = active[index];
      for (let otherIndex = index + 1; otherIndex < active.length; otherIndex += 1) {
        const [idB, b] = active[otherIndex];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let distance = Math.hypot(dx, dy);
        if (distance < 0.01) {
          const angle = ((graphHash(`${idA}:${idB}`) % 628) / 100);
          dx = Math.cos(angle);
          dy = Math.sin(angle);
          distance = 1;
        }
        const ux = dx / distance;
        const uy = dy / distance;
        const repulsion = (1700 * alpha) / (distance * distance + 45);
        a.vx -= ux * repulsion;
        a.vy -= uy * repulsion;
        b.vx += ux * repulsion;
        b.vy += uy * repulsion;
        const minimum = a.r + b.r + 8;
        if (distance < minimum) {
          const collision = (minimum - distance) * 0.055 * alpha;
          a.vx -= ux * collision;
          a.vy -= uy * collision;
          b.vx += ux * collision;
          b.vy += uy * collision;
        }
      }
    }
    (state.graph.edges || []).forEach((edge) => {
      const sourceId = String(edge.source_id);
      const targetId = String(edge.target_id);
      if (!visible.has(sourceId) || !visible.has(targetId)) return;
      const source = state.graphPositions.get(sourceId);
      const target = state.graphPositions.get(targetId);
      if (!source || !target) return;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const ideal = edge.relation === "belongs_to_domain" ? 155 : edge.relation === "has_open_gap" ? 112 : 128;
      const force = (distance - ideal) * 0.0022 * alpha * Math.max(0.45, Number(edge.confidence || 0.6));
      source.vx += (dx / distance) * force;
      source.vy += (dy / distance) * force;
      target.vx -= (dx / distance) * force;
      target.vy -= (dy / distance) * force;
    });
    active.forEach(([id, position]) => {
      if (state.graphDraggingNode === id) return;
      const node = nodeMap.get(id);
      const dx = position.x - GRAPH_VIEW.cx;
      const dy = (position.y - GRAPH_VIEW.cy) / 0.66;
      const angle = Math.atan2(dy, dx);
      const targetRadius = graphTargetRadius(node?.node_type);
      const targetX = GRAPH_VIEW.cx + Math.cos(angle) * targetRadius;
      const targetY = GRAPH_VIEW.cy + Math.sin(angle) * targetRadius * 0.66;
      position.vx += (targetX - position.x) * 0.0018 * alpha;
      position.vy += (targetY - position.y) * 0.0018 * alpha;
      position.vx += (GRAPH_VIEW.cx - position.x) * 0.00014 * alpha;
      position.vy += (GRAPH_VIEW.cy - position.y) * 0.00014 * alpha;
      position.vx *= 0.88;
      position.vy *= 0.88;
      position.x = Math.max(34, Math.min(GRAPH_VIEW.width - 34, position.x + position.vx));
      position.y = Math.max(34, Math.min(GRAPH_VIEW.height - 34, position.y + position.vy));
    });
    state.graphSimulationAlpha *= 0.972;
  } else {
    saveGraphPositionCache();
  }
  refreshGraphGeometry(now);
  if (state.graphMotionEnabled || state.graphSimulationAlpha > 0.02) {
    state.graphAnimationFrame = requestAnimationFrame(graphSimulationStep);
  } else {
    state.graphAnimationFrame = null;
  }
}

function startGraphSimulation(alpha = 0.72) {
  state.graphSimulationAlpha = Math.max(state.graphSimulationAlpha, alpha);
  state.graphPositionCacheSaved = false;
  if (!state.graphAnimationFrame) state.graphAnimationFrame = requestAnimationFrame(graphSimulationStep);
}

function stopGraphAnimation() {
  if (state.graphAnimationFrame) cancelAnimationFrame(state.graphAnimationFrame);
  state.graphAnimationFrame = null;
}

function renderGraphClusterList() {
  const container = $("graph-cluster-list");
  const clusters = [...(state.graph.clusters || [])]
    .sort((a, b) => Number(b.priority_score || 0) - Number(a.priority_score || 0))
    .slice(0, 8);
  if (!clusters.length) {
    container.innerHTML = `<p class="graph-sidebar-empty">当前作用域还没有聚类。</p>`;
    return;
  }
  container.innerHTML = `<span class="graph-sidebar-label">优先探索聚类</span>${clusters.map((cluster, index) => {
    const domains = (cluster.domain_hypotheses || []).slice(0, 2).map((item) => domainUiLabel(item.domain_id)).join(" × ");
    return `<button class="graph-cluster-row" type="button" data-node-id="${escapeHtml(cluster.cluster_id)}"><b>${String(index + 1).padStart(2, "0")}</b><span><strong>${escapeHtml(cluster.name || "未命名聚类")}</strong><small>${escapeHtml(domains || "待判定领域")}</small></span><em>${escapeHtml(percentage(cluster.priority_score || 0))}</em></button>`;
  }).join("")}`;
  container.querySelectorAll(".graph-cluster-row").forEach((button) => button.addEventListener("click", () => selectGraphNode(button.dataset.nodeId)));
}

function renderGraphInspector(nodeId = state.selectedGraphNode) {
  const inspector = $("graph-inspector");
  const nodeMap = graphNodeMap();
  const clusterMap = graphClusterMap();
  const node = nodeMap.get(String(nodeId || ""));
  if (!node) {
    const counts = (state.graph.nodes || []).reduce((result, item) => {
      result[item.node_type] = (result[item.node_type] || 0) + 1;
      return result;
    }, {});
    const topCluster = [...(state.graph.clusters || [])].sort((a, b) => Number(b.priority_score || 0) - Number(a.priority_score || 0))[0];
    inspector.innerHTML = `<div class="graph-inspector-empty"><span>网络概览</span><h3>${escapeHtml((state.graph.nodes || []).length)} 个节点</h3><p>${escapeHtml((state.graph.edges || []).length)} 条有依据的连接，跨越 ${escapeHtml(counts.domain || 0)} 个领域。</p><dl><div><dt>知识</dt><dd>${escapeHtml(counts.knowledge || 0)}</dd></div><div><dt>聚类</dt><dd>${escapeHtml(counts.cluster || 0)}</dd></div><div><dt>缺口</dt><dd>${escapeHtml(counts.knowledge_gap || 0)}</dd></div></dl>${topCluster ? `<button type="button" class="graph-focus-button" data-node-id="${escapeHtml(topCluster.cluster_id)}">查看最高优先聚类 ↗</button>` : ""}<small>点击节点查看领域概率、缺失信息与连接理由。</small></div>`;
    inspector.querySelector(".graph-focus-button")?.addEventListener("click", (event) => selectGraphNode(event.currentTarget.dataset.nodeId));
    return;
  }
  const type = node.node_type || "knowledge";
  const cluster = clusterMap.get(String(node.node_id));
  const edges = (state.graph.edges || []).filter((edge) => String(edge.source_id) === String(node.node_id) || String(edge.target_id) === String(node.node_id));
  const relations = edges.slice(0, 10).map((edge) => {
    const otherId = String(edge.source_id) === String(node.node_id) ? String(edge.target_id) : String(edge.source_id);
    const other = nodeMap.get(otherId);
    return `<button type="button" data-node-id="${escapeHtml(otherId)}"><span>${escapeHtml(GRAPH_RELATION_LABELS[edge.relation] || edge.relation)}</span><strong>${escapeHtml(compact(other?.title || otherId, 32))}</strong><small>${escapeHtml(percentage(edge.confidence || 0))}</small></button>`;
  }).join("");
  const domainHypotheses = cluster?.domain_hypotheses || node.domain_hypotheses || [];
  const hypothesisMarkup = domainHypotheses.slice(0, 6).map((hypothesis) => `<div class="graph-hypothesis"><div><span>${escapeHtml(domainUiLabel(hypothesis.domain_id))}</span><b>${escapeHtml(percentage(hypothesis.probability || 0))}</b></div><i style="--probability:${Math.max(0, Math.min(1, Number(hypothesis.probability || 0)))}"></i><p>${escapeHtml(hypothesis.rationale || "模型未提供说明")}</p></div>`).join("");
  const missing = cluster?.missing_information || [];
  inspector.innerHTML = `<header class="graph-inspector-heading"><span>${escapeHtml(GRAPH_TYPE_LABELS[type] || type)}</span><button id="graph-inspector-close" type="button" aria-label="关闭详情">×</button></header>
    <h3>${escapeHtml(node.title || node.node_id)}</h3>
    <p class="graph-inspector-summary">${escapeHtml(node.summary || cluster?.summary || (type === "domain" ? "受控领域节点，连接所有明确归属到这里的知识。" : "暂无内容概览。"))}</p>
    ${cluster ? `<div class="graph-score-grid"><div><span>综合优先级</span><strong>${escapeHtml(percentage(cluster.priority_score || 0))}</strong></div><div><span>信息缺口</span><strong>${escapeHtml(percentage(cluster.missing_score || 0))}</strong></div><div><span>潜在领域</span><strong>${escapeHtml(percentage(cluster.potential_score || 0))}</strong></div></div>` : ""}
    ${hypothesisMarkup ? `<section class="graph-inspector-block"><span>领域可能性</span>${hypothesisMarkup}</section>` : ""}
    ${missing.length ? `<section class="graph-inspector-block"><span>仍需补充</span><ul>${missing.slice(0, 8).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>` : ""}
    <section class="graph-inspector-block graph-connections"><span>直接连接 · ${escapeHtml(edges.length)}</span>${relations || "<p>当前节点没有直接连接。</p>"}</section>`;
  $("graph-inspector-close").addEventListener("click", () => selectGraphNode(null));
  inspector.querySelectorAll(".graph-connections button").forEach((button) => button.addEventListener("click", () => selectGraphNode(button.dataset.nodeId)));
}

function graphVisibilitySet() {
  const nodeMap = graphNodeMap();
  const query = state.graphQuery.trim().toLowerCase();
  const type = state.graphType;
  if (!query && type === "all") return new Set(nodeMap.keys());
  const matches = new Set();
  nodeMap.forEach((node, id) => {
    const cluster = graphClusterMap().get(id);
    const haystack = JSON.stringify({ node, cluster }).toLowerCase();
    if ((!query || haystack.includes(query)) && (type === "all" || node.node_type === type)) matches.add(id);
  });
  const visible = new Set(matches);
  (state.graph.edges || []).forEach((edge) => {
    const source = String(edge.source_id);
    const target = String(edge.target_id);
    if (matches.has(source)) visible.add(target);
    if (matches.has(target)) visible.add(source);
  });
  return visible;
}

function refreshGraphFocus() {
  const selected = state.selectedGraphNode ? String(state.selectedGraphNode) : null;
  const hovered = state.hoveredGraphNode ? String(state.hoveredGraphNode) : null;
  const focus = hovered || selected;
  const related = focus ? graphConnectedIds(focus) : new Set();
  const visible = graphVisibilitySet();
  $("graph-nodes").querySelectorAll(".graph-node").forEach((element) => {
    const id = element.dataset.nodeId;
    element.classList.toggle("is-hidden", !visible.has(id));
    element.classList.toggle("is-selected", id === selected);
    element.classList.toggle("is-hovered", id === hovered);
    element.classList.toggle("is-related", Boolean(focus && related.has(id) && id !== focus));
    element.classList.toggle("is-muted", Boolean(focus && !related.has(id)));
  });
  $("graph-edges").querySelectorAll(".graph-edge").forEach((element) => {
    const source = element.dataset.sourceId;
    const target = element.dataset.targetId;
    const active = Boolean(focus && (source === focus || target === focus));
    const hidden = !visible.has(source) || !visible.has(target);
    element.classList.toggle("is-hidden", hidden);
    element.classList.toggle("is-active", active);
    element.classList.toggle("is-muted", Boolean(focus && !active));
  });
  renderGraphParticles(focus, visible);
  $("graph-cluster-list").querySelectorAll(".graph-cluster-row").forEach((button) => button.classList.toggle("active", button.dataset.nodeId === selected));
}

function renderGraphParticles(focus, visible) {
  const container = $("graph-particles");
  if (!container) return;
  if (!focus || !state.graphMotionEnabled) {
    container.innerHTML = "";
    return;
  }
  const nodeMap = graphNodeMap();
  const communities = graphCommunityMap();
  const edges = (state.graph.edges || [])
    .filter((edge) => visible.has(String(edge.source_id)) && visible.has(String(edge.target_id)) && (String(edge.source_id) === focus || String(edge.target_id) === focus))
    .slice(0, 12);
  container.innerHTML = edges.map((edge, index) => {
    const sourceId = String(edge.source_id);
    const source = nodeMap.get(sourceId);
    const color = source ? graphNodeColor(source, communities) : "#0e8f87";
    const edgeId = String(edge.edge_id || `${sourceId}:${edge.target_id}:${index}`);
    return [0, 0.5].map((phase, particleIndex) => `<circle class="graph-flow-particle" r="${particleIndex ? 2.1 : 3}" data-edge-id="${escapeHtml(edgeId)}" data-source-id="${escapeHtml(sourceId)}" data-target-id="${escapeHtml(edge.target_id)}" data-phase="${phase + index * 0.071}" data-speed="${0.00013 + (index % 4) * 0.000012}" style="--particle-color:${color}"></circle>`).join("");
  }).join("");
  refreshGraphGeometry();
}

function selectGraphNode(nodeId) {
  state.selectedGraphNode = nodeId ? String(nodeId) : null;
  state.hoveredGraphNode = null;
  refreshGraphFocus();
  renderGraphInspector();
}

function drawKnowledgeGraph() {
  const nodeMap = graphNodeMap();
  const degreeMap = graphDegreeMap();
  const communities = graphCommunityMap();
  const anchors = new Set([...(state.graph.clusters || [])]
    .sort((a, b) => Number(b.priority_score || 0) - Number(a.priority_score || 0))
    .slice(0, 7)
    .map((cluster) => String(cluster.cluster_id)));
  const validEdges = (state.graph.edges || []).filter((edge) => nodeMap.has(String(edge.source_id)) && nodeMap.has(String(edge.target_id)));
  $("graph-edges").innerHTML = validEdges.map((edge, index) => {
    const source = nodeMap.get(String(edge.source_id));
    const color = source ? graphNodeColor(source, communities) : "#8aa0a3";
    const edgeId = String(edge.edge_id || `${edge.source_id}:${edge.target_id}:${index}`);
    return `<path class="graph-edge relation-${escapeHtml(edge.relation || "related")}" data-edge-id="${escapeHtml(edgeId)}" data-source-id="${escapeHtml(edge.source_id)}" data-target-id="${escapeHtml(edge.target_id)}" data-relation="${escapeHtml(edge.relation || "related")}" style="--edge-color:${color};--edge-opacity:${Math.max(0.08, Math.min(0.32, Number(edge.confidence || 0.5) * 0.28))}"><title>${escapeHtml(GRAPH_RELATION_LABELS[edge.relation] || edge.relation)} · ${escapeHtml(edge.rationale || "")}</title></path>`;
  }).join("");
  $("graph-nodes").innerHTML = (state.graph.nodes || []).map((node) => graphNodeMarkup(node, degreeMap.get(String(node.node_id)) || 0, anchors.has(String(node.node_id)), communities)).join("");
  $("graph-nodes").querySelectorAll(".graph-node").forEach((element) => {
    element.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") selectGraphNode(element.dataset.nodeId);
    });
    element.addEventListener("pointerenter", () => {
      if (state.graphDraggingNode) return;
      state.hoveredGraphNode = element.dataset.nodeId;
      refreshGraphFocus();
    });
    element.addEventListener("pointerleave", () => {
      if (state.hoveredGraphNode === element.dataset.nodeId) {
        state.hoveredGraphNode = null;
        refreshGraphFocus();
      }
    });
  });
  refreshGraphGeometry();
  applyGraphTransform();
  refreshGraphFocus();
  renderGraphClusterList();
  renderGraphInspector();
  startGraphSimulation(0.86);
}

function setupGraphPointerControls() {
  const svg = $("knowledge-graph-svg");
  let drag = null;
  svg.addEventListener("pointerdown", (event) => {
    const nodeElement = event.target.closest?.(".graph-node");
    const scaleX = 1000 / Math.max(1, svg.clientWidth);
    const scaleY = 620 / Math.max(1, svg.clientHeight);
    if (nodeElement) {
      const id = nodeElement.dataset.nodeId;
      const position = state.graphPositions.get(id);
      if (!position) return;
      drag = { mode: "node", id, startX: event.clientX, startY: event.clientY, x: position.x, y: position.y, scaleX, scaleY, moved: false };
      state.graphDraggingNode = id;
      state.hoveredGraphNode = id;
    } else {
      drag = { mode: "pan", startX: event.clientX, startY: event.clientY, x: state.graphTransform.x, y: state.graphTransform.y, scaleX, scaleY, moved: false };
    }
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const screenDx = event.clientX - drag.startX;
    const screenDy = event.clientY - drag.startY;
    if (!drag.moved && Math.hypot(screenDx, screenDy) < 4) return;
    drag.moved = true;
    const dx = screenDx * drag.scaleX;
    const dy = screenDy * drag.scaleY;
    if (drag.mode === "node") {
      const position = state.graphPositions.get(drag.id);
      if (!position) return;
      position.x = drag.x + dx / state.graphTransform.k;
      position.y = drag.y + dy / state.graphTransform.k;
      position.vx = 0;
      position.vy = 0;
      state.graphPositionCacheSaved = false;
      refreshGraphGeometry();
    } else {
      state.graphTransform.x = drag.x + dx;
      state.graphTransform.y = drag.y + dy;
      applyGraphTransform();
    }
  });
  const finish = (event, cancelled = false) => {
    const completed = drag;
    if (completed && svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    drag = null;
    state.graphDraggingNode = null;
    if (!cancelled && completed?.mode === "node" && !completed.moved) selectGraphNode(completed.id);
    if (completed?.moved) startGraphSimulation(0.18);
  };
  svg.addEventListener("pointerup", (event) => finish(event));
  svg.addEventListener("pointercancel", (event) => finish(event, true));
  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.12 : 0.89;
    state.graphTransform.k = Math.max(0.55, Math.min(2.4, state.graphTransform.k * factor));
    applyGraphTransform();
  }, { passive: false });
}

function changeGraphZoom(factor) {
  state.graphTransform.k = Math.max(0.55, Math.min(2.4, state.graphTransform.k * factor));
  applyGraphTransform();
}

function fitKnowledgeGraph() {
  state.graphTransform = { x: 0, y: 0, k: 1 };
  applyGraphTransform();
}

function toggleGraphMotion() {
  state.graphMotionEnabled = !state.graphMotionEnabled;
  const button = $("graph-motion");
  button.classList.toggle("active", state.graphMotionEnabled);
  button.textContent = state.graphMotionEnabled ? "暂停漂移" : "恢复漂移";
  $("graph-motion-status").textContent = state.graphMotionEnabled ? "动态布局" : "布局已暂停";
  refreshGraphFocus();
  if (state.graphMotionEnabled) startGraphSimulation(0.04);
  else if (state.graphSimulationAlpha <= 0.02) stopGraphAnimation();
}

function toggleGraphColorMode() {
  state.graphColorMode = state.graphColorMode === "community" ? "type" : "community";
  $("graph-color-mode").textContent = state.graphColorMode === "community" ? "按聚类着色" : "按类型着色";
  drawKnowledgeGraph();
}

async function loadKnowledgeGraph() {
  const empty = $("graph-empty");
  empty.classList.remove("hidden");
  try {
    stopGraphAnimation();
    const params = new URLSearchParams({
      tenant_id: context().tenant_id,
      security_scope_id: context().security_scope_id,
      limit: "2000",
    });
    const graph = await api(`/v1/knowledge-graph?${params}`);
    state.graph = {
      nodes: Array.isArray(graph.nodes) ? graph.nodes : [],
      edges: Array.isArray(graph.edges) ? graph.edges : [],
      clusters: Array.isArray(graph.clusters) ? graph.clusters : [],
      explorations: Array.isArray(graph.explorations) ? graph.explorations : [],
    };
    state.selectedGraphNode = null;
    state.hoveredGraphNode = null;
    layoutGraph();
    drawKnowledgeGraph();
    const crossDomain = state.graph.clusters.filter((cluster) => (cluster.domain_hypotheses || []).length > 1).length;
    $("graph-summary").textContent = `${state.graph.nodes.length} 节点 · ${state.graph.edges.length} 连接 · ${crossDomain} 个跨学科聚类`;
    empty.classList.toggle("hidden", state.graph.nodes.length > 0);
    if (!state.graph.nodes.length) empty.innerHTML = `<span>⌁</span><strong>当前作用域还没有知识网络</strong><p>完成知识入库和聚类后，这里会出现领域、聚类、知识与缺口。</p>`;
  } catch (error) {
    state.graph = { nodes: [], edges: [], clusters: [], explorations: [] };
    $("graph-summary").textContent = "知识网络暂时不可用";
    empty.classList.remove("hidden");
    empty.innerHTML = `<span>!</span><strong>知识网络读取失败</strong><p>${escapeHtml(error.message)}</p>`;
    renderGraphInspector();
  }
}

async function loadGaps() {
  try {
    const params = new URLSearchParams({
      tenant_id: context().tenant_id,
      security_scope_id: context().security_scope_id,
      limit: "100",
    });
    const entries = await api(`/v1/knowledge-gaps?${params}`);
    state.gaps = Array.isArray(entries) ? entries : [];
    state.gapLimit = GAP_PAGE_SIZE;
    renderGaps(state.gaps);
  } catch (error) {
    $("gap-grid").innerHTML = `<div class="library-empty"><span class="empty-glyph">!</span><div><strong>待补知识暂时不可用</strong><p>${escapeHtml(error.message)}</p></div></div>`;
  }
}

async function loadKnowledge() {
  const knowledgeRequest = (async () => {
    try {
    const params = new URLSearchParams({
      tenant_id: context().tenant_id,
      security_scope_id: context().security_scope_id,
      limit: "100",
    });
    const entries = await api(`/v1/knowledge?${params}`);
    state.knowledge = Array.isArray(entries) ? entries : [];
    state.libraryLimit = LIBRARY_PAGE_SIZE;
    renderKnowledge(state.knowledge);
    } catch (error) {
      $("knowledge-grid").innerHTML = `<div class="library-empty"><span class="empty-glyph">!</span><div><strong>知识库暂时不可用</strong><p>${escapeHtml(error.message)}</p></div></div>`;
    }
  })();
  await Promise.all([knowledgeRequest, loadGaps(), loadKnowledgeGraph()]);
}

$("refresh-button").addEventListener("click", loadHealth);
$("ingest-button").addEventListener("click", ingest);
$("retrieve-button").addEventListener("click", retrieve);
$("approve-button").addEventListener("click", () => resume("approve"));
$("reject-button").addEventListener("click", () => resume("reject"));
$("clear-events").addEventListener("click", () => { state.events = []; renderEvents(); });
$("refresh-library").addEventListener("click", loadKnowledge);
$("graph-search").addEventListener("input", (event) => {
  state.graphQuery = event.target.value;
  refreshGraphFocus();
  startGraphSimulation(0.2);
});
$("graph-filter").querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
  state.graphType = button.dataset.type || "all";
  $("graph-filter").querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
  refreshGraphFocus();
  startGraphSimulation(0.24);
}));
$("graph-zoom-in").addEventListener("click", () => changeGraphZoom(1.18));
$("graph-zoom-out").addEventListener("click", () => changeGraphZoom(0.84));
$("graph-fit").addEventListener("click", fitKnowledgeGraph);
$("graph-motion").addEventListener("click", toggleGraphMotion);
$("graph-color-mode").addEventListener("click", toggleGraphColorMode);
$("library-filter").addEventListener("input", () => {
  state.libraryLimit = LIBRARY_PAGE_SIZE;
  renderKnowledge(state.knowledge);
});
$("library-more").addEventListener("click", () => {
  const filter = $("library-filter").value.trim().toLowerCase();
  const visibleCount = state.knowledge.filter((entry) => !filter || JSON.stringify(entry).toLowerCase().includes(filter)).length;
  state.libraryLimit = state.libraryLimit < visibleCount ? state.libraryLimit + LIBRARY_PAGE_SIZE : LIBRARY_PAGE_SIZE;
  renderKnowledge(state.knowledge);
  if (state.libraryLimit === LIBRARY_PAGE_SIZE) $("knowledge-library").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("gap-more").addEventListener("click", () => {
  state.gapLimit = state.gapLimit < state.gaps.length
    ? state.gapLimit + GAP_PAGE_SIZE
    : GAP_PAGE_SIZE;
  renderGaps(state.gaps);
  if (state.gapLimit === GAP_PAGE_SIZE) $("knowledge-gaps").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("tenant-id").addEventListener("input", () => { $("metric-tenant").textContent = `tenant / ${$("tenant-id").value || "—"}`; });
$("security-scope").addEventListener("input", () => {
  $("metric-scope").textContent = $("security-scope").value || "—";
  $("scope-chip").textContent = $("security-scope").value || "—";
});
$("tenant-id").addEventListener("change", loadKnowledge);
$("security-scope").addEventListener("change", loadKnowledge);
document.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() === "r" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) loadHealth();
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") retrieve();
});

loadHealth();
setupGraphPointerControls();
loadKnowledge();
