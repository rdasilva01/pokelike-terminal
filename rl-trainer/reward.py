from config import *


def compute_reward(
    prev: dict | None,
    curr: dict,
    action: int,
    info: dict,
) -> float:
    r = RW_PER_STEP

    if info.get("game_over"):
        return r + RW_GAME_OVER

    if info.get("stage_complete"):
        r += RW_STAGE_COMPLETE
        if info.get("caught_shiny_this_run"):
            r += RW_SHINY_BONUS_ON_WIN

    if info.get("shiny_seen"):
        r += RW_SHINY_SIGHTED

    if info.get("caught_nonshiny"):
        r += RW_CATCH_NONSHINY

    if info.get("skip_catch"):
        r += RW_SKIP_CATCH

    if info.get("reroll_used"):
        r += RW_REROLL

    # Progress signals derived from state delta
    if prev is not None:
        prev_nodes_done = sum(1 for n in prev.get("nodes", []) if n.get("state") == "completed")
        curr_nodes_done = sum(1 for n in curr.get("nodes", []) if n.get("state") == "completed")
        if curr_nodes_done > prev_nodes_done:
            r += RW_NODE_ADVANCED * (curr_nodes_done - prev_nodes_done)

    if info.get("map_boss_beaten"):
        r += RW_MAP_BOSS_BEATEN

    return r
