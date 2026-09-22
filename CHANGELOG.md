# O‘zgarishlar

Format: [Keep a Changelog](https://keepachangelog.com/). Versiya raqami
`app/runtime_support.py` dagi `VERSION` va `pyproject.toml` da bir xil bo‘lishi
kerak; `bundle.json` har bir paketning fayl-hash qulf-fayli.

## [Unreleased]

### Qo‘shildi — macOS (Apple Silicon)
- `MusicPro.command` va `TEKSHIRISH.command` — Finder’dan ikki marta bosiladigan
  ishga tushirgichlar; Python 3.11+ ni topadi, serverni fon rejimida ochadi.
- `app/bin/ffmpeg`, `app/bin/ffprobe` — FFmpeg 9.0 arm64 (GPL, libx264).
- `app/folder_dialog.py` — platformaga qarab papka oynasi: Windows’da avvalgi
  `win_dialog.py`, macOS’da Finder paneli (`osascript`).
- GPU rejimi macOS’da `h264_videotoolbox` (Apple media engine) orqali ishlaydi;
  sifat darajalari CRF qiymatlariga mos `-q:v` bilan.
- `/api/init` endi `platform` maydonini qaytaradi; interfeys ishga tushirgich nomi,
  paket yorlig‘i va GPU izohini shu asosda ko‘rsatadi.
- `developer/e2e_macos.py` — haqiqiy VideoToolbox va CPU+GPU navbat sinovi.
- `README_MAC.txt` — macOS foydalanuvchi qo‘llanmasi.

### Qo‘shildi — loyiha vositalari
- `developer/build_manifest.py` — `bundle.json` ni istalgan platformada yangilaydi
  (`--check` bilan farqni ko‘rsatadi).
- `developer/fetch_binaries.py` — git’da saqlanmaydigan uchinchi tomon binarlarini
  SHA-256 bilan yuklab, `bundle.json` ga solishtiradi.
- `developer/tasks.py` va `Makefile` — `test`, `e2e`, `check`, `manifest`, `lint`,
  `fetch`, `run`, `clean`, `ci` vazifalari.
- `pyproject.toml` (ruff sozlamasi), `.gitignore`, `.gitattributes`, `.editorconfig`,
  `README.md`, ushbu `CHANGELOG.md`.
- GitHub Actions CI (`.github/workflows/ci.yml`): Linux (tizim FFmpeg — lint, 79 unit
  test, 4 CPU E2E), Windows va macOS (Apple Silicon) — `fetch_binaries.py` orqali
  aynan paketdagi binarlar bilan unit testlar. Windows paketi birinchi marta haqiqiy
  Windows’da avtomatik sinaladi.

### Tuzatildi
- **`app/engine.py`: sog‘lom manba noto‘g‘ri chiqarib tashlanardi.** Musiqaga mos
  (beat) rejimda bo‘lak ofseti `1e-4` s dan kichik chiqsa, `-ss` ga Python’ning
  ilmiy yozuvi (`3.1e-05`) uzatilardi; ffmpeg vaqt parseri uni rad etadi
  (`Invalid duration for option ss`), segment ikki marta yiqiladi va manba
  “render qilinmadi” deb bloklanadi — oxirgi bo‘lak bo‘lsa, butun navbat
  “Yaroqli oddiy bo‘lak qolmadi” bilan tugaydi. Har qayta rejalash yuzlab ofset
  tortgani uchun run’ga ~5–12 % ehtimol edi; CI shuni tutdi. Endi `-ss` qat’iy
  o‘nlik (`0.000031`); haqiqiy ffmpeg bilan regressiya testi qo‘shildi.
- `developer/e2e_recovery.py` nodeterministik edi: har qayta rejalash yangi urug‘
  oladi, bitta litsen o‘rni bilan buzilgan litsen ~12% holatda hech qaysi rejaga
  tushmasdi. Endi `license_count=2` (`e2e_playlist.py` dagidek) — har rejada ikkala
  litsen ishlatiladi.
- `app/tests/test_portable.py`: qulf ushlab turganda `instance.lock` o‘qilardi —
  Windows’da `msvcrt.locking` majburiy qulf, o‘qish rad etiladi. Tekshiruv
  bo‘shatilgandan keyinga ko‘chirildi; `try/finally` bilan qulf har doim bo‘shatiladi.
- `developer/fetch_binaries.py`: `python313._pth` Windows’da CRLF bilan yozilardi va
  `bundle.json` ga mos kelmasdi (`newline='\n'`).
- ruff: 17 ta ishlatilmagan import va 1 ta o‘lik o‘zgaruvchi olib tashlandi;
  `test_recovery.py` `StorageError` ni `engine` star-importidan tasodifan olardi —
  endi `failures` dan aniq import.

### O‘zgartirildi
- `app/resources.py`: macOS’da bo‘sh xotira `vm_stat` orqali o‘lchanadi
  (`SC_AVPHYS_PAGES` yo‘qligi sabab avval doim 4 GB deb olinardi).
- `app/app.py`: `auto` rejimda macOS’da ishchi jarayon `nice` bilan past
  ustuvorlikda; natija papkasini ochish `open` orqali.
- `app/bootstrap.py`: macOS uchun `osascript` dialoglari; Windows-only to‘siq
  olib tashlandi.
- `app/runtime_support.py`: o‘rnatilgan rejimda macOS ma’lumot papkasi
  `~/Library/Application Support/MusicProStudio/data`.
- Qo‘llanma bitta faylga keltirildi: `BOSHLASH.html`; `/help` shuni beradi.
- `THIRD_PARTY.md`: macOS FFmpeg va Python bo‘limlari; Windows FFmpeg uchun doimiy
  GitHub reliz manzili.
- Testlar `tempfile` papkasini `resolve()` qiladi (macOS’da `/var` → `/private/var`).

### O‘chirildi
- `app/QOLLANMA.html` (`BOSHLASH.html` ning bayt-bayt nusxasi), `app/diagnose.py`
  (hech qayerdan chaqirilmasdi), `licenses/ffmpeg/doc/` va `presets/` (11 MB
  FFmpeg HTML hujjatlari va libvpx presetlari — litsenziyaga aloqasi yo‘q).

## [1.8.0] — 2026-09-10

Windows 10/11 x64 portable paket (Python 3.13 va FFmpeg 9.0.1 ichida).

### Qo‘shildi
- Har bir natijaviy video uchun alohida playlist tanlash: barcha o‘rinlar
  (Top 5, Top 10, 1000 tagacha), bo‘sh o‘rinlar random, videolar orasida mustaqil.
- Har bir playlist rejasi o‘z natija ishiga bog‘lanadi; boshqa ishning rejasi
  tanlovlarni o‘zgartira olmaydi.
- 7 ta yangi test; jami 79 ta avtomatik test.

### Saqlangan
- Bitta musiqa rejimi, random bo‘laklar, musiqaga mos montaj, effektlar, litsen
  qoidalari, CPU/GPU umumiy navbat, resurs rejimlari, Playlist.txt va Excel
  hisobotlari 1.7 dagidek.

Oldingi versiyalar (1.2 … 1.7) ushbu omborga kirmagan; ularning tarixi asl
Windows paketining `TEST_REPORT.md` va `developer/BUILD.md` fayllarida qisqacha
qayd etilgan.
