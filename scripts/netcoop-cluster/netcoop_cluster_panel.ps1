# Lost Zone — мастер (owner 2026-10-17): one window for the world master, the
# maps of this folder and the players on them. Tabs: maps, players (from the
# rosters the maps write; administrator commands go back to them through the
# shared cluster folder) and the master's console (its log + its command line).
param([string]$Runtime = $PSScriptRoot, [switch]$StartMaster, [string]$Tab = 'locations', [string]$Snapshot = '')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
. (Join-Path $PSScriptRoot 'netcoop_cluster_controls.ps1')
$Runtime = [IO.Path]::GetFullPath($Runtime)
$planPath = Join-Path $Runtime 'appdata\server\netcoop_cluster.ltx'
if (-not (Test-Path -LiteralPath $planPath)) { throw "Cluster plan missing: $planPath" }
$wakeDir = Join-Path $Runtime 'appdata\server\netcoop_cluster'
$logDir = Join-Path $Runtime 'appdata\server\logs'
# The watchdog publishes this machine's maps as host_view_<computer>.json.
$viewName = "host_view_$($env:COMPUTERNAME.ToLowerInvariant()).json"
# Each start writes its own log pair: a running watchdog keeps its files open.
$script:watchdogErr = $null
function Read-Shared([string]$Path) {
    # Read without blocking the watchdog's atomic replace of the same file.
    $stream = [IO.File]::Open($Path, 'Open', 'Read', [IO.FileShare]'ReadWrite, Delete')
    try { return [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8).ReadToEnd() } finally { $stream.Dispose() }
}
function Watchdog-Running {
    @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like '*netcoop_cluster_watchdog.ps1*' -and $_.CommandLine -like "*$Runtime*" }).Count -gt 0
}
# Ticked maps (one per line): what "Запустить" starts. Chosen by the hoster.
$checkFile = Join-Path $wakeDir 'panel_selected.txt'
$mapNames = @{
    k00_marsh='Болота'; l01_escape='Кордон'; l02_garbage='Свалка'; l03_agroprom='Агропром';
    l03u_agr_underground='Подземелья Агропрома'; l04_darkvalley='Тёмная долина'; l04u_labx18='Лаборатория X18';
    l05_bar='Бар'; l06_rostok='Дикая территория'; l07_military='Армейские склады'; l08_yantar='Янтарь';
    l08u_brainlab='Лаборатория X16'; l09_deadcity='Мёртвый город'; l10_limansk='Лиманск';
    l10_radar='Радар'; l10_red_forest='Рыжий лес'; l10u_bunker='Лаборатория X19'; l11_hospital='Госпиталь';
    l11_pripyat='Припять'; l12_stancia='ЧАЭС'; l12_stancia_2='ЧАЭС — север'; l12u_control_monolith='Управление Монолитом';
    l12u_sarcofag='Саркофаг'; l13_generators='Генераторы'; l13u_warlab='Лаборатория X7'; labx8='Лаборатория X8';
    jupiter='Юпитер'; jupiter_underground='Путепровод'; pripyat='Восточная Припять';
    zaton='Затон'; k01_darkscape='Тёмная лощина'; k02_trucks_cemetery='Кладбище техники'; y04_pole='Луга'
}
# Every location is ready to start (owner 2026-10-12): maps missing from the
# hoster's plan are added from the full template with the host he set for his
# own maps (his external address stays) and start when a player heads there.
function Read-Plan([string]$Path) {
    $data = [ordered]@{}; $current = ''
    foreach ($line in Get-Content -LiteralPath $Path -Encoding Default) {
        $text = ($line -split ';',2)[0].Trim()
        if ($text -match '^\[(.+)\]$') { $current = $Matches[1]; if (-not $data.Contains($current)) { $data[$current] = [ordered]@{} }; continue }
        if ($current -and $text -match '^([\w.]+)\s*=\s*(.*)$') { $data[$current][$Matches[1]] = $Matches[2].Trim() }
    }
    return $data
}
function Merge-Plan {
    $template = Join-Path $PSScriptRoot 'netcoop_cluster.ltx.full'
    if (-not (Test-Path -LiteralPath $template)) { return 0 }
    $plan = Read-Plan $planPath; $full = Read-Plan $template
    foreach ($name in @('cluster','locations','launch','on_demand')) { if (-not $plan.Contains($name)) { $plan[$name] = [ordered]@{} } }
    $missing = @($full['locations'].Keys | Where-Object { -not $plan['locations'].Contains($_) })
    if (-not $missing.Count) { return 0 }
    $hosts = @($plan['locations'].Values | ForEach-Object { ($_ -split ':')[0] } | Group-Object | Sort-Object Count -Descending)
    $hostName = if ($hosts.Count) { $hosts[0].Name } else { '127.0.0.1' }
    $used = @{}; foreach ($address in $plan['locations'].Values) { $p = 0; if ([int]::TryParse(($address -split ':')[-1], [ref]$p)) { $used[$p] = $true; $used[$p + 1] = $true } }
    foreach ($map in $missing) {
        $port = [int](($full['locations'][$map] -split ':')[-1])
        while ($used[$port] -or $used[$port + 1]) { $port += 2 }
        $used[$port] = $true; $used[$port + 1] = $true
        $plan['locations'][$map] = "${hostName}:$port"
        if (-not $plan['launch'].Contains($map) -and $full['launch'].Contains($map)) { $plan['launch'][$map] = $full['launch'][$map] }
        if (-not $plan['on_demand'].Contains($map)) { $plan['on_demand'][$map] = '1' }
    }
    Copy-Item -LiteralPath $planPath -Destination "$planPath.before_all_maps" -Force
    $out = [Collections.Generic.List[string]]::new()
    $out.Add('; Lost Zone location plan. [locations] map = address players use : port (UDP port and port+1).')
    $out.Add('; [launch] = start point, [on_demand] 1 = starts when a player heads there. Edited by the panel.')
    foreach ($name in $plan.Keys) {
        $out.Add(''); $out.Add("[$name]")
        foreach ($key in $plan[$name].Keys) { $out.Add("$key = $($plan[$name][$key])") }
    }
    [IO.File]::WriteAllLines($planPath, $out, [Text.Encoding]::Default)
    return $missing.Count
}
$script:addedMaps = Merge-Plan

$locations = [ordered]@{}; $onDemand = @{}; $section = ''
foreach ($line in Get-Content -LiteralPath $planPath -Encoding Default) {
    $text = ($line -split ';',2)[0].Trim()
    if ($text -match '^\[(.+)\]$') { $section = $Matches[1]; continue }
    if ($section -eq 'locations' -and $text -match '^(\w+)\s*=\s*(\S+)$') { $locations[$Matches[1]] = $Matches[2] }
    if ($section -eq 'on_demand' -and $text -match '^(\w+)\s*=\s*1$') { $onDemand[$Matches[1]] = $true }
}
if (-not $locations.Count) { throw 'Cluster plan has no locations' }
$checked = @{}
if (Test-Path -LiteralPath $checkFile) {
    foreach ($map in Get-Content -LiteralPath $checkFile) { if ($locations.Contains($map.Trim())) { $checked[$map.Trim()] = $true } }
} else {
    # First run: every map that is not started on demand.
    foreach ($map in $locations.Keys) { if (-not $onDemand[$map]) { $checked[$map] = $true } }
}
function Save-Checked {
    [IO.Directory]::CreateDirectory($wakeDir) | Out-Null
    Write-ClusterText $checkFile ((@($locations.Keys | Where-Object { $checked[$_] }) -join "`r`n") + "`r`n")
}

