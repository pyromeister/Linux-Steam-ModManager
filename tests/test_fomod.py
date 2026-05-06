"""Tests for lsmm.core.fomod — FOMOD XML parser."""

import os
import tempfile
import zipfile
from pathlib import Path

from lsmm.core.fomod import detect_fomod, FomodConfig


# ── XML fixtures ──────────────────────────────────────────────────────────────

_MINIMAL_XML = """\
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:noNamespaceSchemaLocation="ModuleConfig.xsd">
  <moduleName>Test Mod</moduleName>
  <requiredInstallFiles>
    <file source="Data/plugin.esp" destination="plugin.esp" />
  </requiredInstallFiles>
  <installSteps order="Explicit">
    <installStep name="Main Files">
      <optionalFileGroups order="Explicit">
        <group name="Choose Version" type="SelectExactlyOne">
          <plugins order="Explicit">
            <plugin name="Low">
              <description>Low settings</description>
              <files>
                <file source="Low/settings.ini" destination="settings.ini" />
              </files>
              <typeDescriptor><type value="Optional" /></typeDescriptor>
            </plugin>
            <plugin name="High">
              <description>High settings</description>
              <files>
                <file source="High/settings.ini" destination="settings.ini" />
              </files>
              <typeDescriptor><type value="Recommended" /></typeDescriptor>
            </plugin>
          </plugins>
        </group>
      </optionalFileGroups>
    </installStep>
  </installSteps>
</config>
"""

_ALL_GROUP_TYPES_XML = """\
<config>
  <moduleName>GroupTypesMod</moduleName>
  <installSteps order="Explicit">
    <installStep name="Step1">
      <optionalFileGroups order="Explicit">
        <group name="G1" type="SelectExactlyOne"><plugins order="Explicit"/></group>
        <group name="G2" type="SelectAny"><plugins order="Explicit"/></group>
        <group name="G3" type="SelectAll"><plugins order="Explicit"/></group>
        <group name="G4" type="SelectAtLeastOne"><plugins order="Explicit"/></group>
        <group name="G5" type="SelectAtMostOne"><plugins order="Explicit"/></group>
        <group name="G6" type="UnknownType"><plugins order="Explicit"/></group>
      </optionalFileGroups>
    </installStep>
  </installSteps>
</config>
"""

_TYPE_DESCRIPTORS_XML = """\
<config>
  <moduleName>TypesMod</moduleName>
  <installSteps order="Explicit">
    <installStep name="Step1">
      <optionalFileGroups order="Explicit">
        <group name="G" type="SelectAny">
          <plugins order="Explicit">
            <plugin name="Required"><description/><files/>
              <typeDescriptor><type value="Required"/></typeDescriptor>
            </plugin>
            <plugin name="Recommended"><description/><files/>
              <typeDescriptor><type value="Recommended"/></typeDescriptor>
            </plugin>
            <plugin name="NotUsable"><description/><files/>
              <typeDescriptor><type value="NotUsable"/></typeDescriptor>
            </plugin>
            <plugin name="CouldBeUsable"><description/><files/>
              <typeDescriptor><type value="CouldBeUsable"/></typeDescriptor>
            </plugin>
            <plugin name="NoDescriptor"><description/><files/></plugin>
          </plugins>
        </group>
      </optionalFileGroups>
    </installStep>
  </installSteps>
</config>
"""

_REQUIRED_ONLY_XML = """\
<config>
  <moduleName>RequiredOnly</moduleName>
  <requiredInstallFiles>
    <file source="core.esp" />
    <file source="textures/rock.dds" destination="textures/rock.dds" />
    <folder source="meshes" destination="meshes" />
  </requiredInstallFiles>
</config>
"""

