#!/usr/bin/env python3
"""Blog: one introduction post for every project folder in the Copilot repo.

Once a day the "Update blog" workflow checks out the source repository (see
[blog] in config.toml) and runs this script. Every top-level folder that has a
readme and no post yet gets one. A post says what the solution is for, who it
helps, what you need and what you get. It never repeats install or run steps:
it links to the folder's readme for those.

Each post is written three ways:
  docs/data/blog.json      read by the Blog tab of the site
  docs/blog/<slug>.html    a page of its own, with link-preview tags for LinkedIn
  docs/blog/<slug>.txt     the LinkedIn post, ready to paste

With the SUMMARY_ENDPOINT / SUMMARY_API_KEY / SUMMARY_MODEL secrets (the same
ones the news collector uses) an AI model writes the post. Without them the post
is built from the readme and the repository's own README table.

Standard library only.  python scripts/blog.py --source <checkout> [--no-ai]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = DOCS / "data" / "blog.json"
PAGES = DOCS / "blog"

LINKEDIN_LIMIT = 3000   # LinkedIn's limit for a post

# Readme sections that hold steps rather than purpose. They are left out of what
# the post is written from, so the post cannot repeat them.
STEP_HEADINGS = re.compile(
    r"\b(install|installation|set ?up|set it up|setup|getting started|get started|quick ?start|"
    r"how to (run|use|install|deploy|set)|run it|running|usage|deploy|deployment|steps?\b|"
    r"step \d|walkthrough|configure|configuration|build order|upgrade|update it|uninstall|"
    r"troubleshoot|parameters|examples?|commands?)",
    re.I)
# Sections that say what is needed. Kept, and read first for "What you need".
NEED_HEADINGS = re.compile(
    r"\b(prerequisites?|requirements?|what you need|before you (start|begin)|you need|"
    r"permissions?|licen[cs](e|es|ing)|roles?)\b", re.I)

GRAPH_SCOPE = re.compile(
    r"\b[A-Z][A-Za-z]+(?:\.[A-Z][A-Za-z]+)*\.(?:Read|ReadWrite|ReadBasic|Write)(?:\.[A-Z][A-Za-z]+)*\b")

SYSTEM_PROMPT = """You write short introduction blog posts for a Microsoft Copilot practitioner's \
GitHub projects. You are given one project: its folder name, its readme (install and run \
steps already removed), its file list and any Microsoft Graph permissions its scripts ask for.

Write for IT admins and Copilot owners. Plain, confident, first person plural is fine. No hype \
words (revolutionary, game-changer, unlock, supercharge, seamless). Do not invent features, \
licenses or permissions that are not in the material.

Never include install, setup or run steps, commands, code, parameters or file paths to run. \
Readers follow the readme for that; say so in one line at most.

Answer with JSON only, in this shape:
{"title": "post title, under 70 characters",
 "summary": "one or two sentences, under 220 characters, used as the link preview",
 "purpose": "one or two short paragraphs: the problem and what this solution does about it",
 "audience": "one sentence: who it is for",
 "needs": ["what you need: licenses, roles, permissions, tools. 2 to 7 short items"],
 "gets": ["what you get out of it. 2 to 5 short items"],
 "linkedin": "a LinkedIn post of 600 to 1300 characters: a one-line hook, two or three short \
paragraphs, a short 'You'll need' list using the • character, then the line {LINK} on its own. \
No hashtags (they are added after). No markdown."}"""


# --------------------------------------------------------------------- helpers
def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "post"


def clip(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def plain(md: str) -> str:
    """Markdown to one line of plain text."""
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"<[^>]+>", "", md)
    md = re.sub(r"[*_`]+", "", md)
    return re.sub(r"\s+", " ", md).strip()


def find_readme(folder: Path) -> Path | None:
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.name.lower() in ("readme.md", "readme.markdown", "readme.txt"):
            return p
    return None


def split_sections(md: str) -> list[tuple[int, str, str]]:
    """[(level, heading, body)], with level 0 for text before the first heading."""
    md = re.sub(r"```.*?```", "", md, flags=re.S)        # code is never post material
    out: list[tuple[int, str, list[str]]] = [(0, "", [])]
    for line in md.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            out.append((len(m.group(1)), m.group(2).strip(), []))
        else:
            out[-1][2].append(line)
    return [(lvl, h, "\n".join(body).strip()) for lvl, h, body in out]


def readme_material(md: str) -> dict:
    """Title, intro, needs and the readme with every step section removed."""
    sections = split_sections(md)
    title, kept, needs, skip_below = "", [], [], 0
    for lvl, head, body in sections:
        if lvl == 1 and not title:
            title = plain(head)
        if skip_below and lvl > skip_below:
            continue                                     # inside a step section
        skip_below = 0
        if head and STEP_HEADINGS.search(head) and not NEED_HEADINGS.search(head):
            skip_below = lvl
            continue
        if head and NEED_HEADINGS.search(head):
            needs.extend(plain(m) for m in re.findall(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$", body, re.M))
        kept.append(("#" * lvl + " " + head + "\n\n" if head else "") + body)
    text = "\n\n".join(k for k in kept if k.strip())
    intro = []
    for para in re.split(r"\n\s*\n", text):
        # Prose only: no headings, tables, lists, rules or "Oct 30, 2026 · @Chad Cox" bylines.
        lines = [l for l in para.splitlines()
                 if not re.match(r"^\s*(#|\||[-*+] |\d+\.\s|---|>)", l)]
        p = plain(" ".join(lines))
        p = re.sub(r"\s*See \[?[^.]*\.$", "", p)          # trailing "See Build order."
        if len(p) > 60 and not p.endswith(":") and not re.match(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}", p):
            intro.append(p)
    return {"title": title, "intro": intro[:2], "needs": needs, "text": text}


def repo_table(root_readme: str) -> dict[str, dict]:
    """The repository README's "Folder | What it is | What you get" rows, by folder."""
    rows: dict[str, dict] = {}
    header: list[str] = []
    for line in root_readme.splitlines():
        if not line.strip().startswith("|"):
            header = []
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        if not header:
            header = [c.lower() for c in cells]
            continue
        link = next((re.search(r"\]\(([^)]+)\)", c) for c in cells if "](" in c), None)
        if not link:
            continue
        folder = urllib.parse.unquote(link.group(1)).split("/")[0]
        row = dict(zip(header, (plain(c) for c in cells)))
        rows[folder] = {"what": row.get("what it is", ""), "gets": row.get("what you get", "")}
    return rows


