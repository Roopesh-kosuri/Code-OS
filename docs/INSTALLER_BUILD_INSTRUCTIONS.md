# Building v3.1.1 Installers

After the v3.1.0 code is committed and tagged, build installers locally:

## Windows (on Windows machine)
```powershell
npm install
pip install -r backend/requirements.txt pyinstaller
npm run build:backend-exe
npm run fetch-runtimes
npm run package
```
Output: `release/CODE-OS-Setup-3.1.1.exe` + `release/CODE-OS-3.1.1-portable.exe`

## Linux (on Ubuntu 22.04 / WSL2)
```bash
sudo apt-get update && sudo apt-get install -y ruby ruby-dev build-essential rpm
sudo gem install --no-document fpm
npm install
pip install -r backend/requirements.txt pyinstaller
npm run build:backend-exe
node scripts/download-runtimes.js --linux
npm run package
```
Output: `release/CODE-OS-3.1.1.AppImage` + `release/code-os_3.1.1_amd64.deb`

## macOS (automatic via CI)
Push tag `v3.1.1` → GitHub Actions builds and uploads `.dmg` + `.zip`

## Verification
Test each installer on a clean machine (no Python/Node pre-installed):
- App must launch without "Backend not running" banner
- Backend must connect within 30 seconds
- Terminal `python --version` must return bundled 3.11.x
- Terminal `node --version` must return bundled v20.x.x
