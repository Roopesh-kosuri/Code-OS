"""
Language and Toolchain Detector for CODE OS Multi-Language Run Support.
Detects programming languages from file extensions, discovers installed compilers & runtimes,
and constructs safe compilation and execution pipelines.
"""
from dataclasses import dataclass, field
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal


@dataclass
class LanguageSpec:
    id: str
    name: str
    extensions: list[str]
    is_compiled: bool
    runner_command: str  # Primary command or compiler
    runner_args: list[str] = field(default_factory=list)
    compile_command: str | None = None
    compile_args: list[str] = field(default_factory=list)
    install_hint: str = ""
    docs_url: str = ""


@dataclass
class ToolchainStatus:
    id: str
    name: str
    installed: bool
    version: str | None = None
    command_path: str | None = None
    compile_command_path: str | None = None
    install_hint: str = ""
    error_message: str | None = None


# Supported language profiles
LANGUAGE_SPECS: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        id="python",
        name="Python",
        extensions=[".py", ".pyw"],
        is_compiled=False,
        runner_command="python",
        install_hint="Install Python from https://www.python.org/downloads/ or run 'winget install Python.Python.3.11' (Windows) / 'brew install python' (macOS)",
        docs_url="https://docs.python.org/",
    ),
    "javascript": LanguageSpec(
        id="javascript",
        name="JavaScript (Node.js)",
        extensions=[".js", ".mjs", ".cjs"],
        is_compiled=False,
        runner_command="node",
        install_hint="Install Node.js from https://nodejs.org/ or run 'winget install OpenJS.NodeJS' (Windows) / 'brew install node' (macOS)",
        docs_url="https://nodejs.org/docs/",
    ),
    "typescript": LanguageSpec(
        id="typescript",
        name="TypeScript",
        extensions=[".ts", ".tsx", ".mts", ".cts"],
        is_compiled=False,
        runner_command="tsx",  # Will fallback to ts-node or deno/bun if tsx not found
        install_hint="Install tsx or ts-node via 'npm install -g tsx' or 'npm install -g ts-node typescript'",
        docs_url="https://www.typescriptlang.org/",
    ),
    "cpp": LanguageSpec(
        id="cpp",
        name="C / C++",
        extensions=[".cpp", ".cc", ".cxx", ".c", ".hpp", ".h"],
        is_compiled=True,
        runner_command="",  # Dynamic compiled binary
        compile_command="g++",  # Will fallback to clang++ or cl
        install_hint="Install GCC/G++ (MinGW on Windows via 'winget install MSYS2.MSYS2' or Visual Studio Build Tools, or 'brew install gcc' on macOS / 'apt install g++' on Linux)",
        docs_url="https://isocpp.org/",
    ),
    "java": LanguageSpec(
        id="java",
        name="Java",
        extensions=[".java"],
        is_compiled=True,
        runner_command="java",
        compile_command="javac",
        install_hint="Install JDK 17+ from https://adoptium.net/ or run 'winget install EclipseAdoptium.Temurin.17.JDK' (Windows) / 'brew install openjdk' (macOS)",
        docs_url="https://docs.oracle.com/en/java/",
    ),
    "go": LanguageSpec(
        id="go",
        name="Go",
        extensions=[".go"],
        is_compiled=False,  # Can run directly via `go run`
        runner_command="go",
        runner_args=["run"],
        install_hint="Install Go from https://go.dev/dl/ or run 'winget install GoLang.Go' (Windows) / 'brew install go' (macOS)",
        docs_url="https://go.dev/doc/",
    ),
    "rust": LanguageSpec(
        id="rust",
        name="Rust",
        extensions=[".rs"],
        is_compiled=True,
        runner_command="",  # Dynamic compiled binary
        compile_command="rustc",
        install_hint="Install Rust from https://rustup.rs/ or run 'winget install Rustlang.Rustup' (Windows) / 'curl https://sh.rustup.rs -sSf | sh' (macOS/Linux)",
        docs_url="https://www.rust-lang.org/learn",
    ),
    "shell": LanguageSpec(
        id="shell",
        name="Shell / Script",
        extensions=[".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd"],
        is_compiled=False,
        runner_command="bash" if os.name != "nt" else "powershell",
        install_hint="Built into operating system",
        docs_url="",
    ),
}

# Extension to language ID mapping
EXTENSION_MAP: dict[str, str] = {}
for lang_id, spec in LANGUAGE_SPECS.items():
    for ext in spec.extensions:
        EXTENSION_MAP[ext.lower()] = lang_id