def inventory(folder: Path) -> dict:
    files, scopes, tech = [], set(), set()
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or any(part.startswith(".") for part in p.relative_to(folder).parts):
            continue
        rel = p.relative_to(folder).as_posix()
        files.append(rel)
        ext = p.suffix.lower()
        if ext in (".ps1", ".psm1"):
            tech.add("PowerShell 7")
            try:
                code = p.read_text("utf-8", "replace")
            except OSError:
                continue
            if "Connect-MgGraph" in code:
                tech.add("Microsoft Graph PowerShell (Microsoft.Graph.Authentication module)")
            # Permission names appear as quoted strings, often over several lines.
            scopes.update(q for q in re.findall(r"[\"']([A-Z][\w.]+)[\"']", code)
                          if GRAPH_SCOPE.fullmatch(q))
    return {"files": files[:60], "scopes": sorted(scopes), "tech": sorted(tech)}


def needs_cowork(inv: dict, md: str) -> str:
    """Copilot Cowork is required for prompt projects, optional where a script also runs it."""
    if not re.search(r"\bcowork\b", md + " ".join(inv["files"]), re.I):
        return ""
    if "PowerShell 7" in inv["tech"]:
        return "Microsoft 365 Copilot with Copilot Cowork, if you run it there instead of PowerShell"
    return "Microsoft 365 Copilot with Copilot Cowork"


# ------------------------------------------------------------------ AI writer
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None   # never resend the key to another host


def ask_model(material: dict) -> dict | None:
    endpoint = os.environ.get("SUMMARY_ENDPOINT", "").strip()
    token = os.environ.get("SUMMARY_API_KEY", "").strip()
    model = os.environ.get("SUMMARY_MODEL", "").strip()
    if not (endpoint and token and model):
        return None
    body = json.dumps({
        "model": model, "temperature": 0.4, "max_tokens": 1800,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": json.dumps(material, ensure_ascii=False)}],
    }).encode()
    req = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "api-key": token,
        "Content-Type": "application/json", "User-Agent": "copilot-agent-watch-blog"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=120) as resp:
            reply = json.loads(resp.read())["choices"][0]["message"]["content"] or ""
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"  model call failed ({exc}); using the readme instead", file=sys.stderr)
        return None
    return parse_reply(reply)


def _clean(s: object, n: int) -> str:
    if not isinstance(s, str):
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    return clip(re.sub(r"[ \t]+", " ", s).strip(), n)


def has_steps(text: str) -> bool:
    """True when text looks like it repeats install or run steps."""
    return bool(re.search(r"```|^\s*(PS>|\$ |\.\\|\./|pip |npm |Install-Module|git clone)"
                          r"|Install-Module|Set-ExecutionPolicy", text, re.M | re.I))


