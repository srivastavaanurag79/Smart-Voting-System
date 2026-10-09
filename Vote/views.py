import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import aadhaar as aadhaar_service
from . import crypto, face
from .models import (
    Ballot,
    BallotToken,
    Candidate,
    Election,
    Position,
    UserProfile,
    VoterBallotRecord,
)

logger = logging.getLogger(__name__)


# --- helpers -----------------------------------------------------------------

def get_profile(user) -> UserProfile:
    """Return (creating if needed) the electoral-roll profile for ``user``."""
    profile, _ = UserProfile.objects.get_or_create(
        user=user, defaults={"id": user.username}
    )
    return profile


def active_election() -> Election | None:
    return Election.objects.filter(is_active=True).order_by("-created_at").first()


def _contests(election: Election):
    result = []
    for contest in election.positions.all().order_by("id"):
        result.append(
            {
                "contest": contest,
                "candidates": list(contest.candidates.all().order_by("id")),
            }
        )
    return result


# --- static pages ------------------------------------------------------------

def index(request):
    return render(request, "Vote/home.html")


def home(request):
    return render(request, "Vote/home.html", {})


def home_hindi(request):
    return render(request, "Vote/home_hindi.html", {})


def home_tamil(request):
    return render(request, "Vote/home_tamil.html", {})


def home_bengali(request):
    return render(request, "Vote/home_bengali.html", {})


def home_malayalam(request):
    return render(request, "Vote/home_malayalam.html", {})


def about(request):
    return render(request, "Vote/about.html", {})


def voted(request):
    return render(request, "Vote/voted.html", {})


def invalid(request):
    return render(request, "Vote/invalid.html", {})


def casted(request):
    """Shows the voter their anonymous ballot receipt after casting."""
    receipt = request.session.pop("last_receipt", "")
    public_id = ""
    if receipt:
        code = receipt[:8].upper()
        public_id = f"SV-{code[:4]}-{code[4:]}"
    return render(request, "Vote/casted.html", {"receipt": receipt, "public_id": public_id})


# --- authentication ----------------------------------------------------------

def user_login(request):
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        user = authenticate(username=username, password=password)
        if user is None:
            logger.info("Failed login for username=%s", username)
            messages.error(request, "Invalid username or password.")
            return HttpResponseRedirect("/Vote/invalid/")
        if not user.is_active:
            messages.error(request, "This account is disabled.")
            return HttpResponseRedirect("/Vote/invalid/")
        login(request, user)
        get_profile(user)
        return HttpResponseRedirect("/Vote/vote/")
    return render(request, "Vote/login.html", {})


@login_required(login_url="/Vote/login/")
def user_logout(request):
    logout(request)
    return HttpResponseRedirect("/Vote/home/")


# --- face enrolment ----------------------------------------------------------

def face_index(request):
    """Enrolment page. Requires an account: eligibility must be tied to a voter."""
    if not request.user.is_authenticated:
        return render(request, "face_index.html", {"needs_login": True})
    profile = get_profile(request.user)
    return render(request, "face_index.html", {"profile": profile})


@login_required(login_url="/Vote/login/")
@require_POST
def enroll_face(request):
    """Accept base64 frames from the browser webcam, store them, retrain."""
    frames = request.POST.getlist("frames[]") or request.POST.getlist("frames")
    if not frames:
        return JsonResponse({"ok": False, "error": "No frames received."}, status=400)
    profile = get_profile(request.user)
    try:
        saved = face.enroll_frames(str(profile.id), frames)
    except cv2_error() as exc:  # pragma: no cover - defensive
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    if saved == 0:
        return JsonResponse(
            {"ok": False, "error": "No face detected. Improve lighting and try again."},
            status=400,
        )
    trained = face.train_model()
    profile.face_enrolled = True
    profile.save(update_fields=["face_enrolled"])
    return JsonResponse({"ok": True, "samples": saved, "trained_on": trained})


def cv2_error():
    import cv2

    return cv2.error


def trainer(request):
    """Retrain the recogniser from the stored dataset."""
    trained = face.train_model()
    messages.success(request, f"Classifier trained on {trained} samples.")
    return redirect("/Vote/face_index")


# --- face login --------------------------------------------------------------

def face_login(request):
    """GET renders the capture page; POST matches a frame and logs the voter in."""
    if request.method == "POST":
        frame = request.POST.get("frame", "")
        try:
            voter_id, confidence = face.predict(frame)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Face prediction failed")
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)
        if voter_id is None or confidence >= settings.FACE_MATCH_THRESHOLD:
            return JsonResponse(
                {"ok": False, "error": "Face not recognised.", "confidence": confidence},
                status=401,
            )
        profile = UserProfile.objects.filter(id=voter_id).select_related("user").first()
        if profile is None or not profile.user.is_active:
            return JsonResponse(
                {"ok": False, "error": "Matched face has no eligible voter."}, status=403
            )
        login(request, profile.user, backend="django.contrib.auth.backends.ModelBackend")
        return JsonResponse(
            {
                "ok": True,
                "voter": profile.user.username,
                "redirect": reverse("Vote:vote"),
                "confidence": confidence,
            }
        )
    return render(request, "face_login.html", {})


