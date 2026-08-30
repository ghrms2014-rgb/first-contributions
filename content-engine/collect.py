#!/usr/bin/env python3
"""RSS/Atom 피드를 모아 data/items.json 에 쌓는다.

외부 라이브러리를 쓰지 않는다(파이썬 표준 라이브러리만). 그래야
pip install 없이 GitHub Actions 무료 러너에서 그대로 돈다.
"""

import hashlib
import html
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
ITEMS_PATH = os.path.join(BASE, "data", "items.json")

USER_AGENT = "content-engine/1.0 (+https://github.com/)"
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as fp:
        return json.load(fp)


def ssl_context():
    """사내 프록시 등으로 CA 번들이 지정된 환경도 그대로 지원한다."""
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


def fetch(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return response.read()


def strip_tags(text):
    if not text:
        return ""
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return SPACE_RE.sub(" ", text).strip()


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def find_text(element, *names):
    for child in element:
        if local_name(child.tag) in names:
            return (child.text or "").strip()
    return ""


def find_link(element):
    """RSS는 <link>텍스트</link>, Atom은 <link href="..."/> 를 쓴다."""
    fallback = ""
    for child in element:
        if local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        rel = child.attrib.get("rel", "alternate")
        if href and rel == "alternate":
            return href.strip()
        if href and not fallback:
            fallback = href.strip()
        if child.text and child.text.strip():
            return child.text.strip()
    return fallback


def parse_date(raw):
    if not raw:
        return None
    raw = raw.strip()
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_feed(raw_bytes, source_name):
    root = ElementTree.fromstring(raw_bytes)
    entries = []
    for element in root.iter():
        if local_name(element.tag) in ("item", "entry"):
            entries.append(element)

    items = []
    for entry in entries:
        title = strip_tags(find_text(entry, "title"))
        link = find_link(entry)
        if not title or not link:
            continue
        summary = strip_tags(
            find_text(entry, "description", "summary", "content", "encoded")
        )
        published = parse_date(
            find_text(entry, "pubDate", "published", "updated", "date")
        )
        items.append(
            {
                "id": hashlib.sha1(link.encode("utf-8")).hexdigest()[:16],
                "source": source_name,
                "title": title,
                "link": link,
                "summary": summary[:600],
                "published": published.isoformat() if published else None,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return items


def load_existing():
    if not os.path.exists(ITEMS_PATH):
        return []
    try:
        with open(ITEMS_PATH, encoding="utf-8") as fp:
            return json.load(fp)
    except (json.JSONDecodeError, OSError):
        return []


def prune(items, keep_days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    kept = []
    for item in items:
        stamp = item.get("published") or item.get("collected_at")
        moment = parse_date(stamp)
        if moment is None or moment >= cutoff:
            kept.append(item)
    return kept


def main():
    config = load_config()
    timeout = config["collect"]["timeout_seconds"]
    keep_days = config["collect"]["keep_days"]

    existing = load_existing()
    known = {item["id"] for item in existing}

    added = 0
    failures = []
    for source in config["sources"]:
        if not source.get("enabled", True):
            continue
        try:
            raw = fetch(source["url"], timeout)
            items = parse_feed(raw, source["name"])
        except Exception as error:  # 피드 하나가 죽어도 전체는 계속 돈다
            failures.append(f"{source['name']}: {type(error).__name__}: {error}")
            print(f"  [실패] {source['name']} -> {error}", file=sys.stderr)
            continue

        fresh = [item for item in items if item["id"] not in known]
        for item in fresh:
            known.add(item["id"])
        existing.extend(fresh)
        added += len(fresh)
        print(f"  [수집] {source['name']}: {len(items)}건 중 신규 {len(fresh)}건")

    existing = prune(existing, keep_days)
    existing.sort(key=lambda item: item.get("published") or "", reverse=True)

    os.makedirs(os.path.dirname(ITEMS_PATH), exist_ok=True)
    with open(ITEMS_PATH, "w", encoding="utf-8") as fp:
        json.dump(existing, fp, ensure_ascii=False, indent=1)

    print(f"신규 {added}건 추가, 보관 중 {len(existing)}건 -> {ITEMS_PATH}")
    if failures:
        print(f"실패한 소스 {len(failures)}개: config.json 에서 URL을 확인하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
