$ErrorActionPreference = 'Stop'
$creatorRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$creatorRuntime = Get-Content -LiteralPath (Join-Path $creatorRoot 'local.runtime.json') -Raw | ConvertFrom-Json
$creatorPythonw = Join-Path (Split-Path -Parent $creatorRuntime.python) 'pythonw.exe'
$creatorIcon = Join-Path $creatorRoot 'resources\icons\tt-creator.ico'
if (-not (Test-Path -LiteralPath $creatorPythonw) -or -not (Test-Path -LiteralPath $creatorIcon)) { throw '运行环境或图标不存在' }
$creatorShell = New-Object -ComObject WScript.Shell
$creatorDesktop = $creatorShell.SpecialFolders.Item('Desktop')
foreach ($creatorShortcutPath in @((Join-Path $creatorRoot '启动TT创作助手.lnk'), (Join-Path $creatorDesktop 'TT创作助手.lnk'))) {
    $creatorLink = $creatorShell.CreateShortcut($creatorShortcutPath)
    $creatorLink.TargetPath = $creatorPythonw
    $creatorLink.Arguments = '"' + (Join-Path $creatorRoot 'tools\gui_bootstrap.pyw') + '"'
    $creatorLink.WorkingDirectory = $creatorRoot
    $creatorLink.IconLocation = $creatorIcon + ',0'
    $creatorLink.Description = 'TT创作助手'
    $creatorLink.Save()
    $creatorVerified = $creatorShell.CreateShortcut($creatorShortcutPath)
    if ($creatorVerified.IconLocation -ne $creatorLink.IconLocation -or $creatorVerified.TargetPath -ne $creatorLink.TargetPath) { throw '快捷方式验证失败' }
    Write-Output ('图标已写入：' + $creatorShortcutPath)
}
