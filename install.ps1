$PackageName = if ($env:NETORIUM_PACKAGE_NAME) { $env:NETORIUM_PACKAGE_NAME } else { "netorium-cli" }
$InstallSource = if ($env:NETORIUM_INSTALL_SOURCE) { $env:NETORIUM_INSTALL_SOURCE } else { "github" }
$GithubRepo = if ($env:NETORIUM_GITHUB_REPO) { $env:NETORIUM_GITHUB_REPO } else { "it31wasdrexm/netorium" }
$GithubRef = if ($env:NETORIUM_GITHUB_REF) { $env:NETORIUM_GITHUB_REF } else { "main" }
$GithubRefKind = if ($env:NETORIUM_GITHUB_REF_KIND) { $env:NETORIUM_GITHUB_REF_KIND } else { "heads" }
$PackageSpec = $env:NETORIUM_PACKAGE_SPEC
$StandaloneUrl = $env:NETORIUM_STANDALONE_URL
$StandaloneAssetName = $env:NETORIUM_STANDALONE_ASSET_NAME
$DefaultLocalAppData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $env:USERPROFILE "AppData\Local" }
$VenvDir = if ($env:NETORIUM_VENV_DIR) { $env:NETORIUM_VENV_DIR } else { Join-Path $DefaultLocalAppData "Netorium\venv" }
$BinDir = if ($env:NETORIUM_BIN_DIR) { $env:NETORIUM_BIN_DIR } else { Join-Path $DefaultLocalAppData "Netorium\bin" }
$GithubApiBaseUrl = if ($env:NETORIUM_GITHUB_API_BASE_URL) { $env:NETORIUM_GITHUB_API_BASE_URL.TrimEnd("/") } else { "https://api.github.com" }
$ReleaseApiUrl = if ($env:NETORIUM_RELEASE_API_URL) { $env:NETORIUM_RELEASE_API_URL } else { "$GithubApiBaseUrl/repos/$GithubRepo/releases/latest" }
$HttpHeaders = @{ "User-Agent" = "netorium-installer" }
$UpdateMode = if ($env:NETORIUM_UPDATE) { $env:NETORIUM_UPDATE -eq "1" } else { $false }
$UseColor = -not $env:NETORIUM_NO_COLOR -and $Host.UI.SupportsVirtualTerminal

function Write-NetoriumBanner {
    if (-not $UseColor) {
        return
    }

    Write-Host ""
    Write-Host " _   _      _             _" -ForegroundColor Cyan
    Write-Host "| \ | | ___| |_ ___ _ __ (_) ___  _ __" -ForegroundColor Cyan
    Write-Host "|  \| |/ _ \ __/ _ \ '_ \| |/ _ \| '_ \" -ForegroundColor Cyan
    Write-Host "| |\  |  __/ ||  __/ | | | | (_) | | | |" -ForegroundColor Cyan
    Write-Host "|_| \_|\___|\__\___|_| |_|_|\___/|_| |_|" -ForegroundColor Cyan
    Write-Host "  Network access control CLI" -ForegroundColor DarkGray
    Write-Host ""
}

function Write-NetoriumStep {
    param (
        [string]$Message
    )

    if ($UseColor) {
        Write-Host "▸ $Message" -ForegroundColor Cyan
    } else {
        Write-Host "-> $Message"
    }
}

function Write-NetoriumOk {
    param (
        [string]$Message
    )

    if ($UseColor) {
        Write-Host "✔ $Message" -ForegroundColor Green
    } else {
        Write-Host "OK $Message"
    }
}

function Write-NetoriumWarn {
    param (
        [string]$Message
    )

    if ($UseColor) {
        Write-Host "! $Message" -ForegroundColor Yellow
    } else {
        Write-Host "WARN $Message"
    }
}

function Invoke-NetoriumSpinner {
    param (
        [string]$Message,
        [scriptblock]$Action
    )

    Write-NetoriumStep $Message
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Message failed."
    }
    Write-NetoriumOk $Message
}

