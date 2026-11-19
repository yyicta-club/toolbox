$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }

Push-Location $projectRoot
try {
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name YYICToolbox `
        --paths src `
        --distpath dist `
        --workpath build `
        src/yyict_toolbox/__main__.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建失败（退出码 $LASTEXITCODE）"
    }
} finally {
    Pop-Location
}
