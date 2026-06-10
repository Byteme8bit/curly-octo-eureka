const $ = (sel) => document.querySelector(sel);

let refreshMs = 15000;
let timer = null;
const charts = {};

const CHART_COLORS = {
  line: "#3d8bfd",
  lineFill: "rgba(61, 139, 253, 0.12)",
  good: "#3dd68c",
  bad: "#f56565",
  warn: "#f5a623",
  muted: "#5a6a85",
  palette: ["#3d8bfd", "#3dd68c", "#f5a623", "#a78bfa", "#f56565", "#38bdf8", "#fb7185"],
};

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

function pnlClass(n) {
  if (n == null || Number.isNaN(n)) return "";
  return n >= 0 ? "score-good" : "score-bad";
}

function fmtUsd(n) {
  if (n == null || Number.isNaN(n)) return "—";
  const v = Number(n);
  const sign = v >= 0 ? "" : "-";
  return sign + "$" + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n, asRatio) {
  if (n == null || Number.isNaN(n)) return "—";
  const v = Number(n);
  if (asRatio || (v <= 1 && v >= -1)) return (v * 100).toFixed(2) + "%";
  return v.toFixed(2) + "%";
}

function fmtPnl(n) {
  if (n == null || Number.isNaN(n)) return "—";
  const v = Number(n);
  return (v >= 0 ? "+" : "") + v.toFixed(2);
}

function shortTime(ts) {
  if (!ts) return "";
  const parts = ts.split(" ");
  if (parts.length >= 2) return parts[1].slice(0, 5);
  return ts.slice(0, 16);
}

function destroyChart(id) {
  if (charts[id]) {
    charts[id].destroy();
    delete charts[id];
  }
}

function defaultChartOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: {
        ticks: { color: "#8b9bb4", font: { family: "Consolas, monospace", size: 10 }, maxRotation: 45 },
        grid: { color: "rgba(45, 58, 79, 0.5)" },
      },
      y: {
        ticks: { color: "#8b9bb4", font: { family: "Consolas, monospace", size: 10 } },
        grid: { color: "rgba(45, 58, 79, 0.5)" },
      },
    },
    ...extra,
  };
}

function renderMetricStrip(summary) {
  const s = summary || {};
  const metrics = [
    { label: "Portfolio", value: fmtUsd(s.portfolio_usd), cls: "mono" },
    { label: "Session PnL", value: fmtPnl(s.baseline_pnl), cls: `mono ${pnlClass(s.baseline_pnl)}` },
    { label: "Drawdown", value: fmtPct(s.drawdown_pct, true), cls: `mono ${s.drawdown_pct > 0.05 ? "score-bad" : ""}` },
    { label: "Cash", value: fmtPct(s.cash_pct, true), cls: "mono" },
    { label: "Trades", value: String(s.trade_count ?? 0), cls: "mono" },
    { label: "Health", value: s.health_score != null ? `${s.health_score}/100` : "—", cls: `mono ${scoreClass(s.health_score || 0)}` },
  ];
  return metrics.map((m) => `
    <div class="metric">
      <span class="metric-label">${esc(m.label)}</span>
      <span class="metric-value ${m.cls || ""}">${esc(m.value)}</span>
    </div>`).join("");
}

function updatePortfolioChart(points) {
  const ctx = document.getElementById("chart-portfolio");
  if (!ctx) return;
  destroyChart("portfolio");
  const labels = (points || []).map((p) => shortTime(p.time));
  const data = (points || []).map((p) => p.portfolio_usd);
  charts.portfolio = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data,
        borderColor: CHART_COLORS.line,
        backgroundColor: CHART_COLORS.lineFill,
        fill: true,
        tension: 0.25,
        pointRadius: data.length > 40 ? 0 : 2,
        borderWidth: 2,
      }],
    },
    options: defaultChartOptions(),
  });
}

function updatePnlBarChart(deltas) {
  const ctx = document.getElementById("chart-pnl-bars");
  if (!ctx) return;
  destroyChart("pnlBars");
  const slice = (deltas || []).slice(-24);
  const labels = slice.map((d) => shortTime(d.time));
  const data = slice.map((d) => d.delta_pnl);
  charts.pnlBars = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: data.map((v) => (v >= 0 ? CHART_COLORS.good : CHART_COLORS.bad)),
        borderWidth: 0,
      }],
    },
    options: defaultChartOptions(),
  });
}

