param(
    [string]$Config = "config/settings.yaml",
    [string]$Universe = "",
    [string]$AsOf = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDirectory = Join-Path $ProjectRoot "data\runtime"
$LogDirectory = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $RuntimeDirectory, $LogDirectory | Out-Null

$LockPath = Join-Path $RuntimeDirectory "daily_pipeline.lock"
try {
    $LockHandle = [System.IO.File]::Open(
        $LockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch [System.IO.IOException] {
    Write-Error "Un autre pipeline quotidien est déjà en cours."
    exit 75
}

$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$LogPath = Join-Path $LogDirectory "daily_pipeline_$Timestamp.log"
try {
    Push-Location $ProjectRoot
    $Arguments = @("-m", "src.pipeline", "--config", $Config)
    if ($Universe) { $Arguments += @("--universe", $Universe) }
    if ($AsOf) { $Arguments += @("--as-of", $AsOf) }
    & python @Arguments 2>&1 | Tee-Object -FilePath $LogPath
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "Le pipeline a échoué avec le code $ExitCode. Voir $LogPath"
    }
} finally {
    Pop-Location
    $LockHandle.Dispose()
}

Write-Output "Pipeline terminé. Journal : $LogPath"

