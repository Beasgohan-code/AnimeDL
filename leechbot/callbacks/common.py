# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================
# License   : MIT License
# =============================================================================

"""
All inline keyboard callback query handlers.

Each callback category is handled by a dedicated async function
for clarity, testability, and maintainability.
"""

import logging

logger = logging.getLogger(__name__)


async def safe_answer(callback_query, *args, **kwargs):
    """Safe wrapper for callback_query.answer() to suppress QueryIdInvalid."""
    try:
        await callback_query.answer(*args, **kwargs)
    except Exception:
        pass
