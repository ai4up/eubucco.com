"""Download/usage analytics.

The data bucket is public-read, so downloads don't pass through the app. Instead
MinIO is configured to POST an ``ObjectAccessed:Get`` bucket notification here,
which we de-duplicate and forward to Plausible as a custom "S3 Download" event.

The MinIO bucket-notification target must point at ``/analytics/webhook/minio/``.
"""

import hashlib
import json
import logging
from urllib.parse import quote, unquote

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


def _is_new_download(user_ip: str, obj_key: str, ttl: int = 60) -> bool:
    """Return True only the first time we see this (user_ip, obj_key) within `ttl`
    seconds. Uses cache.add() (atomic set-if-not-exists); requires Redis."""
    fingerprint = hashlib.md5(f"{user_ip}:{obj_key}".encode()).hexdigest()
    dedupe_key = f"minio_dl_lock:{fingerprint}"
    return cache.add(dedupe_key, True, ttl)


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

    plausible_api = f"{settings.PLAUSIBLE_API_URL.rstrip('/')}/api/event"
    forwarded_count = 0

    for rec in records:
        if "ObjectAccessed:Get" not in rec.get("eventName", ""):
            continue

        s3_data = rec.get("s3", {})
        source_data = rec.get("source", {})
        req_params = rec.get("requestParameters", {})
        obj_key = unquote(s3_data.get("object", {}).get("key"))

        # Request deduplication
        user_ip = req_params.get("sourceIPAddress", "unknown")
        if not _is_new_download(user_ip, obj_key):
            continue

        # Method detection
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

        # Path extraction: {version}/{type}/{format}/.../{file}
        parts = obj_key.split("/")
        if len(parts) < 3:
            continue  # not a data download path, skip
        version = parts[0]
        data_type = parts[1]
        file_format = parts[2]
        file_name = parts[-1]
        region = file_name.split(".")[0]
        country = region[:2]

        payload = {
            "name": "S3 Download",
            "url": f"https://{settings.PLAUSIBLE_DATA_DOMAIN}/downloads/{quote(obj_key)}",
            "domain": settings.PLAUSIBLE_DATA_DOMAIN,
            "props": json.dumps(
                {
                    "version": version,
                    "type": data_type,
                    "format": file_format,
                    "region": region,
                    "country": country,
                    "method": method,
                    "user_agent": original_ua,
                }
            ),
        }

        # Forward IP/UA so Plausible can derive location & device info.
        if original_ua == "unknown":
            logger.warning("Unknown User-Agent for request: %s", req_params)
            original_ua = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

        headers = {
            "User-Agent": original_ua,
            "X-Forwarded-For": user_ip,
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                plausible_api, json=payload, headers=headers, timeout=5
            )
            if resp.status_code in (200, 202):
                forwarded_count += 1
        except Exception as e:
            logger.error("Plausible error: %s", e)

    return JsonResponse({"status": "ok", "forwarded": forwarded_count})
