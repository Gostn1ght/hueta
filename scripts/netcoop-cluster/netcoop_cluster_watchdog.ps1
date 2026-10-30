# Location cluster watchdog: runs this machine's location servers and starts
# again any that exits. The plan is appdata\server\netcoop_cluster.ltx
# ([locations] map = host:port, [launch] map = start section, [cluster]
# per_server); a map belongs to this machine when its host is one of its
# addresses (or 127.0.0.1/localhost). Servers start one after another: a
# loading server briefly needs ~6 GB.
#
# It fits the servers to this machine: free memory is measured all the time;
# the system keeps -SystemReserveGB and a game client on the same PC keeps
# -ClientReserveGB (while it runs, or always with -WithClient). When a player
# heads to a map whose server is not running and memory is short, the server
# that has stood empty the longest is stopped first (its world was saved when
# its last player left). Servers use normal priority: starving authority ticks
# makes movement and vehicles stutter even when the client's FPS is high.
# The video card is the client's alone (servers draw nothing).
#   powershell -ExecutionPolicy Bypass -File netcoop_cluster_watchdog.ps1 [-Maps k00_marsh,l01_escape] [-WithClient]
param(
    [string]$Runtime = $PSScriptRoot,
    [string[]]$Maps = @(),
    [int]$LoadTimeoutSeconds = 600,
    [double]$SystemReserveGB = 3,
    [double]$ClientReserveGB = 8,
    [switch]$WithClient,
    [switch]$NoAutoStart
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'netcoop_cluster_controls.ps1')
. (Join-Path $PSScriptRoot 'netcoop_cluster_lifecycle.ps1')
$Runtime = [IO.Path]::GetFullPath($Runtime)
$mutexHash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($Runtime.ToLowerInvariant()))).Replace('-', '')
$createdMutex = $false
$watchdogMutex = [Threading.Mutex]::new($true, "Local\LostZoneCluster_$mutexHash", [ref]$createdMutex)
if (-not $createdMutex) { throw 'A watchdog already owns this runtime' }
# "-Maps a,b" through -File arrives as one string.
$Maps = @($Maps | ForEach-Object { $_ -split "," } | Where-Object { $_ })
$exe = Join-Path $Runtime "dedicated\LostZoneServerDX11.exe"
$planPath = Join-Path $Runtime "appdata\server\netcoop_cluster.ltx"
if (-not (Test-Path $exe)) { throw "missing $exe" }
if (-not (Test-Path $planPath)) { throw "missing $planPath (copy scripts\netcoop-cluster\netcoop_cluster.ltx.full there)" }

# Minimal ltx reader: section -> ordered key/value pairs.
$plan = @{}; $section = $null
foreach ($line in Get-Content $planPath -Encoding Default) {
    $text = ($line -split ";", 2)[0].Trim()
    if ($text -match "^\[(.+)\]$") { $section = $Matches[1]; $plan[$section] = [ordered]@{}; continue }
    if ($section -and $text -match "^([^=]+?)\s*=\s*(.+)$") { $plan[$section][$Matches[1]] = $Matches[2] }
}
$perServer = if ($plan["cluster"] -and $plan["cluster"]["per_server"]) { [int]$plan["cluster"]["per_server"] } else { 128 }
$local = @("127.0.0.1", "localhost", $env:COMPUTERNAME.ToLower())
try { $local += (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | ForEach-Object { $_.IPAddress }) } catch {}

