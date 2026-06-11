"""Human-readable and machine-readable verification reports."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from bot.verifier.models import SessionReport, Verdict
from bot.verifier.summary import format_executive_banner


def format_text_report(report: SessionReport, *, verbose: bool = False) -> str:
    lines = [
        format_executive_banner(report),
        "",
        "INDEPENDENT TRADE VERIFICATION REPORT",
        f"Generated: {report.generated_at}",
        f"Trades reviewed: {report.trades_reviewed}",
        "",
        "VERDICT SUMMARY",
        f"  CONFIRM:   {report.confirm}",
        f"  DENY:      {report.deny}",
        f"  UNCERTAIN: {report.uncertain}",
        "",
        f"Paper PnL (reviewed trades): ${report.paper_pnl_usd:,.2f}",
        f"Fee drag (reviewed trades):  ${report.estimated_fee_drag_usd:,.2f}",
        "",
    ]

    if report.systematic_issues:
        lines.append("SYSTEMATIC ISSUES")
        for issue in report.systematic_issues:
            lines.append(f"  - {issue}")
        lines.append("")

    lines.append("SOURCES")
    for key, path in report.sources.items():
        lines.append(f"  {key}: {path}")
    lines.append("")

    if verbose:
        lines.append("TRADE DETAILS")
        for tv in report.trade_verdicts:
            lines.append("-" * 40)
            lines.append(
                f"[{tv.verdict.value}] #{tv.trade_index} {tv.time} "
                f"{tv.from_asset}->{tv.to_asset} ({tv.symbol})"
            )
            if tv.receipt_file:
                lines.append(f"  Receipt: {tv.receipt_file}")
            for check in tv.checks:
                if check.verdict != Verdict.CONFIRM:
                    lines.append(f"  {check.name}: {check.verdict.value} — {check.detail}")
    else:
        non_confirm = [t for t in report.trade_verdicts if t.verdict != Verdict.CONFIRM]
        if non_confirm:
            lines.append(f"NON-CONFIRM TRADES ({len(non_confirm)}) — use --verbose for all")
            for tv in non_confirm[:50]:
                failed = [c for c in tv.checks if c.verdict != Verdict.CONFIRM]
                reasons = "; ".join(f"{c.name}: {c.detail[:80]}" for c in failed[:3])
                lines.append(
                    f"  [{tv.verdict.value}] #{tv.trade_index} {tv.from_asset}->{tv.to_asset} — {reasons}"
                )
            if len(non_confirm) > 50:
                lines.append(f"  ... and {len(non_confirm) - 50} more")

    lines.append("=" * 60)
    return "\n".join(lines)


def write_json_report(report: SessionReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)
    return path


def write_html_report(report: SessionReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for tv in report.trade_verdicts:
        checks_html = "<br>".join(
            escape(f"{c.name}: {c.verdict.value} — {c.detail}")
            for c in tv.checks
            if c.verdict != Verdict.CONFIRM
        ) or "All checks passed"
        rows.append(
            f"<tr class='{tv.verdict.value.lower()}'>"
            f"<td>{tv.trade_index}</td>"
            f"<td>{escape(tv.time)}</td>"
            f"<td>{escape(tv.from_asset)}→{escape(tv.to_asset)}</td>"
            f"<td><strong>{tv.verdict.value}</strong></td>"
            f"<td>{checks_html}</td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Trade Verification {escape(report.generated_at)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
.summary {{ display: flex; gap: 2rem; margin-bottom: 1.5rem; }}
.card {{ padding: 1rem 1.5rem; border-radius: 8px; background: #f4f4f5; }}
.confirm {{ background: #ecfdf5; }}
.deny {{ background: #fef2f2; }}
.uncertain {{ background: #fffbeb; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; vertical-align: top; }}
th {{ background: #18181b; color: white; }}
</style></head><body>
<h1>Independent Trade Verification</h1>
<p>Generated {escape(report.generated_at)} — {report.trades_reviewed} trades reviewed</p>
<div class="summary">
  <div class="card confirm"><strong>CONFIRM</strong><br>{report.confirm}</div>
  <div class="card uncertain"><strong>UNCERTAIN</strong><br>{report.uncertain}</div>
  <div class="card deny"><strong>DENY</strong><br>{report.deny}</div>
</div>
<p>Paper PnL: ${report.paper_pnl_usd:,.2f} | Fee drag: ${report.estimated_fee_drag_usd:,.2f}</p>
<table><thead><tr><th>#</th><th>Time</th><th>Route</th><th>Verdict</th><th>Notes</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
