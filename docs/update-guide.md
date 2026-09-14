# CODE OS — Fleet Update & Installation Guide (v5.0.0)

This guide provides instructions for upgrading existing installations or deploying fresh instances of **CODE OS v5.0.0**.

> [!NOTE]
> CODE OS does not currently use a background auto-updater. Upgrades across machines and developer fleets are performed by uninstalling the previous launcher build and installing the updated v5.0.0 artifact.

---

## 1. Verifying Artifact Integrity (SHA256 Checksums)

Before installing any artifact, verify its SHA256 checksum against `SHA256SUMS.txt` published with the release.

### Windows (PowerShell)
```powershell
Get-FileHash -Algorithm SHA256 "CODE OS Setup 5.0.0.exe"
Get-Content SHA256SUMS.txt
```

### Linux (Bash)
```bash
sha256sum -c SHA256SUMS.txt --ignore-missing
```

### macOS (Terminal)
```bash
shasum -a 256 "CODE OS-5.0.0-mac-x64.dmg"
```

---

## 2. Windows Upgrade Procedure

### Step 1: Close Active Processes
Close any running instances of CODE OS or its background supervisors (`watchdog_launcher.exe`, `python.exe`, `electron.exe`).

### Step 2: Uninstall the Previous Version
1. Open **Windows Settings** → **Apps** → **Installed apps**.
2. Locate **CODE OS** and click **Uninstall**.
3. *Note: User data, vector databases, and workspace settings located in `%APPDATA%\code_os` are preserved across uninstalls.*

### Step 3: Install the Updated v5.0.0 Artifact
1. Run `CODE OS Setup 5.0.0.exe`.
2. Follow the setup wizard to complete the installation.
3. Launch CODE OS from the desktop shortcut or Start Menu.
4. Verify the window title or Settings → About section displays:
   ```text
   Version 5.0.0 (build <commit-hash>)
   ```

### Portable Windows Version
For environments where administrative installation is restricted:
1. Extract `CODE OS-5.0.0-win.zip` to your desired directory (e.g., `C:\Tools\CODE OS`).
2. Run `CODE OS.exe`.

---

## 3. Linux Upgrade Procedure

### AppImage
1. Delete the existing `.AppImage` file.
2. Download `CODE OS-5.0.0-x86_64.AppImage`.
3. Make it executable:
   ```bash
   chmod +x "CODE OS-5.0.0-x86_64.AppImage"
   ```
4. Run:
   ```bash
   ./CODE\ OS-5.0.0-x86_64.AppImage
   ```

### Debian Package (.deb)
```bash
sudo apt-get remove code-os
sudo dpkg -i code-os_5.0.0_amd64.deb
```

---

## 4. Troubleshooting & Verification

- **Offline Payload Budgeting**: All v5.0.0 fleet artifacts bundle `tiktoken` and local encoding blobs (`cl100k_base`, `o200k_base`) inside `resources/tiktoken`. No network connectivity is required for token accounting.
- **Runtimes Included**: Embedded Python 3.11, Node.js 20, and Git are pre-packaged. No prerequisites need to be installed on end-user machines.
