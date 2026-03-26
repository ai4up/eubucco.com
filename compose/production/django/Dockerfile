ARG PYTHON_VERSION=3.9-slim-bullseye

# Define an alias for the specific python version used in this file.
FROM python:${PYTHON_VERSION} AS python

# --- Python build stage ---
FROM python AS python-build-stage

ARG BUILD_ENVIRONMENT=production

# Install apt packages
RUN apt-get update && apt-get install --no-install-recommends -y \
  build-essential \
  libpq-dev

# Requirements are installed here to ensure they will be cached.
COPY ./requirements .

# Create Python Dependency and Sub-Dependency Wheels.
RUN pip wheel --wheel-dir /usr/src/app/wheels \
  -r ${BUILD_ENVIRONMENT}.txt


# --- Python 'run' stage ---
FROM python AS python-run-stage

ARG BUILD_ENVIRONMENT=production
ARG APP_HOME=/app

# Fixed legacy ENV formatting
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV BUILD_ENV=${BUILD_ENVIRONMENT}

WORKDIR ${APP_HOME}

# Create django user/group and initialize required directories with correct permissions
RUN addgroup --system django \
    && adduser --system --ingroup django django \
    && mkdir -p ${APP_HOME}/staticfiles ${APP_HOME}/media ${APP_HOME}/.cache \
    && chown -R django:django ${APP_HOME}

# Consolidated system dependencies, GIS tools, and Node.js 20 (LTS)
RUN apt-get update && apt-get install --no-install-recommends -y \
  libpq-dev \
  gettext \
  netcat \
  gcc \
  postgresql \
  binutils \
  libproj-dev \
  gdal-bin \
  python3-gdal \
  proj-bin \
  ca-certificates \
  curl \
  gnupg \
  # Modern NodeSource installation (Fixes GPG error)
  && mkdir -p /etc/apt/keyrings \
  && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
  && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
  && apt-get update \
  && apt-get install -y nodejs --no-install-recommends \
  # Cleanup layers
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man \
  && apt-get clean

# Copy python dependency wheels from build stage
COPY --from=python-build-stage /usr/src/app/wheels /wheels/

# Install setuptools first, then install python dependencies from wheels
RUN pip install --no-cache-dir --upgrade pip setuptools \
  && pip install --no-cache-dir --no-index --find-links=/wheels/ /wheels/* \
  && rm -rf /wheels/

# Copy scripts and fix line endings/permissions
COPY --chown=django:django ./compose/production/django/entrypoint /entrypoint
COPY --chown=django:django ./compose/production/django/start /start
COPY --chown=django:django ./compose/production/django/celery/worker/start-io /start-celeryworker-io
COPY --chown=django:django ./compose/production/django/celery/worker/start-heavy /start-celeryworker-heavy
COPY --chown=django:django ./compose/production/django/celery/beat/start /start-celerybeat
COPY --chown=django:django ./compose/production/django/api/start /start-api
COPY --chown=django:django ./compose/production/django/celery/flower/start /start-flower

RUN sed -i 's/\r$//g' /entrypoint /start /start-celeryworker-io /start-celeryworker-heavy /start-celerybeat /start-api /start-flower \
    && chmod +x /entrypoint /start /start-celeryworker-io /start-celeryworker-heavy /start-celerybeat /start-api /start-flower

# Copy application code to WORKDIR
COPY --chown=django:django . ${APP_HOME}

# Final ownership check to ensure the django user can write to /app
RUN chown -R django:django ${APP_HOME}

EXPOSE 5000

USER django

ENTRYPOINT ["/entrypoint"]
