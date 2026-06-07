import sys, time
sys.path.insert(0, '..')
sys.path.insert(0, '.')

from runner import GameRunner
from screen_detector import detect, ScreenType

r = GameRunner(0)
r.start(headless=False)
s = r.reset(stage=1)
starters = sorted(s.get("starters", []), key=lambda x: x.get("bst", 0), reverse=True)
s = r.act_starter(0, starters)

# Navigate to a catch node
print("Navigating nodes to find a catch screen...")
for _ in range(10):
    screen = detect(r.page)
    if screen == ScreenType.CATCH_POKEMON:
        break
    s = r.act_node(0)
    print(f"  screen: {detect(r.page)}")
    if detect(r.page) == ScreenType.CATCH_POKEMON:
        break

s = r.parse_state()
print("\nCatch screen state:")
print("  screen:", s.get("screen"))
choices = s.get("choices", [])
print("  choices:", len(choices))
for i, c in enumerate(choices):
    print(f"    [{i}] {c.get('name')} lv{c.get('level')} shiny={c.get('is_shiny')}")

# Check what .poke-choice-wrap looks like
dom = r.page.evaluate("""() => {
    const wraps = document.querySelectorAll('.screen.active .poke-choice-wrap');
    return {
        count: wraps.length,
        visible: [...wraps].filter(w => w.getBoundingClientRect().width > 0).length,
        first_html: wraps[0]?.outerHTML.slice(0, 300),
    }
}""")
print("\n.poke-choice-wrap in DOM:")
print("  count:", dom["count"])
print("  visible:", dom["visible"])
print("  first:", dom["first_html"])

print("\nTrying act_catch(0)...")
s2 = r.act_catch(0)
print("After catch, screen:", s2.get("screen"))

input("Press Enter to close...")
r.close()
