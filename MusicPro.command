#!/bin/bash
# MusicPro Studio — macOS ishga tushirgich (Windowsdagi MusicPro.exe ekvivalenti).
# Finder oynasidan ikki marta bosing. Dastur brauzerda ochiladi.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

TITLE="MusicPro Studio"

panel() {  # Finderdan ochilganda terminal ko'rinmasligi mumkin; panel ko'rinadi.
    local body
    body=$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk 'BEGIN{ORS="\\n"}{print}')
    /usr/bin/osascript -e "display dialog \"${body}\" with title \"$TITLE\" buttons {\"OK\"} default button \"OK\" with icon stop" >/dev/null 2>&1 || true
}

fail() {
    printf '\n%s\n\n' "$1" >&2
    panel "$1"
    exit 1
}

# --- Python 3.11+ ni topish -------------------------------------------------
# /usr/bin/python3 Xcode litsenziyasini talab qilishi mumkin, shuning uchun oxirida.
find_python() {
    local candidate
    for candidate in \
        "${MUSICPRO_PYTHON:-}" \
        "$(command -v python3 2>/dev/null || true)" \
        /opt/homebrew/bin/python3 \
        /usr/local/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
        /usr/bin/python3
    do
        [ -n "$candidate" ] && [ -x "$candidate" ] || continue
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

PY="$(find_python || true)"
[ -n "$PY" ] || fail "Python 3.11 yoki undan yangisi topilmadi.

python.org saytidan macOS uchun Python o'rnating, so'ng bu faylni qayta oching:
https://www.python.org/downloads/macos/"

# --- Paket to'liqligi -------------------------------------------------------
[ -f "$HERE/app/bootstrap.py" ] || fail "Paket to'liq emas: app/bootstrap.py topilmadi.
ZIPni to'liq oching va butun MusicPro papkasini saqlang."

for tool in ffmpeg ffprobe; do
    [ -f "$HERE/app/bin/$tool" ] || fail "Paket to'liq emas: app/bin/$tool topilmadi.
macOS uchun FFmpeg fayllari yo'q. README_MAC.txt ga qarang."
    [ -x "$HERE/app/bin/$tool" ] || chmod +x "$HERE/app/bin/$tool" 2>/dev/null || true
done

# Internetdan ko'chirilgan imzosiz fayllarni macOS karantinga oladi; olib tashlaymiz.
/usr/bin/xattr -d com.apple.quarantine "$HERE/app/bin/ffmpeg" "$HERE/app/bin/ffprobe" >/dev/null 2>&1 || true

# --- Ishga tushirish --------------------------------------------------------
printf '\n  %s 1.8 — macOS\n  Python: %s\n\n  Ishga tushmoqda…\n' "$TITLE" "$("$PY" -V 2>&1)"

DATA="$HERE/data"
mkdir -p "$DATA"
nohup "$PY" -X utf8 -B "$HERE/app/bootstrap.py" >/dev/null 2>&1 &
PID=$!
disown "$PID" 2>/dev/null || true

# Server manzilini yozishini kutamiz; yiqilsa startup.log dan sababni ko'rsatamiz.
ADDRESS=""
for _ in $(seq 1 60); do
    if [ -f "$DATA/instance.json" ]; then
        ADDRESS="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("address",""))' "$DATA/instance.json" 2>/dev/null || true)"
        [ -n "$ADDRESS" ] && break
    fi
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.5
done

if [ -n "$ADDRESS" ]; then
    printf '  Tayyor: %s\n\n  Brauzer oynasida ishlang. Yopish uchun dasturdagi “Chiqish” tugmasini bosing.\n  Bu Terminal oynasini yopsangiz ham dastur ishlashda davom etadi.\n\n' "$ADDRESS"
    exit 0
fi

if kill -0 "$PID" 2>/dev/null; then
    printf '  Dastur ishga tushdi, lekin manzil hali yozilmadi. Brauzerni tekshiring.\n\n'
    exit 0
fi

DETAIL="Batafsil: data/startup.log"
if [ -f "$DATA/startup.log" ]; then
    TAIL="$(tail -n 12 "$DATA/startup.log" 2>/dev/null || true)"
    [ -n "$TAIL" ] && DETAIL="$TAIL"
fi
fail "MusicPro ishga tushmadi.

$DETAIL"
