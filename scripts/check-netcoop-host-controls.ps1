$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'netcoop-cluster/netcoop_cluster_controls.ps1')
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testDirectory = Join-Path $temporaryRoot "lz-host-controls-$([Guid]::NewGuid().ToString('N'))"
try {
    if ((Get-ClusterHostMode $testDirectory 'l02_garbage') -ne 'auto') { throw 'Missing mode must be automatic' }
    Send-ClusterHostCommand $testDirectory 'labx8' 'restart'
    if ([IO.File]::ReadAllText((Join-Path $testDirectory 'host_command_labx8.txt')) -ne 'restart') { throw 'Request mismatch' }
    Send-ClusterHostCommand $testDirectory 'labx8' 'stop'
    if ([IO.File]::ReadAllText((Join-Path $testDirectory 'host_command_labx8.txt')) -ne 'stop') { throw 'Atomic replacement failed' }
    $claimed = Claim-ClusterHostCommand $testDirectory 'labx8'
    Send-ClusterHostCommand $testDirectory 'labx8' 'start'
    if ([IO.File]::ReadAllText($claimed) -ne 'stop') { throw 'Claim did not keep original request' }
    Remove-Item -LiteralPath $claimed
    if ([IO.File]::ReadAllText((Join-Path $testDirectory 'host_command_labx8.txt')) -ne 'start') { throw 'Consuming old request deleted a newer one' }
    Write-ClusterText (Join-Path $testDirectory 'host_mode_labx8.txt') 'off'
    if ((Get-ClusterHostMode $testDirectory 'labx8') -ne 'off') { throw 'Manual stop not persistent' }
    Request-ClusterSavedStop $testDirectory 1361 12345
    if ([IO.File]::ReadAllText((Join-Path $testDirectory 'host_stop_1361.txt')) -ne 'stop|12345') { throw 'Stop must target exact process' }
    $rejected = 0
    foreach ($bad in @('../bad','x/y','x\y','x|bad')) {
        try { Send-ClusterHostCommand $testDirectory $bad 'start' } catch { $rejected++ }
    }
    try { Send-ClusterHostCommand $testDirectory 'labx8' 'kill' } catch { $rejected++ }
    try { Request-ClusterSavedStop $testDirectory 0 12345 } catch { $rejected++ }
    if ($rejected -ne 6) { throw 'Invalid host requests admitted' }
    foreach ($file in @('netcoop_cluster_panel.ps1','netcoop_cluster_watchdog.ps1','netcoop_cluster_controls.ps1','netcoop_cluster_lifecycle.ps1')) {
        $tokens=$null; $errors=$null
        $null=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot "netcoop-cluster/$file"),[ref]$tokens,[ref]$errors)
        if ($errors.Count) { throw ($errors | Out-String) }
    }
    Write-Output 'PASS hoster IPC: atomic commands, persistent modes, process-bound saved stop, invalid requests rejected; no game/UI launched'
} finally {
    $resolved = [IO.Path]::GetFullPath($testDirectory)
    if (-not $resolved.StartsWith($temporaryRoot,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $resolved -Leaf) -notmatch '^lz-host-controls-[a-f0-9]{32}$') { throw 'Unsafe test cleanup target' }
    if ([IO.Directory]::Exists($resolved)) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