# A map belongs here when its host is one of this machine's addresses. A
# single-host plan that lists the router's public IP (as the README says for
# play over the internet) matches no local interface: then every map is ours.
$anyHost = $false
foreach ($map in $plan["locations"].Keys) {
    $hostName = ($plan["locations"][$map] -split ":")[0]
    if ($local -contains $hostName.ToLower()) { $anyHost = $false; break }
    $anyHost = $true
}
if ($anyHost) { Write-Host "no plan address is local: all maps run on this machine" }
$servers = @()
foreach ($map in $plan["locations"].Keys) {
    if ($map -notmatch '^\w+$') { throw 'Invalid map key in cluster plan' }
    if ($Maps.Count -and $Maps -notcontains $map) { continue }
    $address = $plan["locations"][$map]
    $hostName, $port = $address -split ":"
    if (-not $anyHost -and $local -notcontains $hostName.ToLower()) { continue }
    $start = $plan["launch"][$map]
    if (-not $start) { Write-Host "skip $map`: no [launch] start section"; continue }
    if ($start -notmatch '^\w+$' -or [int]$port -lt 1 -or [int]$port -gt 65534) { throw "Invalid launch plan for $map" }
    # The first two servers keep the worlds they had before the full plan.
    $world = switch ($map) { "k00_marsh" { "zone" } "l01_escape" { "zone_escape" } default { "zone_$map" } }
    $onDemand = $plan["on_demand"] -and $plan["on_demand"][$map] -eq "1"
    $servers += @{ Name = $map; Port = [int]$port; Start = $start; World = $world; OnDemand = $onDemand }
}
if (-not $servers.Count) { throw "no maps of this machine in $planPath" }

function Find-Log($s) {
    $log = if ($s.Name -eq "k00_marsh") { "srv" } else { "srv_$($s.Name)" }
    Get-ChildItem (Join-Path $Runtime "appdata\server\logs") -Filter "xray_$log`_*.log" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "^xray_$([regex]::Escape($log))_[^_]+\.log$" } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

# Milestones of a location server start, in log order, with the share of the
# load done when they appear (measured on Cordon: ~4 min to the first save).
$loadMilestones = @(
    @('Loading DLL: xrGame\.dll', 4), @('Starting RENDER device', 8), @('\* phase time: 0 ms', 12),
    @('\[world\] acquired|no saved world yet|loading saved world', 16), @('Loading spawn registry', 50),
    @('spawn points are successfully loaded', 58), @('Loading HOM', 76), @('squad\(s\), \d+ NPC\(s\) of other maps', 90),
    @('ALife switch distance|\[world\] saved \S+ \(bootstrap\)', 100)
)
$readyPattern = 'ALife switch distance|\[world\] saved \S+ \(bootstrap\)'
function Get-LoadProgress($s) {
    if ($s.State -eq 'running') { return 100 }
    if ($s.State -notin @('loading','loading_timeout') -or -not $s.LoadStarted) { return 0 }
    $file = Find-Log $s
    $done = 1; $next = 4
    if ($file -and $file.LastWriteTime -gt $s.LoadStarted) {
        $seen = @(Select-String -LiteralPath $file.FullName -Pattern ($loadMilestones | ForEach-Object { $_[0] }) -ErrorAction SilentlyContinue | ForEach-Object { $_.Line })
        foreach ($m in $loadMilestones) {
            if (@($seen | Where-Object { $_ -match $m[0] }).Count) { $done = $m[1] } else { $next = $m[1]; break }
        }
    }
    if ($done -ge 100) { return 99 }
    # Creep toward the next milestone (never reaching it) while the log is quiet.
    $since = if ($s.MilestoneAt -and $s.MilestoneValue -eq $done) { $s.MilestoneAt } else { $s.MilestoneValue = $done; $s.MilestoneAt = Get-Date; $s.MilestoneAt }
    $creep = [math]::Min(0.85, ((Get-Date) - $since).TotalSeconds / 90.0)
    return [int][math]::Floor($done + ($next - $done) * $creep)
}

