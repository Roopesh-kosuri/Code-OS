# Code Signing Plan

## Current State
- Installers are unsigned
- Windows SmartScreen shows warning on first run
- macOS Gatekeeper requires right-click → Open

## Options Evaluated

### Windows: EV Code Signing Certificate
- **Cost**: $400-600/year
- **Providers**: DigiCert, Sectigo, GlobalSign
- **Benefit**: Removes SmartScreen warning immediately
- **Requires**: Hardware token (USB HSM) or cloud HSM for signing

### macOS: Apple Developer ID
- **Cost**: $99/year (Apple Developer Program)
- **Benefit**: Passes Gatekeeper, can notarize binaries with Apple notary service
- **Requires**: Apple Developer account & certificate provisioning

### Linux: sigstore/cosign (free)
- **Cost**: $0
- **Benefit**: Transparent signing, verifiable by anyone via OIDC & Rekor transparency log
- **Status**: Ready for immediate integration in CI/CD

## Recommended Phased Rollout
1. **Immediate**: Add `sigstore` / `cosign` for Linux AppImage / deb builds (free & automated in GitHub Actions).
2. **3 months**: Enroll in Apple Developer Program for macOS Developer ID signing & notarization.
3. **6 months**: Procure Windows EV Code Signing Certificate once project funding milestones are reached.

## Signatures Storage
- Store signatures and sha256 checksums in GitHub Release assets alongside installer binaries.
- Include verification script in installer documentation.