function Test-PythonCommand {
    param (
        [string]$Command,
        [string[]]$Arguments
    )

    & $Command @($Arguments + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")) *> $null
    return $LASTEXITCODE -eq 0
}

function Get-PythonCommand {
    $Candidates = @(
        [pscustomobject]@{ Command = "py"; Arguments = @("-3") },
        [pscustomobject]@{ Command = "python"; Arguments = @() },
        [pscustomobject]@{ Command = "python3"; Arguments = @() }
    )

    foreach ($Candidate in $Candidates) {
        if ((Get-Command $Candidate.Command -ErrorAction SilentlyContinue) -and (Test-PythonCommand $Candidate.Command $Candidate.Arguments)) {
            return $Candidate
        }
    }

    return $null
}

function Get-AssetArch {
    switch ($env:PROCESSOR_ARCHITECTURE) {
        "ARM64" { return "arm64" }
        "AMD64" { return "x64" }
        default {
            if ([string]::IsNullOrWhiteSpace($env:PROCESSOR_ARCHITECTURE)) {
                return "x64"
            }
            return $env:PROCESSOR_ARCHITECTURE.ToLowerInvariant()
        }
    }
}

function Add-UniqueValue {
    param (
        [string[]]$Values,
        [string]$Value
    )

    if (-not [string]::IsNullOrWhiteSpace($Value) -and -not ($Values -contains $Value)) {
        return @($Values + $Value)
    }
    return $Values
}

function Get-StandaloneAssetNames {
    $Names = @()
    $Names = Add-UniqueValue -Values $Names -Value $StandaloneAssetName
    $Names = Add-UniqueValue -Values $Names -Value "netorium-windows-$(Get-AssetArch).exe"
    $Names = Add-UniqueValue -Values $Names -Value "netorium-windows-x64.exe"
    $Names = Add-UniqueValue -Values $Names -Value "netorium.exe"
    return $Names
}

function Normalize-PathEntry {
    param (
        [string]$PathEntry
    )

    if ([string]::IsNullOrWhiteSpace($PathEntry)) {
        return ""
    }

    $TrimChars = @(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    return $PathEntry.Trim().TrimEnd($TrimChars)
}

function Test-PathEntry {
    param (
        [string]$PathValue,
        [string]$PathEntry
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
    param (
        [string]$PathValue,
        [string]$PathEntry
    )

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $PathEntry
    }
    if ([string]::IsNullOrWhiteSpace($PathEntry)) {
        return $PathValue
    }

    return "$PathValue$([System.IO.Path]::PathSeparator)$PathEntry"
}

function Add-UserPathEntry {
    param (
        [string]$PathEntry
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
        Write-NetoriumOk "Added to user PATH: $PathEntry"
    }

    if (-not (Test-PathEntry -PathValue $env:Path -PathEntry $PathEntry)) {
        $env:Path = Join-PathEntries -PathValue $env:Path -PathEntry $PathEntry
    }
}

function Get-StandaloneDownloadUrl {
    if (-not [string]::IsNullOrWhiteSpace($StandaloneUrl)) {
        return $StandaloneUrl
    }

    if ($GithubRepo -eq "OWNER/REPO") {
        Write-Error "Netorium GitHub repository is not configured. Set NETORIUM_GITHUB_REPO=owner/repo or NETORIUM_STANDALONE_URL before running this installer."
        exit 1
    }

    foreach ($AssetName in (Get-StandaloneAssetNames)) {
        $CandidateUrl = "https://github.com/$GithubRepo/releases/latest/download/$AssetName"
        try {
            $Response = Invoke-WebRequest -Uri $CandidateUrl -Method Head -Headers $HttpHeaders -ErrorAction Stop
            if ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 400) {
                return $CandidateUrl
            }
        } catch {
            continue
        }
    }

    try {
        $Release = Invoke-RestMethod -Uri $ReleaseApiUrl -Headers $HttpHeaders -ErrorAction Stop
    } catch {
        Write-Error "Could not read Netorium latest release from $ReleaseApiUrl. Install Python 3.11+, install pipx, or download the standalone binary manually from https://github.com/$GithubRepo/releases/latest. Details: $($_.Exception.Message)"
        exit 1
    }

    $Assets = @($Release.assets)
    foreach ($AssetName in (Get-StandaloneAssetNames)) {
        $Asset = $Assets | Where-Object { $_.name -eq $AssetName } | Select-Object -First 1
        if ($null -ne $Asset -and -not [string]::IsNullOrWhiteSpace($Asset.browser_download_url)) {
            return $Asset.browser_download_url
        }
    }

    $FallbackAsset = $Assets | Where-Object { $_.name -like "netorium*.exe" } | Select-Object -First 1
    if ($null -ne $FallbackAsset -and -not [string]::IsNullOrWhiteSpace($FallbackAsset.browser_download_url)) {
        return $FallbackAsset.browser_download_url
    }

    $ExpectedNames = (Get-StandaloneAssetNames) -join ", "
    Write-Error "The latest Netorium release does not contain a Windows standalone asset. Expected one of: $ExpectedNames. Release: https://github.com/$GithubRepo/releases/latest"
    exit 1
}

function Invoke-NetoriumDownload {
    param (
        [string]$Url,
        [string]$Destination,
        [string]$Label
    )

    Write-NetoriumStep $Label
    $ProgressPreference = "Continue"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Destination -Headers $HttpHeaders -ErrorAction Stop
    } catch {
        if (Test-Path $Destination) {
            Remove-Item $Destination -Force
        }
        throw "Could not download Netorium standalone binary from $Url. Details: $($_.Exception.Message)"
    }
    Write-NetoriumOk $Label
}

