"use strict";

/* ------------------------------------------------------------------ helpers */
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const short = (h) => (h ? `${h.slice(0, 10)}…${h.slice(-6)}` : "");
const money = (p) => (p.currency === "USD" ? `$${p.amount}` : `${p.amount} ${p.currency}`);

let CONFIG = null;
let JOB = null;
let voiceOn = true;
let lastNarration = "";
let lastActiveCard = null;
let paypalRenderedFor = null;
let paypalScript = null;
let lastAttemptShown = 0;

const RANK = { UPLOADED: 1, CONTRACT_PROPOSED: 2, AGREED: 3, AUTHORIZED: 4, VERIFIED_FAIL: 4.5, VERIFIED_PASS: 5, CAPTURED: 6, VOIDED: 6, EXPIRED: 6 };
const TERMINAL = ["CAPTURED", "VOIDED", "EXPIRED"];
const rank = () => (JOB ? RANK[JOB.state] : 0);

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.form) { init.method = "POST"; init.body = opts.form; }
  else if (opts.body !== undefined || init.method === "POST") {
    init.method = "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body || {});
  }
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, isError ? 7000 : 3500);
}

async function withBusy(btn, label, fn) {
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>${esc(label)}`;
  try { return await fn(); }
  catch (e) { toast(e.message, true); speak(e.message); }
  finally { btn.innerHTML = old; btn.disabled = false; renderAll(); }
}

function store(key, value) {
  try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch (_) { /* storage unavailable */ }
}
function recall(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}

/* -------------------------------------------------------------- voice out */
function pickVoice() {
  const voices = speechSynthesis.getVoices();
  return voices.find((v) => /^en[-_](US|GB|IN)/i.test(v.lang) && /Google|Natural|Samantha|Daniel|Aria|Jenny/i.test(v.name))
    || voices.find((v) => /^en/i.test(v.lang));
}

function speak(text) {
  $("#narration").textContent = text;
  if (!voiceOn || !text || !("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.04;
  const v = pickVoice();
  if (v) u.voice = v;
  const bar = $("#voicebar");
  u.onstart = () => bar.classList.add("speaking");
  u.onend = u.onerror = () => bar.classList.remove("speaking");
  speechSynthesis.speak(u);
}

/* --------------------------------------------------------------- voice in */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let activeRec = null;

function listen(button, onText) {
  if (!SR) { toast("Voice input needs Chrome or Edge. You can type instead.", true); return; }
  if (activeRec) { activeRec.stop(); return; }
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  const rec = new SR();
  rec.lang = "en-US";
  rec.interimResults = true;
  rec.continuous = false;
  let finalText = "";
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) finalText += r[0].transcript; else interim += r[0].transcript;
    }
    onText((finalText + " " + interim).trim(), false);
  };
  rec.onerror = (e) => {
    if (e.error === "not-allowed") toast("Microphone access was blocked. Allow it in the address bar, or type instead.", true);
    else if (!["no-speech", "aborted"].includes(e.error)) toast(`Voice input error: ${e.error}`, true);
  };
  rec.onend = () => {
    button.classList.remove("listening");
    activeRec = null;
    $("#mic-status").textContent = "";
    onText(finalText.trim(), true);
  };
  button.classList.add("listening");
  activeRec = rec;
  rec.start();
}

/* --------------------------------------------------------------- PayPal */
function loadPayPalSdk() {
  if (window.paypal) return Promise.resolve();
  if (paypalScript) return paypalScript;
  paypalScript = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    const params = new URLSearchParams({ "client-id": CONFIG.paypal_client_id, currency: CONFIG.currency, intent: "authorize", components: "buttons" });
    s.src = `https://www.paypal.com/sdk/js?${params}`;
    s.onload = resolve;
    s.onerror = () => { paypalScript = null; reject(new Error("Could not load the PayPal SDK. Check your internet connection and PAYPAL_CLIENT_ID.")); };
    document.head.appendChild(s);
  });
  return paypalScript;
}

