from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from .storage import *
from bot import Bot, Vars  #, logger
import random

from Tools.db import *
from pyrogram.errors import FloodWait

from pyrogram.handlers import CallbackQueryHandler


def dynamic_data_filter(data):
  async def func(flt, _, query):
      return flt.data == query.data

  return filters.create(func, data=data)
  
@Bot.on_callback_query(dynamic_data_filter("refresh"))
async def refresh_handler(_, query):
  if not _.FSB or _.FSB == []:
    await retry_on_flood(query.answer
                         )(" ✅ Thanks for joining! You can now use the bot. ",
                           show_alert=True)
    return await retry_on_flood(query.message.delete)()

  channel_button, change_data = await check_fsb(_, query)
  if not channel_button:
    await retry_on_flood(query.answer
                         )(" ✅ Thanks for joining! You can now use the bot. ",
                           show_alert=True)
    return await retry_on_flood(query.message.delete)()

  channel_button = split_list(channel_button)
  channel_button.append(
      [InlineKeyboardButton("🔃 Refresh 🔃", callback_data="refresh")])

  try:
    await retry_on_flood(query.edit_message_media)(
        media=InputMediaPhoto(random.choice(Vars.PICS),
                              caption=Vars.FORCE_SUB_TEXT),
        reply_markup=InlineKeyboardMarkup(channel_button),
    )
  except:
    await retry_on_flood(query.answer)("You're still not in the channel.")

  if change_data:
    for change_ in change_data:
      _.FSB[change_[0]] = (change_[1], change_[2], change_[3])


@Bot.on_callback_query(dynamic_data_filter("close"))
async def close_handler(_, query):
  try:
    await query.message.reply_to_message.delete()
  except:
    pass
  try:
    await query.message.delete()
  except:
    pass

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(dynamic_data_filter("kclose"))
async def kclose_handler(_, query):
  try:
    await query.message.reply_to_message.delete()
  except:
    pass
  try:
    await query.message.delete()
  except:
    pass

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(dynamic_data_filter("premuim"))
async def premuim_handler(_, query):
  """This Is Premuim Handler Of Callback Data"""
  button = query.message.reply_markup.inline_keyboard
  text = """
<b><i>Premium Price

Pricing Rates
  7 Days - 30 inr / 0.35 USD / NRS 40
  1 Month - 90 inr / 1.05 USD / NRS 140
  3 Months - 260 inr / 2.94 USD / NRS 350
  6 Months - 500 inr / 6.33 USD / NRS 700
  9 Months - 780 inr / 9.14 USD / NRS 1100
  12 Months - 1000 inr / 11.8 USD / NRS 1400

Want To Buy ?!
  Contact or DM - @Shanks_Kun

We Have Limited Seats For Premium Users</i></b>"""
  try:
    del button[-2]
    await retry_on_flood(query.edit_message_media
                         )(media=InputMediaPhoto(random.choice(Vars.PICS),
                                                 caption=text),
                           reply_markup=InlineKeyboardMarkup(button))
  except:
    button = [[InlineKeyboardButton(" Close ", callback_data="kclose")]]
    await retry_on_flood(query.edit_message_media
                         )(media=InputMediaPhoto(random.choice(Vars.PICS),
                                                 caption=text),
                           reply_markup=InlineKeyboardMarkup(button))


@Bot.on_callback_query(dynamic_data_filter("refresh_queue"))
async def queue_refresh_handler(_, query):
  """This Is Queue Refresh Handler Of Callback Data"""
  try:
    _datas_ = list(queue.ongoing_tasks.values())
    reply_txt = f"<blockquote><b>📌 Queue Status (Total: {str(queue.qsize())} chapters)</b></blockquote>\n\n"
    reply_txt += f"<b>👤 Your queue:</b>"
    
    _processing = []
    _user_count = queue.get_count(query.from_user.id)
    if _user_count and int(_user_count) != 0:
      reply_txt+= f"""<blockquote expandable>=> <i>Total Chapters: {_user_count}</i>\n"""
      if _datas_:
        value = next((data['data'] for data in _datas_ if data['user_id'] == query.from_user.id), None)
        value = value[0] if value else None
        if value:
          reply_txt += f"=> <i>{value['manga_title']} - {value['title']}</i></blockquote>\n"
      else:
        reply_txt += "</blockquote>\n"
    else:
      reply_txt += "\n=> <i>No chapters in your queue.</i>\n"
    
    reply_txt += "\n**🚦 Now Processing:**\n"
    if _datas_:
      reply_txt += "<blockquote expandable>"
      for i, data in enumerate(_datas_, 1):
        user_query = data['data'][2]
        reply_txt += f"{i}. {user_query.from_user.mention()}\n"
        _processing.append(user_query.from_user.id)
        if i == 3:
          break
        reply_txt += "</blockquote>\n"
    else:
      reply_txt += "=> <i>No chapters in global queue.</i>\n"
    
    sample_txt = ""
    sample_txt += "\n**⏳ Waiting Line:**\n"
    if queue.qsize() > 0:
      reply_txt += "<blockquote expandable>"
      for i, data in enumerate(queue.storage_data.values(), 1):
        user_query = data['data'][2]
        if user_query.from_user.id not in _processing:
          sample_txt += f"{i}. {user_query.from_user.mention()}\n"
        if i == 3:
          break
      
      sample_txt += "=> <i>Other chapters are in the waiting line.</i>"
      sample_txt += "</blockquote>\n"
    else:
      sample_txt += "=> <i>No chapters in waiting line.</i>\n"
    
    if int(len(reply_txt) + len(sample_txt)) < 4096:
      reply_txt += sample_txt
    try:
      await retry_on_flood(query.edit_message_text)(
        reply_txt,
        reply_markup=InlineKeyboardMarkup([
          [
            InlineKeyboardButton("🗑 Clean Queue 🗑", callback_data="clean_queue"),
            InlineKeyboardButton("🪦 Subscription 🪦", callback_data="isubs")
          ],
          [
            InlineKeyboardButton("⚔️ Close ⚔️", callback_data="kclose"),
            InlineKeyboardButton("🔄 Refresh 🔄", callback_data="refresh_queue")
          ],
          [
            InlineKeyboardButton(" ♕ Owner ♕", user_id=Vars.OWNER)
          ]
        ])
      )
    except FloodWait as e:
      await asyncio.sleep(e.value + 2)
      await retry_on_flood(query.edit_message_text)(
        reply_txt,
        reply_markup=InlineKeyboardMarkup([
          [
            InlineKeyboardButton("🗑 Clean Queue 🗑", callback_data="clean_queue"),
            InlineKeyboardButton("🪦 Subscription 🪦", callback_data="isubs")
          ],
          [
            InlineKeyboardButton("⚔️ Close ⚔️", callback_data="kclose"),
            InlineKeyboardButton("🔄 Refresh 🔄", callback_data="refresh_queue")
          ],
          [
            InlineKeyboardButton(" ♕ Owner ♕", user_id=Vars.OWNER)
          ]
        ])
      )
    except:
      try: return await retry_on_flood(query.answer)(" Nothing Added At Queue. ")
      except: return
    
    try:
      await query.answer()
    except:
      pass
    
  except Exception as err:
    logger.exception(f"refresh_queue : {err}")
    try: await retry_on_flood(query.answer)(" Something went wrong.")
    except: pass


@Bot.on_callback_query(dynamic_data_filter("clean_queue"))
async def clean_queue_handler(_, query):
  """This Is Clean Queue Handler Of Callback Data"""
  if queue.get_count(query.from_user.id):
    numb = await queue.delete_tasks(query.from_user.id)
    try:
      await retry_on_flood(query.answer)(f" All Your Tasks Deleted:- {numb} ")
    except:
      pass
  else:
    try:
      await retry_on_flood(query.answer)(" There is no any your pending tasks.... ")
    except:
      pass

