import { describe, it, expect } from "vitest";
import { isPrivateOrMetadataHost } from "../../electron/services/captureService";

describe("CaptureService Security Hardening", () => {
  it("blocks localhost and loopback addresses", () => {
    expect(isPrivateOrMetadataHost("localhost")).toBe(true);
    expect(isPrivateOrMetadataHost("127.0.0.1")).toBe(true);
    expect(isPrivateOrMetadataHost("127.0.0.5")).toBe(true);
    expect(isPrivateOrMetadataHost("::1")).toBe(true);
    expect(isPrivateOrMetadataHost("0.0.0.0")).toBe(true);
  });

  it("blocks cloud metadata IP addresses", () => {
    expect(isPrivateOrMetadataHost("169.254.169.254")).toBe(true);
    expect(isPrivateOrMetadataHost("fd00:ec2::254")).toBe(true);
    expect(isPrivateOrMetadataHost("100.100.100.200")).toBe(true);
  });

  it("blocks private RFC1918 IPv4 ranges", () => {
    expect(isPrivateOrMetadataHost("10.0.0.1")).toBe(true);
    expect(isPrivateOrMetadataHost("10.255.255.255")).toBe(true);
    expect(isPrivateOrMetadataHost("172.16.0.1")).toBe(true);
    expect(isPrivateOrMetadataHost("172.31.255.255")).toBe(true);
    expect(isPrivateOrMetadataHost("192.168.1.1")).toBe(true);
  });

  it("allows public benign hostnames", () => {
    expect(isPrivateOrMetadataHost("github.com")).toBe(false);
    expect(isPrivateOrMetadataHost("api.openai.com")).toBe(false);
    expect(isPrivateOrMetadataHost("8.8.8.8")).toBe(false);
    expect(isPrivateOrMetadataHost("1.1.1.1")).toBe(false);
  });
});
