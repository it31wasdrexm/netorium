$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

$VenvDir = if ($env:NETORIUM_RELEASE_VENV) { $env:NETORIUM_RELEASE_VENV } else { ".venv-release-win" }
$AssetDir = if ($env:NETORIUM_RELEASE_ASSET_DIR) { $env:NETORIUM_RELEASE_ASSET_DIR } else { "release-assets" }
$BuildTempDir = if ($env:NETORIUM_RELEASE_TEMP_DIR) { $env:NETORIUM_RELEASE_TEMP_DIR } else { ".netorium-release-tmp" }

New-Item -ItemType Directory -Force -Path $BuildTempDir | Out-Null
$ResolvedBuildTempDir = (Resolve-Path $BuildTempDir).Path
$env:TEMP = $ResolvedBuildTempDir
$env:TMP = $ResolvedBuildTempDir
$env:PIP_CACHE_DIR = Join-Path $ResolvedBuildTempDir "pip-cache"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $ResolvedBuildTempDir "pyinstaller-cache"
New-Item -ItemType Directory -Force -Path $env:PIP_CACHE_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:PYINSTALLER_CONFIG_DIR | Out-Null

function Get-AssetArch {
    switch ($env:PROCESSOR_ARCHITECTURE) {
        "ARM64" { return "arm64" }
        "AMD64" { return "x64" }
        default {
            if ([string]::IsNullOrWhiteSpace($env:PROCESSOR_ARCHITECTURE)) {
                return "unknown"
            }
            return $env:PROCESSOR_ARCHITECTURE.ToLowerInvariant()
        }
    }
}

function Test-PythonCandidate {
    param(
        [string] $Command,
        [string[]] $Arguments
    )

    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        return $false
    }

    & $Command @($Arguments + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")) *> $null
    return $LASTEXITCODE -eq 0
}

function Get-PythonCommand {
    if ($env:NETORIUM_PYTHON) {
        if (Test-PythonCandidate -Command $env:NETORIUM_PYTHON -Arguments @()) {
            return @{ Command = $env:NETORIUM_PYTHON; Arguments = @() }
        }

        throw "Configured NETORIUM_PYTHON is not Python 3.11+ or was not found: $env:NETORIUM_PYTHON"
    }

    $Candidates = @(
        @{ Command = "py"; Arguments = @("-3") },
        @{ Command = "python"; Arguments = @() },
        @{ Command = "python3"; Arguments = @() }
    )

    foreach ($Candidate in $Candidates) {
        if (Test-PythonCandidate -Command $Candidate.Command -Arguments $Candidate.Arguments) {
            return $Candidate
        }
    }

    throw "Python 3.11+ was not found. Install Python from python.org or set NETORIUM_PYTHON."
}

function Invoke-ReleasePython {
    param(
        [hashtable] $Python,
        [string[]] $Arguments
    )

    $Command = $Python["Command"]
    $BaseArguments = [string[]] $Python["Arguments"]
    & $Command @($BaseArguments + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $Command $(($BaseArguments + $Arguments) -join ' ')"
    }
}

function Invoke-NativeCommand {
    param(
        [string] $Command,
        [string[]] $Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $Command $($Arguments -join ' ')"
    }
}

$Python = Get-PythonCommand
Write-Host "Using Python:"
Invoke-ReleasePython -Python $Python -Arguments @("-c", "import sys; print(sys.executable + ' ' + sys.version.split()[0])")

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Invoke-ReleasePython -Python $Python -Arguments @("-m", "venv", $VenvDir)
} else {
    Write-Host "Using release venv: $VenvDir"
    Invoke-NativeCommand -Command $VenvPython -Arguments @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
}

Invoke-NativeCommand -Command $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
Invoke-NativeCommand -Command $VenvPython -Arguments @("-m", "pip", "install", "-e", ".[release]")
Invoke-NativeCommand -Command $VenvPython -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "packaging/netorium.spec")

$SourcePath = Join-Path "dist" "netorium.exe"
if (-not (Test-Path $SourcePath)) {
    throw "Expected Windows build output was not created: $SourcePath"
}

New-Item -ItemType Directory -Force -Path $AssetDir | Out-Null
$AssetName = "netorium-windows-$(Get-AssetArch).exe"
$TargetPath = Join-Path $AssetDir $AssetName
Copy-Item $SourcePath $TargetPath -Force
Write-Host "Built: $TargetPath"
