# MusicPro Studio

Oflayn ommaviy video-montaj dasturi. Bo‘laklar papkasi, litsenziyalangan
videolar va musiqalardan tayyor videolar yasaydi: har bir video o‘z musiqasi
(yoki playlisti) uzunligida, litsen parchalari qoidaga muvofiq joylashtirilgan,
xohlasangiz musiqa urg‘ulariga mos kesilgan va effektlangan. Har bir natija
bilan birga `Playlist.txt` va litsenziyalash uchun Excel hisoboti chiqadi.
Nosoz manbalar tasdiqsiz almashtiriladi, navbat qayta ochilganda davom etadi.

Dastur to‘liq mahalliy ishlaydi: `127.0.0.1` dagi HTTP server + brauzer
interfeysi. Internet, tashqi kutubxona yoki o‘rnatish talab qilinmaydi.

| Platforma | Ishga tushirish | Qo‘llanma |
|---|---|---|
| Windows 10/11 x64 | `MusicPro.exe` (yoki `START.bat`) | [README.txt](README.txt) |
| macOS, Apple Silicon | `MusicPro.command` | [README_MAC.txt](README_MAC.txt) |
| Ikkalasi | — | [BOSHLASH.html](BOSHLASH.html) — to‘liq foydalanish qo‘llanmasi |

Paket ichida FFmpeg bor; Windows paketida Python ham bor, macOS’da
kompyuterdagi Python 3.11+ ishlatiladi.

## Qanday ishlaydi

```
MusicPro.exe / MusicPro.command
        │
        ▼
app/bootstrap.py ── data/startup.log, paket to‘liqligi, --check
        │
        ▼
app/app.py ─────── loopback HTTP server (8765–8784) + token, session.json
   │  │  │
   │  │  └── web/studio.html · studio.js · studio.css   (brauzer interfeysi)
   │  │
   │  └───── engine.py   reja tuzish (kadr aniqligida), FFmpeg buyruqlari
   │         playlist.py · effects.py · audio_analysis.py · output_names.py
   │
   └──────── worker.py   har bir video uchun alohida jarayon
                 │        (fayl orqali progress, kooperativ to‘xtatish)
                 ▼
             app/bin/ffmpeg · ffprobe
```

| Modul | Vazifasi |
|---|---|
| `app/engine.py` | Manbalarni skanerlash, deterministik reja (`seed`), segmentlar renderi, concat, tekshiruvlar |
| `app/batch.py` | Navbat, nosoz manbani almashtirish, muammolar ro‘yxati (CSV) |
| `app/playlist.py` | Har video uchun playlist tanlovi, aniq PCM birlashtirish, `Playlist.txt` |
| `app/effects.py` | Kuchli urg‘ularga bog‘langan edit effektlari (FFmpeg filtrlari) |
| `app/audio_analysis.py` | PCM’dan kesim va kuchli urg‘u nuqtalari |
| `app/reports.py` | Excel hisoboti (`report_template.xlsx`), TXT → XLSX konvertatsiya |
| `app/resources.py` | CPU/GPU navbat byudjeti; Windows Job Object CPU limiti |
| `app/output_names.py` | Xavfsiz papka/video nomlari, band nomlar `(2)`, `(3)` |
| `app/runtime_support.py` | `VERSION`, ma’lumot papkasi, bitta nusxa qulfi |
| `app/folder_dialog.py` | Papka oynasi: Windows Shell32 (`win_dialog.py`) yoki Finder |
| `app/portable_check.py` | `TEKSHIRISH`: manifest SHA-256, haqiqiy kodlash, effektlar, Excel |

Ma’lumotlar (`session.json`, jurnallar) portable rejimda paket ichidagi `data/`
papkasida; Windows Setup bilan o‘rnatilganda `%LOCALAPPDATA%\MusicProStudio`,
macOS’da `~/Library/Application Support/MusicProStudio`.

## Papka tuzilmasi

