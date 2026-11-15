"""
run_extraction.py

Runs extract_wiki_senses.py from a file instead of the terminal.
Edit the settings below, then press "Run" in your editor (VS Code,
PyCharm, Spyder, etc.). Keep this file in the same folder as
extract_wiki_senses.py and senses.json.
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
CONFIG_FILE  = "extra_words.json"        # currently contains only "bat"
CONTACT      = "jweinstei1@haverford.edu"  # email or project URL for Wikipedia
OUT_PREFIX   = "wiki_nat"           # output files start with this name
MAX_ARTICLES = 1000                  # small cap for a quick test run
PER_SENSE    = 10                   # sentences sampled per sense
LOWERCASE    = False                # True only if COSMOS's BERT is uncased

# ---------------------------------------------------------------------------
# Hand the settings to the script exactly as if typed in a terminal.
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
# Quick look at the results so you don't have to open the files.
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