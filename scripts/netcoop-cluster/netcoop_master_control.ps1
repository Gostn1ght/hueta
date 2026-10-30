# World master control for one server folder (owner 2026-10-12): the master
# is the authority of every map - weather, emissions, psi storms and the
# calendar come from it, and maps admit no players without it.
#   . netcoop_master_control.ps1                 (functions for the panel)
#   powershell -File netcoop_master_control.ps1 -MasterRoot <server folder> -StartMaster
# The master ships as LostZoneMaster.exe with a portable Python fallback; its private config
# and world DB live in hoster\master\runtime and never leave this PC.
param([string]$MasterRoot = '', [switch]$StartMaster, [switch]$StopMaster, [switch]$InitMaster)

$masterDir = Join-Path $PSScriptRoot 'master'
$masterPython = Join-Path $masterDir 'python\python.exe'
$masterExe = Join-Path $masterDir 'LostZoneMaster.exe'
$masterConfig = Join-Path $masterDir 'runtime\config.json'
# The master in the engine (owner 2026-10-19: part of the game engine, in C++):
# the server executable with -netcoop_master, its own window, SQLite beside it.
$engineExe = Join-Path (Split-Path $PSScriptRoot -Parent) 'dedicated\LostZoneServerDX11.exe'
$engineSqlite = Join-Path (Split-Path $PSScriptRoot -Parent) 'dedicated\sqlite3.dll'
function Master-Engine {
    return (Test-Path -LiteralPath $engineExe -PathType Leaf) -and (Test-Path -LiteralPath $engineSqlite -PathType Leaf)
}
$masterPort = 38477
# GAMMA's new game: 26.10.2018 08:00 in engine game milliseconds.
$masterDefaultCalendar = 63676137600000