function updateAllocationChart(holdings) {
  const ctx = document.getElementById("chart-allocation");
  if (!ctx) return;
  destroyChart("allocation");
  const rows = (holdings || []).filter((h) => h.usd_value > 0);
  if (!rows.length) {
    charts.allocation = new Chart(ctx, {
      type: "doughnut",
      data: { labels: ["—"], datasets: [{ data: [1], backgroundColor: [CHART_COLORS.muted] }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "right", labels: { color: "#8b9bb4" } } } },
    });
    return;
  }
  charts.allocation = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: rows.map((h) => h.asset),
      datasets: [{
        data: rows.map((h) => h.usd_value),
        backgroundColor: rows.map((_, i) => CHART_COLORS.palette[i % CHART_COLORS.palette.length]),
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "right", labels: { color: "#8b9bb4", font: { size: 11 } } } },
    },
  });
}

function updateTradesChart(buckets) {
  const ctx = document.getElementById("chart-trades");
  if (!ctx) return;
  destroyChart("trades");
  const slice = (buckets || []).slice(-14);
  const labels = slice.map((b) => b.bucket.slice(5));
  charts.trades = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Net PnL",
          data: slice.map((b) => b.net_pnl),
          backgroundColor: slice.map((b) => (b.net_pnl >= 0 ? CHART_COLORS.good : CHART_COLORS.bad)),
          yAxisID: "y",
        },
        {
          label: "Trades",
          data: slice.map((b) => b.trade_count),
          type: "line",
          borderColor: CHART_COLORS.warn,
          backgroundColor: "transparent",
          yAxisID: "y1",
          tension: 0.3,
          pointRadius: 3,
        },
      ],
    },
    options: defaultChartOptions({
      plugins: { legend: { display: true, labels: { color: "#8b9bb4", boxWidth: 12 } } },
      scales: {
        x: { ticks: { color: "#8b9bb4", font: { size: 10 } }, grid: { color: "rgba(45, 58, 79, 0.5)" } },
        y: { position: "left", ticks: { color: "#8b9bb4" }, grid: { color: "rgba(45, 58, 79, 0.5)" } },
        y1: { position: "right", grid: { drawOnChartArea: false }, ticks: { color: CHART_COLORS.warn } },
      },
    }),
  });
}

function renderForecasts(fc) {
  const bands = fc?.bands || [];
  if (!bands.length) {
    return `<p class="empty">No forecast bands in latest audit report.${fc?.source ? ` <span class="muted">(${esc(fc.source)})</span>` : ""}</p>`;
  }
  const rows = bands.map((b) => `
    <tr>
      <td class="mono">${esc(b.horizon)}</td>
      <td><span class="badge badge-muted">${esc(b.method)}</span></td>
      <td class="mono ${pnlClass(b.expected_pnl)}">${esc(fmtUsd(b.expected_pnl))}</td>
      <td class="mono">${esc(fmtUsd(b.lower_band))}</td>
      <td class="mono">${esc(fmtUsd(b.upper_band))}</td>
      <td class="mono">${b.confidence != null ? (b.confidence * 100).toFixed(0) + "%" : "—"}</td>
    </tr>`).join("");
  return `
    <p class="forecast-source">From audit <strong>${esc(fc.report_title)}</strong></p>
    <table class="forecast-table">
      <thead><tr><th>Horizon</th><th>Method</th><th>Expected</th><th>10th</th><th>90th</th><th>Conf.</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="disclaimer">${esc(fc.disclaimer || "")}</p>`;
}

