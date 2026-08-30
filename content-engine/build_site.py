#!/usr/bin/env python3
"""posts/*.md 를 site/ 아래 정적 HTML로 굽는다.

GitHub Pages 에 그대로 올리면 되므로 호스팅 비용이 0원이다.
마크다운 변환은 필요한 문법만 직접 처리한다(외부 패키지 없음).
"""

import html
import json
import os
import re
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
POSTS_DIR = os.path.join(BASE, "posts")
SITE_DIR = os.path.join(BASE, "site")

FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
CODE_RE = re.compile(r"`([^`\n]+)`")

STYLE = """
:root { color-scheme: light dark; --fg:#1b1b1f; --muted:#5d5d68; --bg:#fbfbfd; --line:#e3e3ea; --accent:#2f5bd6; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e9e9ee; --muted:#a0a0ac; --bg:#131317; --line:#2c2c34; --accent:#8aa8ff; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font: 16px/1.75 -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Pretendard", "Malgun Gothic", sans-serif; }
.wrap { max-width: 43rem; margin: 0 auto; padding: 3rem 1.25rem 5rem; }
header.site { border-bottom:1px solid var(--line); padding-bottom:1.25rem; margin-bottom:2.5rem; }
header.site a { color:var(--fg); text-decoration:none; font-weight:700; font-size:1.15rem; }
header.site p { color:var(--muted); margin:.4rem 0 0; font-size:.9rem; }
h1 { font-size:1.75rem; line-height:1.35; margin:0 0 .5rem; }
h2 { font-size:1.25rem; margin:2.5rem 0 .75rem; }
h3 { font-size:1.05rem; margin:1.75rem 0 .5rem; }
a { color:var(--accent); }
time, .meta { color:var(--muted); font-size:.875rem; }
ul.index { list-style:none; padding:0; }
ul.index li { padding:.9rem 0; border-bottom:1px solid var(--line); }
ul.index a { text-decoration:none; font-weight:600; }
blockquote { margin:1.25rem 0; padding:.25rem 0 .25rem 1rem; border-left:3px solid var(--line); color:var(--muted); }
hr { border:0; border-top:1px solid var(--line); margin:2.5rem 0; }
code { background:rgba(127,127,140,.16); padding:.1rem .35rem; border-radius:4px; font-size:.9em; }
footer.site { margin-top:4rem; padding-top:1.25rem; border-top:1px solid var(--line); color:var(--muted); font-size:.85rem; }
"""


def parse_front_matter(text):
    meta = {}
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return meta, text
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[match.end() :]


def inline(text):
    """이스케이프를 먼저 하고, 그 위에 허용된 문법만 태그로 되돌린다."""
    text = html.escape(text)
    text = CODE_RE.sub(r"<code>\1</code>", text)
    text = LINK_RE.sub(
        lambda m: '<a href="{}" rel="noopener">{}</a>'.format(
            html.escape(m.group(2), quote=True), m.group(1)
        ),
        text,
    )
    text = BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = ITALIC_RE.sub(r"<em>\1</em>", text)
    return text


def markdown_to_html(text):
    out = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            close_list()
            continue
        if stripped.startswith("---"):
            close_list()
            out.append("<hr>")
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            continue

        if stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(stripped[2:])}</li>")
            continue

        if stripped.startswith("> "):
            close_list()
            out.append(f"<blockquote>{inline(stripped[2:])}</blockquote>")
            continue

        close_list()
        out.append(f"<p>{inline(stripped)}</p>")

    close_list()
    return "\n".join(out)


def page(brand, title, body, is_index=False):
    home = "index.html" if not is_index else "#"
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">
<header class="site">
  <a href="{home}">{html.escape(brand['title'])}</a>
  <p>{html.escape(brand.get('tagline', ''))}</p>
</header>
{body}
<footer class="site">
  <p>{html.escape(brand.get('author', ''))} · 이 페이지는 GitHub Pages로 무료 호스팅됩니다.</p>
</footer>
</div>
</body>
</html>
"""


def slugify(name):
    return re.sub(r"[^a-zA-Z0-9가-힣._-]+", "-", name).strip("-")


def main():
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as fp:
        brand = json.load(fp)["brand"]

    os.makedirs(SITE_DIR, exist_ok=True)
    os.makedirs(POSTS_DIR, exist_ok=True)

    posts = []
    for name in sorted(os.listdir(POSTS_DIR)):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(POSTS_DIR, name), encoding="utf-8") as fp:
            meta, body = parse_front_matter(fp.read())
        if meta.get("status", "published").lower() == "draft":
            print(f"  [건너뜀] {name} (status: draft)")
            continue
        title = meta.get("title") or name[:-3]
        date = meta.get("date") or name[:10]
        slug = slugify(name[:-3]) + ".html"
        with open(os.path.join(SITE_DIR, slug), "w", encoding="utf-8") as fp:
            fp.write(page(brand, title, markdown_to_html(body)))
        posts.append({"title": title, "date": date, "slug": slug})
        print(f"  [발행] {name} -> site/{slug}")

    posts.sort(key=lambda post: post["date"], reverse=True)

    if posts:
        items = "\n".join(
            '<li><a href="{slug}">{title}</a><div class="meta">{date}</div></li>'.format(
                slug=post["slug"], title=html.escape(post["title"]), date=html.escape(post["date"])
            )
            for post in posts
        )
        index_body = f"<h1>지난 글</h1>\n<ul class=\"index\">\n{items}\n</ul>"
    else:
        index_body = (
            "<h1>아직 발행된 글이 없습니다</h1>"
            "<p>초안을 다듬어 <code>content-engine/posts/</code> 에 넣고 "
            "<code>status: published</code> 로 바꾸면 여기에 나타납니다.</p>"
        )

    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as fp:
        fp.write(page(brand, brand["title"], index_body, is_index=True))

    # Jekyll이 파일을 다시 가공하지 않도록 막는다.
    open(os.path.join(SITE_DIR, ".nojekyll"), "w").close()

    print(f"글 {len(posts)}편 -> {SITE_DIR} ({datetime.now().strftime('%H:%M:%S')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
