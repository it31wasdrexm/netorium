$PackageName = if ($env:NETORIUM_PACKAGE_NAME) { $env:NETORIUM_PACKAGE_NAME } else { "netorium-cli" }
$InstallSource = if ($env:NETORIUM_INSTALL_SOURCE) { $env:NETORIUM_INSTALL_SOURCE } else { "github" }
$GithubRepo = if ($env:NETORIUM_GITHUB_REPO) { $env:NETORIUM_GITHUB_REPO } else { "it31wasdrexm/netorium" }
$GithubRef = if ($env:NETORIUM_GITHUB_REF) { $env:NETORIUM_GITHUB_REF } else { "main" }
$GithubRefKind = if ($env:NETORIUM_GITHUB_REF_KIND) { $env:NETORIUM_GITHUB_REF_KIND } else { "heads" }
$PackageSpec = $env:NETORIUM_PACKAGE_SPEC
$DefaultLocalAppData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $env:USERPROFILE "AppData\Local" }
$VenvDir = if ($env:NETORIUM_VENV_DIR) { $env:NETORIUM_VENV_DIR } else { Join-Path $DefaultLocalAppData "Netorium\venv" }
$BinDir = if ($env:NETORIUM_BIN_DIR) { $env:NETORIUM_BIN_DIR } else { Join-Path $DefaultLocalAppData "Netorium\bin" }

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
} else {
    $Python = Get-PythonCommand
    if ($null -eq $Python) {
        Write-Error "Python 3.11+ or pipx is required for this installer. For no-Python machines, use the standalone release binary or Docker image: https://github.com/$GithubRepo/releases/latest"
        exit 1
    }

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

    if ($env:PATH -notlike "*$BinDir*") {
        Write-Host "If netorium is not recognized, add this directory to PATH: $BinDir"
    }
}

Write-Host "Netorium CLI installed."
Write-Host "Run: netorium --help"
