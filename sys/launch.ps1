$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'python.ps1')
    $python = Get-PythonPath
    $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) { throw 'pythonw.exe not found. Install the standard Python 3.12 distribution.' }
    Start-Process -FilePath $pythonw -ArgumentList ('"{0}"' -f (Join-Path $PSScriptRoot 'app.py')) -WorkingDirectory (Split-Path -Parent $PSScriptRoot) -WindowStyle Hidden
} catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message, 'Yandex Discord Presence') | Out-Null
    exit 1
}
