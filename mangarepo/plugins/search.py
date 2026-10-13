# Made by @codexnano from scratch.
# If you find any bugs, please let us know in the channel updates.
# You can 'git pull' to stay updated with the latest changes.

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup as KM, InlineKeyboardButton as KB, InputMediaPhoto
import asyncio
import time
from mangarepo.services.mgr import mgr
from mangarepo.services.util import clean_title
from mangarepo.database.db import db
from mangarepo.config import Config
import logging
log = logging.getLogger(__name__)
_search_states_raw = {}
_SEARCH_STATE_TTL = 1800
_SEARCH_STATE_MAX_SIZE = 1000
class SearchStateWrapper:
    def __init__(self, data_dict, ttl=_SEARCH_STATE_TTL, max_size=_SEARCH_STATE_MAX_SIZE):
        self._data = data_dict
        self._ttl = ttl
        self._max_size = max_size
        self._last_cleanup = 0
        self._cleanup_interval = 60
    def _cleanup(self):
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        expired = [k for k, v in self._data.items()
                   if isinstance(v, dict) and now - v.get('_ts', 0) > self._ttl]
        for k in expired:
            del self._data[k]
        if len(self._data) > self._max_size:
            sorted_items = sorted(
                self._data.items(),
                key=lambda x: x[1].get('_ts', 0) if isinstance(x[1], dict) else 0
            )
            to_remove = len(self._data) - self._max_size
            for key, _ in sorted_items[:to_remove]:
                del self._data[key]
            log.info(f"[SEARCH] Cleaned {to_remove} old entries, now {len(self._data)}")
    def get(self, key, default=None):
        self._cleanup()
        entry = self._data.get(key)
        if entry is None:
            return default
        return entry
    def __getitem__(self, key):
        self._cleanup()
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]
    def __setitem__(self, key, value):
        if isinstance(value, dict):
            value['_ts'] = time.time()
        self._data[key] = value
    def __contains__(self, key):
        return key in self._data
    def pop(self, key, *args):
        return self._data.pop(key, *args)
    def update(self, key, updates):
        if key in self._data:
            self._data[key].update(updates)
            self._data[key]['_ts'] = time.time()
    def __len__(self):
        return len(self._data)
search_states = SearchStateWrapper(_search_states_raw)
SEARCH_B = "https://files.catbox.moe/vhm5zo.jpg"
async def edit_msg(msg, text, reply_markup=None):
    m = msg.message if hasattr(msg, 'message') else msg
    try:
        if m.photo or m.caption:
            await m.edit_caption(text, reply_markup=reply_markup)
        else:
            await m.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        log.warning(f"Edit failed: {e}")
        try: await m.reply(text, reply_markup=reply_markup)
        except: pass
from mangarepo.plugins.fsub import force_sub
@Client.on_message(filters.command("search"))
@force_sub
async def search(c, m):
    q = " ".join(m.command[1:])
    if not q: return await m.reply("<blockquote>⚠ Usage: <code>/search manga name</code></blockquote>")
    sid = f"sch_{m.from_user.id}"
    await db.set_cache(sid, {'q': q})
    msg = await c.send_photo(m.chat.id, SEARCH_B, caption="<blockquote>⋯ Loading sources...</blockquote>")
    await show_sources(msg, sid, page=0)