function renderWatchdog(wd) {
  const h = wd.health || {};
  const s = wd.session || {};
  const score = h.score ?? 0;
  const factorBars = (h.factors || []).map((f, i) => {
    const width = Math.max(15, 100 - i * 12);
    return `<div class="factor-row"><span class="factor-text">${esc(f)}</span><div class="mini-bar"><div class="mini-bar-fill ${scoreClass(score)}" style="width:${width}%"></div></div></div>`;
  }).join("") || `<p class="empty">No factor breakdown</p>`;

  return `
    <div class="health-gauge">
      <div class="gauge-label">Health ${esc(h.label || "")}</div>
      <div class="gauge-track"><div class="gauge-fill ${scoreClass(score)}" style="width:${Math.min(100, Math.max(0, score))}%"></div></div>
      <div class="gauge-score mono ${scoreClass(score)}">${score}/100</div>
    </div>
    <div class="mini-stats">
      <div><span class="muted">Session trades</span><span class="mono">${s.trades_session ?? 0}</span></div>
      <div><span class="muted">Pauses</span><span class="mono">${s.watchdog_pause_count ?? 0}</span></div>
      <div><span class="muted">Errors (1h)</span><span class="mono ${(h.errors_last_hour || 0) > 0 ? "score-bad" : ""}">${h.errors_last_hour ?? 0}</span></div>
      <div><span class="muted">Heartbeat</span><span class="mono">${s.heartbeat_age_sec != null ? s.heartbeat_age_sec + "s" : "—"}</span></div>
    </div>
    <h3 class="sub-heading">Score factors</h3>
    ${factorBars}
    <h3 class="sub-heading">Recent errors</h3>
    ${renderCompactTable(["Time", "Message"], (wd.recent_errors || []).slice(0, 6).map((e) => [
      esc(e.timestamp || e.time || ""),
      esc((e.message || e.summary || "").slice(0, 80)),
    ]))}`;
}

function severityBadge(sev) {
  const s = String(sev || "info").toLowerCase();
  const cls = s === "high" ? "badge-bad" : s === "medium" ? "badge-warn" : "badge-muted";
  return `<span class="badge ${cls}">${esc(sev)}</span>`;
}

function renderAuditor(au) {
  const pending = au.pending_proposals || [];
  const pipeline = `
    <div class="pipeline">
      <div class="pipe-step"><span class="pipe-num mono">${pending.length}</span><span>Pending</span></div>
      <div class="pipe-step"><span class="pipe-num mono">${Object.keys(au.override_history?.active || {}).length}</span><span>Active overrides</span></div>
      <div class="pipe-step"><span class="pipe-num mono">${(au.recent_reports || []).length}</span><span>Reports</span></div>
    </div>`;

  const proposals = pending.map((p) => `
    <div class="proposal-card">
      <div class="proposal-head"><code>${esc(p.knob)}</code> ${severityBadge(p.severity)}</div>
      <div class="mono">${esc(p.current_value)} → ${esc(p.proposed_value)}</div>
      <div class="muted small">${esc(p.expires_at || p.created_at || "")}</div>
    </div>`).join("") || `<p class="empty">No pending proposals</p>`;

  const timeline = (au.recent_reports || []).slice(0, 5).map((r) => `
    <div class="audit-timeline-item">
      <div class="timeline-dot"></div>
      <div>
        <div class="mono">${esc(r.title)}</div>
        <div class="muted small">${esc(r.trigger)} · ${esc(r.net_pnl)} · ${r.proposal_count} proposals</div>
      </div>
    </div>`).join("") || `<p class="empty">No audit reports</p>`;

  return `
    ${pipeline}
    <h3 class="sub-heading">Pending proposals</h3>
    <div class="proposal-list">${proposals}</div>
    <h3 class="sub-heading">Recent audits</h3>
    <div class="audit-timeline">${timeline}</div>`;
}

function renderTimeline(events) {
  if (!events?.length) return `<p class="empty">No recent events</p>`;
  return `<ul class="activity-feed">${events.map((e) => `
    <li class="feed-item feed-${esc(e.type)} sev-${esc(e.severity || "info")}">
      <span class="feed-time mono">${esc(e.time ? e.time.slice(0, 19) : "")}</span>
      <span class="feed-type badge badge-muted">${esc(e.type)}</span>
      <span class="feed-title">${esc(e.title)}</span>
      <span class="feed-detail muted">${esc(e.detail)}</span>
    </li>`).join("")}</ul>`;
}

