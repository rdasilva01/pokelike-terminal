from typing import TypedDict, Optional


class MainMenuState(TypedDict):
    screen: str
    selected_gen: Optional[str]
    available_gens: list[str]
    logged_in_user: Optional[str]


class StarterInfo(TypedDict):
    name: str
    level: str
    types: list[str]
    move: str


class StarterSelectState(TypedDict):
    screen: str
    starters: list[StarterInfo]


class StageInfo(TypedDict):
    number: Optional[int]
    boss: Optional[str]
    boss_type: Optional[str]


class TeamSlot(TypedDict):
    name: str
    level: Optional[int]
    hp_pct: int


class MapNode(TypedDict):
    index: int
    type: str    # start, trainer, wild_encounter, catch_pokemon, move_tutor, mystery, pokecenter, shop, item, boss
    state: str   # completed, available, locked
    accessible: bool
    sprite: str


class MapState(TypedDict):
    screen: str
    stage: StageInfo
    team: list[TeamSlot]
    bag: list[str]
    badges: int
    nodes: list[MapNode]
