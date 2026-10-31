FROM --platform=linux/amd64 python:3.11-slim

WORKDIR /app

# Scoring runs with --network none: nothing may be fetched at run time.
# HF_* offline flags stop the `datasets` import (a cr-renderer dependency)
# from probing the Hugging Face Hub. Bytecode is compiled at build time.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# System libs skia needs at runtime, plus git (build time only) so pip can
# install the pinned cr-renderer commit straight from its repo.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libgl1 \
    libegl1 \
    libglib2.0-0 \
    fontconfig \
    && rm -rf /var/lib/apt/lists/* \
    # skia-python bundles an older libfontconfig that warns on this unused
    # sample config ("unknown element reset-dirs") on every run.
    && rm -f /usr/share/fontconfig/conf.avail/05-reset-dirs-sample.conf

COPY requirements.txt .
RUN pip install -r requirements.txt \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

COPY chameleon_design_schema_v0.9.json .
COPY brand_kit/ ./brand_kit/
COPY renderer/ ./renderer/
COPY engine/ ./engine/
COPY pipelines/ ./pipelines/

# Warm every cache at build time so the offline run does no first-use work:
# the fontconfig cache, bytecode for our code, and one real render that
# imports the full engine + renderer stack.
RUN fc-cache -f \
    && python -m compileall -q engine pipelines renderer \
    && python -c "import tempfile, pathlib; \
from engine.resize import resize; \
from renderer.converter.convert import render_design_to_png; \
src = {'canvas': {'width': 200, 'height': 100}, 'elements': [ \
 {'id': 't', 'type': 'text', 'x': 10, 'y': 10, 'width': 180, 'height': 40, 'content': 'Warm', \
  'font_family': 'Solstice Sans', 'font_size': 24, 'color': 'rgba(0,0,0,1)'}]}; \
out = resize(src, {'width': 100, 'height': 100}); \
render_design_to_png(out, pathlib.Path('brand_kit/assets'), pathlib.Path(tempfile.mkdtemp()) / 'warm.png')"

# input/ and output/ are mounted as volumes at run time (see README) -
# not baked into the image.
RUN mkdir -p /app/input /app/output

ENTRYPOINT ["python", "-m", "engine.main"]
