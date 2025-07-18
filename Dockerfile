FROM ghcr.io/astral-sh/uv:python3.12-alpine

RUN apk add \
    build-base \
    ffmpeg \
    libffi-dev \
    opus-dev \
    sqlite

ADD . /jukebox
WORKDIR /jukebox
RUN uv sync --frozen
CMD ["uv", "run", "src/main.py"]
