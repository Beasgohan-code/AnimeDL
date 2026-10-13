from pyrogram import Client
from pyrogram.types import BotCommand

async def set_bot_commands(client: Client):
    """Automatically register the unified AnimeDL command menu
    (anime downloader core + leech engine) on startup."""
    commands = [
        # ── Anime core ──
        BotCommand("start", "🚀 Sᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ"),
        BotCommand("help", "📖 Hᴇʟᴘ ᴀɴᴅ ғᴇᴀᴛᴜʀᴇs"),
        BotCommand("favorites", "❤ Vɪᴇᴡ ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇ ᴀɴɪᴍᴇ (Aᴅᴍɪɴ)"),
        BotCommand("ongoing", "📆 Vɪᴇᴡ ᴛᴏᴅᴀʏ's ᴀɴɪᴍᴇ sᴄʜᴇᴅᴜʟᴇ"),
        BotCommand("autodel", "🕒 Sᴇᴛ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇ (Aᴅᴍɪɴ)"),
        BotCommand("sources", "🩺 Cʜᴇᴄᴋ ᴡʜɪᴄʜ ᴀɴɪᴍᴇ ꜱᴏᴜʀᴄᴇꜱ ᴀʀᴇ ᴀʟɪᴠᴇ (Aᴅᴍɪɴ)"),
        BotCommand("diag", "🔬 Tᴇꜱᴛ ᴛʜᴇ ғᴜʟʟ ᴅᴏᴡɴʟᴏᴀᴅ ᴘɪᴘᴇʟɪɴᴇ (Aᴅᴍɪɴ)"),
        BotCommand("manage", "⚙️ Mᴀɴᴀɢᴇ ʙᴏᴛ sᴇᴛᴛɪɴɢs (Aᴅᴍɪɴ)"),
        BotCommand("stats", "📊 Aɴɪᴍᴇ ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs (Aᴅᴍɪɴ)"),
        BotCommand("maplist", "📋 Vɪᴇᴡ ᴀɴɪᴍᴇ ᴍᴀᴘᴘɪɴɢs (Aᴅᴍɪɴ)"),
        BotCommand("setmap", "📍 Sᴇᴛ ᴀɴɪᴍᴇ ᴍᴀᴘᴘɪɴɢ (Aᴅᴍɪɴ)"),
        BotCommand("unmap", "❌ Rᴇᴍᴏᴠᴇ ᴀɴɪᴍᴇ ᴍᴀᴘᴘɪɴɢ (Aᴅᴍɪɴ)"),
        BotCommand("admins", "🛡️ Vɪᴇᴡ ʙᴏᴛ ᴀᴅᴍɪɴɪsᴛʀᴀᴛᴏʀs (Aᴅᴍɪɴ)"),
        BotCommand("users", "👥 Vɪᴇᴡ ᴛᴏᴛᴀʟ ᴜsᴇʀs (Aᴅᴍɪɴ)"),
        # ── Manga engine ──
        BotCommand("manga", "📖 ꜰᴇᴀʀᴄɦ ᴍᴀɴɢᴀ/ᴍᴀɴɦᴡᴀ – 15 ꜰᴏᴜʀᴄᴇꜰ"),
        BotCommand("mrandom", "🎲 ʀᴀɴᴅᴏᴍ ꜰᴇʀɪᴇꜰ → ᴄɪᴀᴘᴛᴇʀꜰ"),
        BotCommand("usettings", "⚙️ ᴜꜰᴇʀ ꜰᴇᴛᴛɪɴɢꜰ – ꜰᴏʀᴍᴀᴛ + 18+"),
        BotCommand("premium", "💎 ᴘʀᴇᴍɪᴜᴍ ꜰᴛᴀᴛᴜꜰ"),
        BotCommand("msubscribe", "\U0001f514 \u1d0f\u1d0f\ua730\ua730\u1d0f\u1d1c \u1d00 \ua730\u1d07\u0280\u026a\u1d07\ua730 — ɴᴇᴡ ᴄɪᴀᴘᴛᴇʀ ᴀꜰᴇʀᴛꜰ"),
        BotCommand("msubs", "📚 ꜰᴇᴇ ᴍᴀɴɢᴀ ᴜ ᴄɪᴀꜰꜰ ᴛʀᴀᴄᴋɪɴɢ"),
        BotCommand("munsub", "🗑️ ᴜɴꜰᴏꜰꜰᴏw ᴀ ꜰᴇʀɪᴇꜰ"),
        BotCommand("mcheck", "🔃 ᴄʜᴇᴄᴋ ᴍᴀɴɢᴀ ᴜᴘᴅᴀᴛᴇꜱ ɴᴏᴡ"),
        BotCommand("minterval", "⏱ ꜱᴇᴛ ʏᴏᴜʀ ᴄʜᴀᴘᴛᴇʀ-ᴄʜᴇᴄᴋ ɪɴᴛᴇʀᴠᴀʟ"),
        BotCommand("mchannel", "📢 ᴘᴏꜱᴛ ɴᴇᴡ ᴄʜᴀᴘᴛᴇʀꜱ ᴛᴏ ᴀ ᴄʜᴀɴɴᴇʟ"),
        BotCommand("mexport", "📤 ʙᴀᴄᴋᴜᴘ ʏᴏᴜʀ ꜰᴏʟʟᴏᴡꜱ (ᴊꜱᴏɴ)"),
        BotCommand("mimport", "📥 ʀᴇꜱᴛᴏʀᴇ ꜰᴏʟʟᴏᴡꜱ ꜰʀᴏᴍ ʙᴀᴄᴋᴜᴘ"),
        BotCommand("msearch", "🔎 ꜰᴇᴀʀᴄɦ ᴏɴ ᴏɴᴇ ꜰᴏᴜʀᴄᴇ"),
        BotCommand("minfo", "ℹ️ ᴍᴀɴɢᴀ ᴅᴇᴛᴀɪꜰꜰ ᴄᴀʀᴅ"),
        BotCommand("mqueue", "🧾 ʀᴜɴɴɪɴɢ ᴍᴀɴɢᴀ ꜁ᴏʙꜰ"),
        BotCommand("mclean", "🧹 ᴄꜰᴇᴀʀ ᴍᴀɴɢᴀ ꜰᴇꜰꜰɪᴏɴ"),
        BotCommand("mrefresh", "🔄 ʀᴇ-ɡᴇᴛ ꜰᴀꜰᴛ ᴄɪᴀᴘᴛᴇʀ"),
        BotCommand("mpost", "🖼 ꜰɪᴀʀᴀ⦀ꜰᴇ ᴄᴏᴛᴇʀ ᴘᴏꜰᴛ"),
        # ── Leech engine ──
        BotCommand("tupload", "📥 Lᴇᴇᴄʜ ᴀ ʟɪɴᴋ ᴛᴏ Tᴇʟᴇɢʀᴀᴍ"),
        BotCommand("gdupload", "♻️ Mɪʀʀᴏʀ ᴛᴏ Gᴏᴏɢʟᴇ Dʀɪᴠᴇ"),
        BotCommand("drupload", "📁 Uᴘʟᴏᴀᴅ ᴀ ʟᴏᴄᴀʟ ᴅɪʀᴇᴄᴛᴏʀʏ"),
        BotCommand("ytupload", "🏮 Dᴏᴡɴʟᴏᴀᴅ ᴡɪᴛʜ YT-DLP"),
        BotCommand("glupload", "📸 Dᴏᴡɴʟᴏᴀᴅ ɪᴍᴀɢᴇ ɢᴀʟʟᴇʀɪᴇs"),
        BotCommand("formats", "🎞️ Lɪsᴛ ғᴏʀᴍᴀᴛs ғᴏʀ ᴀ URL"),
        BotCommand("preview", "👁️ Pʀᴇᴠɪᴇᴡ ᴀ ɢᴀʟʟᴇʀʏ (ᴅʀʏ ʀᴜɴ)"),
        BotCommand("settings", "⚙️ Aʟʟ sᴇᴛᴛɪɴɢs — ᴀɴɪᴍᴇ + ʟᴇᴇᴄʜ"),
        BotCommand("setname", "✏️ Sᴇᴛ ᴄᴜsᴛᴏᴍ ғɪʟᴇɴᴀᴍᴇ"),
        BotCommand("autorename", "🏷️ Aᴜᴛᴏ-ʀᴇɴᴀᴍᴇ ᴛᴇᴍᴘʟᴀᴛᴇ"),
        BotCommand("alias", "🔀 Cʀᴇᴀᴛᴇ ᴄᴏᴍᴍᴀɴᴅ ᴀʟɪᴀs"),
        BotCommand("aliases", "📋 Lɪsᴛ ᴄᴏᴍᴍᴀɴᴅ ᴀʟɪᴀsᴇs"),
        BotCommand("unalias", "❌ Rᴇᴍᴏᴠᴇ ᴄᴏᴍᴍᴀɴᴅ ᴀʟɪᴀs"),
        BotCommand("format", "🎬 Sᴇᴛ YT-DLP Qᴜᴀʟɪᴛʏ"),
        BotCommand("speed", "⚡ Sᴇᴛ ʙᴀɴᴅᴡɪᴅᴛʜ ʟɪᴍɪᴛ"),
        BotCommand("queue", "📋 Vɪᴇᴡ ᴅᴏᴡɴʟᴏᴀᴅ ǫᴜᴇᴜᴇ"),
        BotCommand("cancel", "🚫 Cᴀɴᴄᴇʟ ᴄᴜʀʀᴇɴᴛ ʟᴇᴇᴄʜ ᴛᴀsᴋ"),
        BotCommand("cancel_all", "🗑️ Cᴀɴᴄᴇʟ & ᴄʟᴇᴀʀ ǫᴜᴇᴜᴇ"),
        BotCommand("sysstats", "📊 Sʏsᴛᴇᴍ sᴛᴀᴛɪsᴛɪᴄs"),
        BotCommand("status", "📡 Aᴄᴛɪᴠᴇ ʟᴇᴇᴄʜ ᴛᴀsᴋ + Qᴜᴇᴜᴇ"),
        BotCommand("screenshot", "📸 Sᴄʀᴇᴇɴsʜᴏᴛ ᴛᴏᴏʟ"),
        BotCommand("rss_add", "📰 Aᴅᴅ RSS ᴀᴜᴛᴏ-ᴅᴏᴡɴʟᴏᴀᴅ ғᴇᴇᴅ"),
        BotCommand("rss_list", "📋 Lɪsᴛ RSS ғᴇᴇᴅs"),
        BotCommand("rss_remove", "❌ Rᴇᴍᴏᴠᴇ RSS ғᴇᴇᴅ"),
        BotCommand("rss_check", "🔍 Cʜᴇᴄᴋ RSS ғᴇᴇᴅs ɴᴏᴡ"),
        # ── Owner / maintenance ──
        BotCommand("ping", "🏓 Cʜᴇᴄᴋ ʙᴏᴛ ʟᴀᴛᴇɴᴄʏ"),
        BotCommand("anime", "📺 Aɴɪᴍᴇ ɪɴғᴏ ᴄᴀʀᴅ (AɴɪLɪsᴛ)"),
        BotCommand("nextep", "⏰ Nᴇxᴛ ᴇᴘɪsᴏᴅᴇ ᴄᴏᴜɴᴛᴅᴏᴡɴ"),
        BotCommand("history", "🕘 Cᴏɴᴛɪɴᴜᴇ ᴡᴀᴛᴄʜɪɴɢ"),
        BotCommand("health", "❇️ Fᴜʟʟ ʀᴇʟɪᴀʙɪʟɪᴛʏ ᴅᴀꜱʜʙᴏᴀʀᴅ (Aᴅᴍɪɴ)"),
        BotCommand("setrestart", "⏰ Sᴄʜᴇᴅᴜʟᴇ ᴅᴀɪʟʏ ʀᴇsᴛᴀʀᴛ (Oᴡɴᴇʀ)"),
        BotCommand("restart", "🔄 Rᴇsᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ (Aᴅᴍɪɴ)"),
        BotCommand("broadcast", "📡 Bʀᴏᴀᴅᴄᴀsᴛ ᴀ ᴍᴇssᴀɢᴇ (Aᴅᴍɪɴ)"),
    ]
    try:
        await client.set_bot_commands(commands)
        print("Bot commands setup successfully!")
    except Exception as e:
        print(f"Failed to setup bot commands: {e}")
