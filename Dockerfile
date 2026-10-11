FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# pip is build-time only. Its vendored copies of urllib3, msgpack and
# setuptools/pkg_resources (declared in pip/_vendor/bom.cdx.json) lag upstream
# security fixes and are flagged by Trivy, so drop it from the runtime image.
COPY sdk/ /sdk/
RUN pip install --no-cache-dir --no-deps /sdk/ \
    && pip uninstall -y pip

COPY backend/ ./
COPY start.py ./start.py

# Run as non-root user (security best practice)
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

CMD ["python", "start.py"]