# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================

"""
LeechBot uploader modules.

This package contains all uploader implementations.
"""

from .telegram import upload_file, upload_photos_batch, progress_bar

__all__ = ["upload_file", "upload_photos_batch", "progress_bar"]
