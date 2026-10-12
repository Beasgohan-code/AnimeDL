from bot import Bot, Vars, logger
from Tools.db import *
from .storage import web_data, clean, retry_on_flood, get_episode_number, queue, get_webs
from .wks import send_manga_chapter

import asyncio
import os
import shutil


async def get_updates_manga():
  updates = []

  subs_chapters = get_all_subs()
  for sf, data in subs_chapters.items():
    webs = get_webs(sf)
    if not webs:
      continue
    try:
      for url, value in data.items():
        value['url'] = url
        chapters = await webs.get_chapters(value, page=1)
        chapters = webs.iter_chapters(chapters, page=1)
        
        if chapters is None or len(chapters) == 0:
          continue
        
        if 'lastest_chapter' in value:
          lastest_sub_episode = get_episode_number(value['lastest_chapter'])
          lastest_webs_episode = get_episode_number(chapters[0]['title'])  # from chapters
          
          if lastest_sub_episode is None or lastest_webs_episode is None:
            if chapters[0] != value['lastest_chapter']:
              try:
                pictures = await webs.get_pictures(chapters[0]['url'], chapters[0])
              except:
                pictures = None
              
              if pictures and len(pictures) != 0:
                chapters[0]['pictures_list'] = pictures
                chapters[0]['webs'] = sf
                chapters[0]['users'] = data[url]['users']
                chapters[0]['manga_url'] = url
                
                updates.append(chapters[0])
                
                logger.info(
                  f"New Chapter Found: {chapters[0]['title']} - {chapters[0]['manga_title']}"
                )
                await asyncio.sleep(2)
                continue
          
          try:
            lastest_sub_episode = int(lastest_sub_episode)
          except:
            lastest_sub_episode = float(lastest_sub_episode)
          
          try:
            lastest_webs_episode = int(lastest_webs_episode)
          except:
            lastest_webs_episode = float(lastest_webs_episode)
          
          if lastest_sub_episode == lastest_webs_episode:
            continue
          elif lastest_sub_episode > lastest_webs_episode:
            continue
          
          try:
            for chapter in list(reversed(chapters)):
              lastest_webs_episode = get_episode_number(chapter['title'])  # from webs
              
              if lastest_webs_episode is None:
                continue
              
              try:
                lastest_webs_episode = int(lastest_webs_episode)
              except:
                lastest_webs_episode = float(lastest_webs_episode)
              
              if lastest_sub_episode == lastest_webs_episode:
                continue
              elif lastest_sub_episode > lastest_webs_episode:
                continue
              
              #     database(small) < webs(large)
              elif lastest_sub_episode < lastest_webs_episode:
                try:
                  pictures = await webs.get_pictures(chapter['url'], data)
                  
                  if pictures and len(pictures) != 0:
                    chapter['pictures_list'] = pictures
                    chapter['webs'] = sf
                    chapter['users'] = data[url]['users']
                    chapter['manga_url'] = url

                    logger.info(
                        f"New Chapter Found: {chapter['title']} - {chapter['manga_title']}"
                    )

                    updates.append(chapter)
                    await asyncio.sleep(3)
                except:
                  await asyncio.sleep(3)
              
          except Exception as err:
            logger.exception(err)
            continue
        else:
          try:
            pictures = await webs.get_pictures(chapters[0]['url'], chapters[0])
          except:
            pictures = None
          
          if pictures and len(pictures) != 0:
            chapters[0]['pictures_list'] = pictures
            chapters[0]['webs'] = sf
            chapters[0]['users'] = data[url]['users']
            chapters[0]['manga_url'] = url
            
            updates.append(chapters[0])
            
            logger.info(
              f"Else New Chapter Found: {chapters[0]['title']} - {chapters[0]['manga_title']}"
            )
            await asyncio.sleep(2)
    except Exception as err:
      logger.exception(err)

  
  return updates


async def send_updates(data):
  try:
    await Bot.send_message(
        Vars.UPDATE_CHANNEL,
        f"<b><i>Updates: {data['manga_title']} - {data['title']}\n\nUrl: {data['url']}</i></b>"
    )
  except:
    pass

  episode_number = str(get_episode_number(data['title']))
  webs = get_webs(data['webs'])

  for user_id in data['users']:
    await send_manga_chapter(data,
                             picturesList=data['pictures_list'],
                             user=None,
                             sts=None,
                             user_id=user_id,
                             webs=webs,
                             worker_id=123)

  await save_lastest_chapter(data)


async def main_updates():
  while True:
    min = 10
    try:
      logger.info("Getting Updates...")

      updates = await get_updates_manga()
      logger.info(f"Got {len(updates)} updates")
      for data in updates:
        try:
          await send_updates(data)
        except Exception as err:
          logger.exception(err)
          continue
    except Exception as err:
      logger.exception(f"L - {err}")
    finally:
      try:
        await remove_expired_users()
      except:
        logger.info("Passing ")

      logger.info(f"Sleeping for {min} min...")
      await asyncio.sleep(min * 60)
