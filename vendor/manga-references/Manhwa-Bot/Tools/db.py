"""
format:
_id: Vars.DB_NAME
user_id: {
     "subs": {
        "ck": [],
        "as": [],
        ................
        ................
     },
     setting: {
        "file_name": "",
        "caption": "",
        ................
        .................
     }
}
.................
.................
.................
.................
"""

from loguru import logger
from pymongo import MongoClient
from bot import Vars, Bot
import time, asyncio

client = MongoClient(Vars.DB_URL)
db = client[Vars.DB_NAME]
users = db["users"]
acollection = db['premium']

uts = users.find_one({"_id": Vars.DB_NAME})

if not uts:
    uts = {'_id': Vars.DB_NAME}
    users.insert_one(uts)

pts = acollection.find_one({"_id": Vars.DB_NAME})
if not pts:
    pts = {'_id': Vars.DB_NAME}
    acollection.insert_one(pts)


def sync(name=None, type=None):
    users.replace_one({'_id': Vars.DB_NAME}, uts)

def premuim_sync():
    acollection.replace_one({'_id': Vars.DB_NAME}, pts)

async def add_premium(user_id, time_limit_days):
    user_id = str(user_id)
    expiration_timestamp = int(time.time()) + time_limit_days * 24 * 60 * 60
    premium_data = {
        "expiration_timestamp": expiration_timestamp,
    }
    pts[user_id] = premium_data
    premuim_sync()


async def remove_premium(user_id):
    user_id = str(user_id)
    if user_id in pts:
        del pts[user_id]
        premuim_sync()


async def remove_expired_users():
    current_timestamp = int(time.time())
    expired_users = [user for user, data in pts.items() if data.get("expiration_timestamp", 0) < current_timestamp]
    for expired_user in expired_users:
        try:
            user_id = int(expired_user)
            await remove_premium(user_id)
        except:
            pass


async def get_all_premuim():
    for i in acollection.find():
        for j in i:
            try:
                yield int(j), i[j]
            except:
                continue


async def premium_user(user_id=None):
    user_id = str(user_id)
    return pts[user_id] if user_id in pts else None


def get_users(user_id=None):
    users_id_list = []
    for i in users.find():
        for j in i:
            try:
                if user_id and int(j) == int(user_id):
                    try:
                        if str(user_id) in uts:
                            return uts[str(user_id)]
                        else:
                            return None
                    except:
                        pass
                else:
                    users_id_list.append(int(j))
            except:
                continue

    return users_id_list


async def add_sub(user_id, data, web: str, chapter=None):
    user_id = str(user_id)

    if user_id not in uts:
        uts[user_id] = {}
        sync()

    if "subs" not in uts[user_id]:
        uts[user_id]["subs"] = {}
        sync()

    if web not in uts[user_id]["subs"]:
        uts[user_id]["subs"][web] = []
        sync()

    if data not in uts[user_id]["subs"][web]:
        uts[user_id]["subs"][web].append(data)
        sync()


def get_subs(user_id, manga_url=None, web=None):
    user_id = str(user_id)
    subsList = []

    if user_id not in uts:
        uts[user_id] = {}
        sync()

    if "subs" not in uts[user_id]:
        uts[user_id]["subs"] = {}
        sync()

    user_info = get_users(user_id)
    if user_info:
        if web and web in user_info["subs"]:
            if manga_url:
                return True if any(data['url'] == manga_url for data in user_info["subs"][web]) else None

            else:
                subsList.extend(user_info['subs'][web])
        else:
            for j in user_info["subs"].values():
                if manga_url:
                    return True if any(url['url'] == manga_url for url in j) else None
                else:
                    subsList.extend(j)

    return subsList


