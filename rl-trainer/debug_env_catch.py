import sys
sys.path.insert(0, '..')
sys.path.insert(0, '.')

from game_env import PokelikeEnv

env = PokelikeEnv(env_idx=0, stage=1)
env.runner.start(headless=False)

obs, info = env.reset()

ACTION_NAMES = (
    ["node_L", "node_R"] +
    [f"catch_{i}" for i in range(5)] +
    [f"reroll_{i}" for i in range(5)] +
    ["skip_catch"] +
    [f"item_{i}" for i in range(5)] +
    ["skip_item"] +
    [f"starter_{i}" for i in range(20)] +
    [f"swap_{i}" for i in range(15)] +
    [f"equip_{i}" for i in range(3)] +
    [f"tutor_{i}" for i in range(6)] +
    ["skip_tutor"]
)

for step in range(50):
    mask = env.action_masks()
    screen = env._curr_state.get("screen")
    enabled = [ACTION_NAMES[i] for i, m in enumerate(mask) if m]
    print(f"[step {step}] screen={screen}  enabled={enabled}")

    if "catch" in str(screen).lower():
        print("  >>> ON CATCH SCREEN — forcing catch action 2")
        obs, reward, done, trunc, info = env.step(2)
        print(f"  >>> after catch: screen={env._curr_state.get('screen')} reward={reward:.1f}")
        break

    # Pick first enabled non-skip action, or first enabled
    pick = next((i for i, m in enumerate(mask) if m and "skip" not in ACTION_NAMES[i]), None)
    if pick is None:
        pick = next((i for i, m in enumerate(mask) if m), 0)
    obs, reward, done, trunc, info = env.step(pick)
    if done:
        print("  episode ended")
        break

env.close()
