from pyrogram.enums import ParseMode
from cantarella.core.proxy import get_random_proxy, get_proxy_dict
import asyncio
import os
import time
from bs4 import BeautifulSoup
from curl_cffi import requests as c_requests
import json
import re
from pyrogram import Client
from cantarella.telegram.download import _handle_download
from cantarella.scraper.cantarellatv import cantarellatvDownloader
from cantarella.core.database import db
from cantarella.telegram.pages import post_to_main_channel
from cantarella.core.anilist import TextEditor
from config import SET_INTERVAL, TARGET_CHAT_ID, MAIN_CHANNEL, LOG_CHANNEL

BASE_URL = "https://aniwatchtv.to"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

from datetime import datetime

def fetch_schedule_list(source="aniwatch"):
    """Fetch daily schedule."""
    if source == "animetsu":
        from cantarella.scraper.animetsu import AnimetsuScraper
        return AnimetsuScraper().get_schedule()

    try:
        session = c_requests.Session()
        proxy_dict = get_proxy_dict(get_random_proxy())
        if proxy_dict:
            session.proxies.update(proxy_dict)

        # Current date in YYYY-MM-DD format
        date_str = datetime.now().strftime("%Y-%m-%d")

        # AJAX for schedule list, tzOffset = -330 for IST (Indian Standard Time)
        url = f"{BASE_URL}/ajax/schedule/list?date={date_str}&tzOffset=-330"
        resp = session.get(url, headers=HEADERS, impersonate="chrome")
        if resp.status_code == 200:
            html = resp.json().get('html', '')
            if not html.strip() or "No data to display" in html:
                return []

            soup = BeautifulSoup(html, 'html.parser')

            results = []
            # Updated selector for the provided HTML structure
            for item in soup.select('li'):
                time_elem = item.select_one('.time')
                title_elem = item.select_one('.film-name')
                link_elem = item.select_one('a.tsl-link')

                if title_elem and link_elem:
                    href = link_elem.get('href')
                    anime_id = href.split('/')[-1].split('?')[0]
                    results.append({
                        'id': anime_id,
                        'title': title_elem.text.strip(),
                        'time': time_elem.text.strip() if time_elem else "Unknown"
                    })
            return results
    except Exception as e:
        print(f"Error fetching schedule: {e}")
    return []

def fetch_recently_updated():
    try:
        session = c_requests.Session()
        proxy_dict = get_proxy_dict(get_random_proxy())
        if proxy_dict:
            session.proxies.update(proxy_dict)
        results = []

        # Try fetching from home page first
        home_url = f"{BASE_URL}/home"
        resp = session.get(home_url, headers=HEADERS, impersonate="chrome")
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            latest_ep_heading = soup.find('h2', string='Latest Episode')
            if latest_ep_heading:
                section = latest_ep_heading.find_parent('section')
                if section:
                    for item in section.select('.flw-item'):
                        title_elem = item.select_one('.film-name a')
                        if not title_elem:
                            continue
                        title = title_elem.get('title') or title_elem.text.strip()
                        href = title_elem.get('href')
                        anime_id = href.split('/')[-1].split('?')[0]
                        full_url = f"{BASE_URL}{href}" if href.startswith('/') else f"{BASE_URL}/{href}"
                        results.append({
                            'title': title,
                            'id': anime_id,
                            'url': full_url
                        })

        # Fallback to recently-updated if home page parsing failed or returned empty
        if not results:
            print("Could not find Latest Episodes on home page, falling back to /recently-updated")
            fallback_url = f"{BASE_URL}/recently-updated"
            resp = session.get(fallback_url, headers=HEADERS, impersonate="chrome")
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for item in soup.select('.film_list-wrap .flw-item'):
                    title_elem = item.select_one('.film-name a')
                    if not title_elem:
                        continue
                    title = title_elem.get('title') or title_elem.text.strip()
                    href = title_elem.get('href')
                    anime_id = href.split('/')[-1].split('?')[0]
                    full_url = f"{BASE_URL}{href}" if href.startswith('/') else f"{BASE_URL}/{href}"
                    results.append({
                        'title': title,
                        'id': anime_id,
                        'url': full_url
                    })

        return results
    except Exception as e:
        print(f"Error fetching recently updated: {e}")
        return []