# Palette: near-black surfaces, one warm accent, status colours only where they mean something.
function Rgb([int]$r,[int]$g,[int]$b) { [Drawing.Color]::FromArgb($r,$g,$b) }
$C = @{
    bg=(Rgb 10 10 11); surface=(Rgb 16 16 18); raised=(Rgb 24 24 27); hover=(Rgb 32 32 36); line=(Rgb 38 38 42)
    text=(Rgb 232 230 225); muted=(Rgb 140 140 145); dim=(Rgb 90 90 95); accent=(Rgb 217 164 65)
    green=(Rgb 76 195 138); amber=(Rgb 224 168 74); red=(Rgb 229 83 75); track=(Rgb 34 34 38)
}
$fontUi = [Drawing.Font]::new('Segoe UI', 10)
$fontSmall = [Drawing.Font]::new('Segoe UI', 9)
$fontHead = [Drawing.Font]::new('Segoe UI Semibold', 9)
$fontTitle = [Drawing.Font]::new('Bahnschrift SemiBold', 17)

# Dark window frame on Windows 10 1809+/11 (ignored where unsupported).
try {
    Add-Type -Namespace LostZone -Name Dwm -MemberDefinition '[System.Runtime.InteropServices.DllImport("dwmapi.dll")] public static extern int DwmSetWindowAttribute(System.IntPtr hwnd, int attribute, ref int value, int size);'
} catch {}

$form = [Windows.Forms.Form]::new()
$form.Text = 'Lost Zone — мастер'
$form.Size = [Drawing.Size]::new(1160,860); $form.MinimumSize = [Drawing.Size]::new(900,620)
$form.StartPosition = 'CenterScreen'; $form.BackColor = $C.bg; $form.ForeColor = $C.text; $form.Font = $fontUi
$form.Add_HandleCreated({ try { $on = 1; [void][LostZone.Dwm]::DwmSetWindowAttribute($form.Handle, 20, [ref]$on, 4) } catch {} })

$layout = [Windows.Forms.TableLayoutPanel]::new(); $layout.Dock = 'Fill'; $layout.ColumnCount = 1; $layout.RowCount = 5
$layout.Padding = [Windows.Forms.Padding]::new(24,18,24,10); $layout.BackColor = $C.bg
foreach ($height in @(64, 74, 40, -1, 26)) {
    if ($height -lt 0) { [void]$layout.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Percent,100)) }
    else { [void]$layout.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Absolute,$height)) }
}

# Header: title on the left, live summary on the right.
$header = [Windows.Forms.TableLayoutPanel]::new(); $header.Dock = 'Fill'; $header.ColumnCount = 2; $header.RowCount = 2
[void]$header.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Percent,55))
[void]$header.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Percent,45))
function New-Label([string]$Text, $Font, $Color, [string]$Align = 'MiddleLeft') {
    $label = [Windows.Forms.Label]::new(); $label.Dock = 'Fill'; $label.Text = $Text; $label.Font = $Font
    $label.ForeColor = $Color; $label.TextAlign = $Align; $label.AutoEllipsis = $true; return $label
}
$title = New-Label 'LOST ZONE' $fontTitle $C.text 'BottomLeft'
$subtitle = New-Label "Мастер мира · локации · игроки" $fontSmall $C.muted 'TopLeft'
$summary = New-Label '' ([Drawing.Font]::new('Segoe UI Semibold',11)) $C.text 'BottomRight'
$connection = New-Label '' $fontSmall $C.muted 'TopRight'
$header.Controls.Add($title,0,0); $header.Controls.Add($summary,1,0); $header.Controls.Add($subtitle,0,1); $header.Controls.Add($connection,1,1)

# World master (owner 2026-10-12: "the master server must be visible"): the
# World Service process with its own console window; the panel starts it,
# stops it and brings its console to the front. It ships with its own Python.
. (Join-Path $PSScriptRoot 'netcoop_master_control.ps1')
try {
    Add-Type -Namespace LostZone -Name Win -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr hWnd, int nCmdShow);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr hWnd);
'@
} catch {}
function Show-MasterConsole {
    foreach ($p in @(Master-Processes)) {
        foreach ($candidate in @($p.ParentProcessId, $p.ProcessId)) {
            $process = Get-Process -Id $candidate -ErrorAction SilentlyContinue
            if ($process -and $process.MainWindowHandle -ne [IntPtr]::Zero) {
                [void][LostZone.Win]::ShowWindow($process.MainWindowHandle, 9); [void][LostZone.Win]::SetForegroundWindow($process.MainWindowHandle)
                return $true
            }
        }
    }
    return $false
}
$masterCard = [Windows.Forms.TableLayoutPanel]::new(); $masterCard.Dock = 'Fill'; $masterCard.ColumnCount = 3; $masterCard.RowCount = 2
$masterCard.BackColor = $C.surface; $masterCard.Margin = [Windows.Forms.Padding]::new(0,4,0,10); $masterCard.Padding = [Windows.Forms.Padding]::new(14,6,10,6)
[void]$masterCard.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Absolute,22))
[void]$masterCard.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Percent,100))
[void]$masterCard.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::AutoSize))
[void]$masterCard.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Percent,50))
[void]$masterCard.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Percent,50))
$script:masterState = 'stopped'
$masterDot = [Windows.Forms.Panel]::new(); $masterDot.Dock = 'Fill'
$masterDot.Add_Paint({
    param($sender, $e)
    $color = @{ running=$C.green; starting=$C.amber; stopped=$C.dim; missing=$C.red }[$script:masterState]
    $e.Graphics.SmoothingMode = 'AntiAlias'
    $brush = [Drawing.SolidBrush]::new($color); $e.Graphics.FillEllipse($brush, 4, [int]($masterDot.Height / 2) - 5, 10, 10); $brush.Dispose()
})
$masterName = New-Label 'МАСТЕР МИРА' $fontHead $C.text 'BottomLeft'
$masterInfo = New-Label '' $fontSmall $C.muted 'TopLeft'
$masterButtons = [Windows.Forms.FlowLayoutPanel]::new(); $masterButtons.AutoSize = $true; $masterButtons.WrapContents = $false; $masterButtons.Dock = 'Fill'
$masterCard.Controls.Add($masterDot,0,0); $masterCard.SetRowSpan($masterDot,2)
$masterCard.Controls.Add($masterName,1,0); $masterCard.Controls.Add($masterInfo,1,1)
$masterCard.Controls.Add($masterButtons,2,0); $masterCard.SetRowSpan($masterButtons,2)
function Update-Master {
    $running = @(Master-Processes).Count -gt 0
    $listening = $running -and (Master-Listening)
    $script:masterState = if (-not (Test-Path -LiteralPath $masterPython)) { 'missing' } elseif ($listening) { 'running' } elseif ($running) { 'starting' } else { 'stopped' }
    $masterInfo.Text = switch ($script:masterState) {
        'running'  { "Работает · вход игроков: этот адрес, порт $(Entry-Port $Runtime) TCP · календарь, погода, выбросы и пси-шторма всех карт." }
        'starting' { 'Запускается…' }
        'missing'  { 'Не установлен: в hoster\master нет Python. Скопируйте папку сервера целиком.' }
        default    { 'Выключен. Без мастера карты не пускают игроков: он ведёт календарь, погоду, выбросы и пси-шторма.' }
    }
    $masterToggle.Text = if ($running) { 'Остановить мастер' } else { 'Запустить мастер' }
    $masterDot.Invalidate()
}

