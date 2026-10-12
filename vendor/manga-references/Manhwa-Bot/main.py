from TG.wks import Bot, worker, asyncio, Vars, remove_expired_users
from TG.auto import main_updates
from Tools.my_token import expired_token_

import os, shutil
from bot import Bot 
from Tools.cworker import worker

folder_path = "Process"
if os.path.exists(folder_path) and os.path.isdir(folder_path):
  shutil.rmtree(folder_path)

async def main_exp_():
  while True:
    try:
      await remove_expired_users()
      expired_token_()
    except:
      pass
    finally:
      await asyncio.sleep(3600)


if __name__ == "__main__":
  loop = asyncio.get_event_loop()
  for i in range(20):
    loop.create_task(worker(i))

  loop.create_task(main_updates())
  if Vars.SHORTENER:
    loop.create_task(main_exp_())

  Bot.run()
  
