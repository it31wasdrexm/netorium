# NSSM bundle placeholder

Windows release builds download NSSM 2.24 during `scripts/build-windows.ps1`
and place `nssm.exe` next to `netorium.exe` in `%LOCALAPPDATA%\Netorium\bin`.

The binary is not committed to git. It is resolved at runtime from:

1. `nssm.exe` beside the Netorium executable
2. `netorium/vendor/nssm/win64/nssm.exe` in development trees
3. `nssm` on `PATH`
