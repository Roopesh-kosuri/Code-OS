export const ALLOWED_EXTERNAL_SCHEMES = ["https:", "http:", "mailto:"];

export function validateExternalUrl(rawUrl: string): boolean {
  if (!rawUrl || typeof rawUrl !== "string") {
    return false;
  }
  try {
    const parsed = new URL(rawUrl);
    return ALLOWED_EXTERNAL_SCHEMES.includes(parsed.protocol.toLowerCase());
  } catch {
    return false;
  }
}
