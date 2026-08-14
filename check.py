#!/usr/bin/env python3
"""
Watches UCSD Surplus for new laptops / Apple Silicon Mac minis.
Stdlib only. Keeps a JSON file of listing IDs it has already reported.
"""

import html as htmllib
import json
import os
import re
import sys
import time
import urllib.request

# Newest-first pages we scan. Two pages of the computer category = 50 newest
# items, which comfortably covers even a big single-day dump of new inventory.
PAGES = [
    "https://surplus.ucsd.edu/Browse/C161155/ComputerData-Processing-Equip",
    "https://surplus.ucsd.edu/Browse/C161155/ComputerData-Processing-Equip?page=1",
]

STATE_FILE = "seen.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")  # e.g. "ucsd-surplus-a7f3k9"

# --- what counts as a hit -------------------------------------------------
WANT = re.compile(r"LAPTOP|MACBOOK|NOTEBOOK|MAC[\s-]?MINI", re.I)

# Intel-era Mac minis we don't want. Applied only to MAC MINI hits, so an
# Intel PC laptop still comes through. A1283/A1347/A1993 are the Apple model
# numbers for every 2009-2018 Intel mini; Apple Silicon starts at A2348 (M1).
IS_MINI = re.compile(r"MAC[\s-]?MINI", re.I)
INTEL_EVIDENCE = re.compile(
    r"\bi[357]\b|CORE\s*2|C2D|\b20(09|1[0-8])\b|\bA1283\b|\bA1347\b|\bA1993\b",
    re.I,
)

# --- page structure (verified against live HTML 2026-08-13) ---------------
SECTION = re.compile(r'<section data-listingid="(\d+)">(.*?)</section>', re.S)
TITLE = re.compile(r'class="title">\s*<a[^>]*>\s*(.*?)\s*</a>', re.S)
SUBTITLE = re.compile(r'class="subtitle">\s*<a[^>]*>\s*(.*?)\s*</a>', re.S)
STATUS = re.compile(r'status-type">\s*([^<]*?)\s*<')
PRICE = re.compile(r'NumberPart">([\d.,]+)')


def fetch(url, attempts=3):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "personal-listing-watcher/1.0 (hobby project)"},
    )
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(15)  # brief server blip: wait and retry


def parse_block(block):
    title = TITLE.search(block)
    if not title:
        return None
    subtitle = SUBTITLE.search(block)
    status = STATUS.search(block)
    price = PRICE.search(block)
    return {
        "title": htmllib.unescape(title.group(1)),
        "subtitle": htmllib.unescape(subtitle.group(1)) if subtitle else "",
        "status": status.group(1) if status else "",
        "price": f"${price.group(1)}" if price else "price n/a",
    }


def matches(info):
    text = f"{info['title']} {info['subtitle']}"
    if not WANT.search(text):
        return False
    if IS_MINI.search(text) and INTEL_EVIDENCE.search(text):
        return False
    return True


def notify(title, body, url):
    if not NTFY_TOPIC:
        print(f"[no NTFY_TOPIC set] {title}: {url}")
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8"),
                "Click": url,
                "Tags": "computer",
                "Priority": "high",
            },
        )
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        # A failed push must not kill the run: state would never be saved and
        # every already-sent alert would fire again next run.
        print(f"notify failed for {url}: {e}", file=sys.stderr)


def main():
    try:
        with open(STATE_FILE) as f:
            seen = set(json.load(f))
    except FileNotFoundError:
        seen = set()

    first_run = not seen
    found = {}
    sections = parsed = 0

    for url in PAGES:
        page = fetch(url)
        for listing_id, block in SECTION.findall(page):
            sections += 1
            info = parse_block(block)
            if info is None:
                continue
            parsed += 1
            if listing_id not in found and matches(info):
                found[listing_id] = info
        time.sleep(2)  # be polite

    if sections == 0 or parsed == 0:
        # Zero listings parsed means the page structure changed (or we're
        # blocked), not that the category is empty. Fail loudly so the
        # workflow goes red instead of silently never alerting again.
        print(
            f"Parsed {parsed} of {sections} listing blocks — "
            "page structure may have changed; refusing to save state.",
            file=sys.stderr,
        )
        return 1

    new = {k: v for k, v in found.items() if k not in seen}

    if first_run:
        # Don't spam yourself with 20 alerts the very first time.
        print(f"First run — baselining {len(found)} existing matches, no alerts sent.")
    else:
        for listing_id, info in sorted(new.items(), key=lambda kv: -int(kv[0])):
            link = f"https://surplus.ucsd.edu/Listing/Details/{listing_id}"
            detail = " · ".join(
                x for x in (info["price"], info["status"], info["subtitle"]) if x
            )
            print("NEW:", info["title"], "|", detail, "|", link)
            notify(info["title"], detail, link)

    seen |= set(found)
    # Keep the state file from growing forever. Numeric sort: string sort
    # would prune new IDs once they cross a digit-count boundary.
    seen = set(sorted(seen, key=int, reverse=True)[:2000])

    with open(STATE_FILE, "w") as f:
        json.dump(sorted(seen, key=int, reverse=True), f, indent=0)

    print(f"Scanned {sections} listings, {len(found)} matching, "
          f"{0 if first_run else len(new)} new.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
