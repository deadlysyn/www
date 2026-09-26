#!/usr/bin/env python3
"""blog.py - keep the deadlysyn.com blog consistent without a site generator.

Every post lives in blog/posts/<slug>/index.html and is plain HTML you can
edit directly. Only three things in a post are yours to edit:

  1. Three <meta> tags in the <head>:
       <meta name="date" content="2026-09-25">          publication date
       <meta name="keywords" content="aws, go">         tags, comma separated
       <meta name="description" content="...">          summary for search
                                                        results and RSS (leave
                                                        empty to use the first
                                                        paragraph)
     plus, optionally, <meta name="draft" content="true"> to keep a post
     unpublished.
  2. The title, inside <h1 class="name">...</h1>.
  3. The body, between <!-- post:start --> and <!-- post:end -->.

Everything else (running head, NAME/SEE ALSO sections, older/newer links,
footer date) is rewritten by `build`, along with the blog index, tag pages,
RSS feeds and sitemap. Edits you make outside those three places will be
overwritten on the next build.

Usage:
  ./blog.py new "My Post Title" --tags aws,go     scaffold a draft post
  ./blog.py build                                 regenerate everything
  ./blog.py list                                  show posts and drafts

Workflow for a new post:
  1. ./blog.py new "Title" --tags a,b
  2. Write the body in blog/posts/<slug>/index.html
  3. Delete the <meta name="draft"> line when it's ready
  4. ./blog.py build, preview locally, commit

Preview locally with:  python3 -m http.server --directory . 8000
Requires Python 3.8+ and nothing else.
"""

import argparse
import datetime
import html
import re
import sys
import unicodedata
from pathlib import Path

SITE = "https://deadlysyn.com"
TAGLINE = "Yelling at Clouds"
BLOG_DESC = "Writing on DevOps, SRE, cloud infrastructure, IaC, Go, Node.js and engineering culture."
START, END = "<!-- post:start -->", "<!-- post:end -->"

ROOT = Path(__file__).resolve().parent
BLOG = ROOT / "blog"
POSTS = BLOG / "posts"


# ---------------------------------------------------------------- helpers

def die(msg):
    sys.exit(f"blog.py: {msg}")


def esc(s):
    return html.escape(s, quote=True)


def text_of(fragment):
    """Plain text from an HTML fragment."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def slugify(title):
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "post"


def valid_tag(t):
    return re.fullmatch(r"[a-z0-9][a-z0-9-]*", t) is not None


def meta(doc, name):
    m = re.search(r'<meta\s+name="%s"\s+content="([^"]*)"\s*/?>' % re.escape(name), doc)
    return html.unescape(m.group(1)) if m else None


def shorten(s, n=155):
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"


def iso(d):
    return d.isoformat()


def long_date(d):
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def rfc822(d):
    return datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S +0000")


def tag_href(t):
    return f"/blog/tags/{t}/"


def post_href(p):
    return f"/blog/posts/{p['slug']}/"


changed = []


def write(path, text):
    """Write only when content differs, so builds are quiet and diffs stay small."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")
    changed.append(path.relative_to(ROOT))


# ---------------------------------------------------------------- reading posts

def read_post(path):
    doc = path.read_text(encoding="utf-8")
    slug = path.parent.name
    where = path.relative_to(ROOT)
    if START not in doc or END not in doc:
        raise ValueError(f"{where}: missing {START} / {END} markers")
    body = doc.split(START, 1)[1].split(END, 1)[0].strip("\n")

    m = re.search(r'<h1 class="name">(.*?)</h1>', doc, re.S)
    if not m or not m.group(1).strip():
        raise ValueError(f'{where}: missing <h1 class="name">title</h1>')
    title_html = m.group(1).strip()

    raw_date = meta(doc, "date")
    if not raw_date:
        raise ValueError(f'{where}: missing <meta name="date" content="YYYY-MM-DD">')
    try:
        date = datetime.date.fromisoformat(raw_date.strip())
    except ValueError:
        raise ValueError(f"{where}: date {raw_date!r} is not YYYY-MM-DD")

    tags = [t.strip().lower() for t in (meta(doc, "keywords") or "").split(",") if t.strip()]
    for t in tags:
        if not valid_tag(t):
            raise ValueError(f"{where}: tag {t!r} must be lowercase letters, digits and hyphens")

    desc = (meta(doc, "description") or "").strip()
    first_p = re.search(r"<p>(.*?)</p>", body, re.S)
    summary = desc or (text_of(first_p.group(1)) if first_p else "")
    draft = (meta(doc, "draft") or "").strip().lower() in ("true", "yes", "1")

    return dict(slug=slug, path=path, title_html=title_html, title=text_of(title_html),
                date=date, tags=tags, desc=desc, summary=summary, body=body, draft=draft)


