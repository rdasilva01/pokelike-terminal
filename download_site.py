"""
download_site.py — Download pokelike.xyz for local play.

Intercepts all network responses, navigates through key game screens
to trigger lazy-loaded assets, and saves everything to pokelike-local/.

Run: python download_site.py
"""
import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

BASE_URL = "https://pokelike.xyz"
OUT_DIR = Path(__file__).parent / "pokelike-local"

_saved: set[Path] = set()
_skipped_external: set[str] = set()
_errors: list[str] = []


def _url_to_path(url: str) -> Path | None:
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    if host not in ("pokelike.xyz", ""):
        _skipped_external.add(f"{parsed.scheme}://{parsed.netloc}")
        return None
    path = parsed.path.lstrip("/") or "index.html"
    if path.endswith("/"):
        path += "index.html"
    return OUT_DIR / path


async def _save_response(response) -> None:
    url = response.url
    if response.status != 200:
        return
    dest = _url_to_path(url)
    if dest is None or dest in _saved:
        return
    try:
        body = await response.body()
    except Exception as e:
        _errors.append(f"body() failed: {url} — {e}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    _saved.add(dest)
    print(f"  + {dest.relative_to(OUT_DIR)}")


def _rewrite_urls() -> None:
    print("\n[rewrite] Patching absolute URLs in HTML/JS/CSS...")
    for suffix in (".html", ".js", ".css"):
        for f in OUT_DIR.rglob(f"*{suffix}"):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                original = text
                text = re.sub(r'https?://(?:www\.)?pokelike\.xyz/', '/', text)
                text = re.sub(r'https?://(?:www\.)?pokelike\.xyz(?=["\'/\s])', '', text)
                if text != original:
                    f.write_text(text, encoding="utf-8")
                    print(f"  patched {f.relative_to(OUT_DIR)}")
            except Exception as e:
                print(f"  WARN: could not patch {f.name}: {e}")


async def _try_click(page, selector: str, label: str, wait: float = 2.0) -> bool:
    try:
        el = page.locator(selector).first
        if await el.is_visible(timeout=2000):
            await el.click()
            await asyncio.sleep(wait)
            print(f"  clicked: {label}")
            return True
    except Exception:
        pass
    return False


async def _navigate_screens(page) -> None:
    """Click through key screens to trigger lazy-loaded assets."""
    print("\n[navigate] Exploring screens to trigger lazy-loaded assets...")

    await asyncio.sleep(5)

    # Main menu → Normal Mode
    clicked = await _try_click(page, "button.btn-primary:has-text('Normal')", "Normal Mode", 3.0)
    if not clicked:
        await _try_click(page, "button.btn-primary", "first btn-primary", 3.0)

    # Starter select — pick first starter
    await _try_click(page, ".poke-card", "first poke-card (starter)", 2.0)
    await _try_click(page, "button.btn-primary:has-text('Choose')", "Choose starter", 3.0)

    # Wait for map
    await asyncio.sleep(4)

    # Try clicking first available map node
    await _try_click(page, ".node-btn:not([disabled])", "first map node", 4.0)

    # Wait on whatever screen landed
    await asyncio.sleep(6)

    print("  [navigate] done — waiting for trailing requests...")


async def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    print(f"[download] Output: {OUT_DIR}")
    print(f"[download] Source: {BASE_URL}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        page.on("response", lambda r: asyncio.ensure_future(_save_response(r)))

        await page.goto(BASE_URL, wait_until="domcontentloaded")
        print("[download] Page loaded — waiting for network idle...")

        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass  # networkidle may timeout on SPAs; fine

        await _navigate_screens(page)

        # Final drain
        await asyncio.sleep(5)
        await browser.close()

    _rewrite_urls()

    print(f"\n{'='*60}")
    print(f"  Saved:    {len(_saved)} files  →  {OUT_DIR}/")
    if _skipped_external:
        print(f"  External (not saved):")
        for origin in sorted(_skipped_external):
            print(f"    {origin}")
    if _errors:
        print(f"  Errors ({len(_errors)}):")
        for e in _errors[:10]:
            print(f"    {e}")
    print("=" * 60)
    print("\nNext step: python serve_local.py")


if __name__ == "__main__":
    asyncio.run(main())