async def delete_sub(user_id, manga_url=None, web=None):
    """
    This function Use to Delete Subscried Manga From User..
    params:
     user_id : required 
     manga_url : optional => If manga_url is not given then it will delete all subscried manga from user, if web given then it will delete all subscried manga from user in that web
     web : optional => If web is not given then it will delete all subscried manga from user
    extra:
       if the len of subscried manga is 0 then it will delete it from database
    """
    user_id = str(user_id)
    user_info = get_users(user_id)

    if "subs" not in user_info:
        return

    if user_info:
        if web and web in user_info['subs']:
            web_subs = user_info['subs'][web]

            if not manga_url:
                del uts[user_id]['subs'][web]
                sync()

            for data in user_info['subs'][web]:
                if manga_url and data.get('url') == manga_url:
                    if len(uts[user_id]['subs'][web]) == 0:
                        del uts[user_id]['subs'][web]
                        sync()
                    else:
                        uts[user_id]['subs'][web].remove(data)
                        sync()

        else:
            for website, web_subs in user_info['subs'].items():
                for data in web_subs:
                    if data.get('url') == manga_url:
                        if len(uts[user_id]['subs'][website]) == 0:
                            del uts[user_id]['subs'][website]
                            sync()
                        else:
                            uts[user_id]['subs'][website].remove(data)
                            sync()


def get_all_subs():
    """
    return format => {
            web(Webs.sf): {
                 "url" (manga_url): {
                       "title": manga_title,
                       "lastest_chapter": lastest_chapter, at int or float or None
                       "users": [user_id, user_id, user_id, .................],
                }
            }
            ...............
            ...............
        }
    """
    subs_list = {}

    users_list = [j for i in users.find() for j in i]
    users_list.remove('_id')

    for user_id in users_list:
        if user_id in uts:
            if "subs" in uts[user_id]:
                for j, i in uts[user_id]['subs'].items():
                    if j not in subs_list:
                        subs_list[j] = {}

                    for data in i:
                        if data['url'] not in subs_list[j]:
                            subs_list[j][data['url']] = {
                                "title": data['title'],
                                "users": []
                            }

                            if 'lastest_chapter' in data:
                                subs_list[j][
                                    data['url']]['lastest_chapter'] = data[
                                        'lastest_chapter']

                        if user_id not in subs_list[j][data['url']]['users']:
                            subs_list[j][data['url']]['users'].append(user_id)

    return subs_list


async def save_lastest_chapter(data):
    """
    Update the latest chapter for subscribed manga and clean up old field

    Args:
        data: {
            'url': manga_url, 
            'webs': website identifier,
            'users': [user_id1, user_id2, ...],
            'title': latest chapter name,
            'manga_url': manga URL,
            'manga_title': manga title,
            ...
        }
    """
    for user_id in data['users']:
        try:
            # Check if user exists and has subscriptions
            if user_id not in uts or "subs" not in uts[user_id] or data[
                    'webs'] not in uts[user_id]['subs']:
                continue

            subscribed_manga = uts[user_id]['subs'][data['webs']]
            updated = False

            for index, manga_data in enumerate(subscribed_manga):
                # Check if this is the manga we're looking for
                if (manga_data.get('url') == data['manga_url']
                        or manga_data.get('title') == data.get('manga_title')):

                    # Remove old 'last_chapter' field if it exists
                    if "last_chapter" in manga_data:
                        del manga_data["last_chapter"]

                    # Update with new 'lastest_chapter' field
                    if manga_data.get('lastest_chapter') != data['title']:
                        manga_data['lastest_chapter'] = data['title']
                        
                        if data['web'] == "ck":
                            if 'slug' in data:
                                manga_data['slug'] = data.get('slug', None)
                            if 'hid' in data:
                                manga_data['hid'] = data.get('hid', None)
                            
                        subscribed_manga[index] = manga_data
                        
                        updated = True
                        break  # Found and updated, break the loop

            # Only sync if actually updated
            if updated:
                uts[user_id]['subs'][data['webs']] = subscribed_manga
                #logger.info(f"{user_id} => {subscribed_manga}")
                sync()

        except Exception as e:
            print(f"Error updating user {user_id}: {str(e)}")
