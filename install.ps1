$PackageName = if ($env:NETORIUM_PACKAGE_NAME) { $env:NETORIUM_PACKAGE_NAME } else { "netorium-cli" }
$InstallSource = if ($env:NETORIUM_INSTALL_SOURCE) { $env:NETORIUM_INSTALL_SOURCE } else { "github" }
$GithubRepo = if ($env:NETORIUM_GITHUB_REPO) { $env:NETORIUM_GITHUB_REPO } else { "it31wasdrexm/netorium" }
$GithubRef = if ($env:NETORIUM_GITHUB_REF) { $env:NETORIUM_GITHUB_REF } else { "main" }
$GithubRefKind = if ($env:NETORIUM_GITHUB_REF_KIND) { $env:NETORIUM_GITHUB_REF_KIND } else { "heads" }
$PackageSpec = $env:NETORIUM_PACKAGE_SPEC

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
    py -m pip install --user --upgrade $PackageSpec
}

Write-Host "Netorium CLI installed."
Write-Host "Run: netorium --help"
