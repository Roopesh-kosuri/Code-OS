"""
watchdog_launcher.py — Production entry point & supervisor for CODE OS backend.

Spawns uvicorn server in a supervised subprocess and auto-restarts it
if it crashes unexpectedly.
Ensures all file paths (database, vector index, models, logs, cache)
dynamically resolve to the OS user-writable AppData directory, NEVER Program Files.
"""

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


# ── 1. Dynamic User Data Directory Resolution ──────────────────────────────────

def resolve_user_data_dir() -> Path:
    """Resolve dynamic user data directory based on OS standards."""
    override = os.environ.get("CODE_OS_DATA_DIR") or os.environ.get("CODE_OS_HOME")
    if override:
        return Path(override)

    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        if app_data:
            return Path(app_data) / "code_os"
        return Path.home() / "AppData" / "Roaming" / "code_os"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "code_os"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / "code_os"
        return Path.home() / ".config" / "code_os"


DATA_DIR = resolve_user_data_dir()
LOGS_DIR = DATA_DIR / "logs"
MODELS_DIR = DATA_DIR / "models"
CACHE_DIR = DATA_DIR / "cache"

for d in (DATA_DIR, LOGS_DIR, MODELS_DIR, CACHE_DIR):
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        sys.stderr.write(f"[watchdog] Warning: could not create directory {d}: {exc}\n")

# Set environment variables for child processes & libraries
os.environ["CODE_OS_DATA_DIR"] = str(DATA_DIR)
os.environ["CODE_OS_HOME"] = str(DATA_DIR)
os.environ["HF_HOME"] = str(CACHE_DIR / "huggingface")
os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(CACHE_DIR / "sentence_transformers")
os.environ["TORCH_HOME"] = str(CACHE_DIR / "torch")
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["GIT_PYTHON_REFRESH"] = "quiet"

# Setup line buffering for stdout/stderr
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(line_buffering=True, encoding="utf-8")
        except Exception:
            pass


# ── 2. Logging Setup ──────────────────────────────────────────────────────────

WATCHDOG_LOG = LOGS_DIR / "watchdog.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [watchdog] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(WATCHDOG_LOG, encoding="utf-8"),
    ],
)
logger = logging.getLogger("watchdog")


# ── 3. Worker Execution Mode ──────────────────────────────────────────────────

def run_worker():
    """Directly start FastAPI backend with uvicorn in current process."""
    logger.info("Initializing CODE OS backend worker...")
    if getattr(sys, "frozen", False):
        bundle_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        if bundle_dir not in sys.path:
            sys.path.insert(0, bundle_dir)

    try:
        import uvicorn
        from app.main import app as fastapi_app

        logger.info(f"Binding uvicorn on 127.0.0.1:8000 (Data dir: {DATA_DIR})")
        uvicorn.run(
            fastapi_app,
            host="127.0.0.1",
            port=8000,
            log_level="info",
            access_log=False,
        )
    except Exception as exc:
        logger.error(f"Backend worker fatal error: {exc}", exc_info=True)
        sys.exit(1)


# ── 4. Supervisor Mode (Watchdog with Auto-Restart) ───────────────────────────

def run_supervisor():
    """Supervisor loop that launches worker subprocess and auto-restarts on crash."""
    logger.info(f"CODE OS v4.0.0 Watchdog started. Data dir: {DATA_DIR}")

    child_proc = None
    should_exit = False

    def handle_signal(sig, frame):
        nonlocal should_exit, child_proc
        logger.info(f"Received signal {sig}, terminating worker...")
        should_exit = True
        if child_proc and child_proc.poll() is None:
            try:
                child_proc.terminate()
                child_proc.wait(timeout=5)
            except Exception:
                try:
                    child_proc.kill()
                except Exception:
                    pass
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handle_signal)

    crash_timestamps = []
    MAX_RAPID_CRASHES = 5
    WINDOW_SECONDS = 30.0

    while not should_exit:
        if getattr(sys, "frozen", False):
            # In PyInstaller frozen bundle
            cmd = [sys.executable, "--worker"]
        else:
            # In raw Python environment
            cmd = [sys.executable, __file__, "--worker"]

        env = os.environ.copy()
        env["CODE_OS_WORKER"] = "1"

        logger.info(f"Spawning backend worker: {' '.join(cmd)}")
        try:
            child_proc = subprocess.Popen(cmd, env=env)
        except Exception as exc:
            logger.error(f"Failed to spawn worker process: {exc}")
            time.sleep(2)
            continue

        ret_code = child_proc.wait()
        child_proc = None

        if should_exit:
            break

        if ret_code == 0:
            logger.info("Backend worker exited cleanly (code 0). Watchdog stopping.")
            break
        else:
            now = time.time()
            crash_timestamps.append(now)
            # Filter crashes outside window
            crash_timestamps = [t for t in crash_timestamps if now - t <= WINDOW_SECONDS]

            logger.warning(
                f"Backend worker crashed with exit code {ret_code}! "
                f"({len(crash_timestamps)} crashes in past {WINDOW_SECONDS}s)"
            )

            if len(crash_timestamps) >= MAX_RAPID_CRASHES:
                logger.critical(
                    f"Circuit breaker tripped: {MAX_RAPID_CRASHES} crashes in {WINDOW_SECONDS}s. "
                    "Halting restart loop to prevent resource thrashing."
                )
                sys.exit(ret_code)

            logger.info("Auto-restarting backend worker in 1.0 second...")
            time.sleep(1.0)


# ── 5. Main Entry ─────────────────────────────────────────────────────────────

def main():
    if "--worker" in sys.argv or os.environ.get("CODE_OS_WORKER") == "1":
        run_worker()
    else:
        run_supervisor()


if __name__ == "__main__":
    main()
