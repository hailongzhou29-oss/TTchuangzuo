param([string]$PythonPath, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
try {
    Write-Host '正在检查 TT创作助手 运行环境…'
    if (-not $PythonPath) {
        $configPath = Join-Path $projectRoot 'local.runtime.json'
        if (Test-Path -LiteralPath $configPath) {
            $PythonPath = (Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json).python
        }
    }
    if (-not $PythonPath) {
        $candidate = Join-Path $projectRoot '.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $candidate) { $PythonPath = $candidate }
    }
    if (-not $PythonPath) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCommand) { $PythonPath = $pythonCommand.Source }
    }
    if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) {
        throw '未找到 Python。请用 -PythonPath 指定已有 Python 3.12+，或在 local.runtime.json 配置 python 路径。'
    }
    & $PythonPath (Join-Path $PSScriptRoot 'check_runtime.py')
    if ($LASTEXITCODE -ne 0) { throw 'Python / PySide6 检查失败。请在所选环境运行 python -m pip install -r requirements.txt；启动器不会自动安装。' }
    if ($CheckOnly) { exit 0 }
    try { $Host.UI.RawUI.WindowTitle = 'TT创作助手 · 开发版' } catch { }
    & $PythonPath -m app.main
    exit $LASTEXITCODE
} catch {
    Write-Host ('启动失败：' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ('日志目录：' + (Join-Path $projectRoot 'logs'))
    exit 1
}
