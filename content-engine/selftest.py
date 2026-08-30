#!/usr/bin/env python3
"""네트워크 없이 파서/점수/사이트 생성이 잘 도는지 확인한다.

    python3 content-engine/selftest.py
"""

import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import collect  # noqa: E402
import draft  # noqa: E402

RSS_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Sample</title>
  <item>
    <title>OpenAI, &#48120;&#46020;&#50864; &#49888;&#44508; LLM &#52636;&#49884;</title>
    <link>https://example.com/a</link>
    <description>&lt;p&gt;&#49373;&#49457;&#54805; AI &#49884;&#51109;&#51012; &#45209;&#44396;&#45716; &#49688;&#51012;&lt;/p&gt;</description>
    <pubDate>Wed, 27 Aug 2026 09:00:00 +0000</pubDate>
  </item>
  <item>
    <title>&#48512;&#44256; &#50508;&#47548;</title>
    <link>https://example.com/b</link>
    <description>&#44288;&#47144; &#50630;&#45716; &#44544;</description>
    <pubDate>Wed, 27 Aug 2026 08:00:00 +0000</pubDate>
  </item>
</channel></rss>"""

ATOM_SAMPLE = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Sample Atom</title>
  <entry>
    <title>Anthropic launches new Claude model</title>
    <link rel="alternate" href="https://example.org/claude"/>
    <summary>An open source friendly launch for developers.</summary>
    <published>2026-08-27T10:00:00Z</published>
  </entry>
</feed>"""

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


print("1) RSS 2.0 파싱")
rss_items = collect.parse_feed(RSS_SAMPLE, "sample-rss")
check("항목 2건 추출", len(rss_items) == 2, f"-> {len(rss_items)}")
check("제목 파싱", rss_items[0]["title"] == "OpenAI, 미도우 신규 LLM 출시", f"-> {rss_items[0]['title']}")
check("링크 파싱", rss_items[0]["link"] == "https://example.com/a")
check("HTML 태그 제거", "<p>" not in rss_items[0]["summary"], f"-> {rss_items[0]['summary']}")
check("RFC822 날짜 파싱", rss_items[0]["published"].startswith("2026-08-27T09:00"))

print("2) Atom 파싱")
atom_items = collect.parse_feed(ATOM_SAMPLE, "sample-atom")
check("항목 1건 추출", len(atom_items) == 1)
check("href 링크 파싱", atom_items[0]["link"] == "https://example.org/claude")
check("ISO 날짜 파싱", atom_items[0]["published"].startswith("2026-08-27T10:00"))

print("3) 중복 판정용 id")
check("같은 링크면 같은 id", collect.parse_feed(RSS_SAMPLE, "x")[0]["id"] == rss_items[0]["id"])
check("다른 링크면 다른 id", rss_items[0]["id"] != rss_items[1]["id"])

print("4) 점수 계산")
# 사용자가 config.json 을 바꿔도 검사 결과가 흔들리면 안 되므로 고정 설정을 쓴다.
config = {
    "brand": {"title": "테스트 브리핑", "tagline": "검사용", "author": "tester"},
    "keywords": {"OpenAI": 3, "LLM": 3, "Anthropic": 2, "open source": 2, "launch": 1},
    "blocklist": ["부고", "인사말"],
    "draft": {"picks": 5, "headline_candidates": 5, "max_age_hours": 48},
}
scored = draft.score_items(rss_items + atom_items, config, now=draft.parse_when("2026-08-27T12:00:00+00:00"))
check("키워드 있는 글이 위로", scored[0]["title"] != "부고 알림", f"-> {scored[0]['title']}")
check("차단어 글 제외", all(item["title"] != "부고 알림" for item in scored))
check("점수 부여됨", scored[0]["score"] > 0, f"-> {scored[0]['score']}")

print("5) 초안 markdown 생성")
body = draft.render_draft(scored, config, "2026-08-27")
check("제목 포함", config["brand"]["title"] in body)
check("링크 포함", "https://example.org/claude" in body)
check("체크리스트 포함", "발행 전 체크리스트" in body)

print("6) 마크다운 -> HTML 변환")
import build_site  # noqa: E402

html_out = build_site.markdown_to_html("# 제목\n\n본문 **굵게** 와 [링크](https://a.b)\n\n- 하나\n- 둘\n")
check("헤딩 변환", "<h1>제목</h1>" in html_out, f"-> {html_out[:60]}")
check("굵게 변환", "<strong>굵게</strong>" in html_out)
check("링크 변환", '<a href="https://a.b"' in html_out)
check("목록 변환", "<li>하나</li>" in html_out)
check("HTML 이스케이프", "&lt;script&gt;" in build_site.markdown_to_html("<script>x</script>"))

print("7) 페이지 메타데이터 / 구독 박스")
brand_off = {"title": "Test", "tagline": "t", "author": "a", "lang": "en-AU", "base_url": ""}
brand_on = dict(brand_off, subscribe_url="https://example.substack.com", base_url="https://ex.com",
                subscribe_heading="Join", subscribe_blurb="Free weekly")
off = build_site.page(brand_off, "제목", "<p>본문</p>", description="설명입니다", canonical="a.html")
on = build_site.page(brand_on, "제목", "<p>본문</p>", description="설명입니다", canonical="a.html")
check("lang 반영", 'lang="en-AU"' in off)
check("description 반영", 'content="설명입니다"' in off)
check("og:title 있음", 'property="og:title"' in off)
check("구독 URL 없으면 버튼 없음", '<section class="subscribe">' not in off)
check("구독 URL 있으면 버튼 있음", "example.substack.com" in on and "Join" in on)
check("base_url 없으면 canonical 없음", "rel=\"canonical\"" not in off)
check("base_url 있으면 canonical 절대주소", 'rel="canonical" href="https://ex.com/a.html"' in on)
sample_md = "# 제목\n\n실제 **본문** 첫 줄\n"
extracted = build_site.first_paragraph(sample_md)
check("첫 문단 추출", extracted == "실제 본문 첫 줄", f"-> {extracted!r}")

print("8) RSS 피드")
feed = build_site.build_feed(brand_on, [{"title": "글 <제목>", "slug": "a.html",
                                          "description": "요약", "rfc822": "Sun, 30 Aug 2026 00:00:00 +0000"}])
check("XML 선언", feed.startswith("<?xml"))
check("항목 포함", "<item>" in feed and "a.html" in feed)
check("특수문자 이스케이프", "글 &lt;제목&gt;" in feed)

print()
if failures:
    print(f"실패 {len(failures)}건: {', '.join(failures)}")
    raise SystemExit(1)
print("전부 통과.")