def load_posts():
    posts, errors = [], []
    for path in sorted(POSTS.glob("*/index.html")):
        if path.parent.name == "page":  # redirects left over from Hugo pagination
            continue
        try:
            posts.append(read_post(path))
        except ValueError as e:
            errors.append(str(e))
    if errors:
        die("fix these posts first:\n  " + "\n  ".join(errors))
    posts.sort(key=lambda p: (p["date"], p["slug"]), reverse=True)
    return posts


# ---------------------------------------------------------------- templates

FONTS = ("https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700"
         "&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap")


def page(title, desc, canonical, body, foot_center="", extra_head=""):
    return f'''<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="{esc(desc)}">
{extra_head}    <meta name="theme-color" content="#15130f">
    <title>{esc(title)}</title>
    <link rel="canonical" href="{SITE}{canonical}">
    <link rel="alternate" type="application/rss+xml" title="deadlysyn: {TAGLINE}" href="/blog/index.xml">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="{FONTS}" rel="stylesheet">
    <link href="/site.css" rel="stylesheet">
  </head>
  <body>
    <div class="page">
      <header class="running-head">
        <a class="running-head__link" href="/">DEADLYSYN(1)</a>
        <span class="running-head__center">{TAGLINE}</span>
        <a class="running-head__link" href="/blog/">BLOG(7)</a>
      </header>

      <main>
{body}
      </main>

      <footer class="running-foot">
        <span>deadlysyn.com</span>
        <span class="running-foot__center">{foot_center}</span>
        <span>BLOG(7)</span>
      </footer>
    </div>
  </body>
</html>
'''


def section(sid, label, inner, tag="div", cls=""):
    classes = f"entry__body {cls}".strip()
    return f'''        <section class="entry" aria-labelledby="{sid}">
          <h2 id="{sid}" class="entry__label">{label}</h2>
          <{tag} class="{classes}">
{inner}
          </{tag}>
        </section>
'''


def synopsis(all_tags, current=None):
    opts = []
    for t in all_tags:
        cur = ' aria-current="page"' if t == current else ""
        opts.append(f'            <span class="opt">[<a class="flag" href="{tag_href(t)}"{cur}>--{esc(t)}</a>]</span>')
    return '            <span class="cmd">blog</span>\n' + "\n".join(opts)


def entry_list(items):
    return "\n".join(f'''            <li>
              <time datetime="{iso(p["date"])}">{iso(p["date"])}</time>
              <a href="{post_href(p)}">{p["title_html"]}</a>
            </li>''' for p in items)


def links(*pairs):
    return "\n".join(f'            <a href="{h}">{esc(t)}</a>' for h, t in pairs)


def plural(n):
    return "entry" if n == 1 else "entries"


