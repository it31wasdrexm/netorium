param(
    [switch] $InstallUser,
    [switch] $NoInstallUser,
    [switch] $SkipVerify
)

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
        throw "Command failed with exit code ${LASTEXITCODE}: $Command $(($BaseArguments + $Arguments) -join ' ')"
    }
}

function Invoke-NativeCommand {
    param(
        [string] $Command,
        [string[]] $Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command $($Arguments -join ' ')"
    }
}

function Get-DefaultLocalAppData {
    if ($env:LOCALAPPDATA) {
        return $env:LOCALAPPDATA
    }

    if ($env:USERPROFILE) {
        return Join-Path $env:USERPROFILE "AppData\Local"
    }

    throw "LOCALAPPDATA and USERPROFILE are not set. Set NETORIUM_BIN_DIR to choose the install directory."
}

function Normalize-PathEntry {
    param(
        [string] $PathEntry
    )

    $TrimChars = @(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    return $PathEntry.Trim().TrimEnd($TrimChars)
}

function Test-PathEntry {
    param(
        [string] $PathValue,
        [string] $PathEntry
    )

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $false
    }

    $NormalizedPathEntry = Normalize-PathEntry -PathEntry $PathEntry
    foreach ($ExistingEntry in ($PathValue -split [System.IO.Path]::PathSeparator)) {
        if ((Normalize-PathEntry -PathEntry $ExistingEntry) -ieq $NormalizedPathEntry) {
            return $true
        }
    }

    return $false
}

function Join-PathEntries {
    param(
        [string] $PathValue,
        [string] $PathEntry
    )

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $PathEntry
    }

    return "$PathValue$([System.IO.Path]::PathSeparator)$PathEntry"
}

function Add-UserPathEntry {
    param(
        [string] $PathEntry
    )

    $UserPath = [System.Environment]::GetEnvironmentVariable(
        "Path",
        [System.EnvironmentVariableTarget]::User
    )
    if (-not (Test-PathEntry -PathValue $UserPath -PathEntry $PathEntry)) {
        $NewUserPath = Join-PathEntries -PathValue $UserPath -PathEntry $PathEntry
        [System.Environment]::SetEnvironmentVariable(
            "Path",
            $NewUserPath,
            [System.EnvironmentVariableTarget]::User
        )
        Write-Host "Added to user PATH: $PathEntry"
    }

    $env:Path = Join-PathEntries -PathValue $PathEntry -PathEntry $env:Path
}

