param(
    [string]$Version = "",
    [string]$Notes = "",
    [string]$MinSupported = "0.0.0",
    [switch]$SkipBuild
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

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot 'build_windows.ps1')
}

$appDir = Join-Path $projectRoot 'dist\YYICToolbox'
$executable = Join-Path $appDir 'YYICToolbox.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw "Missing $executable. Run scripts\build_windows.ps1 first."
}

# Runtime logs are local artifacts and must not ship inside the release package.
$logDir = Join-Path $appDir 'log'
if (Test-Path -LiteralPath $logDir) {
    Remove-Item -LiteralPath $logDir -Recurse -Force
}

$packageName = "YYICToolbox-$Version-win64.zip"
$packagePath = Join-Path $projectRoot "dist\$packageName"
Remove-Item -LiteralPath $packagePath -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $appDir '*') -DestinationPath $packagePath -CompressionLevel Optimal

$hash = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()
$size = (Get-Item -LiteralPath $packagePath).Length
$manifest = [ordered]@{
    version       = $Version
    notes         = $Notes
    min_supported = $MinSupported
    package       = [ordered]@{
        name   = $packageName
        sha256 = $hash
        size   = $size
    }
}
$manifestPath = Join-Path $projectRoot 'dist\manifest.json'
$manifestJson = $manifest | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($manifestPath, $manifestJson, (New-Object System.Text.UTF8Encoding($false)))

Write-Output "Package:  $packagePath"
Write-Output "Manifest: $manifestPath"
Write-Output "SHA256:   $hash"
Write-Output "Size:     $size bytes"
