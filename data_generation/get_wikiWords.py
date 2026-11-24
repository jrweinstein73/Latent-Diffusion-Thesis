#!/usr/bin/env python3
"""
extract_wiki_senses.py

Builds sense-labeled "natural" sentences for homographs from Wikipedia,
following the CoarseWSD-20 recipe (Loureiro et al., 2021): a hyperlink like
[[Bank (geography)|bank]] tells us which sense of "bank" the writer meant.

Workflow:
  1. For each sense page, ask the Wikipedia API which redirects point to it
     (alternate names that count as the same sense).
  2. Ask which articles link to it (directly or via a redirect), capped.
  3. Download those articles' wikitext in batches.
  4. Convert wikitext to plain text while remembering where each link sits.
  5. Split into sentences; keep sentences where a link's visible text is
     exactly the homograph and the link points to one of our sense pages.
  6. Filter, deduplicate, sample N per sense, write JSONL in our schema.

Usage:
  pip install requests mwparserfromhell
  python extract_wiki_senses.py --config senses.json --email you@haverford.edu
"""

import argparse
import json
import random
import re
import time
from datetime import date
from itertools import islice

import requests
import mwparserfromhell as mwp
from mwparserfromhell.nodes import (
    Comment, ExternalLink, Heading, Tag, Template, Text, Wikilink,
)

API = "https://en.wikipedia.org/w/api.php"
S = requests.Session()  # one reusable connection for every request

# Link prefixes that are not articles (images, categories, other wikis...).
SKIP_NAMESPACES = {"file", "image", "category", "wikipedia", "wp", "template",
                   "help", "portal", "wikt", "wiktionary", "special", "talk"}
# Wikitext tags we drop entirely (footnotes, tables, math, code, galleries).
SKIP_TAGS = {"ref", "table", "math", "code", "pre", "gallery", "timeline",
             "references", "score", "syntaxhighlight", "chem"}
# List-item markup (*, #, ;, :). We tag those lines so we can drop them later.
LIST_TAGS = {"li", "dt", "dd"}
LIST_MARK = "\x00"  # invisible marker placed at the start of list lines


# ---------------------------------------------------------------------------
# 1–3. Talking to the Wikipedia API
# ---------------------------------------------------------------------------

def api_get(params, retries=5):
    """One API call with retries. 'maxlag' makes us back off when Wikipedia's
    servers are busy, which is the etiquette Wikimedia asks bots to follow."""
    params = {**params, "format": "json", "formatversion": 2, "maxlag": 5}
    for attempt in range(retries):
        try:
            data = S.get(API, params=params, timeout=30).json()
            # Server says "too busy": wait and retry the same request.
            if data.get("error", {}).get("code") == "maxlag":
                time.sleep(5)
                continue
            if "error" in data:
                raise RuntimeError(data["error"])
            return data
        except (requests.RequestException, ValueError):
            time.sleep(2 ** attempt)  # network hiccup: exponential backoff
    raise RuntimeError(f"API failed after {retries} tries: {params}")


def backlinks(title, redirects_only=False):
    """Yield pages linking to `title`.
    redirects_only=True  -> the redirect pages themselves ("River bank").
    redirects_only=False -> articles linking directly OR through a redirect."""
    params = {"action": "query", "list": "backlinks", "bltitle": title,
              "blnamespace": 0, "bllimit": "max"}
    if redirects_only:
        params["blfilterredir"] = "redirects"
    else:
        params["blredirect"] = 1  # also return pages that link via redirects


    while True:
        data = api_get(params)
        for item in data["query"]["backlinks"]:
            # With blredirect, a redirect appears as one entry whose
            # 'redirlinks' holds the articles that link through it. Unpack them.
            if item.get("redirect") and not redirects_only:
                yield from item.get("redirlinks", [])
            else:
                yield item
        # Results come 500 at a time; 'continue' is the bookmark for the next page.
        if "continue" not in data:
            break
        params.update(data["continue"])
        time.sleep(0.5)  # small pause between pages


def fetch_wikitext(titles, batch=50):
    """Yield (title, wikitext) for each title, 50 per request (the API max)."""
    titles = list(titles)
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        data = api_get({"action": "query", "prop": "revisions",
                        "rvprop": "content", "rvslots": "main",
                        "titles": "|".join(chunk)})
        for page in data["query"]["pages"]:
            # Deleted/missing pages come back without revisions; skip them.
            revs = page.get("revisions")
            if revs:
                yield page["title"], revs[0]["slots"]["main"]["content"]
        print(f"    fetched {min(i + batch, len(titles))}/{len(titles)} articles")
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# 4. Wikitext -> plain text, keeping link positions
# ---------------------------------------------------------------------------