@Bot.on_callback_query(filters.regex("^chs"))
async def ch_handler(client, query):
  """This Is Information Handler Of Callback Data"""
  reply = query.message.reply_to_message

  user_id = reply.from_user.id
  query_user_id = query.from_user.id
  if user_id != query_user_id:
    return await query.answer("This is not for you", show_alert=True)

  try:
    webs, data = searchs[query.data]
  except:
    return await query.answer("This is an old button, please redo the search",
                              show_alert=True)

  try:
    bio_list = await webs.get_chapters(data)
  except:
    return await query.answer("No chapters found", show_alert=True)

  if not bio_list:
    return await query.answer("No chapters found", show_alert=True)
  if bio_list == [] or len(bio_list) < 1:
    return await query.answer("No chapters found", show_alert=True)

  c = f"pg:{webs.sf}:{hash(bio_list['url'])}:"
  pagination[c] = (webs, bio_list, data)
  
  subs_bool = get_subs(str(query.from_user.id), bio_list['url'], webs.sf)
  sc = f"subs:{hash(bio_list['url'])}"
  subscribes[sc] = (webs, bio_list)

  rand_pic = bio_list['poster'] if "poster" in bio_list else random.choice(
      Vars.PICS)
  caption = bio_list[
      'msg'][:1024] if "msg" in bio_list else f"<b>{bio_list['title']}</b>"
  if webs.sf == "mf":
    button = [
      [
        InlineKeyboardButton("🔔 Unsubscribe 🔔", callback_data=sc) if subs_bool else InlineKeyboardButton("📯 Subscribe 📯", callback_data=sc)
      ],
      [
        InlineKeyboardButton("📨 Chapters 📨", callback_data=f"{c}:1"),
        InlineKeyboardButton("🎴 Volume 🎴", callback_data=f"{c}:v:1")
      ],
      [
        InlineKeyboardButton("💠 Back 💠", callback_data=f"bk.s.{webs.sf}")
      ]
    ]
  else:
    button = [
      [
        InlineKeyboardButton("🔔 Unsubscribe 🔔", callback_data=sc) if subs_bool else InlineKeyboardButton("📯 Subscribe 📯", callback_data=sc)
      ],
      [
        InlineKeyboardButton("📨 Chapters 📨", callback_data=f"{c}:1"),
        InlineKeyboardButton("💠 Back 💠", callback_data=f"bk.s.{webs.sf}")
      ],
    ]
  if webs.sf == "ck":
    button.append([InlineKeyboardButton("🔥 Close 🔥", callback_data="kclose")])
  
  try:
    await retry_on_flood(query.edit_message_media)(
        InputMediaPhoto(rand_pic, caption=caption),
        reply_markup=InlineKeyboardMarkup(button))
  except:
    await retry_on_flood(query.edit_message_media)(
        InputMediaPhoto(Vars.PICS[-1], caption=caption),
        reply_markup=InlineKeyboardMarkup(button))


@Bot.on_callback_query(filters.regex("^pg"))
async def pg_handler(client, query):
  """This Is Pagination Handler Of Callback Data"""
  reply = query.message.reply_to_message

  user_id = reply.from_user.id
  query_user_id = query.from_user.id
  if user_id != query_user_id:
    return await query.answer("This is not for you", show_alert=True)

  call_data = query.data.split(":")
  page = call_data[-1]
  
  vols = None
  if call_data[-2] == "v":
    vols = True
    call_data= ":".join(call_data[:-2])
  else:
    call_data = ":".join(call_data[:-1])
  
  call_data = f"{call_data}:"
  if call_data not in pagination:
    call_data = call_data[:-1]

  if call_data in pagination:
    webs, data, rdata = pagination[call_data]
    sf = webs.sf
    subs_bool = get_subs(str(query.from_user.id), rdata['url'], sf)
    if sf == "ck":
      chapters = await webs.get_chapters(rdata, page=int(page))
      if not chapters:
        return await query.answer("No chapters found", show_alert=True)

      try: 
        chapters = webs.iter_chapters(chapters)
      except:
        return await query.answer("No chapters found", show_alert=True)
      
    elif sf == "mf" and vols:
      chapters = await webs.get_chapters(rdata, vol=True, page=int(page))
      if not chapters:
        return await query.answer("No chapters found", show_alert=True)
      if "chapters" in chapters and not chapters['chapters']:
        return await query.answer("No chapters found", show_alert=True)
      
      try: 
        chapters = webs.iter_chapters(chapters, vol=True, page=int(page))
      except:
        return await query.answer("No chapters found", show_alert=True)
    
    else:
      try:
        chapters = await webs.iter_chapters(data, page=int(page))
      except TypeError:
        chapters = webs.iter_chapters(data, page=int(page))

    if not chapters:
      return await query.answer("No chapters found", show_alert=True)

    if chapters == [] or len(chapters) < 1:
      return await query.answer("No chapters found", show_alert=True)

    button = []
    for chapter in chapters:
      c = f"pic|{hash(chapter['url'])}"
      chaptersList[c] = (webs, chapter)
      button.append(InlineKeyboardButton(chapter['title'], callback_data=c))

    button = split_list(button[:60])
    c = f"pg:{sf}:{hash(chapters[-1]['url'])}:"
    pagination[c] = (webs, data, rdata)

    if int(page) > 0:
      if sf == "ck":
        button.append([
            InlineKeyboardButton("<<", callback_data=f"{c}{int(page) - 1}"),
            InlineKeyboardButton("<2x", callback_data=f"{c}{int(page) - 2}"),
            InlineKeyboardButton("<5x", callback_data=f"{c}{int(page) - 5}")
        ])
      else:
        pre_page_ = []

        if int(int(page) - 1) > 0 and webs.iter_chapters(data, page=int(int(page) - 1)):
          pre_page_.append(
              InlineKeyboardButton("<<", callback_data=f"{c}{int(page) - 1}"))
        if int(int(page) - 2) > 0 and webs.iter_chapters(data, page=int(int(page) - 2)):
          pre_page_.append(
              InlineKeyboardButton("<2x", callback_data=f"{c}{int(page) - 2}"))
        if int(int(page) - 5) > 0 and webs.iter_chapters(data, page=int(int(page) - 5)):
          pre_page_.append(
              InlineKeyboardButton("<5x", callback_data=f"{c}{int(page) - 5}"))
        if pre_page_:
          button.append(pre_page_)

    if webs.sf == "ck":
      button.append([
          InlineKeyboardButton(">>", callback_data=f"{c}{int(page) + 1}"),
          InlineKeyboardButton("2x>", callback_data=f"{c}{int(page) + 2}"),
          InlineKeyboardButton("5x>", callback_data=f"{c}{int(page) + 5}"),
      ])
    else:
      next_page_ = []
      if webs.iter_chapters(data, page=int(int(page) + 1)):
        next_page_.append(
            InlineKeyboardButton(">>", callback_data=f"{c}{int(page) + 1}"))
      if webs.iter_chapters(data, page=int(int(page) + 2)):
        next_page_.append(
            InlineKeyboardButton("2x>", callback_data=f"{c}{int(page) + 2}"))
      if webs.iter_chapters(data, page=int(int(page) + 5)):
        next_page_.append(
            InlineKeyboardButton("5x>", callback_data=f"{c}{int(page) + 5}"))
      if next_page_:
        button.append(next_page_)

    c = f"subs:{hash(rdata['url'])}"
    subscribes[c] = (webs, rdata)

    if webs.sf != "dj":
      if subs_bool:
        button.append(
            [InlineKeyboardButton("🔔 Unsubscribe 🔔", callback_data=c)])
      else:
        button.append([InlineKeyboardButton("📯 Subscribe 📯", callback_data=c)])

    if sf == "ck":
      callback_data = f"sgh:{sf}:{hash(chapters[0]['url'])}"
      pagination[callback_data] = (chapters, webs, rdata, page)
      pagination[callback_data.replace("sgh", "full")] = (chapters[:60], webs)
      button.append([
          InlineKeyboardButton("📡 Scanlation Group 📡",
                               callback_data=callback_data),
          InlineKeyboardButton("📚 Full Page 📚",
                               callback_data=callback_data.replace(
                                   "sgh", "full"))
      ])
      button.append([
        InlineKeyboardButton("💠 Back 💠", callback_data=f"bk.s.{sf}")
      ])
      
    elif sf == "mf":
      callback_data = f"full:{sf}:{hash(chapters[0]['url'])}"
      if int(page) == 1:
        pagination[callback_data] = (chapters[:60], webs)
      else:
        pagination[callback_data] = (chapters, webs)
      
      button.append(
        [
          InlineKeyboardButton("📡 Chapters 📡", callback_data=f"{call_data}:{page}") if vols else InlineKeyboardButton("📡 Volume 📡", callback_data=f"{call_data}v:{page}"),
          InlineKeyboardButton("📚 Full Page 📚", callback_data=callback_data)
        ])
      button.append(
        [
          InlineKeyboardButton("💠 Back 💠", callback_data=f"bk.s.{sf}")
        ]
      )
      
    else:
      callback_data = f"full:{sf}:{hash(chapters[0]['url'])}"
      if int(page) == 1:
        pagination[callback_data] = (chapters[:60], webs)
      else:
        pagination[callback_data] = (chapters, webs)

      button.append(
          [InlineKeyboardButton("📚 Full Page 📚", callback_data=callback_data), InlineKeyboardButton("💠 Back 💠", callback_data=f"bk.s.{sf}")]
      )
      

    try:
      await retry_on_flood(query.edit_message_reply_markup
                           )(InlineKeyboardMarkup(button))
    except:
      await retry_on_flood(client.edit_message_reply_markup
                           )(query.message.chat.id, query.message.message_id,
                             InlineKeyboardMarkup(button))
  else:
    try:
      await query.answer("This is an old button, please redo the search",
                         show_alert=True)
    except:
      pass


