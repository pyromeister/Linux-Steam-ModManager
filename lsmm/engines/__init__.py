from lsmm.engines.bethesda import BethesdaEngine
from lsmm.engines.bepinex import BepInExEngine
from lsmm.engines.modfolder import ModFolderEngine
from lsmm.engines.rimworld import RimWorldEngine

_REGISTRY: dict[str, type] = {
    "bethesda": BethesdaEngine,
    "bepinex": BepInExEngine,
    "modfolder": ModFolderEngine,
    "rimworld": RimWorldEngine,
}


def load_engine(profile: dict):
    name = profile["engine"]
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown engine: {name!r}. Available: {sorted(_REGISTRY)}")
    return cls(profile)