async function renderPayPalButtons() {
  const key = JOB.id + JOB.contract_sha256;
  if (paypalRenderedFor === key) return;
  paypalRenderedFor = key;
  const box = $("#paypal-buttons");
  box.innerHTML = '<p class="muted small"><span class="spinner"></span>Loading PayPal…</p>';
  try {
    await loadPayPalSdk();
    box.innerHTML = "";
    const jobId = JOB.id;
    await window.paypal.Buttons({
      style: { layout: "vertical", shape: "rect", label: "paypal" },
      createOrder: async () => (await api(`/api/jobs/${jobId}/paypal/order`, { method: "POST" })).id,
      onApprove: async (data) => {
        try { const r = await api(`/api/jobs/${jobId}/paypal/authorize`, { body: { order_id: data.orderID } }); setJob(r.job); }
        catch (e) { toast(e.message, true); speak(e.message); }
      },
      onCancel: () => toast("PayPal window closed. Nothing was authorized."),
      onError: (err) => toast(`PayPal error: ${err && err.message ? err.message : err}`, true),
    }).render("#paypal-buttons");
  } catch (e) {
    paypalRenderedFor = null;
    box.innerHTML = `<p class="muted">${esc(e.message)}</p>`;
  }
}

/* ---------------------------------------------------------------- render */
function setJob(job) {
  JOB = job;
  store("voxproof_job", job ? job.id : null);
  renderAll();
}

function renderAll() {
  renderRail();
  renderUpload();
  renderRequest();
  renderContract();
  renderPay();
  renderRun();
  renderReview();
  renderReceipt();
  renderActiveCard();
  if (JOB && JOB.narration && JOB.narration !== lastNarration) {
    lastNarration = JOB.narration;
    speak(JOB.narration);
  }
}

function renderRail() {
  const steps = ["upload", "contract", "agreed", "authorized", "verified", "settled"];
  const r = rank();
  const last = JOB && JOB.attempts.length ? JOB.attempts[JOB.attempts.length - 1].report : null;
  const status = {
    upload: r >= 1 ? "done" : "",
    contract: r >= 2 ? "done" : "",
    agreed: r >= 3 ? "done" : "",
    authorized: r >= 4 ? "done" : "",
    verified: last ? (last.passed ? "done" : "failed") : "",
    settled: JOB && JOB.state === "CAPTURED" ? "done" : (JOB && ["VOIDED", "EXPIRED"].includes(JOB.state) ? "failed" : ""),
  };
  const current = steps.find((s) => !status[s]);
  document.querySelectorAll("#states li").forEach((li) => {
    const s = li.dataset.step;
    li.className = status[s] || (s === current ? "current" : "");
  });
  const ev = $("#events");
  if (!JOB) { ev.innerHTML = '<li class="muted">Nothing yet.</li>'; return; }
  ev.innerHTML = JOB.events.slice().reverse().map((e) =>
    `<li><time>${esc(e.at.slice(11, 19))} · ${esc(e.state)}</time>${esc(e.message)}</li>`).join("");
}

function tableHtml(headers, rows, cellClass) {
  const head = `<tr><th>#</th>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>`;
  const body = rows.map((row, i) => `<tr><td class="rownum">${i + 1}</td>${row.map((v, c) => {
    const extra = cellClass ? cellClass(i + 1, headers[c]) : { cls: "", title: "" };
    return `<td class="${extra.cls}" title="${esc(extra.title)}">${esc(v)}</td>`;
  }).join("")}</tr>`).join("");
  return `<table>${head}${body}</table>`;
}

function renderUpload() {
  const out = $("#upload-result");
  if (!JOB) { out.innerHTML = ""; inputGridKey = null; return; }
  if (inputGridKey === JOB.id) return;
  inputGridKey = JOB.id;
  const p = JOB.input_preview;
  out.innerHTML = `
    <div class="filemeta"><strong>${esc(JOB.input_filename)}</strong> · ${JOB.row_count} rows · ${p.headers.length} columns
      <span class="hash">sha256 ${esc(short(JOB.input_sha256))}</span></div>
    <div class="headers">${p.headers.map((h) => `<code>${esc(h)}</code>`).join("")}</div>
    <p class="muted small">First ${p.rows.length} rows, exactly as uploaded:</p>
    <div id="input-grid" class="grid-box small"></div>`;
  renderInputGrid(p);
}

function renderRequest() {
  $("#card-request").hidden = !JOB;
  if (!JOB) return;
  const locked = rank() >= 4;
  $("#draft").disabled = locked;
  $("#mic-request").disabled = locked;
  $("#request-text").disabled = locked;
  $("#draft").textContent = JOB.contract ? "Redraft the contract" : "Draft the contract";
}