function Install-UserCommand {
    param(
        [string] $SourcePath
    )

    $DefaultLocalAppData = Get-DefaultLocalAppData
    $BinDir = if ($env:NETORIUM_BIN_DIR) {
        $env:NETORIUM_BIN_DIR
    } else {
        Join-Path $DefaultLocalAppData "Netorium\bin"
    }

    $ResolvedBinDir = (New-Item -ItemType Directory -Force -Path $BinDir).FullName
    $InstalledPath = Join-Path $ResolvedBinDir "netorium.exe"

    # Stop any running netorium processes before copying
    if (Test-Path $InstalledPath) {
        sc.exe stop NetoriumController *> $null
        sc.exe stop NetoriumAgent *> $null
        Stop-Process -Name "nssm" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "netorium" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "netorium-agent" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    $OldPath = "$InstalledPath.old"
    if (Test-Path $InstalledPath) {
        Remove-Item -Path $OldPath -Force -ErrorAction SilentlyContinue
        try {
            Rename-Item -Path $InstalledPath -NewName "netorium.exe.old" -Force -ErrorAction Stop
        } catch {
            for ($i = 0; $i -lt 5; $i++) {
                try {
                    Remove-Item -Path $InstalledPath -Force -ErrorAction Stop
                    break
                } catch {
                    Start-Sleep -Seconds 2
                }
            }
        }
    }

    $copySuccess = $false
    for ($i = 0; $i -lt 5; $i++) {
        try {
            Copy-Item $SourcePath $InstalledPath -Force -ErrorAction Stop
            $copySuccess = $true
            break
        } catch {
            if ($i -eq 4) {
                Write-Warning "Could not copy binary after 5 attempts: $_"
                Write-Warning "You may need to close all netorium.exe processes and retry."
            }
            Start-Sleep -Seconds 2
        }
    }
    Remove-Item -Path $OldPath -Force -ErrorAction SilentlyContinue

    Install-BundledNssm -TargetDir $ResolvedBinDir
    Add-UserPathEntry -PathEntry $ResolvedBinDir

    Write-Host "Installed command: $InstalledPath"
    Write-Host "Verifying installed command:"
    Invoke-NativeCommand -Command "netorium" -Arguments @("version")
    Write-Host "Run: netorium --help"
    Write-Host "If this terminal still cannot find netorium, open a new PowerShell window."
}

function Install-BundledNssm {
    param(
        [string] $TargetDir
    )

    $NssmSource = Join-Path $AssetDir "nssm.exe"
    if (-not (Test-Path $NssmSource)) {
        return
    }

    $NssmTarget = Join-Path $TargetDir "nssm.exe"
    Copy-Item $NssmSource $NssmTarget -Force
    Write-Host "Bundled NSSM service helper: $NssmTarget"
}

function Ensure-NssmReleaseAsset {
    $NssmAssetPath = Join-Path $AssetDir "nssm.exe"
    if (Test-Path $NssmAssetPath) {
        return $NssmAssetPath
    }

    $NssmArchivePath = Join-Path $BuildTempDir "nssm.zip"
    $NssmExtractDir = Join-Path $BuildTempDir "nssm"

    # Multiple mirrors in order of preference – nssm.cc has intermittent 503 errors.
    $NssmMirrors = @(
        "https://nssm.cc/release/nssm-2.24.zip",
        "https://github.com/kirillkovalenko/nssm/releases/download/nssm-2.24/nssm-2.24.zip",
        "https://objects.githubusercontent.com/github-production-release-asset-2e65be/nssm/nssm-2.24.zip"
    )

    $Downloaded = $false
    foreach ($NssmDownloadUrl in $NssmMirrors) {
        Write-Host "Downloading NSSM for Windows service installs: $NssmDownloadUrl"
        try {
            Invoke-WebRequest -Uri $NssmDownloadUrl -OutFile $NssmArchivePath -TimeoutSec 30 -ErrorAction Stop
            $Downloaded = $true
            break
        } catch {
            Write-Warning "Failed to download from $NssmDownloadUrl : $_"
        }
    }

    if (-not $Downloaded) {
        Write-Warning "All NSSM download mirrors failed. Build will proceed without NSSM."
        Write-Warning "The standalone exe will use sc.exe or Task Scheduler for background service."
        Write-Warning "You can manually place nssm.exe next to netorium.exe to enable NSSM service support."
        return $null
    }

    if (Test-Path $NssmExtractDir) {
        Remove-Item $NssmExtractDir -Recurse -Force
    }
    Expand-Archive -Path $NssmArchivePath -DestinationPath $NssmExtractDir -Force

    $NssmSource = Get-ChildItem -Path $NssmExtractDir -Recurse -Filter "nssm.exe" |
        Where-Object { $_.FullName -match "win64" } |
        Select-Object -First 1
    if (-not $NssmSource) {
        Write-Warning "Could not find win64/nssm.exe in the downloaded NSSM archive. Skipping NSSM bundle."
        return $null
    }

    New-Item -ItemType Directory -Force -Path $AssetDir | Out-Null
    Copy-Item $NssmSource.FullName $NssmAssetPath -Force
    Write-Host "Prepared NSSM asset: $NssmAssetPath"
    return $NssmAssetPath
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
Ensure-NssmReleaseAsset | Out-Null
$ResolvedTargetPath = (Resolve-Path $TargetPath).Path
if (-not $SkipVerify) {
    Write-Host "Verifying standalone build:"
    Invoke-NativeCommand -Command $ResolvedTargetPath -Arguments @("version")
}

$ShouldInstallUser = -not $NoInstallUser
if ($InstallUser) {
    $ShouldInstallUser = $true
}

if ($ShouldInstallUser) {
    Install-UserCommand -SourcePath $ResolvedTargetPath
} else {
    Write-Host "Skipped current-user command install."
}

Write-Host "Run standalone build: .\$TargetPath --help"
Write-Host "Verify standalone build: .\$TargetPath version"
Write-Host "Run installed command: netorium --help"
Write-Host "Build only without installing command: .\scripts\build-windows.ps1 -NoInstallUser"
