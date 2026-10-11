# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.
# =============================================================================

"""
Google Drive downloader module.

Handles downloads from Google Drive, including files, folders, and shared drives.
Uses the Google Drive API with proper pagination, error handling, and async wrappers.
"""

import io
import logging
import pickle
import asyncio
from functools import partial
from natsort import natsorted
from re import search as re_search
from os import makedirs, path as ospath
from urllib.parse import parse_qs, urlparse
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from leechbot.utility.handler import cancelTask
from leechbot.utility.helper import sizeUnit, getTime, speedETA, status_bar
from leechbot.utility.variables import Gdrive, Messages, Paths, BotTimes, Transfer

logger = logging.getLogger(__name__)

# Max recursion depth for folder traversal
MAX_FOLDER_DEPTH = 50


# =============================================================================
# Async wrapper for blocking API calls
# =============================================================================
async def _run_sync(func, *args, **kwargs):
    """Run a synchronous function in a thread pool to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


# =============================================================================
# Service Builder
# =============================================================================
async def build_service():
    """
    Build Google Drive API service from token.
    """
    if not ospath.exists(Paths.access_token):
        await cancelTask("Token.pickle Not Found! Please Run The Google Drive Setup First.")
        return

    def _build():
        with open(Paths.access_token, "rb") as token:
            creds = pickle.load(token)
            Gdrive.service = build("drive", "v3", credentials=creds)

    try:
        await _run_sync(_build)
    except Exception as e:
        logger.error(f"Failed to build GDrive service: {e}")
        await cancelTask(f"GDrive auth failed: {e}")


def _ensure_service():
    """Raise if GDrive service is not initialized."""
    if Gdrive.service is None:
        raise RuntimeError("GDrive service not initialized. Call build_service() first.")


# =============================================================================
# Extract File ID
# =============================================================================
async def getIDFromURL(link: str) -> str:
    """
    Extract file ID from Google Drive link.

    Supports:
      - https://drive.google.com/file/d/ID/...
      - https://drive.google.com/drive/folders/ID
      - https://drive.google.com/open?id=ID
      - https://drive.google.com/uc?id=ID
      - https://drive.google.com/drive/u/0/folders/ID

    Returns:
        str: file/folder ID
    """
    # Pattern 1: /file/d/ID or /folders/ID (with optional /u/N/ prefix)
    regex = r"drive\.google\.com/(?:drive/)?(?:u/\d+/)?(?:file/d/|folders/)([-\w]+)"
    match = re_search(regex, link)
    if match:
        return match.group(1)

    # Pattern 2: ?id=ID query parameter
    parsed = urlparse(link)
    params = parse_qs(parsed.query)
    if "id" in params:
        return params["id"][0]

    await cancelTask("Invalid Google Drive Link")
    logger.error(f"G-Drive ID not found in: {link}")
    return ""


# =============================================================================
# Get Files in Folder (with pagination)
# =============================================================================
def _getFilesByFolderID(folder_id: str) -> list:
    """
    Get ALL files in a Google Drive folder (handles pagination).

    Args:
        folder_id: folder ID

    Returns:
        list: list of file objects
    """
    _ensure_service()
    page_token = None
    files = []

    while True:
        response = (
            Gdrive.service.files()
            .list(
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                q=f"'{folder_id}' in parents and trashed = false",
                spaces="drive",
                pageSize=200,
                fields="nextPageToken, files(id, name, mimeType, size, shortcutDetails)",
                orderBy="folder, name",
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if page_token is None:
            break

    return files


# =============================================================================
# Get File Metadata
# =============================================================================
def _getFileMetadata(file_id: str) -> dict:
    """
    Get metadata for a file.

    Args:
        file_id: file ID

    Returns:
        dict: file metadata
    """
    _ensure_service()
    return (
        Gdrive.service.files()
        .get(fileId=file_id, supportsAllDrives=True, fields="name, id, mimeType, size")
        .execute()
    )


# =============================================================================
# Get Folder Size (with pagination)
# =============================================================================
def _get_Gfolder_size(folder_id: str, depth: int = 0) -> int:
    """
    Calculate total size of a folder recursively (handles pagination).

    Args:
        folder_id: folder ID
        depth: current recursion depth

    Returns:
        int: total size in bytes
    """
    if depth > MAX_FOLDER_DEPTH:
        logger.warning(f"GDrive folder nesting exceeded {MAX_FOLDER_DEPTH} levels")
        return 0

    try:
        _ensure_service()
        total_size = 0
        page_token = None

        while True:
            query = f"trashed = false and '{folder_id}' in parents"
            results = (
                Gdrive.service.files()
                .list(
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    q=query,
                    fields="nextPageToken, files(id, mimeType, size)",
                    pageSize=200,
                    pageToken=page_token,
                )
                .execute()
            )

            items = results.get("files", [])
            folders = []

            for item in items:
                if "size" in item:
                    total_size += int(item["size"])
                elif item.get("mimeType") == "application/vnd.google-apps.folder":
                    folders.append(item["id"])

            for fid in folders:
                total_size += _get_Gfolder_size(fid, depth + 1)

            page_token = results.get("nextPageToken")
            if page_token is None:
                break

        return total_size

    except HttpError as error:
        logger.error(f"Folder size error: {error}")
        return 0


# =============================================================================
# Google Apps types (not downloadable)
# =============================================================================
_GOOGLE_APPS_PREFIX = "application/vnd.google-apps"

def _is_google_apps(mime_type: str) -> bool:
    """Check if a mimeType is a Google Apps type (Docs, Sheets, Slides, etc.)."""
    return mime_type.startswith(_GOOGLE_APPS_PREFIX)


# =============================================================================
# Main Download Function
# =============================================================================
async def g_DownLoad(link: str, num: int):
    """
    Download file or folder from Google Drive.

    Args:
        link: Google Drive share link
        num: link number for display
    """
    # Ensure service is ready
    if Gdrive.service is None:
        await build_service()
        if Gdrive.service is None:
            return

    file_id = await getIDFromURL(link)
    if not file_id:
        return

    meta = await _run_sync(_getFileMetadata, file_id)
    Messages.download_name = meta.get("name", "GDrive File")
    Messages.status_head = (
        f"<b>📥 Downloading</b> <code>Link {str(num).zfill(2)}</code>\n\n"
        f"<b>🏷️ Name:</b> <code>{Messages.download_name}</code>\n"
    )

    if meta.get("mimeType") == "application/vnd.google-apps.folder":
        await gDownloadFolder(file_id, Paths.down_path, num)
    elif _is_google_apps(meta.get("mimeType", "")):
        await cancelTask("Google Docs/Sheets/Slides cannot be downloaded directly")
    else:
        await gDownloadFile(file_id, Paths.down_path)


# =============================================================================
# Download Single File
# =============================================================================
async def gDownloadFile(file_id: str, path: str):
    """
    Download a single file from Google Drive.

    Args:
        file_id: file ID
        path: download path
    """
    try:
        file = await _run_sync(_getFileMetadata, file_id)
    except HttpError as error:
        err = "File not found or not accessible"
        logger.error(err)
        await cancelTask(err)
        return

    if _is_google_apps(file.get("mimeType", "")):
        await cancelTask("Google Docs/Sheets/Slides cannot be downloaded directly")
        return

    try:
        file_name = file.get("name", f"Untitled_{file_id}")
        file_size = int(file.get("size", 0))
        file_path = ospath.join(path, file_name)

        # Run download in thread pool with progress reporting
        loop = asyncio.get_running_loop()

        def _run_download():
            file_contents = io.BytesIO()
            request = Gdrive.service.files().get_media(
                fileId=file_id, supportsAllDrives=True
            )
            downloader = MediaIoBaseDownload(
                file_contents, request, chunksize=70 * 1024 * 1024
            )

            done = False
            while not done:
                status, done = downloader.next_chunk()
                file_contents.seek(0)
                with open(file_path, "ab") as f:
                    f.write(file_contents.getvalue())
                file_contents.seek(0)
                file_contents.truncate()

            return file_size

        # Progress monitoring in async context
        async def _download_with_progress():
            download_task = loop.run_in_executor(None, _run_download)

            # Poll file size for progress
            while not download_task.done():
                if ospath.exists(file_path):
                    current = ospath.getsize(file_path)
                    down_done = sum(Transfer.down_bytes) + current
                    speed_string, eta, percentage = speedETA(
                        BotTimes.task_start, down_done, Transfer.total_down_size
                    )
                    await status_bar(
                        down_msg=Messages.status_head,
                        speed=speed_string,
                        percentage=percentage,
                        eta=getTime(eta),
                        done=sizeUnit(down_done),
                        left=sizeUnit(Transfer.total_down_size),
                        engine="GDrive ♻️"
                    )
                await asyncio.sleep(2)

            return await download_task

        result = await _download_with_progress()
        Transfer.down_bytes.append(result)

    except HttpError as error:
        if error.resp.status == 403 and "User rate limit" in str(error):
            logger.error("Download quota exceeded")
            await cancelTask("Download Quota Exceeded")
        elif error.resp.status == 404:
            logger.error("File not found")
            await cancelTask("GDrive file not found")
        else:
            logger.error(f"GDrive error: {error}")
            await cancelTask(f"GDrive Error: {error}")

    except Exception as e:
        logger.error(f"Download error: {e}")
        await cancelTask(f"Download Error: {e}")


# =============================================================================
# Download Folder
# =============================================================================
async def gDownloadFolder(folder_id: str, path: str, num: int = 0, depth: int = 0):
    """
    Download a folder recursively from Google Drive.

    Args:
        folder_id: folder ID
        path: download path
        num: link number (for display)
        depth: current recursion depth
    """
    if depth > MAX_FOLDER_DEPTH:
        logger.warning(f"GDrive folder nesting exceeded {MAX_FOLDER_DEPTH} levels")
        return

    try:
        folder_meta = await _run_sync(_getFileMetadata, folder_id)
    except HttpError as e:
        logger.error(f"Cannot access folder: {e}")
        return

    folder_name = folder_meta.get("name", f"folder_{folder_id[:8]}")
    folder_path = ospath.join(path, folder_name)

    if not ospath.exists(folder_path):
        makedirs(folder_path)

    result = await _run_sync(_getFilesByFolderID, folder_id)

    if not result:
        return

    result = natsorted(result, key=lambda k: k.get("name", ""))

    for item in result:
        file_id = item["id"]
        mime_type = item.get("mimeType", "")
        shortcut = item.get("shortcutDetails")

        if shortcut:
            file_id = shortcut.get("targetId", file_id)
            mime_type = shortcut.get("targetMimeType", mime_type)

        if mime_type == "application/vnd.google-apps.folder":
            await gDownloadFolder(file_id, folder_path, num, depth + 1)
        elif _is_google_apps(mime_type):
            logger.info(f"Skipping Google Apps type: {item.get('name')} ({mime_type})")
        else:
            await gDownloadFile(file_id, folder_path)


# =============================================================================
# Public wrappers (for __init__.py exports)
# =============================================================================
async def getFileMetadata(file_id: str) -> dict:
    """Public async wrapper for getFileMetadata."""
    return await _run_sync(_getFileMetadata, file_id)


async def getFilesByFolderID(folder_id: str) -> list:
    """Public async wrapper for getFilesByFolderID."""
    return await _run_sync(_getFilesByFolderID, folder_id)


async def get_Gfolder_size(folder_id: str) -> int:
    """Public async wrapper for get_Gfolder_size."""
    return await _run_sync(_get_Gfolder_size, folder_id)
