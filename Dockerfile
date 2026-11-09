# syntax=docker/dockerfile:1
# Multi-target image:
#   shop   demo application only
#   lab    shop + Incident Lab (fault scenarios and private ground truth)
#   forge  control plane (API + worker). Contains shop's shared libraries
#          (config schema, config write path, models) but NOT lab/ or scenarios,
#          so the investigator process cannot read ground truth even by accident.
#          tests/unit/test_isolation.py asserts this.

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home /app app
COPY requirements/shop.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

FROM base AS shop
COPY alembic.ini /app/alembic.ini
COPY shop /app/shop
COPY tools /app/tools
USER app
EXPOSE 8000 8001 8002

FROM shop AS lab
USER root
COPY lab /app/lab
USER app
ENTRYPOINT ["python", "-m", "lab"]

FROM base AS forge
COPY requirements/forge.txt /tmp/forge-requirements.txt
RUN pip install -r /tmp/forge-requirements.txt
COPY shop /app/shop
COPY forge /app/forge
USER app
EXPOSE 8080
