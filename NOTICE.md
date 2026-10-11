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

## Modifications

Both cores have been substantially modified for this project: the two bots
were merged onto a single Pyrogram client, command/callback routing was
de-conflicted, configuration was unified, and deployment tooling was rewritten.