def parse_reply(reply: str) -> dict | None:
    """Validate the model's JSON. Anything malformed or step-like is refused."""
    start, end = reply.find("{"), reply.rfind("}")
    try:
        data = json.loads(reply[start:end + 1]) if 0 <= start < end else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        return None
    post = {
        "title": _clean(data.get("title"), 90),
        "summary": _clean(data.get("summary"), 240),
        "purpose": _clean(data.get("purpose"), 1400),
        "audience": _clean(data.get("audience"), 240),
        "needs": [_clean(x, 160) for x in data.get("needs") or [] if _clean(x, 160)][:7],
        "gets": [_clean(x, 160) for x in data.get("gets") or [] if _clean(x, 160)][:5],
        "linkedin": _clean(data.get("linkedin"), 2400),
    }
    if not (post["title"] and post["summary"] and post["purpose"] and post["linkedin"]):
        return None
    if has_steps(json.dumps(post)):
        return None
    return post


# ------------------------------------------------------------ fallback writer
def fallback_post(name: str, rm: dict, row: dict, inv: dict) -> dict:
    title = rm["title"] or name
    what = row.get("what") or (rm["intro"][0] if rm["intro"] else f"{name}: a Microsoft Copilot project.")
    purpose = "\n\n".join(rm["intro"][:2]) or what
    needs = [n for n in rm["needs"] if not has_steps(n)][:5]
    for t in inv["tech"] + [inv.get("cowork", "")]:
        if t and t not in needs:
            needs.append(t)
    if inv["scopes"]:
        more = len(inv["scopes"]) - 8
        needs.append("Microsoft Graph permissions: " + ", ".join(inv["scopes"][:8])
                     + (f" and {more} more" if more > 0 else ""))
    gets = [row["gets"]] if row.get("gets") else []
    summary = clip(what.rstrip(".") + ".", 220)
    hook = f"New in my Copilot repo: {title}."
    lines = [hook, "", summary] + (["", clip(purpose, 900)] if purpose != what else [])
    if needs:
        lines += ["", "You'll need:"] + [f"• {n}" for n in needs]
    if gets:
        lines += ["", "What you get: " + gets[0]]
    lines += ["", "{LINK}"]
    return {"title": clip(f"Introducing {title}", 90), "summary": summary, "purpose": purpose,
            "audience": "", "needs": needs, "gets": gets, "linkedin": "\n".join(lines)}


# -------------------------------------------------------------------- output
def finish_linkedin(text: str, page_url: str, source_url: str, tags: list[str]) -> str:
    link = f"Read more: {page_url}\nThe project: {source_url}" if page_url else f"The project: {source_url}"
    text = text.replace("{LINK}", link) if "{LINK}" in text else text.rstrip() + "\n\n" + link
    tag_line = " ".join("#" + re.sub(r"\W", "", t) for t in tags if t)
    if tag_line:
        text = text.rstrip() + "\n\n" + tag_line
    return text[:LINKEDIN_LIMIT]


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | {site}</title>
<meta name="description" content="{summary}">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{summary}">
<meta property="og:site_name" content="{site}">
{og_url}<meta property="article:published_time" content="{date}">
<meta name="author" content="{author}">
<meta name="twitter:card" content="summary">
<link rel="stylesheet" href="../style.css">
<style>
  .article {{ max-width: 44rem; margin: 0 auto; padding: 2.5rem 1rem 4rem; }}
  .article h1 {{ font: 700 clamp(1.9rem, 5vw, 2.8rem)/1.05 var(--display); letter-spacing: -0.02em; margin: 0.4rem 0 0.8rem; }}
  .article h2 {{ font-size: 1.25rem; margin-top: 2rem; }}
  .article .meta {{ color: var(--muted); margin: 0; }}
  .article .lead {{ font-size: 1.2rem; }}
  .article li {{ margin-bottom: 0.35rem; }}
  .article .cta {{ margin-top: 2rem; padding: 1rem 1.2rem; border-left: 3px solid var(--accent); background: var(--surface); }}
</style>
</head>
<body>
<main class="article">
  <p class="meta"><a href="../#blog">← {site} blog</a></p>
  <h1>{title}</h1>
  <p class="meta">{date_label} · {author}</p>
  <p class="lead">{summary}</p>
  {purpose}
  {audience}
  {needs}
  {gets}
  <p class="cta">Setup and run steps are in the project readme: <a href="{source}">{folder} on GitHub</a>.</p>