def render_post(p, older, newer):
    rows = []
    if p["tags"]:
        tl = "\n".join(f'              <a href="{tag_href(t)}">{esc(t)}(7)</a>' for t in p["tags"])
        rows.append(f'            <div class="see-also__row">\n              <span class="see-also__key">tags</span>\n{tl}\n            </div>')
    for key, other in (("older", older), ("newer", newer)):
        if other:
            rows.append(f'            <div class="see-also__row">\n              <span class="see-also__key">{key}</span>\n'
                        f'              <a href="{post_href(other)}">{other["title_html"]}</a>\n            </div>')
    rows.append('            <div class="see-also__row">\n              <span class="see-also__key">index</span>\n'
                '              <a href="/blog/">blog(7)</a>\n            </div>')

    name = (f'            <h1 class="name">{p["title_html"]}</h1>\n'
            f'            <p class="meta"><time datetime="{iso(p["date"])}">{long_date(p["date"])}</time></p>')
    body = (section("name", "NAME", name)
            + section("description", "DESCRIPTION", f"{START}\n{p['body']}\n{END}", "div", "prose post")
            + section("see-also", "SEE ALSO", "\n".join(rows), "nav", "see-also see-also--stacked"))

    head = (f'    <meta name="date" content="{iso(p["date"])}">\n'
            f'    <meta name="keywords" content="{esc(", ".join(p["tags"]))}">\n')
    if p["draft"]:
        head += '    <meta name="draft" content="true">\n    <meta name="robots" content="noindex">\n'
    # the description meta is the author's field: keep it verbatim, even when empty
    html_out = page(f'{p["title"]} — deadlysyn', p["desc"], post_href(p), body,
                    foot_center=long_date(p["date"]), extra_head=head)
    return html_out


def redirect(target):
    return f'''<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Moved</title>
    <link rel="canonical" href="{SITE}{target}">
    <meta name="robots" content="noindex">
    <meta http-equiv="refresh" content="0; url={target}">
  </head>
  <body>
    <p>This page has moved to <a href="{target}">{SITE}{target}</a>.</p>
  </body>
</html>
'''


# ---------------------------------------------------------------- commands