def normalize_title(t):
    """Make link targets comparable to API titles: drop '#section', turn
    underscores into spaces, capitalize the first letter (Wikipedia does)."""
    t = re.sub(r"\s+", " ", t.split("#")[0].replace("_", " ")).strip()
    return t[:1].upper() + t[1:]


def to_text_with_links(wikitext):
    """Return (plain_text, links). Each link is (start, end, anchor, target)
    with character offsets into plain_text."""
    pieces, links = [], []
    length = 0  # running length of the text built so far

    def emit(s):
        nonlocal length
        pieces.append(s)
        length += len(s)

    def walk(nodes):
        for node in nodes:
            if isinstance(node, Text):
                emit(str(node.value))

            elif isinstance(node, Wikilink):
                title = str(node.title).strip()
                # Skip [[File:...]], [[Category:...]], interwiki links, etc.
                prefix = title.lstrip(":").split(":")[0].lower()
                if ":" in title and prefix in SKIP_NAMESPACES:
                    continue
                # Visible text: the part after '|' if present, else the title.
                anchor = node.text.strip_code().strip() if node.text else title
                start = length
                emit(anchor)
                links.append((start, length, anchor, normalize_title(title)))

            elif isinstance(node, Tag):
                tag = str(node.tag).lower()
                if tag in SKIP_TAGS:
                    continue  # drop footnotes, tables, etc. entirely
                if tag in LIST_TAGS:
                    emit(LIST_MARK)  # remember this line is a list item
                elif node.contents:
                    walk(node.contents.nodes)  # bold/italic/span: keep insides

            elif isinstance(node, Heading):
                emit("\n")  # section titles are not sentences

            elif isinstance(node, ExternalLink):
                if node.title:
                    emit(node.title.strip_code())  # keep visible link text

            elif isinstance(node, (Template, Comment)):
                continue  # infoboxes, citations, {{...}} and <!-- --> dropped

    walk(mwp.parse(wikitext).nodes)
    return "".join(pieces), links


# ---------------------------------------------------------------------------
# 5. Sentences and filtering
# ---------------------------------------------------------------------------

# A sentence boundary: . ! or ? followed by space and an uppercase/quote/digit.
# Simple and imperfect (e.g. "U.S. Navy"); your manual check catches misses.
BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"“(])')


def sentence_spans(text):
    """Yield (start, end) of each sentence, line by line (one line = one
    paragraph in wikitext). Lines that are list items are skipped."""
    offset = 0
    for line in text.split("\n"):
        if line and not line.lstrip().startswith(LIST_MARK):
            start = 0
            for m in BOUNDARY.finditer(line):
                yield offset + start, offset + m.start()
                start = m.end()
            yield offset + start, offset + len(line)
        offset += len(line) + 1  # +1 for the newline we split on


