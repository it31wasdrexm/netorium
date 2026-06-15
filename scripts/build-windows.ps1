$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

$VenvDir = if ($env:NETORIUM_RELEASE_VENV) { $env:NETORIUM_RELEASE_VENV } else { ".venv-release" }
$AssetDir = if ($env:NETORIUM_RELEASE_ASSET_DIR) { $env:NETORIUM_RELEASE_ASSET_DIR } else { "release-assets" }

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
}

$Python = Get-PythonCommand
Write-Host "Using Python:"
Invoke-ReleasePython -Python $Python -Arguments @("-c", "import sys; print(sys.executable + ' ' + sys.version.split()[0])")

Invoke-ReleasePython -Python $Python -Arguments @("-m", "venv", $VenvDir)

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e ".[release]"
& $VenvPython -m PyInstaller --noconfirm --clean packaging/netorium.spec

$SourcePath = Join-Path "dist" "netorium.exe"
if (-not (Test-Path $SourcePath)) {
    throw "Expected Windows build output was not created: $SourcePath"
}

New-Item -ItemType Directory -Force -Path $AssetDir | Out-Null
$AssetName = "netorium-windows-$(Get-AssetArch).exe"
$TargetPath = Join-Path $AssetDir $AssetName
Copy-Item $SourcePath $TargetPath -Force
Write-Host "Built: $TargetPath"
