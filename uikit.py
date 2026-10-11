# ============================================================================
#  AnimeDL — UI Kit (rich formatting layer)
# ============================================================================
#  Modern message design system built on `richgram` (by Badmunda05), which
#  renders Telegram Bot API 10.3 rich messages — native headings, tables,
#  expandable sections and styled buttons — with an automatic plain-HTML
#  fallback whenever a client or delivery path can't do rich.
#
#  RULES for using this module:
#    • Text containing rich-only tags (<h1-6>, <table>, <details>,
#      <tg-button>, …) MUST be delivered through uikit.send / uikit.edit /
#      uikit.reply — never through raw edit_text / reply_text.
#    • Classic-safe tags (<b>, <i>, <code>, <blockquote>, <a>, <pre>) may go
#      anywhere, as before.
# ============================================================================

import html as _html

import config
import richgram
from richgram import (
    RICH_AVAILABLE,
    rich_heading,
    rich_kv_table,
    rich_details,
    rich_note,
    rich_footer,
    rich_button,
    rich_button_row,
    rich_esc,
)

# Re-export for callers
RICH = RICH_AVAILABLE
esc = rich_esc

BAR_FILL = "▰"
BAR_EMPTY = "▱"
BRAND = "AnimeDL"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def bar(percent: float, width: int = 12) -> str:
    """Unicode progress bar (no HTML — safe to use anywhere)."""
    percent = max(0.0, min(100.0, float(percent)))
    filled = round(width * percent / 100)
    return BAR_FILL * filled + BAR_EMPTY * (width - filled)


def heading(text: str, level: int = 2) -> str:
    return rich_heading(text, level=level)


def kv(pairs) -> str:
    """Key/value table from an iterable of (label, value) pairs."""
    return rich_kv_table([(k, v) for k, v in pairs])


def details(summary: str, body: str, open: bool = False) -> str:
    return rich_details(summary, body, open=open)


def note(text: str, expandable: bool = False) -> str:
    return rich_note(text, expandable=expandable)


def footer(extra: str = "") -> str:
    tail = f" • {extra}" if extra else ""
    return rich_footer(f"{BRAND} v{config.VERSION}{tail}")


def code(value) -> str:
    return f"<code>{_html.escape(str(value), quote=False)}</code>"


def bold(value) -> str:
    return f"<b>{_html.escape(str(value), quote=False)}</b>"


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------
def btn(label: str, callback_data: str = None, url: str = None,
        style: str = "primary") -> str:
    """One styled button fragment. style: primary|success|danger|link|default."""
    if callback_data is not None:
        return rich_button(label, callback_data=callback_data, style=style)
    return rich_button(label, url=url, style=style)


def btn_row(*buttons_) -> str:
    return rich_button_row(*buttons_)


def buttons(*rows) -> str:
    """Full button block from rows of btn() fragments."""
    return "".join(rich_button_row(*row) for row in rows)


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------
def panel(title: str, *sections, level: int = 2, with_footer: bool = True) -> str:
    """Heading + sections + brand footer."""
    parts = [heading(title, level=level)]
    parts.extend(s for s in sections if s)
    if with_footer:
        parts.append(footer())
    return "".join(parts)


def progress_panel(head_html: str, percentage: float, speed: str, eta: str,
                   done: str, left: str, engine: str,
                   sys_html: str = "") -> str:
    """Live download/upload progress layout."""
    pct_html = (
        f"<blockquote><code>{bar(percentage, 14)}</code>  "
        f"<b>{percentage:.1f}%</b></blockquote>"
    )
    rows = kv([
        ("⚡ Speed", code(speed)),
        ("⏳ ETA", code(eta)),
        ("📦 Size", f"{code(done)} / {code(left)}"),
        ("🔧 Engine", code(engine)),
    ])
    return f"{head_html}{pct_html}{rows}{sys_html}"


def ping_panel(latency_ms: float, uptime: str, quality: str, sys_pairs) -> str:
    body = (
        heading("🏓 Pong!", level=3)
        + f"<blockquote>{code(f'{latency_ms:.2f} ms')} · {bold(quality)}</blockquote>"
        + kv([("⏱️ Uptime", code(uptime)), ("🤖 Version", code(f"v{config.VERSION}"))])
        + kv(list(sys_pairs))
    )
    return panel("Latency", body, level=3)


def status_panel(active_html: str, queue_html: str) -> str:
    return panel("📡 Task Status", active_html, queue_html, level=3)


def queue_panel(items_html: str, total: int) -> str:
    body = heading("📋 Download Queue", level=3) + items_html
    if total:
        body += note(f"Total queued: {total}")
    return panel("Queue", body, level=3)


def stats_panel(bot_pairs, storage_html: str, sys_pairs, specs_pairs) -> str:
    body = (
        heading("📊 Statistics", level=3)
        + kv(list(bot_pairs))
        + storage_html
        + details("🖥️ System", kv(list(sys_pairs)))
        + details("⚙️ Specs", kv(list(specs_pairs)))
    )
    return panel("AnimeDL", body, level=3)


def summary_panel(summary_pairs, extra_html: str = "") -> str:
    body = heading("✅ Task Complete", level=3) + kv(list(summary_pairs)) + extra_html
    return panel("Done", body, level=3)


def error_panel(context: str, err, hint: str = "") -> str:
    body = (
        heading("⚠️ Error", level=3)
        + note(f"{context}")
        + f"<pre>{_html.escape(str(err))[:1500]}</pre>"
        + (note(hint) if hint else "")
    )
    return panel("Something went wrong", body, level=3)


# ---------------------------------------------------------------------------
# Delivery (rich with automatic fallback — the ONLY sanctioned way to send
# text that contains rich-only tags)
# ---------------------------------------------------------------------------
async def send(client, chat_id, html_text: str, **kwargs):
    return await richgram.rich_send(client, chat_id, html_text, **kwargs)


async def reply(message, html_text: str, client=None, quote: bool = True, **kwargs):
    return await richgram.rich_reply(message, html_text, client=client, quote=quote, **kwargs)


async def edit(target, html_text: str, client=None, **kwargs):
    return await richgram.rich_edit(target, html_text, client=client, **kwargs)


async def edit_where(client, chat_id, message_id, html_text: str, **kwargs):
    return await richgram.rich_edit(client, html_text, client=client,
                                    chat_id=chat_id, message_id=message_id, **kwargs)
