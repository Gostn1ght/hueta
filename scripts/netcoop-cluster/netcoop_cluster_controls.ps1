# Shared local hoster IPC. Dot-sourcing this file never starts or stops a process.
function Write-ClusterText([string]$Path, [string]$Text) {
    $directory = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $temporary = "$Path.$PID.$([Guid]::NewGuid().ToString('N')).tmp"
    [IO.File]::WriteAllText($temporary, $Text, [Text.UTF8Encoding]::new($false))
    try {
        # A reader (the panel, every second) may hold the file for a moment:
        # retry instead of failing the whole watchdog on a sharing violation.
        for ($attempt = 1; ; $attempt++) {
            try {
                if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
                else { [IO.File]::Move($temporary, $Path) }
                break
            } catch [System.IO.IOException], [System.UnauthorizedAccessException] {
                if ($attempt -ge 40) { throw }
                Start-Sleep -Milliseconds 50
            }
        }
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    }
}

function Get-ClusterHostMode([string]$Directory, [string]$Map) {
    if ($Map -notmatch '^\w+$') { throw 'Invalid map key' }
    $file = Join-Path $Directory "host_mode_$Map.txt"
    if (-not [IO.File]::Exists($file)) { return 'auto' }
    $mode = [IO.File]::ReadAllText($file).Trim()
    if ($mode -notin @('on', 'off', 'auto')) { throw "Invalid host mode for $Map" }
    return $mode
}

function Send-ClusterHostCommand([string]$Directory, [string]$Map, [string]$Action) {
    if ($Map -notmatch '^\w+$' -or $Action -notin @('start', 'stop', 'restart', 'auto')) { throw 'Invalid host command' }
    Write-ClusterText (Join-Path $Directory "host_command_$Map.txt") $Action
}

# Claim by rename, then consume only the claimed file. A newer command can
# replace the mailbox while this one is being handled and must not be deleted.
function Claim-ClusterHostCommand([string]$Directory, [string]$Map) {
    if ($Map -notmatch '^\w+$') { throw 'Invalid map key' }
    $file = Join-Path $Directory "host_command_$Map.txt"
    $claimed = "$file.$PID.$([Guid]::NewGuid().ToString('N')).claimed"
    try { [IO.File]::Move($file, $claimed); return $claimed }
    catch [IO.IOException] { return $null }
}

function Request-ClusterSavedStop([string]$Directory, [int]$Port, [int]$ProcessId) {
    if ($Port -lt 1 -or $Port -gt 65534 -or $ProcessId -lt 1) { throw 'Invalid server identity' }
    Write-ClusterText (Join-Path $Directory "host_stop_$Port.txt") "stop|$ProcessId"
}
