#!/bin/bash
# MusicPro Studio — paket, CPU, audio, effekt va Excel tekshiruvi (macOS).
# Natija data/diagnostics.txt ga yoziladi va avtomatik ochiladi.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

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
if [ -z "$PY" ]; then
    printf '\nPython 3.11 yoki undan yangisi topilmadi.\nhttps://www.python.org/downloads/macos/\n\n' >&2
    read -r -p "Yopish uchun Enter bosing…" _
    exit 1
fi

for tool in ffmpeg ffprobe; do
    [ -f "$HERE/app/bin/$tool" ] && [ ! -x "$HERE/app/bin/$tool" ] && chmod +x "$HERE/app/bin/$tool" 2>/dev/null
done
/usr/bin/xattr -d com.apple.quarantine "$HERE/app/bin/ffmpeg" "$HERE/app/bin/ffprobe" >/dev/null 2>&1 || true

printf '\n  MusicPro Studio — tekshiruv\n  Python: %s\n\n  Bu bir necha daqiqa olishi mumkin…\n\n' "$("$PY" -V 2>&1)"
"$PY" -X utf8 -B "$HERE/app/bootstrap.py" --check
STATUS=$?

if [ "$STATUS" -ne 0 ]; then
    printf '\n  Tekshiruv xato bilan tugadi. Batafsil: data/startup.log\n\n' >&2
    read -r -p "Yopish uchun Enter bosing…" _
    exit "$STATUS"
fi

printf '\n  Tekshiruv tugadi. Natija: data/diagnostics.txt\n\n'
