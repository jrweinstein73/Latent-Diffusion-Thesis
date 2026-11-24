import requests
import time

S = requests.Session()
S.headers["User-Agent"] = "HomographThesis/0.1 (your_email@haverford.edu)"
API = "https://en.wikipedia.org/w/api.php"

def backlinks(title, redirects_only=False):
    params = {"action": "query", "list": "backlinks", "bltitle": title,
              "blnamespace": 0, "bllimit": "max", "format": "json"}
    if redirects_only:
        params["blfilterredir"] = "redirects"
    else:
        params["blredirect"] = 1  # include pages linking via redirects
    while True:
        r = S.get(API, params=params).json()
        for item in r["query"]["backlinks"]:
            if "redirect" in item and redirects_only: 
                yield from item.get("redirlinks", [])
            else:
                yield item
            if "continue" not in r:
                break
            params.update(r["continue"])
            time.sleep(0.5)