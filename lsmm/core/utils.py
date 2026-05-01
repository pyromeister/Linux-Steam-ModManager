"""Shared game-query helpers used across GUI modules."""

import json

from lsmm.core.config import load_profile, GAMES_DIR, USER_GAMES_DIR


def load_engine(game: str):
    profile = load_profile(game)
    profile["slug"] = game
    engine_name = profile["engine"]
    if engine_name == "bethesda":
        from lsmm.engines.bethesda import BethesdaEngine
        return BethesdaEngine(profile)
    if engine_name == "bepinex":
        from lsmm.engines.bepinex import BepInExEngine
        return BepInExEngine(profile)
    if engine_name == "rimworld":
        from lsmm.engines.rimworld import RimWorldEngine
        return RimWorldEngine(profile)
    if engine_name == "modfolder":
        from lsmm.engines.modfolder import ModFolderEngine
        return ModFolderEngine(profile)
    raise ValueError(f"Engine '{engine_name}' not yet implemented")


def available_games() -> list:
    games: dict[str, str] = {}
    for p in GAMES_DIR.glob("*.json"):
        try:
            games[p.stem] = json.loads(p.read_text())["name"]
        except Exception:
            continue
    if USER_GAMES_DIR.exists():
        for p in USER_GAMES_DIR.glob("*.json"):
            try:
                games[p.stem] = json.loads(p.read_text())["name"]
            except Exception:
                continue
    return sorted(games.items())


def find_game_by_nexus_domain(domain: str) -> str | None:
    for slug, _ in available_games():
        try:
            if load_profile(slug).get("nexus_domain", "").lower() == domain.lower():
                return slug
        except Exception:
            continue
    return None
