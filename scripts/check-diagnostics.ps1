$ErrorActionPreference='Stop'
$temporary=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$fixture=Join-Path $temporary ('lz-diagnostics-'+[Guid]::NewGuid().ToString('N'))
try {
    $logs=Join-Path $fixture 'appdata\server\logs'
    [IO.Directory]::CreateDirectory($logs) | Out-Null
    [IO.File]::WriteAllText((Join-Path $logs 'xray_srv_l08_yantar_fixture.log'),"[diag][admission] map=l08_yantar phase=ready`r`nAuthorization: Bearer private-fixture-marker`r`npassword=private-fixture-marker`r`n")
    [IO.File]::WriteAllText((Join-Path $fixture 'appdata\server\netcoop_accounts.txt'),'private-fixture-marker')
    $master=Join-Path $fixture 'appdata\master'
    [IO.Directory]::CreateDirectory($master) | Out-Null
    [IO.File]::WriteAllText((Join-Path $master 'config.json'),'private-fixture-marker')
    & (Join-Path $PSScriptRoot 'dist\CollectDiagnostics.ps1') -Root $fixture | Out-Null
    $zip=Get-ChildItem -LiteralPath (Join-Path $fixture 'appdata\diagnostics') -Filter '*.zip' | Select-Object -First 1
    if (-not $zip) {throw 'Diagnostic ZIP missing'}
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive=[IO.Compression.ZipFile]::OpenRead($zip.FullName)
    try {
        $seen=$false
        foreach ($entry in $archive.Entries) {
            if ($entry.FullName -match 'accounts|config\.json|\.sqlite|\.key|\.secret') {throw 'Private file collected'}
            $reader=New-Object IO.StreamReader($entry.Open())
            try {$text=$reader.ReadToEnd()} finally {$reader.Dispose()}
            if ($text -match 'private-fixture-marker') {throw 'Credential-bearing line collected'}
            if ($text -match 'phase=ready') {$seen=$true}
        }
        if (-not $seen) {throw 'Useful diagnostic line lost'}
    } finally {$archive.Dispose()}
    Write-Output 'PASS actual diagnostic collector: bounded log export, useful admission detail retained, credential lines redacted, private files excluded; no game/master launched'
} finally {
    $resolved=[IO.Path]::GetFullPath($fixture)
    if (-not $resolved.StartsWith($temporary,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $resolved -Leaf) -notmatch '^lz-diagnostics-[a-f0-9]{32}$') {throw 'Unsafe fixture cleanup target'}
    if (Test-Path -LiteralPath $resolved) {Remove-Item -LiteralPath $resolved -Recurse -Force}
}
