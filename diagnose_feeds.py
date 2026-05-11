"""diagnose_feeds.py — probe every RSS feed and report failure mode."""
import requests, feedparser, time

FEEDS = [
    ("World Nuclear News",       "https://www.world-nuclear-news.org/rss"),
    ("ANS Nuclear Newswire",     "https://www.ans.org/news/feed"),
    ("NEI News",                 "https://www.nei.org/rss"),
    ("Power Magazine Nuclear",   "https://www.powermag.com/category/nuclear/feed/"),
    ("Power Engineering",        "https://www.power-eng.com/feed/"),
    ("Utility Dive",             "https://www.utilitydive.com/feeds/news/"),
    ("Neutron Bytes",            "https://neutronbytes.com/feed/"),
    ("Nuclear Engineering Intl", "https://www.neimagazine.com/rss"),
    ("Canary Media",             "https://www.canarymedia.com/rss"),
    ("Latitude Media",           "https://www.latitudemedia.com/feed"),
    ("Atomic Insights",          "https://atomicinsights.com/feed"),
    ("NucNet",                   "https://nucnet.org/feed.rss"),
    ("DOE Nuclear Energy",       "https://www.energy.gov/ne/rss.xml"),
    ("DOE News",                 "https://www.energy.gov/news/rss.xml"),
    ("NRC News",                 "https://www.nrc.gov/reading-rm/doc-collections/news/rss.xml"),
    ("NRC Press Releases",       "https://www.nrc.gov/reading-rm/doc-collections/press-releases/rss.xml"),
    ("IAEA Nuclear Power",       "https://www.iaea.org/feeds/topical/nuclear-power.xml"),
    ("IAEA Newscenter",          "https://www.iaea.org/newscenter/feed"),
    ("Holtec News",              "https://holtecinternational.com/feed/"),
    ("NANO Nuclear IR",          "https://ir.nanonuclearenergy.com/rss/news-releases.xml"),
    ("Helion Energy",            "https://www.helionenergy.com/feed/"),
    ("TerraPower News",          "https://www.terrapower.com/news/feed/"),
    ("Kairos Power",             "https://kairospower.com/news/feed/"),
    ("Oklo IR",                  "https://ir.oklo.com/news-releases/rss"),
    ("X-energy News",            "https://x-energy.com/news/feed/"),
    ("Commonwealth Fusion",      "https://cfs.energy/news/feed/"),
    ("GE Vernova Newsroom",      "https://www.gevernova.com/news/press-releases/rss"),
    ("Westinghouse Newsroom",    "https://www.westinghousenuclear.com/about/news/rss"),
    ("NuScale IR",               "https://ir.nuscalepower.com/news-releases/rss"),
    ("TVA Newsroom",             "https://www.tva.com/rss/news"),
    ("Duke Energy News",         "https://news.duke-energy.com/rss/all.rss"),
    ("Dominion Energy News",     "https://news.dominionenergy.com/press-releases/rss"),
    ("Constellation IR",         "https://ir.constellationenergy.com/news-releases/rss"),
    ("Southern Company News",    "https://www.southerncompany.com/news/rss"),
    ("Google Blog",              "https://blog.google/rss/"),
    ("Microsoft On the Issues",  "https://blogs.microsoft.com/on-the-issues/feed/"),
    ("Meta Newsroom",            "https://about.fb.com/rss/"),
    ("Amazon About",             "https://www.aboutamazon.com/news/rss"),
    ("Brookfield IR",            "https://bam.brookfield.com/news-releases/rss"),
]
UA = "Mozilla/5.0 (compatible; NuclearDealBot/3.0)"

print(f"Testing {len(FEEDS)} feeds...\n")
for name, url in FEEDS:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
        parsed = feedparser.parse(r.content)
        parsed_direct = feedparser.parse(url)
        n_req = len(parsed.entries)
        n_direct = len(parsed_direct.entries)
        icon = "OK" if n_req > 0 else ("FP" if n_direct > 0 else "FAIL")
        ct = r.headers.get("Content-Type", "")[:40]
        print(f"  [{icon:4s}] {name:30s} HTTP {r.status_code} | req={n_req} fpd={n_direct} | {ct}")
    except Exception as e:
        print(f"  [ERR ] {name:30s} {type(e).__name__}: {str(e)[:60]}")
    time.sleep(0.3)
