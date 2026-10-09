param([ValidateSet('menu','migrate','status','start','stop','restart','enable','disable','sessions')][string]$Action = 'menu')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$rootPath = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $PSScriptRoot 'presence.py'
$taskName = 'YandexDiscordPresence'
$logPath = Join-Path $PSScriptRoot 'presence.log'

function Get-PresenceTask {
    $tasks = @(Get-ScheduledTask -ErrorAction Stop | Where-Object TaskName -eq $taskName)
    if ($tasks.Count) { return $tasks[0] }
    return $null
}

. (Join-Path $PSScriptRoot 'python.ps1')

function Save-PresenceTask([bool]$autostart) {
    $configPath = Join-Path $rootPath 'config.json'
    if (-not (Test-Path -LiteralPath $configPath)) { throw 'Сначала сохраните Application ID на вкладке «Подключение».' }
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$config.discord_application_id -notmatch '^\d+$') { throw 'Укажите числовой Discord Application ID в настройках.' }
    $python = Get-PythonPath
    $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) { throw "Не найден pythonw.exe рядом с $python" }
    $env:PYTHONPATH = Join-Path $PSScriptRoot '.deps'
    $dependenciesReady = $false
    try {
        & $python -c 'from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager; import pypresence, psutil' 2>$null
        $dependenciesReady = $LASTEXITCODE -eq 0
    } catch { }
    if (-not $dependenciesReady) {
        Write-Host 'Устанавливаю зависимости...'
        & $python -m pip install --target $env:PYTHONPATH -r (Join-Path $PSScriptRoot 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости.' }
    }
    $taskAction = New-ScheduledTaskAction -Execute $pythonw -Argument ('"{0}" --background' -f $scriptPath) -WorkingDirectory $PSScriptRoot
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $options = @{TaskName=$taskName; Action=$taskAction; Principal=$principal; Settings=$settings; Description='Yandex Music Discord Rich Presence'; Force=$true}
    if ($autostart) { $options.Trigger = New-ScheduledTaskTrigger -AtLogOn -User $user }
    Register-ScheduledTask @options | Out-Null
}

function Start-Presence {
    $task = Get-PresenceTask
    if (-not $task) { Save-PresenceTask $false }
    Start-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 2
    $task = Get-PresenceTask
    if ($task.State -ne 'Running') {
        if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath -Encoding UTF8 -Tail 12 }
        throw 'Фоновый процесс завершился. Подробности выше и в журнале.'
    }
    Write-Host 'Интеграция запущена в фоне.' -ForegroundColor Green
}

function Stop-Presence {
    $task = Get-PresenceTask
    if ($task -and $task.State -eq 'Running') { Stop-ScheduledTask -TaskName $taskName }
    # Also stop old manually launched copies belonging to this project only.
    $oldScriptPath = Join-Path $rootPath 'presence.py'
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" | Where-Object {
        $_.CommandLine -and ($_.CommandLine.Contains($scriptPath) -or $_.CommandLine.Contains($oldScriptPath))
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
    Write-Host 'Интеграция остановлена.'
}

function Show-Status {
    $task = Get-PresenceTask
    $running = $task -and $task.State -eq 'Running'
    $enabled = $task -and @($task.Triggers | Where-Object Enabled).Count -gt 0
    Write-Host ('Процесс: ' + $(if ($running) {'работает'} else {'остановлен'}))
    Write-Host ('Автозапуск при входе в Windows: ' + $(if ($enabled) {'включён'} else {'выключен'}))
}

function Invoke-PresenceAction([string]$selected) {
    switch ($selected) {
        'status' {
            $task = Get-PresenceTask
            @{running=[bool]($task -and $task.State -eq 'Running'); autostart=[bool]($task -and @($task.Triggers | Where-Object Enabled).Count -gt 0)} | ConvertTo-Json -Compress
        }
        'start' { Start-Presence }
        'stop' { Stop-Presence }
        'restart' { Stop-Presence; Start-Presence }
        'enable' {
            $task = Get-PresenceTask
            $wasRunning = $task -and $task.State -eq 'Running'
            if ($wasRunning) { Stop-Presence }
            Save-PresenceTask $true
            Start-Presence
            Write-Host 'Автозапуск включён.'
        }
        'disable' {
            $task = Get-PresenceTask
            if ($task) {
                $wasRunning = $task.State -eq 'Running'
                if ($wasRunning) { Stop-Presence }
                Save-PresenceTask $false
                if ($wasRunning) { Start-Presence }
            }
            Write-Host 'Автозапуск выключен.'
        }
        'migrate' {
            $task = Get-PresenceTask
            if ($task) {
                $wasRunning = $task.State -eq 'Running'
                $enabled = @($task.Triggers | Where-Object Enabled).Count -gt 0
                Stop-Presence
                Save-PresenceTask $enabled
                if ($wasRunning) { Start-Presence }
            }
        }
        'sessions' {
            $python = Get-PythonPath
            & $python $scriptPath --list-sessions
            if ($LASTEXITCODE -ne 0) { throw 'Не удалось получить медиасессии.' }
        }
    }
}

if ($Action -ne 'menu') { Invoke-PresenceAction $Action; exit }
while ($true) {
    Clear-Host
    Write-Host 'Yandex Music — Discord Rich Presence' -ForegroundColor Cyan
    try { Show-Status } catch { Write-Host $_.Exception.Message -ForegroundColor Red }
    Write-Host "`n1. Запустить`n2. Остановить`n3. Перезапустить`n4. Включить автозапуск`n5. Выключить автозапуск`n6. Открыть настройки`n7. Показать журнал`n8. Показать медиасессии`n0. Закрыть меню`n"
    $choice = Read-Host 'Выберите действие'
    if ($choice -eq '0') { break }
    try {
        switch ($choice) {
            '1' { Invoke-PresenceAction 'start' }
            '2' { Invoke-PresenceAction 'stop' }
            '3' { Invoke-PresenceAction 'restart' }
            '4' { Invoke-PresenceAction 'enable' }
            '5' { Invoke-PresenceAction 'disable' }
            '6' {
                Start-Process notepad.exe -ArgumentList ('"{0}"' -f (Join-Path $rootPath 'config.json')) -Wait
                Write-Host 'После сохранения настроек выберите «Перезапустить».'
            }
            '7' {
                if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath -Encoding UTF8 -Tail 40 }
                else { Write-Host 'Журнал пока пуст.' }
            }
            '8' { Invoke-PresenceAction 'sessions' }
            default { Write-Host 'Введите номер из меню.' }
        }
    } catch {
        Write-Host "Ошибка: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host 'При необходимости откройте журнал через пункт 7.'
    }
    Read-Host 'Нажмите Enter, чтобы вернуться в меню' | Out-Null
}
