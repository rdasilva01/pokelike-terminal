import shutil
import subprocess
import sys
import time
from pathlib import Path

from config import LOCAL_URL, USE_LOCAL

if sys.platform == "win32":
    CHROME_PATHS = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    CHROME_USER_DATA = r"C:\ChromeDebug"
else:
    CHROME_PATHS = []   # resolved via PATH on Linux
    CHROME_USER_DATA = str(Path.home() / ".chrome-debug")

_START_URL = LOCAL_URL if USE_LOCAL else "https://pokelike.xyz/"

CHROME_ARGS = [
    "--remote-debugging-port=9222",
    f"--user-data-dir={CHROME_USER_DATA}",
    _START_URL,
]

# Linux binary names to try (in order)
LINUX_CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]


def find_chrome() -> str:
    if sys.platform == "win32":
        for path in CHROME_PATHS:
            if Path(path).exists():
                return str(path)
        raise FileNotFoundError(
            "Chrome not found. Set CHROME_PATHS at the top of launcher.py."
        )
    else:
        for name in LINUX_CHROME_NAMES:
            found = shutil.which(name)
            if found:
                return found
        raise FileNotFoundError(
            f"Chrome not found. Install google-chrome or chromium-browser, "
            f"or set LINUX_CHROME_NAMES in launcher.py."
        )


def main():
    try:
        chrome = find_chrome()
    except FileNotFoundError as e:
        print(f"[Error] {e}")
        sys.exit(1)

    print(f"[Launcher] Starting Chrome: {chrome}")
    subprocess.Popen([chrome, *CHROME_ARGS])

    print("[Launcher] Waiting for Chrome to start...")
    time.sleep(2)

    print("[Launcher] Launching interactor...\n")
    import interactor
    interactor.main()


if __name__ == "__main__":
    main()
