"""
Load order file manager — reads/writes Plugins.txt (Bethesda format).
Preserves comment lines and blank lines exactly as-is.
Format: *Active.esm | InactiveMod.esm | # comment
"""

from pathlib import Path
from dataclasses import dataclass


@dataclass
class PluginEntry:
    name: str
    active: bool

    def __str__(self):
        return f"{'*' if self.active else ''}{self.name}"


@dataclass
class PluginsFile:
    path: Path
    _lines: list  # mix of PluginEntry and raw str (comments/blanks)

    @classmethod
    def read(cls, path: Path) -> "PluginsFile":
        if not path.exists():
            return cls(path=path, _lines=[])
        lines = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                lines.append(raw)  # preserve as-is
            elif stripped.startswith("*"):
                lines.append(PluginEntry(name=stripped[1:], active=True))
            else:
                lines.append(PluginEntry(name=stripped, active=False))
        return cls(path=path, _lines=lines)

    def write(self) -> None:
        self.path.write_text(
            "\n".join(str(line) for line in self._lines) + "\n",
            encoding="utf-8",
        )

    @property
    def plugins(self) -> list[PluginEntry]:
        return [e for e in self._lines if isinstance(e, PluginEntry)]

    def get(self, name: str) -> PluginEntry | None:
        return next((p for p in self.plugins if p.name == name), None)

    def add(self, name: str, active: bool = True) -> None:
        if self.get(name):
            return  # already present
        self._lines.append(PluginEntry(name=name, active=active))

    def remove(self, name: str) -> None:
        self._lines = [
            e for e in self._lines
            if not (isinstance(e, PluginEntry) and e.name == name)
        ]

    def set_active(self, name: str, active: bool) -> None:
        entry = self.get(name)
        if entry:
            entry.active = active

    def get_order(self) -> list[str]:
        return [p.name for p in self.plugins]

    def set_order(self, order: list[str]) -> None:
        """Reorder plugins to match `order`. Unknown names appended at end."""
        plugin_map = {p.name: p for p in self.plugins}
        non_plugins = [e for e in self._lines if not isinstance(e, PluginEntry)]

        ordered = []
        for name in order:
            if name in plugin_map:
                ordered.append(plugin_map.pop(name))
        # Append any plugins not mentioned in order (e.g. vanilla masters)
        ordered.extend(plugin_map.values())

        # Rebuild: put comments first, then ordered plugins
        self._lines = non_plugins + ordered

    def print_list(self) -> None:
        for p in self.plugins:
            status = "✓" if p.active else "✗"
            print(f"  [{status}] {p.name}")
