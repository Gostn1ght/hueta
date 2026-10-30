$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'netcoop-cluster/netcoop_cluster_controls.ps1')
. (Join-Path $PSScriptRoot 'netcoop-cluster/netcoop_cluster_lifecycle.ps1')
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$wakeDir = Join-Path $temporaryRoot "lz-watchdog-$([Guid]::NewGuid().ToString('N'))"
$running = @{}; $idleSince = @{}; $script:spawnRequests = @()
$script:physicalEnough = $false; $script:commitGB = 0
$LoadTimeoutSeconds = 600; $readyPattern = 'ALife switch distance'
$exe = 'NEVER-EXECUTE.exe'; $Runtime = $wakeDir; $perServer = 128
function Publish-HostState {}
function Players-On($s) { return 0 }
function Server-MemoryGB { return 1.5 }
function Make-Room($need) { return $script:physicalEnough }
function Free-CommitGB { return $script:commitGB }
function Find-Log($s) { return Get-Item -LiteralPath (Join-Path $wakeDir "$($s.Name).log") -ErrorAction SilentlyContinue }
function Start-Process {
    param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,[switch]$PassThru)
    if ($FilePath -ne $exe -or $WindowStyle -ne 'Hidden') { throw 'Unexpected real process request' }
    $script:spawnRequests += $ArgumentList
    return [pscustomobject]@{ Id=12345; HasExited=$false; ExitCode=0; PriorityClass='Normal' }
}
function Check($ok,$message) { if (-not $ok) { throw $message } }
function Map($name,$port) { return @{Name=$name;Port=$port;Start='start';World='world';OnDemand=$false;State='stopped';Loading=$false} }
try {
    # Extract the actual launcher function, but replace its only process API.
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'netcoop-cluster/netcoop_cluster_watchdog.ps1'),[ref]$tokens,[ref]$errors)
    Check ($errors.Count -eq 0) 'Watchdog syntax error'
    $function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-Location'},$true)
    Invoke-Expression $function.Extent.Text
    $a=Map 'l08_yantar' 1319; $b=Map 'l01_escape' 1301; $servers=@($a,$b)
    Send-ClusterHostCommand $wakeDir $a.Name 'start'; Update-ClusterLocation $a
    Send-ClusterHostCommand $wakeDir $b.Name 'start'; Update-ClusterLocation $b
    Check ((Get-ClusterLaunchNeedGB) -eq 6) 'Startup peak reserve was underestimated'
    Start-ClusterQueuedLocation
    Check ($script:spawnRequests.Count -eq 0 -and $a.State -eq 'memory') 'Initial start bypassed memory gate'
    $script:commitGB=8
    Write-ClusterText (Join-Path $wakeDir 'host_master_paused.txt') 'paused'
    Start-ClusterQueuedLocation
    Check ($script:spawnRequests.Count -eq 0 -and $a.State -eq 'master_stopped') 'Stopped master still launched maps'
    Remove-Item -LiteralPath (Join-Path $wakeDir 'host_master_paused.txt')
    Start-ClusterQueuedLocation
    Check ($script:spawnRequests.Count -eq 1 -and $a.Loading) 'Budgeted map did not start'
    Start-ClusterQueuedLocation
    Check ($script:spawnRequests.Count -eq 1) 'Two maps loaded simultaneously'
    # Stop both the slow load and queued map without waiting for readiness.
    Send-ClusterHostCommand $wakeDir $a.Name 'stop'; Update-ClusterLocation $a
    Send-ClusterHostCommand $wakeDir $b.Name 'stop'; Update-ClusterLocation $b
    Check ($a.State -eq 'saving' -and (Get-ClusterHostMode $wakeDir $a.Name) -eq 'off') 'Slow-load stop was not applied'
    Check ((Get-ClusterHostMode $wakeDir $b.Name) -eq 'off') 'Queued stop was not persistent'
    Check ([IO.File]::ReadAllText((Join-Path $wakeDir 'host_stop_1319.txt')) -eq 'stop|12345') 'Stop targeted the wrong process'
    $running[$a.Name].HasExited=$true
    Update-ClusterLocation $a; Start-ClusterQueuedLocation
    Check ($script:spawnRequests.Count -eq 1 -and -not $running[$a.Name]) 'Stopped maps restarted'
    # Late readiness must recover from loading_timeout instead of sticking there.
    Send-ClusterHostCommand $wakeDir $b.Name 'start'; Update-ClusterLocation $b; Start-ClusterQueuedLocation
    $b.LoadStarted=(Get-Date).AddSeconds(-601)
    Update-ClusterLocation $b
    Check ($b.State -eq 'loading_timeout') 'Long load not visible'
    [IO.File]::WriteAllText((Join-Path $wakeDir "$($b.Name).log"),'ALife switch distance 650 m')
    Update-ClusterLocation $b
    Check ($b.State -eq 'running' -and -not $b.Loading) 'Late readiness never recovered'
    # Repeated failures wait, then quarantine after three; explicit start resets it.
    for ($attempt=1;$attempt -le 3;$attempt++) {
        $running[$b.Name].HasExited=$true; $running[$b.Name].ExitCode=3
        Update-ClusterLocation $b
        Check ($b.Failures -eq $attempt) 'Failure counter incorrect'
        $count=$script:spawnRequests.Count; Start-ClusterQueuedLocation
        Check ($script:spawnRequests.Count -eq $count) 'Crash immediately relaunched'
        if ($attempt -lt 3) { $b.NextStart=(Get-Date).AddSeconds(-1); Start-ClusterQueuedLocation }
    }
    Check ($b.Blocked -and $b.State -eq 'failed') 'Crash loop was not quarantined'
    Send-ClusterHostCommand $wakeDir $b.Name 'start'; Update-ClusterLocation $b; Start-ClusterQueuedLocation
    Check ($b.Loading -and -not $b.Blocked -and $b.Failures -eq 0) 'Explicit start did not reset failed state'
    $b.Loading=$false; $b.State='running'; $running[$b.Name].HasExited=$true; $running[$b.Name].ExitCode=0
    Update-ClusterLocation $b
    Check ((Get-ClusterHostMode $wakeDir $b.Name) -eq 'off') 'A deliberately closed console will respawn'
    Send-ClusterHostCommand $wakeDir $b.Name 'start'; Update-ClusterLocation $b; Start-ClusterQueuedLocation
    $b.Loading=$false; $b.State='running'; $b.LoadStarted=(Get-Date).AddSeconds(-1)
    [IO.File]::WriteAllText((Join-Path $wakeDir "$($b.Name).log"),'! [Lost Zone] dedicated lost its level; exiting instead of opening the menu')
    $running[$b.Name].HasExited=$true; $running[$b.Name].ExitCode=0
    Update-ClusterLocation $b
    Check ($b.State -eq 'retry' -and $b.Failures -eq 1) 'Lost level was treated as a manual stop'
    Write-Output 'PASS actual watchdog: mocked process API only; memory-gated serial startup, responsive stop, persistent off, late readiness, crash backoff/quarantine and explicit retry; no game/master/UI launched'
} finally {
    $resolved=[IO.Path]::GetFullPath($wakeDir)
    if (-not $resolved.StartsWith($temporaryRoot,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $resolved -Leaf) -notmatch '^lz-watchdog-[a-f0-9]{32}$') { throw 'Unsafe fixture cleanup target' }
    if ([IO.Directory]::Exists($resolved)) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
