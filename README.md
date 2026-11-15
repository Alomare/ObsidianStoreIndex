# Obsidian Store Index

The list of mods the **STORE** tab of [Obsidian](https://github.com/Alomare/ObsidianLauncher) shows. Obsidian reads `index.json` and the pictures in `img/` from the raw files of this repository, and installs a mod from the newest release of the repository the index names.

## Files

| File | What it holds |
|---|---|
| `mods.json` | The repositories in the Store: `kit` for the Obsidian Kit, `mods` for the rest, `verified`, the GitHub accounts whose mods carry the Obsidian Verified tag, and `private`, mods in early access from private repositories. Edited by hand. |
| `index.json` | Built from the releases. Do not edit. |
| `img/` | The icon and the thumbnail of each mod, built with `index.json`. |
| `tools/build.py` | The build. |
| `tools/validate.py` | The checks on a pull request that adds a mod (`tools/test_validate.py` tests the text rules and the change rules). |

## How the index is built

`tools/build.py` reads each repository at the newest stable release (or the newest release, when none is stable):

- `obsidian.json`: id, name, authors, version, scope, requirements and options.
- From `dev`, else `main`, else the release, so they can change between releases: the description in `obsidian.json`, `README.md` (the text of the mod page, without the sections about installing, building, tests, credits and the license, and without pictures), the icon the manifest names and `thumbnail.jpg`.
- The notes of the last ten releases, with the date and the channel (stable, beta and others, from the tag).

The workflow in `.github/workflows/build.yml` runs the build every six hours, on a change to `mods.json` or the build, and when started by hand, and commits only what changed.

To build by hand: `pip install pillow`, then `python tools/build.py`. The build uses `GITHUB_TOKEN` when it is set, else the token of the GitHub CLI.

## Adding a mod

A mod in the Store needs a public GitHub repository, not a fork and not archived, with:

- `obsidian.json` at the root, with `id`, `name`, `version`, a `scope` (`client`, `session`, `library` or `expansion`) and a `description` that serves as the summary.
- A stable release tagged `v<major>.<minor>.<patch>` (no pre-release part) whose version matches `version` in the manifest, with one mod ZIP attached (or one ZIP whose name holds the mod id). The ZIP holds `obsidian.json` at the root or in a single top folder.
- A `README.md` written in words.
- Optional: `thumbnail.jpg` at the root (16:9) and an icon named by `image` in the manifest.

## Submitting a mod

Mods are submitted from Obsidian: **STORE** tab, **Submit a mod**, while signed in to GitHub. Obsidian checks the repository first, then opens a pull request that appends the repository to `mods` in `mods.json`.

The workflow in `.github/workflows/validate.yml` runs `tools/validate.py` on the pull request. The checks run from the base branch, and the pull request fails unless:

- The only change is repositories appended to `mods`. Changes to `kit`, `verified` and `private` are made by the maintainer only.
- Each added repository exists, is public, is not a fork or archived, is not listed yet, and belongs to the author of the pull request. For a repository of an organization, membership is checked by hand.
- The newest stable release meets the requirements above, and the manifest in the ZIP parses and declares a scope.
- The mod id is not used by another mod in the Store. Ids starting with `obsidian.` are reserved for the Obsidian Kit.
- Every mod in `requires` is in the Store.
- The name, the summary and the README read as text: not too short or too long, no placeholders, no keyboard mashing, no long runs of one letter, not all capitals. The rules are the same as in Obsidian.

The maintainer then reviews the pull request and merges it. The next build adds the mod to `index.json`.

To run the checks by hand: `python tools/validate.py --base <mods.json of the base branch> --author <GitHub login>`, which reads `mods.json` and `index.json` of this folder.

## Early access

A mod in a private repository can be listed under `private` in `mods.json`. The build cannot read private repositories, so each entry is written by hand:

```json
"private": [
  {"repo": "owner/name", "id": "owner.mod", "name": "Mod name", "summary": "One line about the mod.", "scope": "client"}
]
```

The build checks each entry (`repo` is `owner/name`, `id` follows the id rule of Obsidian and is not used by a public mod, `scope` is one of the four, `name` and `summary` are not empty) and copies it to `private` in `index.json`.

## Format

`index.json` holds `format` (now 1) and `mods`, a list of:

| Field | Meaning |
|---|---|
| `id`, `name`, `summary`, `authors` | From `obsidian.json` (English). |
| `verified` | The owner of the repository is listed in `verified` in `mods.json`. |
| `description` | Markdown from the README. |
| `version`, `released` | The newest stable release and the date. |
| `added` | The date of the first release. |
| `early` | The version starts with `0.` |
| `scope`, `requires`, `options` | From `obsidian.json`; `options` is the count. |
| `repo` | `owner/name` on GitHub. |
| `stars` | The stars of the repository on GitHub, at the time of the build. |
| `downloads` | Downloads of every asset of every published release, added up at the time of the build. |
| `kit` | In the Obsidian Kit. |
| `icon`, `banner` | Paths in this repository, or null. |
| `versions` | `version`, `date`, `channel`, `notes`, newest first. |

`private`, present when `mods.json` lists early access mods, is a list of `repo`, `id`, `name`, `summary`, `scope` (copied from `mods.json`) and `verified`.

A new field can be added without a new `format`. A change that older Obsidian versions would read wrong raises `format`, and those versions then show the Store as unavailable.
