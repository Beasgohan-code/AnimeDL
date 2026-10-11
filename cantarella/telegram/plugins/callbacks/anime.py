import asyncio
import re
import time
from pyrogram import Client, filters
from pyrogram.enums import ParseMode, ChatType
from pyrogram.types import InlineKeyboardMarkup
from cantarella.button import Button as InlineKeyboardButton

from cantarella.core.state import user_episodes, user_search_results, user_range_data, user_watch_next, user_ani_search
from cantarella.core.database import db
from cantarella.core.images import get_random_image
from config import *
from .helpers import check_fsub, send_fsub_prompt
# ─────────────────────────────────────────────
#  Anime select & episode pagination
# ─────────────────────────────────────────────

@Client.on_callback_query(filters.regex("^anime_"))
async def on_anime_select(client: Client, callback_query):
    if not await check_fsub(client, callback_query.from_user.id):
        await callback_query.answer("🔒 ᴘʟᴇᴀꜱᴇ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ!", show_alert=True)
        return await send_fsub_prompt(client, callback_query.message)

    anime_id = callback_query.data.split("_")[1]

    # ── Multi-source engine: namespaced ids look like "hianime:slug" ──
    if ":" in anime_id:
        provider_id, provider_anime_id = anime_id.split(":", 1)
        try:
            from anime_sources import list_provider_episodes, get_provider
            provider = get_provider(provider_id)
        except Exception:
            await callback_query.answer("❌ Unknown source.", show_alert=True)
            return
        url = f"{provider_id}:{provider_anime_id}"
        entries = await client.loop.run_in_executor(
            None, list_provider_episodes, provider_id, provider_anime_id
        )
        if not entries:
            await callback_query.answer("❌ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ ғᴏᴜɴᴅ.")
            return
        user_episodes[callback_query.from_user.id] = {
            "title": entries[0].get("title", provider.name),
            "episodes": entries,
            "url": url,
            "page": 0,
        }
        return await show_episodes_page(client, callback_query, 0)

    active_source = await db.get_user_setting(0, "active_source", "hianime")
    if active_source == "animetsu":
        url = f"https://animetsu.live/anime/{anime_id}"
        from cantarella.scraper.animetsu import AnimetsuScraper
        downloader = AnimetsuScraper()
        from anime_sources.base import cached_episodes
        entries = await client.loop.run_in_executor(
            None, lambda: cached_episodes(
                f"list:animetsu:{anime_id}", downloader.list_episodes, anime_id))
    else:
        url = f"https://aniwatchtv.to/watch/{anime_id}"
        from cantarella.scraper.cantarellatv import cantarellatvDownloader
        downloader = cantarellatvDownloader()
        from anime_sources.base import cached_episodes
        entries = await client.loop.run_in_executor(
            None, lambda: cached_episodes(f"list:aniwatchtv:{url}", downloader.list_episodes, url))

    if not entries:
        await callback_query.answer("❌ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ ꜰᴏᴜɴᴅ.")
        return

    user_episodes[callback_query.from_user.id] = {
        'title':    entries[0].get('title', 'ᴜɴᴋɴᴏᴡɴ'),
        'episodes': entries,
        'url':      url,
        'page':     0
    }
    await show_episodes_page(client, callback_query, 0)


