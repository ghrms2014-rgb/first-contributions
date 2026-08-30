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
config = collect.load_config()
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

print()
if failures:
    print(f"실패 {len(failures)}건: {', '.join(failures)}")
    raise SystemExit(1)
print("전부 통과.")
