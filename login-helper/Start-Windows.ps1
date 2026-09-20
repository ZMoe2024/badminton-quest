$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$questRoot = $PSScriptRoot
try {
    $questNode = $null
    $questInstalled = Get-Command node -ErrorAction SilentlyContinue
    if ($questInstalled) {
        & $questInstalled.Source -e "process.exit(Number(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)"
        if ($LASTEXITCODE -eq 0) { $questNode = $questInstalled.Source }
    }
    if (-not $questNode) {
        $questArch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { 'arm64' } else { 'x64' }
        $questVersion = 'v22.23.2'
        $questName = "node-$questVersion-win-$questArch"
        $questCache = Join-Path $env:LOCALAPPDATA 'BadmintonQuestLogin\runtime'
        $questNode = Join-Path $questCache "$questName\node.exe"
        if (-not (Test-Path -LiteralPath $questNode)) {
            Write-Host 'Preparing local runtime from nodejs.org (first run only)...'
            New-Item -ItemType Directory -Force -Path $questCache | Out-Null
            $questArchive = Join-Path $questCache "$questName.zip"
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri "https://nodejs.org/dist/$questVersion/$questName.zip" -OutFile $questArchive
            $questExpected = if ($questArch -eq 'arm64') { 'fec025a6da31757e3b6af84c5a1628e9d38442ca99a2161091d78f2fcfa35ef3' } else { '1177b4137ba5adaa56354ae40f1080c7450e8ae09cecb47da459d1c52ac99f97' }
            if ((Get-FileHash -LiteralPath $questArchive -Algorithm SHA256).Hash.ToLower() -ne $questExpected) {
                throw 'Runtime checksum mismatch. Download stopped; no code was executed.'
            }
            Expand-Archive -LiteralPath $questArchive -DestinationPath $questCache -Force
            Remove-Item -LiteralPath $questArchive
        }
    }
    & $questNode (Join-Path $questRoot 'session-helper.mjs') @args
    exit $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