async def show_episodes_page(client, callback_query, page):
    user_id = callback_query.from_user.id
    data    = user_episodes.get(user_id)
    if not data:
        return

    entries         = data['episodes']
    start           = page * 20
    end             = start + 20
    current_entries = entries[start:end]

    buttons = []
    for i, entry in enumerate(current_entries):
        ep_idx = start + i
        buttons.append([InlineKeyboardButton(f"ᴇᴘɪꜱᴏᴅᴇ {ep_idx+1}", callback_data=f"ep_{ep_idx}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ ᴘʀᴇᴠ", callback_data=f"eps_page_{page-1}"))
    if end < len(entries):
        nav_row.append(InlineKeyboardButton("ɴᴇxᴛ ➡️", callback_data=f"eps_page_{page+1}"))

    jump_row = []
    if page >= 5:
        jump_row.append(InlineKeyboardButton("⏪ -100 ᴇᴘꜱ", callback_data=f"eps_page_{page-5}"))
    if (page + 5) * 20 < len(entries):
        jump_row.append(InlineKeyboardButton("+100 ᴇᴘꜱ ⏩", callback_data=f"eps_page_{page+5}"))

    if nav_row:
        buttons.append(nav_row)
    if jump_row:
        buttons.append(jump_row)

    # Add Favorite button (Admin Only)
    user_id = callback_query.from_user.id
    is_admin = user_id == OWNER_ID or await db.is_admin(user_id)

    range_btn = InlineKeyboardButton("🔢 ʀᴀɴɢᴇ ᴅᴏᴡɴʟᴏᴀᴅ", callback_data="range_dl_prompt")
    if is_admin:
        favorites = await db.get_favorites(user_id)
        is_fav = any(f['id'] == data['url'].split('/')[-1] for f in favorites)
        fav_btn = InlineKeyboardButton("❤ ʀᴇᴍᴏᴠᴇ ғᴀᴠ", callback_data=f"rem_fav_{data['url'].split('/')[-1]}") if is_fav else InlineKeyboardButton("🤍 ᴀᴅᴅ ғᴀᴠ", callback_data=f"add_fav_{data['url'].split('/')[-1]}")
        buttons.append([fav_btn, range_btn])
    else:
        buttons.append([range_btn])

    buttons.append([
        InlineKeyboardButton("🔙 ʙᴀᴄᴋ",         callback_data="back_to_search"),
        InlineKeyboardButton("📥 ᴅᴏᴡɴʟᴏᴀᴅ ᴀʟʟ", callback_data="download_all_opts"),
        InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ",         callback_data="adl_cancel")
    ])

    try:
        await callback_query.edit_message_caption(
            caption=f"<blockquote>📺 <b>ᴇᴘɪꜱᴏᴅᴇꜱ (ᴘᴀɢᴇ {page+1}):</b>\nꜱᴇʟᴇᴄᴛ ᴀɴ ᴇᴘɪꜱᴏᴅᴇ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ:</blockquote>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML
        )
    except:
        await callback_query.edit_message_text(
            f"<blockquote>📺 <b>ᴇᴘɪꜱᴏᴅᴇꜱ (ᴘᴀɢᴇ {page+1}):</b>\nꜱᴇʟᴇᴄᴛ ᴀɴ ᴇᴘɪꜱᴏᴅᴇ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ:</blockquote>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML
        )


@Client.on_callback_query(filters.regex("^eps_page_"))
async def on_eps_page(client: Client, callback_query):
    page = int(callback_query.data.split("_")[2])
    await show_episodes_page(client, callback_query, page)


@Client.on_callback_query(filters.regex("^back_to_search$"))
async def on_back_to_search(client: Client, callback_query):
    user_id = callback_query.from_user.id
    results = user_search_results.get(user_id)
    if not results:
        await callback_query.answer("❌ ꜱᴇᴀʀᴄʜ ʀᴇꜱᴜʟᴛꜱ ᴇxᴘɪʀᴇᴅ.", show_alert=True)
        return

    buttons = []
    for res in results:
        cb_data = f"anime_{res['id']}"
        if len(cb_data) > 64:
            cb_data = cb_data[:64]
        buttons.append([InlineKeyboardButton(f"{res['title']} ({res['type']})", callback_data=cb_data)])

    buttons.append([InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="adl_cancel")])

    keyboard = InlineKeyboardMarkup(buttons)
    try:
        await callback_query.edit_message_caption(
            caption="<blockquote>📺 <b>ꜱᴇᴀʀᴄʜ ʀᴇꜱᴜʟᴛꜱ:</b>\nꜱᴇʟᴇᴄᴛ ᴀɴ ᴀɴɪᴍᴇ:</blockquote>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    except:
        await callback_query.edit_message_text(
            "<blockquote>📺 <b>ꜱᴇᴀʀᴄʜ ʀᴇꜱᴜʟᴛꜱ:</b>\nꜱᴇʟᴇᴄᴛ ᴀɴ ᴀɴɪᴍᴇ:</blockquote>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )


@Client.on_callback_query(filters.regex("^add_fav_"))
async def on_add_favorite(client: Client, callback_query):
    user_id = callback_query.from_user.id
    if user_id != OWNER_ID and not await db.is_admin(user_id):
        return await callback_query.answer("❌ ᴛʜɪꜱ ꜰᴇᴀᴛᴜʀᴇ ɪꜱ ꜰᴏʀ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.", show_alert=True)

    anime_id = callback_query.data.split("_")[2]
    data = user_episodes.get(user_id)
    if not data:
        return await callback_query.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.")

    await db.add_favorite(user_id, anime_id, data['title'])
    await callback_query.answer("✅ ᴀᴅᴅᴇᴅ ᴛᴏ ғᴀᴠᴏʀɪᴛᴇꜱ!", show_alert=True)
    await show_episodes_page(client, callback_query, data.get('page', 0))

@Client.on_callback_query(filters.regex("^rem_fav_"))
async def on_rem_favorite(client: Client, callback_query):
    user_id = callback_query.from_user.id
    if user_id != OWNER_ID and not await db.is_admin(user_id):
        return await callback_query.answer("❌ ᴛʜɪꜱ ꜰᴇᴀᴛᴜʀᴇ ɪꜱ ꜰᴏʀ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.", show_alert=True)

    anime_id = callback_query.data.split("_")[2]
    await db.remove_favorite(user_id, anime_id)
    await callback_query.answer("❌ ʀᴇᴍᴏᴠᴇᴅ ғʀᴏᴍ ғᴀᴠᴏʀɪᴛᴇꜱ!", show_alert=True)
    data = user_episodes.get(user_id)
    if data:
        await show_episodes_page(client, callback_query, data.get('page', 0))

@Client.on_callback_query(filters.regex("^range_dl_prompt$"))
async def on_range_dl_prompt(client: Client, callback_query):
    user_id = callback_query.from_user.id
    if user_id not in user_episodes:
        return await callback_query.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.")

    from pyrogram.types import ForceReply
    # Telegram requires ForceReply to be sent in a NEW message to reliably trigger the keyboard auto-reply
    prompt = await client.send_message(
        chat_id=callback_query.message.chat.id,
        text="🔢 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴛʜᴇ ʀᴀɴɢᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ.\n\nFᴏʀᴍᴀᴛ: <code>start-end</code> (ᴇ.ɢ., <code>1-12</code>)",
        reply_markup=ForceReply(selective=True),
        parse_mode=ParseMode.HTML
    )
    # Store prompt message ID and original list message ID
    user_range_data[user_id] = {'prompt_id': prompt.id, 'original_msg_id': callback_query.message.id}
    await callback_query.answer()

@Client.on_callback_query(filters.regex("^cancel_range$"))
async def on_cancel_range(client: Client, callback_query):
    user_id = callback_query.from_user.id
    if user_id in user_range_data:
        msg_id = user_range_data[user_id].get('msg_id')
        if msg_id:
            try: await client.delete_messages(callback_query.message.chat.id, msg_id)
            except: pass
        del user_range_data[user_id]
    await callback_query.answer("❌ ʀᴀɴɢᴇ ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴀɴᴄᴇʟʟᴇᴅ.")

@Client.on_message(filters.private & filters.reply)
async def handle_range_input(client: Client, message):
    if not message.reply_to_message:
        return
    reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""
    if "ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴛʜᴇ ʀᴀɴɢᴇ" not in reply_text:
        return

    user_id = message.from_user.id
    # Clean up clutter: delete prompt and user reply
    try:
        await message.delete()
        await message.reply_to_message.delete()
    except: pass

    text = message.text.strip()
    match = re.match(r"(\d+)-(\d+)", text)

    if not match:
        msg = await message.reply("❌ ɪɴᴠᴀʟɪᴅ ғᴏʀᴍᴀᴛ. ᴜꜱᴇ <code>start-end</code> (ᴇ.ɢ., 1-12)")
        await asyncio.sleep(5)
        await msg.delete()
        return

    start, end = int(match.group(1)), int(match.group(2))
    if start > end:
        msg = await message.reply("❌ ꜱᴛᴀʀᴛ ᴇᴘɪꜱᴏᴅᴇ ᴄᴀɴɴᴏᴛ ʙᴇ ɢʀᴇᴀᴛᴇʀ ᴛʜᴀɴ ᴇɴᴅ ᴇᴘɪꜱᴏᴅᴇ.")
        await asyncio.sleep(5)
        await msg.delete()
        return

    user_range_data[user_id] = {'start': start, 'end': end, 'selected_qualities': []}
    await show_range_quality_selection(client, message, start, end, user_id=user_id)

async def show_range_quality_selection(client, message, start, end, edit=False, user_id=None):
    if user_id is None:
        if hasattr(message, 'from_user') and message.from_user and not message.from_user.is_bot:
            user_id = message.from_user.id
        elif message.chat and message.chat.type == ChatType.PRIVATE:
            user_id = message.chat.id
        else:
            user_id = message.chat.id

    if user_id not in user_range_data:
         user_range_data[user_id] = {'start': start, 'end': end, 'selected_qualities': []}

    selected = user_range_data[user_id].get('selected_qualities', [])

    def btn(q, label):
        return f"✅ {label}" if q in selected else label

    buttons = [
        [
            InlineKeyboardButton(btn("360", "360ᴘ"), callback_data="trq_360"),
            InlineKeyboardButton(btn("720", "720ᴘ"), callback_data="trq_720"),
            InlineKeyboardButton(btn("1080", "1080ᴘ"), callback_data="trq_1080")
        ],
        [InlineKeyboardButton(btn("auto", "ᴀᴜᴛᴏ (ʙᴇꜱᴛ)"), callback_data="trq_auto")],
        [
            InlineKeyboardButton("✅ ᴅᴏɴᴇ", callback_data="start_range_dl"),
            InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data="cancel_range")
        ]
    ]

    text = f"<blockquote>🔢 <b>ʀᴀɴɢᴇ ꜱᴇʟᴇᴄᴛᴇᴅ:</b> {start}-{end}\nꜱᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛɪᴇꜱ:</blockquote>"
    if edit:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
    else:
        new_msg = await client.send_message(message.chat.id, text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        user_range_data[user_id]['msg_id'] = new_msg.id

@Client.on_callback_query(filters.regex("^trq_"))
async def on_toggle_range_quality(client: Client, callback_query):
    user_id = callback_query.from_user.id
    if user_id not in user_range_data:
        # Try to recover from message
        msg_text = callback_query.message.text or callback_query.message.caption or ""
        m = re.search(r"ʀᴀɴɢᴇ ꜱᴇʟᴇᴄᴛᴇᴅ:</b> (\d+)-(\d+)", msg_text)
        if m:
            user_range_data[user_id] = {'start': int(m.group(1)), 'end': int(m.group(2)), 'selected_qualities': []}
        else:
            return await callback_query.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ. ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴛʜᴇ ʀᴀɴɢᴇ ᴀɢᴀɪɴ.", show_alert=True)

    quality = callback_query.data.split("_")[1]
    selected = user_range_data[user_id].setdefault('selected_qualities', [])

    if quality in selected:
        selected.remove(quality)
    else:
        selected.append(quality)

    range_data = user_range_data[user_id]
    await show_range_quality_selection(client, callback_query.message, range_data['start'], range_data['end'], edit=True, user_id=user_id)

@Client.on_callback_query(filters.regex("^start_range_dl$"))
async def on_start_range_dl(client: Client, callback_query):
    if not await check_fsub(client, callback_query.from_user.id):
        await callback_query.answer("🔒 ᴘʟᴇᴀꜱᴇ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ!", show_alert=True)
        return await send_fsub_prompt(client, callback_query.message)

    user_id = callback_query.from_user.id
    if user_id not in user_range_data:
        # Try to recover
        msg_text = callback_query.message.text or callback_query.message.caption or ""
        m = re.search(r"ʀᴀɴɢᴇ ꜱᴇʟᴇᴄᴛᴇᴅ:</b> (\d+)-(\d+)", msg_text)
        if m:
             # We still need qualities from somewhere, but they should be in the buttons...
             # Actually if user_range_data is gone, selected_qualities is gone too.
             pass
        return await callback_query.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.", show_alert=True)

    if user_id not in user_episodes:
        return await callback_query.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ. ᴘʟᴇᴀꜱᴇ ꜱᴇᴀʀᴄʜ ᴀɴɪᴍᴇ ᴀɢᴀɪɴ.", show_alert=True)

    range_data = user_range_data[user_id]
    qualities = range_data.get('selected_qualities', [])
    if not qualities:
        return await callback_query.answer("⚠️ ᴘʟᴇᴀꜱᴇ ꜱᴇʟᴇᴄᴛ ᴀᴛ ʟᴇᴀꜱᴛ ᴏɴᴇ ǫᴜᴀʟɪᴛʏ!", show_alert=True)

    start, end = range_data['start'], range_data['end']

    all_episodes = user_episodes[user_id]['episodes']
    selected_episodes = []

    for ep in all_episodes:
        try:
            ep_num = int(ep.get('ep_number', 0))
            if start <= ep_num <= end:
                selected_episodes.append(ep)
        except:
            pass

    if not selected_episodes:
        return await callback_query.answer("❌ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ ғᴏᴜɴᴅ ɪɴ ᴛʜɪꜱ ʀᴀɴɢᴇ.", show_alert=True)

    await callback_query.answer(f"📥 ꜱᴛᴀʀᴛɪɴɢ ʀᴀɴɢᴇ ᴅᴏᴡɴʟᴏᴀᴅ ғᴏʀ {len(selected_episodes)} ᴇᴘɪꜱᴏᴅᴇꜱ...")
    try: await callback_query.message.delete()
    except: pass

    from cantarella.telegram.download import _handle_download, run_episode_batch
    from cantarella.telegram.pages import post_to_main_channel
    from cantarella.core.utils import chunk_list

    target_chat = int(TARGET_CHAT_ID) if TARGET_CHAT_ID else callback_query.message.chat.id
    status_msg  = await callback_query.message.reply(
        f"<blockquote>🔢 <b>ʀᴀɴɢᴇ ᴅᴏᴡɴʟᴏᴀᴅ ꜱᴛᴀʀᴛᴇᴅ</b>\nǫᴜᴀʟɪᴛɪᴇꜱ: {', '.join(qualities)}\nʀᴀɴɢᴇ: {start}-{end}</blockquote>",
        parse_mode=ParseMode.HTML
    )
    range_t0 = time.time()
    range_ok = 0
    range_fail = 0

    quality_priority = {"360": 1, "720": 2, "1080": 3, "auto": 4}
    qualities.sort(key=lambda q: quality_priority.get(q, 99))

    chunk_size = 25
    for chunk_idx, ep_chunk in enumerate(chunk_list(selected_episodes, chunk_size)):
        ep_range_str = f"{ep_chunk[0]['ep_number']}-{ep_chunk[-1]['ep_number']}"
        all_chunk_msgs = []
        quality_map = {}

        for q in qualities:
            first_id = None
            last_id = None
            results_list, ok_n, fail_n = await run_episode_batch(
                client, None, ep_chunk, q, target_chat, progress_msg=status_msg
            )
            range_ok += ok_n
            range_fail += fail_n
            ep_msgs = [m for ms in results_list for m in ms]
            if ep_msgs:
                all_chunk_msgs.extend(ep_msgs)
                _ids = sorted(m.id for m in ep_msgs)   # out-of-order uploads
                first_id, last_id = _ids[0], _ids[-1]

            if first_id and last_id:
                q_label = f"{q}p" if q.isdigit() else "ᴀᴜᴛᴏ"
                quality_map[q_label] = str(first_id) if first_id == last_id else f"{first_id}-{last_id}"

        if all_chunk_msgs:
            await post_to_main_channel(client, ep_chunk[0]['url'], all_chunk_msgs, quality_map, batch_ep_range=ep_range_str)

    _took = int(time.time() - range_t0)
    try:
        _chat = await client.get_chat(target_chat)
        _where = f"📍 ꜰɪʟᴇꜱ ɪɴ: <b>{getattr(_chat, 'title', None) or getattr(_chat, 'first_name', target_chat)}</b>"
    except Exception:
        _where = f"📍 ꜰɪʟᴇꜱ ɪɴ: <code>{target_chat}</code>"
    if range_ok:
        await status_msg.edit_text(
            f"<blockquote>✅ <b>ʀᴀɴɢᴇ ᴅᴏᴡɴʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ!</b>\n"
            f"📦 ᴇᴘɪꜱᴏᴅᴇꜱ: ✅ {range_ok}" + (f" · ❌ {range_fail}" if range_fail else "") +
            f"\n⏱ ᴛᴏᴏᴋ: {_took//60}ᴍ {_took%60:02d}ꜱ\n{_where}</blockquote>",
            parse_mode=ParseMode.HTML
        )
    else:
        await status_msg.edit_text(
            f"<blockquote>❌ <b>ʀᴀɴɢᴇ ꜰᴀɪʟᴇᴅ — ɴᴏᴛʜɪɴɢ ᴡᴀꜱ ᴜᴘʟᴏᴀᴅᴇᴅ.</b>\n"
            f"⏱ ᴀғᴛᴇʀ {_took//60}ᴍ {_took%60:02d}ꜱ\n"
            f"💡 ᴛʀʏ ᴀɢᴀɪɴ ᴏʀ ᴘɪᴄᴋ ᴀɴᴏᴛʜᴇʀ ꜱᴏᴜʀᴄᴇ ғʀᴏᴍ /settings</blockquote>",
            parse_mode=ParseMode.HTML
        )

@Client.on_callback_query(filters.regex("^favorites$"))
async def on_favorites_cb(client: Client, callback_query):
    user_id = callback_query.from_user.id
    if user_id != OWNER_ID and not await db.is_admin(user_id):
        return await callback_query.answer("❌ ᴛʜɪꜱ ꜰᴇᴀᴛᴜʀᴇ ɪꜱ ꜰᴏʀ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.", show_alert=True)

    favorites = await db.get_favorites(user_id)

    if not favorites:
        return await callback_query.answer("❤ ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇꜱ ʟɪꜱᴛ ɪꜱ ᴇᴍᴘᴛʏ.", show_alert=True)

    buttons = []
    for fav in favorites:
        buttons.append([InlineKeyboardButton(fav['title'], callback_data=f"anime_{fav['id']}")])

    buttons.append([InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="start"), InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="adl_close")])

    await callback_query.edit_message_caption(
        caption="<blockquote>❤ <b>ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇ ᴀɴɪᴍᴇꜱ:</b></blockquote>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML
    )