def clean(s):
    """Tidy leftovers from removed templates/footnotes: empty parentheses,
    space before punctuation, repeated whitespace."""
    s = re.sub(r"\(\s*[,;]?\s*\)", "", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return re.sub(r"\s+", " ", s)


def extract(article, wikitext, word, target_to_sense, args):
    """Yield candidate rows from one article for one homograph."""
    text, links = to_text_with_links(wikitext)
    for s_start, s_end in sentence_spans(text):
        for l_start, l_end, anchor, target in links:
            # The link must sit inside this sentence...
            if not (s_start <= l_start and l_end <= s_end):
                continue
            # ...show exactly the homograph as its visible text...
            if anchor.lower() != word:
                continue
            # ...not be glued to letters, as in [[bank]]s -> "banks"...
            before = text[l_start - 1:l_start]
            after = text[l_end:l_end + 1]
            if before.isalpha() or after.isalpha():
                continue
            # ...and point (directly or via redirect) at one of our senses.
            sense = target_to_sense.get(target)
            if sense is None:
                continue

            # Clean the sentence and recompute where the homograph now sits.
            raw = text[s_start:s_end]
            sent = clean(raw).strip()
            prefix = clean(raw[:l_start - s_start]).lstrip()
            start = len(prefix)
            # Safety check: if cleaning shifted things, drop rather than guess.
            if sent[start:start + len(anchor)].lower() != word:
                continue

            # Quality filters (tune on the command line).
            n_words = len(sent.split())
            if not (args.min_words <= n_words <= args.max_words):
                continue  # too short to have context / too long for templates
            if len(re.findall(rf"\b{re.escape(word)}\b", sent, re.I)) != 1:
                continue  # homograph appears twice: ambiguous target
            if sent.count(",") > args.max_commas:
                continue  # comma-heavy = probably a list in disguise
            if sent[-1:] not in ".!?":
                continue  # fragments, captions, headings

            yield {"article_title": article, "sense_id": sense,
                   "text": sent.lower() if args.lowercase else sent,
                   "char_span": [start, start + len(anchor)]}


# ---------------------------------------------------------------------------
# 6. Main: run every word, dedupe, sample, write files
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True,
                    help='JSON: {"bank": {"bank_geography": "Bank (geography)", ...}}')
    ap.add_argument("--email", required=True, help="contact for the User-Agent")
    ap.add_argument("--max-articles", type=int, default=1000,
                    help="cap on linking articles fetched per sense")
    ap.add_argument("--per-sense", type=int, default=10,
                    help="sentences sampled per sense for the final file")
    ap.add_argument("--min-words", type=int, default=6)
    ap.add_argument("--max-words", type=int, default=40)
    ap.add_argument("--max-commas", type=int, default=4)
    ap.add_argument("--lowercase", action="store_true",
                    help="lowercase text (only if COSMOS's BERT is uncased)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out-prefix", default="wiki_natural")
    args = ap.parse_args()

    # Wikipedia asks scripts to identify themselves with contact info.
    S.headers["User-Agent"] = f"HomographThesis/0.1 ({args.email})"
    config = json.load(open(args.config))
    rng = random.Random(args.seed)  # fixed seed = reproducible sampling

    all_rows, sampled, summary = [], [], {}
    for word, senses in config.items(): # word is a string (key), senses is a dict of var: wiki page
        word = word.lower()
        print(f"\n== {word} ==")

        # A potential sense can either be one page (e.g. "Bat") or it can be a list of pages
        # For ease, we treat both as lists 
        # make a dict of sense (key) with values of its pages as a list of length ≥ 1
        get_pages = {s: (p if isinstance(p, list) else [p]) for s,p in senses.items()}

        # Step 1: every title that counts as each sense (page + its redirects).
        target_to_sense = {}
        for sense_id, pages in get_pages.items():
            for page in pages:
                target_to_sense[normalize_title(page)] = sense_id
                for r in backlinks(page, redirects_only=True):
                    target_to_sense[normalize_title(r["title"])] = sense_id
        print(f"  {len(target_to_sense)} titles map to {len(senses)} senses")

        # Step 2: articles linking to any sense (each fetched once).
        articles = set()
        for sense_id, pages in get_pages.items():
            for page in pages:
                found = {p["title"] for p in islice(backlinks(page), args.max_articles)}
                print(f"  {sense_id}: {len(found)} linking articles")
                articles |= found

        # Steps 3–5: download, convert, extract; drop duplicate sentences.
        seen, rows = set(), []
        for title, wikitext in fetch_wikitext(sorted(articles)):
            for row in extract(title, wikitext, word, target_to_sense, args):
                key = row["text"].lower()
                if key not in seen:
                    seen.add(key)
                    rows.append({"homograph": word, **row})

        # Raw counts per sense (biased by --max-articles; see summary note).
        counts = {s: sum(r["sense_id"] == s for r in rows) for s in senses}
        summary[word] = counts
        print(f"  extracted: {counts}")

        # Step 6: sample up to N per sense and give rows schema fields/ids.
        k = 0
        for sense_id in senses:
            pool = [r for r in rows if r["sense_id"] == sense_id]
            for r in rng.sample(pool, min(args.per_sense, len(pool))):
                k += 1
                sampled.append({
                    "id": f"{word}_nat_{k:03d}", "family_id": None,
                    "homograph": word, "sense_id": sense_id,
                    "sense_page": senses[sense_id], "condition": "natural",
                    "source": "wikipedia_links", "text": r["text"],
                    
                    "char_span": r["char_span"], "cue": None,
                    "cue_position": None, "cue_distance": None,
                    "context_level": None, "article_title": r["article_title"],
                    "retrieved": date.today().isoformat(),
                })
        all_rows.extend(rows)

    # Outputs: every candidate (for browsing), the sample, and the counts.
    with open(f"{args.out_prefix}_candidates.jsonl", "w") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(f"{args.out_prefix}_sampled.jsonl", "w") as f:
        for r in sampled:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(f"{args.out_prefix}_counts.json", "w") as f:
        json.dump({"note": "Counts reflect --max-articles caps; not a true "
                           "sense-frequency estimate for heavily linked senses.",
                   "counts": summary}, f, indent=2)
    print(f"\nWrote {len(all_rows)} candidates, {len(sampled)} sampled rows.")


if __name__ == "__main__":
    main()

