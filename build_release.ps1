[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConverterName = "Ncm" + [char]0x62D6 + [char]0x4E00 + [char]0x62D6 + ".exe"
$ConverterPath = Join-Path $RepoRoot $ConverterName
$LicensePath = Join-Path $RepoRoot "LICENSE"
$NoticesPath = Join-Path $RepoRoot "THIRD_PARTY_NOTICES.md"
$IconPngPath = Join-Path $RepoRoot "assets\app_icon.png"
$IconIcoPath = Join-Path $RepoRoot "assets\app_icon.ico"
$PythonEnv = Split-Path -Parent $PythonPath
$CondaLibraryBin = Join-Path $PythonEnv "Library\bin"
$OriginalPath = $env:PATH

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python interpreter not found: $PythonPath"
}
if (-not (Test-Path -LiteralPath $ConverterPath -PathType Leaf)) {
    throw "Bundled NCM converter not found: $ConverterPath"
}
if (-not (Test-Path -LiteralPath $LicensePath -PathType Leaf)) {
    throw "Project license not found: $LicensePath"
}
if (-not (Test-Path -LiteralPath $NoticesPath -PathType Leaf)) {
    throw "Third-party notices not found: $NoticesPath"
}
if (-not (Test-Path -LiteralPath $IconPngPath -PathType Leaf)) {
    throw "Application PNG icon not found: $IconPngPath"
}
if (-not (Test-Path -LiteralPath $IconIcoPath -PathType Leaf)) {
    throw "Application ICO icon not found: $IconIcoPath"
}

Push-Location $RepoRoot
try {
    if (Test-Path -LiteralPath $CondaLibraryBin -PathType Container) {
        $env:PATH = "$CondaLibraryBin;$env:PATH"
    }

    $Version = (& $PythonPath -c "from config import APP_VERSION; print(APP_VERSION)").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Version)) {
        throw "Could not read APP_VERSION with the configured interpreter."
    }

    $ArtifactName = "Music-Metadata-Perfecter-v$Version"
    & $PythonPath -m PyInstaller `
        --clean `
        --noconfirm `
        --onefile `
        --noconsole `
        --name $ArtifactName `
        --icon $IconIcoPath `
        --add-data "$ConverterPath;." `
        --add-data "$IconPngPath;assets" `
        --collect-data pykakasi `
        main.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    $ExePath = Join-Path $RepoRoot "dist\$ArtifactName.exe"
    $ZipPath = Join-Path $RepoRoot "dist\$ArtifactName-windows-x64.zip"
    $ChecksumPath = Join-Path $RepoRoot "dist\$ArtifactName-SHA256SUMS.txt"
    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
        throw "Expected executable was not created: $ExePath"
    }

    Compress-Archive `
        -LiteralPath @($ExePath, $LicensePath, $NoticesPath) `
        -DestinationPath $ZipPath `
        -CompressionLevel Optimal `
        -Force
    $HashLines = @($ExePath, $ZipPath) | ForEach-Object {
        $Hash = Get-FileHash -LiteralPath $_ -Algorithm SHA256
        "{0}  {1}" -f $Hash.Hash.ToLowerInvariant(), (Split-Path $_ -Leaf)
    }
    [System.IO.File]::WriteAllLines(
        $ChecksumPath,
        $HashLines,
        [System.Text.UTF8Encoding]::new($false)
    )

    Write-Output "Built release artifacts:"
    Write-Output "  $ExePath"
    Write-Output "  $ZipPath"
    Write-Output "  $ChecksumPath"
}
finally {
    $env:PATH = $OriginalPath
    Pop-Location
}