@Client.on_callback_query(filters.regex("^ep_"))
async def on_episode_select(client: Client, callback_query):
    if not await check_fsub(client, callback_query.from_user.id):
        await callback_query.answer("🔒 ᴘʟᴇᴀꜱᴇ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ!", show_alert=True)
        return await send_fsub_prompt(client, callback_query.message)

    ep_idx  = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id
    if user_id not in user_episodes:
        await callback_query.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.")
        return

    page = ep_idx // 20
    buttons = [
        [
            InlineKeyboardButton("360ᴘ",  callback_data=f"dl_360_{ep_idx}"),
            InlineKeyboardButton("720ᴘ",  callback_data=f"dl_720_{ep_idx}"),
            InlineKeyboardButton("1080ᴘ", callback_data=f"dl_1080_{ep_idx}")
        ],
        [InlineKeyboardButton("ᴀᴜᴛᴏ (ʙᴇꜱᴛ)",    callback_data=f"dl_auto_{ep_idx}")],
        [InlineKeyboardButton("ᴀʟʟ ǫᴜᴀʟɪᴛɪᴇꜱ", callback_data=f"dl_all_{ep_idx}")],
        [InlineKeyboardButton("🔗 ꜱᴛʀᴇᴀᴍ ʟɪɴᴋ", callback_data=f"sl_{ep_idx}")],
        [
            InlineKeyboardButton("🔙 ʙᴀᴄᴋ", callback_data=f"eps_page_{page}"),
            InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="adl_cancel")
        ]
    ]
    try:
        await callback_query.edit_message_caption(
            caption=f"<blockquote>📥 <b>ᴅᴏᴡɴʟᴏᴀᴅ ᴇᴘɪꜱᴏᴅᴇ {ep_idx+1}</b>\nꜱᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛʏ:</blockquote>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML
        )
    except:
        await callback_query.edit_message_text(
            f"<blockquote>📥 <b>ᴅᴏᴡɴʟᴏᴀᴅ ᴇᴘɪꜱᴏᴅᴇ {ep_idx+1}</b>\nꜱᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛʏ:</blockquote>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML
        )

    # ── Speed: prefetch the stream resolution in the background NOW, so the
    # quality tap a few seconds later starts downloading instantly ──
    try:
        from anime_sources import is_provider_url, get_provider, provider_id_for_url
        from anime_sources.base import cached_streams
        ep_data = user_episodes[user_id]['episodes'][ep_idx]
        ep_url = ep_data.get("url", "")
        if is_provider_url(ep_url):
            pid = provider_id_for_url(ep_url)

            def _prefetch():
                try:
                    cached_streams(f"res:{pid}:{ep_url}",
                                   get_provider(pid).resolve, ep_url)
                except Exception:
                    pass  # prefetch is best-effort; real path retries

            asyncio.get_running_loop().run_in_executor(None, _prefetch)
    except Exception:
        pass