function Start-Location($s) {
    $oldStop = Join-Path $wakeDir "host_stop_$($s.Port).txt"
    if (Test-Path -LiteralPath $oldStop) { Remove-Item -LiteralPath $oldStop -Force }
    $s.State = 'loading'; $s.Loading = $true; $s.LoadStarted = Get-Date; $s.MilestoneAt = $null; $s.HealthySince = $null
    Publish-HostState
    $log = if ($s.Name -eq "k00_marsh") { "srv" } else { "srv_$($s.Name)" }
    $arguments = "-nosplashwindow -noprefetch -netcoop -multi_instance -netcoop_background -logname $log -fsltx fsgame_server.ltx " +
        "-netport $($s.Port) -netcoop_start_location=$($s.Start) -netcoop_world=$($s.World) " +
        # Empty for 2 min: hibernate (world saved, RAM returned, wakes on connect).
        # On-demand maps exit only after 6 h empty, or when Make-Room needs memory.
        "-netcoop_hibernate=120 " +
        $(if ($s.OnDemand) { "-netcoop_idle_exit=21600 " } else { "" }) +
        # +1: the server's own local client takes a slot.
        "-start `"server(all/single/alife/new/portsv=$($s.Port)/maxplayers=$($perServer + 1))`" " +
        "`"client(localhost/name=serverauthority/port=$($s.Port)/portcl=$($s.Port + 1))`""
    $p = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $Runtime -WindowStyle Hidden -PassThru
    $running[$s.Name] = $p
    Publish-HostState
    try { $p.PriorityClass = "Normal" } catch {}
    Write-Host ("{0:HH:mm:ss} started {1} (port {2}, pid {3})" -f (Get-Date), $s.Name, $s.Port, $p.Id)
    # The outer loop monitors readiness. Never block operator commands here.
    return $p
}

# ---- machine budget ----------------------------------------------------------
$os = Get-CimInstance Win32_OperatingSystem
$totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$cores = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
Write-Host ("machine: {0} GB memory, {1} logical cores; reserve {2} GB system + {3} GB game client" -f $totalGB, $cores, $SystemReserveGB, $ClientReserveGB)

