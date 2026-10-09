"""Seed a reproducible demo election: users, electoral roll, contests, records.

Run with:  python manage.py seed_demo
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from records.models import Records
from Vote import crypto
from Vote.models import Candidate, Election, Position, UserProfile

# username, password, is_superuser, electoral-roll id
VOTERS = [
    ("thesrivas", "thesri1234", True, "admin"),
    ("khatrimann", "khatri1234", False, "4"),
    ("guptaabhishek", "gupta1234", False, "1"),
    ("guptaarchit", "gupta1234", False, "2"),
    ("kanyalakshya", "kanya1234", False, "3"),
    ("anurag", "anu123456", False, "201600713"),
]

CONTESTS = [
    (
        "General Secretary",
        "The senior representative of the student body.",
        [
            ("Divyanshu Gupta", "Head of the debate society."),
            ("Akshay Garg", "Two years on the cultural committee."),
            ("Anurag Srivastava", "Founder of the coding club."),
        ],
    ),
    (
        "Deputy General Secretary",
        "Assists the General Secretary.",
        [
            ("Apoorv Agarwal", "Leads the sports council."),
            ("Abhinav Chopra", "Runs the media cell."),
        ],
    ),
]


class Command(BaseCommand):
    help = "Create demo users, electoral roll, an election and sample candidates."

    @transaction.atomic
    def handle(self, *args, **options):
        for username, password, is_super, roll_id in VOTERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"is_superuser": is_super, "is_staff": is_super},
            )
            if created:
                user.set_password(password)
                user.save()
            UserProfile.objects.update_or_create(
                id=roll_id,
                defaults={"user": user},
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(VOTERS)} voters."))

        election = Election.objects.filter(is_active=True).first()
        if election is None:
            _, public_pem = crypto.load_or_create_rsa_keypair("election")
            election = Election.objects.create(
                name="National Assembly Election (Demo)",
                description="Reference demo of an encrypted, anonymous ballot.",
                is_active=True,
                key_name="election",
                public_key_pem=public_pem,
            )

        for name, about, candidates in CONTESTS:
            contest, _ = Position.objects.get_or_create(
                election=election,
                position=name,
                defaults={"about": about, "no_of_candidates": len(candidates)},
            )
            for candidate_name, description in candidates:
                Candidate.objects.get_or_create(
                    candidate=contest,
                    name=candidate_name,
                    defaults={"Description": description},
                )
        self.stdout.write(
            self.style.SUCCESS(f"Election '{election.name}' ready with contests.")
        )

        Records.objects.get_or_create(
            id="201600713",
            defaults={
                "first_name": "Anurag",
                "last_name": "Srivastava",
                "residence": "Majitar",
                "country": "India",
                "education": "B.Tech CSE",
                "occupation": "Student",
                "marital_status": "Single",
                "bio": "Demo voter profile.",
            },
        )
        self.stdout.write(self.style.SUCCESS("Demo data complete."))
