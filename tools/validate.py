# Checks a pull request that adds mods to the Store. Obsidian runs the same checks before it opens the
# pull request (core/src/submit.rs in the Launcher), but a pull request can come from anywhere, so the
# index checks again. Keep text_problem and readme_words identical to the Rust ones.
#
#   python tools/validate.py --base <base mods.json> --author <login>
#       [--head <pr mods.json>] [--index <index.json>] [--files <list of changed files>]
#
# --head defaults to mods.json in this repository and --index to index.json here. Uses GITHUB_TOKEN when
# set, else `gh auth token`. Exits 1 with the list of problems, also written to $GITHUB_STEP_SUMMARY.
import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")  # the mod id rule of Obsidian (manifest.rs valid_id)
TAG = re.compile(r"^v(\d+\.\d+\.\d+)(\+[0-9A-Za-z.-]+)?$")  # stable: no pre-release part
SCOPES = ("client", "session", "library", "expansion")
ZIP_CAP = 200 * 1024 * 1024
MANIFEST_CAP = 1024 * 1024
MAINTAINER = "alomare"

JUNK = ["lorem ipsum", "asdf", "qwerty", "zxcv", "hjkl", "test test", "todo", "tbd", "placeholder", "description here",
        "your description", "mod name", "my mod", "example mod", "untitled"]


def text_problem(text, kind):
    """Why `text` is not readable as a `kind` ("name", "summary", "readme"), or None when it is."""
    text = text.strip()
    n = len(text)
    lo, hi = {"name": (3, 40), "summary": (20, 500)}.get(kind, (150, float("inf")))
    if n < lo:
        return "short"
    if n > hi:
        return "long"
    lower = text.lower()
    squashed = "".join(c for c in lower if c.isalnum() or c == " ").strip()
    if any(squashed == j or (kind != "name" and j in squashed) for j in JUNK) or squashed in ("test", "mod"):
        return "placeholder"
    visible = [c for c in text if not c.isspace()]
    letters = sum(1 for c in visible if c.isalpha())
    if letters * 2 < len(visible):
        return "symbols"
    run, last = 1, None
    for c in lower:
        run = run + 1 if c == last else 1
        last = c
        if run >= 5:
            return "repeated"
    words = text.split()
    # Latin script: words are split by spaces and carry a fair share of vowels.
    ascii_l = [c for c in lower if c.isascii() and c.isalpha()]
    latin = len(ascii_l) * 2 >= letters
    if kind != "name" and latin and len(words) < (4 if kind == "summary" else 30):
        return "words"
    if any(len(w) > 30 and "://" not in w and "/" not in w and "`" not in w for w in words):
        return "gibberish"
    if len(ascii_l) >= 10 and latin:
        v = sum(1 for c in ascii_l if c in "aeiouy") / len(ascii_l)
        if not (0.2 <= v <= 0.7):
            return "gibberish"
    upper = sum(1 for c in text if c.isupper())
    if kind != "name" and letters >= 12 and upper * 10 >= letters * 8:
        return "shouting"
    return None


def readme_words(md):
    """README text without the Markdown that is not words: code blocks, link and picture addresses, tags."""
    out = []
    fence = False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        kept, depth, i = [], 0, 0
        while i < len(line):
            c = line[i]
            i += 1
            if c == "<":
                depth += 1
            elif c == ">" and depth > 0:
                depth -= 1
            elif c == "]" and i < len(line) and line[i] == "(":
                end = line.find(")", i)
                i = len(line) if end < 0 else end + 1
            elif depth == 0 and c not in "#*_`|![":
                kept.append(c)
        out.append("".join(kept).strip() + "\n")
    return "".join(out)


def en(v):
    if isinstance(v, dict):
        return v.get("en") or next(iter(v.values()), "") or ""
    return v if isinstance(v, str) else ""


def diff_problems(base, head):
    """Problems with the change from base to head mods.json, and the repositories appended to `mods`."""
    problems = []
    if not isinstance(head, dict):
        return ["mods.json is not a JSON object"], []
    for key in sorted(set(base) | set(head)):
        if key == "mods":
            continue
        if base.get(key) != head.get(key):
            problems.append(f"`{key}` changed: only the maintainer edits it")
    old, new = base.get("mods") or [], head.get("mods")
    if not isinstance(new, list) or not all(isinstance(r, str) for r in new):
        return problems + ["`mods` must be a list of repository names"], []
    if new[:len(old)] != old:
        problems.append("entries of `mods` were changed, removed or reordered: only appending is allowed")
        return problems, []
    added = new[len(old):]
    if not added:
        problems.append("no repository was added to `mods`")
    return problems, added


