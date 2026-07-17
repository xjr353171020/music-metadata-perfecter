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
$PythonEnv = Split-Path -Parent $PythonPath
$CondaLibraryBin = Join-Path $PythonEnv "Library\bin"
$OriginalPath = $env:PATH

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python interpreter not found: $PythonPath"
}
if (-not (Test-Path -LiteralPath $ConverterPath -PathType Leaf)) {
    throw "Bundled NCM converter not found: $ConverterPath"
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
        --add-data "$ConverterPath;." `
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

    Compress-Archive -LiteralPath $ExePath -DestinationPath $ZipPath -CompressionLevel Optimal -Force
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