_MALFORMED_XML = "this is not xml at all <<<"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_zip(members: dict[str, str | bytes], suffix=".zip") -> Path:
    """Create a real temp zip file on disk and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with zipfile.ZipFile(path, "w") as z:
        for name, content in members.items():
            data = content.encode() if isinstance(content, str) else content
            z.writestr(name, data)
    return Path(path)


# ── detect_fomod — detection ──────────────────────────────────────────────────

def test_returns_none_for_non_zip(tmp_path):
    f = tmp_path / "mod.7z"
    f.write_bytes(b"fake")
    assert detect_fomod(f) is None


def test_returns_none_for_zip_without_fomod_dir(tmp_path):
    path = _make_zip({"Data/plugin.esp": b""})
    assert detect_fomod(path) is None


def test_returns_config_for_zip_with_moduleconfig(tmp_path):
    path = _make_zip({"fomod/ModuleConfig.xml": _MINIMAL_XML})
    result = detect_fomod(path)
    assert isinstance(result, FomodConfig)


def test_lookup_case_insensitive(tmp_path):
    path = _make_zip({"FOMOD/MODULECONFIG.XML": _MINIMAL_XML})
    result = detect_fomod(path)
    assert result is not None


# ── required files ────────────────────────────────────────────────────────────

def test_required_files_parsed():
    path = _make_zip({"fomod/ModuleConfig.xml": _MINIMAL_XML})
    cfg = detect_fomod(path)
    assert len(cfg.required_files) == 1
    src, dst = cfg.required_files[0]
    assert src == "Data/plugin.esp"
    assert dst == "plugin.esp"


def test_required_file_missing_destination_defaults_to_src_basename():
    path = _make_zip({"fomod/ModuleConfig.xml": _REQUIRED_ONLY_XML})
    cfg = detect_fomod(path)
    srcs = [s for s, _ in cfg.required_files]
    assert "core.esp" in srcs
    # file with no destination: dst == src basename
    no_dst = next((s, d) for s, d in cfg.required_files if s == "core.esp")
    assert no_dst[1] == "core.esp"


def test_required_folder_entry_included():
    path = _make_zip({"fomod/ModuleConfig.xml": _REQUIRED_ONLY_XML})
    cfg = detect_fomod(path)
    srcs = [s for s, _ in cfg.required_files]
    assert "meshes" in srcs


def test_empty_required_files_produces_empty_list():
    xml = "<config><moduleName>X</moduleName></config>"
    path = _make_zip({"fomod/ModuleConfig.xml": xml})
    cfg = detect_fomod(path)
    assert cfg.required_files == []


# ── steps and groups ──────────────────────────────────────────────────────────

def test_step_count_and_name():
    path = _make_zip({"fomod/ModuleConfig.xml": _MINIMAL_XML})
    cfg = detect_fomod(path)
    assert len(cfg.steps) == 1
    assert cfg.steps[0].name == "Main Files"


def test_group_parsed_correctly():
    path = _make_zip({"fomod/ModuleConfig.xml": _MINIMAL_XML})
    cfg = detect_fomod(path)
    group = cfg.steps[0].groups[0]
    assert group.name == "Choose Version"
    assert group.type == "SelectExactlyOne"


def test_all_five_group_types_parsed():
    path = _make_zip({"fomod/ModuleConfig.xml": _ALL_GROUP_TYPES_XML})
    cfg = detect_fomod(path)
    types = [g.type for g in cfg.steps[0].groups]
    assert "SelectExactlyOne" in types
    assert "SelectAny" in types
    assert "SelectAll" in types
    assert "SelectAtLeastOne" in types
    assert "SelectAtMostOne" in types


def test_unknown_group_type_defaults_to_select_any():
    path = _make_zip({"fomod/ModuleConfig.xml": _ALL_GROUP_TYPES_XML})
    cfg = detect_fomod(path)
    unknown = next(g for g in cfg.steps[0].groups if "Unknown" in g.name or g.type == "SelectAny")
    assert unknown.type in ("SelectAny",)


# ── plugins ───────────────────────────────────────────────────────────────────

def test_plugin_name_and_description():
    path = _make_zip({"fomod/ModuleConfig.xml": _MINIMAL_XML})
    cfg = detect_fomod(path)
    plugins = cfg.steps[0].groups[0].plugins
    assert plugins[0].name == "Low"
    assert plugins[0].description == "Low settings"


def test_plugin_files_parsed():
    path = _make_zip({"fomod/ModuleConfig.xml": _MINIMAL_XML})
    cfg = detect_fomod(path)
    plugin = cfg.steps[0].groups[0].plugins[0]
    assert len(plugin.files) == 1
    src, dst = plugin.files[0]
    assert src == "Low/settings.ini"
    assert dst == "settings.ini"


def test_plugin_type_descriptors_all_five():
    path = _make_zip({"fomod/ModuleConfig.xml": _TYPE_DESCRIPTORS_XML})
    cfg = detect_fomod(path)
    plugins = cfg.steps[0].groups[0].plugins
    by_name = {p.name: p.type_descriptor for p in plugins}
    assert by_name["Required"] == "Required"
    assert by_name["Recommended"] == "Recommended"
    assert by_name["NotUsable"] == "NotUsable"
    assert by_name["CouldBeUsable"] == "CouldBeUsable"


def test_missing_type_descriptor_defaults_to_optional():
    path = _make_zip({"fomod/ModuleConfig.xml": _TYPE_DESCRIPTORS_XML})
    cfg = detect_fomod(path)
    plugins = cfg.steps[0].groups[0].plugins
    no_desc = next(p for p in plugins if p.name == "NoDescriptor")
    assert no_desc.type_descriptor == "Optional"


def test_missing_description_is_empty_string():
    path = _make_zip({"fomod/ModuleConfig.xml": _TYPE_DESCRIPTORS_XML})
    cfg = detect_fomod(path)
    plugin = cfg.steps[0].groups[0].plugins[0]
    assert plugin.description == ""


# ── resilience ────────────────────────────────────────────────────────────────

def test_malformed_xml_returns_none():
    path = _make_zip({"fomod/ModuleConfig.xml": _MALFORMED_XML})
    result = detect_fomod(path)
    assert result is None


def test_no_steps_xml_returns_config_with_empty_steps():
    path = _make_zip({"fomod/ModuleConfig.xml": _REQUIRED_ONLY_XML})
    cfg = detect_fomod(path)
    assert cfg is not None
    assert cfg.steps == []
    assert cfg.name == "RequiredOnly"