function Install-StandaloneRelease {
    New-Item -ItemType Directory -Force $BinDir *> $null
    $ResolvedBinDir = (Resolve-Path $BinDir).Path
    $TargetPath = Join-Path $ResolvedBinDir "netorium.exe"
    $TempPath = "$TargetPath.download"
    $DownloadUrl = Get-StandaloneDownloadUrl

    Invoke-NetoriumDownload -Url $DownloadUrl -Destination $TempPath -Label "Downloading Netorium CLI"
    if (-not (Test-Path $TempPath) -or (Get-Item $TempPath).Length -le 0) {
        Write-Error "Downloaded Netorium standalone binary is empty: $DownloadUrl"
        exit 1
    }
    Move-Item -Path $TempPath -Destination $TargetPath -Force

    $VersionOutput = & $TargetPath version 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Downloaded Netorium binary failed verification: $TargetPath"
        exit 1
    }

    Add-UserPathEntry -PathEntry $ResolvedBinDir
    Write-NetoriumOk "Standalone CLI installed: $TargetPath"
    if (-not [string]::IsNullOrWhiteSpace($VersionOutput)) {
        Write-NetoriumOk ($VersionOutput | Select-Object -First 1)
    }
    Write-NetoriumWarn "If this terminal cannot find netorium, open a new PowerShell window."
}

function Resolve-PackageSpec {
    if (-not [string]::IsNullOrWhiteSpace($PackageSpec)) {
        return
    }

    switch ($InstallSource) {
        "github" {
            if ($GithubRepo -eq "OWNER/REPO") {
                Write-Error "Netorium GitHub repository is not configured. Set NETORIUM_GITHUB_REPO=owner/repo or NETORIUM_PACKAGE_SPEC before running this installer."
                exit 1
            }
            $script:PackageSpec = "https://github.com/$GithubRepo/archive/refs/$GithubRefKind/$GithubRef.zip"
        }
        "pypi" {
            $script:PackageSpec = $PackageName
        }
        "local" {
            $script:PackageSpec = Split-Path -Parent $MyInvocation.MyCommand.Path
        }
        default {
            Write-Error "Unsupported NETORIUM_INSTALL_SOURCE: $InstallSource. Use github, pypi, local, or set NETORIUM_PACKAGE_SPEC directly."
            exit 1
        }
    }
}

function Test-UpdateMode {
    if ($UpdateMode) {
        return
    }
    if (Get-Command netorium -ErrorAction SilentlyContinue) {
        $script:UpdateMode = $true
    }
}

Test-UpdateMode
Write-NetoriumBanner
if ($UpdateMode) {
    Write-NetoriumStep "Updating Netorium CLI"
} else {
    Write-NetoriumStep "Installing Netorium CLI"
}

Resolve-PackageSpec

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    Invoke-NetoriumSpinner -Message "Installing with pipx" -Action {
        pipx install --force $PackageSpec
    }
} else {
    $Python = Get-PythonCommand
    if ($null -eq $Python) {
        if ($InstallSource -ne "github" -and [string]::IsNullOrWhiteSpace($StandaloneUrl)) {
            Write-Error "Python 3.11+ or pipx is required for NETORIUM_INSTALL_SOURCE=$InstallSource. For no-Python machines, use the default GitHub installer or set NETORIUM_STANDALONE_URL."
            exit 1
        }

        Write-NetoriumWarn "Python 3.11+ or pipx was not found. Switching to standalone release."
        Install-StandaloneRelease
    } else {
        Invoke-NetoriumSpinner -Message "Creating virtual environment" -Action {
            & $Python.Command @($Python.Arguments + @("-m", "venv", $VenvDir))
        }

        $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
        Invoke-NetoriumSpinner -Message "Upgrading pip" -Action {
            & $VenvPython -m pip install --upgrade pip
        }

        Invoke-NetoriumSpinner -Message "Installing Netorium package" -Action {
            & $VenvPython -m pip install --upgrade $PackageSpec
        }

        New-Item -ItemType Directory -Force $BinDir *> $null
        $NetoriumExe = Join-Path $VenvDir "Scripts\netorium.exe"
        $CmdPath = Join-Path $BinDir "netorium.cmd"
        Set-Content -Path $CmdPath -Encoding ASCII -Value @(
            "@echo off",
            "`"$NetoriumExe`" %*"
        )

        Add-UserPathEntry -PathEntry ((Resolve-Path $BinDir).Path)
        Write-NetoriumOk "Linked command: $CmdPath"
    }
}

if (Get-Command netorium -ErrorAction SilentlyContinue) {
    $VersionLine = netorium version 2>$null | Select-Object -First 1
    if (-not [string]::IsNullOrWhiteSpace($VersionLine)) {
        Write-NetoriumOk $VersionLine
    }
}

Write-Host ""
if ($UpdateMode) {
    Write-NetoriumOk "Netorium CLI updated."
} else {
    Write-NetoriumOk "Netorium CLI installed."
}
Write-NetoriumStep "Run: netorium --help"