@Bot.on_callback_query(filters.regex("^sgh"))
async def cgk_handler(client, query):
  """This Is Scanlation Group Handler Of Callback Data"""
  if query.data in pagination:
    jcallback_back = query.data
    reply = query.message.reply_to_message
    user_id = reply.from_user.id
    query_user_id = query.from_user.id
    if user_id != query_user_id:
      return await query.answer("This is not for you", show_alert=True)

    chapters, webs, rdata, page = pagination[query.data]
    data = {}
    for chapter in chapters:
      group_name = chapter['group_name']
      if group_name:
        if group_name not in data:
          data[group_name] = []
        data[group_name].append(chapter)
      else:
        if "Unknown" not in data:
          data["Unknown"] = []
        data["Unknown"].append(chapter)

    button = []

    rcallback_data = f"pg:{webs.sf}:{hash(chapters[-1]['url'])}:{page}"
    pagination[rcallback_data] = (webs, chapters, rdata)
    for group_name in data.keys():
      groupLen = len(data[group_name])
      c = f"sgk|{hash(group_name)}"
      pagination[c] = (data[group_name], webs, page, rcallback_data,
                       jcallback_back)
      button.append([
          InlineKeyboardButton(f"{group_name} ({groupLen})", callback_data=c)
      ])

    button.append([
        InlineKeyboardButton("💠 Back To Chapters 💠",
                             callback_data=rcallback_data)
    ])

    try:
      await retry_on_flood(query.edit_message_reply_markup
                           )(InlineKeyboardMarkup(button))
    except:
      await retry_on_flood(client.edit_message_reply_markup
                           )(query.message.chat.id, query.message.message_id,
                             InlineKeyboardMarkup(button))

    try:
      await query.answer()
    except:
      pass
  else:
    try:
      await query.answer("This is an old button, please redo the search",
                         show_alert=True)
    except:
      pass


@Bot.on_callback_query(filters.regex("^sgk"))
async def sgk_handler(client, query):
  if query.data in pagination:
    reply = query.message.reply_to_message
    if reply:
      user_id = reply.from_user.id
      query_user_id = query.from_user.id
      if user_id != query_user_id:
        return await query.answer("This is not for you", show_alert=True)

    chapters, webs, page, rcallback_data, jcallback_back = pagination[
        query.data]
    #chapters = list(reversed(chapters))
    button = []
    for chapter in chapters:
      c = f"pic|{hash(chapter['url'])}"
      chaptersList[c] = (webs, chapter)
      button.append(InlineKeyboardButton(chapter['title'], callback_data=c))

    button = split_list(button[:60])
    callback_data = f"full:{webs.sf}:{hash(chapters[0]['url'])}"
    pagination[callback_data] = (chapters, webs)
    button.append(
        [InlineKeyboardButton("📖 Full Page 📖", callback_data=callback_data)])

    button.append([
        InlineKeyboardButton("🧸 Back To Groups 🧸",
                             callback_data=jcallback_back)
    ])
    button.append([
        InlineKeyboardButton("💸 Back To Chapters 💸",
                             callback_data=rcallback_data)
    ])

    try:
      await retry_on_flood(query.edit_message_reply_markup
                           )(InlineKeyboardMarkup(button))
    except:
      await retry_on_flood(client.edit_message_reply_markup
                           )(query.message.chat.id, query.message.message_id,
                             InlineKeyboardMarkup(button))

    try:
      await query.answer()
    except:
      pass
  else:
    try:
      await query.answer("This is an old button, please redo the search",
                         show_alert=True)
    except:
      pass


@Bot.on_callback_query(filters.regex("^full"))
async def full_handler(client, query):
  """This Is Full Page Handler Of Callback Data"""

  if query.data in pagination:
    reply = query.message.reply_to_message

    user_id = reply.from_user.id
    query_user_id = query.from_user.id
    if user_id != query_user_id:
      return await query.answer("This is not for you", show_alert=True)

    chapters, webs = pagination[query.data]
    merge_size = uts[str(query.from_user.id)].get('setting',
                                                  {}).get('megre', None)
    priority = uts[str(query.from_user.id)].get('setting',
                                                {}).get("premuim", 1)

    try:
      merge_size = int(merge_size) if merge_size else merge_size
    except:
      merge_size = None

    added_item = {}
    chapters = list(reversed(chapters))

    try:
      if merge_size:
        for i in range(0, len(chapters), merge_size):
          data = chapters[i:i + merge_size]
          for chapter in data:
            episode_num = get_episode_number(data[0]['title'])
            if episode_num not in added_item:
              added_item[episode_num] = data

      else:
        for data in chapters:
          episode_num = get_episode_number(data['title'])
          if episode_num not in added_item:
            added_item[episode_num] = data

      tasks = [
          queue.put(
              data=(data, None, query, None, webs),
              user_id=query.from_user.id,
              priority=priority,
          ) for data in added_item.values()
      ]
      await asyncio.gather(*tasks)

      try:
        await query.answer(f"{len(tasks)} Chapter Added To Queue",
                           show_alert=True)
      except:
        return

    except Exception as err:
      try:
        await retry_on_flood(query.answer)(f"Error: {err}", show_alert=True)
      except Exception as err:
        await retry_on_flood(query.message.reply_text)(f"```{err}```")

  else:
    try:
      await query.answer("This is an old button, please redo the search",
                         show_alert=True)
    except:
      return



@Bot.on_callback_query(filters.regex("^subs"))
async def subs_handler(client, query):
  """This Is Subscribe Handler Of Callback Data"""
  if query.data in subscribes:
    webs, data = subscribes[query.data]

    reply = query.message.reply_to_message

    user_id = reply.from_user.id
    query_user_id = query.from_user.id
    if user_id != query_user_id:
      return await query.answer("This is not for you", show_alert=True)

    reply_markup = query.message.reply_markup
    button = reply_markup.inline_keyboard

    s_data = {"url": data['url'], "title": data['title']}

    if get_subs(str(query.from_user.id), s_data['url'], webs.sf):
      await delete_sub(str(query.from_user.id), s_data['url'], webs.sf)
      if webs.sf == "ck" or webs.sf == "mf":
        button[-3] = [
          InlineKeyboardButton("📯 Subscribe 📯", callback_data=query.data)
        ]
      else:
        button[-2] = [
          InlineKeyboardButton("📯 Subscribe 📯", callback_data=query.data)
        ]
    else:
      await add_sub(str(query.from_user.id), s_data, webs.sf)
      if webs.sf == "ck" or webs.sf == "mf":
        button[-3] = [
          InlineKeyboardButton("🔔 Unsubscribe 🔔", callback_data=query.data)
        ]
      else:
        button[-2] = [
          InlineKeyboardButton("🔔 Unsubscribe 🔔", callback_data=query.data)
        ]
    try:
      await retry_on_flood(query.edit_message_reply_markup
                           )(InlineKeyboardMarkup(button))
    except:
      await retry_on_flood(client.edit_message_reply_markup
                           )(query.message.chat.id, query.message.message_id,
                             InlineKeyboardMarkup(button))
  else:
    try:
      await query.answer("This is an old button, please redo the search",
                         show_alert=True)
    except:
      pass


@Bot.on_callback_query(filters.regex("^pic"))
async def pic_handler(client, query):
  """This Is Pictures Handler Of Callback Data"""
  if query.data in chaptersList:
    webs, data = chaptersList[query.data]
    reply = query.message.reply_to_message

    user_id = reply.from_user.id
    query_user_id = query.from_user.id
    if user_id != query_user_id:
      return await query.answer("This is not for you", show_alert=True)

    try:
      pictures = await webs.get_pictures(url=data['url'], data=data)
    except:
      return await query.answer("No pictures found", show_alert=True)

    if not pictures:
      return await query.answer("No pictures found", show_alert=True)
    
    if str(query.from_user.id) not in uts:
      uts[str(query.from_user.id)] = {}
      sync()
    
    if "setting" not in uts[str(query.from_user.id)]:
      uts[str(query.from_user.id)]['setting'] = {}
      sync()
    
    sts = await retry_on_flood(query.message.reply_text
                               )("<code>Adding...</code>")

    txt = f"<i>Manga Name: **{data['manga_title']}** Chapter: - **{data['title']}**</i>"
    priority = uts[str(query.from_user.id)].get('setting', {}).get("premuim", 1)
    
    task_id = await queue.put(
      data=(data, None, query, sts, webs),
      user_id=user_id,
      priority=priority,
    )
    
    button = [[
        InlineKeyboardButton(" Cancel Your Tasks ",
                             callback_data=f"cl:{task_id}")
    ]]
    await retry_on_flood(sts.edit)(txt,
                                   reply_markup=InlineKeyboardMarkup(button))
    await query.answer(f"Your {task_id} added at queue")
  else:
    try:
      await query.answer("This is an old button, please redo the search",
                         show_alert=True)
    except:
      pass


