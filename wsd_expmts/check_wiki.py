"""

To run this BEFORE extract_wiki_senses.py. For every page in senses.json it
reports whether the title exists, what it redirects to, whether it is a
disambiguation page, and roughly how many articles link to it.

Should be in the same folder as word_dict.json.
"""

import json
import os
import time

import requests

CONFIG_FILE = "word_dict.json"
CONTACT = "jweinstei1@haverford.edu"   # same contact for the extractor

os.chdir(os.path.dirname(os.path.abspath(__file__)))
API = "https://en.wikipedia.org/w/api.php"
S = requests.Session()
S.headers["User-Agent"] = f"HomographThesis/0.1 ({CONTACT})"

def get(params):
    params = {**params, "format": "json", "formatversion": 2}
    return S.get(API, params=params, timeout=30).json()


def page_info(title):
    """Does the page exist? Where does it redirect? Is it a disambiguation page?"""
    data = get({"action": "query", "titles": title, "redirects": 1,
                "prop": "pageprops", "ppprop": "disambiguation"})
    q = data["query"]
    final = q["redirects"][0]["to"] if q.get("redirects") else title
    page = q["pages"][0]
    missing = page.get("missing", False)
    disambig = "disambiguation" in page.get("pageprops", {})
    return final, missing, disambig


def count_backlinks(title, cap=500):
    """Count articles linking to the page (direct + via redirects), up to cap."""
    data = get({"action": "query", "list": "backlinks", "bltitle": title,
                "blnamespace": 0, "bllimit": cap, "blredirect": 1})
    n = 0
    for item in data["query"]["backlinks"]:
        n += len(item.get("redirlinks", [])) if item.get("redirect") else 1
    more = "continue" in data
    return f"{n}+" if more else str(n)


config = json.load(open(CONFIG_FILE)) # config file defined at the top
problems = []
for word, senses in config.items():
    print(f"\n== {word} ==")
    for sense_id, pages in senses.items():
        for page in (pages if isinstance(pages, list) else [pages]):
            final, missing, disambig = page_info(page)
            if missing:
                status = "MISSING - fix this title"
                problems.append((word, sense_id, page, "missing"))
            elif disambig:
                status = "DISAMBIGUATION PAGE - pick a specific article"
                problems.append((word, sense_id, page, "disambiguation"))
            else:
                status = f"ok, ~{count_backlinks(final)} linking articles"
            arrow = f" -> {final}" if final != page else ""
            print(f"  {sense_id:22s} {page}{arrow}: {status}")
            time.sleep(0.3)

print("\n--- Titles to fix ---" if problems else "\nAll titles look valid.")
for p in problems:
    print("  ", *p)