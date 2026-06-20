$ErrorActionPreference = "Stop"

$GithubRepo = if ($env:NETORIUM_GITHUB_REPO) { $env:NETORIUM_GITHUB_REPO } else { "it31wasdrexm/netorium" }
$RawBaseUrl = "https://raw.githubusercontent.com/$GithubRepo/main"
$InstallUrl = if ($env:NETORIUM_INSTALL_URL) { $env:NETORIUM_INSTALL_URL } else { "$RawBaseUrl/get.ps1" }

irm $InstallUrl | iex

Write-Host "Netorium Agent installed."
Write-Host "Next:"
Write-Host "  netorium agent enroll --controller http://YOUR-CONTROLLER:8765 --token YOUR_TOKEN"
