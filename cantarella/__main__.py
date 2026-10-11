# AnimeDL — compatibility entry point.
# The unified entry point lives in main.py; `python -m cantarella` is kept
# working for tools that reference it. IMPORTANT: main.main() is a coroutine
# factory — it must be awaited or the process exits instantly (this exact
# bug once made every watchdog restart silently kill the bot).
import asyncio

import main

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main.main())
    loop.close()