function Server-MemoryGB {
    # Private commit, not resident RAM: paging a map out does not make the
    # next load cheaper. Include only the exact location processes we own.
    $sizes = @($running.Values | Where-Object { $_ -and -not $_.HasExited } | ForEach-Object { $_.Refresh(); $_.PrivateMemorySize64 })
    if ($sizes.Count) { return [math]::Max(0.5, (($sizes | Measure-Object -Average).Average / 1GB)) }
    return 1.5
}
function Free-BudgetGB {
    $free = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
    $clientRunning = [bool](Get-Process LostZoneClientDX11 -ErrorAction SilentlyContinue)
    # A running client already holds its memory; without one, keep room for it.
    $reserve = $SystemReserveGB + $(if ($WithClient -and -not $clientRunning) { $ClientReserveGB } else { 0 })
    return $free - $reserve
}
function Free-CommitGB {
    # RAM + page file still available to new processes, minus the system reserve.
    return (Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory / 1MB - $SystemReserveGB
}
function Players-On($s) {
    $file = Join-Path $Runtime "appdata\server\netcoop_cluster\status_$($s.Port).txt"
    $line = Get-Content $file -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($line -match "^\d+ (\d+) ") { return [int]$Matches[1] }
    return 0
}
$idleSince = @{}
# Make room for one more server: stop the on-demand server empty for longest.
function Make-Room($need) {
    while ((Free-BudgetGB) -lt $need) {
        $victim = $null
        foreach ($s in $servers) {
            $p = $running[$s.Name]
            if ((Get-ClusterHostMode $wakeDir $s.Name) -eq "on" -or -not $s.OnDemand -or -not $p -or $p.HasExited -or (Players-On $s) -gt 0 -or -not $idleSince[$s.Name]) { continue }
            if (-not $victim -or $idleSince[$s.Name] -lt $idleSince[$victim.Name]) { $victim = $s }
        }
        if (-not $victim) { return $false }
        Write-Host ("{0:HH:mm:ss} memory short: stopping empty {1}" -f (Get-Date), $victim.Name)
        Request-ClusterSavedStop $wakeDir $victim.Port $running[$victim.Name].Id
        # Do not reclaim memory before the server acknowledges its saved exit.
        # Retry the requested launch next cycle; no forced world termination.
        $victim.State = 'saving'
        Publish-HostState
        return $false
    }
    return $true
}

Write-Host ("{0} map(s) on this machine: {1}" -f $servers.Count, (($servers | ForEach-Object { $_.Name + $(if ($_.OnDemand) { " (on demand)" } else { "" }) }) -join ", "))
$wakeDir = Join-Path $Runtime "appdata\server\netcoop_cluster"
$running = @{}
$viewFile = "host_view_$($env:COMPUTERNAME.ToLowerInvariant()).json"
# A start command not read yet (the loop is busy loading another map): queued.
function Pending-Start($s) {
    $file = Join-Path $wakeDir "host_command_$($s.Name).txt"
    if (-not (Test-Path -LiteralPath $file)) { return $false }
    try { return ([IO.File]::ReadAllText($file).Trim() -in @('start','restart')) } catch { return $false }
}
function Publish-HostState {
    try { Publish-HostStateNow } catch { Write-Host ("{0:HH:mm:ss} state not published: {1}" -f (Get-Date), $_.Exception.Message) }
}
function Publish-HostStateNow {
    $rows = @($servers | ForEach-Object {
        $process = $running[$_.Name]
        [ordered]@{ map=$_.Name; port=$_.Port; processId=$(if ($process -and -not $process.HasExited) { $process.Id } else { 0 });
            state=$(if ($_.State -and $_.State -ne 'stopped') { $_.State } elseif (-not ($process -and -not $process.HasExited) -and ((Get-ClusterHostMode $wakeDir $_.Name) -eq 'on' -or (Pending-Start $_))) { 'queued' } elseif ($_.State) { $_.State } else { 'stopped' }); mode=Get-ClusterHostMode $wakeDir $_.Name;
            players=Players-On $_; progress=Get-LoadProgress $_; exit_code=$_.LastExitCode; failures=[int]$_.Failures; retry_seconds=$(if ($_.NextStart -and -not $_.Blocked) { [math]::Max(0, [int]($_.NextStart - (Get-Date)).TotalSeconds) } else { 0 }) }
    })
    $os = Get-CimInstance Win32_OperatingSystem
    $memory = [ordered]@{ free_gb=[math]::Round($os.FreePhysicalMemory / 1MB, 1); commit_gb=[math]::Round($os.FreeVirtualMemory / 1MB, 1); need_gb=[math]::Round((Get-ClusterLaunchNeedGB), 1) }
    $view = [ordered]@{ updated=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); watchdog=$PID; memory=$memory; maps=$rows }
    Write-ClusterText (Join-Path $wakeDir $viewFile) ($view | ConvertTo-Json -Depth 4 -Compress)
}
foreach ($s in $servers) {
    # Reattach only exact runtime/port server processes after watchdog restart.
    $matchesForMap = @(Get-CimInstance Win32_Process -Filter "Name='LostZoneServerDX11.exe'" | Where-Object {
        $_.ExecutablePath -eq $exe -and $_.CommandLine -match "-netport\s+$($s.Port)(?:\s|$)"
    })
    if ($matchesForMap.Count -gt 1) { throw "Multiple servers already occupy $($s.Name)" }
    if ($matchesForMap.Count -eq 1) {
        $running[$s.Name] = Get-Process -Id $matchesForMap[0].ProcessId
        $s.State = 'loading'; $s.Loading = $true; $s.LoadStarted = $running[$s.Name].StartTime
    }
}
# Establish manual-only defaults without launching anything. All startup and
# restart requests use the same responsive, memory-budgeted queue below.
foreach ($s in $servers) {
    $mode = Get-ClusterHostMode $wakeDir $s.Name
    if ($NoAutoStart -and $mode -eq 'auto' -and -not $running[$s.Name]) {
        Write-ClusterText (Join-Path $wakeDir "host_mode_$($s.Name).txt") 'off'
    }
}
Publish-HostState
while ($true) {
    foreach ($s in $servers) {
        try { Update-ClusterLocation $s }
        catch { Write-Host ("{0:HH:mm:ss} control error for {1}: {2}" -f (Get-Date), $s.Name, $_.Exception.Message) }
    }
    Start-ClusterQueuedLocation
    Publish-HostState
    Start-Sleep -Seconds 1
}
