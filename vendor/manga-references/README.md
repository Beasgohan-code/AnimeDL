# Reference repositories (vendored in full)

These folders are the **complete upstream codebases** the AnimeDL manga engine
was mined from. They are kept verbatim as technical documentation so every
provider contract, fallback and scraper trick stays auditable — and so future
improvements can be mined without re-fetching anything.

| Folder | Upstream | What AnimeDL took from it |
|--------|----------|---------------------------|
| `Manhwa-Bot/`   | Dra-Sama/Manhwa-Bot (MIT-style headers) | comick, asura, weebcentral, mgeko, manhuafast, manhuaplus, templetoons, manhwaclan, manga18fx, manhwa18 contracts + the cloudscraper (`cs=True`) approach |
| `Manga-Bot/`    | Codeflix-Bots/Manga-Bot (MIT, see folder) | mangakakalot, mangasee, mangabuddy, ninemanga contracts + img2pdf/img2cbz patterns |
| `AUTO-MANGA-BOT/` | abhinai2244/AUTO-MANGA-BOT | allmanga/mangaforest/webcentral notes; settings/admin UX references |

Rules respected by the AnimeDL project:

1. **Nothing here is imported at runtime.** The shipped engine lives in
   `manga_sources/` (rebuilt + hardened). `cantarella/` and `leechbot/` never
   touch this folder; the plugin loaders register their own modules only.
2. **User-facing text carries AnimeDL branding only.** These folders are
   developer-facing reference code.
3. Upstream licenses are preserved inside each folder. If you reuse more code
   from them, keep their license/credit files intact.

`git`-free tarballs were unpacked (no nested `.git`), so `git status` treats
these as ordinary vendored files.
