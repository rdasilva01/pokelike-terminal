import sys, time
sys.path.insert(0, '..')
sys.path.insert(0, '.')

from runner import GameRunner
from screen_detector import detect, ScreenType

r = GameRunner(0)
r.start(headless=False)

s = r.reset(stage=1)
print("after reset, screen:", s.get("screen"))
print("starters:", len(s.get("starters", [])))

# Pick first starter
starters = sorted(s.get("starters", []), key=lambda x: x.get("bst", 0), reverse=True)
print("picking:", starters[0]["name"])
s = r.act_starter(0, starters)
print("after starter pick, screen:", s.get("screen"))
print("nodes:", s.get("nodes", [])[:5])
print("team:", [(p.get("name"), p.get("level")) for p in s.get("team", [])])

time.sleep(1)

# Check what's in the SVG
svg_info = r.page.evaluate("""() => {
    const svg = document.querySelector('.screen.active svg');
    if (!svg) return {found: false};
    const gs = Array.from(svg.children).filter(el => el.tagName === 'g');
    const clickable = gs.filter(el => (el.getAttribute('style') || '').includes('pointer-events: auto'));
    const withImage = clickable.filter(el => el.querySelector('image'));
    return {
        found: true,
        total_g: gs.length,
        clickable_g: clickable.length,
        with_image: withImage.length,
        first_clickable_style: clickable[0]?.getAttribute('style'),
        all_g_styles: gs.slice(0,5).map(g => g.getAttribute('style')),
    };
}""")
print("\nSVG info:", svg_info)

# Try clicking and see what happens
print("\ntrying act_node(0)...")
s2 = r.act_node(0)
print("after node click, screen:", s2.get("screen"))
print("nodes now:", s2.get("nodes", [])[:5])

r.close()