@Bot.on_callback_query(filters.regex("^cl"))
async def cl_handler(client, query):
  """This Is Cancel Handler Of Callback Data"""
  task_id = query.data.split(":")[-1]
  reply = query.message.reply_to_message

  if await queue.delete_task(task_id):
    await retry_on_flood(query.message.edit_text
                         )("<i>Your Task Cancelled !</i>")
  else:
    await retry_on_flood(query.answer)(" Task Not Found ", show_alert=True)
    await retry_on_flood(query.message.delete)()


async def isubs_handle(_, query):
  """This Is Subscribe Handler Of Callback Data"""
  try:
    page = int(query.data.split(":")[-1])
  except:
    page = 1

  user_id = str(query.from_user.id)
  if user_id not in uts:
    uts[user_id] = {}
    sync()

    return await query.answer("You Have No Subs", show_alert=True)

  manga_subs = get_subs(user_id)
  if not manga_subs:
    return await query.answer("You Have No Subs", show_alert=True)

  if manga_subs is True:
    return await query.answer("You Have No Subs", show_alert=True)

  button = []

  manga_subs = manga_subs[(page - 1) * 60:page *
                          60] if page != 1 else manga_subs[:60]

  for data in manga_subs:
    web = check_get_web(data['url'])

    data['slug'] = data['url'].split("/")[-1]
    if data['slug'] == "":
      data['slug'] = data['url'].split("/")[-2]

    c = f"chs|{web.sf}{hash(data['url'])}"
    searchs[c] = (web, data)
    button.append([InlineKeyboardButton(data['title'], callback_data=c)])

  if len(manga_subs) > 60:
    button.append(
        [InlineKeyboardButton(f">>", callback_data=f"isubs:{page+1}")])
  if page != 1:
    button.append(
        [InlineKeyboardButton(f"<<", callback_data=f"isubs:{page-1}")])

  button.append([
    InlineKeyboardButton("♧ Queue ♧", callback_data="refresh_queue"),
    InlineKeyboardButton("🔥 Close 🔥", callback_data="kclose")
  ])

  try:
    await retry_on_flood(query.edit_message_media
                         )(InputMediaPhoto(random.choice(Vars.PICS), caption="<i>Your Subs ..</i>"),
                           reply_markup=InlineKeyboardMarkup(button))
  except:
    try:
      await retry_on_flood(_.edit_message_caption
                           )(query.message.chat.id,
                             query.message.message_id,
                             "<i>Your Subs ..</i>",
                             reply_markup=InlineKeyboardMarkup(button))

    except:
      chat_id = query.message.chat.id or query.chat.id
      msg_id = query.message.reply_to_message.message_id or query.reply_to_message.message_id

      await retry_on_flood(_.send_photo)(
          chat_id,
          photo=random.choice(Vars.PICS),
          caption="<i>Your Subs ..</i>",
          reply_to_message_id=msg_id,
          invert_media=True,
          reply_markup=InlineKeyboardMarkup(button),
      )
  finally:
    try:
      await query.answer()
    except:
      return


Bot.add_handler(CallbackQueryHandler(isubs_handle, filters.regex("^isubs")))


@Bot.on_callback_query(filters.regex("^bk"))
async def bk_handler(client, query):
  """This Is Back Handler Of Callback Data"""
  reply = query.message.reply_to_message
  photo = random.choice(Vars.PICS)
  try:
    user_id = reply.from_user.id
    query_user_id = query.from_user.id
    if user_id != query_user_id:
      return await query.answer("This is not for you", show_alert=True)
  except:
    pass

  if query.data == "bk.p":
    await retry_on_flood(query.message.edit_media)(
        media=InputMediaPhoto(photo, caption="<i>Select The Webs ....</i>"),
        reply_markup=plugins_list(),
    )
    try:
      return await query.answer()
    except:
      return None

  elif query.data.startswith("bk.s"):
    data = query.data
    sf = query.data.split(".")[-1]

    reply = reply.text
    if reply.startswith("/search"):
      search = reply.split(" ", 1)[-1]
    else:
      search = reply

    webs = get_webs(sf)
    if webs:
      reply_markup = query.message.reply_markup
      button = reply_markup.inline_keyboard
      button.append(
          [InlineKeyboardButton("🖥 Close 🖥", callback_data="kclose")])
      reply_markup = InlineKeyboardMarkup(button)

      if query.message.reply_to_message:
        try:
          if "/subs" in reply or "/subscribes" in reply or "/queue" in reply:
            return await isubs_handle(client, query)

          else:
            try:
              await query.message.edit_text(
                  f"<i>Searching:- <b>{search}</b> ...</i>")
            except:
              pass

            results = await webs.search(search)

        except:
          return await retry_on_flood(query.edit_message_media)(
              media=InputMediaPhoto(
                  photo,
                  caption=f"<i>No results found :- <b>{search}</b> ....</i>"),
              reply_markup=reply_markup)

        if results:
          button = []
          for result in results:
            c = f"chs|{data}{result['id']}" if "id" in result else f"chs|{data}{hash(result['url'])}"
            searchs[c] = (webs, result)

            button.append(
                [InlineKeyboardButton(result['title'], callback_data=c)])

          if reply.startswith("/subs"):
            button.append(
                [InlineKeyboardButton("🪬 Close 🪬", callback_data="kclose")])

          else:
            button.append(
                [InlineKeyboardButton("🪬 Back 🪬", callback_data="bk.p")])

          await retry_on_flood(query.edit_message_media)(
              media=InputMediaPhoto(
                  photo, f"<i>Select Manga:- <b>{search}</b> ...</i>"),
              reply_markup=InlineKeyboardMarkup(button))

        else:
          await retry_on_flood(query.message.edit_media)(
              media=InputMediaPhoto(
                  photo,
                  caption=f"<i>No results found:- <b>{search}</b> ....</i>"),
              reply_markup=reply_markup)

  try:
    await query.answer()
  except:
    pass




@Bot.on_callback_query(filters.regex("^plugin_"))
async def cb_handler(client, query):
  data = query.data
  data = data.split("_")[-1]
  photo = random.choice(Vars.PICS)
  reply = query.message.reply_to_message

  user_id = reply.from_user.id
  query_user_id = query.from_user.id
  if user_id != query_user_id:
    return await query.answer("This is not for you", show_alert=True)

  reply = reply.text
  if reply.startswith("/search"):
    search = reply.split(" ", 1)[-1]
  else:
    search = reply

  webs = get_webs(data)
  reply_markup = query.message.reply_markup

  try:
    await query.edit_message_text(f"<i>Searching:- <b>{search}</b> ... </i>")
  except:
    pass

  try:
    results = await webs.search(search)
  except:
    return await retry_on_flood(query.edit_message_media)(
        media=InputMediaPhoto(photo, caption=f"<i>No results found:- <b>{search}</b></i>"),
        reply_markup=reply_markup,
    )

  if not results:
    return await retry_on_flood(query.edit_message_media)(
        media=InputMediaPhoto(photo, caption=f"<i>No results found:- <b>{search}</b></i>"),
        reply_markup=reply_markup,
    )

  if results == [] or len(results) < 1:
    return await retry_on_flood(query.edit_message_media)(
        media=InputMediaPhoto(photo, caption=f"<i>No results found:- <b>{search}</b></i>"),
        reply_markup=reply_markup,
    )

  button = []
  for result in results:
    c = f"chs|{data}{result['id']}" if "id" in result else f"chs|{data}{hash(result['url'])}"

    searchs[c] = (webs, result)
    button.append([InlineKeyboardButton(result['title'], callback_data=c)])

  button.append([InlineKeyboardButton("🔥 Back 🔥", callback_data="bk.p")])

  await retry_on_flood(query.edit_message_media
                       )(media=InputMediaPhoto(photo,
                                               caption=f"<i>Select Manga:- <b>{search}</b></i>"),
                         reply_markup=InlineKeyboardMarkup(button))
  try:
    return await query.answer()
  except:
    return


'''
@Bot.on_callback_query()
async def extra_handler(client, query):
  try: 
    await query.answer('This is an old button, please redo the search',
       show_alert=True)
  except:
    pass
'''

db_type = "uts"
name = Vars.DB_NAME


