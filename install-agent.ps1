# NetGate Agent installer draft for Windows.
# This is a template. Real implementation must verify package signatures/checksums.

$PackageName = "netgate-cli"

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    pipx install $PackageName
} else {
    py -m pip install --user $PackageName
}

Write-Host "NetGate Agent installed."
Write-Host "Next:"
Write-Host "  netgate-agent enroll --controller https://YOUR-CONTROLLER:8765 --token YOUR_TOKEN"