def detect(request):
    """Backwards-compatible entry point: face verification instead of a webcam."""
    return redirect("/Vote/face_login")


# --- voting ------------------------------------------------------------------

@login_required(login_url="/Vote/login/")
def vote(request):
    election = active_election()
    if election is None:
        messages.error(request, "No active election is configured.")
        return redirect("/Vote/home/")

    profile = get_profile(request.user)
    if not profile.aadhaar_verified:
        messages.info(
            request, "Verify your Aadhaar identity (face/fingerprint/iris) before voting."
        )
        return redirect("Vote:aadhaar_verify")
    if profile.voted:
        return HttpResponseRedirect("/Vote/voted/")

    if request.method == "POST":
        return _cast_ballot(request, election, profile)

    token = crypto.new_voting_token()
    request.session["voting_token"] = token
    context = {
        "election": election,
        "contests": _contests(election),
        "voting_token": token,
    }
    return render(request, "Vote/vote.html", context)


@transaction.atomic
def _cast_ballot(request, election, profile):
    token = request.POST.get("voting_token", "")
    session_token = request.session.get("voting_token", "")
    if not token or token != session_token:
        messages.error(request, "Your voting session expired. Please try again.")
        return redirect("Vote:vote")

    fingerprint = crypto.token_fingerprint(token)
    if BallotToken.objects.filter(fingerprint=fingerprint).exists():
        messages.error(request, "This ballot token has already been used.")
        return redirect("Vote:voted")

    # Enforce one verified person = one vote per election, independent of
    # account count. The record stores only that the identity voted.
    identity_hash = profile.identity_hash or crypto.hash_hex("voter", str(profile.id))
    if VoterBallotRecord.objects.filter(
        election=election, identity_hash=identity_hash
    ).exists():
        messages.error(request, "This Aadhaar identity has already voted in this election.")
        return redirect("Vote:voted")

    payload = {}
    for contest in election.positions.all():
        field = f"contest_{contest.id}"
        choice = request.POST.get(field)
        if not choice:
            messages.error(request, "Please select a candidate for every contest.")
            return redirect("Vote:vote")
        candidate = get_object_or_404(Candidate, pk=choice, candidate=contest)
        payload[str(contest.id)] = candidate.id

    encrypted = crypto.encrypt_ballot(election.public_key_pem, payload)
    receipt = crypto.ballot_receipt(encrypted)

    last = Ballot.objects.filter(election=election).order_by("-index").first()
    index = (last.index + 1) if last else 1
    prev_hash = last.entry_hash if last else crypto.hash_hex("genesis", str(election.id), election.name)
    entry_hash = crypto.hash_hex("ballot", str(index), prev_hash, receipt, encrypted)

    Ballot.objects.create(
        election=election,
        encrypted_payload=encrypted,
        receipt_hash=receipt,
        index=index,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    BallotToken.objects.create(fingerprint=fingerprint)
    try:
        VoterBallotRecord.objects.create(
            election=election, identity_hash=identity_hash
        )
    except IntegrityError:
        # Someone with the same identity raced us; refuse the double vote.
        transaction.set_rollback(True)
        messages.error(request, "This Aadhaar identity has already voted in this election.")
        return redirect("Vote:voted")
    profile.voted = True
    profile.save(update_fields=["voted"])
    request.session.pop("voting_token", None)
    request.session["last_receipt"] = receipt
    return redirect("Vote:casted")


# --- tally + results ---------------------------------------------------------

def _tally(election: Election) -> dict:
    """Decrypt every ballot and count votes. Returns {contest_id: {cand_id: n}}."""
    private_key = crypto.load_private_key(election.key_name)
    if private_key is None:
        raise RuntimeError(
            "Election private key not available; a tally holder must provide it."
        )
    counts: dict[str, dict[str, int]] = {}
    for ballot in election.ballots.all():
        payload = crypto.decrypt_ballot(private_key, ballot.encrypted_payload)
        for contest_id, candidate_id in payload.items():
            counts.setdefault(str(contest_id), {})
            counts[str(contest_id)][str(candidate_id)] = (
                counts[str(contest_id)].get(str(candidate_id), 0) + 1
            )
    return counts


@login_required(login_url="/Vote/login/")
@require_POST
def run_tally(request):
    if not request.user.is_staff:
        messages.error(request, "Only election officials can run the tally.")
        return redirect("Vote:results")
    election = active_election() or Election.objects.first()
    if election is None:
        messages.error(request, "No election to tally.")
        return redirect("Vote:results")
    try:
        counts = _tally(election)
    except RuntimeError as exc:
        messages.error(request, str(exc))
        return redirect("Vote:results")

    for contest in election.positions.all():
        contest_counts = counts.get(str(contest.id), {})
        for candidate in contest.candidates.all():
            candidate.votes = contest_counts.get(str(candidate.id), 0)
            candidate.save(update_fields=["votes"])
    election.results_published = True
    election.save(update_fields=["results_published"])
    messages.success(request, "Tally complete.")
    return redirect("Vote:results")


def results(request):
    election = active_election() or Election.objects.first()
    contests = _contests(election) if election else []
    chart_data = []
    for item in contests:
        contest = item["contest"]
        chart_data.append(
            {
                "contest": contest.position,
                "labels": [c.name for c in item["candidates"]],
                "votes": [c.votes for c in item["candidates"]],
            }
        )
    context = {
        "election": election,
        "contests": contests,
        "chart_data": json.dumps(chart_data),
        "published": bool(election and election.results_published),
    }
    return render(request, "Vote/results.html", context)


# --- blockchain-style bulletin board + verification --------------------------

def bulletin(request):
    election = active_election() or Election.objects.first()
    chain = list(election.ballots.all()) if election else []
    context = {"election": election, "chain": chain, "chain_valid": _chain_valid(chain)}
    return render(request, "Vote/bulletin.html", context)


def _chain_valid(chain) -> bool:
    prev = None
    for i, block in enumerate(chain):
        expected_prev = (
            prev.entry_hash
            if prev is not None
            else crypto.hash_hex("genesis", str(block.election_id), block.election.name)
        )
        if block.prev_hash != expected_prev:
            return False
        expected_hash = crypto.hash_hex(
            "ballot", str(block.index), block.prev_hash, block.receipt_hash, block.encrypted_payload
        )
        if block.entry_hash != expected_hash:
            return False
        prev = block
    return True


def verify_ballot(request):
    """Public verifier: paste a receipt and confirm it is on the ledger."""
    result = None
    receipt = ""
    if request.method == "POST":
        receipt = request.POST.get("receipt", "").strip()
        ballot = Ballot.objects.filter(receipt_hash=receipt).first() if receipt else None
        if ballot is None:
            result = {"found": False}
        else:
            chain = list(ballot.election.ballots.all())
            result = {
                "found": True,
                "valid_chain": _chain_valid(chain),
                "ballot": ballot,
            }
    return render(request, "Vote/verify_ballot.html", {"result": result, "receipt": receipt})


# --- Aadhaar verification (mock provider) ------------------------------------

@login_required(login_url="/Vote/login/")
def aadhaar_verify(request):
    """Bind a verified Aadhaar identity (and optional biometric) to eligibility.

    The biometric is sent for a 1:1 match and is **not stored** - only a boolean
    and the identity hash are kept.
    """
    profile = get_profile(request.user)
    provider = aadhaar_service.get_provider()
    context = {
        "profile": profile,
        "mock": getattr(provider, "name", "mock") == "mock",
        "modalities": sorted(aadhaar_service.BIOMETRIC_MODALITIES),
    }

    if request.method == "POST":
        number = request.POST.get("aadhaar", "").replace(" ", "")
        otp = request.POST.get("otp", None)
        modality = request.POST.get("modality", "face")
        biometric = request.POST.get("biometric", "")

        # Step 1 (demo): reveal the deterministic mock OTP for a valid number.
        if (otp is None or otp == "") and hasattr(provider, "expected_otp"):
            if aadhaar_service.is_valid_aadhaar(number):
                context["otp_hint"] = provider.expected_otp(number)
                context["number"] = number
                return render(request, "Vote/aadhaar_verify.html", context)

        otp_result = provider.verify(number, otp=otp)
        if not otp_result.verified:
            messages.error(request, otp_result.message)
            return render(request, "Vote/aadhaar_verify.html", context)

        bio_result = provider.verify_biometric(number, modality, biometric)
        if not bio_result.matched:
            messages.error(request, f"Aadhaar OK but biometric failed: {bio_result.message}")
            context["number"] = number
            return render(request, "Vote/aadhaar_verify.html", context)

        identity_hash = crypto.hash_hex("aadhaar", number)
        # One Aadhaar identity can be attached to only one account.
        clash = (
            UserProfile.objects.filter(identity_hash=identity_hash)
            .exclude(pk=profile.pk)
            .exists()
        )
        if clash:
            messages.error(
                request, "This Aadhaar identity is already linked to another voter."
            )
            return render(request, "Vote/aadhaar_verify.html", context)

        profile.aadhaar_verified = True
        profile.biometric_verified = True
        profile.identity_hash = identity_hash
        profile.aadhaar_encrypted = crypto.encrypt_pii(number)
        profile.save(
            update_fields=[
                "aadhaar_verified",
                "biometric_verified",
                "identity_hash",
                "aadhaar_encrypted",
            ]
        )
        messages.success(
            request,
            f"{otp_result.message} {bio_result.message} "
            f"Ref: {bio_result.reference_id or otp_result.reference_id}",
        )
        return redirect("Vote:vote")

    return render(request, "Vote/aadhaar_verify.html", context)


# --- legacy endpoints --------------------------------------------------------

def create_dataset(request):
    """Legacy URL kept alive; enrolment now happens through the browser webcam."""
    return redirect("/Vote/face_index")