def fetch_animetsu_recently_updated():
    from cantarella.scraper.animetsu import AnimetsuScraper
    scraper = AnimetsuScraper()

    # Get Recently Updated Anime (Latest Release section)
    recent_list = scraper.fetch_recently_updated(per_page=20)

    # Filter by freshness (Only releases in last 2 hours)
    now_ms = time.time() * 1000
    two_hours_ms = 2 * 60 * 60 * 1000

    filtered_results = []
    for anime in recent_list:
        aired_at = anime.get('aired_at')
        # If aired_at exists, we use it for strict 2-hour window
        if aired_at:
            if (now_ms - aired_at) <= two_hours_ms:
                filtered_results.append(anime)
        # Fallback for the very first few items if timestamp is missing
        elif anime['id'] in {x['id'] for x in recent_list[:3]}:
            filtered_results.append(anime)

    return filtered_results

async def check_and_download_ongoing(client: Client, chat_id: int):
    active_source = await db.get_user_setting(0, "active_source", "animetsu")
    print(f"Checking for recently updated anime (Source: {active_source})...")

    # -- Cross-source fallback: these upstream sites rot / block IPs often,
    #    so if the active source returns nothing we try the other one before
    #    giving up (a silent empty cycle used to disable auto-uploads).
    sources_to_try = [active_source]
    other = "aniwatch" if active_source == "animetsu" else "animetsu"
    if other not in sources_to_try:
        sources_to_try.append(other)

    recent_animes, used_source = [], active_source
    scheduled_ids = set()
    animetsu_scraper = None
    downloader = cantarellatvDownloader()

    for src in sources_to_try:
        try:
            if src == "animetsu":
                from cantarella.scraper.animetsu import AnimetsuScraper
                animetsu_scraper = AnimetsuScraper()
                batch = await asyncio.to_thread(fetch_animetsu_recently_updated)
                sched = await asyncio.to_thread(fetch_schedule_list, source="animetsu")
            else:
                animetsu_scraper = None
                batch = await asyncio.to_thread(fetch_recently_updated)
                sched = await asyncio.to_thread(fetch_schedule_list, source="aniwatch")
            if batch:
                recent_animes, used_source = batch, src
                scheduled_ids = {item['id'] for item in sched}
                break
            print(f"Ongoing source {src}: no recently-updated data")
        except Exception as e:
            print(f"Ongoing source {src} failed: {e}")

    if not recent_animes:
        print(
            "⚠️ All ongoing sources failed or returned nothing — "
            "auto-download skipped this cycle (sites may be blocking this server)"
        )
        return

    if used_source != active_source:
        print(f"↪️ Active source {active_source} unavailable — fell back to {used_source}")

    for idx, anime in enumerate(recent_animes):
        try:
            if used_source == "animetsu":
                entries = await asyncio.to_thread(animetsu_scraper.list_episodes, anime['id'])
            else:
                entries = await asyncio.to_thread(downloader.list_episodes, anime['url'])

            if not entries:
                print(f"Waiting for episode: {anime['title']} (Anime page exists, but no episodes listed yet)")
                continue

            # Usually the latest episode is the last one in the list
            latest_ep = entries[-1]
            ep_url = latest_ep['url']

            # Use episode number for identifier to prevent re-downloads when title or internal ep_id changes
            ep_num = latest_ep.get('ep_number')
            ep_id = latest_ep.get('ep_id')

            # Fast early exit check to avoid spamming the AniList API
            if ep_num:
                ep_identifier = f"{anime['id']}_ep_{ep_num}"
            else:
                ep_identifier = f"{anime['id']}_{latest_ep.get('title', 'Unknown')}"

            old_ep_identifier = f"{anime['id']}_{latest_ep.get('title', 'Unknown')}"
            legacy_ep_identifier = None
            if ep_num and ep_id:
                legacy_ep_identifier = f"{anime['id']}_{ep_num}_{ep_id}"

            is_new_processed = await db.is_processed(ep_identifier)
            is_old_processed = await db.is_processed(old_ep_identifier)
            is_legacy_processed = legacy_ep_identifier and await db.is_processed(legacy_ep_identifier)

            if is_new_processed or is_old_processed or is_legacy_processed:
                # Ensure the new stable identifier is marked as processed if an old format was found
                if not is_new_processed:
                    await db.mark_processed(ep_identifier)
                continue

            # Clean title for better AniList searching (remove extra spaces)
            clean_search_title = re.sub(r'\s+', ' ', anime['title']).strip()

            # Metadata Correction using AniList
            te = TextEditor(clean_search_title)
            await te.load_anilist()
            data = te.adata

            # User requested ONLY English name for filenames and search to avoid errors
            romaji_title = data.get('title', {}).get('romaji')
            english_title = data.get('title', {}).get('english')

            # Prioritize English title as requested
            anime_name = english_title or romaji_title or anime['title']

            # Robustness check: if AniList title is completely different from site title,
            # fallback to site title to avoid wrong identification (e.g. Beyblade X -> Blood Blockade)
            from difflib import SequenceMatcher
            similarity = SequenceMatcher(None, anime['title'].lower(), anime_name.lower()).ratio()
            # Threshold increased to 0.5 for stricter matching
            if similarity < 0.5:
                print(f"⚠️ Low similarity ({similarity:.2f}) between site title '{anime['title']}' and AniList match '{anime_name}'. Falling back to site title.")
                anime_name = anime['title']

            if not (romaji_title or english_title):
                    # Clean up trailing number from fallback name if it was likely a season
                    anime_name = re.sub(r'\s+\d+$', '', anime_name).strip()

            ani_season = "1"
            ani_ep_num = "0"

            # 1. Try extracting numeric season from HiAnime title first (most reliable for "Season X" or trailing numbers)
            # Catch "Season 5" or "Anime 5" (common for Chinese/Donghua on HiAnime)
            match_s = re.search(r'Season (\d+)', anime['title'], re.I)
            if not match_s:
                 # Check for trailing number in the title (e.g. "Yong Sheng 5")
                 match_s = re.search(r'\s+(\d+)$', anime['title'])

            if match_s:
                ani_season = match_s.group(1)
            else:
                # 2. Try guessit from TextEditor (pdata)
                te_season = te.pdata.get('anime_season')
                if te_season:
                    ani_season = str(te_season)
                else:
                    # 3. Fallback to AniList data
                    match_s2 = re.search(r'Season (\d+)', anime_name, re.I)
                    if match_s2:
                        ani_season = match_s2.group(1)

            # 4. Extract Episode number
            # For Animetsu, we prioritize the episode number from the full list
            if used_source == "animetsu":
                # Get ep_num from the last entry in the full episode list
                if entries and entries[-1].get('ep_number'):
                    ani_ep_num = str(entries[-1]['ep_number'])
                # Fallback to the one from the recently updated list if list was empty
                elif anime.get('ep_num') is not None:
                    ani_ep_num = str(anime['ep_num'])
            elif data.get('nextAiringEpisode'):
                # This works if the episode just aired and is the next expected one
                ani_ep_num = str(data['nextAiringEpisode']['episode'] - 1)
            else:
                # Fallback to parsing the episode list entry title
                match_ep = re.search(r'Episode (\d+)', latest_ep.get('title', ''))
                if match_ep:
                    ani_ep_num = match_ep.group(1)
                else:
                    # Try guessit on the entry title
                    from guessit import guessit
                    g = guessit(latest_ep.get('title', ''))
                    if g.get('episode'):
                        ani_ep_num = str(g['episode'])

            # Manual Fixes for specific anime if needed (e.g. Dr. Stone)
            if "Dr. Stone" in anime_name:
                if "New World" in anime['title']:
                    ani_season = "3"
                if "Science Future" in anime['title'] or "Season 4" in anime['title']:
                    ani_season = "4"

            # Compute the ultimate universal identifier to avoid duplicate downloads
            # even if the site lists it twice (e.g., dub added later)
            universal_ep_identifier = f"{anime_name}_S{ani_season}_E{ani_ep_num}"

            # Second layer check: if this universal episode was downloaded through another ID, skip.
            is_universal_processed = await db.is_processed(universal_ep_identifier)

            if is_universal_processed:
                # Mark this site-specific ID as processed too, so we don't query AniList for it again
                await db.mark_processed(ep_identifier)
                continue

            print(f"New episode found: {anime['title']} - {latest_ep.get('title', 'Unknown')} (Universal ID: {universal_ep_identifier})")

            # 1. Strict Schedule check as requested
            is_scheduled = scheduled_ids is None or anime['id'] in scheduled_ids

            country_of_origin = data.get("countryOfOrigin", "")
            is_chinese = country_of_origin == "CN"

            if is_chinese and not is_scheduled:
                print(f"⏭️ Skipping unscheduled Chinese anime (Donghua): {anime['title']}")
                await db.mark_processed(ep_identifier)
                await db.mark_processed(universal_ep_identifier)
                continue

            # Send a starting message to edit (in LOG_CHANNEL if set)

            log_id = int(LOG_CHANNEL) if LOG_CHANNEL else chat_id
            anime_name_sc = anime_name
            status_msg = await client.send_message(log_id, f"<blockquote>🔄 ᴀᴜᴛᴏ-ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ɴᴇᴡ ᴇᴘɪꜱᴏᴅᴇ: {anime_name_sc} - ꜱ{ani_season}ᴇ{ani_ep_num}...</blockquote>", parse_mode=ParseMode.HTML)

            # Use the existing download logic (downloading to TARGET_CHAT_ID)
            # quality="all" will download 360p, 720p, 1080p sequentially
            # Pass message=None so _handle_download doesn't try to send user-side progress
            uploaded_msgs, _ = await _handle_download(
                client, None, ep_url, status_msg,
                is_playlist=False, quality="all", chat_id=chat_id,
                name_override=anime_name,
                season_override=str(ani_season),
                ep_num_override=str(ani_ep_num) if ani_ep_num else None
            )

            if uploaded_msgs:
                # Create a quality map for the main channel
                quality_map = {}
                for msg in uploaded_msgs:
                    match = re.search(r'\[(\d+p)\]', msg.caption or "")
                    if match:
                        quality_map[match.group(1)] = msg.id

                await post_to_main_channel(client, ep_url, uploaded_msgs, quality_map, None, str(ani_season), str(ani_ep_num) if ani_ep_num else "1")

                # Mark as processed ONLY if something was uploaded
                # This ensures we retry if sources weren't ready yet
                await db.mark_processed(ep_identifier)
                await db.mark_processed(universal_ep_identifier)
            else:
                print(f"⏭️ No episodes uploaded for {anime['title']} (sources might not be ready), will retry in next cycle.")

        except Exception as e:
            print(f"Error processing {anime['title']}: {e}")


