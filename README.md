# Obsidian Store Index

The list of mods the **STORE** tab of [Obsidian](https://github.com/Alomare/ObsidianLauncher) shows. Obsidian reads `index.json` and the pictures in `img/` from the raw files of this repository, and installs a mod from the newest release of the repository the index names.

## Files

| File | What it holds |
|---|---|
| `mods.json` | The repositories in the Store: `kit` for the Obsidian Kit, `mods` for the rest. Edited by hand. |
| `index.json` | Built from the releases. Do not edit. |
| `img/` | The icon and the thumbnail of each mod, built with `index.json`. |
| `tools/build.py` | The build. |

## How the index is built

`tools/build.py` reads each repository at the newest stable release (or the newest release, when none is stable):

- `obsidian.json`: id, name, description, version, scope, requirements and options.
- `README.md`: the text of the mod page, without the sections about installing, building, tests, credits and the license, and without pictures.
- The icon the manifest names and `thumbnail.jpg`, from the release, else from `main`, else from `dev`.
- The notes of the last ten releases, with the date and the channel (stable, beta and others, from the tag).

The workflow in `.github/workflows/build.yml` runs the build every six hours, on a change to `mods.json` or the build, and when started by hand, and commits only what changed.

To build by hand: `pip install pillow`, then `python tools/build.py`. The build uses `GITHUB_TOKEN` when it is set, else the token of the GitHub CLI.

## Adding a mod

A mod in the Store needs a public GitHub repository with:

- `obsidian.json` at the root.
- Releases tagged `v<version>`, with the mod ZIP attached.
- Optional: `thumbnail.jpg` at the root (16:9) and an icon named by `image` in the manifest.

Add the repository to `mods` in `mods.json`.

## Format

`index.json` holds `format` (now 1) and `mods`, a list of:

| Field | Meaning |
|---|---|
| `id`, `name`, `summary` | From `obsidian.json` (English). |
| `description` | Markdown from the README. |
| `version`, `released` | The newest stable release and the date. |
| `added` | The date of the first release. |
| `early` | The version starts with `0.` |
| `scope`, `requires`, `options` | From `obsidian.json`; `options` is the count. |
| `repo` | `owner/name` on GitHub. |
| `kit` | In the Obsidian Kit. |
| `icon`, `banner` | Paths in this repository, or null. |
| `versions` | `version`, `date`, `channel`, `notes`, newest first. |

A new field can be added without a new `format`. A change that older Obsidian versions would read wrong raises `format`, and those versions then show the Store as unavailable.
