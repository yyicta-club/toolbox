param(
    [string]$Version = ""
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not $Version) {
    $initFile = Join-Path $projectRoot 'src\yyict_toolbox\__init__.py'
    $match = Select-String -LiteralPath $initFile -Pattern '__version__\s*=\s*"([^"]+)"'
    if (-not $match) { throw "Cannot read __version__ from __init__.py" }
    $Version = $match.Matches[0].Groups[1].Value
}

# Single-file portable variant. Use its own work directory so it can coexist with
# the onedir build without invalidating each other's caches.
$buildDir = Join-Path $projectRoot 'build\portable'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$stdoutLog = Join-Path $buildDir 'pyinstaller.out.log'
$stderrLog = Join-Path $buildDir 'pyinstaller.err.log'

$argumentLine = @(
    '-m PyInstaller'
    '--noconfirm'
    '--clean'
    '--onefile'
    '--windowed'
    "--name YYICToolbox-$Version-portable"
    '--paths src'
    '--add-data "src/yyict_toolbox/resources/logo.png;resources"'
    '--add-data "src/yyict_toolbox/resources/images/xiehuiqq.png;resources/images"'
    '--icon "src/yyict_toolbox/resources/logo.ico"'
    '--distpath dist'
    "--workpath build\portable"
    'src/yyict_toolbox/__main__.py'
) -join ' '

$process = Start-Process -FilePath (Join-Path $projectRoot '.venv\Scripts\python.exe') `
    -ArgumentList $argumentLine `
    -Wait -PassThru -NoNewWindow `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog
if ($process.ExitCode -ne 0) {
    throw "PyInstaller build failed (exit code $($process.ExitCode)). See $stdoutLog and $stderrLog"
}

$portablePath = Join-Path $projectRoot "dist\YYICToolbox-$Version-portable.exe"
if (-not (Test-Path -LiteralPath $portablePath)) {
    throw "Missing $portablePath after the build"
}

$hash = (Get-FileHash -LiteralPath $portablePath -Algorithm SHA256).Hash.ToLowerInvariant()
$size = (Get-Item -LiteralPath $portablePath).Length
Write-Output "Portable: $portablePath"
Write-Output "SHA256:   $hash"
Write-Output "Size:     $size bytes"