function New-Grid {
    $g = [Windows.Forms.DataGridView]::new(); $g.Dock = 'Fill'; $g.ReadOnly = $true
    $g.AllowUserToAddRows = $false; $g.AllowUserToDeleteRows = $false; $g.AllowUserToResizeRows = $false
    $g.MultiSelect = $false; $g.SelectionMode = 'FullRowSelect'; $g.RowHeadersVisible = $false
    $g.AutoSizeColumnsMode = 'Fill'; $g.BorderStyle = 'None'; $g.BackgroundColor = $C.bg
    $g.CellBorderStyle = 'None'; $g.GridColor = $C.line
    $g.EnableHeadersVisualStyles = $false; $g.ColumnHeadersBorderStyle = 'None'
    $g.ColumnHeadersHeightSizeMode = 'DisableResizing'; $g.ColumnHeadersHeight = 34
    $g.ColumnHeadersDefaultCellStyle.BackColor = $C.bg; $g.ColumnHeadersDefaultCellStyle.ForeColor = $C.dim
    $g.ColumnHeadersDefaultCellStyle.SelectionBackColor = $C.bg; $g.ColumnHeadersDefaultCellStyle.Font = $fontHead
    $g.DefaultCellStyle.BackColor = $C.surface; $g.DefaultCellStyle.ForeColor = $C.text
    $g.DefaultCellStyle.SelectionBackColor = $C.hover; $g.DefaultCellStyle.SelectionForeColor = $C.text
    $g.RowTemplate.Height = 40
    return ,$g
}
$grid = New-Grid
$COL_CHECK=0; $COL_DOT=1; $COL_NAME=2; $COL_STATE=3; $COL_LOAD=4; $COL_PLAYERS=5; $COL_MODE=6; $COL_ADDR=7
foreach ($column in @('','','ЛОКАЦИЯ','СОСТОЯНИЕ','ЗАГРУЗКА','ИГРОКИ','РЕЖИМ','АДРЕС')) { [void]$grid.Columns.Add("c$($grid.Columns.Count)",$column) }
$weights = @(16, 10, 130, 100, 130, 46, 96, 100)
for ($i = 0; $i -lt $weights.Count; $i++) { $grid.Columns[$i].FillWeight = $weights[$i]; $grid.Columns[$i].SortMode = 'NotSortable' }
$grid.Columns[$COL_ADDR].DefaultCellStyle.ForeColor = $C.muted; $grid.Columns[$COL_MODE].DefaultCellStyle.ForeColor = $C.muted
$grid.Columns[$COL_CHECK].ToolTipText = 'Отметить все / снять все'
$rowByMap = @{}; $stateByMap = @{}; $progressByMap = @{}
foreach ($map in $locations.Keys) {
    $name = if ($mapNames[$map]) { $mapNames[$map] } else { $map }
    $index = $grid.Rows.Add('','',$name,'Нет данных','','—','—',$locations[$map])
    $grid.Rows[$index].Tag = $map; $rowByMap[$map] = $grid.Rows[$index]; $stateByMap[$map] = 'none'; $progressByMap[$map] = 0
}
$stateColor = @{ running=$C.green; loading=$C.amber; queued=$C.amber; saving=$C.amber; memory=$C.red; loading_timeout=$C.red; retry=$C.amber; failed=$C.red; stopped=$C.dim; none=$C.dim; remote=$C.dim }
$separator = [Drawing.Pen]::new($C.line)
$grid.Add_RowPostPaint({
    param($sender, $e)
    $y = $e.RowBounds.Bottom - 1
    $e.Graphics.DrawLine($separator, $e.RowBounds.Left, $y, $e.RowBounds.Right, $y)
})
$grid.Add_CellPainting({
    param($sender, $e)
    if ($e.RowIndex -lt 0) {
        if ($e.ColumnIndex -eq $COL_CHECK) {
            # Header tick: all / some / none ticked.
            $e.PaintBackground($e.ClipBounds, $false)
            $all = @($locations.Keys | Where-Object { $checked[$_] }).Count
            $state = if ($all -eq $locations.Count) { 2 } elseif ($all) { 1 } else { 0 }
            Draw-Tick $e.Graphics $e.CellBounds $state
            $e.Handled = $true
        }
        return
    }
    $map = [string]$grid.Rows[$e.RowIndex].Tag
    if ($e.ColumnIndex -eq $COL_CHECK) {
        $e.PaintBackground($e.ClipBounds, $true)
        Draw-Tick $e.Graphics $e.CellBounds $(if ($checked[$map]) { 2 } else { 0 })
        $e.Handled = $true
    } elseif ($e.ColumnIndex -eq $COL_DOT) {
        $e.PaintBackground($e.ClipBounds, $true)
        $color = if ($stateColor[$stateByMap[$map]]) { $stateColor[$stateByMap[$map]] } else { $C.dim }
        $size = 9; $x = $e.CellBounds.X + [int](($e.CellBounds.Width - $size) / 2); $y = $e.CellBounds.Y + [int](($e.CellBounds.Height - $size) / 2)
        $e.Graphics.SmoothingMode = 'AntiAlias'
        $brush = [Drawing.SolidBrush]::new($color); $e.Graphics.FillEllipse($brush, $x, $y, $size, $size); $brush.Dispose()
        $e.Handled = $true
    } elseif ($e.ColumnIndex -eq $COL_LOAD) {
        # Load bar like the launcher's: thin track, accent fill, percent on the right.
        $e.PaintBackground($e.ClipBounds, $true)
        $state = $stateByMap[$map]; $pct = [int]$progressByMap[$map]
        $text = switch ($state) { 'running' { 'готово' } 'loading' { "$pct%" } 'queued' { 'в очереди' } default { '' } }
        $b = $e.CellBounds; $textWidth = 70
        if ($state -in @('running','loading','queued')) {
            $track = [Drawing.Rectangle]::new($b.X + 4, $b.Y + [int]($b.Height / 2) - 2, [math]::Max(10, $b.Width - $textWidth - 12), 4)
            $brush = [Drawing.SolidBrush]::new($C.track); $e.Graphics.FillRectangle($brush, $track); $brush.Dispose()
            $fill = if ($state -eq 'running') { $track.Width } else { [int]($track.Width * [math]::Min(100, $pct) / 100) }
            if ($fill -gt 0) {
                $brush = [Drawing.SolidBrush]::new($(if ($state -eq 'running') { $C.green } else { $C.accent }))
                $e.Graphics.FillRectangle($brush, $track.X, $track.Y, $fill, $track.Height); $brush.Dispose()
            }
        }
        if ($text) {
            $rect = [Drawing.Rectangle]::new($b.Right - $textWidth - 4, $b.Y, $textWidth, $b.Height)
            [Windows.Forms.TextRenderer]::DrawText($e.Graphics, $text, $fontSmall, $rect, $(if ($state -eq 'running') { $C.green } else { $C.muted }), [Windows.Forms.TextFormatFlags]'Right, VerticalCenter')
        }
        $e.Handled = $true
    }
})
function Draw-Tick($g, $bounds, [int]$state) {
    $size = 16; $x = $bounds.X + [int](($bounds.Width - $size) / 2); $y = $bounds.Y + [int](($bounds.Height - $size) / 2)
    $g.SmoothingMode = 'AntiAlias'
    $box = [Drawing.Rectangle]::new($x, $y, $size, $size)
    if ($state -gt 0) {
        $brush = [Drawing.SolidBrush]::new($C.accent); $g.FillRectangle($brush, $box); $brush.Dispose()
        $pen = [Drawing.Pen]::new((Rgb 20 14 4), 2)
        if ($state -eq 2) { $g.DrawLines($pen, [Drawing.Point[]]@([Drawing.Point]::new($x+4,$y+8), [Drawing.Point]::new($x+7,$y+11), [Drawing.Point]::new($x+12,$y+5))) }
        else { $g.DrawLine($pen, $x+4, $y+8, $x+12, $y+8) }
        $pen.Dispose()
    } else {
        $brush = [Drawing.SolidBrush]::new($C.bg); $g.FillRectangle($brush, $box); $brush.Dispose()
        $pen = [Drawing.Pen]::new((Rgb 70 70 76), 1); $g.DrawRectangle($pen, $x, $y, $size - 1, $size - 1); $pen.Dispose()
    }
}
# Tick by clicking the box (or anywhere in its column), the header ticks all; Space ticks the selected row.
$grid.Add_CellMouseClick({
    param($sender, $e)
    if ($e.Button -ne 'Left' -or $e.ColumnIndex -ne $COL_CHECK) { return }
    if ($e.RowIndex -lt 0) {
        $tickAll = @($locations.Keys | Where-Object { $checked[$_] }).Count -ne $locations.Count
        foreach ($map in $locations.Keys) { $checked[$map] = $tickAll }
    } else {
        $map = [string]$grid.Rows[$e.RowIndex].Tag; $checked[$map] = -not $checked[$map]
    }
    Save-Checked; Update-Summary; $grid.Invalidate()
})
$grid.Add_KeyDown({
    param($sender, $e)
    if ($e.KeyCode -eq 'Space' -and $grid.SelectedRows.Count) {
        $map = [string]$grid.SelectedRows[0].Tag; $checked[$map] = -not $checked[$map]
        Save-Checked; Update-Summary; $grid.Invalidate(); $e.Handled = $true
    }
})

