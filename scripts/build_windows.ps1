$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }

Push-Location $projectRoot
try {
    # PyInstaller writes progress to stderr. Collect both streams separately so a
    # caller running with ErrorActionPreference=Stop is not tripped by stderr records,
    # and so the full log is available when the build fails.
    $buildDir = Join-Path $projectRoot 'build'
    New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
    $stdoutLog = Join-Path $buildDir 'pyinstaller.out.log'
    $stderrLog = Join-Path $buildDir 'pyinstaller.err.log'

    $argumentLine = @(
        '-m PyInstaller'
        '--noconfirm'
        '--clean'
        '--onedir'
        '--windowed'
        '--name YYICToolbox'
        '--paths src'
        '--add-data "src/yyict_toolbox/resources/logo.png;resources"'
        '--add-data "src/yyict_toolbox/resources/images/xiehuiqq.png;resources/images"'
        '--icon "src/yyict_toolbox/resources/logo.ico"'
        '--distpath dist'
        '--workpath build'
        'src/yyict_toolbox/__main__.py'
    ) -join ' '

    $process = Start-Process -FilePath $python `
        -ArgumentList $argumentLine `
        -Wait -PassThru -NoNewWindow `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog
    if ($process.ExitCode -ne 0) {
        throw "PyInstaller build failed (exit code $($process.ExitCode)). See $stdoutLog and $stderrLog"
    }
} finally {
    Pop-Location
}
