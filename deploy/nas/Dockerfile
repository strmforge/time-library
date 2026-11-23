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

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TL_DATA_DIR=/data \
    TL_HOST=0.0.0.0 \
    TL_PORT=9850 \
    TL_LLAMA_DIR=/opt/llama

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
COPY tl_server /app/tl_server
# The client install package is served from here (with the skill it carries).
COPY tl_client /app/tl_client
COPY system/skills/time-library /app/system/skills/time-library
# Files unpacked on a NAS storage pool can arrive owner-only; the server runs
# as the NAS user, not root, so make the code readable by everyone.
RUN chmod -R a+rX /app /opt/llama

EXPOSE 9850
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/v1/health' % os.environ.get('TL_PORT', '9850'), timeout=3)"

CMD ["python", "-m", "tl_server"]
