# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Web platform for the EUBUCCO dataset (~322M European building footprints): a download UI, an
interactive map explorer, an S3-compatible data lake (MinIO), and a REST API. Cookiecutter-Django
based. Two HTTP services run side by side (Django + FastAPI), with Celery for background jobs.

## Commands

Almost everything runs inside the Docker stack. `local.yml` **builds** the image locally;
`dev.yml`/`production.yml` **pull** prebuilt images from Docker Hub.

```bash
# Start the local stack (builds image)
docker compose -f local.yml up --build -d

# Tests (pytest, settings=config.settings.test, --reuse-db; see pytest.ini)
docker compose -f local.yml run --rm django pytest
docker compose -f local.yml run --rm django pytest eubucco/data/tests.py::ClassName::test_name   # single test
docker compose -f local.yml run --rm django coverage run -m pytest && ... coverage html

# Lint / format (line length 120; config in setup.cfg & .pre-commit-config.yaml)
pre-commit install            # one-time
pre-commit run --all-files    # black + flake8(+isort) + pyupgrade
docker compose -f local.yml run --rm django mypy eubucco

# Django
docker compose -f local.yml run --rm django python manage.py makemigrations
docker compose -f local.yml run --rm django python manage.py migrate
docker compose -f local.yml run --rm django python manage.py shell
docker compose -f local.yml run --rm django python manage.py createsuperuser

# Docs (MkDocs Material)
mkdocs serve

# Regenerate the "Getting Started" tutorial page from its source notebook
# (needs `pygments`; source notebook lives in the sibling `eubucco` repo)
python scripts/render_tutorial_notebook.py \
  ../eubucco/tutorials/website/getting-started-website.ipynb
```

The `/tutorials/getting_started` page is generated from a Jupyter notebook by
`scripts/render_tutorial_notebook.py` (a custom theme-adaptive renderer, not nbconvert). It writes
the include fragment `eubucco/templates/tutorials/_getting_started_notebook.html` and extracts plot
PNGs + the Folium map to `eubucco/static/notebooks/getting-started/`. Edit the notebook in the
`eubucco` repo, then re-run the script and commit the regenerated fragment + assets together. The
downloadable `eubucco/static/notebooks/getting-started.ipynb` is **curated by hand** — the script
intentionally leaves it untouched, so edit it directly when you want to update the download.

The repo carries some pre-existing flake8 debt, so the pre-commit hooks may block commits over code
you didn't touch — committing with `git commit --no-verify` is acceptable here.

Test discovery: pytest only collects `tests.py` and `test_*.py` (pytest.ini). Test files live as
`eubucco/<app>/tests.py`.

Local ports: Django `:8000`, FastAPI `:8001` (+ `/docs`), MinIO `:9000`/console `:9001`,
MailHog `:8025`, Flower `:5555`.

For frontend/template iteration **without Docker**, see `LOCAL_DEVELOPMENT.md` (run `python
manage.py runserver` + `npm run dev` in `theme/static_src/` to watch Tailwind).

## Architecture

### Two independent ASGI servers (not mounted into each other)
- **Django** — `uvicorn config.asgi:application` (`:8000`, started by `compose/*/django/start`).
  Serves templates, admin, the `explore/*` visualizations and the `data/download` UI. Has hybrid
  HTTP/WebSocket routing (`config/asgi.py`, `config/websocket.py`).
- **FastAPI** — `uvicorn eubucco.api.main:api` (`:8001`, started by `compose/*/django/api/start`).
  Standalone; calls `django.setup()` to reuse Django settings/models. Routers in `eubucco/api/v1/`:
  `datalake` (MinIO/NUTS metadata + **direct public download URLs** + bundle zip) and `tiles`
  (on-demand MVT via DuckDB over parquet in MinIO). The data bucket is public-read, so downloads are
  plain public URLs — there is no app-served download endpoint.

