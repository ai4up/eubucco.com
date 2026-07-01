# EUBUCCO Website

> A web platform for exploring and accessing the EUBUCCO dataset.

[![Built with Cookiecutter Django](https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg?logo=cookiecutter)](https://github.com/cookiecutter/cookiecutter-django/)
[![Black code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## About

**EUBUCCO** is a scientific database of individual building footprints for **322+ million buildings** across the 27 European Union countries, Norway, Switzerland, and the UK. This repository contains the web platform that provides:

- **Data Download Interface** - Download building data by region, country, or custom filters
- **Interactive Map Explorer** - Browse and visualize building data across Europe
- **Data Lake** - S3-compatible object storage for storing and distributing EUBUCCO data
- **RESTful API** - Programmatic access to building data and more
- **Documentation** - Comprehensive guides for data access and usage

The platform serves as the primary interface for researchers, urban planners, and developers working with European building stock data.


## Architecture

### Tech Stack

**Backend**
- **Django** - Main web framework
- **MinIO** - S3-compatible object storage
- **PostGIS** - Geospatial database
- **FastAPI** - High-performance API server
- **Redis** - Caching and Celery broker
- **Celery** - Asynchronous task processing
- **Flower** - Celery monitoring
- **MkDocs + Material**  - Documentation rendering

**Frontend**
- **Django Templates** - Server-side rendering
- **Tailwind CSS** - Utility-first CSS framework
- **Leaflet** - Interactive maps

**Infrastructure**
- **Docker & Docker Compose** - Containerization
- **Nginx** (production) - Reverse proxy
- **Traefik** (production) - Load balancer
- **Portainer** (production) - Container management
- **Watchtower** (production) - Container updates
- **Plausible** (production) - Analytics

**Data Processing**
- **DuckDB** - Analytical database for Parquet queries
- **PyArrow** - Parquet file handling
- **GeoPandas** - Geospatial data manipulation

### Project Structure

```
eubucco/
├── config/             # Django configuration
│   ├── settings/       # Environment-specific settings
│   └── urls.py         # URL routing
├── eubucco/            # Django apps
│   ├── analytics/      # Download analytics (MinIO webhook → Plausible)
│   ├── api/            # FastAPI endpoints
│   │   └── v1/         # API version 1
│   │       ├── tiles.py      # Vector tile generation
│   │       └── datalake.py   # Data lake access (public download URLs + bundle zip)
│   ├── data/           # MinIO data management, ingestion/tiling jobs, /data/download UI
│   ├── explore/        # Visualizations: explore/map, explore/coverage, explore/conflation
│   ├── tutorials/      # Jupyter notebook tutorials + home-page embeds
│   ├── templates/      # Django templates
│   ├── static/         # Static assets
│   └── users/          # Minimal user model (Django admin only; no public auth)
├── compose/            # Docker Compose configurations
│   ├── local/          # Local development
│   └── production/     # Production deployment
├── docs/               # Documentation (MkDocs)
├── requirements/       # Python dependencies
└── theme/              # Frontend theme & Tailwind sources
```

## API Documentation

Auto-generated docs (Swagger UI): http://localhost:8001/docs

### Vector Tiles

Get Mapbox Vector Tiles (MVT) for building footprints:

```
GET /v0.1/tiles/{z}/{x}/{y}.pbf
```

**Parameters:**
- `z`, `x`, `y`: Tile coordinates (zoom, x, y)
- `include_attributes`: Comma-separated list of attributes (default: `id,height,construction_year,type`)

**Example:**
```bash
curl http://localhost:8001/v0.1/tiles/10/512/512.pbf
```

### Data Lake API

**List all NUTS partitions:**
```
GET /v0.1/datalake/nuts/{version}
```

**Get specific partition:**
```
GET /v0.1/datalake/nuts/{version}/{nuts_id}
```

**Download bundle:**
```
GET /v0.1/datalake/nuts/{version}/{nuts_prefix}/bundle?format=parquet
```


## Deployment

Development and production deployment uses Docker Compose with additional services:

```bash
docker compose -f dev.yml -p eubucco-dev --env-file <path-to-file> up -d
```

```bash
docker compose -f production.yml -p eubucco --env-file <path-to-file> up -d
```

Production configuration includes:
- Traefik for reverse proxy and SSL
- Watchtower for automatic container updates
- Portainer for container management
- Plausible for analytics

See `compose/production/` for production-specific configurations.

**Access production services:**
- Main website: https://eubucco.com
- API server: https://api.eubucco.com
- API docs: https://api.eubucco.com/docs
- Documentation: https://docs.eubucco.com
- Flower (Celery monitoring): https://tasks.eubucco.com
- Portainer (container management): https://docker.eubucco.com
- Plausible (analytics): https://analytics.eubucco.com
- Traefik dashboard: https://traefik.eubucco.com
- MinIO (S3 object storage): https://s3.eubucco.com/
- MinIO console: https://minio-console.eubucco.com/


## Development


### Prerequisites

- [Docker](https://www.docker.com/get-started) and Docker Compose


### Code Style

- **Python**: Follow [Black](https://black.readthedocs.io/) formatting
- **Type hints**: Use type hints where possible
- **Docstrings**: Follow Google-style docstrings
- **Pre-commit**: Install [pre-commit](https://pre-commit.com/) hooks: `pre-commit install`


### Local Setup

1. **Set up environment variables**
   ```bash
   .envs/.local/.django
   .envs/.local/.postgres
   .envs/.local/.minio
   ```

2. **Start the development environment**
   ```bash
   docker compose -f local.yml up --build -d
   ```

3. **Create a superuser**
   ```bash
   docker compose -f local.yml run --rm django python manage.py createsuperuser
   ```

4. **Access the application**
   - Main website: http://localhost:8000
   - API server: http://localhost:8001
   - API docs: http://localhost:8001/docs
   - MinIO S3 endpoint: http://localhost:9000
   - MinIO console: http://localhost:9001
   - MailHog (email testing): http://localhost:8025
   - Flower (Celery monitoring): http://localhost:5555


### Documentation

Build and serve docs locally with MkDocs:

```
mkdocs serve
```

### Testing

Run the test suite:

```bash
# Run all tests
docker compose -f local.yml run --rm django pytest

# Run with coverage
docker compose -f local.yml run --rm django coverage run -m pytest
docker compose -f local.yml run --rm django coverage html
```


### Common Development Tasks

**Run tests**
```bash
docker compose -f local.yml run --rm django pytest
```

**Run type checking**
```bash
docker compose -f local.yml run --rm django mypy eubucco
```

**Format code**
```bash
docker compose -f local.yml run --rm django black .
```

**Create database migrations**
```bash
docker compose -f local.yml run --rm django python manage.py makemigrations
```

**Run database migrations**
```bash
docker compose -f local.yml run --rm django python manage.py migrate
```

**Access Django shell**
```bash
docker compose -f local.yml run --rm django python manage.py shell
```

**Regenerate the "Getting Started" tutorial page**

The `/tutorials/getting_started` page is rendered from a single Jupyter notebook by a custom
theme-adaptive renderer (not nbconvert). The notebook at
`eubucco/static/notebooks/getting-started.ipynb` is both the file users download *and* the source
the page is built from, so the two never drift. To update the tutorial, edit that notebook, then:

```bash
# needs `pygments`; reads the in-repo notebook by default
python scripts/render_tutorial_notebook.py
```

This rewrites the include fragment `eubucco/templates/tutorials/_getting_started_notebook.html`
and the extracted plot/Folium assets under `eubucco/static/notebooks/getting-started/`. Commit the
notebook, the regenerated fragment, and the assets together.


## Operations / Running Jobs

Jobs fall into three buckets by **how they are triggered**. The full release order
(rsync → ingest → upload extras → tiles → coverage) lives in `create-release.md`.

### 1. Runtime async (Celery — automatic)
The web app dispatches these; dedicated workers consume them (no manual trigger):
- `io_tasks` worker — parquet uploads to MinIO (`upload_parquet_task`).
- `heavy_tasks` worker (concurrency 1, OOM-isolated) — GPKG/SHP conversion (`convert_spatial_task`).
- `tiling` worker (optional) — Celery path for tile tasks; tiling normally runs via the
  one-off generator below instead.

Monitor with Flower (`:5555`) or `docker compose ... logs -f celeryworker-io celeryworker-heavy`.

### 2. One-off release jobs (Django management commands)
Run explicitly, on demand. Locally via `docker compose -f local.yml run --rm django python manage.py <cmd>`;
on the server the data-bearing ones are also exposed as one-off compose services (profile `generators`).

| Job | Command | When to run |
|-----|---------|-------------|
| Ingest buildings | `manage.py ingest_buildings --data-version v0.2 [--reupload]` | New/updated building parquet in `data/s3/<version>/`. Dispatches the upload→convert Celery chain (workers must be up). |
| Upload extras | `manage.py upload_extras [--data-version v0.1] [--reupload]` (svc: `extras-uploader`) | New additional files / examples / v0.1 buildings under `data/{additional,examples,buildings}/`. Idempotent. |
| Building tiles | `manage.py generate_building_tiles --data-version v0.2` (svc: `tile-generator`) | After ingest, to (re)build `buildings.pmtiles`. Resumable; long-running. |
| Coverage tiles | `manage.py generate_coverage_tiles --data-version v0.2` (svc: `coverage-generator`) | After `region-stats.parquet` changes, to rebuild the choropleth + summary. |

Example (server, dev stack):
```bash
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django run --rm extras-uploader
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django run --rm tile-generator
```

### 3. Local preprocessing scripts (developer machine, commit the output)
Run on your machine; the generated artifacts are committed:
- `python scripts/render_tutorial_notebook.py` — regenerate the Getting Started page (see above).
- `python scripts/build_country_stats.py` — aggregate NUTS3 stats → per-country dashboard JSON.

### MinIO download analytics
Downloads are direct public-URL GETs against MinIO (no app round-trip). MinIO is configured
to POST an `ObjectAccessed:Get` bucket notification to **`/analytics/webhook/minio/`**, which
de-duplicates and forwards each download to Plausible.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


## Contact

- **Email**: nachtigall@tu-berlin.de
- **Website**: https://eubucco.com
- **Documentation**: https://docs.eubucco.com
- **Issues**: https://github.com/ai4up/eubucco/issues

## Related Resources

- [ai4up/eubucco](https://github.com/ai4up/eubucco) - Main repository
- [ai4up/eubucco-conflation](https://github.com/ai4up/eubucco-conflation) - Matching and merging repository
- [ai4up/eubucco-features](https://github.com/ai4up/eubucco-features) - Feature engineering repository for building attribute prediction
- [ai4up/ufo-prediction](https://github.com/ai4up/ufo-prediction) - Building attribute prediction repository
