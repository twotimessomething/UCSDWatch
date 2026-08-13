#!/usr/bin/env python3
"""
Watches UCSD Surplus for new laptops / Apple Silicon Mac minis.
Stdlib only. Keeps a JSON file of listing IDs it has already reported.
"""

import json
import os
import re
import sys
import time
import urllib.request

# Newest-first pages we scan. Two pages of the computer category = 48 newest items,
# which comfortably covers even a big single-day dump of new inventory.
PAGES = [
    "https://surplus.ucsd.edu/Browse/C161155/ComputerData-Processing-Equip",
    "https://surplus.ucsd.edu/Browse/C161155/ComputerData-Processing-Equip?page=1",
]

STATE_FILE = "seen.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")  # e.g. "ucsd-surplus-a7f3k9"

# --- what counts as a hit -------------------------------------------------
# Slugs are uppercase-ish and hyphenated, e.g. COMPUTER-LAPTOP-14-i5-10310-17GHZ
WANT = re.compile(r"LAPTOP|MACBOOK|NOTEBOOK|MAC-?MINI", re.I)

# Intel-era Mac minis and junk we don't want. Applied only to MAC MINI hits,
# so an Intel PC laptop still comes through.
INTEL_MINI = re.compile(r"MAC-?MINI", re.I)
NOT_APPLE_SILICON = re.compile(r"\bi[357]\b|CORE-2|C2D|\b20(09|10|11|12|13|14)\b", re.I)

LINK = re.compile(r"/Listing/Details/(\d+)/([A-Za-z0-9\-]+)")


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "personal-listing-watcher/1.0 (hobby project)"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def matches(slug):
    if not WANT.search(slug):
        return False
    if INTEL_MINI.search(slug) and NOT_APPLE_SILICON.search(slug):
        return False
    return True


def notify(title, body, url):
    if not NTFY_TOPIC:
        print(f"[no NTFY_TOPIC set] {title}: {url}")
        return
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


def main():
    try:
        with open(STATE_FILE) as f:
            seen = set(json.load(f))
    except FileNotFoundError:
        seen = set()

    first_run = not seen
    found = {}

    for url in PAGES:
        html = fetch(url)
        for listing_id, slug in LINK.findall(html):
            if listing_id not in found and matches(slug):
                found[listing_id] = slug
        time.sleep(2)  # be polite

    new = {k: v for k, v in found.items() if k not in seen}

    if first_run:
        # Don't spam yourself with 20 alerts the very first time.
        print(f"First run — baselining {len(found)} existing matches, no alerts sent.")
    else:
        for listing_id, slug in sorted(new.items(), reverse=True):
            title = slug.replace("-", " ")
            link = f"https://surplus.ucsd.edu/Listing/Details/{listing_id}"
            print("NEW:", title, link)
            notify("UCSD Surplus", title, link)

    seen |= set(found)
    # Keep the state file from growing forever.
    seen = set(sorted(seen, reverse=True)[:2000])

    with open(STATE_FILE, "w") as f:
        json.dump(sorted(seen, reverse=True), f, indent=0)

    print(f"Scanned {len(found)} matching listings, {0 if first_run else len(new)} new.")


if __name__ == "__main__":
    sys.exit(main())
