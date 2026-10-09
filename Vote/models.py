from django.contrib.auth.models import User
from django.db import models


class Election(models.Model):
    """A single election/ referendum. Ballots are encrypted to its public key."""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=False)
    results_published = models.BooleanField(default=False)
    public_key_pem = models.TextField(blank=True, default="")
    key_name = models.CharField(max_length=100, default="election")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Position(models.Model):
    """A contest/office within an election (e.g. "President")."""

    election = models.ForeignKey(
        Election, on_delete=models.CASCADE, related_name="positions", null=True, blank=True
    )
    position = models.CharField(max_length=50)
    no_of_candidates = models.IntegerField(default=0)
    about = models.TextField(default="", blank=True)

    def __str__(self):
        return self.position


class Candidate(models.Model):
    candidate = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="candidates")
    name = models.CharField(max_length=50)
    Description = models.TextField()
    image = models.ImageField(upload_to="Vote/static/Vote", blank=True)
    votes = models.IntegerField(default=0)

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    """Electoral-roll entry for an authenticated user.

    Speeds up identity decisions and stores voter PII encrypted at rest. The
    ``id`` is the voter's roll number / unique id and is used as the face
    recognition label. ``identity_hash`` is unique so one Aadhaar identity can
    only ever be attached to one account.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    voted = models.BooleanField(default=False)
    id = models.CharField(max_length=100, primary_key=True)
    identity_hash = models.CharField(
        max_length=64, blank=True, null=True, unique=True
    )
    aadhaar_encrypted = models.TextField(blank=True, default="")
    aadhaar_verified = models.BooleanField(default=False)
    biometric_verified = models.BooleanField(default=False)
    face_enrolled = models.BooleanField(default=False)
    # ECI electoral-roll (EPIC) data, never stored in plaintext.
    epic_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    epic_encrypted = models.TextField(blank=True, default="")
    encrypted_details = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    def __str__(self):
        return self.user.username


class VoterBallotRecord(models.Model):
    """One row per (election, Aadhaar identity) that has cast a ballot.

    This is what enforces **one verified person = one vote per election**,
    independent of how many accounts exist. It records only *that* an identity
    voted - never which ballot was theirs - so it does not link the person to a
    choice.
    """

    election = models.ForeignKey(
        Election, on_delete=models.CASCADE, related_name="voter_records"
    )
    identity_hash = models.CharField(max_length=64)
    cast_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("election", "identity_hash")

    def __str__(self):
        return f"{self.election_id}:{self.identity_hash[:12]}"


class Ballot(models.Model):
    """An anonymous, encrypted ballot plus its link in the hash chain.

    There is deliberately **no** foreign key to a voter. The row proves that
    *some* eligible ballot was cast; it cannot be traced back to a person.
    """

    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="ballots")
    encrypted_payload = models.TextField()
    receipt_hash = models.CharField(max_length=64, unique=True)
    index = models.PositiveIntegerField()
    prev_hash = models.CharField(max_length=64)
    entry_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["index"]

    @property
    def public_id(self) -> str:
        """A short, human-readable identifier derived from the receipt.

        Deterministic, so it can be quoted and looked up, but it reveals
        nothing about the vote (it is derived from the ciphertext hash).
        """
        code = self.receipt_hash[:8].upper()
        return f"SV-{code[:4]}-{code[4:]}"

    def __str__(self):
        return f"ballot #{self.index}"


class BallotToken(models.Model):
    """Fingerprints of one-time anonymous voting tokens that were consumed.

    Only ``sha256(token)`` is stored, so the token cannot be recovered or linked
    to the voter who used it.
    """

    fingerprint = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.fingerprint[:16]
