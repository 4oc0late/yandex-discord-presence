function Get-PythonPath {
    if ($env:YANDEX_PRESENCE_PYTHON) {
        if (-not (Test-Path -LiteralPath $env:YANDEX_PRESENCE_PYTHON)) {
            throw 'YANDEX_PRESENCE_PYTHON points to a missing python.exe.'
        }
        return $env:YANDEX_PRESENCE_PYTHON
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $path = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $path -and (Test-Path -LiteralPath $path)) { return $path }
        } catch { }
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) {
        try {
            $path = & $command.Source -c 'import sys; assert sys.version_info[:2] == (3, 12); print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $path -and (Test-Path -LiteralPath $path)) { return $path }
        } catch { }
    }
    # Retain compatibility with the runtime used by the original local installation.
    $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundled) { return $bundled }
    throw 'Install Python 3.12 (64-bit) with Tcl/Tk and the Python launcher, then try again.'
}
