from pathlib import Path

from django.core.management.base import BaseCommand

from eubucco.data import storage
from eubucco.data.constants import ADDITIONAL_PREFIX, DATASET_PREFIX, EXAMPLES_PREFIX

# Local source dirs (under --source-root) mapped to their MinIO top-level prefix.
# additional/examples are flat; buildings are country-level (format-partitioned).
KINDS = {
    "additional": ADDITIONAL_PREFIX,
    "examples": EXAMPLES_PREFIX,
    "buildings": DATASET_PREFIX,
}
_BUILDING_SUFFIXES = {".gpkg.zip": "gpkg", ".csv.zip": "csv"}


class Command(BaseCommand):
    help = (
        "Upload the 'extras' (additional files, examples, and legacy v0.1 "
        "country-level buildings) from the local data tree into MinIO so everything "
        "is served from object storage. Idempotent: existing objects are skipped "
        "unless --reupload. Layout expected under <source-root>:\n"
        "  additional/<version>/*        -> <version>/additional/<file>\n"
        "  examples/<version>/*          -> <version>/examples/<file>\n"
        "  buildings/<version>/v0_1-<R>.{csv,gpkg}.zip -> <version>/buildings/{csv,gpkg}/<R>.{ext}"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-root",
            default="data",
            help="Root of the local data tree (mounted at /app/data in containers).",
        )
        parser.add_argument(
            "--version",
            default=None,
            help="Only upload this version (e.g. v0.1). Default: every version dir found.",
        )
        parser.add_argument(
            "--kinds",
            default=",".join(KINDS),
            help=f"Comma-separated subset of {','.join(KINDS)}.",
        )
        parser.add_argument(
            "--reupload",
            action="store_true",
            help="Overwrite objects that already exist in MinIO.",
        )

    def handle(self, *args, **options):
        root = Path(options["source_root"])
        only_version = options["version"]
        kinds = [k.strip() for k in options["kinds"].split(",") if k.strip()]
        reupload = options["reupload"]
        storage.ensure_bucket()

        uploaded = skipped = 0
        for kind in kinds:
            if kind not in KINDS:
                self.stderr.write(
                    self.style.WARNING(f"Unknown kind '{kind}', skipping")
                )
                continue
            kind_dir = root / kind
            if not kind_dir.is_dir():
                self.stdout.write(f"  {kind}: no '{kind_dir}' dir, skipping")
                continue

            for version_dir in sorted(p for p in kind_dir.iterdir() if p.is_dir()):
                version = version_dir.name
                if only_version and version != only_version:
                    continue
                self.stdout.write(self.style.MIGRATE_HEADING(f"{kind} / {version}"))
                for path in sorted(version_dir.glob("*")):
                    if not path.is_file() or path.name.startswith("."):
                        continue
                    key = self._object_key(kind, version, path.name)
                    if key is None:
                        self.stderr.write(
                            self.style.WARNING(f"  skip (unrecognised): {path.name}")
                        )
                        continue
                    if storage.upload_if_missing(path, key, reupload=reupload):
                        uploaded += 1
                        self.stdout.write(f"  ✓ {path.name} -> {key}")
                    else:
                        skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {uploaded} uploaded, {skipped} skipped (already present)."
            )
        )

    def _object_key(self, kind, version, filename):
        if kind == "buildings":
            prefix = f"{version.replace('.', '_')}-"  # e.g. v0.1 -> "v0_1-"
            for suffix, fmt in _BUILDING_SUFFIXES.items():
                if filename.endswith(suffix):
                    region = filename.removesuffix(suffix).removeprefix(prefix)
                    return storage.legacy_buildings_key(
                        version, fmt, f"{region}{suffix}"
                    )
            return None  # unknown buildings file
        # additional / examples are flat under {version}/{kind}/
        return f"{version}/{KINDS[kind]}/{filename}"
