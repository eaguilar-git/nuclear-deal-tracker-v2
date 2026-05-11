"""test_candidate_feeds.py — find working RSS feeds for entities in the v0.4 database.

Tests ~45 candidate feed URLs for utilities, vendors, hyperscalers, government,
and policy actors that we're tracking but don't yet have feed coverage for.

Prints which ones actually return RSS data. Add the working ones to scraper.py.

    python3 test_candidate_feeds.py
"""

import requests
import feedparser
import time


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


CANDIDATES = [
    # ── Major utilities (each has multiple sites in our database) ──────────
    ("Constellation IR (alt 1)",     "https://investors.constellationenergy.com/rss/news-releases.xml"),
    ("Constellation IR (alt 2)",     "https://www.constellationenergy.com/newsroom.rss"),
    ("Constellation IR (alt 3)",     "https://investors.constellationenergy.com/news-and-events/news-releases/rss"),
    ("Duke Energy News (alt 1)",     "https://news.duke-energy.com/rss"),
    ("Duke Energy News (alt 2)",     "https://news.duke-energy.com/press-releases.rss"),
    ("Dominion Energy (alt 1)",      "https://news.dominionenergy.com/rss"),
    ("Dominion Energy (alt 2)",      "https://news.dominionenergy.com/all-news/rss"),
    ("Southern Co (alt 1)",          "https://www.southerncompany.com/newsroom.rss"),
    ("Southern Co (alt 2)",          "https://www.southerncompany.com/news/rss.xml"),
    ("NextEra Energy News",          "https://www.investor.nexteraenergy.com/news-and-events/news-releases/rss"),
    ("NextEra (alt)",                "https://www.nexteraenergy.com/news/rss.xml"),
    ("Entergy Newsroom",             "https://www.entergynewsroom.com/news/rss"),
    ("Vistra IR",                    "https://investor.vistracorp.com/news-releases/rss"),
    ("Xcel Energy News",             "https://www.xcelenergy.com/newsroom/rss"),
    ("Energy Northwest News",        "https://www.energy-northwest.com/whoweare/news/Pages/rss.aspx"),
    ("PSEG News",                    "https://www.pseg.com/newsroom/rss"),
    ("AEP News",                     "https://aep.com/news/rss"),

    # ── Major vendors (some had dead feeds in v3.0) ────────────────────────
    ("TerraPower (alt 1)",           "https://www.terrapower.com/feed/"),
    ("TerraPower (alt 2)",           "https://www.terrapower.com/rss"),
    ("Westinghouse (alt 1)",         "https://info.westinghousenuclear.com/blog/rss.xml"),
    ("Westinghouse (alt 2)",         "https://www.westinghousenuclear.com/news/feed/"),
    ("NuScale (alt 1)",              "https://www.nuscalepower.com/feed"),
    ("NuScale (alt 2)",              "https://www.nuscalepower.com/news.rss"),
    ("Kairos Power (alt)",           "https://kairospower.com/feed"),
    ("Oklo IR (alt 1)",              "https://investors.oklo.com/news-releases/rss"),
    ("Oklo IR (alt 2)",              "https://www.oklo.com/news-events/rss"),
    ("GE Vernova Newsroom (alt 1)",  "https://www.gevernova.com/news/rss"),
    ("GE Vernova Newsroom (alt 2)",  "https://www.gevernova.com/feed/news.xml"),
    ("CFS News (alt 1)",             "https://cfs.energy/feed/"),
    ("CFS News (alt 2)",             "https://www.cfsenergy.com/feed/"),
    ("Last Energy News",             "https://www.lastenergy.com/feed/"),
    ("Aalo Atomics",                 "https://aaloatomics.com/feed/"),
    ("Radiant Industries",           "https://www.radiantnuclear.com/feed/"),
    ("BWXT IR",                      "https://investor.bwxt.com/news-releases/rss"),
    ("Fermi America",                "https://fermienergia.com/feed/"),

    # ── Government / regulatory (beyond NRC + DOE) ─────────────────────────
    ("DOE LPO News",                 "https://www.energy.gov/lpo/rss.xml"),
    ("White House Briefing Room",    "https://www.whitehouse.gov/briefing-room/feed/"),
    ("EXIM Bank News",               "https://www.exim.gov/news/feed"),

    # ── Trade press additions ──────────────────────────────────────────────
    ("Reuters Energy",               "https://www.reuters.com/business/energy/rss"),
    ("Bloomberg Green Energy",       "https://www.bloomberg.com/feed/green/energy.xml"),
    ("Axios Pro Energy",             "https://www.axios.com/energy/feed.xml"),
    ("E&E News",                     "https://www.eenews.net/rss"),
    ("Reuters Sustainability",       "https://www.reuters.com/sustainability/feed"),

    # ── State governors / industry orgs ────────────────────────────────────
    ("NY Governor News",             "https://www.governor.ny.gov/news.rss"),
    ("Illinois Governor News",       "https://www.illinois.gov/news.rss"),
    ("Virginia Governor News",       "https://www.governor.virginia.gov/newsroom/news-releases.rss"),
    ("Texas Governor News",          "https://gov.texas.gov/news.rss"),
    ("Wyoming Governor News",        "https://governor.wyo.gov/news/rss"),
    ("USNIC / NIA News",             "https://nuclearinnovationalliance.org/feed"),
    ("Third Way Climate Energy",     "https://www.thirdway.org/climate-and-energy/rss"),
    ("ClearPath Action",             "https://clearpath.org/feed"),
]


def test_feed(name, url):
    """Try to fetch and parse a feed. Returns (status, n_entries, content_type, err)."""
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=15, allow_redirects=True)
        ct = r.headers.get("Content-Type", "")[:30]
        parsed = feedparser.parse(r.content)
        return r.status_code, len(parsed.entries), ct, None
    except requests.exceptions.Timeout:
        return None, 0, "", "timeout"
    except requests.exceptions.ConnectionError:
        return None, 0, "", "conn error"
    except Exception as e:
        return None, 0, "", f"{type(e).__name__}: {str(e)[:30]}"


def main():
    print(f"Testing {len(CANDIDATES)} candidate feeds...\n")
    working = []
    for name, url in CANDIDATES:
        status, n, ct, err = test_feed(name, url)
        if err:
            print(f"  [ERR  ] {name:32s} {err}")
        elif n > 0:
            print(f"  [OK   ] {name:32s} HTTP {status} | {n} entries | {ct}")
            working.append((name, url, n))
        else:
            print(f"  [EMPTY] {name:32s} HTTP {status} | {n} entries | {ct}")
        time.sleep(0.3)

    print(f"\n{'═'*70}")
    print(f"Summary: {len(working)} candidate feed(s) work")
    print(f"{'═'*70}\n")

    if working:
        print("ADD THESE TO scraper.py FEEDS list (copy these lines):\n")
        for name, url, n in working:
            # Strip "(alt 1)" type suffixes from the printed name
            clean_name = name.split(" (")[0]
            ent = "nuclear_only" in name.lower() or "trade press" in name.lower()
            extra = ', "nuclear_only": True' if ent else ''
            # Decide on nuclear_only: probably True for hyperscaler/general trade press,
            # False for vendors/utilities (their newsrooms are mostly nuclear-relevant)
            general_purpose_keywords = ['reuters', 'bloomberg', 'axios', 'governor', 'white house']
            needs_filter = any(k in name.lower() for k in general_purpose_keywords)
            extra = ', "nuclear_only": True' if needs_filter else ''
            print(f'    {{"name": "{clean_name}",  "url": "{url}"{extra}}},')
        print()


if __name__ == "__main__":
    main()
