param([string]$PythonPath, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
try {
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
    & $PythonPath -c 'import sys, PySide6; assert sys.version_info >= (3,12), "需要 Python 3.12+"; print("Python",sys.version.split()[0],"PySide6",PySide6.__version__)'
    if ($LASTEXITCODE -ne 0) { throw 'Python / PySide6 检查失败。请在所选环境运行 python -m pip install -r requirements.txt；启动器不会自动安装。' }
    if ($CheckOnly) { exit 0 }
    & $PythonPath -m app.main
    exit $LASTEXITCODE
} catch {
    Write-Host ('启动失败：' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ('日志目录：' + (Join-Path $projectRoot 'logs'))
    exit 1
}
