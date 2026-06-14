# Netorium Agent installer draft for Windows.
# This is a template. Real implementation must verify package signatures/checksums.

$PackageName = "netorium-cli"

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    pipx install $PackageName
} else {
    py -m pip install --user $PackageName
}

Write-Host "Netorium Agent installed."
Write-Host "Next:"
Write-Host "  netorium-agent enroll --controller https://YOUR-CONTROLLER:8765 --token YOUR_TOKEN"
