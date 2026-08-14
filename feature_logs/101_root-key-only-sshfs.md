# 101 — Root key-only SSH for SSHFS full mount

**Requested:** 2026-08-13 01:29 PDT
**Status:** complete

## Request
PERMISSION GRANTED: enable root key-only SSH for SSHFS full mount

## Actions taken
VPS `mail.lynch.gdn` / `172.245.39.184`:
- Copied `cursor` authorized pubkey → `/root/.ssh/authorized_keys`
- Drop-in `/etc/ssh/sshd_config.d/50-root-key-only.conf`: `PermitRootLogin prohibit-password`
- Reloaded `sshd`; verified `root@` and `cursor@` key login

## Verification
```powershell
ssh -F NUL -i $env:USERPROFILE\.ssh\cursor_vps root@172.245.39.184 whoami
```
→ `root`

SSHFS-Win Manager: USER `root`, PATH `/`, same key file.

## Notes
Root password auth remains disabled. Prefer `cursor@` for day-to-day app work; `root@` for full filesystem mount only.
