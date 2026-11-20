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
        --add-data "src/yyict_toolbox/resources/logo.png;resources" `
        --add-data "src/yyict_toolbox/resources/images/xiehuiqq.png;resources/images" `
        --icon "src/yyict_toolbox/resources/logo.ico" `
        --distpath dist `
        --workpath build `
        --onefile `
        src/yyict_toolbox/__main__.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed (exit code $LASTEXITCODE)"
    }
} finally {
    Pop-Location
}