function renderCompactTable(headers, rows) {
  if (!rows.length) return `<p class="empty">No data</p>`;
  return `<table class="compact"><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderWhales(wh) {
  if (!wh?.enabled && !wh?.recent_events?.length) {
    return `<p class="empty muted">${esc(wh?.config_hint || "Whale watch inactive — no state file yet.")}</p>`;
  }
  const stats = `
    <div class="mini-stats">
      <div><span class="muted">Last check</span><span class="mono">${esc(shortTime(wh.last_check_at) || "—")}</span></div>
      <div><span class="muted">24h count</span><span class="mono">${wh.count_24h ?? 0}</span></div>
      <div><span class="muted">Stored</span><span class="mono">${wh.total_events ?? 0}</span></div>
    </div>`;
  const rows = (wh.recent_events || []).map((e) => [
    esc(shortTime(e.time)),
    esc(e.asset),
    esc(e.direction),
    `<span class="mono">${esc(fmtUsd(e.usd_size))}</span>`,
    esc((e.source || "").replace(/_/g, " ")),
  ]);
  return `${stats}
    <h3 class="sub-heading">Recent whale moves</h3>
    ${renderCompactTable(["Time", "Asset", "Dir", "USD", "Source"], rows)}`;
}

function renderOverviewSnapshot(data) {
  const tb = data.tradebot || {};
  const wd = data.watchdog || {};
  const au = data.auditor || {};
  const s = data.summary || {};
  const holdings = (tb.portfolio?.holdings || [])
    .filter((h) => h.usd_value > 0)
    .sort((a, b) => b.usd_value - a.usd_value)
    .slice(0, 6);
  const chips = holdings.map((h) =>
    `<span class="holding-chip"><strong>${esc(h.asset)}</strong> <span class="mono">${esc(fmtUsd(h.usd_value))}</span></span>`
  ).join("") || `<span class="muted">No holdings</span>`;

  const lastTrade = (tb.recent_trades || [])[0];
  const lastTradeHtml = lastTrade
    ? `<div class="mono">${esc(shortTime(lastTrade.time))}</div><div>${esc(lastTrade.summary)}</div>
       <div class="mono ${pnlClass(lastTrade.gain_loss_usd)}">${esc(lastTrade.gain_loss)}</div>`
    : `<span class="muted">No trades yet</span>`;

  const latestEvent = (data.timeline?.events || [])[0];
  const latestHtml = latestEvent
    ? `<div class="mono">${esc(shortTime(latestEvent.time))} · ${esc(latestEvent.type)}</div>
       <div>${esc(latestEvent.title)}</div>
       <div class="muted small">${esc((latestEvent.detail || "").slice(0, 140))}${(latestEvent.detail || "").length > 140 ? "…" : ""}</div>`
    : `<span class="muted">No recent events</span>`;

  const blocked = (tb.blocked_opportunities || [])[0];
  const h = wd.health || {};
  const sess = wd.session || {};
  const pending = (au.pending_proposals || []).length;
  const wh = data.whales || {};
  const lastWhale = (wh.recent_events || [])[0];
  const whaleHtml = lastWhale
    ? `<div class="mono">${esc(shortTime(lastWhale.time))} · ${esc(lastWhale.asset)} ${esc(lastWhale.direction)}</div>
       <div class="mono">${esc(fmtUsd(lastWhale.usd_size))}</div>
       <div class="muted small">${esc((lastWhale.source || "").replace(/_/g, " "))}</div>`
    : `<span class="muted">${wh.enabled ? "No whale events yet" : "Enable WHALE_WATCH_ENABLED=1"}</span>`;

  return `
    <div class="snapshot-grid">
      <div class="snapshot-card">
        <h3>Holdings</h3>
        <div class="holding-chips">${chips}</div>
      </div>
      <div class="snapshot-card">
        <h3>Last trade</h3>
        ${lastTradeHtml}
      </div>
      <div class="snapshot-card">
        <h3>Bot status</h3>
        <div class="mini-stats">
          <div><span class="muted">Health</span><span class="mono ${scoreClass(s.health_score || 0)}">${s.health_score ?? "—"}/100</span></div>
          <div><span class="muted">Session trades</span><span class="mono">${s.trades_session ?? sess.trades_session ?? 0}</span></div>
          <div><span class="muted">Heartbeat</span><span class="mono">${sess.heartbeat_age_sec != null ? sess.heartbeat_age_sec + "s" : "—"}</span></div>
          <div><span class="muted">Auditor pending</span><span class="mono">${pending}</span></div>
          <div><span class="muted">Errors (1h)</span><span class="mono ${(h.errors_last_hour || 0) > 0 ? "score-bad" : ""}">${h.errors_last_hour ?? 0}</span></div>
          <div><span class="muted">Cash</span><span class="mono">${esc(fmtPct(s.cash_pct, true))}</span></div>
        </div>
      </div>
      <div class="snapshot-card">
        <h3>Latest whale</h3>
        ${whaleHtml}
        <div class="muted small">${wh.count_24h ?? 0} in last 24h</div>
      </div>
      <div class="snapshot-card">
        <h3>Latest activity</h3>
        ${latestHtml}
      </div>
      <div class="snapshot-card snapshot-wide">
        <h3>Below hurdle / blocked</h3>
        ${blocked ? `<div class="small">${esc(blocked.slice(0, 160))}${blocked.length > 160 ? "…" : ""}</div>` : `<span class="muted">None right now</span>`}
      </div>
    </div>`;
}

function renderTradebotDetail(tb) {
  const holdings = (tb.portfolio?.holdings || []).map((h) => [
    esc(h.asset), `<span class="mono">${esc(h.qty)}</span>`, `<span class="mono">${esc(fmtUsd(h.usd_value))}</span>`,
  ]);
  const trades = (tb.recent_trades || []).slice(0, 8).map((t) => [
    esc(t.time), esc(t.summary), `<span class="mono ${pnlClass(t.gain_loss_usd)}">${esc(t.gain_loss)}</span>`,
  ]);
  const blocked = (tb.blocked_opportunities || []).map((b) => `<li>${esc(b)}</li>`).join("") || "<li class='empty'>None</li>";
  return `
    <h3 class="sub-heading">Holdings</h3>
    ${renderCompactTable(["Asset", "Qty", "USD"], holdings)}
    <h3 class="sub-heading">Recent trades</h3>
    ${renderCompactTable(["Time", "Trade", "Gain/Loss"], trades)}
    <h3 class="sub-heading">Blocked / below hurdle</h3>
    <ul class="blocked-list">${blocked}</ul>`;
}

async function loadChartData() {
  const [histRes, tradesRes] = await Promise.all([
    fetch("/api/portfolio/history"),
    fetch("/api/trades/series"),
  ]);
  const hist = histRes.ok ? await histRes.json() : { points: [], pnl_deltas: [] };
  const trades = tradesRes.ok ? await tradesRes.json() : { buckets: [] };
  return { hist, trades };
}

async function refresh() {
  try {
    const [overviewRes, chartData] = await Promise.all([
      fetch("/api/overview"),
      loadChartData(),
    ]);
    if (!overviewRes.ok) throw new Error(overviewRes.statusText);
    const data = await overviewRes.json();
    refreshMs = (data.refresh_seconds || 15) * 1000;

    $("#meta-line").textContent = `Root: ${data.root} · refresh ${data.refresh_seconds}s · ${new Date().toLocaleTimeString()}`;
    $("#metric-strip").innerHTML = renderMetricStrip(data.summary);
    const snap = $("#overview-snapshot-panel");
    if (snap) snap.innerHTML = renderOverviewSnapshot(data);

    updatePortfolioChart(chartData.hist.points);
    updatePnlBarChart(chartData.hist.pnl_deltas);
    updateAllocationChart(data.tradebot?.portfolio?.holdings);
    updateTradesChart(chartData.trades.buckets);

    $("#forecasts-panel").innerHTML = renderForecasts(data.forecasts);
    $("#whales-panel").innerHTML = renderWhales(data.whales || {});
    $("#watchdog-panel").innerHTML = renderWatchdog(data.watchdog || {});
    $("#auditor-panel").innerHTML = renderAuditor(data.auditor || {});
    $("#timeline-panel").innerHTML = renderTimeline(data.timeline?.events);
    $("#tradebot-detail").innerHTML = renderTradebotDetail(data.tradebot || {});

    const bl = data.backlog || [];
    $("#backlog-list").innerHTML = bl.map((l) => `<li>${esc(l)}</li>`).join("") || "<li class='empty'>—</li>";
  } catch (err) {
    $("#meta-line").textContent = "Failed to load: " + err.message;
  }
}

function startPolling() {
  refresh();
  if (timer) clearInterval(timer);
  timer = setInterval(refresh, refreshMs);
}

document.addEventListener("DOMContentLoaded", startPolling);
