#Requires -Version 5.1
<#
.SYNOPSIS
    Deploy TradeBot + dashboard to mail.lynch.gdn and enable systemd units.
#>
param(
    [string]$VpsHost = "172.245.39.184",
    [string]$VpsUser = "cursor",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\cursor_vps",
    [string]$RemoteDir = "/home/cursor/eth-trading-bot",
    [switch]$SkipLocalStop
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SshBase = @(
    "-F", "NUL",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-i", $IdentityFile
)
$Target = "$VpsUser@$VpsHost"

function Invoke-Remote {
    param([string]$Command)
    # Normalize to LF — Windows CRLF breaks bash heredocs / remote scripts.
    $normalized = ($Command -replace "`r`n", "`n") -replace "`r", "`n"
    & ssh @SshBase $Target $normalized
    if ($LASTEXITCODE -ne 0) { throw "Remote command failed ($LASTEXITCODE): $Command" }
}

function Copy-ToRemote {
    param([string]$LocalPath, [string]$RemotePath)
    & scp @SshBase -q $LocalPath "${Target}:${RemotePath}"
    if ($LASTEXITCODE -ne 0) { throw "scp failed: $LocalPath -> $RemotePath" }
}

Write-Host "==> Ensuring remote directory $RemoteDir"
Invoke-Remote "mkdir -p '$RemoteDir'"

# Prefer rsync if available; else tar+scp
$rsync = Get-Command rsync -ErrorAction SilentlyContinue
$excludeFile = Join-Path $env:TEMP "tradebot-rsync-excludes.txt"
@(
    ".venv/"
    "logs/"
    "archive/"
    "VersionHistory/"
    "receipts/"
    "reports/"
    "__pycache__/"
    "*.pyc"
    ".git/"
    "tradebot.lock"
    ".pytest_cache/"
    "Error Logs/"
) | Set-Content -Path $excludeFile -Encoding ascii

Write-Host "==> Syncing repo (no .venv / archive / VersionHistory)"
if ($rsync) {
    & rsync -az --delete --exclude-from=$excludeFile -e "ssh -F NUL -o BatchMode=yes -i `"$IdentityFile`"" `
        "$RepoRoot/" "${Target}:${RemoteDir}/"
    if ($LASTEXITCODE -ne 0) { throw "rsync failed" }
} else {
    $tarLocal = Join-Path $env:TEMP "eth-trading-bot-deploy.tgz"
    if (Test-Path $tarLocal) { Remove-Item $tarLocal -Force }
    Push-Location $RepoRoot
    try {
        # Windows tar (bsdtar)
        tar -czf $tarLocal `
            --exclude=.venv --exclude=logs --exclude=archive --exclude=VersionHistory `
            --exclude=receipts --exclude=reports --exclude=.git --exclude=__pycache__ `
            --exclude=tradebot.lock --exclude=".pytest_cache" --exclude="Error Logs" `
            .
    } finally {
        Pop-Location
    }
    Copy-ToRemote $tarLocal "$RemoteDir/.deploy.tgz"
    Invoke-Remote "cd '$RemoteDir' && tar -xzf .deploy.tgz && rm -f .deploy.tgz"
    Remove-Item $tarLocal -Force -ErrorAction SilentlyContinue
}

Write-Host "==> Copying runtime secrets/state (.env, paper baseline, paper state)"
Copy-ToRemote (Join-Path $RepoRoot ".env") "$RemoteDir/.env"
if (Test-Path (Join-Path $RepoRoot "paper_baseline.json")) {
    Copy-ToRemote (Join-Path $RepoRoot "paper_baseline.json") "$RemoteDir/paper_baseline.json"
}
if (Test-Path (Join-Path $RepoRoot ".paper_state.json")) {
    Copy-ToRemote (Join-Path $RepoRoot ".paper_state.json") "$RemoteDir/.paper_state.json"
}
if (Test-Path (Join-Path $RepoRoot ".tradebot_goals_state.json")) {
    Copy-ToRemote (Join-Path $RepoRoot ".tradebot_goals_state.json") "$RemoteDir/.tradebot_goals_state.json"
}

Write-Host "==> Ensuring DASHBOARD_HOST=127.0.0.1 on remote .env"
$patchPy = Join-Path $env:TEMP "patch_dashboard_bind.py"
@'
from pathlib import Path
p = Path("/home/cursor/eth-trading-bot/.env")
text = p.read_text(encoding="utf-8") if p.exists() else ""
lines = text.splitlines()
out = []
seen_host = seen_port = False
for line in lines:
    if line.startswith("DASHBOARD_HOST="):
        out.append("DASHBOARD_HOST=127.0.0.1"); seen_host = True
    elif line.startswith("DASHBOARD_PORT="):
        out.append("DASHBOARD_PORT=8765"); seen_port = True
    else:
        out.append(line)
if not seen_host:
    out.append("DASHBOARD_HOST=127.0.0.1")
if not seen_port:
    out.append("DASHBOARD_PORT=8765")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
print("dashboard bind ok")
'@ | Set-Content -Path $patchPy -Encoding utf8
# Force LF
[IO.File]::WriteAllText($patchPy, ((Get-Content $patchPy -Raw) -replace "`r`n","`n"))
Copy-ToRemote $patchPy "$RemoteDir/scripts/_patch_dashboard_bind.py"
Invoke-Remote "python3 '$RemoteDir/scripts/_patch_dashboard_bind.py'"

Write-Host "==> Ensuring python3-venv + creating venv + installing requirements"
Invoke-Remote "set -e; sudo apt-get update -qq; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip; cd '$RemoteDir'; rm -rf .venv; python3 -m venv .venv; .venv/bin/pip install -U pip wheel; .venv/bin/pip install -r requirements.txt; mkdir -p logs"

Write-Host "==> Installing systemd units"
Copy-ToRemote (Join-Path $RepoRoot "deploy\systemd\tradebot.service") "/tmp/tradebot.service"
Copy-ToRemote (Join-Path $RepoRoot "deploy\systemd\tradebot-dashboard.service") "/tmp/tradebot-dashboard.service"
Invoke-Remote "set -e; sudo mv /tmp/tradebot.service /etc/systemd/system/tradebot.service; sudo mv /tmp/tradebot-dashboard.service /etc/systemd/system/tradebot-dashboard.service; sudo systemctl daemon-reload; sudo systemctl enable tradebot tradebot-dashboard; sudo systemctl restart tradebot tradebot-dashboard; sleep 4; sudo systemctl --no-pager --full status tradebot tradebot-dashboard || true"

Write-Host "==> Health checks"
Invoke-Remote "cd '$RemoteDir'; .venv/bin/python scripts/is_tradebot_running.py; curl -fsS http://127.0.0.1:8765/api/paper/status; echo"

if (-not $SkipLocalStop) {
    Write-Host "==> Stopping local Windows TradeBot to avoid dual paper bots"
    $lock = Join-Path $RepoRoot "tradebot.lock"
    if (Test-Path $lock) {
        $botPid = Get-Content $lock
        Stop-Process -Id $botPid -Force -ErrorAction SilentlyContinue
        Start-Sleep 2
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped local PID $botPid"
    } else {
        Write-Host "No local tradebot.lock"
    }
}

Write-Host ""
Write-Host "Deploy complete."
Write-Host "Tunnel: ssh -F NUL -i `"$IdentityFile`" -L 8765:127.0.0.1:8765 $Target"
Write-Host "Then open http://127.0.0.1:8765/"
