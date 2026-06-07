import sys, time
sys.path.insert(0, '..')
sys.path.insert(0, '.')

from runner import GameRunner

r = GameRunner(0)
r.start(headless=False)
s = r.reset(stage=1)

starters = sorted(s.get("starters", []), key=lambda x: x.get("bst", 0), reverse=True)
s = r.act_starter(0, starters)
print("on screen:", s.get("screen"))

time.sleep(1)

# Snapshot localStorage before
before = r.page.evaluate("""() => {
    const out = {};
    for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        out[k] = localStorage.getItem(k);
    }
    return out;
}""")

# Open settings modal
r.page.evaluate("""() => {
    const btn = document.querySelector('button[title="Settings"]');
    if (btn) btn.click();
    else openSettingsModal?.();
}""")
time.sleep(0.5)

# Check all checkboxes
r.page.evaluate("""() => {
    document.querySelectorAll('.settings-checkbox').forEach(cb => {
        if (!cb.checked) cb.click();
    });
}""")
time.sleep(0.5)

# Snapshot after
after = r.page.evaluate("""() => {
    const out = {};
    for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        out[k] = localStorage.getItem(k);
    }
    return out;
}""")

# Show what changed
print("\nNew/changed localStorage keys after enabling settings:")
for k, v in after.items():
    if k not in before or before[k] != v:
        print(f"  {k} = {v}")

# Also show checkbox states
states = r.page.evaluate("""() =>
    [...document.querySelectorAll('.settings-checkbox')].map(cb => ({
        key: cb.dataset.key, checked: cb.checked
    }))
""")
print("\nCheckbox states:", states)

input("Press Enter to close...")
r.close()