### Settings
`config/settings/{base,local,production,test}.py`, selected by `DJANGO_SETTINGS_MODULE`
(defaults to `config.settings.local` when the `DEVELOPMENT` env var is set, else
`config.settings.production`). DB is **PostGIS**; cache + Celery broker/result backend are Redis.
Env files live in `.envs/.{local,dev,production}/{.django,.postgres,.minio}`.

### Celery (queue-specialized workers)
`config/celery_app.py` autodiscovers `eubucco/*/tasks.py`. Queue is set per task via
`@celery_app.task(queue=...)`; each worker consumes one queue:
- **`io_tasks`** (concurrency 4/8) — parquet uploads to MinIO (`upload_parquet_task`).
- **`heavy_tasks`** (concurrency **1**, deliberate OOM isolation) — GeoPackage/Shapefile
  conversion (`convert_spatial_task`).
- **`tiling`** — tiling tasks exist (`tile_region_task`, `tile_join_and_upload` in
  `eubucco/data/tiling.py`; `generate_coverage_tiles_task` in `eubucco/data/coverage.py`) and a
  `start-tiling` worker script exists, but **there is no running tiling worker by default**. Tile
  generation runs via the one-off `tile-generator` container with `--executor local` (in-process
  `ProcessPoolExecutor`), so the Celery tiling path is dormant/optional. Periodic tasks use
  `django_celery_beat` `DatabaseScheduler`.

`eubucco/data/tasks.py` is a thin registry that re-exports the tasks (so autodiscover registers
them); the logic lives in `ingest.py`, `tiling.py`, `coverage.py`, with shared key/upload/URL
helpers in `eubucco/data/storage.py`.

### Data lake (MinIO) conventions
Prefixes in `eubucco/data/constants.py` (`DATASET_PREFIX="buildings"`,
`ADDITIONAL_PREFIX`). **Everything** lives in MinIO. Object keys:
```
{version}/buildings/parquet/nuts_id={id}/{file}.parquet       # raw (NUTS-partitioned, v0.2)
{version}/buildings/{gpkg|shp}/nuts_id={id}/{id}.{ext}        # converted (v0.2)
v0.1/buildings/{gpkg|csv}/{region}.{gpkg.zip|csv.zip}         # legacy country-level (v0.1)
{version}/buildings/tiles/buildings.pmtiles                   # vector tiles
{version}/coverage/coverage-stats.pmtiles (+ -summary.json)   # choropleth
{version}/additional/{file}  (+ additional/metadata.json)     # additional files + descriptions
```
The local source tree (`data/`, mounted at `/app/data`) mirrors this **version-first**:
`data/{version}/buildings/*.parquet` (v0.2 raw NUTS) or `*.{gpkg,csv}.zip` (v0.1 country),
and `data/{version}/additional/*`. `ingest_buildings`/tiling read the parquet; `upload_extras`
uploads the additional files + v0.1 zips.
The data bucket is **public-read + list**; downloads are direct public URLs (the MinIO webhook →
Plausible tracks every GET). Build keys / URLs via `eubucco/data/storage.py` (`parquet_key`,
`public_object_url`, `pmtiles_url`, `upload_if_missing`, …); the low-level client is
`eubucco/data/minio_client.py`.

### Building tile pipeline (`eubucco/data/tiling.py`, `manage.py generate_building_tiles`)
Per-region, parallel: DuckDB `COPY` parquet → FlatGeobuf → `tippecanoe` → per-region `.pmtiles`,
then `tile-join` merges all regions into one `buildings.pmtiles` and uploads to MinIO. Key facts:
- Building geometry is stored in **EPSG:3035** (ETRS89-LAEA); tiles reproject to **EPSG:4326**.
  DuckDB reads the GeoParquet `geometry` (WKB) **natively as GEOMETRY** — no `ST_GeomFromWKB`.