@Bot.on_callback_query(filters.regex("mus"))
async def main_user_panel(_, query):
  user_id = str(query.from_user.id)
  if not user_id in uts:
    uts[user_id] = {}
    sync()

  if not "setting" in uts[user_id]:
    uts[user_id]['setting'] = {}
    sync()

  thumbnali = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)

  if thumbnali:
    thumb = "True" if not thumbnali.startswith("http") else thumbnali
  else:
    thumb = thumbnali
  if banner1:
    banner1 = "True" if not banner1.startswith("http") else banner1
  if banner2:
    banner2 = "True" if not banner2.startswith("http") else banner2

  txt = users_txt.format(
      id=user_id,
      file_name=uts[user_id]['setting'].get("file_name", "None"),
      caption=uts[user_id]['setting'].get("caption", "None"),
      thumb=thumb,
      banner1=banner1,
      banner2=banner2,
      dump=uts[user_id]['setting'].get("dump", "None"),
      type=uts[user_id]['setting'].get("type", "None"),
      megre=uts[user_id]['setting'].get("megre", "None"),
      regex=uts[user_id]['setting'].get("regex", "None"),
      len=uts[user_id]['setting'].get("file_name_len", "None"),
      password=uts[user_id]['setting'].get("password", "None"),
      compress=uts[user_id]['setting'].get("compress", "None"),
  )
  button = [
      [
          InlineKeyboardButton("🪦 File Name 🪦", callback_data="ufn"),
          InlineKeyboardButton("🪦 Caption‌ 🪦", callback_data="ucp")
      ],
      [
          InlineKeyboardButton("🪦 Thumbnali 🪦", callback_data="uth"),
          InlineKeyboardButton("🪦 Regex 🪦", callback_data="uregex")
      ],
      [
          InlineKeyboardButton("⚒ Banner ⚒", callback_data="ubn"),
          InlineKeyboardButton("⚒ Compress ⚒", callback_data="u_compress"),
      ],
      [
          InlineKeyboardButton("⚙️ Password ⚙️", callback_data="upass"),
          InlineKeyboardButton("⚙️ Megre Size ⚙️", callback_data="umegre")
      ],
      [
          InlineKeyboardButton("⚒ File Type ⚒", callback_data="u_file_type"),
      ],
  ]
  if not Vars.CONSTANT_DUMP_CHANNEL:
    button[-1].append(
        InlineKeyboardButton("⚒ Dump Channel ⚒", callback_data="udc"))

  button.append([InlineKeyboardButton("❄️ Close ❄️", callback_data="close")])
  if not thumbnali:
    thumbnali = random.choice(Vars.PICS)

  try:
    await query.edit_message_media(media=InputMediaPhoto(thumbnali,
                                                         caption=txt),
                                   reply_markup=InlineKeyboardMarkup(button))
  except FloodWait as er:
    await asyncio.sleep(er.value)
    await query.edit_message_media(media=InputMediaPhoto(thumbnali,
                                                         caption=txt),
                                   reply_markup=InlineKeyboardMarkup(button))
  except:
    await retry_on_flood(query.edit_message_media
                         )(media=InputMediaPhoto(Vars.PICS[5], caption=txt),
                           reply_markup=InlineKeyboardMarkup(button))

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(filters.regex("^ufn"))
async def file_name_handler(_, query):
  user_id = str(query.from_user.id)
  if not user_id in uts:
    uts[user_id] = {}
    uts[user_id]['setting'] = {}
    sync()

  file_name = uts[user_id]['setting'].get("file_name", None)
  caption = uts[user_id]['setting'].get("caption", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)
  dump = uts[user_id]['setting'].get("dump", None)
  type = uts[user_id]['setting'].get("type", None)
  megre = uts[user_id]['setting'].get("megre", None)
  regex = uts[user_id]['setting'].get("regex", None)
  file_name_len = uts[user_id]['setting'].get("file_name_len", None)
  password = uts[user_id]['setting'].get("password", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  compress = uts[user_id]['setting'].get("compress", "None")

  if thumb:
    thumb = "True" if not thumb.startswith("http") else thumb

  button = [[
      InlineKeyboardButton("📐 sᴇᴛ/ᴄʜᴀɴɢᴇ 📐", callback_data="ufn_change"),
      InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ 🗑️", callback_data="ufn_delete")
  ],
            [
                InlineKeyboardButton("📐 sᴇᴛ/ᴄʜᴀɴɢᴇ ʟᴇɴ 📐",
                                     callback_data="ufn_len_change"),
                InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ ʟᴇɴ 🗑️",
                                     callback_data="ufn_len_delete")
            ], [InlineKeyboardButton("🔙 ʙᴀᴄᴋ 🔙", callback_data="mus")]]

  if query.data == "ufn":
    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb=thumb,
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )
    await retry_on_flood(query.edit_message_caption
                         )(txt, reply_markup=InlineKeyboardMarkup(button))

  elif query.data == "ufn_change":
    await retry_on_flood(
        query.edit_message_caption
    )("<b>📐 Send File Name 📐 \n<u><i>Params:</u></i>\n=><code>{manga_title}</code>: Manga Name \n=> <code>{chapter_num}</code>: Chapter Number</b>"
      )
    try:
      call = await _.listen(user_id=int(user_id), timeout=60)

      uts[user_id]['setting']["file_name"] = call.text
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=call.text,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))

      await call.delete()

      try:
        await query.answer(" Sucessfully Added ")
      except:
        pass

    except asyncio.TimeoutError:
      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))

  elif query.data == "ufn_delete":
    if file_name:
      uts[user_id]['setting']["file_name"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name="None",
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))

      try:
        await query.answer("Sucessfully Deleted")
      except:
        pass
    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)

  elif query.data == "ufn_len_change":
    await retry_on_flood(
        query.edit_message_caption
    )("<b>📐 Send File Name Len 📐\n Example: 15, 20, 50</b>")

    try:
      call = await _.listen(int(user_id), timeout=60)
      try:
        len_ch = int(call.text)
        uts[user_id]['setting']["file_name_len"] = call.text
        sync()

        file_name_len = int(call.text)

        await call.delete()
        await retry_on_flood(query.answer)("🤖 Sucessfully Added 🤖")

      except ValueError:
        await retry_on_flood(query.answer)("📐 ᴛʜɪs ɪs ɴᴏᴛ ᴀ ᴠᴀʟɪᴅ ɪɴᴛᴇɢᴇʀ 📐",
                                           show_alert=True)

    except asyncio.TimeoutError:
      await retry_on_flood(query.answer)("📐 ᴛɪᴍᴇᴏᴜᴛ 📐")

    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb=thumb,
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )

    await retry_on_flood(query.edit_message_caption
                         )(txt, reply_markup=InlineKeyboardMarkup(button))

  elif query.data == "ufn_len_delete":
    if file_name_len:
      uts[user_id]['setting']["file_name_len"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len="None",
          password=password,
          compress=compress,
      )
      if not thumb:
        await retry_on_flood(query.edit_message_media
                             )(media=InputMediaPhoto(random.choice(Vars.PICS),
                                                     txt),
                               reply_markup=InlineKeyboardMarkup(button))

      else:
        await retry_on_flood(query.edit_message_caption
                             )(txt, reply_markup=InlineKeyboardMarkup(button))

      await retry_on_flood(query.answer)("🤖 Sucessfully Deleted 🤖")
    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(filters.regex("^ucp"))
async def caption_handler(_, query):
  user_id = str(query.from_user.id)
  if not user_id in uts:
    uts[user_id] = {}
    sync()

    uts[user_id]['setting'] = {}
    sync()

  file_name = uts[user_id]['setting'].get("file_name", None)
  caption = uts[user_id]['setting'].get("caption", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)
  dump = uts[user_id]['setting'].get("dump", None)
  type = uts[user_id]['setting'].get("type", None)
  megre = uts[user_id]['setting'].get("megre", None)
  regex = uts[user_id]['setting'].get("regex", None)
  file_name_len = uts[user_id]['setting'].get("file_name_len", None)
  password = uts[user_id]['setting'].get("password", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  compress = uts[user_id]['setting'].get("compress", "None")
  if thumb:
    thumb = "True" if not thumb.startswith("http") else thumb

  button = [[
      InlineKeyboardButton("📐 sᴇᴛ/ᴄʜᴀɴɢᴇ 📐", callback_data="ucp_change"),
      InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ 🗑️", callback_data="ucp_delete")
  ], [InlineKeyboardButton("🔙 ʙᴀᴄᴋ 🔙", callback_data="mus")]]

  if query.data == "ucp":
    await retry_on_flood(query.edit_message_reply_markup
                         )(InlineKeyboardMarkup(button))

  elif query.data == "ucp_change":
    button = [[
        InlineKeyboardButton("📐 sᴇᴛ/ᴄʜᴀɴɢᴇ 📐", callback_data="ucp_change"),
        InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ 🗑️", callback_data="ucp_delete")
    ], [InlineKeyboardButton("🔙 ʙᴀᴄᴋ 🔙", callback_data="mus")]]

    await retry_on_flood(
        query.edit_message_caption
    )("<b>📐 Send Caption 📐 \n<u>Note:</u> <blockquote>Use HTML Tags For Bold, Italic,etc</blockquote>\n<u>Params:</u>\n=><code>{manga_title}</code>: Manga Name \n=> <code>{chapter_num}</code>: Chapter Number\n<code>{file_name}</code>: File Name</b>"
      )
    try:
      call = await _.listen(user_id=int(user_id), timeout=60)

      uts[user_id]['setting']["caption"] = call.text
      sync()

      caption = call.text

      await call.delete()

    except asyncio.TimeoutError:
      await retry_on_flood(query.answer)("📐 ᴛɪᴍᴇᴏᴜᴛ 📐", show_alert=True)

    except Exception as err:
      await retry_on_flood(query.answer)(f"📐 {err} 📐", show_alert=True)

    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb=thumb,
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )

    await retry_on_flood(query.edit_message_caption
                         )(txt, reply_markup=InlineKeyboardMarkup(button))

  elif query.data == "ucp_delete":
    if caption:
      uts[user_id]['setting']["caption"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption="None",
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))
      await retry_on_flood(query.answer)("👻 Sucessfully Deleted 👻")

    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(filters.regex("^uth"))