# Overall progress, like the launcher's bar.
$progressPanel = [Windows.Forms.TableLayoutPanel]::new(); $progressPanel.Dock = 'Fill'; $progressPanel.ColumnCount = 2; $progressPanel.RowCount = 2
[void]$progressPanel.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Percent,100))
[void]$progressPanel.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Absolute,80))
[void]$progressPanel.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Absolute,30))
[void]$progressPanel.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Absolute,14))
$progressText = New-Label '' $fontUi $C.text 'BottomLeft'
$progressPct = New-Label '' ([Drawing.Font]::new('Segoe UI Semibold',10)) $C.accent 'BottomRight'
$bar = [Windows.Forms.Panel]::new(); $bar.Dock = 'Fill'; $bar.Margin = [Windows.Forms.Padding]::new(0,6,0,2)
$script:barValue = 0; $script:barDone = $false
$bar.Add_Paint({
    param($sender, $e)
    $r = $bar.ClientRectangle
    $brush = [Drawing.SolidBrush]::new($C.track); $e.Graphics.FillRectangle($brush, $r); $brush.Dispose()
    $w = [int]($r.Width * [math]::Min(100, $script:barValue) / 100)
    if ($w -gt 0) { $brush = [Drawing.SolidBrush]::new($(if ($script:barDone) { $C.green } else { $C.accent })); $e.Graphics.FillRectangle($brush, 0, 0, $w, $r.Height); $brush.Dispose() }
})
$progressPanel.Controls.Add($progressText,0,0); $progressPanel.Controls.Add($progressPct,1,0); $progressPanel.Controls.Add($bar,0,1)
$progressPanel.SetColumnSpan($bar, 2)

# Actions: one primary button, quiet secondary ones, utilities on the right.
function New-Button([string]$Text, [bool]$Primary = $false) {
    $button = [Windows.Forms.Button]::new(); $button.Text = $Text; $button.AutoSize = $true
    $button.MinimumSize = [Drawing.Size]::new(118,38); $button.Padding = [Windows.Forms.Padding]::new(12,0,12,0)
    $button.Margin = [Windows.Forms.Padding]::new(0,12,8,0); $button.FlatStyle = 'Flat'; $button.Cursor = [Windows.Forms.Cursors]::Hand
    $button.FlatAppearance.BorderSize = 1; $button.Font = [Drawing.Font]::new('Segoe UI Semibold',10)
    if ($Primary) {
        $button.BackColor = $C.accent; $button.ForeColor = (Rgb 20 14 4); $button.FlatAppearance.BorderColor = $C.accent
        $button.FlatAppearance.MouseOverBackColor = (Rgb 233 184 88); $button.FlatAppearance.MouseDownBackColor = (Rgb 196 146 52)
    } else {
        $button.BackColor = $C.raised; $button.ForeColor = $C.text; $button.FlatAppearance.BorderColor = $C.line
        $button.FlatAppearance.MouseOverBackColor = $C.hover; $button.FlatAppearance.MouseDownBackColor = $C.line
    }
    return $button
}
$actions = [Windows.Forms.TableLayoutPanel]::new(); $actions.Dock = 'Fill'; $actions.ColumnCount = 2; $actions.RowCount = 1
[void]$actions.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Percent,100))
[void]$actions.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::AutoSize))
$left = [Windows.Forms.FlowLayoutPanel]::new(); $left.Dock = 'Fill'; $left.WrapContents = $false
$right = [Windows.Forms.FlowLayoutPanel]::new(); $right.AutoSize = $true; $right.WrapContents = $false; $right.Dock = 'Fill'