_SRC_BENCH = {}  # src -> bench-until-ts (persistent across watcher runs)

async def check_mapped_anime(client: Client, chat_id: int):
    """Watch every /setmap'd anime across the healthy multi-source providers.

    The site-based 'recently updated' feeds die whenever animetsu/aniwatchtv
    rot or block the server. This watcher instead searches the mapped anime
    names on the API providers (hianime/allanime/gogo/...) every cycle and
    downloads episodes that were never processed — fully independent of the
    legacy sites. Backlog guard: at most the 3 newest episodes run per cycle;
    a huge backlog (>10) is marked processed so history doesn't queue-dump
    (use the batch 'Download All' flow for old episodes).
    """
    try:
        mappings = await db.get_all_mappings()
    except Exception as e:
        print(f"Mapped watcher: cannot load mappings: {e}")
        return
    if not mappings:
        return

    from anime_sources import search_provider, get_provider
    from anime_sources.base import SOURCE_CYCLE

    try:
        active_source = await db.get_user_setting(0, "active_source", "hianime")
    except Exception:
        active_source = "hianime"   # DB blip → sane default, cycle continues
    order = [s for s in ([active_source] + SOURCE_CYCLE)
             if s not in ("animetsu", "aniwatch")]  # legacy sites: DNS-dead
    seen = set()
    order = [s for s in order if not (s in seen or seen.add(s))]
    dead_sources = set()  # circuit breaker: connection-dead for one mapping = skip for the cycle
    now = time.time()
    # TLS-fingerprint blocks (animepahe behind DDoS-Guard etc.) do not clear
    # in 90s — bench those sources for 30 min so logs stay readable and we
    # stop burning a request on a blocked host every cycle.
    long_bench = {s: ts for s, ts in _SRC_BENCH.items() if ts > now}
    for s in long_bench:
        dead_sources.add(s)

    for doc in mappings:
        channel_id = doc.get("_id")
        for name in doc.get("anime_names", []) or []:
            found = None
            suspects = []  # returned nothing; may be dead — verdict when a later source hits
            for src in order:
                if src in dead_sources:
                    continue
                try:
                    res = await asyncio.to_thread(search_provider, src, name)
                except Exception as e:
                    res = []
                    _msg = str(e)
                    if any(sig in _msg for sig in (
                            "TLS", "SSL", "curl: (35)", "curl: (7)",
                            "Name or service not known", "Connection refused",
                            "connection reset", "UNREACHABLE")):
                        _SRC_BENCH[src] = time.time() + 1800  # 30 min
                        print(f"Mapped watcher: {src} unreachable "
                              f"({_msg[:60]}…) — benching for 30 min")
                if res:
                    found = res[0]
                    if suspects:
                        dead_sources.update(suspects)
                        print(
                            f"Mapped watcher: {', '.join(suspects)} returned nothing while "
                            f"{src} served '{name}' — benching them for this cycle"
                        )
                    break
                suspects.append(src)
            if not found:
                print(f"Mapped watcher: no healthy source answered for '{name}'")
                continue

            provider_id, _, provider_anime_id = found["id"].partition(":")
            try:
                provider = get_provider(provider_id)
                eps = await asyncio.to_thread(provider.episodes, provider_anime_id)
            except Exception as e:
                print(f"Mapped watcher: episode list failed for '{name}' ({provider_id}): {e}")
                continue

            try:
                eps.sort(key=lambda e: float(str(e.number)), reverse=True)
            except (ValueError, TypeError):
                pass

            pending = []
            db_ok = True
            for ep in eps:
                ep_id = f"{found['id']}::{ep.number}"
                try:
                    done = bool(await db.is_processed(ep_id))
                except Exception as e:
                    # A DB hiccup must never look like "unprocessed" —
                    # that would re-download everything. Skip the cycle.
                    print(f"Mapped watcher: is_processed unavailable for '{name}' — skipping this cycle ({e})")
                    db_ok = False
                    break
                if not done:
                    pending.append((ep, ep_id))

            if not db_ok or not pending:
                continue

            # Backlog guard: a fresh mapping of a 1000-ep show must not
            # queue-dump the instance. Keep the 3 newest, retire the rest.
            if len(pending) > 10:
                for _, retire_id in pending[3:]:
                    try:
                        await db.mark_processed(retire_id)
                    except Exception:
                        pass
                print(
                    f"Mapped watcher: '{name}' has {len(pending)} unprocessed episodes — "
                    f"history retired, downloading the 3 newest only "
                    f"(use batch 'Download All' for old episodes)"
                )
                pending = pending[:3]

            for ep, ep_id in pending:
                print(f"Mapped watcher: new episode {ep.number} of {name} ({provider_id})")
                log_id = int(LOG_CHANNEL) if LOG_CHANNEL else chat_id
                try:
                    status_msg = await client.send_message(
                        log_id,
                        f"<blockquote>🔄 ᴀᴜᴛᴏ-ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ (ᴡᴀᴛᴄʜᴇᴅ): {name} — EP {ep.number}…</blockquote>",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    status_msg = None
                try:
                    uploaded_msgs, quality_map = await _handle_download(
                        client, None, ep.url,
                        status_msg,
                        is_playlist=False, quality="auto", chat_id=chat_id,
                        name_override=name,
                        season_override="1",
                        ep_num_override=str(ep.number),
                    )
                    if uploaded_msgs:
                        await post_to_main_channel(
                            client, ep.url, uploaded_msgs, quality_map,
                            None, "1", str(ep.number),
                        )
                    await db.mark_processed(ep_id)
                except Exception as e:
                    print(f"Mapped watcher: download failed for {name} EP {ep.number}: {e}")


async def ongoing_task(client: Client):
    if not TARGET_CHAT_ID:
        print("WARNING: TARGET_CHAT_ID is not set in environment or config.py. Ongoing auto-downloads are disabled.")
        return

    try:
        target_chat_id = int(TARGET_CHAT_ID)
    except ValueError:
        print("WARNING: TARGET_CHAT_ID must be a valid integer chat ID. Ongoing auto-downloads are disabled.")
        return

    print(f"Starting ongoing checker. Interval: {SET_INTERVAL}s, Target Chat: {target_chat_id}")

    while True:
        ongoing_enabled = await db.get_user_setting(0, "ongoing_enabled", False)
        if ongoing_enabled:
            # The legacy 'recently updated' site feeds only exist for the
            # two site scrapers. With a provider source active they would
            # just hammer dead/TLS-blocked domains every cycle — skip them
            # and let the mapped-anime watcher do the work.
            try:
                src = await db.get_user_setting(0, "active_source", "animetsu")
            except Exception:
                src = "animetsu"
            if src in ("animetsu", "aniwatch"):
                try:
                    await check_and_download_ongoing(client, target_chat_id)
                except Exception as e:
                    print(f"Error in ongoing task loop: {e}")
            # Provider-based watcher — keeps working even when both
            # legacy site feeds are down (dead DNS / TLS blocks).
            try:
                await check_mapped_anime(client, target_chat_id)
            except Exception as e:
                print(f"Error in mapped-anime watcher: {e}")
        else:
            pass  # Paused via /settings, loop stays alive

        await asyncio.sleep(SET_INTERVAL)