async def thumb_handler(_, query):
  user_id = str(query.from_user.id)
  if not user_id in uts:
    uts[user_id] = {}
    sync()

    uts[user_id]['setting'] = {}
    sync()

  file_name = uts[user_id]['setting'].get("file_name", None)
  caption = uts[user_id]['setting'].get("caption", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)
  dump = uts[user_id]['setting'].get("dump", None)
  type = uts[user_id]['setting'].get("type", "[PDF, CBZ]")
  megre = uts[user_id]['setting'].get("megre", None)
  regex = uts[user_id]['setting'].get("regex", None)
  file_name_len = uts[user_id]['setting'].get("file_name_len", None)
  password = uts[user_id]['setting'].get("password", None)
  thumbnali = uts[user_id]['setting'].get("thumb", None)
  compress = uts[user_id]['setting'].get("compress", "None")
  if thumbnali:
    thumb = "True" if not thumb.startswith("http") else thumb
  else:
    thumb = "None"

  button = [[
      InlineKeyboardButton("📐 SET/CHANGE 📐", callback_data="uth_change"),
      InlineKeyboardButton("📐 CONSTANT 📐", callback_data="uth_constant")
  ],
            [
                InlineKeyboardButton("🗑️ DELETE 🗑️",
                                     callback_data="uth_delete"),
                InlineKeyboardButton("🔙 BACK 🔙", callback_data="mus"),
            ]]

  if query.data == "uth":
    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb=thumb,
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )
    txt += "\n\n<blockquote><b>CONSTANT:- THE PARCTICULAR POSTER OF MANGA WILL ADDED AS FILE THUMBNALI</b></blockquote>"

    if not thumb:
      thumb = random.choice(Vars.PICS)
    try:
      await retry_on_flood(query.edit_message_media
                           )(media=InputMediaPhoto(thumb, caption=txt),
                             reply_markup=InlineKeyboardMarkup(button))
    except:
      await retry_on_flood(query.edit_message_media
                           )(media=InputMediaPhoto(Vars.PICS[2], caption=txt),
                             reply_markup=InlineKeyboardMarkup(button))

  elif query.data == "uth_constant":
    uts[user_id]['setting']["thumb"] = "constant"
    sync()

    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb="constant",
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )
    await retry_on_flood(query.edit_message_caption
                         )(txt, reply_markup=InlineKeyboardMarkup(button))
    await retry_on_flood(query.answer)("🎮 Sucessfully Added 🎮")

  elif query.data == "uth_change":
    await retry_on_flood(
        query.edit_message_caption
    )("<b>📐 Send Thumbnail 📐 \n<u>Note:</u> <blockquote>You Can Send Links or Images Docs.. </blockquote></b>"
      )
    try:
      call = await _.listen(user_id=int(user_id), timeout=60)
      call_type = call.photo or call.document or None
      if call_type:
        call_type = call_type.file_id
        uts[user_id]['setting']["thumb"] = call_type
        sync()

      elif not call_type:
        call_type = call.text
        if call_type.startswith("http"):
          uts[user_id]['setting']["thumb"] = call_type
          sync()

        else:
          await retry_on_flood(query.answer
                               )("📐 ᴛʜɪs ɪs ɴᴏᴛ ᴀ ᴠᴀʟɪᴅ ᴛʜᴜᴍʙɴᴀɪʟ 📐",
                                 show_alert=True)

          return

      #thumb = "True" if not str(call_type).startswith("http") else call_type

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=call_type,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )
      if not call_type:
        call_type = random.choice(Vars.PICS)

      await retry_on_flood(query.edit_message_media
                           )(media=InputMediaPhoto(call_type, txt),
                             reply_markup=InlineKeyboardMarkup(button))

      await call.delete()
      await retry_on_flood(query.answer)("🎮 Sucessfully Added 🎮")
    except asyncio.TimeoutError:
      await retry_on_flood(query.answer)("📐 ᴛɪᴍᴇᴏᴜᴛ 📐", show_alert=True)

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_media
                           )(media=InputMediaPhoto(random.choice(Vars.PICS),
                                                   txt),
                             reply_markup=InlineKeyboardMarkup(button))

    except Exception as err:
      await retry_on_flood(query.answer)(f"📐 {err} 📐", show_alert=True)
      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_media
                           )(media=InputMediaPhoto(random.choice(Vars.PICS),
                                                   txt),
                             reply_markup=InlineKeyboardMarkup(button))

  elif query.data == "uth_delete":
    if thumb:
      uts[user_id]['setting']["thumb"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_media
                           )(media=InputMediaPhoto(Vars.PICS[-2], caption=txt),
                             reply_markup=InlineKeyboardMarkup(button))
    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(filters.regex("^ubn"))
async def banner_handler(_, query):
  user_id = str(query.from_user.id)

  if not user_id in uts:
    uts[user_id] = {}
    sync()

    uts[user_id]['setting'] = {}
    sync()

  file_name = uts[user_id]['setting'].get("file_name", None)
  caption = uts[user_id]['setting'].get("caption", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)
  dump = uts[user_id]['setting'].get("dump", None)
  type = uts[user_id]['setting'].get("type", None)
  megre = uts[user_id]['setting'].get("megre", None)
  regex = uts[user_id]['setting'].get("regex", None)
  file_name_len = uts[user_id]['setting'].get("file_name_len", None)
  password = uts[user_id]['setting'].get("password", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  compress = uts[user_id]['setting'].get("compress", None)
  if thumb:
    thumb = "True" if not thumb.startswith("http") else thumb

  button = [[
      InlineKeyboardButton("📐 Set/Change 1 📐", callback_data="ubn_set1"),
      InlineKeyboardButton("🗑️ Delete 1 🗑️", callback_data="ubn_delete1")
  ],
            [
                InlineKeyboardButton("📐 Set/Change 2 📐",
                                     callback_data="ubn_set2"),
                InlineKeyboardButton("🗑️ Delete 2 🗑️",
                                     callback_data="ubn_delete2")
            ], [InlineKeyboardButton("🔙 ʙᴀᴄᴋ 🔙", callback_data="mus")]]

  if query.data == "ubn":
    await retry_on_flood(query.edit_message_reply_markup
                         )(InlineKeyboardMarkup(button))

  if query.data.startswith("ubn_set"):
    if banner1:
      photo = banner1

    elif banner2:
      photo = banner2

    elif not thumb:
      photo = random.choice(Vars.PICS)
    else:
      photo = None

    if photo:
      await retry_on_flood(query.edit_message_media)(media=InputMediaPhoto(
          photo,
          caption=
          "<b>📐 Send Banner 📐 \n<u>Note:</u> <blockquote>You Can Send Links or Images Docs.. </blockquote></b>"
      ))

    else:
      await retry_on_flood(
          query.edit_message_caption
      )("<b>📐 Send Banner 📐 \n<u>Note:</u> <blockquote>You Can Send Links or Images Docs.. </blockquote></b>"
        )

    try:
      call = await _.listen(user_id=int(user_id), timeout=60)
      call_type = call.photo or call.document or None
      banner_set = ""
      txt = ""

      if call_type:
        banner_set = call.photo.file_id
      elif not call_type:
        banner_set = call.text
        if not banner_set.startswith("http"):
          await retry_on_flood(query.answer)("📐 This Is Not Vaild Banner 📐")
          return

      if query.data == "ubn_set1":
        uts[user_id]['setting']["banner1"] = banner_set
        sync()

        banner = banner_set if banner_set.startswith("http") else "True"
        txt = users_txt.format(
            id=user_id,
            file_name=file_name,
            caption=caption,
            thumb=thumb,
            banner1=banner_set,
            banner2=banner2,
            dump=dump,
            type=type,
            megre=megre,
            regex=regex,
            len=file_name_len,
            password=password,
            compress=compress,
        )

      elif query.data == "ubn_set2":
        uts[user_id]['setting']["banner2"] = banner_set
        sync()

        banner = banner_set if banner_set.startswith("http") else "True"
        txt = users_txt.format(
            id=user_id,
            file_name=file_name,
            caption=caption,
            thumb=thumb,
            banner1=banner1,
            banner2=banner_set,
            dump=dump,
            type=type,
            megre=megre,
            regex=regex,
            len=file_name_len,
            password=password,
            compress=compress,
        )

      await retry_on_flood(query.edit_message_media
                           )(media=InputMediaPhoto(banner_set, caption=txt),
                             reply_markup=InlineKeyboardMarkup(button))
      await retry_on_flood(call.delete)()

    except asyncio.TimeoutError:
      await retry_on_flood(query.answer)("📐 ᴛɪᴍᴇᴏᴜᴛ 📐", show_alert=True)
      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_media
                           )(media=InputMediaPhoto(Vars.PICS[2], caption=txt),
                             reply_markup=InlineKeyboardMarkup(button))

    except Exception as err:
      await retry_on_flood(query.answer)(f"📐 {err} 📐", show_alert=True)
      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_media
                           )(media=InputMediaPhoto(Vars.PICS[0], caption=txt),
                             reply_markup=InlineKeyboardMarkup(button))

  elif query.data == "ubn_delete1":
    if banner1:
      uts[user_id]['setting']["banner1"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1="None",
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))
      await retry_on_flood(query.answer)("🎬 Sucessfully Deleted 🎬")
    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)

  elif query.data == "ubn_delete2":
    if banner2:
      uts[user_id]['setting']["banner2"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2="None",
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))
      await retry_on_flood(query.answer)("🎬 Sucessfully Deleted 🎬")
    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(filters.regex("^udc"))
