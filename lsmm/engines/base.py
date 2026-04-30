"""
BaseEngine — abstract interface all engine plugins must implement.
The GUI reads capability flags to decide which panels to show.
"""

from abc import ABC, abstractmethod
from pathlib import Path


class BaseEngine(ABC):
    # --- Capability flags (GUI reads these) ---
    has_load_order: bool = False
    has_script_extender: bool = False
    has_activation_toggle: bool = False

    def __init__(self, game_profile: dict):
        self.profile = game_profile

    # --- Required ---

    @abstractmethod
    def install(self, archive_path: Path, mod_name: str = None) -> None:
        """Extract archive and install mod files to the correct locations."""

    @abstractmethod
    def uninstall(self, mod_name: str) -> None:
        """Remove all files belonging to mod_name."""

    @abstractmethod
    def list_mods(self) -> list[dict]:
        """Return list of installed mods: [{name, active, files}]"""

    # --- Load order (only implement if has_load_order = True) ---

    def get_load_order(self) -> list[str]:
        raise NotImplementedError

    def set_load_order(self, order: list[str]) -> None:
        raise NotImplementedError

    def move_mod(self, mod_name: str, new_position: int) -> None:
        order = self.get_load_order()
        if mod_name not in order:
            raise ValueError(f"Mod not in load order: {mod_name}")
        order.remove(mod_name)
        order.insert(new_position, mod_name)
        self.set_load_order(order)

    # --- Activation (only implement if has_activation_toggle = True) ---

    def enable_mod(self, mod_name: str) -> None:
        raise NotImplementedError

    def disable_mod(self, mod_name: str) -> None:
        raise NotImplementedError
