# Builds index.json and img/ from the repositories listed in mods.json, as each one is at its newest
# stable release: the obsidian.json and the README at that tag, the icon the manifest names and
# thumbnail.jpg, and the notes of the last releases. Obsidian reads index.json and the pictures from the raw
# files of this repository, so the Store costs no GitHub API call.
#
#   python tools/build.py            (uses GITHUB_TOKEN when set, else `gh auth token`, else no token)
#
# Needs Pillow. Writes only what changed: a picture is named after a hash of the source file, so an
# unchanged picture keeps its name and Obsidian keeps the copy it has.
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "img")
FORMAT = 1
VERSIONS = 10  # releases listed for each mod
ICON = (256, 256)
BANNER = (1280, 720)
# README sections a player doesn't need in the Store.
STOP = re.compile(r"^(install|installing|installation|building|build|development|license|credits|tests|testing|for mod authors|release|releasing|contributing|source)", re.I)


def token():
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    except OSError:
        return ""


TOKEN = token()


def get(url, api=False):
    req = urllib.request.Request(url, headers={"User-Agent": "ObsidianStoreIndex"})
    if api:
        req.add_header("Accept", "application/vnd.github+json")
        if TOKEN:
            req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def api(path):
    body = get("https://api.github.com" + path, api=True)
    return json.loads(body) if body is not None else None


def raw(repo, tag, path):
    return get(f"https://raw.githubusercontent.com/{repo}/{tag}/{path.lstrip('./')}")


def en(v):
    return (v.get("en") or next(iter(v.values()), "")) if isinstance(v, dict) else (v or "")


def channel(tag):
    v = tag.lstrip("vV")
    if "-" not in v:
        return "stable"
    word = re.match(r"[A-Za-z]*", v.split("-", 1)[1]).group(0).lower()
    return word or "pre"


def readme(text):
    text = re.sub(r"^# .*\n+", "", text.replace("\r\n", "\n"), count=1)
    out, size = [], 0
    for part in re.split(r"(?m)^(?=## )", text):
        head = part[3:].split("\n", 1)[0].strip() if part.startswith("## ") else ""
        if head and STOP.match(head):
            continue
        if size + len(part) > 6000 and out:
            break
        out.append(part.rstrip() + "\n\n")
        size += len(part)
    text = "".join(out).strip()
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # pictures in the README stay on GitHub
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def notes(body):
    body = (body or "").replace("\r\n", "\n").strip()
    return re.sub(r"^# .*\n+", "", body, count=1)


def picture(data, slug, kind, size):
    """A JPEG of the picture in img/, named after a hash of the source, and the path for index.json."""
    name = f"{slug}-{kind}-{hashlib.sha256(data).hexdigest()[:10]}.jpg"
    dest = os.path.join(IMG, name)
    if not os.path.exists(dest):
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail(size, Image.LANCZOS)
        im.save(dest, "JPEG", quality=85, optimize=True)
    return "img/" + name


def entry(repo, kit):
    latest = api(f"/repos/{repo}/releases/latest")
    releases = [r for r in (api(f"/repos/{repo}/releases?per_page=100") or []) if not r.get("draft")]
    if not latest and releases:
        latest = releases[0]
    if not latest:
        raise SystemExit(f"{repo}: no release")
    tag = latest["tag_name"]
    m = json.loads(raw(repo, tag, "obsidian.json"))
    slug = re.sub(r"[^a-z0-9]+", "-", m["id"].lower()).strip("-")
    # A picture comes from the release, else from main, else from dev: a new thumbnail can land before the next release.
    def pic(path):
        for ref in (tag, "main", "dev"):
            data = raw(repo, ref, path)
            if data:
                return data
        return None
    icon = banner = None
    if m.get("image"):
        data = pic(m["image"])
        icon = picture(data, slug, "icon", ICON) if data else None
    data = pic("thumbnail.jpg")
    banner = picture(data, slug, "banner", BANNER) if data else None
    text = raw(repo, tag, "README.md")
    version = m["version"]
    vers = [{"version": r["tag_name"].lstrip("vV"), "date": (r.get("published_at") or "")[:10] or None,
             "channel": channel(r["tag_name"]), "notes": notes(r.get("body"))} for r in releases[:VERSIONS]]
    dates = [r.get("published_at") for r in releases if r.get("published_at")]
    return {
        "id": m["id"],
        "name": en(m["name"]),
        "summary": en(m.get("description")),
        "description": readme(text.decode("utf-8")) if text else "",
        "version": version,
        "early": version.split(".")[0] == "0",
        "scope": m.get("scope", "unspecified"),
        "requires": m.get("requires", []),
        "options": len(m.get("options") or []),
        "option_list": [{"label": en(o.get("label")) or o.get("id", ""), "description": en(o.get("description")), "group": o.get("group")}
                        for o in m.get("options") or []],
        "option_groups": [{"id": g.get("id", ""), "label": en(g.get("label")) or g.get("id", "")} for g in m.get("option_groups") or []],
        "repo": repo,
        "kit": kit,
        "icon": icon,
        "banner": banner,
        "released": (latest.get("published_at") or "")[:10] or None,
        "added": min(dates)[:10] if dates else None,
        "versions": vers,
    }


def main():
    src = json.load(open(os.path.join(ROOT, "mods.json"), encoding="utf-8"))
    os.makedirs(IMG, exist_ok=True)
    mods = [entry(r, True) for r in src["kit"]] + [entry(r, False) for r in src["mods"]]
    ids = [m["id"] for m in mods]
    if len(set(ids)) != len(ids):
        raise SystemExit("two repositories give the same mod id")
    index = {"format": FORMAT, "mods": mods}
    with open(os.path.join(ROOT, "index.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
        f.write("\n")
    used = {os.path.basename(p) for m in mods for p in (m["icon"], m["banner"]) if p}
    for f in os.listdir(IMG):
        if f not in used:
            os.remove(os.path.join(IMG, f))
    for m in mods:
        print(f"{m['name']:<28} {m['version']:<16} {m['scope']:<10} icon={'y' if m['icon'] else '-'} banner={'y' if m['banner'] else '-'} versions={len(m['versions'])}")


if __name__ == "__main__":
    sys.exit(main())