async def dump_handler(_, query):
  user_id = str(query.from_user.id)
  if not user_id in uts:
    uts[user_id] = {}
    sync()

    uts[user_id]['setting'] = {}
    sync()

  file_name = uts[user_id]['setting'].get("file_name", None)
  caption = uts[user_id]['setting'].get("caption", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)
  dump = uts[user_id]['setting'].get("dump", None)
  type = uts[user_id]['setting'].get("type", None)
  megre = uts[user_id]['setting'].get("megre", None)
  regex = uts[user_id]['setting'].get("regex", None)
  file_name_len = uts[user_id]['setting'].get("file_name_len", None)
  password = uts[user_id]['setting'].get("password", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  compress = uts[user_id]['setting'].get("compress", None)
  if thumb:
    thumb = "True" if not thumb.startswith("http") else thumb

  button = [[
      InlineKeyboardButton("📐 sᴇᴛ/ᴄʜᴀɴɢᴇ 📐", callback_data="udc_change"),
      InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ 🗑️", callback_data="udc_delete")
  ], [InlineKeyboardButton("🔙 ʙᴀᴄᴋ 🔙", callback_data="mus")]]

  if query.data == "udc":
    await retry_on_flood(query.edit_message_reply_markup
                         )(InlineKeyboardMarkup(button))

  elif query.data == "udc_change":
    await retry_on_flood(
        query.edit_message_caption
    )("<b>📐 Send Dump Channel 📐 \n<u>Note:</u> <blockquote>You Can Send Username(without @) or Channel Id or Forward Message from Channel.. </blockquote></b>"
      )
    try:
      call = await _.listen(user_id=int(user_id), timeout=60)
      if call.text:
        dump = call.text
      elif call.forward_from_chat:
        dump = call.forward_from_chat.id

      uts[user_id]['setting']["dump"] = dump
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))
      await call.delete()
      await retry_on_flood(query.answer)("🎬 Sucessfully Added 🎬")

    except asyncio.TimeoutError:
      await retry_on_flood(query.answer)("📐 ᴛɪᴍᴇᴏᴜᴛ 📐")
      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))

    except Exception as err:
      await retry_on_flood(query.answer)(f"📐 {err} 📐", show_alert=True)
      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))

  elif query.data == "udc_delete":
    if dump:
      uts[user_id]['setting']["dump"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump="None",
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )
      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))
      await retry_on_flood(query.answer)("🎲 Sucessfully Deleted 🎲")
    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(filters.regex("^u_file_type"))
async def type_handler(_, query):
  user_id = str(query.from_user.id)
  if not user_id in uts:
    uts[user_id] = {}
    sync()

    uts[user_id]['setting'] = {}
    sync()

  file_name = uts[user_id]['setting'].get("file_name", None)
  caption = uts[user_id]['setting'].get("caption", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)
  dump = uts[user_id]['setting'].get("dump", None)
  type = uts[user_id]['setting'].get("type", None)
  megre = uts[user_id]['setting'].get("megre", None)
  regex = uts[user_id]['setting'].get("regex", None)
  file_name_len = uts[user_id]['setting'].get("file_name_len", None)
  password = uts[user_id]['setting'].get("password", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  compress = uts[user_id]['setting'].get("compress", None)
  if thumb:
    thumb = "True" if not thumb.startswith("http") else thumb

  if not "type" in uts[user_id]['setting']:
    uts[user_id]['setting']["type"] = []
    sync()

  type = uts[user_id].get("setting", {}).get("type", [])

  button = [[]]
  if "PDF" in type:
    button[0].append(
        InlineKeyboardButton("📙 PDF 📙", callback_data="u_file_type_pdf"))
  else:
    button[0].append(
        InlineKeyboardButton("❗PDF ❗", callback_data="u_file_type_pdf"))
  if "CBZ" in type:
    button[0].append(
        InlineKeyboardButton("📂 CBZ 📂", callback_data="u_file_type_cbz"))
  else:
    button[0].append(
        InlineKeyboardButton("❗CBZ ❗", callback_data="u_file_type_cbz"))

  button.append([InlineKeyboardButton("🔙 ʙᴀᴄᴋ 🔙", callback_data="mus")])

  if query.data == "u_file_type":
    await retry_on_flood(query.edit_message_reply_markup
                         )(InlineKeyboardMarkup(button))

  elif query.data == "u_file_type_pdf":
    if "PDF" in type:
      uts[user_id]['setting']["type"].remove("PDF")
      sync()

      button[0][0] = InlineKeyboardButton("❗PDF ❗",
                                          callback_data="u_file_type_pdf")

    else:
      uts[user_id]['setting']["type"].append("PDF")
      sync()

      button[0][0] = InlineKeyboardButton("📙 PDF 📙",
                                          callback_data="u_file_type_pdf")

    type = uts[user_id].get("setting", {}).get("type", "None")
    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb=thumb,
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )
    await retry_on_flood(query.edit_message_caption
                         )(txt, reply_markup=InlineKeyboardMarkup(button))

  elif query.data == "u_file_type_cbz":
    if "CBZ" in type:
      uts[user_id]['setting']["type"].remove("CBZ")
      sync()

      button[0][1] = InlineKeyboardButton("❗CBZ ❗",
                                          callback_data="u_file_type_cbz")

    else:
      uts[user_id]['setting']["type"].append("CBZ")
      sync()

      button[0][1] = InlineKeyboardButton("📂 CBZ 📂",
                                          callback_data="u_file_type_cbz")

    type = uts[user_id].get("setting", {}).get("type", "None")
    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb=thumb,
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )

    await retry_on_flood(query.edit_message_caption
                         )(txt, reply_markup=InlineKeyboardMarkup(button))

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(filters.regex("^umegre"))
async def megre_handler(_, query):
  user_id = str(query.from_user.id)
  if not user_id in uts:
    uts[user_id] = {}
    sync()

    uts[user_id]['setting'] = {}
    sync()

  file_name = uts[user_id]['setting'].get("file_name", None)
  caption = uts[user_id]['setting'].get("caption", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)
  dump = uts[user_id]['setting'].get("dump", None)
  type = uts[user_id]['setting'].get("type", None)
  megre = uts[user_id]['setting'].get("megre", None)
  regex = uts[user_id]['setting'].get("regex", None)
  file_name_len = uts[user_id]['setting'].get("file_name_len", None)
  password = uts[user_id]['setting'].get("password", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  compress = uts[user_id]['setting'].get("compress", None)
  if thumb:
    thumb = "True" if not thumb.startswith("http") else thumb
  button = [[
      InlineKeyboardButton("📐 sᴇᴛ/ᴄʜᴀɴɢᴇ 📐", callback_data="umegre_change"),
      InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ 🗑️", callback_data="umegre_delete")
  ], [InlineKeyboardButton("🔙 ʙᴀᴄᴋ 🔙", callback_data="mus")]]
  if query.data == "umegre":
    await retry_on_flood(query.edit_message_reply_markup
                         )(InlineKeyboardMarkup(button))

  elif query.data == "umegre_change":
    await retry_on_flood(
        query.edit_message_caption
    )("<b>📐 Send Megre Size 📐 \n<u>Note:</u> <blockquote>It's Number For Megre. i.e 2, 3 ,4 ,5,etc </blockquote></b>"
      )
    try:
      call = await _.listen(user_id=int(user_id), timeout=60)
      call_int = int(call.text)

      uts[user_id]['setting']["megre"] = call.text
      sync()

      megre = call.text
      await call.delete()
    except ValueError:
      await retry_on_flood(query.answer)("📐 ᴛʜɪs ɪs ɴᴏᴛ ᴀ ᴠᴀʟɪᴅ ɪɴᴛᴇɢᴇʀ 📐",
                                         show_alert=True)
    except asyncio.TimeoutError:
      await retry_on_flood(query.answer)("📐 ᴛɪᴍᴇᴏᴜᴛ 📐", show_alert=True)
    except Exception as err:
      await retry_on_flood(query.answer)(f"📐 {err} 📐", show_alert=True)

    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb=thumb,
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )

    await retry_on_flood(query.edit_message_caption
                         )(txt, reply_markup=InlineKeyboardMarkup(button))
    await retry_on_flood(query.answer)("🎬 Sucessfully Added 🎬")

  elif query.data == "umegre_delete":
    if megre:
      uts[user_id]['setting']["megre"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre="None",
          regex=regex,
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))
      await retry_on_flood(query.answer)("🎬 Sucessfully Deleted 🎬")
    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(filters.regex("^upass"))
