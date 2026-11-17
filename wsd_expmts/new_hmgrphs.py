"""
run_extraction.py

Note: word_dict.json should be in the same folder and is a dictionary. For each homograph key, 
multiple senses are given as values. Each value should have appropriate hyperlink/page associated with wiki data
Format is dict[homograph] = str(value): str(wikipedia page)

To confirm that all wiki pages exist, check_wiki.py should run and confirm before this script is run.
"""

import json
import os
import sys

# Make sure Python finds the other files no matter where you run this from.
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

import get_wikiWords  # the extraction script

# ---------------------------------------------------------------------------
# SETTINGS (to edit)
# ---------------------------------------------------------------------------
CONFIG_FILE  = "word_dict.json"        # contains a mix of CoarseWSD-20 words and custom homograph labels
CONTACT      = "jweinstei1@haverford.edu"  # email or project URL for Wikipedia
OUT_PREFIX   = "[DATASET]"           # output files start with this name
MAX_ARTICLES = 1000                 # arbitrary cap to start
PER_SENSE    = 10                   # sentences sampled per sense, 2 senses per word
LOWERCASE    = False                # True only if COSMOS's BERT were uncased, but it's cased

# ---------------------------------------------------------------------------
# Settings passed in exactly as written above.
# ---------------------------------------------------------------------------
sys.argv = [
    "extract_wiki_senses.py",
    "--config", CONFIG_FILE,
    "--email", CONTACT,
    "--out-prefix", OUT_PREFIX,
    "--max-articles", str(MAX_ARTICLES),
    "--per-sense", str(PER_SENSE),
]
if LOWERCASE:
    sys.argv.append("--lowercase")

get_wikiWords.main()

# ---------------------------------------------------------------------------
# Quick look to confirm functionality.
# ---------------------------------------------------------------------------
print("\n--- Counts per sense ---")
with open(f"{OUT_PREFIX}_counts.json") as f:
    print(json.dumps(json.load(f)["counts"], indent=2))

print("\n--- Sampled sentences ---")
with open(f"{OUT_PREFIX}_sampled.jsonl") as f:
    for line in f:
        row = json.loads(line)
        start, end = row["char_span"]
        text = row["text"]
        # Show the homograph in [brackets] so you can check the span is right.
        marked = text[:start] + "*[" + text[start:end] + "]*" + text[end:]
        print(f"{row['sense_id']:15s} {marked}")