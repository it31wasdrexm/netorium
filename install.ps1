$PackageName = "netorium-cli"

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    pipx install $PackageName
} else {
    py -m pip install --user $PackageName
}

Write-Host "Netorium CLI installed."
Write-Host "Run: netorium --help"
