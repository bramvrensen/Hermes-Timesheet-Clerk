FROM python:3.12-slim-bookworm

ARG HERMES_REVISION=5fc308a70719a83cccdbba4c0e39c23f5a8239d5
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    TIMESHEET_CLERK_MODE=standalone \
    TIMESHEET_CLERK_STATE_DIR=/data/clerk \
    TIMESHEET_CLERK_HERMES_ROOT=/data/hermes \
    TIMESHEET_CLERK_HERMES_BIN=/opt/hermes/.venv/bin/hermes \
    TIMESHEET_CLERK_UI_BASE_PATH="" TZ=Europe/Amsterdam

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.10.12
RUN mkdir -p /opt/hermes \
    && curl --retry 5 --retry-delay 5 --retry-max-time 90 -fsSL \
       "https://codeload.github.com/NousResearch/hermes-agent/tar.gz/${HERMES_REVISION}" -o /tmp/hermes.tar.gz \
    && tar -xzf /tmp/hermes.tar.gz --strip-components=1 -C /opt/hermes \
    && rm /tmp/hermes.tar.gz \
    && cd /opt/hermes && uv sync --locked --no-dev \
    && /opt/hermes/.venv/bin/hermes --help >/dev/null

WORKDIR /opt/timesheet-clerk
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY timesheet_clerk ./timesheet_clerk
COPY frontend ./frontend
COPY hermes_plugins ./hermes_plugins
COPY skills ./skills
COPY plugin.yaml ./plugin.yaml
RUN useradd --uid 10001 --create-home timesheet-clerk \
    && mkdir -p /data/clerk /data/hermes \
    && chown -R timesheet-clerk:timesheet-clerk /data
USER timesheet-clerk
EXPOSE 8501 8502
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s \
    CMD python -m timesheet_clerk.healthcheck
CMD ["python", "-m", "timesheet_clerk.service"]
