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
  await Promise.all([knowledgeRequest, loadGaps()]);
}

$("refresh-button").addEventListener("click", loadHealth);
$("ingest-button").addEventListener("click", ingest);
$("retrieve-button").addEventListener("click", retrieve);
$("approve-button").addEventListener("click", () => resume("approve"));
$("reject-button").addEventListener("click", () => resume("reject"));
$("clear-events").addEventListener("click", () => { state.events = []; renderEvents(); });
$("refresh-library").addEventListener("click", loadKnowledge);
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
loadKnowledge();
