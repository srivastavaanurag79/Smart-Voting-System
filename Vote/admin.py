from django.contrib import admin

from .models import (
    Ballot,
    BallotToken,
    Candidate,
    Election,
    Position,
    UserProfile,
    VoterBallotRecord,
)


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "results_published", "created_at")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("position", "election", "no_of_candidates")


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("name", "candidate", "votes")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "voted",
        "aadhaar_verified",
        "biometric_verified",
        "face_enrolled",
    )


@admin.register(VoterBallotRecord)
class VoterBallotRecordAdmin(admin.ModelAdmin):
    list_display = ("election", "identity_hash", "cast_at")


@admin.register(Ballot)
class BallotAdmin(admin.ModelAdmin):
    list_display = ("index", "election", "receipt_hash", "created_at")
    readonly_fields = ("encrypted_payload", "receipt_hash", "index", "prev_hash", "entry_hash")


@admin.register(BallotToken)
class BallotTokenAdmin(admin.ModelAdmin):
    list_display = ("fingerprint", "used_at")