async def password_handler(_, query):
  user_id = str(query.from_user.id)
  if not user_id in uts:
    uts[user_id] = {}
    sync()
    uts[user_id]['setting'] = {}
    sync()

  file_name = uts[user_id]['setting'].get("file_name", None)
  caption = uts[user_id]['setting'].get("caption", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)
  dump = uts[user_id]['setting'].get("dump", None)
  type = uts[user_id]['setting'].get("type", None)
  megre = uts[user_id]['setting'].get("megre", None)
  regex = uts[user_id]['setting'].get("regex", None)
  file_name_len = uts[user_id]['setting'].get("file_name_len", None)
  password = uts[user_id]['setting'].get("password", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  compress = uts[user_id]['setting'].get("compress", None)
  if thumb:
    thumb = "True" if not thumb.startswith("http") else thumb

  button = [[
      InlineKeyboardButton("📐 sᴇᴛ/ᴄʜᴀɴɢᴇ 📐", callback_data="upass_change"),
      InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ 🗑️", callback_data="upass_delete")
  ], [InlineKeyboardButton("🔙 ʙᴀᴄᴋ 🔙", callback_data="mus")]]

  if query.data == "upass":
    await retry_on_flood(query.edit_message_reply_markup
                         )(InlineKeyboardMarkup(button))
  elif query.data == "upass_change":
    await retry_on_flood(
        query.edit_message_caption
    )("<b>📐 Send Password 📐 \n<u>Note:</u> <blockquote>It's Password For PDF.</blockquote></b>"
      )
    try:
      call = await _.listen(user_id=int(user_id), timeout=60)
      password = call.text

      uts[user_id]['setting']["password"] = password
      sync()

      await call.delete()
    except asyncio.TimeoutError:
      await retry_on_flood(query.answer)("📐 ᴛɪᴍᴇᴏᴜᴛ 📐", show_alert=True)
    except Exception as err:
      await retry_on_flood(query.answer)(f"📐 {err} 📐", show_alert=True)

    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb=thumb,
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )

    await retry_on_flood(query.edit_message_caption
                         )(txt, reply_markup=InlineKeyboardMarkup(button))
    await retry_on_flood(query.answer)("🎼 Sucessfully Added 🎼")

  elif query.data == "upass_delete":
    if password:
      uts[user_id]['setting']["password"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password="None",
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))
    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)

  try:
    await query.answer()
  except:
    pass


@Bot.on_callback_query(filters.regex("^uregex"))
async def regex_handler(_, query):
  user_id = str(query.from_user.id)
  if not user_id in uts:
    uts[user_id] = {}
    sync()

    uts[user_id]['setting'] = {}
    sync()

  file_name = uts[user_id]['setting'].get("file_name", None)
  caption = uts[user_id]['setting'].get("caption", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)
  dump = uts[user_id]['setting'].get("dump", None)
  type = uts[user_id]['setting'].get("type", None)
  megre = uts[user_id]['setting'].get("megre", None)
  regex = uts[user_id]['setting'].get("regex", None)
  file_name_len = uts[user_id]['setting'].get("file_name_len", None)
  password = uts[user_id]['setting'].get("password", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  compress = uts[user_id]['setting'].get("compress", None)
  if thumb:
    thumb = "True" if not thumb.startswith("http") else thumb

  button = [[
      InlineKeyboardButton(i, callback_data=f"uregex_set_{i}")
      for i in range(1, 5)
  ], [InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ 🗑️", callback_data="uregex_delete")],
            [InlineKeyboardButton("🔙 ʙᴀᴄᴋ 🔙", callback_data="mus")]]
  if query.data == "uregex":
    await retry_on_flood(query.edit_message_reply_markup
                         )(InlineKeyboardMarkup(button))
  elif query.data.startswith("uregex_set"):
    regex = query.data.split("_")[-1]

    uts[user_id]['setting'][f"regex"] = regex
    sync()

    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb=thumb,
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )

    await retry_on_flood(query.edit_message_caption
                         )(txt, reply_markup=InlineKeyboardMarkup(button))
  elif query.data == "uregex_delete":
    if regex:
      uts[user_id]['setting']["regex"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex="None",
          len=file_name_len,
          password=password,
          compress=compress,
      )

      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=InlineKeyboardMarkup(button))
    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)


@Bot.on_callback_query(filters.regex("^u_compress"))
async def compress_handler(_, query):
  user_id = str(query.from_user.id)
  if not user_id in uts:
    uts[user_id] = {}
    sync()

    uts[user_id]['setting'] = {}
    sync()

  file_name = uts[user_id]['setting'].get("file_name", None)
  caption = uts[user_id]['setting'].get("caption", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  banner1 = uts[user_id]['setting'].get("banner1", None)
  banner2 = uts[user_id]['setting'].get("banner2", None)
  dump = uts[user_id]['setting'].get("dump", None)
  type = uts[user_id]['setting'].get("type", None)
  megre = uts[user_id]['setting'].get("megre", None)
  regex = uts[user_id]['setting'].get("regex", None)
  file_name_len = uts[user_id]['setting'].get("file_name_len", None)
  password = uts[user_id]['setting'].get("password", None)
  thumb = uts[user_id]['setting'].get("thumb", None)
  compress = uts[user_id]['setting'].get("compress", None)
  thumb = "True" if thumb and not thumb.startswith("http") else thumb

  def get_button():
    compress = uts[user_id]['setting'].get("compress", None)
    compress = int(compress) if compress else 2
    button = []
    for i in range(0, 105, 5):
      if i == int(compress):
        button.append(
            InlineKeyboardButton(f"✔️ {i} ✔️",
                                 callback_data=f"u_compress_set_{i}"))
      else:
        button.append(
            InlineKeyboardButton(f"{i}", callback_data=f"u_compress_set_{i}"))

    button = [button[x:x + 5] for x in range(0, len(button), 5)]
    button.append([
        InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ 🗑️", callback_data="u_compress_delete")
    ])

    button.append([InlineKeyboardButton("🔙 ʙᴀᴄᴋ 🔙", callback_data="mus")])
    return InlineKeyboardMarkup(button)

  if query.data == "u_compress":
    await retry_on_flood(query.edit_message_reply_markup)(get_button())
  elif query.data.startswith("u_compress_set"):
    compress = query.data.split("_")[-1]
    uts[user_id]['setting']["compress"] = compress
    sync()

    txt = users_txt.format(
        id=user_id,
        file_name=file_name,
        caption=caption,
        thumb=thumb,
        banner1=banner1,
        banner2=banner2,
        dump=dump,
        type=type,
        megre=megre,
        regex=regex,
        len=file_name_len,
        password=password,
        compress=compress,
    )
    await retry_on_flood(query.edit_message_caption)(txt,
                                                     reply_markup=get_button())
    await retry_on_flood(query.answer)(" Sucessfully Added ")

  elif query.data == "u_compress_delete":
    if compress:
      uts[user_id]['setting']["compress"] = None
      sync()

      txt = users_txt.format(
          id=user_id,
          file_name=file_name,
          caption=caption,
          thumb=thumb,
          banner1=banner1,
          banner2=banner2,
          dump=dump,
          type=type,
          megre=megre,
          regex=regex,
          len=file_name_len,
          password=password,
          compress="None",
      )
      await retry_on_flood(query.edit_message_caption
                           )(txt, reply_markup=get_button())
      await retry_on_flood(query.answer)(" Sucessfully Deleted ")
    else:
      await retry_on_flood(query.answer)("📐 𝒀𝒐𝒖 𝒉𝒂𝒔 𝒏𝒐𝒕 𝑺𝒆𝒕 𝑰𝒕 ! 📐",
                                         show_alert=True)
