$ErrorActionPreference = "Stop"

$GithubRepo = if ($env:NETORIUM_GITHUB_REPO) { $env:NETORIUM_GITHUB_REPO } else { "it31wasdrexm/netorium" }
$RawBaseUrl = "https://raw.githubusercontent.com/$GithubRepo/main"
$InstallUrl = if ($env:NETORIUM_INSTALL_URL) { $env:NETORIUM_INSTALL_URL } else { "$RawBaseUrl/install.ps1" }

$env:NETORIUM_QUICK_INSTALL = "1"
irm $InstallUrl | iex