# ─────────────────────────────────────────────
#  Stream-link mode — resolve + share direct m3u8 (no download)
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex("^sl_"))
async def on_stream_link(client: Client, callback_query):
    if not await check_fsub(client, callback_query.from_user.id):
        await callback_query.answer("🔒 ᴘʟᴇᴀꜱᴇ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ!", show_alert=True)
        return await send_fsub_prompt(client, callback_query.message)

    ep_idx = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id
    if user_id not in user_episodes:
        return await callback_query.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.")

    ep_data = user_episodes[user_id]["episodes"][ep_idx]
    ep_url = ep_data.get("url", "")

    from anime_sources import is_provider_url, get_provider, provider_id_for_url
    if not is_provider_url(ep_url):
        return await callback_query.answer(
            "🔗 Stream links are available for Hianime / AllAnime / Gogo / AnimePahe sources.",
            show_alert=True,
        )

    await callback_query.answer("🔗 Resolving stream…")
    try:
        await callback_query.edit_message_caption(
            caption="<blockquote>🔗 <b>ʀᴇꜱᴏʟᴠɪɴɢ ꜱᴛʀᴇᴀᴍ...</b></blockquote>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    provider = get_provider(provider_id_for_url(ep_url))
    try:
        from anime_sources.base import cached_streams
        resolved = await client.loop.run_in_executor(
            None, lambda: cached_streams(
                f"res:{provider.id}:{ep_url}", provider.resolve, ep_url))
    except Exception as e:
        return await callback_query.message.reply(
            f"<blockquote>❌ <b>ꜱᴛʀᴇᴀᴍ ʀᴇꜱᴏʟᴜᴛɪᴏɴ ғᴀɪʟᴇᴅ:</b> {e}</blockquote>",
            parse_mode=ParseMode.HTML,
        )

    if not resolved.streams:
        return await callback_query.message.reply(
            "<blockquote>❌ ɴᴏ ꜱᴛʀᴇᴀᴍꜱ ғᴏᴜɴᴅ.</blockquote>", parse_mode=ParseMode.HTML
        )

    best = resolved.streams[0]
    quality = best.get("quality", "auto")
    link = best.get("url", "")
    subs = len(resolved.subtitles or [])
    audio = "dub" if getattr(provider, "id", "") == "hianime" and "dub" in ep_url else "sub/dub"

    text = (
        f"<blockquote>🔗 <b>{resolved.title} — EP {resolved.ep_num}</b></blockquote>\n"
        f"<blockquote>📶 <b>Quality:</b> <code>{quality}p</code>\n"
        f"🌐 <b>Source:</b> <code>{provider.name}</code>\n"
        f"🗣 <b>Audio:</b> <code>{audio}</code>"
        + (f"\n💬 <b>Subtitles:</b> <code>{subs} track(s)</code>" if subs else "")
        + "</blockquote>\n"
        f"<a href=\"{link}\">▶️ Open stream (m3u8)</a>\n"
        "<blockquote><i>Tip: paste this link into VLC / MX Player / TPlayer to watch instantly — no download needed.</i></blockquote>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬇️ ᴅᴏᴡɴʟᴏᴀᴅ ɪɴsᴛᴇᴀᴅ", callback_data=f"ep_{ep_idx}"),
         InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ", callback_data="adl_cancel")],
    ])
    try:
        await callback_query.edit_message_caption(caption=text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback_query.message.reply(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────
#  Continue watching — next episode / clear
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex("^wnext_"))
async def on_watch_next(client: Client, callback_query):
    if not await check_fsub(client, callback_query.from_user.id):
        await callback_query.answer("🔒 ᴘʟᴇᴀsᴇ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ꜰɪʀsᴛ!", show_alert=True)
        return await send_fsub_prompt(client, callback_query.message)

    user_id = callback_query.from_user.id
    idx = int(callback_query.data.split("_")[1])
    urls = user_watch_next.get(user_id) or []
    if idx >= len(urls) or not urls[idx]:
        return await callback_query.answer("❌ ɴᴇxᴛ-ᴇᴘɪsᴏᴅᴇ ʟɪɴᴋ ᴇxᴘɪʀᴇᴅ.", show_alert=True)

    from cantarella.telegram.download import _handle_download
    from config import TARGET_CHAT_ID

    await callback_query.answer("⏭ Starting next episode…")
    status_msg = await callback_query.message.reply(
        "<blockquote>⏭ <b>ᴘʀᴇᴘᴀʀɪɴɢ ɴᴇxᴛ ᴇᴘɪsᴏᴅᴇ...</b></blockquote>",
        parse_mode=ParseMode.HTML,
    )
    target_chat = int(TARGET_CHAT_ID) if TARGET_CHAT_ID else callback_query.message.chat.id
    await _handle_download(
        client, callback_query.message, urls[idx],
        status_msg, quality="auto", chat_id=target_chat,
    )


@Client.on_callback_query(filters.regex("^wclear$"))
async def on_watch_clear(client: Client, callback_query):
    from cantarella.core.database import db
    await db.clear_history(callback_query.from_user.id)
    user_watch_next.pop(callback_query.from_user.id, None)
    await callback_query.answer("🗑 History cleared", show_alert=True)
    try:
        await callback_query.message.delete()
    except Exception:
        pass


# ─────────────────────────────────────────────
#  /anime info card → search & download tap
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex("^aisearch$"))
async def on_ani_search(client: Client, callback_query):
    user_id = callback_query.from_user.id
    name = user_ani_search.get(user_id)
    if not name:
        return await callback_query.answer("❌ ꜱᴇᴀʀᴄʜ ᴇxᴘɪʀᴇᴅ — run /anime again.", show_alert=True)

    await callback_query.answer("🔍 Searching…")
    try:
        await callback_query.edit_message_caption(
            caption=f"<blockquote>🔍 <b>ꜱᴇᴀʀᴄʜɪɴɢ <i>{name}</i>...</b></blockquote>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    from cantarella.scraper.search import search_anime_multi
    from anime_sources.base import SOURCE_NAMES
    from cantarella.core.database import db as _db
    active_source = await _db.get_user_setting(0, "active_source", "hianime")
    results, tried = await client.loop.run_in_executor(None, search_anime_multi, name, active_source)

    if not results:
        import html as _html
        tried_line = " · ".join(f"{SOURCE_NAMES.get(s, s)}: {o}" for s, o in tried)
        return await callback_query.edit_message_caption(
            caption=(
                "<blockquote>❌ ɴᴏ ʀᴇꜰᴜʟᴛꜰ ᴀᴄᴛɪꜱᴇ ᴏɴ ᴀɴꜱ ꜰᴏᴜʀᴄᴇ.</blockquote>\n"
                f"<blockquote>🔎 {_html.escape(tried_line)}</blockquote>"
            ),
            parse_mode=ParseMode.HTML,
        )

    user_search_results[user_id] = results
    served_by = SOURCE_NAMES.get(tried[-1][0], tried[-1][0])
    buttons = []
    for res in results[:10]:
        cb = f"anime_{res['id']}"[:64]
        buttons.append([InlineKeyboardButton(f"{res['title']} ({res.get('type', 'TV')})", callback_data=cb)])
    buttons.append([InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="adl_cancel")])

    try:
        await callback_query.edit_message_caption(
            caption=f"<blockquote>📺 <b>ꜱᴇᴀʀᴄʜ ʀᴇsᴜʟᴛꜱ:</b>\nꜱᴇʟᴇᴄᴛ ᴀɴ ᴀɴɪᴍᴇ:</blockquote>\nꜱᴇʀᴠᴇᴅ ʙʏ: {served_by}</blockquote>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await callback_query.message.reply(
            f"<blockquote>📺 <b>ꜱᴇᴀʀᴄʜ ʀᴇsᴜʟᴛꜱ:</b>\nꜱᴇʟᴇᴄᴛ ᴀɴ ᴀɴɪᴍᴇ:</blockquote>\nꜱᴇʀᴠᴇᴅ ʙʏ: {served_by}</blockquote>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )

    # ── Speed: warm episode listings for the top results in the background,
    # so tapping a result shows its episode list instantly ──
    try:
        def _warm_listings():
            for res in results[:4]:
                rid = str(res.get("id", ""))
                try:
                    if ":" in rid:
                        from anime_sources import list_provider_episodes
                        pid, paid = rid.split(":", 1)
                        list_provider_episodes(pid, paid)
                    elif active_source == "animetsu":
                        from anime_sources.base import cached_episodes as _ce
                        from cantarella.scraper.animetsu import AnimetsuScraper
                        _ce(f"list:animetsu:{rid}", AnimetsuScraper().list_episodes, rid)
                    else:
                        from anime_sources.base import cached_episodes as _ce
                        from cantarella.scraper.cantarellatv import cantarellatvDownloader
                        _u = f"https://aniwatchtv.to/watch/{rid}"
                        _ce(f"list:aniwatchtv:{_u}", cantarellatvDownloader().list_episodes, _u)
                except Exception:
                    pass

        asyncio.get_running_loop().run_in_executor(None, _warm_listings)
    except Exception:
        pass

