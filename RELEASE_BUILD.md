# Netorium Release Build Guide

Use this guide when publishing standalone GitHub Release assets.

Do not upload files directly from `dist/`. PyInstaller creates generic names
such as `netorium` or `netorium.exe`; GitHub keeps that name and the documented
download URL will not work. Always upload the renamed files from
`release-assets/`.

## Expected Asset Names

```text
netorium-linux-x64
netorium-windows-x64.exe
netorium-macos-x64
netorium-macos-arm64
```

## Linux Build on Linux

From the repository root on Linux:

```bash
scripts/build-standalone.sh
```

Expected output on a 64-bit Linux machine:

```text
release-assets/netorium-linux-x64
```

Verify it:

```bash
chmod +x release-assets/netorium-linux-x64
./release-assets/netorium-linux-x64 version
```

Upload it to a release:

```bash
gh release upload VERSION release-assets/netorium-linux-x64 --clobber
```

After upload, the download URL is:

```text
https://github.com/it31wasdrexm/netorium/releases/latest/download/netorium-linux-x64
```

## Windows Build on Windows

Build the Windows executable on Windows, not on Linux. Use a real Windows
machine, Windows VM, or Windows CI runner.

In Windows PowerShell from the repository root:

```powershell
.\scripts\build-windows.ps1
```

Expected output on a 64-bit Windows machine:

```text
release-assets\netorium-windows-x64.exe
```

Verify it:

```powershell
.\release-assets\netorium-windows-x64.exe version
```

Upload it to a release:

```powershell
gh release upload VERSION release-assets\netorium-windows-x64.exe --clobber
```

After upload, the download URL is:

```text
https://github.com/it31wasdrexm/netorium/releases/latest/download/netorium-windows-x64.exe
```

## Clean Up a Wrong Asset Name

If a release already has an asset named only `netorium`, delete that asset and
upload the named Linux asset:

```bash
gh release delete-asset VERSION netorium -y
gh release upload VERSION release-assets/netorium-linux-x64 --clobber
```
