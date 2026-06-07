"""
game_env.py — gymnasium.Env wrapping one headless Playwright browser.

Observation: ~316-dim float32 flat vector (see _encode_obs).
Action:       57-dim discrete with action masking (MaskablePPO).
"""
import sys
from pathlib import Path

import numpy as np
import gymnasium as gym
from gymnasium import spaces

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from screen_detector import ScreenType

from runner import GameRunner, TYPE_IDX
from reward import compute_reward
from config import (
    N_ACTIONS, N_TYPES, N_NODE_TYPES, N_SCREENS, N_MAP_NODES, N_TEAM_SLOTS,
    N_STARTER_SLOTS, N_CATCH_SLOTS, N_ITEM_SLOTS, N_BAG_ITEMS, N_SWAP_PAIRS,
    N_TUTOR_SLOTS, KNOWN_ITEMS, MAX_STEPS_PER_EPISODE,
)

# ---------------------------------------------------------------------------
# Vocab tables
# ---------------------------------------------------------------------------

SCREEN_NAMES = [
    "main_menu", "starter_select", "map", "catch_pokemon", "battle",
    "item_select", "item_equip", "trade_offer", "team_full", "unknown",
]

NODE_TYPES = [
    "unknown", "trainer", "boss", "catch", "pokecenter",
    "item", "move_tutor", "mystery", "trade", "start", "legendary", "wild",
]
NODE_TYPE_IDX = {t: i for i, t in enumerate(NODE_TYPES)}

# 15 unordered swap pairs for a 6-member team
SWAP_PAIRS = [(i, j) for i in range(6) for j in range(i + 1, 6)]  # 15 entries

# ---------------------------------------------------------------------------
# Observation dimension breakdown (must match _encode_obs exactly)
# ---------------------------------------------------------------------------
#   screen one-hot                       10
#   stage / region / map progress         3
#   team  (6 slots × 5 features)         30
#   map nodes (23 × 3)                   69
#   upcoming boss types (3 × 18)         54
#   catch choices (5 × 5)               25
#   starter choices (20 × 4)            80
#   item choices (5 × 1)                 5
#   bag items (20 binary)               20
#   remaining-starters type hist (18)    18
#   -------                             ---
#   total                               314

OBS_DIM = 10 + 3 + 30 + 69 + 54 + 25 + 80 + 5 + 20 + 18  # 314


def _type_idx(name: str) -> float:
    return TYPE_IDX.get((name or "").lower().capitalize(), 0) / N_TYPES


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

class PokelikeEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, env_idx: int = 0, stage: int = 1):
        super().__init__()
        self.env_idx = env_idx
        self.stage   = stage
        self.runner  = GameRunner(env_idx)

        self.observation_space = spaces.Box(0.0, 1.0, shape=(OBS_DIM,), dtype=np.float32)
        self.action_space      = spaces.Discrete(N_ACTIONS)

        self._prev_state: dict | None = None
        self._curr_state: dict        = {}
        self._step_count: int         = 0
        self._caught_shiny: bool      = False
        self._starters_sorted: list   = []
        self._prev_badges: int        = 0

    # ------------------------------------------------------------------ obs

    def _encode_obs(self, state: dict) -> np.ndarray:
        obs = np.zeros(OBS_DIM, dtype=np.float32)
        p = 0

        # Screen (10)
        screen = state.get("screen", ScreenType.UNKNOWN)
        sname  = screen.name.lower() if isinstance(screen, ScreenType) else str(screen).lower()
        for i, n in enumerate(SCREEN_NAMES):
            if n.replace("_", "") in sname.replace("_", ""):
                obs[p + i] = 1.0
                break
        p += 10

        # Stage / region / map (3) — rough progress proxy
        obs[p]     = self.stage / 5.0
        obs[p + 1] = 0.0  # region (TODO: extract from state if parser exposes it)
        obs[p + 2] = 0.0  # map within region
        p += 3

        # Team (6 × 5 = 30)
        team = state.get("team", [])
        for i, poke in enumerate(team[:N_TEAM_SLOTS]):
            types = poke.get("types", [])
            obs[p + i * 5]     = _type_idx(types[0] if types else "")
            obs[p + i * 5 + 1] = _type_idx(types[1] if len(types) > 1 else "")
            obs[p + i * 5 + 2] = min(poke.get("level", 0) / 100.0, 1.0)
            obs[p + i * 5 + 3] = float(poke.get("hp_pct", 1.0) or 1.0)
            obs[p + i * 5 + 4] = 1.0 if poke.get("held_item") else 0.0
        p += 30

        # Map nodes (23 × 3 = 69)
        nodes = state.get("nodes", [])
        for i, node in enumerate(nodes[:N_MAP_NODES]):
            ntype = NODE_TYPE_IDX.get(node.get("type", "unknown"), 0) / len(NODE_TYPES)
            obs[p + i * 3]     = ntype
            obs[p + i * 3 + 1] = 1.0 if node.get("accessible") else 0.0
            obs[p + i * 3 + 2] = 1.0 if node.get("state") == "completed" else 0.0
        p += 69

        # Upcoming boss types (3 × 18 = 54)
        boss_types = state.get("upcoming_boss_types", [])
        for bi, bt in enumerate(boss_types[:3]):
            ti = TYPE_IDX.get(bt.lower().capitalize(), 0)
            if ti > 0 and bi * 18 + ti - 1 < 54:
                obs[p + bi * 18 + (ti - 1)] = 1.0
        p += 54

        # Catch choices (5 × 5 = 25)
        choices = state.get("choices", [])
        for i, ch in enumerate(choices[:N_CATCH_SLOTS]):
            types = ch.get("types", [])
            obs[p + i * 5]     = _type_idx(types[0] if types else "")
            obs[p + i * 5 + 1] = _type_idx(types[1] if len(types) > 1 else "")
            obs[p + i * 5 + 2] = min((ch.get("level") or 0) / 100.0, 1.0)
            obs[p + i * 5 + 3] = 1.0 if ch.get("is_shiny") else 0.0
            obs[p + i * 5 + 4] = 1.0 if ch.get("is_caught") else 0.0
        p += 25

        # Starter choices top-20 (20 × 4 = 80)
        for i, s in enumerate(self._starters_sorted[:N_STARTER_SLOTS]):
            types = s.get("types", [])
            obs[p + i * 4]     = _type_idx(types[0] if types else "")
            obs[p + i * 4 + 1] = _type_idx(types[1] if len(types) > 1 else "")
            obs[p + i * 4 + 2] = 1.0 if s.get("is_shiny") else 0.0
            obs[p + i * 4 + 3] = min(s.get("bst", 400) / 700.0, 1.0)
        p += 80

        # Item choices (5 × 1 = 5) — name vocab index
        item_choices = state.get("choices", []) if "item" in sname else []
        for i, item in enumerate(item_choices[:N_ITEM_SLOTS]):
            name = item.get("name", "")
            obs[p + i] = (KNOWN_ITEMS.index(name) + 1) / len(KNOWN_ITEMS) if name in KNOWN_ITEMS else 0.0
        p += 5

        # Bag items (20 binary)
        bag_names = {b.get("name", "") for b in state.get("bag", [])}
        for i, iname in enumerate(KNOWN_ITEMS[:N_BAG_ITEMS]):
            obs[p + i] = 1.0 if iname in bag_names else 0.0
        p += 20

        # Remaining-starters type histogram (18)
        if len(self._starters_sorted) > N_STARTER_SLOTS:
            rest = self._starters_sorted[N_STARTER_SLOTS:]
            counts = np.zeros(18, dtype=np.float32)
            for s in rest:
                for t in s.get("types", []):
                    ti = TYPE_IDX.get(t.lower().capitalize(), 0)
                    if ti > 0:
                        counts[ti - 1] += 1
            mx = counts.max()
            if mx > 0:
                counts /= mx
            obs[p:p + 18] = counts
        p += 18  # noqa: F841

        return obs

    # ------------------------------------------------------------------ mask

    def _get_action_mask(self, state: dict) -> np.ndarray:
        mask = np.zeros(N_ACTIONS, dtype=bool)
        screen = state.get("screen", ScreenType.UNKNOWN)
        sname  = screen.name.lower() if isinstance(screen, ScreenType) else str(screen).lower()

        if "map" in sname:
            nodes = state.get("nodes", [])
            accessible = [n for n in nodes if n.get("accessible") and n.get("state") != "completed"]
            mask[0] = len(accessible) >= 1
            mask[1] = len(accessible) >= 2
            if not mask[0]:
                mask[0] = True  # always allow at least one node action on map
            team = state.get("team", [])
            if len(team) >= 2:
                for i in range(N_SWAP_PAIRS):
                    mask[39 + i] = True
            bag = state.get("bag", [])
            for i in range(min(3, len(bag))):
                mask[54 + i] = True

        elif "catch" in sname:
            choices = state.get("choices", [])
            n = len(choices)
            for i in range(min(n, N_CATCH_SLOTS)):
                mask[2 + i] = True   # catch slot
                mask[7 + i] = True   # reroll slot
            mask[12] = True  # skip

        elif "item" in sname and "equip" not in sname:
            choices = state.get("choices", [])
            for i in range(min(len(choices), N_ITEM_SLOTS)):
                mask[13 + i] = True
            mask[18] = True  # skip

        elif "item_equip" in sname or "equip" in sname:
            pokemon = state.get("pokemon", [])
            n = len(pokemon)
            for i in range(min(n, N_TUTOR_SLOTS)):
                mask[57 + i] = True
            mask[63] = True  # always allow skip

        elif "starter" in sname or "team_select" in sname:
            for i in range(min(N_STARTER_SLOTS, len(self._starters_sorted))):
                mask[19 + i] = True

        # Fallback — never send all-False mask to MaskablePPO
        if not mask.any():
            mask[0] = True
        return mask

    # ------------------------------------------------------------------ decode

    @staticmethod
    def decode_action(action: int) -> tuple[str, int | tuple]:
        if 0 <= action <= 1:
            return "node", action
        if 2 <= action <= 6:
            return "catch", action - 2
        if 7 <= action <= 11:
            return "reroll", action - 7
        if action == 12:
            return "skip_catch", 0
        if 13 <= action <= 17:
            return "item", action - 13
        if action == 18:
            return "skip_item", 0
        if 19 <= action <= 38:
            return "starter", action - 19
        if 39 <= action <= 53:
            return "swap", SWAP_PAIRS[action - 39]
        if 54 <= action <= 56:
            return "equip", action - 54
        if 57 <= action <= 62:
            return "move_tutor", action - 57
        if action == 63:
            return "skip_tutor", 0
        return "noop", 0

    # ------------------------------------------------------------------ gymnasium API

    def action_masks(self) -> np.ndarray:
        return self._get_action_mask(self._curr_state)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._step_count   = 0
        self._caught_shiny = False
        self._prev_state   = None
        self._prev_badges  = 0
        self._starters_sorted = []

        state = self.runner.reset(stage=self.stage)

        # Cache and sort starters if we landed on the starter/team-select screen
        screen = state.get("screen", ScreenType.UNKNOWN)
        sname = screen.name if isinstance(screen, ScreenType) else str(screen).upper()
        if any(x in sname for x in ("STARTER", "TEAM_SELECT")):
            starters = state.get("starters", [])
            self._starters_sorted = sorted(starters, key=lambda s: s.get("bst", 400), reverse=True)

        self._curr_state = state
        obs  = self._encode_obs(state)
        mask = self._get_action_mask(state)
        return obs, {"action_mask": mask}

    def step(self, action: int):
        self._step_count += 1
        info: dict = {}
        state = self._curr_state
        screen = state.get("screen", ScreenType.UNKNOWN)
        sname  = screen.name.lower() if isinstance(screen, ScreenType) else str(screen).lower()

        action_type, param = self.decode_action(action)

        # Shiny scouting on catch screen
        if "catch" in sname:
            for ch in state.get("choices", []):
                if ch.get("is_shiny"):
                    info["shiny_seen"] = True
                    self._caught_shiny = True
                    break

        # Execute
        if action_type == "node":
            new_state = self.runner.act_node(param)
        elif action_type == "catch":
            choices = state.get("choices", [])
            slot = min(param, len(choices) - 1)
            if slot >= 0 and choices[slot].get("is_shiny"):
                info["caught_shiny"] = True
                self._caught_shiny   = True
            else:
                info["caught_nonshiny"] = True
            new_state = self.runner.act_catch(slot)
        elif action_type == "reroll":
            info["reroll_used"] = True
            new_state = self.runner.act_reroll(param)
        elif action_type == "skip_catch":
            info["skip_catch"] = True
            new_state = self.runner.act_skip_catch()
        elif action_type == "item":
            new_state = self.runner.act_item(param)
        elif action_type == "skip_item":
            new_state = self.runner.act_skip_item()
        elif action_type == "starter":
            new_state = self.runner.act_starter(param, self._starters_sorted)
        elif action_type == "swap":
            new_state = self.runner.act_swap(*param)
        elif action_type == "equip":
            new_state = self.runner.act_equip(param)
        elif action_type == "move_tutor":
            new_state = self.runner.act_move_tutor(param)
        elif action_type == "skip_tutor":
            new_state = self.runner.act_skip_tutor()
        else:
            new_state = state

        # Detect map boss completion via badge count increase
        curr_badges = new_state.get("badges", 0) or 0
        if curr_badges > self._prev_badges:
            info["map_boss_beaten"] = True
            self._prev_badges = curr_badges

        # Terminal checks
        game_over      = self.runner.is_game_over()
        stage_complete = self.runner.is_stage_complete()

        if game_over:
            info["game_over"] = True
        if stage_complete:
            info["stage_complete"]        = True
            info["caught_shiny_this_run"] = self._caught_shiny

        terminated = game_over or stage_complete
        truncated  = self._step_count >= MAX_STEPS_PER_EPISODE

        reward = compute_reward(self._prev_state, new_state, action, info)

        self._prev_state = state
        self._curr_state = new_state

        obs  = self._encode_obs(new_state)
        mask = self._get_action_mask(new_state)
        info["action_mask"] = mask

        return obs, reward, terminated, truncated, info

    def close(self):
        self.runner.close()
