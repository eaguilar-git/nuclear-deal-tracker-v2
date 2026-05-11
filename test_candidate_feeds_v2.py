"""test_candidate_feeds_v2.py — find working RSS feeds using broader sources.

Round 2: Google News RSS queries, press release wires, additional NRC/regulatory
feeds, sector-specific aggregators.

    python3 test_candidate_feeds_v2.py
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
    # ── Google News RSS for vendors with dead native feeds ─────────────────
    # Format: https://news.google.com/rss/search?q=KEYWORDS&hl=en-US&gl=US&ceid=US:en
    # Note: "site:" filters work; quotes force exact phrase. Mix to control noise.
    ("GN: TerraPower",               "https://news.google.com/rss/search?q=%22TerraPower%22+Natrium+OR+Kemmerer+OR+reactor&hl=en-US&gl=US&ceid=US:en"),
    ("GN: NuScale Power",            "https://news.google.com/rss/search?q=%22NuScale%22+nuclear+OR+SMR&hl=en-US&gl=US&ceid=US:en"),
    ("GN: Kairos Power",             "https://news.google.com/rss/search?q=%22Kairos+Power%22+reactor+OR+Hermes&hl=en-US&gl=US&ceid=US:en"),
    ("GN: Oklo",                     "https://news.google.com/rss/search?q=%22Oklo%22+nuclear+OR+Aurora+OR+reactor&hl=en-US&gl=US&ceid=US:en"),
    ("GN: GE Vernova nuclear",       "https://news.google.com/rss/search?q=%22GE+Vernova%22+nuclear+OR+BWRX&hl=en-US&gl=US&ceid=US:en"),
    ("GN: Duke Energy nuclear",      "https://news.google.com/rss/search?q=%22Duke+Energy%22+nuclear+OR+reactor+OR+SMR&hl=en-US&gl=US&ceid=US:en"),
    ("GN: Dominion nuclear",         "https://news.google.com/rss/search?q=%22Dominion+Energy%22+nuclear+OR+reactor+OR+SMR&hl=en-US&gl=US&ceid=US:en"),
    ("GN: NextEra nuclear",          "https://news.google.com/rss/search?q=%22NextEra%22+nuclear+OR+Duane+Arnold&hl=en-US&gl=US&ceid=US:en"),
    ("GN: Southern Company nuclear", "https://news.google.com/rss/search?q=%22Southern+Company%22+nuclear+OR+Vogtle&hl=en-US&gl=US&ceid=US:en"),
    ("GN: Entergy nuclear",          "https://news.google.com/rss/search?q=%22Entergy%22+nuclear+OR+reactor&hl=en-US&gl=US&ceid=US:en"),
    ("GN: Vistra nuclear",           "https://news.google.com/rss/search?q=%22Vistra%22+nuclear+OR+Comanche+Peak&hl=en-US&gl=US&ceid=US:en"),
    ("GN: Xcel nuclear",             "https://news.google.com/rss/search?q=%22Xcel+Energy%22+nuclear+OR+Monticello+OR+%22Prairie+Island%22&hl=en-US&gl=US&ceid=US:en"),
    ("GN: PG&E Diablo Canyon",       "https://news.google.com/rss/search?q=%22Diablo+Canyon%22+OR+%22PG%26E%22+nuclear&hl=en-US&gl=US&ceid=US:en"),
    ("GN: PSEG nuclear",             "https://news.google.com/rss/search?q=%22PSEG%22+OR+%22Salem%22+OR+%22Hope+Creek%22+nuclear&hl=en-US&gl=US&ceid=US:en"),

    # Topics / focus areas
    ("GN: hyperscaler nuclear PPA",  "https://news.google.com/rss/search?q=%22nuclear%22+%22power+purchase%22+OR+%22PPA%22+data+center&hl=en-US&gl=US&ceid=US:en"),
    ("GN: US SMR deployment",        "https://news.google.com/rss/search?q=%22small+modular+reactor%22+OR+%22SMR%22+US+deployment&hl=en-US&gl=US&ceid=US:en"),
    ("GN: nuclear restart",          "https://news.google.com/rss/search?q=%22nuclear+plant+restart%22+OR+%22reactor+restart%22+US&hl=en-US&gl=US&ceid=US:en"),
    ("GN: NRC license renewal",      "https://news.google.com/rss/search?q=%22NRC%22+%22license+renewal%22+OR+%22SLR%22&hl=en-US&gl=US&ceid=US:en"),
    ("GN: DOE nuclear loan",         "https://news.google.com/rss/search?q=%22DOE%22+OR+%22Department+of+Energy%22+nuclear+%22loan%22+OR+%22grant%22&hl=en-US&gl=US&ceid=US:en"),
    ("GN: AP1000",                   "https://news.google.com/rss/search?q=%22AP1000%22+US+OR+%22VC+Summer%22+OR+Vogtle&hl=en-US&gl=US&ceid=US:en"),
    ("GN: BWRX-300",                 "https://news.google.com/rss/search?q=%22BWRX-300%22&hl=en-US&gl=US&ceid=US:en"),
    ("GN: Natrium reactor",          "https://news.google.com/rss/search?q=%22Natrium%22+reactor+OR+Wyoming&hl=en-US&gl=US&ceid=US:en"),
    ("GN: Xe-100",                   "https://news.google.com/rss/search?q=%22Xe-100%22+OR+%22X-energy%22&hl=en-US&gl=US&ceid=US:en"),
    ("GN: data center nuclear",      "https://news.google.com/rss/search?q=%22data+center%22+nuclear+%22Microsoft%22+OR+%22Amazon%22+OR+%22Google%22+OR+%22Meta%22&hl=en-US&gl=US&ceid=US:en"),

    # ── Additional NRC feeds (beyond what we have) ─────────────────────────
    ("NRC New Reactors",             "https://www.nrc.gov/reading-rm/doc-collections/new-reactors/rss.xml"),
    ("NRC Operating Reactors",       "https://www.nrc.gov/reading-rm/doc-collections/operating-reactors/rss.xml"),
    ("NRC Public Meeting Notices",   "https://www.nrc.gov/public-involve/public-meetings/rss.xml"),
    ("NRC Federal Register",         "https://www.nrc.gov/reading-rm/doc-collections/fr-notices/rss.xml"),

    # ── Press release wires ────────────────────────────────────────────────
    ("BusinessWire Energy",          "https://feeds.businesswire.com/BW/Industry/13-Energy"),
    ("BusinessWire Nuclear",         "https://feeds.businesswire.com/BW/Industry/13002-Nuclear"),
    ("PR Newswire Energy",           "https://www.prnewswire.com/rss/energy-utilities-latest-news/energy-utilities-latest-news-list.rss"),
    ("PR Newswire Utilities",        "https://www.prnewswire.com/rss/utilities-news-releases-list.rss"),
    ("GlobeNewswire Energy",         "https://www.globenewswire.com/RssFeed/industry/2300%20-%20Energy/feedTitle/GlobeNewswire%20-%20Energy"),
    ("AP Energy News",               "https://feeds.apnews.com/rss/apf-energy"),

    # ── Sector aggregators ─────────────────────────────────────────────────
    ("Energy Storage News (nuclear-adjacent)", "https://www.energy-storage.news/feed/"),
    ("Clean Energy Wire",            "https://www.cleanenergywire.org/rss.xml"),
    ("Yale Climate Connections",     "https://yaleclimateconnections.org/feed/"),
    ("Inside Climate News",          "https://insideclimatenews.org/feed/"),
    ("Greentech Media (TechCrunch)", "https://techcrunch.com/category/clean-energy/feed/"),
    ("CarbonBrief",                  "https://www.carbonbrief.org/feed/"),
    ("UtilityDive Energy",           "https://www.utilitydive.com/feeds/news/"),  # control - known working

    # ── Wire services (general but capture nuclear stories) ────────────────
    ("Reuters World News (alt)",     "https://feeds.reuters.com/Reuters/worldNews"),
    ("Bloomberg Markets (alt)",      "https://feeds.bloomberg.com/markets/news.rss"),
    ("CNBC Energy",                  "https://www.cnbc.com/id/19836768/device/rss/rss.html"),
    ("MarketWatch Energy",           "http://feeds.marketwatch.com/marketwatch/marketpulse/"),

    # ── DC policy / regulatory adjacent ────────────────────────────────────
    ("FERC News",                    "https://www.ferc.gov/news-events/news/feed"),
    ("EIA Press",                    "https://www.eia.gov/rss/press_rss.xml"),
    ("EIA Today in Energy",          "https://www.eia.gov/tools/rss/rss_news.xml"),
    ("EPA News",                     "https://www.epa.gov/newsreleases/all-news-releases.rss"),
    ("Senate ENR Committee",         "https://www.energy.senate.gov/rss/news.xml"),
    ("House E&C Committee",          "https://energycommerce.house.gov/news/feed"),

    # ── Think tanks / industry orgs (working URLs) ─────────────────────────
    ("Breakthrough Institute",       "https://thebreakthrough.org/feed"),
    ("RFF Energy",                   "https://www.rff.org/feed/"),
    ("EnergyWire",                   "https://www.eenews.net/feeds/energy/"),
    ("Greentech / Wood Mackenzie",   "https://www.woodmac.com/rss/"),
]


def test_feed(name, url):
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
            print(f"  [ERR  ] {name:45s} {err}")
        elif n > 0:
            print(f"  [OK   ] {name:45s} HTTP {status} | {n:3d} entries | {ct}")
            working.append((name, url, n))
        else:
            print(f"  [EMPTY] {name:45s} HTTP {status} | {n:3d} entries | {ct}")
        time.sleep(0.3)

    print(f"\n{'═'*80}")
    print(f"Summary: {len(working)} candidate feed(s) work")
    print(f"{'═'*80}\n")

    if working:
        print("Working feeds (review for usefulness before adding):\n")
        for name, url, n in working:
            print(f"  [{n:3d} entries] {name}")
            print(f"               {url}\n")


if __name__ == "__main__":
    main()