def token():
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    except OSError:
        return ""


TOKEN = None


def request(url, accept="application/vnd.github+json", auth=True):
    req = urllib.request.Request(url, headers={"User-Agent": "ObsidianStoreIndex", "Accept": accept})
    if auth and TOKEN and url.startswith("https://api.github.com"):
        req.add_header("Authorization", f"Bearer {TOKEN}")
    return urllib.request.urlopen(req, timeout=120)


def api(path, raw=False):
    try:
        with request("https://api.github.com" + path, "application/vnd.github.raw" if raw else "application/vnd.github+json") as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return body.decode("utf-8", "replace") if raw else json.loads(body)


def download(url, dest):
    """Writes url to dest, refusing more than ZIP_CAP bytes."""
    size = 0
    with request(url, "application/octet-stream", auth=False) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                return True
            size += len(chunk)
            if size > ZIP_CAP:
                return False
            f.write(chunk)


def zip_manifest(path):
    """The text of obsidian.json in the zip, at the root or in a single top folder, or an error string."""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return None, "the release asset is not a valid ZIP"
    with z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if "obsidian.json" in names:
            member = "obsidian.json"
        else:
            tops = {n.split("/", 1)[0] for n in z.namelist()}
            member = f"{next(iter(tops))}/obsidian.json" if len(tops) == 1 else None
            if member not in names:
                return None, "no obsidian.json at the root of the ZIP or in a single top folder"
        info = z.getinfo(member)
        if info.file_size > MANIFEST_CAP:
            return None, "obsidian.json in the ZIP is too large"
        return z.read(member).decode("utf-8-sig", "replace"), None


def check_manifest(m, tag_version, owner, index_ids):
    """Problems with a parsed manifest; also returns the display name and summary."""
    problems = []
    if not isinstance(m, dict):
        return ["obsidian.json is not a JSON object"], "", ""
    mid = m.get("id")
    if not isinstance(mid, str) or not ID.match(mid):
        problems.append("manifest `id` must be 1 to 64 lowercase letters, digits, '.', '_' or '-', starting with a letter or digit")
        mid = None
    if m.get("version") != tag_version:
        problems.append(f"manifest `version` ({m.get('version')}) differs from the release tag ({tag_version})")
    name = m.get("name")
    if not (isinstance(name, str) or (isinstance(name, dict) and name and all(isinstance(v, str) for v in name.values()))):
        problems.append("manifest `name` must be a string or a map of languages to strings")
        name = ""
    if m.get("scope") not in SCOPES:
        problems.append(f"manifest `scope`: declare a scope ({', '.join(SCOPES)})")
    if mid:
        if mid in index_ids:
            problems.append(f"the id {mid} is already used by a mod in the Store")
        if mid.startswith("obsidian.") and owner.lower() != MAINTAINER:
            problems.append(f"the id {mid} is reserved: ids starting with obsidian. belong to the Obsidian Kit")
    requires = m.get("requires") or []
    if not isinstance(requires, list):
        problems.append("manifest `requires` must be a list of mod ids")
        requires = []
    for need in requires:
        if need not in index_ids:
            problems.append(f"requires {need}, which is not in the Store")
    desc = m.get("description")
    return problems, en(name), en(desc) if isinstance(desc, (str, dict)) else ""


def text_problems(name, summary, readme):
    problems = []
    for kind, label, text in (("name", "name", name), ("summary", "summary (manifest `description`)", summary)):
        why = text_problem(text, kind)
        if why:
            problems.append(f"{label}: {why}")
    if readme is None:
        problems.append("no README in the repository")
    else:
        why = text_problem(readme_words(readme), "readme")
        if why:
            problems.append(f"README: {why}")
    return problems