function originHtml(c) {
  if (c.origin === "customer") return `<span class="origin">You said “${esc(c.from_request)}”</span>`;
  if (c.origin === "suggested") return '<span class="origin">Suggested by VoxProof</span>';
  return '<span class="origin">Always on</span>';
}

function renderContract() {
  const card = $("#card-contract");
  card.hidden = !(JOB && JOB.contract);
  if (card.hidden) return;
  const k = JOB.contract;
  $("#contract-hash").textContent = `sha256 ${short(JOB.contract_sha256)}`;
  const label = (c) => CONFIG_LABEL(c);
  const customer = k.checks.filter((c) => c.origin === "customer");
  const suggested = k.checks.filter((c) => c.origin === "suggested");
  const baseline = k.checks.filter((c) => c.origin === "baseline");
  const sev = (c) => `<span class="tag ${CHECK_META[c.type].severity}">${CHECK_META[c.type].severity}</span>`;

  const saidHtml = customer.length
    ? customer.map((c) => `<div class="said"><div class="quote">“${esc(c.from_request)}”</div><div class="arrow">→</div><div class="rule">${esc(label(c))}</div></div>`).join("")
    : '<p class="muted">You didn\'t name specific rules, so VoxProof suggested the protections below.</p>';

  const how = { copy: "copy exactly", parse_price: "read price → 0.00", parse_integer: "read whole number" };
  const mapRows = k.mappings.map((m) => `<tr><td><code>${esc(m.target)}</code></td>
      <td>${m.source ? `<code>${esc(m.source)}</code>` : '<span class="muted">(none, stays blank)</span>'}</td>
      <td>${esc(how[m.transform])}</td>
      <td>${m.default !== null && m.default !== undefined ? `<code>${esc(m.default)}</code>` : '<span class="muted">never filled in</span>'}</td></tr>`).join("");

  const canAgree = JOB.state === "CONTRACT_PROPOSED";
  $("#contract-body").innerHTML = `
    <p class="summary">${esc(k.summary)}</p>
    <h3 class="sub">What you said → what the code will check</h3>
    ${saidHtml}
    ${suggested.length ? `<h3 class="sub">VoxProof also protects you</h3><ul class="checklist">${suggested.map((c) => `<li>${sev(c)}<span>${esc(label(c))}</span></li>`).join("")}</ul>` : ""}
    <details><summary>${baseline.length} always-on checks</summary><ul class="checklist">${baseline.map((c) => `<li>${sev(c)}<span>${esc(label(c))}</span></li>`).join("")}</ul></details>
    <h3 class="sub">Column mapping</h3>
    <div class="table-wrap"><table><tr><th>Store column</th><th>From your file</th><th>How</th><th>If blank</th></tr>${mapRows}</table></div>
    ${k.assumptions.length ? `<h3 class="sub">Assumptions</h3><ul class="assumptions">${k.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
    <div class="contract-foot">
      <div><div class="muted small">Price (set by VoxProof, not the AI)</div><div class="price">${esc(money(k.price))}</div></div>
      <div class="muted small">Drafted by ${esc(k.drafted_by)}<br>Blocking checks must all pass before you can pay.</div>
      <span class="spacer"></span>
      ${canAgree ? '<button class="primary" data-action="agree">Agree to this contract</button>' : '<span class="badge pass">AGREED</span>'}
    </div>`;
}

function renderPay() {
  const card = $("#card-pay");
  card.hidden = rank() < 3;
  if (card.hidden) return;
  const price = money(JOB.contract.price);
  $("#pay-lead").innerHTML = `<strong>${esc(price)}</strong> goes on hold with PayPal. It is <strong>not charged</strong> unless every required check passes <em>and</em> you tap Accept. Otherwise the hold is voided.`;
  const needsAuth = JOB.state === "AGREED";
  const mock = CONFIG.paypal_mode === "mock";
  $("#paypal-buttons").hidden = !needsAuth || mock;
  $("#mock-pay").hidden = !needsAuth || !mock;
  if (needsAuth && !mock) renderPayPalButtons();
  const p = JOB.paypal || {};
  $("#pay-status").innerHTML = p.authorization_id ? `
    <dl class="kv">
      <dt>Order</dt><dd>${esc(p.order_id)}</dd>
      <dt>Authorization</dt><dd>${esc(p.authorization_id)}</dd>
      <dt>Status</dt><dd>${esc(p.auth_status)}</dd>
      <dt>Hold expires</dt><dd>${esc(p.expiration_time || "")}</dd>
      <dt>Bound to contract</dt><dd>custom_id = ${esc(short(JOB.contract_sha256))}</dd>
    </dl>` : "";
}

function renderRun() {
  const card = $("#card-run");
  card.hidden = rank() < 4;
  if (card.hidden) return;
  const canRun = JOB.state === "AUTHORIZED" || (JOB.state === "VERIFIED_FAIL" && JOB.attempts_left > 0);
  const btn = $("#run");
  if (!btn.querySelector(".spinner")) {
    btn.disabled = !canRun;
    btn.textContent = JOB.attempts.length ? `Retry with verifier feedback (${JOB.attempts_left} left)` : "Run the job";
  }
  $("#simulate-fault").disabled = !canRun || JOB.attempts.length > 0;
  if (JOB.attempts.length > 0) $("#simulate-fault").checked = false;
  $("#attempts").innerHTML = JOB.attempts.slice().reverse().map((a) => `
    <div class="attempt">
      <header><strong>Attempt ${a.n}</strong>
        <span class="muted small">planned by ${esc(a.plan.planned_by)}${a.simulated_fault ? " · simulated faulty worker" : ""}</span>
        <span class="badge ${a.report.passed ? "pass" : "fail"}">${a.report.passed ? "PASSED" : "FAILED"} ${a.report.blocking_passed}/${a.report.blocking_total}</span></header>
      <div class="ops">${a.plan.operations.map((o) => `<span class="op ${o.injected_fault ? "fault" : ""}">${esc(o.op)}(${esc(o.source || o.value)} → ${esc(o.target)})</span>`).join("")}</div>
      ${a.plan.notes ? `<p class="muted small">${esc(a.plan.notes)}</p>` : ""}
    </div>`).join("");
}

function renderReview() {
  const card = $("#card-review");
  card.hidden = !(JOB && JOB.attempts.length);
  if (card.hidden) return;
  const a = JOB.attempts[JOB.attempts.length - 1];
  const r = a.report;
  if (a.n !== lastAttemptShown) {
    lastAttemptShown = a.n;
    $("#answer").innerHTML = "";
    $("#ask-text").value = "";
  }
  const warn = r.warning_count ? ` · ${r.attention_rows.length} rows need your attention` : "";
  $("#verdict").innerHTML = `<div class="verdict ${r.passed ? "pass" : "fail"}">
      <div class="big">${r.passed ? "Verified" : "Not verified"}</div>
      <div>${r.blocking_passed} of ${r.blocking_total} required checks passed${esc(warn)}<br>
      <span class="muted small">Attempt ${a.n} · ${esc(r.verifier)} · output sha256 ${esc(short(r.output_sha256))}</span></div></div>`;

  $("#checks").innerHTML = r.checks.map((c) => {
    const icon = c.passed ? '<span class="icon pass">✓</span>' : (c.severity === "blocking" ? '<span class="icon fail">✕</span>' : '<span class="icon warn">!</span>');
    const rows = c.failures.map((f) => `<tr><td>${f.row ? `row ${f.row}` : ""}</td><td><code>${esc(f.column || "")}</code></td><td><code>${esc(f.value)}</code></td><td>${esc(f.reason)}</td></tr>`).join("");
    const more = c.failure_count > c.failures.length ? `<p class="muted small">…and ${c.failure_count - c.failures.length} more</p>` : "";
    return `<details class="check" ${!c.passed && c.severity === "blocking" ? "open" : ""}>
      <summary>${icon}<span class="label">${esc(c.label)}<br>${originHtml(c)}</span><span class="tag ${c.severity}">${c.severity}</span>
      <span class="count">${c.passed ? "ok" : c.failure_count}</span></summary>
      ${c.failures.length ? `<div class="failures"><table>${rows}</table>${more}</div>` : ""}</details>`;
  }).join("");

  renderResultGrid(a);

  const actions = $("#review-actions");
  if (JOB.state === "VERIFIED_PASS") {
    actions.innerHTML = `<button class="danger" data-action="reject">Reject &amp; void the hold</button>
      <button class="accept" data-action="accept">Accept &amp; pay ${esc(money(JOB.contract.price))}</button>`;
  } else if (JOB.state === "VERIFIED_FAIL") {
    actions.innerHTML = `<span class="muted small">Payment is blocked until every required check passes.</span>
      <button class="danger" data-action="reject">Reject &amp; void the hold</button>
      <button class="accept" disabled title="Blocked: checks failed">Accept &amp; pay</button>`;
  } else {
    actions.innerHTML = "";
  }
}

function renderReceipt() {
  const card = $("#card-receipt");
  card.hidden = !(JOB && TERMINAL.includes(JOB.state));
  if (card.hidden) return;
  const p = JOB.paypal || {};
  const rc = JOB.receipt;
  const ev = JOB.events[JOB.events.length - 1];
  let html;
  if (JOB.state === "CAPTURED") {
    html = `<div class="stamp paid">PAID</div>
      <p class="lead">${esc(money(JOB.contract.price))} captured after the code verified the work and you accepted it.</p>
      <dl class="kv">
        <dt>PayPal capture</dt><dd>${esc(p.capture_id)} (${esc(p.capture_status)})</dd>
        <dt>Authorization</dt><dd>${esc(p.authorization_id)}</dd>
        <dt>Order</dt><dd>${esc(p.order_id)}</dd>
        <dt>Contract sha256</dt><dd>${esc(rc.contract_sha256)}</dd>
        <dt>Input sha256</dt><dd>${esc(rc.input_sha256)}</dd>
        <dt>Output sha256</dt><dd>${esc(rc.output_sha256)}</dd>
        <dt>Re-verified at</dt><dd>${esc(rc.verified_at)}</dd>
      </dl>
      <div class="actions">
        <a class="link" href="/api/jobs/${JOB.id}/evidence.json">Download evidence (JSON)</a>
        <button class="secondary" data-action="new">Start a new job</button>
        <a href="/api/jobs/${JOB.id}/output.csv"><button class="accept">Download store_import.csv</button></a>
      </div>`;
  } else {
    html = `<div class="stamp void">${JOB.state === "EXPIRED" ? "EXPIRED" : "VOIDED"}</div>
      <p class="lead">You were not charged. ${esc(ev ? ev.message : "")}</p>
      <dl class="kv"><dt>Order</dt><dd>${esc(p.order_id || "")}</dd><dt>Authorization</dt><dd>${esc(p.authorization_id || "")} (${esc(p.auth_status || "")})</dd></dl>
      <div class="actions">
        <a class="link" href="/api/jobs/${JOB.id}/evidence.json">Download evidence (JSON)</a>
        <button class="secondary" data-action="new">Start a new job</button>
      </div>`;
  }
  $("#receipt-body").innerHTML = html;
}

function renderActiveCard() {
  const map = { UPLOADED: "card-request", CONTRACT_PROPOSED: "card-contract", AGREED: "card-pay", AUTHORIZED: "card-run",
    VERIFIED_FAIL: "card-review", VERIFIED_PASS: "card-review", CAPTURED: "card-receipt", VOIDED: "card-receipt", EXPIRED: "card-receipt" };
  const id = JOB ? map[JOB.state] : "card-upload";
  document.querySelectorAll(".card").forEach((c) => c.classList.toggle("active", c.id === id));
  if (id !== lastActiveCard) {
    lastActiveCard = id;
    const el = document.getElementById(id);
    if (el && JOB) setTimeout(() => el.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  }
}

/* ------------------------------------------------------- AG Grid views */
let inputGridKey = null;
let inputGridApi = null;
let resultGridKey = null;
let resultGridApi = null;
let resultRows = [];
let gridFilter = "all";

const hasAgGrid = () => typeof window.agGrid !== "undefined" && typeof window.agGrid.createGrid === "function";

function gridTheme() {
  try {
    return window.agGrid.themeQuartz.withParams({
      accentColor: "#6d5efc", backgroundColor: "#ffffff", foregroundColor: "#0f172a",
      headerBackgroundColor: "#f8f9fd", borderColor: "#e6e8f1", fontFamily: "inherit",
      fontSize: 13, headerFontWeight: 600, wrapperBorderRadius: 12, spacing: 7,
    });
  } catch (_) { return undefined; }
}

function makeGrid(el, options) {
  const theme = gridTheme();
  if (theme) options.theme = theme;
  return window.agGrid.createGrid(el, options);
}

function gridFallback(el, html, why) {
  el.classList.add("fallback");
  el.innerHTML = `<div class="table-wrap">${html}</div>`;
  if (why) console.warn("AG Grid unavailable, using a plain table:", why);
}

function renderInputGrid(p) {
  const el = $("#input-grid");
  if (inputGridApi) { try { inputGridApi.destroy(); } catch (_) { /* already gone */ } inputGridApi = null; }
  if (!hasAgGrid()) { gridFallback(el, tableHtml(p.headers, p.rows), "script not loaded"); return; }
  try {
    inputGridApi = makeGrid(el, {
      columnDefs: [{ headerName: "#", field: "_row", width: 64, pinned: "left", sort: "asc", filter: false },
        ...p.headers.map((h, j) => ({ headerName: h, field: `c${j}`, minWidth: 110, flex: 1 }))],
      rowData: p.rows.map((r, i) => Object.assign({ _row: i + 1 }, ...r.map((v, j) => ({ [`c${j}`]: v })))),
      defaultColDef: { sortable: true, resizable: true, filter: true },
    });
  } catch (e) { gridFallback(el, tableHtml(p.headers, p.rows), e); }
}

const STATUS_LABEL = { failed: "Failed check", attention: "Needs you", changed: "Converted", ok: "Unchanged" };

function buildResultRows(pv) {
  return pv.rows.map((r, i) => {
    const n = i + 1;
    const d = { _row: n, _changed: 0, _bad: 0, _warn: 0 };
    pv.headers.forEach((c, j) => {
      const key = `${n}:${c}`;
      const ch = pv.changed[key];
      const fl = pv.flagged[key];
      d[`v${j}`] = r[j];
      d[`b${j}`] = ch ? ch.before : r[j];
      if (ch) d._changed += 1;
      if (fl && fl.severity === "blocking") d._bad += 1;
      else if (fl) d._warn += 1;
    });
    d._status = d._bad ? "failed" : d._warn ? "attention" : d._changed ? "changed" : "ok";
    return d;
  });
}

function rowPasses(d) {
  if (gridFilter === "failed") return d._bad > 0;
  if (gridFilter === "attention") return d._warn > 0;
  if (gridFilter === "changed") return d._changed > 0;
  return true;
}

function updateFilterCounts() {
  $("#n-all").textContent = resultRows.length;
  $("#n-failed").textContent = resultRows.filter((d) => d._bad).length;
  $("#n-attention").textContent = resultRows.filter((d) => d._warn).length;
  $("#n-changed").textContent = resultRows.filter((d) => d._changed).length;
  document.querySelectorAll("#grid-filters button").forEach((b) => b.classList.toggle("on", b.dataset.filter === gridFilter));
}

function legacyResultTable(pv) {
  return tableHtml(pv.headers, pv.rows, (row, col) => {
    const key = `${row}:${col}`;
    const flag = pv.flagged[key];
    const ch = pv.changed[key];
    let cls = "";
    let title = "";
    if (ch) { cls = "changed"; title = `was: "${ch.before}" (${ch.note})`; }
    if (flag) { cls = flag.severity === "blocking" ? "bad" : "warn"; title = flag.reason + (ch ? ` | was: "${ch.before}"` : ""); }
    return { cls, title };
  });
}

function renderResultGrid(attempt) {
  const pv = JOB.preview;
  if (!pv) return;
  const key = `${JOB.id}:${attempt.n}`;
  if (resultGridKey === key) return;
  resultGridKey = key;
  resultRows = buildResultRows(pv);
  gridFilter = "all";
  $("#grid-search").value = "";
  $("#grid-compare").checked = false;
  updateFilterCounts();
  $("#grid-note").textContent = pv.total_rows > pv.rows.length ? `Showing the first ${pv.rows.length} of ${pv.total_rows} rows.` : "";

  const el = $("#result-grid");
  el.classList.remove("fallback");
  el.innerHTML = "";
  if (resultGridApi) { try { resultGridApi.destroy(); } catch (_) { /* already gone */ } resultGridApi = null; }
  if (!hasAgGrid()) {
    $("#grid-toolbar").hidden = true;
    gridFallback(el, legacyResultTable(pv), "script not loaded");
    return;
  }
  $("#grid-toolbar").hidden = false;

  const cellKey = (p, c) => `${p.data._row}:${c}`;
  const columnDefs = [
    { headerName: "#", field: "_row", width: 64, pinned: "left", sort: "asc", filter: false },
    { headerName: "Status", field: "_status", width: 132, pinned: "left", filter: false,
      cellRenderer: (p) => `<span class="st st-${p.value}">${STATUS_LABEL[p.value]}</span>`,
      tooltipValueGetter: (p) => `${p.data._bad} failed · ${p.data._warn} need attention · ${p.data._changed} converted` },
  ];
  pv.headers.forEach((c, j) => {
    columnDefs.push({
      colId: `b${j}`, field: `b${j}`, headerName: `${c} · source`, hide: true, minWidth: 110, flex: 1,
      cellClass: "vp-before", headerClass: "vp-before-h", headerTooltip: "Value in your uploaded file",
    });
    columnDefs.push({
      colId: `v${j}`, field: `v${j}`, headerName: c, minWidth: 110, flex: 1,
      cellClassRules: {
        "vp-bad": (p) => (pv.flagged[cellKey(p, c)] || {}).severity === "blocking",
        "vp-warn": (p) => (pv.flagged[cellKey(p, c)] || {}).severity === "warning",
        "vp-changed": (p) => !!pv.changed[cellKey(p, c)] && !pv.flagged[cellKey(p, c)],
      },
      tooltipValueGetter: (p) => {
        const fl = pv.flagged[cellKey(p, c)];
        const ch = pv.changed[cellKey(p, c)];
        const parts = [];
        if (fl) parts.push(fl.reason);
        if (ch) parts.push(`Your file: "${ch.before}" (${ch.note || "copied"})`);
        return parts.length ? parts.join("  ·  ") : undefined;
      },
    });
  });

  try {
    resultGridApi = makeGrid(el, {
      columnDefs,
      rowData: resultRows,
      defaultColDef: { sortable: true, resizable: true, filter: true },
      getRowId: (p) => String(p.data._row),
      tooltipShowDelay: 150,
      animateRows: true,
      isExternalFilterPresent: () => gridFilter !== "all",
      doesExternalFilterPass: (node) => rowPasses(node.data),
    });
  } catch (e) {
    $("#grid-toolbar").hidden = true;
    gridFallback(el, legacyResultTable(pv), e);
  }
}

function bindGridControls() {
  $("#grid-filters").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-filter]");
    if (!b) return;
    gridFilter = b.dataset.filter;
    updateFilterCounts();
    if (resultGridApi) resultGridApi.onFilterChanged();
  });
  $("#grid-search").addEventListener("input", (e) => {
    if (resultGridApi) resultGridApi.setGridOption("quickFilterText", e.target.value);
  });
  $("#grid-compare").addEventListener("change", (e) => {
    if (!resultGridApi || !JOB || !JOB.preview) return;
    resultGridApi.setColumnsVisible(JOB.preview.headers.map((_, j) => `b${j}`), e.target.checked);
  });
}

/* ------------------------------------------------------------- labels */
let CHECK_META = {};
function CONFIG_LABEL(c) {
  const t = (c.targets || []).join(", ") || "all columns";
  return (CHECK_META[c.type] ? CHECK_META[c.type].label : c.type).replace("{targets}", t);
}

/* ------------------------------------------------------------- actions */
async function upload(form) {
  const r = await api("/api/jobs", { form });
  paypalRenderedFor = null;
  lastActiveCard = null;
  inputGridKey = null;
  resultGridKey = null;
  $("#request-text").value = "";
  $("#answer").innerHTML = "";
  setJob(r.job);
}

function bind() {
  $("#file").addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    upload(form).catch((err) => toast(err.message, true));
    e.target.value = "";
  });
  const drop = $("#drop");
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    upload(form).catch((err) => toast(err.message, true));
  });
  $("#use-sample").addEventListener("click", (e) => withBusy(e.currentTarget, "Loading…", () => {
    const form = new FormData();
    form.append("sample", "1");
    return upload(form);
  }));

  $("#example-request").addEventListener("click", () => {
    $("#request-text").value = "Convert this into my store's import format. Preserve all product IDs. Never invent missing prices.";
  });
  $("#mic-request").addEventListener("click", (e) => {
    const base = $("#request-text").value.trim();
    $("#mic-status").textContent = activeRec ? "" : "Listening… tap the mic again to stop.";
    listen(e.currentTarget, (text) => { $("#request-text").value = [base, text].filter(Boolean).join(" "); });
  });
  $("#draft").addEventListener("click", (e) => withBusy(e.currentTarget, "Drafting with AI…", async () => {
    const r = await api(`/api/jobs/${JOB.id}/contract`, { body: { request_text: $("#request-text").value } });
    paypalRenderedFor = null;
    setJob(r.job);
  }));

  $("#mock-approve").addEventListener("click", (e) => withBusy(e.currentTarget, "Authorizing…", async () => {
    const order = await api(`/api/jobs/${JOB.id}/paypal/order`, { method: "POST" });
    const r = await api(`/api/jobs/${JOB.id}/paypal/authorize`, { body: { order_id: order.id } });
    setJob(r.job);
  }));

  $("#run").addEventListener("click", (e) => withBusy(e.currentTarget, "AI planning, code verifying…", async () => {
    const r = await api(`/api/jobs/${JOB.id}/process`, { body: { simulate_fault: $("#simulate-fault").checked } });
    $("#simulate-fault").checked = false;
    setJob(r.job);
  }));

  const ask = async () => {
    const text = $("#ask-text").value.trim();
    if (!text || !JOB) return;
    const r = await api(`/api/jobs/${JOB.id}/ask`, { body: { text } });
    $("#answer").innerHTML = `<div class="answer ${r.refused ? "refused" : ""}">${esc(r.answer)}</div>`;
    speak(r.answer);
    const fresh = await api(`/api/jobs/${JOB.id}`);
    JOB = fresh.job;
    renderRail();
  };
  $("#ask").addEventListener("click", (e) => withBusy(e.currentTarget, "…", ask));
  $("#ask-text").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); ask().catch((err) => toast(err.message, true)); } });
  $("#mic-ask").addEventListener("click", (e) => listen(e.currentTarget, (text, final) => {
    $("#ask-text").value = text;
    if (final && text) ask().catch((err) => toast(err.message, true));
  }));

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn || !JOB) return;
    const action = btn.dataset.action;
    if (action === "agree") {
      withBusy(btn, "Locking…", async () => setJob((await api(`/api/jobs/${JOB.id}/agree`, { body: { contract_sha256: JOB.contract_sha256 } })).job));
    } else if (action === "accept") {
      withBusy(btn, "Re-verifying & capturing…", async () => setJob((await api(`/api/jobs/${JOB.id}/accept`, { body: { accept_nonce: JOB.accept_nonce } })).job));
    } else if (action === "reject") {
      withBusy(btn, "Voiding…", async () => setJob((await api(`/api/jobs/${JOB.id}/reject`, { body: { reason: "customer rejected the work" } })).job));
    } else if (action === "new") {
      store("voxproof_job", null);
      window.location.reload();
    }
  });

  $("#voice-toggle").addEventListener("click", (e) => {
    voiceOn = !voiceOn;
    e.currentTarget.textContent = voiceOn ? "Voice on" : "Voice off";
    e.currentTarget.setAttribute("aria-pressed", String(voiceOn));
    if (!voiceOn && "speechSynthesis" in window) speechSynthesis.cancel();
  });
  $("#replay").addEventListener("click", () => speak($("#narration").textContent));
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  bind();
  bindGridControls();
  CONFIG = await api("/api/config");
  CHECK_META = CONFIG.check_library || {};
  const pp = $("#mode-paypal");
  pp.textContent = CONFIG.paypal_mode === "mock" ? "PayPal: MOCK (offline)" : "PayPal: Sandbox";
  pp.className = "pill " + (CONFIG.paypal_mode === "mock" ? "mock" : "live");
  const ai = $("#mode-ai");
  ai.textContent = `AI: ${CONFIG.ai}`;
  ai.className = "pill " + (CONFIG.ai_is_mock ? "mock" : "live");
  if (CONFIG.warnings.length) {
    const w = $("#warnings");
    w.hidden = false;
    w.innerHTML = CONFIG.warnings.map(esc).join("<br>");
  }
  if (!SR) $("#mic-status").textContent = "Voice input needs Chrome or Edge. Typing works everywhere.";
  if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => {};
  const saved = recall("voxproof_job");
  if (saved) {
    try {
      const r = await api(`/api/jobs/${saved}`);
      lastNarration = r.job.narration;
      $("#narration").textContent = r.job.narration;
      setJob(r.job);
    }
    catch (_) { store("voxproof_job", null); renderAll(); }
  } else {
    renderAll();
  }
}

boot().catch((e) => toast(e.message, true));
