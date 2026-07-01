# Creating / updating a data release

End-to-end procedure to publish a dataset version (e.g. `v0.2`) to the server. All data ends up in MinIO; the website/API serve it from there.

> [!NOTE]
> Commands target the **dev** stack — swap `dev.yml`/`-p eubucco-dev`/`.envs/.dev` for the production equivalents to release to prod.

Prereqs on the server: `ssh eubucco` (lands as `flo`; `flo` is not in the docker
group, so every `docker`/`docker compose` needs `sudo`).

### 1. Sync data from HPC to the server
```bash
# building parquet (raw, NUTS-named *.parquet)
ls /p/projects/eubucco/data/7-release/ | xargs -n 1 -P 8 -I {} \
  rsync -avP --inplace /p/projects/eubucco/data/7-release/{} flo@194.163.151.34:/home/flo/eubucco-data/{}

# additional files (stats parquet, metadata xlsx/csv, etc.)
scp /p/projects/eubucco/data/8-additional-files/eubucco_lat_lon.parquet flo@194.163.151.34:/home/flo/
rsync -avP --inplace --no-whole-file --exclude "eubucco_lat_lon.parquet" \
  /p/projects/eubucco/data/8-additional-files/ flo@194.163.151.34:/home/flo/eubucco-additional-files
```

### 2. Stage into the data tree (`/home/eubucco-data`, as root)
The tree mirrors the MinIO layout, **version-first**: `<version>/buildings/` (raw NUTS
parquet for v0.2, country-level zips for v0.1) and `<version>/additional/`.
`ingest_buildings` reads `<version>/buildings/*.parquet`; `upload_extras` reads
`<version>/{additional,buildings}/`:
```bash
sudo mkdir -p /home/eubucco-data/v0.2/buildings /home/eubucco-data/v0.2/additional
sudo mv /home/flo/eubucco-data/*            /home/eubucco-data/v0.2/buildings/     # raw building parquet
sudo mv /home/flo/eubucco_lat_lon.parquet   /home/eubucco-data/v0.2/additional/
sudo rsync -av --inplace /home/flo/eubucco-additional-files/* /home/eubucco-data/v0.2/additional/
# v0.1 country-level buildings are already staged under /home/eubucco-data/v0.1/buildings/
```

### 3. (Optional) Update docs
Update docs for new version. Commit, tag, and push changes.
```bash
git tag v0.2 HEAD
git push --tags
```
Wait for GitHub CI to build and push docs image to DockerHub. Then, ssh into server, pull new docs image, and redeploy:
```bash
cd /home/eubucco
docker pull eubucco/eubucco-docs
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django up --build -d docs
```

### 4. (Optional) Update website
Update compose + pull/rebuild images:
```bash
sudo -E git -C /home/eubucco/ pull
cd /home/eubucco
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django pull
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django up --build -d
```

### 5. Ingest building data (parquet → MinIO, then GPKG/SHP conversion)
Dispatches a Celery chain; the `celeryworker-io` and `celeryworker-heavy` workers must be up.
```bash
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django \
  run --rm django python manage.py ingest_buildings --data-version v0.2 --reupload
```

### 6. Upload the extras (additional files, v0.1 country buildings) to MinIO
One-off container; idempotent (skips objects already present, `--reupload` to overwrite):
```bash
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django \
  run --rm extras-uploader
```

### 7. Generate the building vector tiles (`buildings.pmtiles`)
```bash
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django \
  run -d --name tilegen tile-generator          # long-running; resumable on rerun
sudo docker logs -f tilegen
```

### 8. Generate the coverage choropleth (`coverage-stats.pmtiles` + summary)
```bash
sudo docker compose -f dev.yml -p eubucco-dev --env-file ./.envs/.dev/.django \
  run --rm coverage-generator
```

### 9. Inspect logs
```bash
sudo docker compose -f dev.yml -p eubucco-dev logs --since 5m -f celeryworker-io celeryworker-heavy
```

---

## One-time MinIO setup (per environment)
- **Public read + list** on the data prefixes so downloads work as direct public URLs
  (already configured in prod; the bucket serves PMTiles + downloads anonymously).
- **Download analytics webhook**: configure the bucket's `ObjectAccessed:Get` notification
  to POST to **`/analytics/webhook/minio/`** (moved from the old `data/webhook/minio/`).