</main>
</body>
</html>
"""


def write_page(post: dict, site: str, author: str, site_url: str) -> None:
    e = html.escape
    paras = "\n  ".join(f"<p>{e(p)}</p>" for p in re.split(r"\n\s*\n", post["purpose"]) if p.strip())
    def ul(head, items):
        return (f"<h2>{head}</h2>\n  <ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>") if items else ""
    date = post["date"][:10]
    page_url = urllib.parse.urljoin(site_url, post["page"]) if site_url else ""
    (PAGES / f"{post['slug']}.html").write_text(PAGE.format(
        title=e(post["title"]), site=e(site), summary=e(post["summary"]), author=e(author),
        og_url=f'<meta property="og:url" content="{e(page_url)}">\n' if page_url else "",
        date=e(post["date"]), date_label=e(datetime.fromisoformat(date).strftime("%b %d, %Y")),
        purpose=paras, audience=f"<p><strong>Who it's for:</strong> {e(post['audience'])}</p>" if post["audience"] else "",
        needs=ul("What you need", post["needs"]), gets=ul("What you get", post["gets"]),
        source=e(post["source"]), folder=e(post["folder"])), "utf-8")
    (PAGES / f"{post['slug']}.txt").write_text(post["linkedin"] + "\n", "utf-8")


# ---------------------------------------------------------------------- main
def run(source: Path, cfg: dict, use_ai: bool = True, force: set[str] | None = None,
        today: str | None = None) -> list[str]:
    blog = cfg.get("blog", {})
    site = cfg.get("site", {})
    repo = blog.get("repo", "chadmcox/Copilot")
    branch = blog.get("branch", "main")
    skip = {s.lower() for s in blog.get("skip", [])}
    tags = blog.get("hashtags", ["MicrosoftCopilot", "Copilot", "M365"])
    author = blog.get("author", "")
    site_url = site.get("url", "")
    force = force or set()

    store = json.loads(DATA.read_text("utf-8")) if DATA.exists() else {"posts": []}
    posts = {p["folder"]: dict(p) for p in store.get("posts", [])}
    root_readme = find_readme(source)
    table = repo_table(root_readme.read_text("utf-8", "replace")) if root_readme else {}
    PAGES.mkdir(parents=True, exist_ok=True)

    made = []
    for folder in sorted(p for p in source.iterdir() if p.is_dir()):
        name = folder.name
        if name.startswith((".", "_")) or name.lower() in skip:
            continue
        readme = find_readme(folder)
        if not readme:
            print(f"- {name}: no readme yet, waiting")
            continue
        md = readme.read_text("utf-8", "replace")
        digest = hashlib.sha256(md.encode()).hexdigest()[:16]
        if name in posts and slugify(name) not in force and name not in force:
            # Shows on the Blog tab when a readme has changed since its post was written.
            posts[name]["readme_changed"] = digest != posts[name].get("readme_hash")
            continue

        rm = readme_material(md)
        inv = inventory(folder)
        inv["cowork"] = needs_cowork(inv, md)
        row = table.get(name, {})
        written = None
        if use_ai:
            written = ask_model({
                "folder": name, "title": rm["title"], "repository_summary": row,
                "readme_without_steps": rm["text"][:9000], "files": inv["files"],
                "graph_permissions": inv["scopes"],
                "detected_tools": inv["tech"] + ([inv["cowork"]] if inv["cowork"] else [])})
        post = written or fallback_post(name, rm, row, inv)

        slug = slugify(name)
        source_url = f"https://github.com/{repo}/tree/{branch}/{urllib.parse.quote(name)}"
        page = f"blog/{slug}.html"
        page_url = urllib.parse.urljoin(site_url, page) if site_url else ""
        old = posts.get(name, {})
        post.update({
            "slug": slug, "folder": name, "source": source_url, "page": page,
            "date": old.get("date") or (today or now_iso()), "updated": now_iso(),
            "ai": bool(written), "readme_hash": digest, "readme_changed": False,
            "linkedin": finish_linkedin(post["linkedin"], page_url, source_url, tags),
        })
        write_page(post, site.get("title", "Blog"), author, site_url)
        posts[name] = post
        made.append(name)
        print(f"+ {name}: post written ({'AI' if written else 'from the readme'})")

    ordered = sorted(posts.values(), key=lambda p: p["date"], reverse=True)
    if made or ordered != store.get("posts") or not DATA.exists():
        # Only rewrite when something changed, so quiet days make no commit.
        DATA.parent.mkdir(parents=True, exist_ok=True)
        DATA.write_text(json.dumps({"generated": now_iso(), "repo": repo, "posts": ordered},
                                   indent=1, ensure_ascii=False) + "\n", "utf-8")
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", required=True, help="checkout of the repository to write about")
    ap.add_argument("--no-ai", action="store_true", help="build posts from the readme only")
    ap.add_argument("--regenerate", default="", help="comma-separated folder names or slugs to rewrite")
    args = ap.parse_args()
    cfg = tomllib.loads((ROOT / "config.toml").read_text("utf-8"))
    if not cfg.get("blog", {}).get("enabled", True):
        print("Blog is turned off in config.toml.")
        return 0
    force = {s.strip() for s in args.regenerate.split(",") if s.strip()}
    made = run(Path(args.source), cfg, use_ai=not args.no_ai, force=force)
    print(f"{len(made)} new post(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
