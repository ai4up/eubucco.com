# S3 download analytics (MinIO → Plausible)

This system implements a server-side telemetry bridge designed to capture and enrich S3 object interaction data. By hooking into storage-level events, it provides a comprehensive view of dataset consumption patterns—tracking everything from browser downloads to programmatic access via CLI tools and database engines—without requiring front-end JavaScript or client-side instrumentation. It functions by intercepting raw file access events and relaying them as enriched "Custom events" to a Plausible Analytics instance.

### Overview of the Setup

The architecture relies on four distinct layers:

1. **MinIO (Storage):** Detects when a file is accessed via the `ObjectAccessed:Get` event.
2. **mc-setup (Configuration):** A sidecar container that configures MinIO to send those events to a specific URL (the Django Webhook).
3. **Django (Bridge):** Receives the raw S3 data, cleans it, deduplicates it, and prepares it for analytics.
4. **Plausible (Analytics):** Receives a standard HTTP POST from Django containing enriched download metadata.

---

### Critical Implementation Tweaks


#### 1. Atomic Deduplication via Redis

**The Problem:** Clients like `aws-cli` or `duckdb` often download files in multiple parts (parallel chunks). This triggers multiple MinIO events for a single file download, which would inflate your analytics by 10x or more.
**The Tweak:** The `_is_new_download` function uses `cache.add()` in Redis. This is an **atomic "set-if-not-exists"** operation. If a second event for the same IP and file arrives within 60 seconds, it is ignored.

#### 2. User-Agent Signature Detection

**The Problem:** Standard analytics only tell you "something happened."
**The Tweak:** The logic in `views.py` inspects the User-Agent strings to categorize *how* people are accessing data. It differentiates between a **Browser/Portal** visit, a **CLI** command, or a **DuckDB** query. For `User-Agent` headers to be present, a `audit_webhook` is required (`notify_webhook` doesn't include these details).

#### 3. IP and UA Spoofing for Geo-Location

**The Problem:** If Django simply forwards the event, Plausible thinks the "visitor" is your server's IP address (showing all downloads coming from your data center).
**The Tweak:** The bridge manually sets the `X-Forwarded-For` and `User-Agent` headers in the `requests.post` call. This "spoofs" the request so Plausible attributes the download to the **original user's** country and device.

#### 4. The ARN Registration Sequence

**The Problem:** You cannot simply tell a bucket to send events to a webhook; the webhook must be "registered" as a valid destination first.
**The Tweak:** The `mc-setup` entrypoint follows a strict 3-step dance:

1. Define the `audit_webhook` and `notify_webhook` endpoint. [^1][^2]
2. **Restart MinIO** (required for the service to generate the internal Amazon Resource Name / ARN).
3. Only then run `mc event add` using the newly created ARN.

#### 5. Path-Based Metadata Extraction

**The Problem:** S3 object keys are just flat strings (e.g., `v0.1/spatial/parquet/italy.parquet`).
**The Tweak:** The view splits the string to extract `version`, `data_type`, and `region` (e.g., "italy"). These are passed to Plausible as **Custom Properties**, allowing you to filter your analytics dashboard by specific regions or data versions.


#### 6. Internal Networking and "Hairpin NAT"

**The Problem:** In many production environments, a container trying to reach its own host via a public domain (e.g., `https://analytics.eubucco.com`) fails because the request hits the firewall from the inside and is dropped (Hairpin NAT).
**The Tweak:**
* **Internal Routing:** The `PLAUSIBLE_API_URL` was changed from the public HTTPS address to the internal Docker address: `http://plausible:8000`. This bypasses the public internet and SSL overhead entirely.
* **Network Alias:** To give MinIO a stable target, a `django-webhook` alias was added to the Django service within the Docker network.
* **Security:** `django-webhook` was added to `DJANGO_ALLOWED_HOSTS` in `production.py` so Django accepts the internal traffic.


---

### Operational Requirements

* **Redis:** Must be active as the cache backend for deduplication.
* **CSRF Exemption:** The `minio_webhook` view is marked `@csrf_exempt` because MinIO cannot provide a Django-compliant CSRF token.
* **Service Ordering:** `minio-setup` depends on both `minio` and `django` to ensure the target is ready before it attempts to register the webhook.

[^1]: A `notify_webhook` is required to generate a ARN, apparently defining an `audit_webhook` does not create one.
[^2]: `django` service needs to be up and running, since MinIO's `notify_webhook` sends a test request to validate the target endpoint.