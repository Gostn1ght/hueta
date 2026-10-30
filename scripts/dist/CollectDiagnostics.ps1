param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = 'Stop'
$rootPath = [IO.Path]::GetFullPath($Root)
$stamp = [DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss_fff')
$destination = Join-Path $rootPath 'appdata\diagnostics'
$staging = Join-Path $destination ('report_' + $stamp)
New-Item -ItemType Directory -Force -Path $staging | Out-Null
$utf8 = New-Object Text.UTF8Encoding($false)
function Save-Text([string]$Name, [string]$Text) {
    [IO.File]::WriteAllText((Join-Path $staging $Name), $Text, $utf8)
}
function Redact-Lines([string]$Text) {
    # Never collect account records, credentials, request payloads or raw dumps.
    $lines = $Text -split "`r?`n"
    return (($lines | ForEach-Object {
        if ($_ -match '(?i)bearer\s|password|passwd|firebase|signing.key|private.key|salt[=:|]|hash[=:|]|device[=:|]|token[=:|"\s]') {
            '[credential-bearing line omitted]'
        } else { $_ }
    }) -join "`r`n")
}
try {
    $system = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    Save-Text 'system.json' (([ordered]@{
        collected_utc = [DateTime]::UtcNow.ToString('o'); schema = 1
        os = $system.Caption; version = $system.Version; cpu = $cpu.Name
        logical_cores = $cpu.NumberOfLogicalProcessors
        total_ram_kib = $system.TotalVisibleMemorySize; free_ram_kib = $system.FreePhysicalMemory
        free_virtual_kib = $system.FreeVirtualMemory
    }) | ConvertTo-Json)
    $processes = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^(LostZone|Anomaly|xrEngine|NetAnomaly)' -and
        $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath).StartsWith($rootPath + '\', [StringComparison]::OrdinalIgnoreCase)
    } | Select-Object ProcessId, ParentProcessId, Name, CreationDate, WorkingSetSize)
    Save-Text 'processes.json' (ConvertTo-Json -InputObject $processes)
    $ports = @((Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object State -eq 'Listen' |
        Select-Object LocalAddress, LocalPort, OwningProcess),
        (Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, OwningProcess))
    Save-Text 'ports.json' (ConvertTo-Json -InputObject $ports -Depth 4)
    $files = @()
    foreach ($relative in @('bin','dedicated')) {
        $native = Join-Path $rootPath $relative
        if (Test-Path -LiteralPath $native) {
            $files += Get-ChildItem -LiteralPath $native -File | Where-Object Extension -in '.exe','.dll' | ForEach-Object {
                [ordered]@{path = $relative + '/' + $_.Name; bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
            }
        }
    }
    Save-Text 'native-versions.json' (ConvertTo-Json -InputObject $files -Depth 3)
    $cluster = Join-Path $rootPath 'appdata\server\netcoop_cluster'
    if (Test-Path -LiteralPath $cluster) {
        Get-ChildItem -LiteralPath $cluster -File | Where-Object {
            $_.Name -match '^(admission_\d+\.json|status_\d+\.txt|host_view_native\.json|host_mode_[a-z0-9_]+\.txt|host_master_paused\.txt)$' -and $_.Length -lt 1048576
        } | ForEach-Object {Save-Text $_.Name (Redact-Lines ([IO.File]::ReadAllText($_.FullName)))}
    }
    $plan = Join-Path $rootPath 'appdata\server\netcoop_cluster.ltx'
    if (Test-Path -LiteralPath $plan) {Save-Text 'cluster-plan.ltx' (Redact-Lines ([IO.File]::ReadAllText($plan)))}
    $logs = @()
    foreach ($relative in @('appdata\master\logs','appdata\server\netcoop_cluster','appdata\server\logs','appdata\logs','appdata\player\logs')) {
        $folder = Join-Path $rootPath $relative
        if (Test-Path -LiteralPath $folder) {$logs += Get-ChildItem -LiteralPath $folder -File -Filter '*.log'}
    }
    $index = 0
    foreach ($file in ($logs | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 80)) {
        $stream = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
        try {
            $size = [int][Math]::Min(1048576, $stream.Length)
            [void]$stream.Seek(-$size, [IO.SeekOrigin]::End)
            $buffer = New-Object byte[] $size
            $got = $stream.Read($buffer, 0, $size)
            $encoding = if ($file.DirectoryName -match 'master') {$utf8} else {[Text.Encoding]::GetEncoding(1251)}
            $tail = $encoding.GetString($buffer,0,$got)
            if ($stream.Length -gt $size) {$tail = $tail.Substring([Math]::Max(0,$tail.IndexOf("`n")+1))}
            Save-Text (('{0:D2}_' -f $index) + $file.Name) (Redact-Lines $tail)
        } finally {$stream.Dispose()}
        $index++
    }
    Save-Text 'README.txt' "Offline diagnostics. No game was started. Logs are bounded tails; secret-bearing lines are removed. Private configs, databases, accounts and dumps are deliberately excluded. Compare map/PID/port/epoch/phase with the UTC collection time."
    $zip = $staging + '.zip'
    Compress-Archive -LiteralPath $staging -DestinationPath $zip -CompressionLevel Optimal
    Save-Text 'complete.txt' ([DateTime]::UtcNow.ToString('o'))
    Write-Output $zip
} catch {
    Save-Text 'collection-error.txt' ($_.Exception.GetType().FullName + ': ' + $_.Exception.Message)
    throw
}