def detect_language(file_path: str | Path) -> LanguageSpec | None:
    """Detect language profile from file path extension."""
    p = Path(file_path)
    ext = p.suffix.lower()
    lang_id = EXTENSION_MAP.get(ext)
    if not lang_id:
        # Check for special filenames like Makefile, Dockerfile
        if p.name.lower() in ("dockerfile", "containerfile"):
            return None
        return None
    return LANGUAGE_SPECS.get(lang_id)


def _find_executable(candidates: list[str]) -> str | None:
    """Find the first existing executable in system PATH, JAVA_HOME, or common JDK paths."""
    for cmd in candidates:
        found = shutil.which(cmd)
        if found:
            return found
        # Check JAVA_HOME for java/javac
        if cmd in ("javac", "java", "javac.exe", "java.exe"):
            java_home = os.environ.get("JAVA_HOME")
            if java_home:
                exe_name = cmd if cmd.endswith(".exe") or os.name != "nt" else f"{cmd}.exe"
                candidate = Path(java_home) / "bin" / exe_name
                if candidate.is_file():
                    return str(candidate)
            # Check standard Windows JDK directories
            if os.name == "nt":
                import glob
                exe_name = cmd if cmd.endswith(".exe") else f"{cmd}.exe"
                for pattern in (
                    r"C:\Program Files\Java\jdk*\bin",
                    r"C:\Program Files\Eclipse Adoptium\jdk*\bin",
                    r"C:\Program Files\Microsoft\jdk*\bin",
                    r"C:\Program Files\Amazon Corretto\jdk*\bin",
                ):
                    for bin_dir in glob.glob(pattern):
                        candidate = Path(bin_dir) / exe_name
                        if candidate.is_file():
                            return str(candidate)
    return None