def check_repo(repo, author, listed, index_ids):
    """Problems and warnings for one added repository."""
    problems, warnings = [], []
    if not REPO.match(repo):
        return [f"`{repo}` is not owner/name"], warnings
    if repo.lower() in listed:
        return ["already in the Store"], warnings
    info = api(f"/repos/{repo}")
    if not info:
        return ["the repository does not exist or is not public"], warnings
    full = info.get("full_name") or repo
    owner = (info.get("owner") or {}).get("login") or repo.split("/")[0]
    if full.lower() != repo.lower():
        problems.append(f"the repository moved to {full}: list that name")
    if info.get("private"):
        problems.append("the repository is private")
    if info.get("fork"):
        problems.append("the repository is a fork")
    if info.get("archived"):
        problems.append("the repository is archived")
    if (info.get("owner") or {}).get("type") == "Organization":
        warnings.append(f"organization repository ({owner}): check membership by hand")
    elif owner.lower() != author.lower():
        problems.append(f"the repository belongs to {owner}, not to the author of the pull request ({author})")
    rel = api(f"/repos/{full}/releases/latest")
    if not rel:
        return problems + ["no stable release"], warnings
    tag = rel.get("tag_name") or ""
    t = TAG.match(tag)
    if not t:
        return problems + [f"the newest release tag {tag} is not v<major>.<minor>.<patch> without a pre-release part"], warnings
    zips = [a for a in rel.get("assets") or [] if a.get("name", "").lower().endswith(".zip")]
    if len(zips) > 1:
        try:
            with request(f"https://raw.githubusercontent.com/{full}/{tag}/obsidian.json", "application/json", auth=False) as r:
                rid = json.loads(r.read()).get("id") or ""
        except (urllib.error.HTTPError, ValueError, AttributeError):
            rid = ""
        zips = [a for a in zips if rid and rid in a["name"]]
    if len(zips) != 1:
        return problems + ["the newest release needs exactly one .zip asset (or exactly one whose name holds the mod id)"], warnings
    asset = zips[0]
    if (asset.get("size") or 0) > ZIP_CAP:
        return problems + ["the release ZIP is larger than 200 MB"], warnings
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mod.zip")
        if not download(asset["browser_download_url"], path):
            return problems + ["the release ZIP is larger than 200 MB"], warnings
        text, err = zip_manifest(path)
    if err:
        return problems + [err], warnings
    try:
        m = json.loads(text)
    except ValueError as e:
        return problems + [f"obsidian.json in the ZIP does not parse: {e}"], warnings
    more, name, summary = check_manifest(m, t.group(1), owner, index_ids)
    problems += more
    problems += text_problems(name, summary, api(f"/repos/{full}/readme", raw=True))
    return problems, warnings


def report(general, per_repo):
    """Markdown report and whether everything passed."""
    lines, ok = [], not general
    for p in general:
        lines.append(f"- {p}")
    for repo, (problems, warnings) in per_repo.items():
        ok = ok and not problems
        lines.append(f"\n### {repo}: {'problems' if problems else 'passed'}")
        lines += [f"- {p}" for p in problems]
        lines += [f"- Warning: {w}" for w in warnings]
    head = "## Store submission: passed" if ok else "## Store submission: failed"
    return head + "\n\n" + "\n".join(lines).strip() + "\n", ok


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def main(argv=None):
    global TOKEN
    ap = argparse.ArgumentParser(description="Checks a pull request that adds mods to the Store.")
    ap.add_argument("--base", required=True, help="mods.json of the base branch")
    ap.add_argument("--head", default=os.path.join(ROOT, "mods.json"), help="mods.json of the pull request")
    ap.add_argument("--index", default=os.path.join(ROOT, "index.json"), help="index.json of the base branch")
    ap.add_argument("--author", required=True, help="GitHub login of the pull request author")
    ap.add_argument("--files", help="file listing the paths the pull request changes, one per line")
    a = ap.parse_args(argv)
    TOKEN = token()

    general = []
    if a.files:
        with open(a.files, encoding="utf-8") as f:
            other = [p.strip() for p in f if p.strip() and p.strip() != "mods.json"]
        if other:
            general.append("the pull request changes files other than mods.json: " + ", ".join(other))
    base = load(a.base)
    try:
        head = load(a.head)
    except ValueError as e:
        head = None
        general.append(f"mods.json does not parse: {e}")
    per_repo = {}
    if head is not None:
        problems, added = diff_problems(base, head)
        general += problems
        if len(set(r.lower() for r in added)) != len(added):
            general.append("the same repository is added twice")
        if not problems:
            index = load(a.index)
            index_ids = {m["id"] for m in index.get("mods", [])} | {p["id"] for p in index.get("private", [])}
            listed = {r.lower() for r in (base.get("kit") or []) + (base.get("mods") or [])}
            for repo in added:
                per_repo[repo] = check_repo(repo, a.author, listed, index_ids)
    text, ok = report(general, per_repo)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
