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
        Write-Host "Added to user PATH: $PathEntry"
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

function Install-StandaloneRelease {
    New-Item -ItemType Directory -Force $BinDir *> $null
    $ResolvedBinDir = (Resolve-Path $BinDir).Path
    $TargetPath = Join-Path $ResolvedBinDir "netorium.exe"
    $TempPath = "$TargetPath.download"
    $DownloadUrl = Get-StandaloneDownloadUrl

    try {
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $TempPath -Headers $HttpHeaders -ErrorAction Stop
        if (-not (Test-Path $TempPath) -or (Get-Item $TempPath).Length -le 0) {
            Write-Error "Downloaded Netorium standalone binary is empty: $DownloadUrl"
            exit 1
        }
        Move-Item -Path $TempPath -Destination $TargetPath -Force
    } catch {
        if (Test-Path $TempPath) {
            Remove-Item $TempPath -Force
        }
        Write-Error "Could not download Netorium standalone binary from $DownloadUrl. Details: $($_.Exception.Message)"
        exit 1
    }

    Add-UserPathEntry -PathEntry $ResolvedBinDir
    Write-Host "Installed standalone Netorium CLI: $TargetPath"
    Write-Host "If this terminal cannot find netorium, open a new PowerShell window."
}

if ([string]::IsNullOrWhiteSpace($PackageSpec)) {
    switch ($InstallSource) {
        "github" {
            if ($GithubRepo -eq "OWNER/REPO") {
                Write-Error "Netorium GitHub repository is not configured. Set NETORIUM_GITHUB_REPO=owner/repo or NETORIUM_PACKAGE_SPEC before running this installer."
                exit 1
            }
            $PackageSpec = "https://github.com/$GithubRepo/archive/refs/$GithubRefKind/$GithubRef.zip"
        }
        "pypi" {
            $PackageSpec = $PackageName
        }
        "local" {
            $PackageSpec = Split-Path -Parent $MyInvocation.MyCommand.Path
        }
        default {
            Write-Error "Unsupported NETORIUM_INSTALL_SOURCE: $InstallSource. Use github, pypi, local, or set NETORIUM_PACKAGE_SPEC directly."
            exit 1
        }
    }
}

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    pipx install --force $PackageSpec
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} else {
    $Python = Get-PythonCommand
    if ($null -eq $Python) {
        if ($InstallSource -ne "github" -and [string]::IsNullOrWhiteSpace($StandaloneUrl)) {
            Write-Error "Python 3.11+ or pipx is required for NETORIUM_INSTALL_SOURCE=$InstallSource. For no-Python machines, use the default GitHub installer or set NETORIUM_STANDALONE_URL."
            exit 1
        }

        Install-StandaloneRelease
    } else {
        & $Python.Command @($Python.Arguments + @("-m", "venv", $VenvDir))
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }

        $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
        & $VenvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }

        & $VenvPython -m pip install --upgrade $PackageSpec
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }

        New-Item -ItemType Directory -Force $BinDir *> $null
        $NetoriumExe = Join-Path $VenvDir "Scripts\netorium.exe"
        $CmdPath = Join-Path $BinDir "netorium.cmd"
        Set-Content -Path $CmdPath -Encoding ASCII -Value @(
            "@echo off",
            "`"$NetoriumExe`" %*"
        )

        Add-UserPathEntry -PathEntry ((Resolve-Path $BinDir).Path)
    }
}

Write-Host "Netorium CLI installed."
Write-Host "Run: netorium --help"
