FROM python:3.13-alpine
WORKDIR /site
COPY index.html server.py ./
COPY assets ./assets
USER nobody
CMD ["python", "-u", "server.py"]
