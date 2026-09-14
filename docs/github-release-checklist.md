# GitHub Release Upload Checklist

## Prerequisites
- [ ] GitHub repository created: github.com/yourusername/code-os
- [ ] SSH key or personal access token configured
- [ ] Release v5.0.0 created on GitHub (draft mode)

## Upload Artifacts
- [ ] Upload `release/CODE OS Setup 5.0.0.exe` (Windows installer)
- [ ] Upload `release/CODE OS-5.0.0-win.zip` (Windows portable)
- [ ] Upload `release/CODE OS-5.0.0-mac.dmg` (macOS installer, when built)
- [ ] Upload `release/CODE OS-5.0.0-x86_64.AppImage` (Linux AppImage, when built)
- [ ] Upload `release/code-os_5.0.0_amd64.deb` (Linux Debian, when built)

## Release Description
Copy the content from RELEASE_NOTES.md into the GitHub Release
description field.

## Publish
- [ ] Click "Publish release" on GitHub
- [ ] Verify all artifacts are downloadable
- [ ] Test download + install on a fresh system

## Push Release Branch (Optional)
If you want to push the clean release branch:
  git remote add origin git@github.com:yourusername/code-os.git
  git push origin release-v5
  git push origin v5.0.0

DO NOT push the dev branch with audit history to public remote.
