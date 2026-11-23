# Time Library server image.
#
# Build from the repository root (a NAS folder keeps the same layout):
#   docker build -f deploy/nas/Dockerfile -t time-library-server .
#
# The model runtime (llama.cpp's llama-server) is pinned and checked by sha256.
# It is downloaded during the build, unless deploy/nas/vendor/llama/ already
# holds it (python deploy/nas/llama_runtime.py --dest deploy/nas/vendor/llama),
# for a NAS that cannot reach GitHub.

FROM python:3.11-slim AS runtime-fetch
# The script is always there; vendor/ only when fetched beforehand.
COPY deploy/nas/llama_runtime.py deploy/nas/vendo[r] /ctx/
RUN python /ctx/llama_runtime.py --dest /opt/llama --prefetched /ctx/llama

# The server's own code, as one layer: an update from the admin page fetches just
# that layer (see tl_server/update.py), so it must be the last one of the image.
FROM python:3.11-slim AS app
COPY tl_server /app/tl_server
# The client install package is served from here (with the skill it carries).
COPY tl_client /app/tl_client
COPY system/skills/time-library /app/system/skills/time-library
# Files unpacked on a NAS storage pool can arrive owner-only; the server runs
# as the NAS user, not root, so make the code readable by everyone.
RUN chmod -R a+rX /app

FROM python:3.11-slim

# What the server's code can count on here: this Python, requirements-vectors.txt,
# the llama.cpp build, the system packages below. Raise it when any of them changes
# in a way newer code needs (tests/server_client/test_update.py keeps watch); such a
# version then asks for a new image instead of an update from the admin page.
ARG TL_RUNTIME=1
LABEL org.time-library.runtime="${TL_RUNTIME}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TL_DATA_DIR=/data \
    TL_HOST=0.0.0.0 \
    TL_PORT=9850 \
    TL_LLAMA_DIR=/opt/llama \
    TL_RUNTIME=${TL_RUNTIME}

# llama-server needs the GNU OpenMP runtime, which the slim image lacks.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Recall by meaning runs a small embedding model with ONNX Runtime (optional for
# the server, part of this image). A NAS that cannot reach PyPI builds with a
# mirror: TL_PIP_INDEX in .env (for example https://mirrors.aliyun.com/pypi/simple/).
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements-vectors.txt /tmp/requirements-vectors.txt
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r /tmp/requirements-vectors.txt \
 && rm /tmp/requirements-vectors.txt

WORKDIR /app
COPY --from=runtime-fetch /opt/llama /opt/llama
# Starts the server, and goes back by itself when an update does not work. Outside
# /app: an update replaces the server's code, never this.
COPY deploy/nas/launcher.py /opt/time-library/launcher.py
RUN chmod -R a+rX /opt/llama /opt/time-library

EXPOSE 9850
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/v1/health' % os.environ.get('TL_PORT', '9850'), timeout=3)"

CMD ["python", "/opt/time-library/launcher.py"]

# Last, and nothing after it.
COPY --from=app /app /app
