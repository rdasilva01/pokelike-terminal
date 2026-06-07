import sys, time
sys.path.insert(0, '..')
sys.path.insert(0, '.')

from playwright.sync_api import sync_playwright
import tempfile
from pathlib import Path
from runner import _build_unlock_payload
from screen_detector import detect

with sync_playwright() as pw:
    profile = Path(tempfile.gettempdir()) / "pokelike_dbg3"
    profile.mkdir(exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(str(profile), headless=True)
    page = ctx.new_page()

    page.goto("http://localhost:8080/", wait_until="domcontentloaded", timeout=15000)
    time.sleep(1.5)

    payload = _build_unlock_payload()
    page.evaluate("""(p) => {
        const d = JSON.parse(p);
        localStorage.setItem('poke_hall_of_fame', JSON.stringify(d.hof));
        localStorage.setItem('poke_hof_index',    JSON.stringify(d.hofIndex));
        localStorage.setItem('poke_dex',          JSON.stringify(d.dex));
        localStorage.setItem('poke_elite_wins',   '20');
        localStorage.setItem('poke_tutorial_seen','true');
        localStorage.setItem('poke_trainer',      'boy');
    }""", payload)

    page.reload(wait_until="domcontentloaded", timeout=15000)
    time.sleep(1.5)

    page.evaluate("document.getElementById('btn-endless-run')?.click()")
    time.sleep(1)

    page.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button'))
            .filter(b => b.getBoundingClientRect().width > 0 && b.textContent.includes('Gen'));
        if (btns[0]) btns[0].click();
    }""")
    time.sleep(1)

    if page.evaluate("!!document.getElementById('trainer-boy')"):
        page.evaluate("document.getElementById('trainer-boy').click()")
        time.sleep(0.8)

    print("screen:", detect(page))

    info = page.evaluate("""() => {
        const s = document.querySelector('.screen.active');
        return {
            id: s?.id,
            visible_btns: [...document.querySelectorAll('button')]
                .filter(b => b.getBoundingClientRect().width > 0)
                .map(b => b.textContent.trim()),
            preview: s?.innerHTML.slice(0, 800),
        }
    }""")
    print("id:", info["id"])
    print("visible buttons:", info["visible_btns"])
    print("html preview:", info["preview"])

    ctx.close()
