$PackageName = "netgate-cli"

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    pipx install $PackageName
} else {
    py -m pip install --user $PackageName
}

Write-Host "NetGate CLI installed."
Write-Host "Run: netgate --help"
