# 007 — Cursor agent shell sandbox issue on Windows

**Requested:** 2026-05-25
**Status:** instructions provided; user action required

## Request
> You reported that: The Cursor agent shell on your Windows machine has been refusing to execute commands all session (sandbox helper issue). Please fix this or tell me what steps to take.

## Symptom
Agent shell calls return `Sandbox policy 'workspace_readwrite' is not supported on this system. Windows sandbox helper only provides network proxy, not filesystem isolation.`

## Resolution (user)
Open Cursor Settings (`Ctrl+,`) → search `sandbox` → switch the Agent shell sandbox policy from `workspace-readwrite` to `disabled` / `insecure-none`, or edit `settings.json`:
```json
{ "cursor.agent.sandboxMode": "insecure-none" }
```
Restart Cursor. After that, the agent can run shell commands end-to-end and verify changes.

## Notes
- Confirmed Windows limitation per Cursor's sandbox helper output.
- Workaround until then: agent writes Python verification scripts the user can run manually.
