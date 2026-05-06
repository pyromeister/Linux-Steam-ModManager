"""FOMOD XML installer parser — zip archives only."""

import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_VALID_GROUP_TYPES = {
    "SelectExactlyOne", "SelectAny", "SelectAll", "SelectAtLeastOne", "SelectAtMostOne"
}
_DEFAULT_GROUP_TYPE = "SelectAny"

_VALID_TYPE_DESCRIPTORS = {"Required", "Recommended", "Optional", "NotUsable", "CouldBeUsable"}
_DEFAULT_TYPE_DESCRIPTOR = "Optional"

_MAX_XML_BYTES = 4 * 1024 * 1024  # 4 MB cap — sane upper bound for ModuleConfig.xml


@dataclass
class FomodPlugin:
    name: str
    description: str
    files: list[tuple[str, str]]
    type_descriptor: str


@dataclass
class FomodGroup:
    name: str
    type: str
    plugins: list[FomodPlugin]


@dataclass
class FomodStep:
    name: str
    groups: list[FomodGroup]


@dataclass
class FomodConfig:
    name: str
    required_files: list[tuple[str, str]]
    steps: list[FomodStep]


def _find_config_member(names: list[str]) -> str | None:
    for n in names:
        if n.lower() == "fomod/moduleconfig.xml":
            return n
    return None


def _parse_files(parent) -> list[tuple[str, str]]:
    result = []
    if parent is None:
        return result
    for tag in ("file", "folder"):
        for el in parent.findall(tag):
            src = el.get("source", "")
            dst = el.get("destination", Path(src).name)
            result.append((src, dst))
    return result


def _parse_plugin(el) -> FomodPlugin:
    name = el.get("name", "")
    desc_el = el.find("description")
    description = (desc_el.text or "").strip() if desc_el is not None else ""
    files = _parse_files(el.find("files"))
    td = el.find("typeDescriptor/type")
    if td is not None and td.get("value") in _VALID_TYPE_DESCRIPTORS:
        type_descriptor = td.get("value")
    else:
        type_descriptor = _DEFAULT_TYPE_DESCRIPTOR
    return FomodPlugin(name=name, description=description, files=files, type_descriptor=type_descriptor)


def _parse_group(el) -> FomodGroup:
    name = el.get("name", "")
    gtype = el.get("type", _DEFAULT_GROUP_TYPE)
    if gtype not in _VALID_GROUP_TYPES:
        gtype = _DEFAULT_GROUP_TYPE
    plugins = [_parse_plugin(p) for p in el.findall("plugins/plugin")]
    return FomodGroup(name=name, type=gtype, plugins=plugins)


def _parse_step(el) -> FomodStep:
    name = el.get("name", "")
    groups = [_parse_group(g) for g in el.findall("optionalFileGroups/group")]
    return FomodStep(name=name, groups=groups)


def _parse_xml(xml_bytes: bytes) -> FomodConfig | None:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    mod_name = ""
    name_el = root.find("moduleName")
    if name_el is not None:
        mod_name = (name_el.text or "").strip()

    req_parent = root.find("requiredInstallFiles")
    required_files = _parse_files(req_parent)

    steps = [_parse_step(s) for s in root.findall("installSteps/installStep")]

    return FomodConfig(name=mod_name, required_files=required_files, steps=steps)


def detect_fomod(archive_path: Path) -> FomodConfig | None:
    try:
        with zipfile.ZipFile(archive_path) as zf:
            member = _find_config_member(zf.namelist())
            if member is None:
                return None
            if zf.getinfo(member).file_size > _MAX_XML_BYTES:
                return None
            xml_bytes = zf.read(member)
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    return _parse_xml(xml_bytes)