def cmd_build(_args=None, quiet=False):
    posts = load_posts()
    live = [p for p in posts if not p["draft"]]
    if not live:
        die("no published posts found")
    all_tags = sorted({t for p in live for t in p["tags"]})
    latest = live[0]["date"]

    # posts (drafts get rendered too so you can preview them, but aren't linked anywhere)
    for i, p in enumerate(live):
        newer = live[i - 1] if i > 0 else None
        older = live[i + 1] if i + 1 < len(live) else None
        write(p["path"], render_post(p, older, newer))
    for p in posts:
        if p["draft"]:
            write(p["path"], render_post(p, None, None))

    # blog index
    body = (section("name", "NAME", f'            <h1 class="name"><span class="cmd">blog</span> — {TAGLINE.lower()}</h1>')
            + section("synopsis", "SYNOPSIS", synopsis(all_tags), "p", "synopsis")
            + section("entries", "ENTRIES", entry_list(live), "ol", "entries")
            + section("see-also", "SEE ALSO", links(("/", "deadlysyn(1)"), ("/blog/tags/", "tags(7)"), ("/blog/index.xml", "rss(5)")), "nav", "see-also"))
    write(BLOG / "index.html", page("blog(7) — deadlysyn", BLOG_DESC, "/blog/", body, foot_center=long_date(latest)))

    # tag pages
    for t in all_tags:
        tp = [p for p in live if t in p["tags"]]
        body = (section("name", "NAME", f'            <h1 class="name"><span class="cmd">blog --{esc(t)}</span> — {len(tp)} {plural(len(tp))} tagged {esc(t)}</h1>')
                + section("synopsis", "SYNOPSIS", synopsis(all_tags, t), "p", "synopsis")
                + section("entries", "ENTRIES", entry_list(tp), "ol", "entries")
                + section("see-also", "SEE ALSO", links(("/blog/", "blog(7)"), ("/blog/tags/", "tags(7)"), ("/", "deadlysyn(1)")), "nav", "see-also"))
        write(BLOG / "tags" / t / "index.html",
              page(f"blog --{t} — deadlysyn", f"Posts tagged {t} on the deadlysyn blog.", tag_href(t), body, foot_center=long_date(tp[0]["date"])))

    # tags that no longer have posts: point them at the tag list instead of leaving stale pages
    for d in sorted((BLOG / "tags").iterdir()):
        if d.is_dir() and d.name not in all_tags and d.name != "page" and (d / "index.html").exists():
            write(d / "index.html", redirect("/blog/tags/"))

    counts = {t: sum(t in p["tags"] for p in live) for t in all_tags}
    rows = "\n".join(f'            <dt><a class="flag" href="{tag_href(t)}">--{esc(t)}</a></dt>\n'
                     f'            <dd>{counts[t]} {plural(counts[t])}</dd>' for t in all_tags)
    body = (section("name", "NAME", '            <h1 class="name"><span class="cmd">tags</span> — every topic on the blog</h1>')
            + section("options", "OPTIONS", rows, "dl", "options")
            + section("see-also", "SEE ALSO", links(("/blog/", "blog(7)"), ("/", "deadlysyn(1)")), "nav", "see-also"))
    write(BLOG / "tags" / "index.html", page("tags(7) — deadlysyn", "Every topic on the deadlysyn blog.", "/blog/tags/", body))

    # RSS (GUIDs are post URLs, matching the old Hugo feed)
    def item(p):
        cats = "".join(f"      <category>{esc(t)}</category>\n" for t in p["tags"])
        return (f"    <item>\n      <title>{esc(p['title'])}</title>\n"
                f"      <link>{SITE}{post_href(p)}</link>\n      <guid>{SITE}{post_href(p)}</guid>\n"
                f"      <pubDate>{rfc822(p['date'])}</pubDate>\n{cats}"
                f"      <description>{esc(p['summary'])}</description>\n    </item>")
    items = "\n".join(item(p) for p in live)
    for rel in ("blog/index.xml", "blog/posts/index.xml"):
        write(ROOT / rel, f'''<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>deadlysyn: {TAGLINE}</title>
    <link>{SITE}/blog/</link>
    <description>{BLOG_DESC}</description>
    <language>en-us</language>
    <lastBuildDate>{rfc822(latest)}</lastBuildDate>
    <atom:link href="{SITE}/{rel}" rel="self" type="application/rss+xml"/>
{items}
  </channel>
</rss>
''')

    # sitemap
    urls = [("/", latest), ("/blog/", latest), ("/blog/tags/", latest)]
    urls += [(post_href(p), p["date"]) for p in live]
    urls += [(tag_href(t), next(p for p in live if t in p["tags"])["date"]) for t in all_tags]
    sm = "\n".join(f"  <url>\n    <loc>{SITE}{u}</loc>\n    <lastmod>{iso(d)}</lastmod>\n  </url>" for u, d in urls)
    write(BLOG / "sitemap.xml", '<?xml version="1.0" encoding="utf-8"?>\n'
          f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{sm}\n</urlset>\n')

    broken = check_links(skip={p["path"] for p in posts if p["draft"]})
    if not quiet:
        drafts = [p for p in posts if p["draft"]]
        print(f"{len(live)} posts, {len(all_tags)} tags" + (f", {len(drafts)} draft(s): " + ", ".join(p["slug"] for p in drafts) if drafts else ""))
        print("updated:\n  " + "\n  ".join(map(str, changed)) if changed else "everything already up to date")
        if broken:
            print(f"\nwarning: {len(broken)} broken internal link(s):")
            for src, href in broken:
                print(f"  {src}: {href}")


def check_links(skip=()):
    broken = []
    for f in sorted(ROOT.rglob("*.html")):
        if f in skip:  # drafts link to tag pages that only exist once they're published
            continue
        doc = f.read_text(encoding="utf-8")
        for href in re.findall(r'<(?:a|link)\b[^>]*\bhref="([^"]+)"', doc):
            h = href[len(SITE):] or "/" if href.startswith(SITE) else href
            if not h.startswith("/") or h.startswith("//"):
                continue
            h = h.split("#")[0].split("?")[0]
            target = ROOT / h.lstrip("/")
            if h.endswith("/") or target.is_dir():
                target = target / "index.html"
            if not target.exists():
                broken.append((f.relative_to(ROOT), href))
    return broken


def cmd_new(args):
    tags = [t.strip().lower() for t in (args.tags or "").split(",") if t.strip()]
    for t in tags:
        if not valid_tag(t):
            die(f"tag {t!r} must be lowercase letters, digits and hyphens")
    slug = args.slug or slugify(args.title)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        die(f"slug {slug!r} must be lowercase letters, digits and hyphens")
    path = POSTS / slug / "index.html"
    if path.exists():
        die(f"{path.relative_to(ROOT)} already exists (pick another --slug)")
    try:
        date = datetime.date.fromisoformat(args.date) if args.date else datetime.date.today()
    except ValueError:
        die(f"--date {args.date!r} is not YYYY-MM-DD")

    p = dict(slug=slug, path=path, title_html=esc(args.title), title=args.title, date=date, tags=tags,
             desc="", summary="", draft=True,
             body="<p>Write the first paragraph here. It becomes the summary in search results and RSS unless you fill in the description meta tag.</p>\n"
                  "<h3>A subheading</h3>\n"
                  "<p>Code blocks work like this:</p>\n"
                  '<pre tabindex="0"><code class="language-bash">echo "hello"</code></pre>')
    write(path, render_post(p, None, None))
    print(f"created {path.relative_to(ROOT)} (draft)")
    print("write the post between the post:start and post:end markers, delete the draft meta tag when it's ready, then run: ./blog.py build")
    print("tip: `./blog.py highlight` adds syntax colors to any new code blocks")


def cmd_list(_args):
    for p in load_posts():
        flag = "  [draft]" if p["draft"] else ""
        print(f"{iso(p['date'])}  {p['slug']:<40} {', '.join(p['tags'])}{flag}")


def cmd_highlight(args):
    """Add syntax-highlighting spans to code blocks that don't have them yet (needs Pygments)."""
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name, TextLexer
    except ImportError:
        die("highlighting needs Pygments: pip install pygments (code blocks still display fine without it)")
    aliases = {"hcl": "terraform", "dockerfile": "docker", "shell": "bash", "sh": "bash"}
    fmt = HtmlFormatter(nowrap=True, classprefix="tok-")
    targets = [POSTS / args.slug / "index.html"] if args.slug else sorted(POSTS.glob("*/index.html"))
    for path in targets:
        if not path.exists():
            die(f"{path.relative_to(ROOT)} not found")
        doc = path.read_text(encoding="utf-8")

        def repl(m):
            attrs, code = m.group(1), m.group(2)
            if 'class="tok-' in code:
                return m.group(0)  # already highlighted
            lang = re.search(r'class="language-([\w+-]+)"', attrs)
            name = aliases.get(lang.group(1).lower(), lang.group(1).lower()) if lang else None
            try:
                lexer = get_lexer_by_name(name) if name else TextLexer()
            except Exception:
                lexer = TextLexer()
            out = highlight(html.unescape(code), lexer, fmt).rstrip("\n")
            out = re.sub(r'<span class="tok-(?:w|err)">([^<]*)</span>', r"\1", out)
            return f'<pre tabindex="0"><code{attrs}>{out}</code></pre>'

        new = re.sub(r'<pre[^>]*><code([^>]*)>(.*?)</code></pre>', repl, doc, flags=re.S)
        if new != doc:
            write(path, new)
    print("highlighted:\n  " + "\n  ".join(map(str, changed)) if changed else "no unhighlighted code blocks found")


def main():
    ap = argparse.ArgumentParser(description="Maintain the deadlysyn.com blog as plain HTML.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Run without arguments to see the full workflow in the docstring: head -40 blog.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="scaffold a new draft post")
    n.add_argument("title")
    n.add_argument("--tags", help="comma separated, e.g. aws,go")
    n.add_argument("--date", help="YYYY-MM-DD (default: today)")
    n.add_argument("--slug", help="URL slug (default: from title)")
    n.set_defaults(func=cmd_new)

    sub.add_parser("build", help="regenerate posts' chrome, index, tag pages, feeds and sitemap").set_defaults(func=cmd_build)
    sub.add_parser("list", help="list posts and drafts").set_defaults(func=cmd_list)

    h = sub.add_parser("highlight", help="add syntax colors to new code blocks (needs Pygments)")
    h.add_argument("slug", nargs="?", help="only this post")
    h.set_defaults(func=cmd_highlight)

    args = ap.parse_args()
    if not POSTS.is_dir():
        die(f"expected {POSTS.relative_to(ROOT.parent)} next to this script")
    args.func(args)


if __name__ == "__main__":
    main()