async def show_sources(msg, sid, page=0):
    sources = sorted(list(mgr.srcs.keys()))
    files_per_page = 12
    total = len(sources)
    start = page * files_per_page
    end = start + files_per_page
    current_srcs = sources[start:end]
    btns = []
    if page == 0:
        btns.append([KB("[SEARCH] All Sources", f"ms_start_{sid}")])
    row = []
    for src in current_srcs:
        dname = src.replace('Webs', '')
        row.append(KB(f"{dname}", f"src_{sid}_{src}"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row: btns.append(row)
    nav = []
    if page > 0: nav.append(KB("◂◂ Prev", f"pg_{sid}_{page-1}"))
    if end < total: nav.append(KB("Next ▸▸", f"pg_{sid}_{page+1}"))
    if nav: btns.append(nav)
    if not btns: btns.append([KB("✕ Close", "close")])
    data = await db.get_cache(sid)
    q_txt = data['q'] if data else "?"
    await edit_msg(msg, f"<b>▸ Search:</b> <code>{q_txt}</code>\n\n<blockquote>Select a source below</blockquote>", reply_markup=KM(btns))
@Client.on_callback_query(filters.regex(r"^pg_"))
async def pg(c, q):
    parts = q.data.split("_")
    page = int(parts[-1])
    sid = "_".join(parts[1:-1])
    await show_sources(q.message, sid, page)
@Client.on_callback_query(filters.regex(r"^src_"))
async def select_source(c, q):
    parts = q.data.split("_")
    if len(parts) < 4: return await q.answer("Invalid Data")
    sid = f"{parts[1]}_{parts[2]}"
    src = "_".join(parts[3:])
    data = await db.get_cache(sid)
    if not data: return await q.answer("Exp")
    query = data['q']
    await edit_msg(q.message, f"<blockquote>⋯ Searching {src.replace('Webs','')}...</blockquote>")
    try:
        s = mgr.get(src)
        if not s: return await edit_msg(q.message, "Source not found.")
        try:
            res = await asyncio.wait_for(s.search(query), timeout=45)
        except asyncio.TimeoutError:
            return await edit_msg(q.message, f"<blockquote>⚠ {src} timed out. Try again.</blockquote>", reply_markup=KM([[KB("◂ Back", f"pg_{sid}_0"), KB("↻ Retry", f"src_{sid}_{src}")]]))
        if not res:
            return await edit_msg(
                q.message,
                f"<blockquote>⚠ No results on {src}</blockquote>",
                reply_markup=KM([[KB("◂ Back to Sources", f"pg_{sid}_0")]])
            )
        btns = []
        for i, r in enumerate(res):
            r['src'] = src
            r['sid'] = sid
            r['_cached_at'] = __import__('time').time()
            k = f"m_{sid}_{src}_{i}"
            await db.set_cache(k, r)
            btns.append([KB(clean_title(r['title'], 30), f"sel_{k}")])
        btns.append([KB("◂ Back to Sources", f"pg_{sid}_0")])
        await edit_msg(q.message, f"<b>▸ {src.replace('Webs','')}</b>\n\n<blockquote>Select manga</blockquote>", reply_markup=KM(btns))
    except Exception as e:
        await edit_msg(q.message, f"<blockquote>⚠ {e}</blockquote>", reply_markup=KM([[KB("◂ Back", f"pg_{sid}_0")]]))
@Client.on_callback_query(filters.regex(r"^sel_"))
async def sel(c, q):
    k = q.data.replace("sel_", "")
    d = await db.get_cache(k)
    if not d: return await q.answer("Session Expired", show_alert=True)
    src_name = d.get('src', 'Unknown')
    sid = d.get('sid')
    if not sid:
        p = k.split("_")
        if len(p) >= 4: sid = f"{p[1]}_{p[2]}"
    if d.get('from_multi'):
        ms_page = d.get('ms_page', 0)
        res_key = f"ms_res_{sid}"
        back_cb = f"msp_{res_key}_{sid}_{ms_page}"
    else:
        back_cb = f"src_{sid}_{src_name}" if sid else "close"
    if 'msg' not in d or 'chapters' not in d:
        await edit_msg(q.message, f"<b>{d['title']}</b>\n<blockquote>⋯ Fetching details from {src_name}...</blockquote>")
        try:
            s = mgr.get(src_name)
            if s:
                orig_data = d.copy()
                try:
                    new_data = await asyncio.wait_for(s.get_chapters(d), timeout=60)
                except asyncio.TimeoutError:
                    return await edit_msg(
                        q.message,
                        f"<b>{d['title']}</b>\n<blockquote>⚠ Details request timed out</blockquote>",
                        reply_markup=KM([[KB("↻ Retry", f"sel_{k}")], [KB("◂ Back", back_cb)]])
                    )
                if new_data:
                    for key in ['src', 'sid', 'from_multi', 'ms_page', '_cached_at']:
                        if key in orig_data:
                            new_data[key] = orig_data[key]
                    d = new_data
                    await db.set_cache(k, d)
        except Exception as e:
            log.error(f"Error fetching info for {d['title']}: {e}")
    txt = d.get('msg')
    if not txt:
        txt = (
            f"<b>▸ {d['title']}</b>\n\n"
            f"<blockquote>"
            f"<b>Source:</b> {src_name}\n"
            f"<b>Chapters:</b> {'Available' if d.get('chapters') else 'Load required'}"
            f"</blockquote>"
        )
    photo = d.get('poster') or SEARCH_B
    try:
        if q.message.photo:
            await q.message.edit_media(media=InputMediaPhoto(photo, caption=txt), reply_markup=KM([
                [KB("▸ Load Chapters" if not d.get('chapters') else "▸ View Chapters", f"ld_{k}")],
                [KB("◂ Back", back_cb)]
            ]))
        else:
            await q.message.reply_photo(photo, caption=txt, reply_markup=KM([
                [KB("▸ Load Chapters" if not d.get('chapters') else "▸ View Chapters", f"ld_{k}")],
                [KB("◂ Back", back_cb)]
            ]))
    except:
        await edit_msg(q.message, txt, reply_markup=KM([
            [KB("▸ Load Chapters" if not d.get('chapters') else "▸ View Chapters", f"ld_{k}")],
            [KB("◂ Back", back_cb)]
        ]))
@Client.on_callback_query(filters.regex(r"^ld_"))
async def load(c, q):
    k = q.data.replace("ld_", "")
    d = await db.get_cache(k)
    if not d: return await q.answer("Session expired", show_alert=True)
    src_name = d.get('src')
    s = mgr.get(src_name)
    if not s: return await q.answer("Source error", show_alert=True)
    if d.get('chapters'):
        try:
            chaps = s.iter_chapters(d, 1)
            if chaps:
                cid = f"chaps_{k}"
                await db.set_cache(cid, {'m': d, 'c': chaps})
                return await show_chapters(q.message, cid, 0)
        except Exception as e:
            log.warning(f"iter_chapters failed, refetching: {e}")
    await edit_msg(q.message, f"<blockquote>⋯ Loading chapters from {src_name}...</blockquote>")
    try:
        try:
            orig_data = d.copy()
            raw = await asyncio.wait_for(s.get_chapters(d), timeout=60)
        except asyncio.TimeoutError:
            return await edit_msg(
                q.message,
                f"<blockquote>⚠ Chapter loading timed out</blockquote>\n\n<i>Try again or choose another source</i>",
                reply_markup=KM([[KB("↻ Retry", f"ld_{k}")], [KB("◂ Back", f"sel_{k}")]])
            )
        if raw:
            for key in ['src', 'sid', 'from_multi', 'ms_page', '_cached_at']:
                if key in orig_data:
                    raw[key] = orig_data[key]
            d = raw
            await db.set_cache(k, d)
        chaps = s.iter_chapters(d, 1)
        if not chaps:
            return await edit_msg(
                q.message,
                "<blockquote>⚠ No chapters found</blockquote>",
                reply_markup=KM([[KB("◂ Back", f"sel_{k}")]])
            )
        cid = f"chaps_{k}"
        await db.set_cache(cid, {'m': d, 'c': chaps})
        await show_chapters(q.message, cid, 0)
    except Exception as e:
        log.error(f"Load chapters error: {e}")
        err_msg = str(e)
        if "Connection" in err_msg or "403" in err_msg:
            err_msg = "Connection failed"
        elif "Timeout" in err_msg:
            err_msg = "Request timed out"
        await edit_msg(
            q.message,
            f"<blockquote>⚠ {err_msg[:80]}</blockquote>",
            reply_markup=KM([
                [KB("↻ Retry", f"ld_{k}")],
                [KB("◂ Back", f"sel_{k}"), KB("✗ Close", "close")]
            ])
        )
async def show_chapters(msg, cid, page):
    data = await db.get_cache(cid)
    if not data: return await edit_msg(msg, "Expired.")
    m_info = data['m']
    chaps = data['c']
    PER_PAGE = 15
    total = len(chaps)
    start = page * PER_PAGE
    end = start + PER_PAGE
    curr = chaps[start:end]
    btns = []
    row = []
    for i, chap in enumerate(curr):
        real_idx = start + i
        t = chap['title'].replace(m_info['title'], '').strip()[:15] or f"Ch {real_idx+1}"
        row.append(KB(t, f"trk_{cid}_{real_idx}"))
        if len(row) == 3:
            btns.append(row)
            row = []
    if row: btns.append(row)
    nav = []
    if page > 0: nav.append(KB("◂◂", f"cp_{cid}_{page-1}"))
    if end < total: nav.append(KB("▸▸", f"cp_{cid}_{page+1}"))
    if nav: btns.append(nav)
    k = cid.replace("chaps_", "")
    btns.append([KB("◂ Back", f"sel_{k}")])
    await edit_msg(
        msg,
        f"<b>▸ {m_info['title']}</b>\n\n"
        f"<blockquote>Select starting chapter ({page+1}/{(total//PER_PAGE)+1})</blockquote>",
        reply_markup=KM(btns)
    )
@Client.on_callback_query(filters.regex(r"^cp_"))
async def chap_page(c, q):
    parts = q.data.split("_")
    page = int(parts[-1])
    cid = "_".join(parts[1:-1])
    await show_chapters(q.message, cid, page)
@Client.on_callback_query(filters.regex(r"^trk_"))
async def track_setup(c, q):
    parts = q.data.split("_")
    idx = int(parts[-1])
    cid = "_".join(parts[1:-1])
    data = await db.get_cache(cid)
    if not data: return await q.answer("Exp")
    chaps = data['c']
    if idx >= len(chaps): return await q.answer("Err index")
    sel_chap = chaps[idx]
    sel_k = f"sel_final_{q.from_user.id}"
    await db.set_cache(sel_k, {'m': data['m'], 'l': sel_chap})
    uid = q.from_user.id
    if uid in search_states and search_states[uid].get('chat_id'):
        cur = search_states[uid]
        cur['ctx_key'] = sel_k
        await edit_msg(q.message, "<blockquote>Finalizing additional source...</blockquote>")
        return await finalize_sub(q.message, uid, cur, cur.get('banner'), q.message)
    search_states[uid] = {"state": "await_chan", "ctx_key": sel_k}
    await edit_msg(
        q.message,
        f"<b>▸ Start from:</b> {sel_chap['title']}\n\n"
        "<blockquote>Forward a message from target channel or send channel ID</blockquote>\n"
        "<i>Bot must be admin there</i>",
        reply_markup=KM([[KB("✗ Cancel", "cancel_trk")]])
    )
@Client.on_callback_query(filters.regex("^cancel_trk"))
async def cancel_trk(c, q):
    search_states.pop(q.from_user.id, None)
    await q.message.delete()
async def check_search_state(_, __, m):
    return m.from_user and m.from_user.id in search_states
has_search_state = filters.create(check_search_state)
@Client.on_message(filters.private & has_search_state)
@force_sub
async def search_listener(c, m):
    uid = m.from_user.id
    data = search_states.get(uid)
    state = data.get('state', 'await_chan')
    if state == "await_chan":
        chat_id = None
        if m.forward_from_chat:
            chat_id = m.forward_from_chat.id
        elif m.text:
            text = m.text.strip()
            import re
            id_match = re.search(r"(-100\d+|\d+)", text)
            if id_match:
                chat_id = int(id_match.group(1))
            elif text.startswith("@"):
                chat_id = text
            elif "t.me/" in text:
                chat_id = "@" + text.split("/")[-1] if not text.split("/")[-1].isdigit() else int(text.split("/")[-1])
            else:
                chat_id = text
        if not chat_id: return await m.reply("Invalid. Send ID or Forward.")
        msg = await m.reply("Checking...")
        try:
            chat = await c.get_chat(chat_id)
            mem = await chat.get_member("me")
            if not mem.privileges: return await edit_msg(msg, "✗ Not admin.")
            ctx = await db.get_cache(data['ctx_key'])
            if ctx:
                m_info = ctx['m']
                existing = await db.subs.find_one({
                    "uid": uid,
                    "title": m_info['title'],
                    "cid": chat.id
                })
                if existing:
                    data.update({
                        'chat_id': chat.id,
                        'chat_title': chat.title,
                        'sid': existing['sid'],
                        'banner': existing.get('banner')
                    })
                    await edit_msg(msg, f"<b>⚠ Already Tracked</b>\n<blockquote>{m_info['title']} is already in {chat.title}.</blockquote>\nDo you want to add <b>{m_info['src']}</b> as an additional source to this subscription?",
                        reply_markup=KM([
                            [KB("⊕ Add Source", "finalize_extra")],
                            [KB("✕ Cancel", "close")]
                        ])
                    )
                    search_states[uid] = data
                    return
            inv = f"https://t.me/{chat.username}" if chat.username else None
            if not inv:
                try:
                    link = await c.create_chat_invite_link(chat.id)
                    inv = link.invite_link
                except Exception as e:
                    log.warning(f"[INV] Create invite failed: {e}")
                    inv = f"https://t.me/c/{str(chat.id).replace('-100', '')}/1"
            data.update({
                'chat_id': chat.id,
                'inv': inv,
                'state': 'await_banner',
                'chat_title': chat.title
            })
            search_states[uid] = data
            await edit_msg(
                msg,
                f"<b>✓ Channel Linked:</b> {chat.title}\n\n"
                "<blockquote>Set a <b>Banner Image</b> for update notifications.</blockquote>\n"
                "<i>Choose an option below:</i>",
                reply_markup=KM([
                    [KB("[AUTO] Fetch from Channel", "fetch_banner")],
                    [KB("[MANUAL] Upload Image", "manual_banner")],
                    [KB("[SKIP] No Banner", "skip_banner")]
                ])
            )
        except Exception as e:
            await edit_msg(msg, f"✗ Chat Error: {e}")
    elif state in ("await_banner", "await_banner_upload"):
        if not m.photo:
            return await m.reply("Please send an image or click Skip.", reply_markup=KM([[KB("[SKIP]", "skip_banner")]]))
        msg = await m.reply("<blockquote>Uploading banner to Catbox...</blockquote>")
        try:
            from services.catbox import Catbox
            import os
            p = await m.download()
            url = await Catbox.upload(p)
            if os.path.exists(p): os.remove(p)
            if not url: return await edit_msg(msg, "✗ Catbox upload failed. Try again or skip.")
            await finalize_sub(m, uid, data, url, msg)
        except Exception as e:
            await edit_msg(msg, f"Err: {e}")
async def finalize_sub(m, uid, data, banner_url, msg_to_edit):
    k = data['ctx_key']
    ctx = await db.get_cache(k)
    if not ctx:
        search_states.pop(uid, None)
        return await edit_msg(msg_to_edit, "Session expired.")
    m_info, l_info = ctx['m'], ctx['l']
    sid = data.get('sid')
    if sid:
        await db.add_source_to_sub(uid, sid, m_info['url'], m_info['src'], l_info['title'], l_info['url'])
    else:
        sub = {
            "mid": m_info['url'], "src": m_info['src'], "title": m_info['title'],
            "cid": data['chat_id'], "last": l_info['title'], "lurl": l_info['url'],
            "inv": data['inv'], "banner": banner_url
        }
        sid = await db.add_sub(uid, sub)
        data['sid'] = sid
        data['banner'] = banner_url
    search_states[uid] = data
    await edit_msg(
        msg_to_edit,
        f"<b>▸ Source Added</b>\n\n"
        f"<blockquote>"
        f"<b>ID:</b> <code>{sid}</code>\n"
        f"<b>Manga:</b> {m_info['title']}\n"
        f"<b>Source:</b> {m_info['src']}\n"
        f"<b>From:</b> {l_info['title']}"
        f"</blockquote>\n\n"
        "<i>Add more sources for faster updates</i>",
        reply_markup=KM([
            [KB("⊕ Add More Sources", f"add_more_{sid}")],
            [KB("✓ Finish", "finish_trk")]
        ])
    )
@Client.on_callback_query(filters.regex("^finalize_extra"))
async def finalize_extra(c, q):
    uid = q.from_user.id
    data = search_states.get(uid)
    if not data: return await q.answer("Exp")
    await finalize_sub(q.message, uid, data, data.get('banner'), q.message)
@Client.on_callback_query(filters.regex(r"^add_more_"))
async def add_more_src(c, q):
    uid = q.from_user.id
    if uid not in search_states:
        return await q.answer("Session expired.", show_alert=True)
    await show_sources(q.message, f"sch_{uid}", page=0)
@Client.on_callback_query(filters.regex("^finish_trk"))
async def finish_trk(c, q):
    uid = q.from_user.id
    data = search_states.pop(uid, None)
    if not data: return await q.message.delete()
    await edit_msg(
        q.message,
        "<b>┌─ SETUP COMPLETE ─┐</b>\n\n"
        f"│ <b>Manga:</b> {data.get('chat_title')}\n"
        f"│ <b>ID:</b> <code>{data.get('sid')}</code>\n"
        f"└───────────────────\n\n"
        "Bot will now monitor all sources for updates."
    )
@Client.on_callback_query(filters.regex("^skip_banner"))
async def skip_banner(c, q):
    uid = q.from_user.id
    data = search_states.get(uid)
    if not data: return await q.answer("Exp")
    await edit_msg(q.message, "<blockquote>Finalizing without banner...</blockquote>")
    await finalize_sub(q.message, uid, data, None, q.message)
@Client.on_callback_query(filters.regex("^fetch_banner"))
async def fetch_banner(c, q):
    uid = q.from_user.id
    data = search_states.get(uid)
    if not data: return await q.answer("Exp")
    cid = data.get('chat_id')
    if not cid: return await q.answer("No channel set!")
    await edit_msg(q.message, "<blockquote>Fetching banner from channel...</blockquote>")
    try:
        from services.thumb import fetch_channel_thumb
        from services.catbox import Catbox
        import tempfile, os
        img_bytes = await fetch_channel_thumb(c, cid)
        if not img_bytes:
            return await edit_msg(
                q.message,
                "<b>⚠ No Image Found</b>\n\n"
                "<blockquote>Could not find any image in the first 5 messages of the channel.</blockquote>",
                reply_markup=KM([
                    [KB("[MANUAL] Upload Image", "manual_banner")],
                    [KB("[SKIP] No Banner", "skip_banner")]
                ])
            )
        await edit_msg(q.message, "<blockquote>Uploading to Catbox...</blockquote>")
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(img_bytes)
            tmp_path = f.name
        url = await Catbox.upload(tmp_path)
        os.remove(tmp_path)
        if not url:
            return await edit_msg(
                q.message,
                "✗ Catbox upload failed.",
                reply_markup=KM([
                    [KB("[RETRY] Fetch Again", "fetch_banner")],
                    [KB("[MANUAL] Upload", "manual_banner")],
                    [KB("[SKIP]", "skip_banner")]
                ])
            )
        await finalize_sub(q.message, uid, data, url, q.message)
    except Exception as e:
        await edit_msg(
            q.message,
            f"✗ Error: {e}",
            reply_markup=KM([
                [KB("[MANUAL] Upload", "manual_banner")],
                [KB("[SKIP]", "skip_banner")]
            ])
        )
@Client.on_callback_query(filters.regex("^manual_banner"))
async def manual_banner(c, q):
    uid = q.from_user.id
    data = search_states.get(uid)
    if not data: return await q.answer("Exp")
    data['state'] = 'await_banner_upload'
    search_states[uid] = data
    await edit_msg(
        q.message,
        "<b>[UPLOAD] Banner Image</b>\n\n"
        "<blockquote>Send me an image to use as the banner.</blockquote>\n"
        "<i>Best size: 800x400 or similar ratio.</i>",
        reply_markup=KM([[KB("[SKIP] No Banner", "skip_banner")]])
    )
