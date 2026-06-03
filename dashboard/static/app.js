const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let refreshMs = 15000;
let timer = null;

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function scoreClass(score) {
  if (score >= 80) return "score-good";
  if (score >= 40) return "score-warn";
  return "score-bad";
}

function fmtUsd(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n) {
  if (n == null) return "—";
  const v = Number(n);
  if (v <= 1 && v >= -1) return (v * 100).toFixed(2) + "%";
  return v.toFixed(2) + "%";
}

function renderCards(cards) {
  return `<div class="cards">${cards.map((c) => `
    <div class="card">
      <div class="label">${esc(c.label)}</div>
      <div class="value ${c.cls || ""}">${esc(c.value)}</div>
      ${c.sub ? `<div class="sub">${esc(c.sub)}</div>` : ""}
    </div>`).join("")}</div>`;
}

function renderTable(headers, rows) {
  if (!rows.length) return `<p class="empty">No data</p>`;
  return `<table><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderTradebot(tb) {
  const p = tb.portfolio || {};
  const tick = tb.latest_tick || {};
  const cards = [
    { label: "Portfolio", value: fmtUsd(p.portfolio_usd), sub: p.updated_at || "" },
    { label: "PnL", value: (p.baseline_pnl != null ? (p.baseline_pnl >= 0 ? "+" : "") + p.baseline_pnl : "—"), cls: p.baseline_pnl < 0 ? "score-bad" : "score-good" },
    { label: "Drawdown", value: fmtPct(p.drawdown_pct), sub: tick.decision ? "Last: " + tick.decision : "" },
    { label: "Strategy focus", value: (tb.strategy_focus || "—").slice(0, 80), sub: tick.time || "" },
  ];

  const holdings = (p.holdings || []).map((h) => [
    esc(h.asset),
    esc(h.qty),
    esc(fmtUsd(h.usd_value)),
  ]);

  const trades = (tb.recent_trades || []).map((t) => [
    esc(t.time),
    esc(t.summary),
    esc(t.gain_loss),
  ]);

  const blocked = (tb.blocked_opportunities || []).map((b) => `<li>${esc(b)}</li>`).join("") || "<li class='empty'>None in latest tick</li>";

  const trend = (tb.pnl_trend || []).slice(-12).map((t) => `${t.time}: ${fmtUsd(t.portfolio_usd)} (PnL ${t.baseline_pnl})`).join("\n");

  return `
    ${renderCards(cards)}
    <h2 class="section-title">Holdings</h2>
    ${renderTable(["Asset", "Qty", "USD"], holdings)}
    <h2 class="section-title">Recent trades (receipts)</h2>
    ${renderTable(["Time", "Trade", "Gain/Loss"], trades)}
    <h2 class="section-title">Blocked / below hurdle</h2>
    <ul>${blocked}</ul>
    <h2 class="section-title">PnL trend (recent ticks)</h2>
    <pre class="log-block">${esc(trend || "No tick data in window logs")}</pre>
    <h2 class="section-title">Runtime log (tail)</h2>
    <pre class="log-block">${esc((tb.runtime_log_tail || []).join("\n"))}</pre>
  `;
}

function renderWatchdog(wd) {
  const h = wd.health || {};
  const s = wd.session || {};
  const cards = [
    { label: "Health score", value: `${h.score}/100`, cls: scoreClass(h.score), sub: h.label },
    { label: "Session trades", value: String(s.trades_session ?? 0), sub: s.session_started_at || "" },
    { label: "Pauses", value: String(s.watchdog_pause_count ?? 0), sub: s.last_watchdog_pause_at || "—" },
    { label: "Errors (1h)", value: String(h.errors_last_hour ?? 0), sub: `burst ${h.errors_last_window ?? 0}` },
  ];

  const factors = (h.factors || []).map((f) => `<li>${esc(f)}</li>`).join("");
  const errors = (wd.recent_errors || []).map((e) => [
    esc(e.timestamp || e.time || ""),
    esc(e.message || e.summary || JSON.stringify(e).slice(0, 120)),
  ]);

  return `
    ${renderCards(cards)}
    <h2 class="section-title">Health factors</h2>
    <ul>${factors || "<li class='empty'>—</li>"}</ul>
    <h2 class="section-title">Recent errors (state)</h2>
    ${renderTable(["Time", "Message"], errors)}
    <h2 class="section-title">Watchdog-related log lines</h2>
    <pre class="log-block">${esc((wd.alert_lines || []).join("\n"))}</pre>
  `;
}

function renderAuditor(au) {
  const oh = au.override_history || {};
  const cards = [
    { label: "Pending proposals", value: String((au.pending_proposals || []).length), sub: au.run_markers?.last_scheduled_run_at || "" },
    { label: "Last event run", value: au.run_markers?.last_event_run_at || "—", sub: `trades @ event: ${au.run_markers?.last_trade_count_at_event ?? "—"}` },
    { label: "Active overrides", value: String(Object.keys(oh.active || {}).length), sub: oh.last_auto_apply_at || "no auto-apply" },
    { label: "Reports indexed", value: String((au.recent_reports || []).length), sub: "" },
  ];

  const proposals = (au.pending_proposals || []).map((p) => [
    esc(p.id),
    esc(p.knob),
    esc(`${p.current_value} → ${p.proposed_value}`),
    esc(p.severity),
    esc(p.expires_at),
  ]);

  const reports = (au.recent_reports || []).map((r) => [
    esc(r.title),
    esc(r.trigger),
    esc(r.net_pnl),
    esc(String(r.proposal_count)),
  ]);

  const overrides = Object.entries(oh.active || {}).map(([k, v]) => `<li><code>${esc(k)}</code> = ${esc(v)}</li>`).join("") || "<li class='empty'>None</li>";

  const news = (au.news_headlines || []).map((n) => `<li>${esc(n)}</li>`).join("") || "<li class='empty'>—</li>";

  return `
    ${renderCards(cards)}
    <h2 class="section-title">Pending proposals</h2>
    ${renderTable(["ID", "Knob", "Change", "Severity", "Expires"], proposals)}
    <h2 class="section-title">Runtime overrides</h2>
    <ul>${overrides}</ul>
    <h2 class="section-title">Recent audit reports</h2>
    ${renderTable(["When", "Trigger", "Net PnL", "Proposals"], reports)}
    <h2 class="section-title">News (latest report)</h2>
    <ul>${news}</ul>
    <h2 class="section-title">Auditor chat activity</h2>
    <pre class="log-block">${esc((au.chat_activity || []).join("\n"))}</pre>
  `;
}

async function refresh() {
  try {
    const res = await fetch("/api/overview");
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    refreshMs = (data.refresh_seconds || 15) * 1000;
    $("#meta-line").textContent = `Root: ${data.root} · auto-refresh ${data.refresh_seconds}s · ${new Date().toLocaleTimeString()}`;
    $("#panel-tradebot").innerHTML = renderTradebot(data.tradebot || {});
    $("#panel-watchdog").innerHTML = renderWatchdog(data.watchdog || {});
    $("#panel-auditor").innerHTML = renderAuditor(data.auditor || {});
    const bl = data.backlog || [];
    $("#backlog-list").innerHTML = bl.map((l) => `<li>${esc(l)}</li>`).join("") || "<li class='empty'>—</li>";
  } catch (err) {
    $("#meta-line").textContent = "Failed to load: " + err.message;
  }
}

function setupTabs() {
  $$(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const id = btn.dataset.tab;
      $$(".panel").forEach((p) => {
        const on = p.id === `panel-${id}`;
        p.classList.toggle("active", on);
        p.hidden = !on;
      });
    });
  });
}

function startPolling() {
  refresh();
  if (timer) clearInterval(timer);
  timer = setInterval(refresh, refreshMs);
}

setupTabs();
startPolling();
