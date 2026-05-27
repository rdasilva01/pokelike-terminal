import subprocess
import sys
import time
from pathlib import Path

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
]

CHROME_ARGS = [
    "--remote-debugging-port=9222",
    "--user-data-dir=C:\\ChromeDebug",
    "https://pokelike.xyz/",
]


def find_chrome() -> str:
    for path in CHROME_PATHS:
        if Path(path).exists():
            return str(path)
    raise FileNotFoundError(
        "Chrome not found in default locations. "
        "Set CHROME_PATH at the top of launcher.py to your chrome.exe path."
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
