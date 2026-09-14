# macOS Installation & Gatekeeper Guide

This guide covers installing and running **CODE OS** on macOS (Apple Silicon and Intel).

---

## 1. The Normal Path (Official Production Releases)

Official release builds of CODE OS are cryptographically signed with an Apple Developer ID certificate, built with Hardened Runtime entitlements (JIT, unsigned executable memory for Node/V8, and audio input for voice mode), and notarized by Apple.

### Installation Steps:
1. Download the latest `.dmg` or `.zip` from the official release page:
   - **Apple Silicon (M1/M2/M3/M4):** `CODE OS-<version>-mac-arm64.dmg`
   - **Intel:** `CODE OS-<version>-mac-x64.dmg`
2. Open the `.dmg` file.
3. Drag **CODE OS.app** into your **`/Applications`** folder.
4. Launch CODE OS from Launchpad or Spotlight.
5. Gatekeeper validates the stapled Apple notarization ticket and opens the application cleanly with zero warnings.

---

## 2. Why Does macOS Show "CODE OS is damaged and can't be opened"?

If you download an unsigned development build (or a community-built binary) and double-click it, macOS Gatekeeper may display this warning:

> **"CODE OS is damaged and can't be opened. You should move it to the Trash."**

### Plain-Language Explanation:
- **Your application is NOT actually damaged or corrupted.**
- When you download any file from the internet (via Safari, Chrome, Slack, Discord, curl, etc.), macOS automatically attaches a security flag called the **Quarantine Attribute** (`com.apple.quarantine`).
- When you try to run an application with this quarantine flag, macOS **Gatekeeper** inspects it for:
  1. A valid Apple Developer ID signature.
  2. Hardened Runtime security compliance.
  3. An Apple Notarization ticket (proving Apple scanned the binary for malicious code).
- If the build was compiled without official Apple developer credentials (e.g., local builds or development releases labeled `*-UNSIGNED-DEV*`), Gatekeeper blocks execution and displays the misleading "damaged" message as a defensive safeguard.

---

## 3. Development Build Workarounds (Opening Unsigned Builds)

If you are running an unofficial build, pull request preview, or local dev artifact, use one of the two standard workarounds below.

### Method A: Strip the Quarantine Attribute (Recommended)

Open **Terminal** (`Applications > Utilities > Terminal`) and run:

```bash
# If you moved CODE OS to Applications:
xattr -cr "/Applications/CODE OS.app"

# Or if the app is still in your Downloads folder:
xattr -cr ~/Downloads/"CODE OS.app"
```

#### What this command does:
- `xattr -d com.apple.quarantine` or `xattr -cr` recursively strips the quarantine flag from the application bundle and all nested Electron helpers, allowing macOS to launch the app normally.

---

### Method B: Right-Click Open (Finder GUI)

If you prefer not to use Terminal:

1. Open **Finder** and navigate to `/Applications` (or the folder containing `CODE OS.app`).
2. **Right-click** (or **Control-click**) on `CODE OS.app`.
3. Select **Open** from the context menu (do not just double-click).
4. A dialog will appear asking: *"macOS cannot verify the developer of CODE OS. Are you sure you want to open it?"*
5. Click **Open**.
6. macOS registers a permanent security exception for this binary on your machine. All future launches can be done with a standard double-click.

---

## 4. Troubleshooting & Verification Commands

Developers and system administrators can inspect the bundle's signature and notarization status using native macOS tools:

```bash
# 1. Check if quarantine attribute is present
xattr -l "/Applications/CODE OS.app"

# 2. Inspect codesign identity and hardened runtime flags
codesign -dv --verbose=4 "/Applications/CODE OS.app"

# 3. Deep-verify signatures across all nested helpers
codesign --verify --deep --strict "/Applications/CODE OS.app"

# 4. Assess Gatekeeper evaluation status
spctl --assess -vv --type install "/Applications/CODE OS.app"
# Or:
spctl -a -vv -t install "/Applications/CODE OS.app"

# 5. Check Apple Notarization stapled ticket
xcrun stapler validate "/Applications/CODE OS.app"
```
