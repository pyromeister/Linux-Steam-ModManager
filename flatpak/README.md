# LSMM Flatpak

App ID: `io.github.pyromeister.lsmm`

## Prerequisites

```bash
# Install flatpak-builder
sudo apt install flatpak-builder   # Debian/Ubuntu
sudo dnf install flatpak-builder   # Fedora

# Install GNOME 47 runtime + SDK
flatpak install flathub org.gnome.Platform//47 org.gnome.Sdk//47
```

## Build & run locally

From the repo root:

```bash
flatpak-builder --user --install --force-clean build-flatpak \
    flatpak/io.github.pyromeister.lsmm.yml

flatpak run io.github.pyromeister.lsmm
```

## NXM handler

The `nxm://` protocol handler is registered automatically when the Flatpak is installed — no manual step needed. The `.desktop` file declares `MimeType=x-scheme-handler/nxm` and `update-desktop-database` runs as part of the install.

If you have another app (e.g. Vortex via Proton) that also claims `nxm://` and want LSMM to take priority, run:

```bash
xdg-mime default io.github.pyromeister.lsmm.desktop x-scheme-handler/nxm
```

## Flathub submission checklist

- [ ] Build + install locally confirmed working
- [ ] Run on Steam Deck (or SteamOS VM) confirmed
- [ ] `appstreamcli validate flatpak/io.github.pyromeister.lsmm.metainfo.xml` passes
- [ ] Screenshots added to metainfo (Flathub requires at least one)
- [ ] Fork https://github.com/flathub/flathub and open PR
- [ ] Add `io.github.pyromeister.lsmm.yml` to root of Flathub PR
  (update `sources` to point to tagged GitHub archive, not local `type: dir`)

## Flathub source adjustment

For Flathub submission, change the lsmm module sources from:

```yaml
sources:
  - type: dir
    path: ..
```

to a tagged release archive:

```yaml
sources:
  - type: archive
    url: https://github.com/pyromeister/Linux-Steam-ModManager/archive/refs/tags/v0.1.1.tar.gz
    sha256: <compute with: curl -sL <url> | sha256sum>
```
