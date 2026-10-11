# NOTICE

This repository combines two open-source projects:

## 1. Anime downloader core (`cantarella/`, `Script.py`)

Derived from the "AniwatchTvdl / Cantarella" project, licensed under the
**GNU General Public License v3.0**. The full license text is in
[`LICENSE`](LICENSE). This combined work is therefore distributed under
GPL-3.0 as well.

## 2. Leech engine (`leechbot/`)

Derived from [LeechBot](https://github.com/Shineii86/LeechBot) by
**Sʜɪɴᴇɪ Nᴏᴜᴢᴇɴ**, licensed under the **MIT License**. The complete license
text and copyright notice are preserved verbatim in
[`LICENSES/LeechBot-LICENSE`](LICENSES/LeechBot-LICENSE), as required by the
MIT License.

## 3. Bundled binary

`binary/N_m3u8DL-RE` is an unmodified build of
[N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) by nilaoda, bundled for
deployment convenience. All rights remain with its original authors.

## 4. Rich UI layer

`uikit.py` is built on [richgram](https://github.com/Badmunda05/richgram) by
**Bad Munda**, MIT License — installed from PyPI as a dependency (not bundled);
its license text is available in the distributed package.

## Modifications

Both cores have been substantially modified for this project: the two bots
were merged onto a single Pyrogram client, command/callback routing was
de-conflicted, configuration was unified, and deployment tooling was rewritten.
