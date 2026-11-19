$ErrorActionPreference = "Stop"
$python = if (Test-Path ".venv\Scripts\python.exe") {
    (Resolve-Path ".venv\Scripts\python.exe").Path
} else {
    "python"
}

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