def _get_version_output(cmd: str, version_flag: str = "--version") -> str | None:
    """Safely run `--version` on an executable and extract the first line."""
    try:
        res = subprocess.run(
            [cmd, version_flag],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        out = (res.stdout or res.stderr or "").strip()
        if out:
            return out.splitlines()[0][:100]
    except Exception:
        pass
    return None


def check_toolchain_status(lang_id: str) -> ToolchainStatus:
    """Inspect system PATH and return availability, version, and binary path for a toolchain."""
    spec = LANGUAGE_SPECS.get(lang_id)
    if not spec:
        return ToolchainStatus(
            id=lang_id,
            name=lang_id.capitalize(),
            installed=False,
            error_message=f"Unsupported language profile '{lang_id}'",
        )

    if lang_id == "python":
        candidates = ["python", "python3", "py"]
        exe = _find_executable(candidates)
        if exe:
            ver = _get_version_output(exe, "--version")
            return ToolchainStatus(
                id="python",
                name=spec.name,
                installed=True,
                version=ver or "Python 3 (detected)",
                command_path=exe,
                install_hint=spec.install_hint,
            )
        return ToolchainStatus(
            id="python",
            name=spec.name,
            installed=False,
            install_hint=spec.install_hint,
            error_message="Python not found. Please install Python 3.8+ to run Python files.",
        )

    if lang_id == "javascript":
        exe = _find_executable(["node", "nodejs"])
        if exe:
            ver = _get_version_output(exe, "--version")
            return ToolchainStatus(
                id="javascript",
                name=spec.name,
                installed=True,
                version=f"Node.js {ver}" if ver else "Node.js (detected)",
                command_path=exe,
                install_hint=spec.install_hint,
            )
        return ToolchainStatus(
            id="javascript",
            name=spec.name,
            installed=False,
            install_hint=spec.install_hint,
            error_message="Node.js not found. Please install Node.js 18+ to run JavaScript files.",
        )

    if lang_id == "typescript":
        # Check runners: tsx, ts-node, bun, deno, or node with npx fallback
        exe = _find_executable(["tsx", "ts-node", "bun", "deno"])
        node_exe = _find_executable(["node", "nodejs"])
        if exe:
            ver = _get_version_output(exe, "--version")
            return ToolchainStatus(
                id="typescript",
                name=spec.name,
                installed=True,
                version=f"{exe} ({ver})" if ver else f"{exe} (detected)",
                command_path=exe,
                install_hint=spec.install_hint,
            )
        elif node_exe:
            return ToolchainStatus(
                id="typescript",
                name=spec.name,
                installed=True,
                version="npx tsx (fallback via Node.js)",
                command_path=node_exe,
                install_hint=spec.install_hint,
            )
        return ToolchainStatus(
            id="typescript",
            name=spec.name,
            installed=False,
            install_hint=spec.install_hint,
            error_message="TypeScript runtime not found. Please install tsx ('npm i -g tsx') or Node.js.",
        )

    if lang_id == "cpp":
        # Check compilers: g++, clang++, gcc, clang, cl
        comp_candidates = ["g++", "clang++", "gcc", "clang", "cl"]
        comp = _find_executable(comp_candidates)
        if comp:
            ver = _get_version_output(comp, "--version") or _get_version_output(comp, "-v")
            return ToolchainStatus(
                id="cpp",
                name=spec.name,
                installed=True,
                version=f"{comp} ({ver})" if ver else f"{comp} (detected)",
                command_path=comp,
                compile_command_path=comp,
                install_hint=spec.install_hint,
            )
        return ToolchainStatus(
            id="cpp",
            name=spec.name,
            installed=False,
            install_hint=spec.install_hint,
            error_message="C/C++ compiler (g++, clang++, or gcc) not found in PATH.",
        )

    if lang_id == "java":
        javac_exe = _find_executable(["javac"])
        java_exe = _find_executable(["java"])
        if javac_exe and java_exe:
            ver = _get_version_output(javac_exe, "-version") or _get_version_output(java_exe, "-version")
            return ToolchainStatus(
                id="java",
                name=spec.name,
                installed=True,
                version=ver or "JDK (detected)",
                command_path=java_exe,
                compile_command_path=javac_exe,
                install_hint=spec.install_hint,
            )
        if not javac_exe:
            return ToolchainStatus(
                id="java",
                name=spec.name,
                installed=False,
                install_hint=spec.install_hint,
                error_message="Java compiler (javac) not found. Install JDK 11+ (or JDK 17+) or set JAVA_HOME.",
            )
        return ToolchainStatus(
            id="java",
            name=spec.name,
            installed=False,
            install_hint=spec.install_hint,
            error_message="Java runtime (java) not found. Please install JDK 17+ or set JAVA_HOME.",
        )

    if lang_id == "go":
        go_exe = _find_executable(["go"])
        if go_exe:
            ver = _get_version_output(go_exe, "version")
            return ToolchainStatus(
                id="go",
                name=spec.name,
                installed=True,
                version=ver or "Go (detected)",
                command_path=go_exe,
                install_hint=spec.install_hint,
            )
        return ToolchainStatus(
            id="go",
            name=spec.name,
            installed=False,
            install_hint=spec.install_hint,
            error_message="Go toolchain not found. Please install Go from https://go.dev/.",
        )

    if lang_id == "rust":
        rustc_exe = _find_executable(["rustc"])
        cargo_exe = _find_executable(["cargo"])
        if rustc_exe or cargo_exe:
            cmd = cargo_exe or rustc_exe
            ver = _get_version_output(cmd, "--version")
            return ToolchainStatus(
                id="rust",
                name=spec.name,
                installed=True,
                version=ver or "Rust toolchain",
                command_path=cargo_exe if cargo_exe else rustc_exe,
                compile_command_path=rustc_exe if rustc_exe else None,
                install_hint=spec.install_hint,
            )
        return ToolchainStatus(
            id="rust",
            name=spec.name,
            installed=False,
            install_hint=spec.install_hint,
            error_message="Rust toolchain not found. Please install rustup from https://rustup.rs/.",
        )

    if lang_id == "shell":
        is_windows = os.name == "nt"
        sh_exe = _find_executable(["pwsh", "powershell"]) if is_windows else _find_executable(["bash", "zsh", "sh"])
        return ToolchainStatus(
            id="shell",
            name=spec.name,
            installed=True,
            version="System Shell",
            command_path=sh_exe if sh_exe else "built-in",
            install_hint=spec.install_hint,
        )

    return ToolchainStatus(
        id=lang_id,
        name=spec.name,
        installed=False,
        install_hint=spec.install_hint,
        error_message=f"Toolchain check not configured for '{lang_id}'",
    )


def get_all_toolchains() -> list[ToolchainStatus]:
    """Retrieve discovery status for all registered language toolchains."""
    return [check_toolchain_status(lang_id) for lang_id in LANGUAGE_SPECS.keys()]
