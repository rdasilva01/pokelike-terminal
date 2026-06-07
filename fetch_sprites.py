"""
fetch_sprites.py — Download all pokelike.xyz node/trainer sprites that the
download_site.py crawler misses (they only load dynamically when the map renders).

Uses Playwright so requests carry proper browser headers/cookies (the server
returns 403 to plain urllib requests due to hotlink protection).

Run: python fetch_sprites.py
"""
import asyncio
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "https://pokelike.xyz/"
OUT  = Path(__file__).parent / "pokelike-local"

SPRITES = [
    # ── node type icons ──────────────────────────────────────────────────
    "sprites/grass.png",
    "sprites/catchPokemon.png",
    "sprites/itemIcon.png",
    "sprites/tradeIcon.png",
    "sprites/legendaryEncounter.png",
    "sprites/questionMark.png",
    "sprites/Poke Center.png",
    "sprites/moveTutor.png",
    "sprites/misteryTrainer.png",
    "sprites/champ.png",

    # ── Kanto gym leaders ────────────────────────────────────────────────
    "sprites/brock.png",
    "sprites/misty.png",
    "sprites/lt. surge.png",
    "sprites/erika.png",
    "sprites/koga.png",
    "sprites/sabrina.png",
    "sprites/blaine.png",
    "sprites/giovanni.png",

    # ── random trainer types ─────────────────────────────────────────────
    "sprites/aceTrainer.png",
    "sprites/bugCatcher.png",
    "sprites/fireSpitter.png",
    "sprites/fisher.png",
    "sprites/hiker.png",
    "sprites/oldGuy.png",
    "sprites/policeman.png",
    "sprites/Scientist.png",
    "sprites/teamRocket.png",
    "sprites/birdCatcher.png",
    "sprites/biker.png",
    "sprites/nerd.png",
    "sprites/medium.png",
    "sprites/schoolBoy.png",
    "sprites/captain.png",

    # ── gen2 node icons ──────────────────────────────────────────────────
    "sprites/gen2/grass.png",
    "sprites/gen2/pokeball.png",

    # ── gen2 trainer types ───────────────────────────────────────────────
    "sprites/gen2/aceTrainer.png",
    "sprites/gen2/bugCatcher.png",
    "sprites/gen2/fireBreather.png",
    "sprites/gen2/fisher.png",
    "sprites/gen2/hiker.png",
    "sprites/gen2/oldMan.png",
    "sprites/gen2/policeman.png",
    "sprites/gen2/Scientist.png",
    "sprites/gen2/teamRocket.png",
    "sprites/gen2/birdCatcher.png",
    "sprites/gen2/biker.png",
    "sprites/gen2/nerd.png",
    "sprites/gen2/medium.png",
    "sprites/gen2/schoolBoy.png",
    "sprites/gen2/captain.png",

    # ── Johto gym leaders ────────────────────────────────────────────────
    "sprites/gen2/falkner.png",
    "sprites/gen2/bugsy.png",
    "sprites/gen2/whitney.png",
    "sprites/gen2/morty.png",
    "sprites/gen2/chuck.png",
    "sprites/gen2/jasmine.png",
    "sprites/gen2/pryce.png",
    "sprites/gen2/clair.png",
    "sprites/gen2/lance.png",
    "sprites/gen2/silver.png",

    # ── Kanto badge sprites (1–8), Johto (9–16) ─────────────────────────
    *[f"sprites/badges/{i}.png" for i in range(1, 17)],

    # ── item sprites ─────────────────────────────────────────────────────
    "sprites/items/loaded_dice.png",

    # ── endless-mode trainers (sprites/trainers/) ────────────────────────
    "sprites/trainers/aaron.png",
    "sprites/trainers/aceTrainer.png",
    "sprites/trainers/agatha-lgpe.png",
    "sprites/trainers/anabel-gen7.png",
    "sprites/trainers/ash-johto.png",
    "sprites/trainers/benga.png",
    "sprites/trainers/bertha.png",
    "sprites/trainers/blaine.png",
    "sprites/trainers/blue.png",
    "sprites/trainers/brawly.png",
    "sprites/trainers/brock.png",
    "sprites/trainers/brock-lgpe.png",
    "sprites/trainers/bugcatcher.png",
    "sprites/trainers/bugsy.png",
    "sprites/trainers/clay.png",
    "sprites/trainers/clemont.png",
    "sprites/trainers/colress.png",
    "sprites/trainers/cynthia.png",
    "sprites/trainers/cyrus.png",
    "sprites/trainers/dawn.png",
    "sprites/trainers/drake-gen3.png",
    "sprites/trainers/erika.png",
    "sprites/trainers/erika-lgpe.png",
    "sprites/trainers/eusine.png",
    "sprites/trainers/falkner.png",
    "sprites/trainers/fisherman.png",
    "sprites/trainers/flint.png",
    "sprites/trainers/gardenia-masters.png",
    "sprites/trainers/ghetsis.png",
    "sprites/trainers/glacia.png",
    "sprites/trainers/grimsley.png",
    "sprites/trainers/hiker.png",
    "sprites/trainers/iris-gen5bw2.png",
    "sprites/trainers/janine.png",
    "sprites/trainers/jasmine.png",
    "sprites/trainers/juan.png",
    "sprites/trainers/koga.png",
    "sprites/trainers/lorelei-lgpe.png",
    "sprites/trainers/ltsurge.png",
    "sprites/trainers/lucian.png",
    "sprites/trainers/marshal.png",
    "sprites/trainers/misty.png",
    "sprites/trainers/misty-lgpe.png",
    "sprites/trainers/n.png",
    "sprites/trainers/phoebe-masters.png",
    "sprites/trainers/red.png",
    "sprites/trainers/roark.png",
    "sprites/trainers/sabrina.png",
    "sprites/trainers/sabrina-gen3.png",
    "sprites/trainers/sabrina-lgpe.png",
    "sprites/trainers/scientist.png",
    "sprites/trainers/silver-masters.png",
    "sprites/trainers/steven-gen6.png",
    "sprites/trainers/teamrocket.png",
    "sprites/trainers/volkner.png",
    "sprites/trainers/wattson.png",
    "sprites/trainers/whitney.png",
    "sprites/trainers/youngster.png",
]


async def fetch_all() -> None:
    if not OUT.exists():
        print(f"[error] {OUT} not found — run download_site.py first.")
        return

    ok = fail = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            base_url=BASE,
            extra_http_headers={"Referer": BASE},
        )
        # Visit the root page first so cookies/session are established
        page = await context.new_page()
        await page.goto(BASE, wait_until="domcontentloaded")

        for path in SPRITES:
            url  = BASE + urllib.parse.quote(path, safe="/.")
            dest = OUT / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                resp = await page.request.get(url, headers={"Referer": BASE})
                if resp.ok:
                    dest.write_bytes(await resp.body())
                    print(f"  + {path}")
                    ok += 1
                else:
                    print(f"  - SKIP {path}  (HTTP {resp.status})")
                    fail += 1
            except Exception as e:
                print(f"  - SKIP {path}  ({e})")
                fail += 1

        await browser.close()

    print(f"\nDone: {ok} saved, {fail} not found on server.")


if __name__ == "__main__":
    asyncio.run(fetch_all())
