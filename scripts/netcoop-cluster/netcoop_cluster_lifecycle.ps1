# Pure controller functions. Importing this file never launches a process.
function Get-ClusterLaunchNeedGB {
    return [math]::Max(6.0, 2 * (Server-MemoryGB))
}

function Update-ClusterLocation($s) {
    $p = $running[$s.Name]
    $claimed = Claim-ClusterHostCommand $wakeDir $s.Name
    if ($claimed) {
        try {
            $action = [IO.File]::ReadAllText($claimed).Trim()
            if ($action -notin @('start','stop','restart','auto')) { throw "Invalid host command for $($s.Name)" }
            $mode = switch ($action) { 'stop' { 'off' } 'auto' { 'auto' } default { 'on' } }
            Write-ClusterText (Join-Path $wakeDir "host_mode_$($s.Name).txt") $mode
            $s.Restarting = $false
            if ($action -ne 'stop') {
                $s.Failures = 0; $s.Blocked = $false; $s.NextStart = $null; $s.LastExitCode = $null
            }
            if ($action -in @('stop','restart') -and $p -and -not $p.HasExited) {
                Request-ClusterSavedStop $wakeDir $s.Port $p.Id
                $s.State = 'saving'; $s.Restarting = $action -eq 'restart'
            }
        } finally { Remove-Item -LiteralPath $claimed -Force }
    }
    $mode = Get-ClusterHostMode $wakeDir $s.Name
    if ($p -and $p.HasExited) {
        $expected = $s.State -eq 'saving' -or $mode -eq 'off'
        $startupFailed = [bool]$s.Loading
        $file = Find-Log $s
        $lostLevel = $file -and $s.LoadStarted -and $file.LastWriteTime -ge $s.LoadStarted -and
            (Select-String -LiteralPath $file.FullName -Pattern 'dedicated lost its level' -Quiet)
        $s.LastExitCode = $p.ExitCode
        $running.Remove($s.Name); $s.Loading = $false; $s.Restarting = $false; $s.State = 'stopped'
        if (-not $expected -and ($p.ExitCode -ne 0 -or $startupFailed -or $lostLevel)) {
            $s.Failures = [int]$s.Failures + 1
            $s.Blocked = $s.Failures -ge 3
            $s.NextStart = (Get-Date).AddSeconds([math]::Min(300, 30 * [math]::Pow(2, $s.Failures - 1)))
            $s.State = if ($s.Blocked) { 'failed' } else { 'retry' }
            Write-Host ("{0:HH:mm:ss} {1} exited with code {2}; attempt {3}; {4}" -f (Get-Date), $s.Name, $p.ExitCode, $s.Failures, $s.State)
        } elseif (-not $expected -and ($mode -eq 'on' -or -not $s.OnDemand)) {
            # Closing a running console is an intentional stop, not a crash.
            Write-ClusterText (Join-Path $wakeDir "host_mode_$($s.Name).txt") 'off'
        }
        $p = $null
    }
    if ($mode -eq 'off') {
        if ($p -and $s.State -ne 'saving') {
            Request-ClusterSavedStop $wakeDir $s.Port $p.Id
            $s.State = 'saving'
        } elseif (-not $p) { $s.State = 'stopped' }
        return
    }
    if (-not $p) { return }
    if ($s.Loading -and $s.State -ne 'saving') {
        $file = Find-Log $s
        if ($file -and $file.LastWriteTime -ge $s.LoadStarted -and
            (Select-String -LiteralPath $file.FullName -Pattern $readyPattern -Quiet)) {
            $s.Loading = $false; $s.State = 'running'; $s.HealthySince = Get-Date
        } elseif (((Get-Date) - $s.LoadStarted).TotalSeconds -ge $LoadTimeoutSeconds) {
            $s.State = 'loading_timeout'
        }
    }
    if ($s.HealthySince -and ((Get-Date) - $s.HealthySince).TotalSeconds -ge 300) { $s.Failures = 0 }
    if ((Players-On $s) -gt 0) { $idleSince.Remove($s.Name) }
    elseif (-not $idleSince[$s.Name]) { $idleSince[$s.Name] = Get-Date }
    $wake = Join-Path $wakeDir "wake_$($s.Name).txt"
    if (Test-Path -LiteralPath $wake) { Remove-Item -LiteralPath $wake -Force -ErrorAction SilentlyContinue }
}

function Start-ClusterQueuedLocation {
    $paused = Test-Path -LiteralPath (Join-Path $wakeDir 'host_master_paused.txt')
    foreach ($s in $servers) {
        if (-not $paused -and $s.State -eq 'master_stopped') { $s.State = 'stopped' }
        if ($paused -and -not $running[$s.Name] -and -not $s.Blocked -and (Get-ClusterHostMode $wakeDir $s.Name) -ne 'off') { $s.State = 'master_stopped' }
    }
    if ($paused) { return }
    # One heavy load at a time, including a loading process asked to save/stop.
    foreach ($s in $servers) {
        $p = $running[$s.Name]
        if ($p -and -not $p.HasExited -and $s.Loading) { return }
    }
    foreach ($s in $servers) {
        $p = $running[$s.Name]
        if ($p -and -not $p.HasExited) { continue }
        $mode = Get-ClusterHostMode $wakeDir $s.Name
        if ($mode -eq 'off') { continue }
        $wake = Join-Path $wakeDir "wake_$($s.Name).txt"
        if ($mode -ne 'on' -and $s.OnDemand -and -not (Test-Path -LiteralPath $wake)) { continue }
        if ($s.Blocked) { $s.State = 'failed'; continue }
        if ($s.NextStart -and (Get-Date) -lt $s.NextStart) { $s.State = 'retry'; continue }
        $need = Get-ClusterLaunchNeedGB
        if (-not ((Make-Room $need) -or (Free-CommitGB) -ge $need)) { $s.State = 'memory'; return }
        # A stop may have arrived during the budget/CIM checks. Handle it first.
        if (Test-Path -LiteralPath (Join-Path $wakeDir "host_command_$($s.Name).txt")) { return }
        try {
            $running[$s.Name] = Start-Location $s
            if (Test-Path -LiteralPath $wake) { Remove-Item -LiteralPath $wake -Force }
        } catch {
            $s.Loading = $false; $s.State = 'failed'; $s.Blocked = $true
            Write-Host ("{0:HH:mm:ss} cannot start {1}: {2}" -f (Get-Date), $s.Name, $_.Exception.Message)
        }
        return
    }
}
