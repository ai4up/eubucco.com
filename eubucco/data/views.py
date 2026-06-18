import hashlib
import json
import logging
import os
from urllib.parse import quote, unquote

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


def _is_new_download(user_ip: str, obj_key: str, ttl: int = 60) -> bool:
    """
    Return True only the first time we see this (user_ip, obj_key) in the last `ttl` seconds.
    Uses cache.add() (atomic set-if-not-exists); requires a real cache backend (e.g. Redis).
    """
    fingerprint = hashlib.md5(f"{user_ip}:{obj_key}".encode()).hexdigest()
    dedupe_key = f"minio_dl_lock:{fingerprint}"
    return cache.add(dedupe_key, True, ttl)


@cache_page(60 * 60)
def map(request):
    return render(request, "data/map.html", {"tile_url": os.environ["TILE_URL"]})


def explorer(request):
    """Building explorer backed by pre-generated PMTiles served from MinIO."""
    minio_public = os.getenv("MINIO_PUBLIC_ENDPOINT", "http://localhost:9000").rstrip("/")
    bucket = os.getenv("MINIO_BUCKET", "eubucco")
    version = os.getenv("BUILDINGS_VERSION", "v0.2")
    pmtiles_url = f"{minio_public}/{bucket}/{version}/buildings/tiles/buildings.pmtiles"
    return render(request, "data/explorer.html", {"pmtiles_url": pmtiles_url})


def coverage(request):
    """Regional coverage and quality visualization."""
    # Use direct MinIO URL instead of presigned URL
    # Since the PMTiles file is served from MinIO, construct a direct URL
    minio_public_endpoint = os.getenv("MINIO_PUBLIC_ENDPOINT", "http://localhost:9000")
    minio_bucket = os.getenv("MINIO_BUCKET", "eubucco")
    version = os.getenv("BUILDINGS_VERSION", "v0.2")
    base = f"{minio_public_endpoint}/{minio_bucket}/{version}/coverage"
    pmtiles_url = f"{base}/coverage-stats.pmtiles"
    summary_url = f"{base}/coverage-summary.json"

    logger.info(f"Coverage PMTiles URL: {pmtiles_url}")

    return render(
        request,
        "data/coverage.html",
        {
            "pmtiles_url": pmtiles_url,
            "summary_url": summary_url,
            "nuts_names_url": static("metadata/nuts_names.json"),
        },
    )

@csrf_exempt
@require_POST
def minio_webhook(request):
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    records = body.get("Records", [])
    if not records:
        return HttpResponse(status=200)

    # SITE CONFIG - Ensure this matches your Plausible dashboard domain
    plausible_api = f"{settings.PLAUSIBLE_API_URL.rstrip('/')}/api/event"
    forwarded_count = 0

    for rec in records:
        if "ObjectAccessed:Get" not in rec.get("eventName", ""):
            continue

        # DATA EXTRACTION
        s3_data = rec.get("s3", {})
        source_data = rec.get("source", {})
        req_params = rec.get("requestParameters", {})
        obj_key = unquote(s3_data.get("object", {}).get("key"))

        # REQUEST DEDUPLICATION
        user_ip = req_params.get("sourceIPAddress", "unknown")
        if not _is_new_download(user_ip, obj_key):
            continue

        # METHOD DETECTION
        original_ua = source_data.get("userAgent", "unknown")
        ua_lower = original_ua.lower()
        if "minio (linux; x86_64) minio-py" in ua_lower:
            method = "Bundle download"
        elif any(x in ua_lower for x in ["mozilla", "chrome", "safari", "console"]):
            method = "Browser/Portal"
        elif "aws-cli" in ua_lower or "mc/release" in ua_lower:
            method = "CLI"
        elif "duckdb" in ua_lower:
            method = "DuckDB"
        elif "python" in ua_lower:
            method = "Python"
        else:
            method = "Other"

        # PATH EXTRACTION
        parts = obj_key.split("/")
        if len(parts) < 3:
            continue  # not a data download path, skip
        version = parts[0]
        data_type = parts[1]
        file_format = parts[2]
        file_name = parts[-1]
        region = file_name.split(".")[0]
        country = region[:2]

        # ENRICHED PAYLOAD
        payload = {
            "name": "S3 Download",
            "url": f"https://{settings.PLAUSIBLE_DATA_DOMAIN}/downloads/{quote(obj_key)}",
            "domain": settings.PLAUSIBLE_DATA_DOMAIN,
            "props": json.dumps({
                "version": version,
                "type": data_type,
                "format": file_format,
                "region": region,
                "country": country,
                "method": method,
                "user_agent": original_ua
            }),
        }

        # 5. FORWARDING WITH IP/UA FOR LOCATION & DEVICE INFO
        if original_ua == "unknown":
            logger.warning(f"Unknown User-Agent for request: {req_params}")
            original_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        headers = {
            "User-Agent": original_ua,
            "X-Forwarded-For": user_ip,
            "Content-Type": "application/json"
        }

        try:
            resp = requests.post(plausible_api, json=payload, headers=headers, timeout=5)
            if resp.status_code in (200, 202):
                forwarded_count += 1
        except Exception as e:
            logger.error(f"Plausible error: {e}")

    return JsonResponse({"status": "ok", "forwarded": forwarded_count})
