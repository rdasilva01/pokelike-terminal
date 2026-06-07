import sys, time
sys.path.insert(0, '..')
sys.path.insert(0, '.')

from runner import GameRunner
from screen_detector import detect

r = GameRunner(0)
r.start(headless=False)
s = r.reset(stage=1)
starters = sorted(s.get("starters", []), key=lambda x: x.get("bst", 0), reverse=True)
s = r.act_starter(0, starters)

print("Waiting for move upgrade screen... navigate until one appears, then press Enter here.")
input()

print("screen:", detect(r.page))
info = r.page.evaluate("""() => {
    const s = document.querySelector('.screen.active');
    return {
        id: s?.id,
        classes: s?.className,
        html: s?.innerHTML.slice(0, 1500),
        visible_btns: [...document.querySelectorAll('button')]
            .filter(b => b.getBoundingClientRect().width > 0)
            .map(b => ({text: b.textContent.trim(), cls: b.className})),
        all_elements_with_move: [...document.querySelectorAll('[class*="move"]')]
            .map(e => e.className).filter((v,i,a) => a.indexOf(v)===i).slice(0,20),
    }
}""")
print("screen id:", info["id"])
print("screen classes:", info["classes"])
print("visible buttons:", info["visible_btns"])
print("move-related classes:", info["all_elements_with_move"])
print("\nHTML preview:")
print(info["html"])

input("Press Enter to close...")
r.close()