function Master-Processes {
    # Match exact executable paths, including both onefile bootloader processes.
    # A neighbouring hoster's directory or unrelated Python must never match.
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='LostZoneMaster.exe' OR Name='LostZoneServerDX11.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and (($_.ExecutablePath -ieq $masterExe) -or
            ($_.ExecutablePath -ieq $engineExe -and $_.CommandLine -like '*-netcoop_master*') -or
            ($_.ExecutablePath -ieq $masterPython -and $_.CommandLine -like '*lostzone*')) })
}
function Master-Available {
    return (Master-Engine) -or (Test-Path -LiteralPath $masterExe -PathType Leaf) -or (Test-Path -LiteralPath $masterPython -PathType Leaf)
}
function Master-Invocation([string[]]$Arguments) {
    if (Master-Engine) {
        if ($Arguments.Count -ge 2 -and $Arguments[0] -ceq '-m' -and $Arguments[1] -ceq 'lostzone') {
            $Arguments = @($Arguments | Select-Object -Skip 2)
        }
        return @{ File = $engineExe; Arguments = @('-netcoop_master') + $Arguments }
    }
    if (Test-Path -LiteralPath $masterExe -PathType Leaf) {
        # Existing callers use the module entry point. The packaged entry point
        # takes exactly the same CLI after removing Python's module prefix.
        if ($Arguments.Count -ge 2 -and $Arguments[0] -ceq '-m' -and $Arguments[1] -ceq 'lostzone') {
            $Arguments = @($Arguments | Select-Object -Skip 2)
        }
        return @{ File = $masterExe; Arguments = $Arguments }
    }
    return @{ File = $masterPython; Arguments = $Arguments }
}
function Master-Listening {
    $client = [Net.Sockets.TcpClient]::new()
    try { return $client.ConnectAsync('127.0.0.1', $masterPort).Wait(150) -and $client.Connected } catch { return $false } finally { $client.Dispose() }
}
function Master-Argument([string]$Argument) {
    # Start-Process joins an argument array without quoting on Windows PS 5.1.
    # Follow the CRT argv rules, including quotes and trailing backslashes.
    $escaped = [regex]::Replace($Argument, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}
function Master-Run([string[]]$Arguments) {
    $invocation = Master-Invocation $Arguments
    $encoded = (@($invocation.Arguments | ForEach-Object { Master-Argument $_ }) -join ' ')
    $process = Start-Process -FilePath $invocation.File -ArgumentList $encoded -WorkingDirectory $masterDir -WindowStyle Hidden -Wait -PassThru
    return $process.ExitCode
}
# The most advanced calendar the maps of this folder already reached (the
# old shared cluster clock files), so no map has to wait for the master.
function Master-InitialCalendar([string]$RuntimeRoot) {
    $best = [double]$masterDefaultCalendar
    $dir = Join-Path $RuntimeRoot 'appdata\server\netcoop_cluster'
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    foreach ($file in @(Get-ChildItem -LiteralPath $dir -Filter 'clock_*.txt' -ErrorAction SilentlyContinue)) {
        $parts = ((Get-Content -LiteralPath $file.FullName -TotalCount 1 -ErrorAction SilentlyContinue) -split '\s+')
        if ($parts.Count -ge 2) {
            $stamp = 0.0; $game = 0.0
            if ([double]::TryParse($parts[0], [ref]$stamp) -and [double]::TryParse($parts[1], [ref]$game) -and $game -gt $best) { $best = $game }
        }
    }
    return [string][math]::Floor($best)
}
# First start on this PC: a private configuration with an explicit world
# identity, every location of the plan and the maps' calendar.
function Initialize-Master([string]$RuntimeRoot, [string[]]$Locations) {
    if (-not (Master-Available)) { throw 'Мастер не установлен: нет hoster\master\LostZoneMaster.exe или резервного Python. Скопируйте папку сервера целиком.' }
    if (-not (Test-Path -LiteralPath $masterConfig)) {
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        $bytes = [byte[]]::new(16); $random.GetBytes($bytes)
        $worldId = [BitConverter]::ToUInt64($bytes, 0) -band [UInt64]0x3FFFFFFFFFFFFFFF; if ($worldId -eq 0) { $worldId = 1 }
        $seed = [BitConverter]::ToUInt64($bytes, 8) -band [UInt64]0x3FFFFFFFFFFFFFFF
        $arguments = @('-m','lostzone','init','--config','runtime\config.json','--world-id',"$worldId",'--seed',"$seed",
            '--initial-ms',(Master-InitialCalendar $RuntimeRoot),'--scale','10') + @($Locations | ForEach-Object { '--location'; $_ })
        $code = Master-Run $arguments
        if ($code -ne 0) { throw "Мастер не смог создать конфигурацию (код $code)." }
    }
    [IO.Directory]::CreateDirectory((Join-Path $RuntimeRoot 'appdata\server')) | Out-Null
    # Each map's own key. One run of the master per map takes seconds (33 maps
    # made every start wait minutes): only a missing key or one older than
    # the master's config is written again, then stamped as current.
    foreach ($location in $Locations) {
        $writer = Join-Path $RuntimeRoot "appdata\server\netcoop_world_writer_$location.json"
        if ((Test-Path -LiteralPath $writer) -and (Get-Item -LiteralPath $writer).LastWriteTimeUtc -ge (Get-Item -LiteralPath $masterConfig).LastWriteTimeUtc) { continue }
        $code = Master-Run @('-m','lostzone','writer-config','--config','runtime\config.json','--location',$location,'--destination',$writer,'--replace','--add-location')
        if ($code -ne 0) { throw "Мастер не смог выдать карте $location доступ к журналу (код $code)." }
        (Get-Item -LiteralPath $writer).LastWriteTimeUtc = [DateTime]::UtcNow
    }
    # The maps' key to the master: one file for every map of this folder
    # (after the maps: a map added above changes the config).
    $bridge = Join-Path $RuntimeRoot 'appdata\server\netcoop_world_bridge.json'
    $fresh = -not (Test-Path -LiteralPath $bridge) -or (Get-Item -LiteralPath $bridge).LastWriteTimeUtc -lt (Get-Item -LiteralPath $masterConfig).LastWriteTimeUtc -or
        -not (Select-String -LiteralPath $bridge -Pattern '"authority"' -Quiet)
    if ($fresh) {
        $code = Master-Run @('-m','lostzone','bridge-config','--config','runtime\config.json','--destination',$bridge,'--authority','--replace')
        if ($code -ne 0) { throw "Мастер не смог выдать картам ключ доступа (код $code)." }
        (Get-Item -LiteralPath $bridge).LastWriteTimeUtc = [DateTime]::UtcNow
    }
}
# Players enter only this machine's address (owner 2026-10-17): the master's
# public entry (TCP, [cluster] entry_port, default 5446 - owner 2026-10-25;
# 0 = off) sends them to their map. 1267, the old default, means 5446.
function Entry-Port([string]$RuntimeRoot) {
    $plan = Join-Path $RuntimeRoot 'appdata\server\netcoop_cluster.ltx'
    $section = ''
    foreach ($line in @(Get-Content -LiteralPath $plan -Encoding Default -ErrorAction SilentlyContinue)) {
        $text = ($line -split ';',2)[0].Trim()
        if ($text -match '^\[(.+)\]$') { $section = $Matches[1]; continue }
        if ($section -eq 'cluster' -and $text -match '^entry_port\s*=\s*(\d+)$') {
            $port = [int]$Matches[1]
            if ($port -eq 1267) { return 5446 }
            return $port
        }
    }
    return 5446
}
function Start-Master([string]$RuntimeRoot, [string[]]$Locations) {
    $pauseFile = Join-Path $RuntimeRoot 'appdata\server\netcoop_cluster\host_master_paused.txt'
    if (@(Master-Processes).Count) {
        if (Test-Path -LiteralPath $pauseFile) { throw 'Мастер открыт, но остановлен. Нажмите «Включить мастер» в его окне.' }
        return 'Мастер уже работает.'
    }
    Initialize-Master $RuntimeRoot $Locations
    $plan = Join-Path $RuntimeRoot 'appdata\server\netcoop_cluster.ltx'
    $entry = Entry-Port $RuntimeRoot
    $extra = if ($entry -gt 0 -and $entry -lt 65536) { " --gateway-port $entry --cluster `"$plan`"" } else { '' }
    # The master runs without a window of its own (owner 2026-10-17: the
    # master is the window "Lost Zone — мастер" with the maps and players);
    # its output goes to a log the window shows, commands go to its console.
    $logs = Join-Path $RuntimeRoot 'appdata\server\netcoop_cluster'
    [IO.Directory]::CreateDirectory($logs) | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $out = Join-Path $logs "master_$stamp.log"; $err = Join-Path $logs "master_$stamp.err.log"
    Get-ChildItem -LiteralPath $logs -Filter 'master_*.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -Skip 10 |
        ForEach-Object { try { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop } catch {} }
    if (Master-Engine) {
        # The master's own window (owner 2026-10-19); its journal is the log the panel shows.
        $gate = if ($entry -gt 0 -and $entry -lt 65536) { $entry } else { 0 }
        Start-Process -FilePath $engineExe -WorkingDirectory $masterDir -ArgumentList ('-netcoop_master window --config runtime\config.json --initialized ' +
            "--cluster `"$plan`" --gateway-port $gate --log-file `"$out`"") -WindowStyle Normal
        return 'Мастер открыт в своём окне «Lost Zone — мастер мира».'
    }
    $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUNBUFFERED = '1'
    if (Test-Path -LiteralPath $masterExe -PathType Leaf) {
        Start-Process -FilePath $masterExe -WorkingDirectory $masterDir -ArgumentList ('serve --config runtime\config.json' + $extra) -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    } else {
        Start-Process -FilePath $masterPython -WorkingDirectory $masterDir -ArgumentList ('-m lostzone serve --config runtime\config.json' + $extra) -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    }
    if (Test-Path -LiteralPath $pauseFile) { Remove-Item -LiteralPath $pauseFile -Force }
    return 'Мастер запускается: его консоль — в окне «Lost Zone — мастер».'
}
function Master-LogPath([string]$RuntimeRoot) {
    $logs = Join-Path $RuntimeRoot 'appdata\server\netcoop_cluster'
    $latest = Get-ChildItem -LiteralPath $logs -Filter 'master_*.log' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike '*.err.log' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) { return $latest.FullName } else { return $null }
}
# One console line for the master window: the master's own administrator
# credential from its private config (read here, never shown or logged).
function Master-Console([string]$Line) {
    $config = Get-Content -LiteralPath $masterConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    $token = $null
    foreach ($entry in $config.credentials.PSObject.Properties) { if ($entry.Value.role -eq 'admin') { $token = [string]$entry.Value.token; break } }
    if (-not $token) { return 'У мастера нет учётной записи администратора.' }
    $body = [Text.Encoding]::UTF8.GetBytes((@{ line = $Line } | ConvertTo-Json -Compress))
    $request = [Net.WebRequest]::Create("http://127.0.0.1:$masterPort/v1/console")
    $request.Method = 'POST'; $request.ContentType = 'application/json'; $request.Timeout = 5000
    $request.Headers['Authorization'] = "Bearer $token"
    try {
        $stream = $request.GetRequestStream(); $stream.Write($body, 0, $body.Length); $stream.Dispose()
        $response = $request.GetResponse()
        try { $reader = [IO.StreamReader]::new($response.GetResponseStream(), [Text.Encoding]::UTF8); $answer = $reader.ReadToEnd() | ConvertFrom-Json }
        finally { $response.Dispose() }
        return [string]$answer.result.text
    } catch [Net.WebException] {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        if ($code -eq 400) { return 'Команда не принята. help — список команд; остановка мастера — кнопкой.' }
        if ($code -eq 503) { return 'Мастер ещё восстанавливает мир, повторите через несколько секунд.' }
        return 'Мастер не отвечает.'
    }
}
function Stop-Master {
    $pauseFile = Join-Path (Split-Path $PSScriptRoot -Parent) 'appdata\server\netcoop_cluster\host_master_paused.txt'
    [IO.Directory]::CreateDirectory((Split-Path $pauseFile -Parent)) | Out-Null
    [IO.File]::WriteAllText($pauseFile, "paused`n", [Text.UTF8Encoding]::new($false))
    $processes = @(Master-Processes)
    if (-not $processes.Count) { return 'Мастер не запущен.' }
    # Every change is an SQLite transaction (WAL, synchronous FULL): stopping
    # the process cannot leave half a write behind.
    foreach ($p in $processes) {
        foreach ($parent in @(Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)" -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'cmd.exe' })) {
            try { Stop-Process -Id $parent.ProcessId -Force -ErrorAction Stop } catch {}
        }
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
    }
    return 'Мастер остановлен.'
}
function Plan-Locations([string]$RuntimeRoot) {
    $plan = Join-Path $RuntimeRoot 'appdata\server\netcoop_cluster.ltx'
    $section = ''; $maps = @()
    foreach ($line in @(Get-Content -LiteralPath $plan -Encoding Default -ErrorAction SilentlyContinue)) {
        $text = ($line -split ';',2)[0].Trim()
        if ($text -match '^\[(.+)\]$') { $section = $Matches[1]; continue }
        if ($section -eq 'locations' -and $text -match '^(\w+)\s*=') { $maps += $Matches[1] }
    }
    return $maps
}

if ($InitMaster) {
    # The engine master's first start from its executable: the same preparation.
    $ErrorActionPreference = 'Stop'
    try { $root = [IO.Path]::GetFullPath($MasterRoot); Initialize-Master $root (Plan-Locations $root); exit 0 }
    catch { Write-Host $_.Exception.Message; exit 1 }
}
if ($StartMaster -or $StopMaster) {
    $ErrorActionPreference = 'Stop'
    try {
        if ($StopMaster) { Stop-Master; exit 0 }
        $root = [IO.Path]::GetFullPath($MasterRoot)
        Start-Master $root (Plan-Locations $root)
        for ($i = 0; $i -lt 60 -and -not (Master-Listening); $i++) { Start-Sleep -Milliseconds 500 }
        if (Master-Listening) { 'Мастер мира работает.' } else { 'Мастер мира ещё запускается - карты подождут его.' }
    } catch { Write-Host $_.Exception.Message; exit 1 }
}