$script:localMaps = @{}; $script:fresh = $false
# Management (the watchdog) starts by itself when an action needs it.
function Connect-Management {
    if ($script:fresh) { return $true }
    # One watchdog per server folder: a running one reads the commands already.
    if (Watchdog-Running) { if (-not $script:watchdogStarted) { $script:watchdogStarted = Get-Date }; return $false }
    [IO.Directory]::CreateDirectory($wakeDir) | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $script:watchdogErr = Join-Path $wakeDir "watchdog_$stamp.err.log"
    $watchdog = Join-Path $PSScriptRoot 'netcoop_cluster_watchdog.ps1'
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$watchdog`"",'-Runtime',"`"$Runtime`"",'-NoAutoStart') -WindowStyle Hidden -RedirectStandardError $script:watchdogErr -RedirectStandardOutput (Join-Path $wakeDir "watchdog_$stamp.log")
    $script:watchdogStarted = Get-Date
    # Old logs of finished runs (files still open are skipped).
    Get-ChildItem -LiteralPath $wakeDir -Filter 'watchdog_*.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -Skip 6 |
        ForEach-Object { try { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop } catch {} }
    return $false
}
function Send-Maps([string]$Action, [string[]]$Maps) {
    try {
        if (-not $Maps.Count) { $status.ForeColor = $C.amber; $status.Text = 'Отметьте галочками локации, которые нужно запустить.'; return }
        foreach ($map in $Maps) { Send-ClusterHostCommand $wakeDir $map $Action }
        $connected = Connect-Management
        $names = ($Maps | ForEach-Object { if ($mapNames[$_]) { $mapNames[$_] } else { $_ } }) -join ', '
        $verb = @{ start='Запуск'; stop='Остановка (с сохранением мира)'; restart='Перезапуск'; auto='Автоматический режим' }[$Action]
        $status.ForeColor = $C.muted
        $status.Text = "$verb`: $names." + $(if ($connected) { '' } else { ' Подключаю управление...' })
    } catch { $status.ForeColor = $C.red; $status.Text = $_.Exception.Message }
}
function Checked-Maps { @($locations.Keys | Where-Object { $checked[$_] }) }
$start = New-Button 'Запустить отмеченные' $true
$start.Add_Click({
    # The world master comes up with the maps (they run without it as well).
    if ((Master-Available) -and -not @(Master-Processes).Count) { try { [void](Start-Master $Runtime @($locations.Keys)) } catch { $status.ForeColor = $C.red; $status.Text = $_.Exception.Message } }
    # Already running maps stay as they are; queued ones load one after another.
    Send-Maps 'start' @(Checked-Maps | Where-Object { $stateByMap[$_] -notin @('running','loading','queued') })
    if (-not @(Checked-Maps | Where-Object { $stateByMap[$_] -notin @('running','loading','queued') }).Count -and @(Checked-Maps).Count) {
        $status.ForeColor = $C.muted; $status.Text = 'Все отмеченные локации уже запущены или в очереди.'
    }
})
$stop = New-Button 'Остановить отмеченные'
$stop.Add_Click({ Send-Maps 'stop' @(Checked-Maps) })
$restart = New-Button 'Перезапустить отмеченные'
$restart.Add_Click({ Send-Maps 'restart' @(Checked-Maps) })
foreach ($b in @($start, $stop, $restart)) { [void]$left.Controls.Add($b) }
$masterToggle = New-Button 'Запустить мастер'; $masterToggle.Margin = [Windows.Forms.Padding]::new(0,6,8,0)
$masterToggle.Add_Click({
    try {
        $message = if (@(Master-Processes).Count) {
            $running = @($locations.Keys | Where-Object { $stateByMap[$_] -in @('running','loading') }).Count
            if ($running -and [Windows.Forms.MessageBox]::Show($form, "Без мастера карты перестанут пускать игроков, погода и выбросы остановятся. Остановить мастер?", 'Lost Zone', 'YesNo', 'Warning') -ne 'Yes') { 'Мастер оставлен работать.' }
            else { Stop-Master }
        } else { Start-Master $Runtime @($locations.Keys) }
        $status.ForeColor = $C.muted; $status.Text = $message; Update-Master
    } catch { $status.ForeColor = $C.red; $status.Text = $_.Exception.Message }
})
$masterShow = New-Button 'Консоль мастера'; $masterShow.Margin = [Windows.Forms.Padding]::new(0,6,0,0)
$masterShow.Add_Click({ Select-Tab 'console' })
[void]$masterButtons.Controls.Add($masterToggle); [void]$masterButtons.Controls.Add($masterShow)
$logs = New-Button 'Логи'
$logs.Add_Click({
    try { [IO.Directory]::CreateDirectory($logDir) | Out-Null; Start-Process -FilePath 'explorer.exe' -ArgumentList "`"$logDir`"" }
    catch { $status.ForeColor = $C.red; $status.Text = $_.Exception.Message }
})
[void]$right.Controls.Add($logs)
$actions.Controls.Add($left,0,0); $actions.Controls.Add($right,1,0)

# Right click on a row: actions for that one map.
$menu = [Windows.Forms.ContextMenuStrip]::new(); $menu.ShowImageMargin = $false
$menu.BackColor = $C.raised; $menu.ForeColor = $C.text; $menu.Font = $fontUi
foreach ($entry in @(@('start','Запустить'),@('stop','Остановить'),@('restart','Перезапустить'),@('auto','Автоматически (по переходам игроков)'))) {
    $item = $menu.Items.Add($entry[1]); $item.Tag = $entry[0]; $item.ForeColor = $C.text
    $item.Add_Click({ if ($grid.SelectedRows.Count) { Send-Maps ([string]$this.Tag) @([string]$grid.SelectedRows[0].Tag) } })
}
$grid.Add_CellMouseDown({
    param($sender, $e)
    if ($e.Button -eq 'Right' -and $e.RowIndex -ge 0) { $grid.ClearSelection(); $grid.Rows[$e.RowIndex].Selected = $true }
})
$grid.ContextMenuStrip = $menu

$status = New-Label 'Отметьте локации галочками и нажмите «Запустить отмеченные». Правая кнопка мыши — действие для одной карты.' $fontSmall $C.muted

# ---- tabs ----------------------------------------------------------------
$pages = [Windows.Forms.Panel]::new(); $pages.Dock = 'Fill'; $pages.BackColor = $C.bg
$tabBar = [Windows.Forms.FlowLayoutPanel]::new(); $tabBar.Dock = 'Fill'; $tabBar.WrapContents = $false; $tabBar.BackColor = $C.bg
$script:tabs = [ordered]@{}; $script:currentTab = ''
function New-Tab([string]$Key, [string]$Text, $Page) {
    $b = [Windows.Forms.Button]::new(); $b.Text = $Text; $b.AutoSize = $true; $b.FlatStyle = 'Flat'; $b.FlatAppearance.BorderSize = 0
    $b.Font = [Drawing.Font]::new('Segoe UI Semibold', 11); $b.ForeColor = $C.muted; $b.BackColor = $C.bg
    $b.Margin = [Windows.Forms.Padding]::new(0,2,22,0); $b.Padding = [Windows.Forms.Padding]::new(0,0,0,0); $b.Cursor = [Windows.Forms.Cursors]::Hand
    $b.FlatAppearance.MouseOverBackColor = $C.bg; $b.FlatAppearance.MouseDownBackColor = $C.bg
    $b.Tag = $Key; $b.Add_Click({ Select-Tab ([string]$this.Tag) })
    $Page.Dock = 'Fill'; $Page.Visible = $false; $pages.Controls.Add($Page)
    $script:tabs[$Key] = @{ button = $b; page = $Page }; [void]$tabBar.Controls.Add($b)
}
function Select-Tab([string]$Key) {
    if (-not $script:tabs.Contains($Key)) { $Key = 'locations' }
    foreach ($k in $script:tabs.Keys) {
        $on = $k -eq $Key; $t = $script:tabs[$k]
        $t.page.Visible = $on; $t.button.ForeColor = if ($on) { $C.accent } else { $C.muted }
    }
    $script:currentTab = $Key
    if ($Key -eq 'console') { [void]$consoleInput.Focus() }
}

# ---- maps ------------------------------------------------------------------
$locPage = [Windows.Forms.TableLayoutPanel]::new(); $locPage.ColumnCount = 1; $locPage.RowCount = 3; $locPage.BackColor = $C.bg
[void]$locPage.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Percent,100))
[void]$locPage.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Absolute,54))
[void]$locPage.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Absolute,60))
$locPage.Controls.Add($grid,0,0); $locPage.Controls.Add($progressPanel,0,1); $locPage.Controls.Add($actions,0,2)

# ---- players ---------------------------------------------------------------
# Every running map lists its players (players_<port>.txt, every 2 s); an
# action goes to the map the player is on (command_<port>.txt), where the
# server runs it as its own console's administrator command.
$playersPage = [Windows.Forms.TableLayoutPanel]::new(); $playersPage.ColumnCount = 1; $playersPage.RowCount = 2; $playersPage.BackColor = $C.bg
[void]$playersPage.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Percent,100))
[void]$playersPage.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Absolute,60))
$playersGrid = New-Grid
foreach ($column in @('ИГРОК','ПЕРСОНАЖ','ЛОКАЦИЯ','ФРАКЦИЯ','РОЛЬ','ПИНГ')) { [void]$playersGrid.Columns.Add("p$($playersGrid.Columns.Count)",$column) }
$pweights = @(110, 130, 110, 90, 70, 50)
for ($i = 0; $i -lt $pweights.Count; $i++) { $playersGrid.Columns[$i].FillWeight = $pweights[$i] }
$playersGrid.Columns[5].DefaultCellStyle.ForeColor = $C.muted
$playersGrid.Add_RowPostPaint({
    param($sender, $e)
    $y = $e.RowBounds.Bottom - 1
    $e.Graphics.DrawLine($separator, $e.RowBounds.Left, $y, $e.RowBounds.Right, $y)
})
$portToMap = @{}
foreach ($map in $locations.Keys) { $p = 0; if ([int]::TryParse(($locations[$map] -split ':')[-1], [ref]$p)) { $portToMap[$p] = $map } }
$roles = @{ admin = 'Админ'; leader = 'Лидер'; player = 'Игрок' }
function Refresh-Players {
    $selected = if ($playersGrid.SelectedRows.Count) { $playersGrid.SelectedRows[0].Tag.login } else { $null }
    $rows = [Collections.Generic.List[object]]::new()
    foreach ($file in @(Get-ChildItem -LiteralPath $wakeDir -Filter 'players_*.txt' -ErrorAction SilentlyContinue)) {
        if (((Get-Date) - $file.LastWriteTime).TotalSeconds -gt 15) { continue } # that map stopped
        $port = 0; if (-not [int]::TryParse(($file.BaseName -replace '^players_',''), [ref]$port)) { continue }
        $map = $portToMap[$port]
        $text = try { Read-Shared $file.FullName } catch { '' }
        foreach ($line in ($text -split "`r?`n")) {
            $f = $line -split '\|'
            if ($f.Count -lt 6 -or -not $f[0]) { continue }
            $rows.Add([pscustomobject]@{ login = $f[0]; name = $f[1]; slot = $f[2]; faction = $f[3]; role = $f[4]; ping = $f[5]; port = $port; map = $map })
        }
    }
    $playersGrid.SuspendLayout(); $playersGrid.Rows.Clear()
    foreach ($r in ($rows | Sort-Object map, login)) {
        $mapName = if ($r.map -and $mapNames[$r.map]) { $mapNames[$r.map] } elseif ($r.map) { $r.map } else { "порт $($r.port)" }
        $roleName = if ($roles[$r.role]) { $roles[$r.role] } else { $r.role }
        $index = $playersGrid.Rows.Add($r.login, $r.name, $mapName, $r.faction, $roleName, "$($r.ping) мс")
        $playersGrid.Rows[$index].Tag = $r
        if ($r.role -eq 'admin') { $playersGrid.Rows[$index].Cells[4].Style.ForeColor = $C.accent }
        if ($selected -and $r.login -eq $selected) { $playersGrid.Rows[$index].Selected = $true }
    }
    $playersGrid.ResumeLayout()
    $script:tabs['players'].button.Text = "Игроки · $($rows.Count)"
    $script:rosterCount = $rows.Count
    try { Update-Summary } catch {}
}
function Send-PlayerCommand([string]$Command, [int]$Port) {
    [IO.Directory]::CreateDirectory($wakeDir) | Out-Null
    [IO.File]::AppendAllText((Join-Path $wakeDir "command_$Port.txt"), "$Command`r`n", [Text.Encoding]::ASCII)
}
function Player-Action([string]$Kind) {
    if (-not $playersGrid.SelectedRows.Count) { $status.ForeColor = $C.amber; $status.Text = 'Выберите игрока в списке.'; return }
    $r = $playersGrid.SelectedRows[0].Tag
    $faction = if ($r.faction) { $r.faction } else { 'stalker' }
    $command, $text = switch ($Kind) {
        'ban'      { "sv_ban $($r.login)", "Бан $($r.login): отключён и не войдёт ни на одну карту (по аккаунту и компьютеру)." }
        'admin'    { "sv_account_role $($r.login) admin", "$($r.login) — администратор." }
        'unadmin'  { "sv_account_role $($r.login) player", "$($r.login) — обычный игрок." }
        'leader'   { "sv_leader $($r.login) $($r.slot) $faction", "$($r.login) — лидер фракции $faction." }
        'unleader' { "sv_leader $($r.login) $($r.slot) off", "$($r.login) больше не лидер." }
    }
    if ($Kind -eq 'ban' -and [Windows.Forms.MessageBox]::Show($form, "Забанить $($r.login)? Он будет отключён и не сможет войти с этого аккаунта и компьютера.", 'Lost Zone', 'YesNo', 'Warning') -ne 'Yes') { return }
    Send-PlayerCommand $command $r.port
    $status.ForeColor = $C.muted; $status.Text = $text
}
$playerActions = [Windows.Forms.FlowLayoutPanel]::new(); $playerActions.Dock = 'Fill'; $playerActions.WrapContents = $false
foreach ($entry in @(@('admin','Сделать админом'),@('unadmin','Снять админа'),@('leader','Лидер фракции'),@('unleader','Снять лидера'),@('ban','Забанить'))) {
    $b = New-Button $entry[1] ($entry[0] -eq 'ban'); $b.Tag = $entry[0]; $b.Add_Click({ Player-Action ([string]$this.Tag) }); [void]$playerActions.Controls.Add($b)
}
$unban = New-Button 'Разбанить по логину…'
$unban.Add_Click({
    Add-Type -AssemblyName Microsoft.VisualBasic
    $login = [Microsoft.VisualBasic.Interaction]::InputBox('Логин игрока, с которого снять бан:', 'Lost Zone', '')
    if (-not $login -or $login -notmatch '^[\w.\-]{3,20}$') { return }
    $running = @($portToMap.Keys | Where-Object { $stateByMap[$portToMap[$_]] -eq 'running' })
    if (-not $running.Count) { $status.ForeColor = $C.amber; $status.Text = 'Снять бан может только работающая карта: запустите хотя бы одну.'; return }
    Send-PlayerCommand "sv_unban $login" $running[0]
    $status.ForeColor = $C.muted; $status.Text = "Бан снят: $login (для всех карт)."
})
[void]$playerActions.Controls.Add($unban)
$playersPage.Controls.Add($playersGrid,0,0); $playersPage.Controls.Add($playerActions,0,1)

# ---- master console ----------------------------------------------------------
$consolePage = [Windows.Forms.TableLayoutPanel]::new(); $consolePage.ColumnCount = 1; $consolePage.RowCount = 2; $consolePage.BackColor = $C.bg
[void]$consolePage.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Percent,100))
[void]$consolePage.RowStyles.Add([Windows.Forms.RowStyle]::new([Windows.Forms.SizeType]::Absolute,48))
$fontMono = [Drawing.Font]::new('Consolas', 10)
$consoleOut = [Windows.Forms.RichTextBox]::new(); $consoleOut.Dock = 'Fill'; $consoleOut.ReadOnly = $true; $consoleOut.BorderStyle = 'None'
$consoleOut.BackColor = $C.surface; $consoleOut.ForeColor = $C.text; $consoleOut.Font = $fontMono; $consoleOut.DetectUrls = $false
$consoleOut.Margin = [Windows.Forms.Padding]::new(0,0,0,6)
$consoleRow = [Windows.Forms.TableLayoutPanel]::new(); $consoleRow.Dock = 'Fill'; $consoleRow.ColumnCount = 2; $consoleRow.RowCount = 1
[void]$consoleRow.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::Percent,100))
[void]$consoleRow.ColumnStyles.Add([Windows.Forms.ColumnStyle]::new([Windows.Forms.SizeType]::AutoSize))
$consoleInput = [Windows.Forms.TextBox]::new(); $consoleInput.Dock = 'Fill'; $consoleInput.BorderStyle = 'FixedSingle'
$consoleInput.BackColor = $C.raised; $consoleInput.ForeColor = $C.text; $consoleInput.Font = [Drawing.Font]::new('Consolas', 11)
$consoleInput.Margin = [Windows.Forms.Padding]::new(0,10,8,0)
$consoleSend = New-Button 'Выполнить' $true; $consoleSend.Margin = [Windows.Forms.Padding]::new(0,4,0,0)
$consoleRow.Controls.Add($consoleInput,0,0); $consoleRow.Controls.Add($consoleSend,1,0)
$consolePage.Controls.Add($consoleOut,0,0); $consolePage.Controls.Add($consoleRow,0,1)
function Console-Append([string]$Text, $Color) {
    if (-not $Text) { return }
    $consoleOut.SelectionStart = $consoleOut.TextLength; $consoleOut.SelectionLength = 0
    $consoleOut.SelectionColor = $Color; $consoleOut.AppendText($Text)
    if ($consoleOut.TextLength -gt 400000) { $consoleOut.Select(0, 100000); $consoleOut.ReadOnly = $false; $consoleOut.SelectedText = ''; $consoleOut.ReadOnly = $true }
    $consoleOut.SelectionStart = $consoleOut.TextLength; $consoleOut.ScrollToCaret()
}
$script:history = [Collections.Generic.List[string]]::new(); $script:historyAt = 0
function Console-Run {
    $line = $consoleInput.Text.Trim(); $consoleInput.Text = ''
    if (-not $line) { return }
    $script:history.Add($line); $script:historyAt = $script:history.Count
    Console-Append "master › $line`r`n" $C.accent
    if (-not (Master-Listening)) { Console-Append "Мастер не запущен.`r`n" $C.red; return }
    $answer = try { Master-Console $line } catch { "Команда не выполнена: $($_.Exception.Message)" }
    Console-Append (($answer -replace "`r?`n", "`r`n") + "`r`n") $C.text
}
$consoleSend.Add_Click({ Console-Run })
$consoleInput.Add_KeyDown({
    param($sender, $e)
    if ($e.KeyCode -eq 'Enter') { Console-Run; $e.SuppressKeyPress = $true }
    elseif ($e.KeyCode -eq 'Up' -and $script:historyAt -gt 0) { $script:historyAt--; $consoleInput.Text = $script:history[$script:historyAt]; $consoleInput.SelectionStart = $consoleInput.TextLength; $e.SuppressKeyPress = $true }
    elseif ($e.KeyCode -eq 'Down' -and $script:historyAt -lt $script:history.Count) {
        $script:historyAt++; $consoleInput.Text = if ($script:historyAt -lt $script:history.Count) { $script:history[$script:historyAt] } else { '' }
        $consoleInput.SelectionStart = $consoleInput.TextLength; $e.SuppressKeyPress = $true
    }
})
# The master's own output: the newest log, followed as it grows.
$script:logPath = $null; $script:logOffset = 0
function Console-Tail {
    $path = Master-LogPath $Runtime
    if (-not $path) { return }
    if ($path -ne $script:logPath) {
        $script:logPath = $path; $script:logOffset = 0
        Console-Append "─── $([IO.Path]::GetFileName($path)) ───`r`n" $C.dim
    }
    $stream = try { [IO.File]::Open($path, 'Open', 'Read', [IO.FileShare]'ReadWrite, Delete') } catch { return }
    try {
        if ($stream.Length -lt $script:logOffset) { $script:logOffset = 0 }
        if ($stream.Length -eq $script:logOffset) { return }
        [void]$stream.Seek($script:logOffset, 'Begin')
        $count = [int][math]::Min(262144, $stream.Length - $script:logOffset)
        $bytes = [byte[]]::new($count); $read = $stream.Read($bytes, 0, $count); $script:logOffset += $read
        $text = [Text.Encoding]::UTF8.GetString($bytes, 0, $read) -replace ([string][char]27 + '\[[0-9;]*m'), ''
        Console-Append ($text -replace "(?<!`r)`n", "`r`n") $C.muted
    } finally { $stream.Dispose() }
}

New-Tab 'locations' 'Локации' $locPage
New-Tab 'players' 'Игроки' $playersPage
New-Tab 'console' 'Консоль мастера' $consolePage
$layout.Controls.Add($header,0,0); $layout.Controls.Add($masterCard,0,1); $layout.Controls.Add($tabBar,0,2); $layout.Controls.Add($pages,0,3); $layout.Controls.Add($status,0,4)
$form.Controls.Add($layout)

$states=@{running='Работает';loading='Загружается';queued='В очереди';stopped='Выключена';saving='Сохраняется';memory='Ждёт память';loading_timeout='Загрузка затянулась';retry='Повтор после сбоя';failed='Остановлена после сбоев'}
$modes=@{on='Включена';off='Выключена';auto='Автоматически'}
function Update-Summary {
    $running = @($locations.Keys | Where-Object { $stateByMap[$_] -eq 'running' }).Count
    $players = 0; foreach ($row in $rowByMap.Values) { $n = 0; if ([int]::TryParse([string]$row.Cells[$COL_PLAYERS].Value, [ref]$n)) { $players += $n } }
    # The maps' own rosters are fresher than the location rows (older maps write none).
    if ($null -ne $script:rosterCount -and $script:rosterCount -gt $players) { $players = $script:rosterCount }
    $summary.Text = "Работает $running из $($locations.Count)   ·   игроков $players   ·   отмечено $(@(Checked-Maps).Count)"
    # Overall bar: the maps being brought up now (queued, loading or just finished).
    $active = @($locations.Keys | Where-Object { $stateByMap[$_] -in @('loading','queued') })
    if ($active.Count) {
        # The batch: every map that was queued or loading since this start began.
        if (-not $script:batch) { $script:batch = @{} }
        foreach ($map in $active) { $script:batch[$map] = $true }
        $batch = @($script:batch.Keys)
        $sum = 0; foreach ($map in $batch) { $sum += $(if ($stateByMap[$map] -eq 'running') { 100 } elseif ($stateByMap[$map] -eq 'loading') { [int]$progressByMap[$map] } else { 0 }) }
        $script:barValue = [int]($sum / [math]::Max(1, $batch.Count)); $script:barDone = $false
        $loading = @($batch | Where-Object { $stateByMap[$_] -eq 'loading' } | Select-Object -First 1)
        $ready = @($batch | Where-Object { $stateByMap[$_] -eq 'running' }).Count
        $now = if ($loading.Count) { "загружается $(if ($mapNames[$loading[0]]) { $mapNames[$loading[0]] } else { $loading[0] }) — $([int]$progressByMap[$loading[0]])%" } else { 'ожидание очереди' }
        $progressText.Text = "Запуск локаций: $now   ·   готово $ready из $($batch.Count)"
        $progressPct.Text = "$($script:barValue)%"
    } elseif ($script:batch -and $script:batch.Count) {
        $ready = @($script:batch.Keys | Where-Object { $stateByMap[$_] -eq 'running' }).Count
        $script:barValue = 100; $script:barDone = $true
        $progressText.Text = "Запуск завершён: работает $ready из $($script:batch.Count)"; $progressPct.Text = '100%'
        if ($ready -lt $script:batch.Count) { $script:barDone = $false }
        $script:batch = $null
    } elseif (-not $script:barDone) {
        $script:barValue = 0
        $progressText.Text = if ($running) { "Работает $running из $($locations.Count)" } else { 'Локации не запущены' }
        $progressPct.Text = ''
    }
    $bar.Invalidate()
}
$refresh = {
    try {
        $viewPath = Join-Path $wakeDir $viewName
        $view = $null
        if (Test-Path -LiteralPath $viewPath) { try { $view = Read-Shared $viewPath | ConvertFrom-Json } catch { $view = $null } }
        $script:fresh = [bool]($view -and ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-[long]$view.updated -lt 30))
        $script:localMaps = @{}
        if ($script:fresh) {
            foreach ($item in $view.maps) {
                $script:localMaps[$item.map]=$true
                $row=$rowByMap[$item.map]; if (-not $row) { continue }
                $state = [string]$item.state
                $stateByMap[$item.map] = $state
                $progressByMap[$item.map] = if ($null -ne $item.progress) { [int]$item.progress } else { 0 }
                $row.Cells[$COL_STATE].Value = if ($state -eq 'retry') { "Сбой, повтор через $($item.retry_seconds) с" } elseif ($state -eq 'failed' -and $null -ne $item.exit_code) { "Сбой, код $($item.exit_code). Нажмите Запустить" } elseif ($states[$state]) { $states[$state] } else { $state }
                $row.Cells[$COL_STATE].Style.ForeColor = if ($stateColor[$state]) { $stateColor[$state] } else { $C.text }
                $row.Cells[$COL_STATE].Style.SelectionForeColor = $row.Cells[$COL_STATE].Style.ForeColor
                $row.Cells[$COL_PLAYERS].Value = if ($item.processId) { [string]$item.players } else { '0' }
                $row.Cells[$COL_MODE].Value = $modes[[string]$item.mode]
            }
            foreach ($map in $locations.Keys) {
                if (-not $script:localMaps.ContainsKey($map)) {
                    $stateByMap[$map]='remote'; $rowByMap[$map].Cells[$COL_STATE].Value='Другой хост'
                    $rowByMap[$map].Cells[$COL_STATE].Style.ForeColor=$C.dim; $rowByMap[$map].Cells[$COL_STATE].Style.SelectionForeColor=$C.dim
                }
            }
            $connection.Text = '● управление подключено'; $connection.ForeColor = $C.green
            if ($script:watchdogStarted) {
                $script:watchdogStarted = $null
                $status.ForeColor = $C.muted; $status.Text = 'Управление подключено. Отмеченные локации запускаются по очереди — прогресс ниже.'
            }
            if (@($locations.Keys | Where-Object { $stateByMap[$_] -eq 'memory' }).Count -and $view.memory) {
                $status.ForeColor = $C.red
                $status.Text = "Не хватает памяти для запуска: свободно $($view.memory.free_gb) ГБ ОЗУ и $($view.memory.commit_gb) ГБ вместе с файлом подкачки, нужно $($view.memory.need_gb) ГБ. Закройте игру и браузер или увеличьте файл подкачки."
            }
        } else {
            foreach ($map in $locations.Keys) {
                $stateByMap[$map]='none'; $rowByMap[$map].Cells[$COL_STATE].Value='Нет связи'
                $rowByMap[$map].Cells[$COL_STATE].Style.ForeColor=$C.dim; $rowByMap[$map].Cells[$COL_STATE].Style.SelectionForeColor=$C.dim
                $rowByMap[$map].Cells[$COL_PLAYERS].Value='—'; $rowByMap[$map].Cells[$COL_MODE].Value='—'
            }
            if ($script:watchdogStarted) {
                $connection.Text = '● подключаю управление...'; $connection.ForeColor = $C.amber
            } else {
                $connection.Text = '● управление подключится при запуске'; $connection.ForeColor = $C.muted
            }
            if ($script:watchdogErr -and (Test-Path -LiteralPath $script:watchdogErr) -and (Get-Item -LiteralPath $script:watchdogErr).Length -gt 0) {
                $text = try { (Read-Shared $script:watchdogErr) -split "`r?`n" } catch { @() }
                $reason = @($text | Where-Object { $_.Trim() -and $_ -notmatch '^\s*(\+|CategoryInfo|FullyQualifiedErrorId|At |строка|At line)' }) | Select-Object -First 1
                $status.ForeColor = $C.red; $status.Text = "Управление не запустилось: $reason"
                $script:watchdogStarted = $null
            } elseif ($script:watchdogStarted -and ((Get-Date) - $script:watchdogStarted).TotalSeconds -gt 30) {
                $status.ForeColor = $C.amber; $status.Text = 'Управление не отвечает. Подробности: appdata\server\netcoop_cluster\watchdog_*.log'
                $script:watchdogStarted = $null
            }
        }
        Update-Summary
        $grid.Invalidate()
    } catch { $status.ForeColor = $C.red; $status.Text = $_.Exception.Message }
}
$timer=[Windows.Forms.Timer]::new(); $timer.Interval=1000; $timer.Add_Tick($refresh); $timer.Start()
$masterTimer=[Windows.Forms.Timer]::new(); $masterTimer.Interval=2000; $masterTimer.Add_Tick({ try { Update-Master } catch {}; try { Refresh-Players } catch {} }); $masterTimer.Start()
$consoleTimer=[Windows.Forms.Timer]::new(); $consoleTimer.Interval=700; $consoleTimer.Add_Tick({ try { Console-Tail } catch {} }); $consoleTimer.Start()
if ($script:addedMaps) { $status.ForeColor = $C.muted; $status.Text = "Добавлены все локации ($($script:addedMaps) новых, не отмечены; старый план сохранён рядом как .before_all_maps). Новые запускаются сами, когда игрок идёт туда." }
# Start Master.cmd: the master comes up with this window.
if ($StartMaster -and (Master-Available) -and -not @(Master-Processes).Count) {
    try { $status.ForeColor = $C.muted; $status.Text = Start-Master $Runtime @($locations.Keys) } catch { $status.ForeColor = $C.red; $status.Text = $_.Exception.Message }
}
Select-Tab $Tab
# -Snapshot <png>: build the window without showing it, draw it, exit (checks).
if ($Snapshot) {
    $form.ShowInTaskbar = $false; $form.Opacity = 0; $form.Show(); [Windows.Forms.Application]::DoEvents()
    & $refresh; try { Update-Master } catch {}; try { Refresh-Players } catch {}; try { Console-Tail } catch {}
    [Windows.Forms.Application]::DoEvents()
    $bmp = [Drawing.Bitmap]::new($form.Width, $form.Height)
    $form.DrawToBitmap($bmp, [Drawing.Rectangle]::new(0, 0, $form.Width, $form.Height)); $bmp.Save($Snapshot); $bmp.Dispose()
    # A RichTextBox does not draw itself into a bitmap: its text goes beside the picture.
    [IO.File]::WriteAllText("$Snapshot.console.txt", $consoleOut.Text, [Text.Encoding]::UTF8)
    foreach ($t in @($timer, $masterTimer, $consoleTimer)) { $t.Stop(); $t.Dispose() }; $form.Close(); $form.Dispose(); return
}
try { & $refresh; try { Update-Master } catch {}; try { Refresh-Players } catch {}; try { Console-Tail } catch {}; [void]$form.ShowDialog() }
finally { foreach ($t in @($timer, $masterTimer, $consoleTimer)) { $t.Stop(); $t.Dispose() }; $form.Dispose() }
