"""Import an ECI electoral roll (EPIC) CSV into encrypted voter profiles.

Usage:
    python manage.py import_electoral_roll path/to/roll.csv --dry-run
    python manage.py import_electoral_roll path/to/roll.csv

Expected columns (header row required, case-insensitive):
    epic, username, first_name, last_name, residence, country,
    education, occupation, marital_status, aadhaar

The EPIC number and every personal field are encrypted before they touch the
database. Only a one-way ``epic_hash`` is stored in cleartext (for matching and
de-duplication), so no operator can read the roll from the database alone.
"""

import csv
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from Vote import crypto
from Vote.models import UserProfile

SENSITIVE_FIELDS = [
    "first_name",
    "last_name",
    "residence",
    "country",
    "education",
    "occupation",
    "marital_status",
]


class Command(BaseCommand):
    help = "Import an ECI electoral roll (EPIC) CSV into encrypted profiles."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate only; write nothing.",
        )

    def handle(self, *args, **options):
        path = Path(options["csv_path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")
        dry_run = options["dry_run"]

        created = updated = skipped = 0
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")
            for row_number, raw in enumerate(reader, start=2):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
                epic = row.get("epic", "")
                username = row.get("username", "")
                if not epic or not username:
                    skipped += 1
                    self.stderr.write(f"Row {row_number}: missing epic/username, skipped.")
                    continue

                details = {field: row.get(field, "") for field in SENSITIVE_FIELDS}
                aadhaar = row.get("aadhaar", "")
                identity_hash = (
                    crypto.hash_hex("aadhaar", aadhaar.replace(" ", ""))
                    if aadhaar
                    else None
                )

                if dry_run:
                    self.stdout.write(
                        f"Row {row_number}: epic={crypto.mask_epic(epic)} "
                        f"user={username} fields={len(details)}"
                    )
                    continue

                with transaction.atomic():
                    user, user_created = User.objects.get_or_create(username=username)
                    profile, profile_created = UserProfile.objects.update_or_create(
                        user=user,
                        defaults={
                            "id": profile_id_or_username(user, username),
                            "epic_hash": crypto.epic_hash(epic),
                            "epic_encrypted": crypto.encrypt_pii(epic.upper()),
                            "encrypted_details": crypto.encrypt_details(details),
                            "aadhaar_encrypted": (
                                crypto.encrypt_pii(aadhaar) if aadhaar else ""
                            ),
                            "identity_hash": identity_hash,
                        },
                    )
                if user_created or profile_created:
                    created += 1
                else:
                    updated += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: nothing written."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Imported electoral roll: {created} created, {updated} updated, "
                    f"{skipped} skipped."
                )
            )


def profile_id_or_username(user, username):
    """Keep an existing profile id, otherwise use the username as the roll id."""
    existing = UserProfile.objects.filter(user=user).first()
    return existing.id if existing else username