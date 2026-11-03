# Сборка: лаунчер, сервер, packer (release) и веб-установщик (профиль setup — по размеру).
# Результат — в папке dist\
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
cargo build --release -p launcher -p server -p packer
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
cargo build --profile setup -p setup
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$brand = Get-Content app\brand.json -Raw -Encoding UTF8 | ConvertFrom-Json
New-Item dist -ItemType Directory -Force | Out-Null
Copy-Item target\setup\NetAnomalySetup.exe ("dist\" + ($brand.product -replace '\s', '') + "Setup.exe") -Force
Copy-Item target\release\Launcher.exe ("dist\" + $brand.exe_name) -Force
Copy-Item target\release\NetAnomalyServer.exe dist\NetAnomalyServer.exe -Force
Copy-Item target\release\packer.exe dist\packer.exe -Force
Get-ChildItem dist | Format-Table Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
Write-Host "Не забудьте опубликовать новый лаунчер: панель сервера -> Публикация версии -> Лаунчер"