```
MusicPro_Studio_1.8/
├── MusicPro.exe · START.bat · TEKSHIRISH.bat        Windows ishga tushirgichlar
├── MusicPro.command · TEKSHIRISH.command            macOS ishga tushirgichlar
├── BOSHLASH.html · README.txt · README_MAC.txt      foydalanuvchi hujjatlari
├── bundle.json                                      paket qulf-fayli (har fayl SHA-256)
├── app/                                             dastur (Python 3.11+, tashqi paketlarsiz)
│   ├── bin/       ffmpeg(.exe) · ffprobe(.exe)      ikkala platforma binarlari
│   ├── web/       studio.html · studio.js · studio.css
│   ├── assets/    report_template.xlsx
│   └── tests/     79 ta unittest
├── runtime/                                         Windows uchun ichki Python 3.13
├── developer/                                       qurish, sinov va reliz vositalari
├── licenses/                                        FFmpeg (GPL v3), NSIS
├── THIRD_PARTY.md · TEST_REPORT.md · CHANGELOG.md
└── pyproject.toml · Makefile · .gitignore · .gitattributes · .editorconfig
```

`app/` va `runtime/` nomlari o‘zgarmas: `MusicPro.exe` ichida
`runtime\pythonw.exe` va `app\bootstrap.py` yo‘llari qattiq yozilgan, exe’ni
qayta qurish uchun Windows va Zig kerak (`developer/BUILD.md`).

## Dasturchi uchun

Talab: Python 3.11+ (tashqi paket kerak emas; `ruff` faqat lint uchun).

Git’dan olingan nusxada binarlar yo‘q — ular ~320 MB va `THIRD_PARTY.md` dagi
manbalardan SHA-256 bilan qayta tiklanadi:

```bash
python3 developer/fetch_binaries.py            # ikkala platforma
python3 developer/fetch_binaries.py --platform macos
```

Vazifalar (`make <vazifa>` yoki `python3 developer/tasks.py <vazifa>`;
Windows’da `py developer\tasks.py <vazifa>`):

| Vazifa | Nima qiladi |
|---|---|
| `test` | `app/tests` — 79 ta unittest (~35 s, haqiqiy FFmpeg bilan) |
| `e2e` | `developer/e2e_*.py` — haqiqiy HTTP server, ishchi jarayonlar, kodlangan videolar |
| `check` | `TEKSHIRISH` hisoboti: manifest, kodlash, effektlar, Excel |
| `manifest` / `manifest --check` | `bundle.json` ni yangilash / farqni ko‘rsatish |
| `lint` | `ruff check` (`pyproject.toml` sozlamasi) |
| `fetch` | uchinchi tomon binarlarini yuklab tekshirish |
| `run` | dasturni oldingi planda ishga tushirish (`run --no-browser` ham mumkin) |
| `clean` | keshlar va tizim chiqindilarini o‘chirish |
| `ci` | `lint` + `test` + `manifest --check` |

Paketdagi biror faylni o‘zgartirgach `manifest` ni ishga tushiring —
`TEKSHIRISH` foydalanuvchi kompyuterida aynan `bundle.json` bo‘yicha tekshiradi.

Windows portable ZIP va (ixtiyoriy) Setup: `developer/BUILD.md`.
Sinovlar qamrovi va chegaralari: `TEST_REPORT.md`.

## Versiyalash

`app/runtime_support.py` dagi `VERSION` — asosiy manba; `pyproject.toml` va
hujjatlardagi raqam unga mos bo‘lishi kerak. O‘zgarishlar `CHANGELOG.md` da.
`bundle.json` har bir reliz uchun qayta yaratiladi va paket bilan birga ketadi.

## Uchinchi tomon va litsenziya

FFmpeg (GPL v3, `libx264` bilan) va Python litsenziyalari, manzillari va
SHA-256 qiymatlari — `THIRD_PARTY.md`. GPL binarlarni tarqatishda litsenziya
matnlarini saqlash va manba kodi manzillarini ko‘rsatish majburiy.
MusicPro’ning o‘z kodi uchun litsenziya belgilanmagan.
