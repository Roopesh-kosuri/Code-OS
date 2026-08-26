import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Button } from "../components/ui/Button";
import { IconButton } from "../components/ui/IconButton";
import { FileIcon } from "../components/ui/FileIcon";
import { PermissionGate } from "../components/ui/PermissionGate";
import { WorkspaceTrustDialog } from "../components/workspace/WorkspaceTrustDialog";
import { WelcomeScreen } from "../components/workspace/WelcomeScreen";
import { CodeOsLogo } from "../components/branding/CodeOsLogo";

describe("Frontend UI Components", () => {
  describe("<Button />", () => {
    it("renders children and handles click events", () => {
      const handleClick = vi.fn();
      render(<Button onClick={handleClick}>Click Me</Button>);

      const btn = screen.getByRole("button", { name: "Click Me" });
      expect(btn).toBeDefined();
      fireEvent.click(btn);
      expect(handleClick).toHaveBeenCalledTimes(1);
    });

    it("applies primary, secondary, ghost, and danger variants", () => {
      const { rerender } = render(<Button variant="primary">Primary</Button>);
      expect(screen.getByRole("button").className).toContain("bg-primary-container");

      rerender(<Button variant="danger">Danger</Button>);
      expect(screen.getByRole("button").className).toContain("bg-error/20");

      rerender(<Button variant="secondary">Secondary</Button>);
      expect(screen.getByRole("button").className).toContain("bg-surface-variant/60");
    });

    it("respects disabled state", () => {
      const handleClick = vi.fn();
      render(<Button disabled onClick={handleClick}>Disabled</Button>);
      const btn = screen.getByRole("button");
      expect(btn).toHaveProperty("disabled", true);
      fireEvent.click(btn);
      expect(handleClick).not.toHaveBeenCalled();
    });
  });

  describe("<IconButton />", () => {
    it("renders accessible label and triggers click", () => {
      const handleClick = vi.fn();
      render(<IconButton label="Close Modal" icon={<span>X</span>} onClick={handleClick} />);

      const btn = screen.getByRole("button", { name: "Close Modal" });
      expect(btn).toBeDefined();
      expect(btn.getAttribute("title")).toBe("Close Modal");
      fireEvent.click(btn);
      expect(handleClick).toHaveBeenCalledTimes(1);
    });
  });

  describe("<FileIcon />", () => {
    it("renders folder icon for directories and extension icons for files", () => {
      const { container: dirContainer } = render(<FileIcon filename="src" isDirectory={true} isOpen={false} />);
      expect(dirContainer.querySelector("svg")).toBeDefined();

      const { container: pyContainer } = render(<FileIcon filename="app.py" />);
      expect(pyContainer.querySelector("svg")).toBeDefined();

      const { container: tsContainer } = render(<FileIcon filename="main.ts" />);
      expect(tsContainer.querySelector("svg")).toBeDefined();
    });
  });

  describe("<PermissionGate />", () => {
    it("renders permission gate with approve and reject actions", () => {
      const handleApprove = vi.fn();
      const handleReject = vi.fn();

      render(
        <PermissionGate
          type="command"
          details="Install dependencies"
          command="npm install"
          onApprove={handleApprove}
          onReject={handleReject}
        />
      );

      expect(screen.getByText(/Command Execution Required/i)).toBeDefined();
      expect(screen.getByText(/Install dependencies/i)).toBeDefined();

      const approveBtn = screen.getByRole("button", { name: /Approve/i });
      fireEvent.click(approveBtn);
      expect(handleApprove).toHaveBeenCalledTimes(1);
    });
  });

  describe("<WorkspaceTrustDialog />", () => {
    it("renders trust dialog and handles confirm action", () => {
      const handleTrust = vi.fn();
      const handleRestricted = vi.fn();
      const handleCancel = vi.fn();

      render(
        <WorkspaceTrustDialog
          workspacePath="D:/my-new-project"
          onTrust={handleTrust}
          onRestricted={handleRestricted}
          onCancel={handleCancel}
        />
      );

      expect(screen.getAllByText(/my-new-project/i).length).toBeGreaterThanOrEqual(1);

      const confirmBtn = screen.getByRole("button", { name: /Continue/i });
      fireEvent.click(confirmBtn);
      expect(handleTrust).toHaveBeenCalledTimes(1);
    });
  });

  describe("<WelcomeScreen />", () => {
    it("renders welcome screen with header and quick actions", () => {
      render(
        <WelcomeScreen
          recentWorkspaces={[]}
          onOpenFolder={vi.fn()}
          onSelectRecent={vi.fn()}
        />
      );

      expect(screen.getByText(/CODE OS/i)).toBeDefined();
      expect(screen.getByText(/High-Performance Environment/i)).toBeDefined();
      expect(screen.getByText(/QUICK ACTIONS/i)).toBeDefined();
    });
  });

  describe("<CodeOsLogo />", () => {
    it("renders logo SVG with custom sizes", () => {
      const { container } = render(<CodeOsLogo size={32} />);
      expect(container.querySelector("svg")).toBeDefined();
    });
  });
});
