from cantarella.core.proxy import get_random_proxy, get_proxy_dict
import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as c_requests
BASE_URL = "https://aniwatchtv.to"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

def search_anime(query, source="aniwatch"):
    if source == "animetsu":
        from cantarella.scraper.animetsu import AnimetsuScraper
        return AnimetsuScraper().search_anime(query)

    # ── Multi-source engine (hianime / allanime / gogo / animepahe / remote) ──
    try:
        from anime_sources import get_provider, search_provider, SOURCE_CYCLE
        if source in ("hianime", "allanime", "gogo", "animepahe", "consumet", "aniwatchapi"):
            return search_provider(source, query)
    except Exception as engine_error:
        print(f"Multi-source search error: {engine_error}")

    search_url = f"{BASE_URL}/search?keyword={query.replace(' ', '+')}"
    try:
        session = c_requests.Session()
        proxy_dict = get_proxy_dict(get_random_proxy())
        if proxy_dict:
            session.proxies.update(proxy_dict)
        resp = session.get(search_url, headers=HEADERS, impersonate="chrome", timeout=15)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []

        # cantarella search results are usually in .film_list-wrap .flw-item
        for item in soup.find_all('div', class_='flw-item'):
            film = item.find('div', class_='film-name')
            title_elem = film.find('a') if film else None
            if not title_elem:
                continue

            title = title_elem.get('title') or title_elem.text.strip()
            href = title_elem.get('href')

            # extract anime_id
            # href format: /watch/anime-name-id
            # or just /anime-name-id
            anime_id = href.split('/')[-1].split('?')[0]

            # Get release year / type if available
            type_elem = item.find('div', class_='fdi-item')
            anime_type = type_elem.text.strip() if type_elem else "Unknown"

            results.append({
                'title': title,
                'id': anime_id,
                'type': anime_type,
                'url': f"{BASE_URL}{href}" if href.startswith('/') else f"{BASE_URL}/{href}"
            })

            # Limit to top 10 results to avoid huge keyboards
            if len(results) >= 10:
                break

        return results
    except Exception as e:
        print(f"Search error: {e}")
        return []

if __name__ == '__main__':
    print(search_anime('naruto'))


_SEARCH_POOL = None  # shared, never joined — slow sources can't stall answers


_RESULT_CACHE = {}         # (query, source) -> (ts, results, winner_key)
_RESULT_CACHE_TTL = 90.0


def search_anime_multi(query, source="animetsu", max_sources=5,
                       head_start=4.0, deadline=12.0):
    """Memoized wrapper: identical searches within 90s answer instantly."""
    import time as _t
    key = (str(query).casefold().strip(), source)
    hit = _RESULT_CACHE.get(key)
    if hit and _t.time() - hit[0] < _RESULT_CACHE_TTL:
        return list(hit[1]), [(hit[2], f"{len(hit[1])} found (cached)")]
    results, tried = _search_anime_multi_impl(query, source, max_sources,
                                              head_start, deadline)
    if results:
        if len(_RESULT_CACHE) > 128:
            _RESULT_CACHE.pop(min(_RESULT_CACHE, key=lambda k: _RESULT_CACHE[k][0]), None)
        _RESULT_CACHE[key] = (_t.time(), results, tried[-1][0] if tried else source)
    return results, tried


def _search_anime_multi_impl(query, source="animetsu", max_sources=5,
                             head_start=4.0, deadline=12.0):
    """Search the active source first, then fall back through the engine —
    but RACE the sources in parallel instead of walking them one by one.

    Every source is queried concurrently; the active source gets a short
    head start (default 4s) to protect result priority, after which the
    first non-empty answer wins. Worst case with a dead primary drops from
    timeout x N to roughly one head-start window.

    Returns (results, tried):
      results — first non-empty result list found ([] if every source failed)
      tried   — [(source_key, outcome)] in priority order, WINNER LAST
                (the UI reads tried[-1] as "served by")
    """
    import concurrent.futures as _cf
    import time as _t

    from anime_sources.base import SOURCE_CYCLE

    order = [source] + [s for s in SOURCE_CYCLE if s != source] + ["aniwatch"]
    seen = set()
    order = [s for s in order if not (s in seen or seen.add(s))]
    order = order[:max(1, max_sources)]

    def _attempt(key):
        return search_anime(query, key) or []

    if len(order) == 1:
        try:
            results = _attempt(order[0])
            outcome = f"{len(results)} found" if results else "no results"
        except Exception as e:
            results, outcome = [], f"error: {type(e).__name__}"
        return results, [(order[0], outcome)]

    tried_by_key = {}
    got = {}
    # Module-level pool: executor threads are reused and never joined, so a
    # slow source can never stall the search that already got its answer.
    global _SEARCH_POOL
    if _SEARCH_POOL is None:
        _SEARCH_POOL = _cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="anisearch")
    pool = _SEARCH_POOL
    futs = {pool.submit(_attempt, k): k for k in order}
    pending = set(futs)
    end = _t.time() + deadline
    grace = _t.time() + head_start  # before this, only the primary may win

    try:
        while pending and _t.time() < end:
            done_now, pending = _cf.wait(pending, timeout=min(0.5, max(0.0, end - _t.time())))
            for fut in done_now:
                key = futs[fut]
                try:
                    r = fut.result()
                    outcome = f"{len(r)} found" if r else "no results"
                except Exception as e:
                    r, outcome = [], f"error: {type(e).__name__}"
                tried_by_key[key] = outcome
                got[key] = r

            # primary answered inside its grace window -> immediate win
            if got.get(source):
                return _ordered(got, tried_by_key, order, source, got[source])
            # grace expired -> first buffered non-empty answer in priority order
            if _t.time() >= grace:
                for k in order:
                    if got.get(k):
                        return _ordered(got, tried_by_key, order, source, got[k])

        for fut in pending:  # global deadline hit
            tried_by_key[futs[fut]] = "timeout"
    finally:
        for fut in pending:
            fut.cancel()

    # nobody won live — best buffered non-empty in priority order
    results = next((got[k] for k in order if got.get(k)), [])
    return _ordered(got, tried_by_key, order, source, results)


def _ordered(got, tried_by_key, order, source, results):
    """Assemble `tried` in priority order with the winning source last."""
    tried = [(k, tried_by_key[k]) for k in order if k in tried_by_key and k != source]
    if source in tried_by_key:
        tried.insert(0, (source, tried_by_key[source]))
    winner_key = source if got.get(source) else next(
        (k for k in order if got.get(k)), None)
    if winner_key is not None:
        tried = [kv for kv in tried if kv[0] != winner_key]
        tried.append((winner_key, tried_by_key.get(winner_key, f"{len(results)} found")))
    return results, tried
