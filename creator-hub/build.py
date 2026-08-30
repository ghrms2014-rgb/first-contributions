#!/usr/bin/env python3
"""인스타 프로필 링크가 향할 허브 페이지를 만든다.

인스타에서 오는 트래픽은 사실상 전부 모바일이라 모바일 우선으로 짠다.
목표는 '조회수를 이메일 주소로 바꾸는 것' 하나다.

    python3 creator-hub/build.py
"""

import html
import json
import os
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
PROFILE_PATH = os.path.join(BASE, "profile.json")
OUT_DIR = os.path.join(ROOT, "_site")
BRIEF_SRC = os.path.join(ROOT, "content-engine", "site")

STYLE = """
:root { color-scheme: light dark;
  --fg:#12121a; --muted:#61616e; --bg:#fafafc; --card:#fff; --line:#e6e6ee;
  --accent:#1f6feb; --accent-fg:#fff; --shadow:0 1px 2px rgba(0,0,0,.06); }
@media (prefers-color-scheme: dark) {
  :root { --fg:#ececf2; --muted:#9a9aa8; --bg:#0e0e12; --card:#18181f; --line:#2a2a33;
    --accent:#4d90ff; --accent-fg:#0e0e12; --shadow:none; }
}
* { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.6 -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Pretendard",
       "Malgun Gothic", "Noto Sans KR", sans-serif; }
.wrap { max-width:30rem; margin:0 auto; padding:2.5rem 1.1rem 4rem; }

.profile { text-align:center; margin-bottom:2rem; }
.avatar { width:88px; height:88px; border-radius:50%; object-fit:cover; margin:0 auto .9rem;
  display:block; border:2px solid var(--line); }
.avatar-fallback { width:88px; height:88px; border-radius:50%; margin:0 auto .9rem;
  display:flex; align-items:center; justify-content:center; font-size:2.2rem;
  background:var(--card); border:2px solid var(--line); }
.profile h1 { font-size:1.35rem; margin:0 0 .3rem; }
.profile .headline { color:var(--fg); font-weight:600; font-size:.95rem; margin:0 0 .2rem; }
.profile .sub { color:var(--muted); font-size:.9rem; margin:0; }

.magnet { background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:1.4rem; margin-bottom:1.6rem; box-shadow:var(--shadow); }
.magnet h2 { font-size:1.1rem; margin:0 0 .5rem; }
.magnet p { color:var(--muted); font-size:.9rem; margin:0 0 1.1rem; }
.btn { display:block; width:100%; text-align:center; padding:.95rem 1rem; border-radius:10px;
  background:var(--accent); color:var(--accent-fg); text-decoration:none; font-weight:700;
  font-size:1rem; border:0; }
.btn:active { opacity:.85; }
.btn[aria-disabled="true"] { background:var(--line); color:var(--muted); font-weight:600; }

.card { display:flex; align-items:center; gap:.9rem; background:var(--card);
  border:1px solid var(--line); border-radius:12px; padding:.95rem 1.1rem;
  margin-bottom:.7rem; text-decoration:none; color:var(--fg); box-shadow:var(--shadow); }
.card:active { transform:scale(.99); }
.card .t { font-weight:600; font-size:.98rem; }
.card .h { color:var(--muted); font-size:.82rem; }
.card .grow { flex:1; min-width:0; }
.card .chev { color:var(--muted); flex-shrink:0; }
.badge { font-size:.7rem; font-weight:700; padding:.2rem .5rem; border-radius:999px;
  background:var(--line); color:var(--muted); flex-shrink:0; }

h3.sec { font-size:.78rem; text-transform:uppercase; letter-spacing:.06em;
  color:var(--muted); margin:1.9rem 0 .7rem; font-weight:700; }
.note { color:var(--muted); font-size:.78rem; line-height:1.55; margin-top:2.2rem;
  padding-top:1.2rem; border-top:1px solid var(--line); }
"""

CHEV = '<span class="chev">&rsaquo;</span>'


def esc(text, quote=False):
    return html.escape(text or "", quote=quote)


def avatar(profile):
    src = profile.get("avatar", "").strip()
    if src:
        return f'<img class="avatar" src="{esc(src, True)}" alt="{esc(profile["name"], True)}">'
    return '<div class="avatar-fallback">👷</div>'


