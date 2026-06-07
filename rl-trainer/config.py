from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).parent.parent
POKEDEX_JSON = REPO_ROOT / "pokelike-local" / "data" / "pokedex.json"

# Server
LOCAL_URL = "http://localhost:8080/"

# Training
N_ENVS = 4
MAX_STEPS_PER_EPISODE = 600
STARTING_STAGE = 1

# Curriculum: min mean episode reward to unlock next stage
CURRICULUM_THRESHOLDS = {1: 400, 2: 600, 3: 800, 4: 1000}

# Action timeouts (seconds)
ACTION_WAIT_TIMEOUT = 10.0
SCREEN_SETTLE_DELAY = 0.35

# Action space dimensions
N_STARTER_SLOTS = 20   # top-20 by BST shown to agent
N_CATCH_SLOTS   = 5
N_ITEM_SLOTS    = 5
N_SWAP_PAIRS    = 15   # C(6,2)
N_EQUIP_SLOTS   = 3
N_TUTOR_SLOTS   = 6   # max team size; teach move to slot 0-5
N_ACTIONS = 2 + N_CATCH_SLOTS + N_CATCH_SLOTS + 1 + N_ITEM_SLOTS + 1 + N_STARTER_SLOTS + N_SWAP_PAIRS + N_EQUIP_SLOTS + N_TUTOR_SLOTS + 1
# = 2+5+5+1+5+1+20+15+3+6+1 = 64

# Observation dimensions (see game_env.py for breakdown)
N_TYPES      = 18
N_NODE_TYPES = 12
N_SCREENS    = 10
N_MAP_NODES  = 23
N_TEAM_SLOTS = 6
N_BAG_ITEMS  = 20   # known item vocab size

# Known item vocab (item_idx is position in this list; 0 = unknown)
KNOWN_ITEMS = [
    "Charcoal", "Mystic Water", "Miracle Seed", "Magnet", "Twisted Spoon",
    "Never-Melt Ice", "Black Belt", "Poison Barb", "Soft Sand", "Sharp Beak",
    "Spell Tag", "Dragon Fang", "BlackGlasses", "Metal Coat", "Silk Scarf",
    "Hard Stone", "Silver Powder", "King's Rock", "Scope Lens", "Wide Lens",
]

# Reward weights
RW_STAGE_COMPLETE      = 1000.0
RW_SHINY_BONUS_ON_WIN  =  500.0
RW_SHINY_SIGHTED       =  100.0
RW_MAP_BOSS_BEATEN     =  150.0
RW_NODE_ADVANCED       =   10.0
RW_CATCH_NONSHINY      =   15.0
RW_GAME_OVER           = -500.0
RW_PER_STEP            =   -0.1
RW_REROLL              =   -0.5
RW_SKIP_CATCH          =   -5.0

# PPO hyperparams
PPO_N_STEPS          = 512
PPO_BATCH_SIZE       = 64
PPO_N_EPOCHS         = 4
PPO_LR               = 3e-4
PPO_GAMMA            = 0.99
PPO_ENT_COEF         = 0.05   # encourages exploration; prevents policy collapse
PPO_TOTAL_TIMESTEPS  = 500_000
