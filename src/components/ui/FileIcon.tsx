import React from "react";

interface FileIconProps {
  filename: string;
  isDirectory?: boolean;
  isOpen?: boolean;
  className?: string;
  size?: number;
}

export function FileIcon({ filename, isDirectory = false, isOpen = false, className = "", size = 15 }: FileIconProps) {
  if (isDirectory) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={`shrink-0 ${className || "text-[#f5a623]"}`}
      >
        {isOpen ? (
          <path
            d="M19 20H4C2.89543 20 2 19.1046 2 18V6C2 4.89543 2.89543 4 4 4H9.17157C9.70201 4 10.2107 4.21071 10.5858 4.58579L12.4142 6.41421C12.7893 6.78929 13.298 7 13.8284 7H20C21.1046 7 22 7.89543 22 9V10H6.5C5.39543 10 4.5 10.8954 4.5 12V18L21.8 13.5C22.3 13.4 22.8 13.8 22.8 14.3V18C22.8 19.1046 21.9046 20 20.8 20H19Z"
            fill="currentColor"
            opacity="0.9"
          />
        ) : (
          <path
            d="M20 18H4V8H20V18ZM20 6H13.8284L12 4.17157C11.6249 3.79653 11.1163 3.58579 10.5858 3.58579H4C2.67392 3.58579 1.40215 4.11259 0.464466 5.05027C-0.473215 5.98795 -1.00002 7.25973 -1.00002 8.58579V18C-1.00002 19.3261 -0.473215 20.5979 0.464466 21.5355C1.40215 22.4732 2.67392 23 4 23H20C21.3261 23 22.5979 22.4732 23.5355 21.5355C24.4732 20.5979 25 19.3261 25 18V11C25 9.67392 24.4732 8.40215 23.5355 7.46447C22.5979 6.52679 21.3261 6 20 6Z"
            fill="currentColor"
          />
        )}
      </svg>
    );
  }

  const name = filename.toLowerCase();
  const ext = name.includes(".") ? name.split(".").pop() || "" : name;

  // 0. Java (.java, .jar, .class, .jsp)
  if (["java", "jar", "class", "jsp"].includes(ext)) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#EA2D2E" />
        <path d="M10 4C9 5.5 11 6.5 10 8" stroke="#FFFFFF" strokeWidth="1.2" strokeLinecap="round" opacity="0.85" />
        <path d="M13 3C12 5 14 6 13 8" stroke="#FFA500" strokeWidth="1.2" strokeLinecap="round" />
        <path d="M6 10H16V15C16 17.2 13.8 19 11 19C8.2 19 6 17.2 6 15V10Z" fill="#FFFFFF" />
        <path d="M16 11H18C18.8 11 19.5 11.7 19.5 12.5C19.5 13.3 18.8 14 18 14H16" stroke="#FFFFFF" strokeWidth="1.4" strokeLinecap="round" />
        <path d="M5 20H17" stroke="#FFFFFF" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }

  // 1. C++ (.cpp, .cc, .cxx, .hpp, .h, .hxx)
  if (["cpp", "cc", "cxx", "hpp", "hxx"].includes(ext) || name.endsWith(".cpp")) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#00599C" />
        <path d="M11.5 8.5C10.5 7.5 8.5 7.5 7.5 8.5C6.5 9.5 6.5 12.5 7.5 13.5C8.5 14.5 10.5 14.5 11.5 13.5" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" />
        <path d="M14 11H17M15.5 9.5V12.5" stroke="#00DAF3" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M18.5 11H21.5M20 9.5V12.5" stroke="#00DAF3" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }

  // 2. C (.c, .h)
  if (ext === "c" || (ext === "h" && !name.includes("cpp"))) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#659AD2" />
        <path d="M16 8C14.5 6.5 10.5 6.5 9 8C7.5 9.5 7.5 14.5 9 16C10.5 17.5 14.5 17.5 16 16" stroke="#FFFFFF" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    );
  }

  // 3. Python (.py, .pyw, .ipynb)
  if (["py", "pyw", "ipynb"].includes(ext)) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#1e293b" />
        {/* Python Top Blue Snake */}
        <path d="M12 4C8.5 4 8.5 5.5 8.5 5.5V7H12.5V8.5H6.5C5 8.5 4 9.5 4 11.5C4 13.5 5 14 5 14H6.5V12.5C6.5 11 7.5 10 9 10H13C14.5 10 15.5 9 15.5 7.5C15.5 6 15.5 4 12 4ZM10 6C10.55 6 11 6.45 11 7C11 7.55 10.55 8 10 8C9.45 8 9 7.55 9 7C9 6.45 9.45 6 10 6Z" fill="#38BDF8" />
        {/* Python Bottom Yellow Snake */}
        <path d="M12 20C15.5 20 15.5 18.5 15.5 18.5V17H11.5V15.5H17.5C19 15.5 20 14.5 20 12.5C20 10.5 19 10 19 10H17.5V11.5C17.5 13 16.5 14 15 14H11C9.5 14 8.5 15 8.5 16.5C8.5 18 8.5 20 12 20ZM14 18C13.45 18 13 17.55 13 17C13 16.45 13.45 16 14 16C14.55 16 15 16.45 15 17C15 17.55 14.55 18 14 18Z" fill="#FACC15" />
      </svg>
    );
  }

  // 4. TypeScript (.ts, .tsx)
  if (["ts", "tsx"].includes(ext)) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#3178C6" />
        <text x="5" y="17" fill="#FFFFFF" fontSize="11" fontWeight="bold" fontFamily="monospace">TS</text>
      </svg>
    );
  }

  // 5. JavaScript (.js, .jsx, .mjs, .cjs)
  if (["js", "jsx", "mjs", "cjs"].includes(ext)) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#F7DF1E" />
        <text x="6" y="17" fill="#000000" fontSize="11" fontWeight="bold" fontFamily="monospace">JS</text>
      </svg>
    );
  }

  // 6. HTML (.html, .htm)
  if (["html", "htm"].includes(ext)) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#E44D26" />
        <path d="M7 8L4 12L7 16" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M17 8L20 12L17 16" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M13 7L11 17" stroke="#FFFFFF" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }

  // 7. CSS / SCSS / LESS
  if (["css", "scss", "sass", "less"].includes(ext)) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#264DE4" />
        <path d="M7 8H17L16 13H8.5L9 16L12 17L15 16" stroke="#FFFFFF" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  // 8. JSON (.json)
  if (ext === "json") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#F59E0B" />
        <text x="6" y="16" fill="#FFFFFF" fontSize="13" fontWeight="bold" fontFamily="monospace">{`{}`}</text>
      </svg>
    );
  }

  // 9. Markdown (.md, .markdown)
  if (["md", "markdown"].includes(ext)) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#8B5CF6" />
        <path d="M5 15V9L8 12L11 9V15M15 9V15M13 12L15 15L17 12" stroke="#FFFFFF" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  // 10. Rust (.rs)
  if (ext === "rs") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#DEA584" />
        <circle cx="12" cy="12" r="5" stroke="#000000" strokeWidth="1.5" strokeDasharray="2 2" />
        <text x="8.5" y="15" fill="#000000" fontSize="9" fontWeight="bold" fontFamily="sans-serif">R</text>
      </svg>
    );
  }

  // 11. Go (.go)
  if (ext === "go") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#00ADD8" />
        <text x="4" y="16" fill="#FFFFFF" fontSize="10" fontWeight="bold" fontFamily="sans-serif">GO</text>
      </svg>
    );
  }

  // 12. Shell / Bash (.sh, .bash, .zsh, .ps1, .bat)
  if (["sh", "bash", "zsh", "ps1", "bat", "cmd"].includes(ext)) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#10B981" />
        <path d="M6 8L10 12L6 16M11 16H18" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  // 13. SQL (.sql, .db, .sqlite)
  if (["sql", "db", "sqlite"].includes(ext)) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#06B6D4" />
        <ellipse cx="12" cy="8" rx="6" ry="3" stroke="#FFFFFF" strokeWidth="1.5" />
        <path d="M6 8V16C6 17.66 8.69 19 12 19C15.31 19 18 17.66 18 16V8" stroke="#FFFFFF" strokeWidth="1.5" />
        <path d="M6 12C6 13.66 8.69 15 12 15C15.31 15 18 13.66 18 12" stroke="#FFFFFF" strokeWidth="1.5" />
      </svg>
    );
  }

  // 14. Images (.png, .jpg, .jpeg, .svg, .gif, .webp)
  if (["png", "jpg", "jpeg", "svg", "gif", "webp", "ico"].includes(ext)) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#EC4899" />
        <circle cx="8.5" cy="8.5" r="1.5" fill="#FFFFFF" />
        <path d="M5 18L10 12L14 16L16 14L19 18H5Z" fill="#FFFFFF" />
      </svg>
    );
  }

  // 15. Config & Git (.env, .gitignore, .yml, .yaml, .toml, .ini)
  if (["env", "gitignore", "yml", "yaml", "toml", "ini", "conf", "config"].includes(ext) || name.startsWith(".")) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className}`}>
        <rect width="24" height="24" rx="4" fill="#64748B" />
        <circle cx="12" cy="8" r="2" fill="#FFFFFF" />
        <circle cx="8" cy="15" r="2" fill="#FFFFFF" />
        <circle cx="16" cy="15" r="2" fill="#FFFFFF" />
        <path d="M12 10V12M12 12L8 13M12 12L16 13" stroke="#FFFFFF" strokeWidth="1.5" />
      </svg>
    );
  }

  // Default File Icon
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={`shrink-0 ${className || "text-on-surface-variant"}`}>
      <path
        d="M14 2H6C4.89543 2 4 2.89543 4 4V20C4 21.1046 4.89543 22 6 22H18C19.1046 22 20 21.1046 20 20V8L14 2Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M14 2V8H20"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M8 13H16M8 17H13"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  );
}
