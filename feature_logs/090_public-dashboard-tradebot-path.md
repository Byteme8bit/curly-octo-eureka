# 090 — Public dashboard at https://lynch.gdn/tradebot/

**Requested:** 2026-08-06
**Status:** complete

## Request
Public URL for dashboard with basic auth; use path `/tradebot/` (not subdomain).

## Actions taken
- `DASHBOARD_BASE_PATH` support in dashboard config/app/static
- nginx snippet `deploy/nginx/tradebot-dashboard.conf`
- systemd dashboard env `DASHBOARD_BASE_PATH=/tradebot`
- HTTP basic auth file `/etc/nginx/.htpasswd-tradebot`

## Verification
Open https://lynch.gdn/tradebot/ — basic auth prompt, then dashboard loads.

## Notes
Dashboard still binds 127.0.0.1 only; nginx terminates TLS.
