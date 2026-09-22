MusicPro Studio 1.8 — macOS

Apple Silicon (M1/M2/M3/M4) uchun. macOS 12 yoki undan yangisi.
FFmpeg paket ichida. Python kompyuteringizdagisidan foydalaniladi.

TALABLAR

1. Python 3.11 yoki undan yangisi.
   Tekshirish uchun Terminalda: python3 -V
   Yo'q bo'lsa: https://www.python.org/downloads/macos/ dan o'rnating.
2. Boshqa hech narsa kerak emas. Homebrew, FFmpeg yoki internet talab qilinmaydi.

ISHGA TUSHIRISH

1. Butun MusicPro_Studio_1.8 papkasini saqlang. Faqat bitta faylni ko'chirmang.
2. MusicPro.command faylini ikki marta bosing.
3. Terminal oynasi ochiladi va dastur brauzerda ishga tushadi.
4. Terminal oynasini yopsangiz ham dastur ishlashda davom etadi.
5. Yopish uchun dastur ichidagi "Chiqish" tugmasini bosing.

Agar macOS "ishlab chiquvchini tekshirib bo'lmadi" desa: MusicPro.command ustida
o'ng tugmani bosing > Ochish > yana Ochish. Bu faqat birinchi safar kerak.

PAPKA TANLASH

"Tanlash" tugmasi Finder oynasini ochadi. Birinchi marta macOS
"Python Hujjatlar papkasiga kirishni so'rayapti" degan ruxsat so'rashi mumkin —
"Ruxsat berish" ni bosing. Oyna ochilmasa, papkaning to'liq manzilini qo'lda
kiriting. Finder'dagi papkani maydonga sichqoncha bilan tortib tashlash ham
mumkin.

QURILMA TANLASH

CPU — protsessor orqali render (libx264).
GPU — Apple apparat kodlovchisi (VideoToolbox). Alohida drayver kerak emas,
      protsessorni bo'sh qoldiradi va tezroq ishlaydi.
CPU + GPU — umumiy navbat: bo'shagan qurilma navbatdagi videoni oladi.

Windows'dagi NVIDIA/Intel/AMD kodlovchilari o'rniga macOS'da VideoToolbox
ishlatiladi. Boshqa barcha sozlamalar va natijalar bir xil.

RESURS REJIMI

macOS qattiq CPU foiz limitini bermaydi (bu Windows imkoniyati). O'rniga
oqimlar soni, parallel segmentlar va past jarayon ustuvorligi boshqariladi.
"Avtomatik" rejimda render past ustuvorlikda ishlaydi va Mac javob berishda
davom etadi.

MA'LUMOTLAR QAYERDA

Navbat, sozlamalar va jurnallar shu papka ichidagi data/ papkasida saqlanadi.
Yangi versiyaga o'tishda eski data/ papkasini yangi paketga nusxalang —
navbat va sozlamalar saqlanadi. Nusxalash paytida dastur yopiq bo'lsin.

TEKSHIRISH

TEKSHIRISH.command faylini ikki marta bosing. U paket fayllarini SHA-256 bilan
tekshiradi, haqiqiy video/audio kodlash va Excel hisobotini sinaydi.
Natija: data/diagnostics.txt

MUAMMO BO'LSA

data/startup.log — ishga tushish jurnali.
Har bir natija papkasida render_diagnostics.txt — shu videoning tafsilotlari.

Dastur ishga tushmasa, Terminalda quyidagini bajaring:
  cd "<MusicPro papkasining manzili>"
  python3 -X utf8 -B app/bootstrap.py

WINDOWS BILAN FARQLAR

- MusicPro.exe / START.bat o'rniga MusicPro.command.
- TEKSHIRISH.bat o'rniga TEKSHIRISH.command.
- Ichki Python o'rniga kompyuterdagi Python 3.11+.
- GPU: NVENC/QSV/AMF o'rniga VideoToolbox.
- CPU foiz limiti yo'q; oqim va ustuvorlik boshqaruvi bor.
- Qolgan hamma narsa bir xil: rejalar, playlist, effektlar, nomlash qoidalari,
  Playlist.txt va Excel hisobotlari aynan o'sha formatda.

BOSHLASH.html — to'liq foydalanish qo'llanmasi (ikkala platforma uchun umumiy).
THIRD_PARTY.md — FFmpeg va Python litsenziyalari.
