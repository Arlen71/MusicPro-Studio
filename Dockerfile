# MusicPro Studio online (cloud/gateway.py) — deployed on Railway.
# The desktop packages do not use this file.
FROM python:3.13-slim-trixie

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg util-linux \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --create-home --uid 10001 musicpro \
 && ffmpeg -hide_banner -version | head -1

WORKDIR /srv/musicpro
COPY app ./app
COPY cloud ./cloud
RUN rm -rf app/tests app/bin && python -m compileall -q app cloud

ENV DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

# Railway mounts the volume owned by root: hand its top folder to the service
# user, then drop privileges for the server and every FFmpeg it starts.
CMD ["sh", "-c", "mkdir -p \"$DATA_DIR\" && chown musicpro:musicpro \"$DATA_DIR\" && exec setpriv --reuid=musicpro --regid=musicpro --init-groups python -B cloud/gateway.py"]