- **Resumable**: finished `region.pmtiles` are skipped, finished `.fgb` reused; both are written
  atomically (temp file + rename), so an interrupted run resumes instead of restarting.
- `tippecanoe`/`tile-join` are compiled into the image (the Dockerfiles), not pip deps.
- The `tile-generator`/`coverage-generator` containers run as `user: root` (the image's `django`
  user can't write the bind-mounted `/app/data`).

### Ingestion orchestration
`ingest_all_by_version(version_tag=...)` (`eubucco/data/ingest.py`) chains the phases (upload →
convert) as Celery chords; trigger it via `manage.py ingest_buildings`. The extras (additional
files, v0.1 country-level buildings) are pushed to MinIO by `manage.py upload_extras`
(compose service `extras-uploader`). See `create-release.md` for the full HPC→server→ingest release
procedure and the README "Operations / Running Jobs" section for the job table.

## Apps (`eubucco/`)
`users` (minimal model, **admin-only** — public auth/allauth removed), `data` (MinIO management +
ingestion/tiling + `data/download` UI), `explore` (visualizations: `explore/map`,
`explore/coverage`, `explore/conflation`), `analytics` (MinIO download webhook → Plausible),
`tutorials`, `api` (FastAPI). Tailwind theme is the `theme/` app (sources in `theme/static_src/`).

## Deploy flow (image-based)
CI builds images from `compose/production/django/Dockerfile` and pushes to Docker Hub:
- push to **`dev`** branch → `eubucco/eubucco.com:dev` (`.github/workflows/build-dev.yml`)
- push to **`main`** → `eubucco/eubucco.com:production` (`build-prod.yml`)

The server (single VM) runs `dev.yml` (dev) and `production.yml` (prod) which reference those image
tags — only the URL differs between them, so keep dev and prod service config identical. Compose
file changes reach the server via `git pull`; code changes reach it via the rebuilt image
(Watchtower / `docker compose pull`). `dev.yml`/`production.yml` are invoked with
`-p eubucco-dev`/`-p eubucco` and `--env-file .envs/.<env>/.django`.

## Server access & operations

Both dev and prod run on a single Contabo VM (`194.163.151.34`, host `vmd100592`). SSH in with the
`eubucco` alias (lands as user **`flo`**):

```bash
ssh eubucco
```

Key facts about the server:
- Repo lives at **`/home/eubucco`** (on branch `main`, owned by root — editing files there needs
  `sudo`). Data lives at **`/home/eubucco-data`** (mounted into containers as `/app/data`); raw
  release parquet is staged under `/home/eubucco-data/v0.2/buildings/`.
- **`flo` is not in the docker group** — every `docker`/`docker compose` command needs `sudo`
  (sudo password is not stored in this repo; ask the maintainer).
- Compose projects: dev = `-f dev.yml -p eubucco-dev`, prod = `-f production.yml -p eubucco`,
  always with `--env-file ./.envs/.<env>/.django`.

```bash
# Bring the dev stack up / pull new images
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django pull
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django up --build -d

# Run a one-off management command (e.g. regenerate building tiles)
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django run --rm tile-generator

# Trigger building ingestion (parquet upload + GPKG/SHP conversion via Celery)
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django \
  run --rm django python manage.py ingest_buildings --data-version v0.2 --reupload
# Upload the extras (additional files, v0.1 country buildings) into MinIO
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django run --rm extras-uploader

# Logs / debugging
sudo docker compose -f dev.yml -p eubucco-dev logs --since 5m -f celeryworker-heavy
sudo docker exec eubucco-dev-redis-1 redis-cli LLEN tiling   # inspect a Celery queue depth
```

Long one-off jobs (tile generation over all NUTS regions) are best run detached
(`run -d --name <name>`) and followed with `sudo docker logs -f <name>`, since they take a while
and the tile pipeline resumes if re-run. The full release procedure (HPC→server rsync→ingest) is
in `create-release.md`.