def magnet_block(magnet):
    """이메일을 받는 자리. 링크가 없으면 버튼을 비활성으로 두고 눈에 띄게 남긴다."""
    if not magnet.get("enabled", True):
        return ""
    url = magnet.get("url", "").strip()
    if url:
        button = f'<a class="btn" href="{esc(url, True)}" rel="noopener">{esc(magnet["button"])}</a>'
    else:
        button = '<span class="btn" aria-disabled="true">링크 미설정 — profile.json 확인</span>'
    return (
        '<section class="magnet">'
        f'<h2>{esc(magnet["title"])}</h2>'
        f'<p>{esc(magnet["blurb"])}</p>'
        f"{button}</section>"
    )


def offer_card(offer):
    url = offer.get("url", "").strip()
    badge = offer.get("badge", "").strip()
    inner = (
        '<div class="grow">'
        f'<div class="t">{esc(offer["title"])}</div>'
        f'<div class="h">{esc(offer["blurb"])}</div>'
        "</div>"
        + (f'<span class="badge">{esc(badge)}</span>' if badge else "")
    )
    if url:
        return f'<a class="card" href="{esc(url, True)}" rel="noopener">{inner}{CHEV}</a>'
    return f'<div class="card">{inner}</div>'


def link_card(link):
    handle = esc(link.get("handle", ""))
    return (
        f'<a class="card" href="{esc(link["url"], True)}" rel="noopener">'
        '<div class="grow">'
        f'<div class="t">{esc(link["title"])}</div>'
        + (f'<div class="h">{handle}</div>' if handle else "")
        + f"</div>{CHEV}</a>"
    )


def render(profile):
    site = profile["site"]
    base = site.get("base_url", "").rstrip("/")
    title = site["title"]
    description = site["description"]

    body = ['<div class="profile">', avatar(profile),
            f'<h1>{esc(profile["name"])}</h1>',
            f'<p class="headline">{esc(profile["headline"])}</p>',
            f'<p class="sub">{esc(profile["sub"])}</p>', "</div>"]

    body.append(magnet_block(profile.get("lead_magnet", {})))

    offers = [o for o in profile.get("offers", []) if o.get("enabled", True)]
    if offers:
        body.append('<h3 class="sec">함께 하기</h3>')
        body.extend(offer_card(offer) for offer in offers)

    links = [l for l in profile.get("links", []) if l.get("enabled", True) and l.get("url")]
    if links:
        body.append('<h3 class="sec">채널</h3>')
        body.extend(link_card(link) for link in links)

    brief = site.get("brief_path", "").strip()
    if brief and os.path.isdir(BRIEF_SRC):
        body.append('<h3 class="sec">지난 글</h3>')
        body.append(
            f'<a class="card" href="{esc(brief, True)}">'
            '<div class="grow"><div class="t">브리핑 전체 보기</div>'
            '<div class="h">현장 소식과 정리한 글</div></div>' + CHEV + "</a>"
        )

    disclaimer = profile.get("disclaimer", "").strip()
    if disclaimer:
        body.append(f'<p class="note">{esc(disclaimer)}</p>')

    meta = [
        f'<meta name="description" content="{esc(description, True)}">',
        f'<meta property="og:title" content="{esc(title, True)}">',
        f'<meta property="og:description" content="{esc(description, True)}">',
        '<meta property="og:type" content="profile">',
        '<meta name="twitter:card" content="summary">',
    ]
    if base:
        meta.append(f'<link rel="canonical" href="{esc(base, True)}/">')
        meta.append(f'<meta property="og:url" content="{esc(base, True)}/">')

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
{chr(10).join(meta)}
<style>{STYLE}</style>
</head>
<body>
<main class="wrap">
{chr(10).join(part for part in body if part)}
</main>
</body>
</html>
"""


def main():
    with open(PROFILE_PATH, encoding="utf-8") as fp:
        profile = json.load(fp)

    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)

    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as fp:
        fp.write(render(profile))
    open(os.path.join(OUT_DIR, ".nojekyll"), "w").close()

    brief = profile["site"].get("brief_path", "").strip().strip("/")
    if brief and os.path.isdir(BRIEF_SRC):
        shutil.copytree(BRIEF_SRC, os.path.join(OUT_DIR, brief))
        print(f"  브리핑 페이지 복사 -> _site/{brief}/")

    print(f"허브 생성 완료 -> _site/index.html")
    if not profile.get("lead_magnet", {}).get("url", "").strip():
        print("  [중요] lead_magnet.url 이 비어 있습니다. 이메일 수집이 안 됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
