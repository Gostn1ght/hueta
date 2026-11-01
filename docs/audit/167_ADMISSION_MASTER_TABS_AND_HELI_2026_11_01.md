# Follow-up: admission, master tabs, observer animation and Mi-24

Status: implementation in progress, not released. Previous release 2026.11.01.1 is delivered (audit 166).

## Confirmed failures

The owner server log at `J:/LostZone/Lost Zone/appdata/server/logs/xray_srv_l01_escape_mahito.log` reports checkpoint submission refusal immediately before character-selection refusal for two accounts. The NCHA writer and both master decoders were updated, but the native checkpoint worker and upload/download envelope still rejected every format newer than NCH9. The native worker now shares the envelope validator; both accept exactly NCH3..9 and NCHA. Unknown formats remain refused. Coordinator admission and durable outbox tests now send actual NCHA fixtures through the master, including resume and transfer, rather than exercising only NCH9.

The hidden console and hidden lists were re-shown when background updates sent WM_SETREDRAW(TRUE), which adds WS_VISIBLE in DefWindowProc (Microsoft documentation: https://learn.microsoft.com/en-us/windows/win32/gdi/wm-setredraw). Redraw batching now runs only for controls that were visible before the update. The native GUI fixture now appends real log text and replaces list rows between every tab switch before asserting visibility.

Native compilation and fixtures run only in GitHub. No owner game/server/master is launched for tests.
