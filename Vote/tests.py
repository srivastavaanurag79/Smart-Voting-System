from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from . import aadhaar, crypto
from .models import (
    Ballot,
    BallotToken,
    Candidate,
    Election,
    Position,
    UserProfile,
    VoterBallotRecord,
)


def valid_aadhaar() -> str:
    base = "23456789012"
    return next(base + str(c) for c in range(10) if aadhaar.is_valid_aadhaar(base + str(c)))


class CryptoTests(TestCase):
    def test_ballot_round_trip(self):
        private_key, public_pem = crypto.load_or_create_rsa_keypair("test-crypto")
        payload = {"1": 3, "2": 5}
        token = crypto.encrypt_ballot(public_pem, payload)
        self.assertEqual(crypto.decrypt_ballot(private_key, token), payload)

    def test_pii_round_trip(self):
        encrypted = crypto.encrypt_pii("123456789012")
        self.assertNotIn("123456789012", encrypted)
        self.assertEqual(crypto.decrypt_pii(encrypted), "123456789012")

    def test_epic_and_details_round_trip(self):
        epic = "ABC1234567"
        details = {"first_name": "Asha", "residence": "Majitar"}
        self.assertEqual(crypto.epic_hash(epic), crypto.epic_hash("abc1234567"))
        self.assertNotIn(epic, crypto.encrypt_pii(epic))
        self.assertEqual(crypto.decrypt_pii(crypto.encrypt_pii(epic)), epic)
        blob = crypto.encrypt_details(details)
        self.assertNotIn("Asha", blob)
        self.assertEqual(crypto.decrypt_details(blob), details)
        self.assertEqual(crypto.mask_epic(epic), "XXXXXX4567")

    def test_token_fingerprint_is_one_way(self):
        token = crypto.new_voting_token()
        self.assertNotEqual(crypto.token_fingerprint(token), token)


class AadhaarTests(TestCase):
    def test_verhoeff_validation(self):
        number = valid_aadhaar()
        self.assertTrue(aadhaar.is_valid_aadhaar(number))
        self.assertFalse(aadhaar.is_valid_aadhaar("123456789012"))
        self.assertFalse(aadhaar.is_valid_aadhaar("012345678901"))

    def test_plausible_format_is_accepting(self):
        self.assertFalse(aadhaar.is_plausible_aadhaar("123"))
        self.assertFalse(aadhaar.is_plausible_aadhaar("012345678901"))
        self.assertTrue(aadhaar.is_plausible_aadhaar("2345 6789 0123"))

    def test_mock_accepts_12_digit_number_without_verhoeff(self):
        provider = aadhaar.get_provider()
        number = "234567890123"  # 12 digits, no leading 0/1
        result = provider.verify(number, otp=provider.expected_otp(number))
        self.assertTrue(result.verified)

    def test_mock_provider_verifies_with_expected_otp(self):
        number = valid_aadhaar()
        provider = aadhaar.get_provider()
        result = provider.verify(number, otp=provider.expected_otp(number))
        self.assertTrue(result.verified)
        self.assertTrue(result.reference_id)


class ElectoralRollImportTests(TestCase):
    def test_import_encrypts_epic_and_details(self):
        from io import StringIO
        from tempfile import NamedTemporaryFile

        from django.core.management import call_command

        csv_body = (
            "epic,username,first_name,last_name,residence,country,education,"
            "occupation,marital_status,aadhaar\n"
            "ABC1234567,rollvoter,Asha,Rao,Majitar,India,B.Tech,Student,Single,\n"
        )
        with NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as handle:
            handle.write(csv_body)
            csv_path = handle.name

        call_command("import_electoral_roll", csv_path, stdout=StringIO())
        profile = UserProfile.objects.get(user__username="rollvoter")
        self.assertEqual(profile.epic_hash, crypto.epic_hash("ABC1234567"))
        self.assertTrue(profile.epic_encrypted)
        self.assertNotIn("ABC1234567", profile.epic_encrypted)
        self.assertEqual(crypto.decrypt_pii(profile.epic_encrypted), "ABC1234567")
        details = crypto.decrypt_details(profile.encrypted_details)
        self.assertEqual(details["first_name"], "Asha")
        self.assertEqual(details["residence"], "Majitar")


class AadhaarViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("avoter", password="pass12345")
        UserProfile.objects.create(id="avoter", user=self.user)
        self.client.force_login(self.user)

    def test_mock_verification_encrypts_and_never_stores_plaintext(self):
        number = valid_aadhaar()
        provider = aadhaar.get_provider()

        step1 = self.client.post("/Vote/aadhaar/", {"aadhaar": number})
        self.assertEqual(step1.status_code, 200)
        self.assertIn("otp_hint", step1.context)

        step2 = self.client.post(
            "/Vote/aadhaar/",
            {
                "aadhaar": number,
                "otp": provider.expected_otp(number),
                "modality": "face",
                "biometric": "demo-face-sample",
            },
        )
        self.assertEqual(step2.status_code, 302)
        profile = UserProfile.objects.get(id="avoter")
        self.assertTrue(profile.aadhaar_verified)
        self.assertTrue(profile.biometric_verified)
        self.assertTrue(profile.aadhaar_encrypted)
        self.assertNotIn(number, profile.aadhaar_encrypted)


class VotingFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("voter1", password="pass12345")
        self.profile = UserProfile.objects.create(
            id="voter1",
            user=self.user,
            identity_hash=crypto.hash_hex("aadhaar", "234567890121"),
            aadhaar_verified=True,
        )
        self.private_key, public_pem = crypto.load_or_create_rsa_keypair("test-election")
        self.election = Election.objects.create(
            name="Test Election",
            is_active=True,
            key_name="test-election",
            public_key_pem=public_pem,
        )
        self.contest = Position.objects.create(
            election=self.election, position="President", no_of_candidates=1
        )
        self.candidate = Candidate.objects.create(
            candidate=self.contest, name="Alice", Description="Demo"
        )

    def _cast(self):
        self.client.force_login(self.user)
        self.client.get("/Vote/vote/")
        token = self.client.session["voting_token"]
        return self.client.post(
            "/Vote/vote/",
            {"voting_token": token, f"contest_{self.contest.id}": self.candidate.id},
        )

    def test_cast_ballot_stores_encrypted_anonymous_record(self):
        response = self._cast()
        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.voted)
        self.assertEqual(Ballot.objects.count(), 1)
        self.assertEqual(BallotToken.objects.count(), 1)
        ballot = Ballot.objects.get()
        # The stored payload must be ciphertext that only opens with the key.
        self.assertNotIn("candidate", ballot.encrypted_payload)
        self.assertEqual(
            crypto.decrypt_ballot(self.private_key, ballot.encrypted_payload),
            {str(self.contest.id): self.candidate.id},
        )

    def test_tally_decrypts_and_counts(self):
        self._cast()
        self.user.is_staff = True
        self.user.save()
        self.client.post("/Vote/tally/")
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.votes, 1)

    def test_double_voting_is_blocked(self):
        self._cast()
        response = self.client.get("/Vote/vote/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/voted/", response.url)

    def test_vote_allowed_without_identity_verification(self):
        # Aadhaar verification is optional: the vote page renders a notice but
        # still allows casting.
        self.profile.aadhaar_verified = False
        self.profile.save(update_fields=["aadhaar_verified"])
        self.client.force_login(self.user)
        response = self.client.get("/Vote/vote/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["identity_verified"])

    def test_public_pages_render(self):
        for url in [
            "/Vote/home/",
            "/Vote/results/",
            "/Vote/bulletin/",
            "/Vote/verify/",
            "/Vote/face_login/",
            "/Vote/login/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_receipt_verification(self):
        self._cast()
        ballot = Ballot.objects.get()
        response = self.client.post("/Vote/verify/", {"receipt": ballot.receipt_hash})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["result"]["found"])
        self.assertTrue(response.context["result"]["valid_chain"])


class OneVotePerIdentityTests(TestCase):
    def setUp(self):
        aadhaar._MOCK_CIDR.clear()
        self.identity_hash = crypto.hash_hex("aadhaar", "234567890121")
        _, public_pem = crypto.load_or_create_rsa_keypair("ident-election")
        self.election = Election.objects.create(
            name="Identity Election",
            is_active=True,
            key_name="ident-election",
            public_key_pem=public_pem,
        )
        self.contest = Position.objects.create(
            election=self.election, position="President", no_of_candidates=1
        )
        self.candidate = Candidate.objects.create(
            candidate=self.contest, name="Alice", Description="Demo"
        )
        self.user = User.objects.create_user("identity_a", password="pass12345")
        self.profile = UserProfile.objects.create(
            id="identity_a",
            user=self.user,
            identity_hash=self.identity_hash,
            aadhaar_verified=True,
        )

    def _cast(self):
        self.client.force_login(self.user)
        self.client.get("/Vote/vote/")
        token = self.client.session["voting_token"]
        return self.client.post(
            "/Vote/vote/",
            {"voting_token": token, f"contest_{self.contest.id}": self.candidate.id},
        )

    def _voter(self, username):
        user = User.objects.create_user(username, password="pass12345")
        return user

    def test_casting_records_the_identity_once(self):
        self._cast()
        self.assertEqual(VoterBallotRecord.objects.count(), 1)
        self.assertEqual(Ballot.objects.count(), 1)

    def test_identity_already_attached_to_another_account_is_rejected(self):
        other = self._voter("identity_b")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserProfile.objects.create(
                    id="identity_b",
                    user=other,
                    identity_hash=self.identity_hash,
                    aadhaar_verified=True,
                )

    def test_identity_that_already_voted_is_blocked(self):
        # Simulate the same identity having voted through another account.
        VoterBallotRecord.objects.create(
            election=self.election, identity_hash=self.identity_hash
        )
        response = self._cast()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/voted/", response.url)
        self.assertEqual(Ballot.objects.count(), 0)

    def test_voter_ballot_record_is_unique_per_election(self):
        VoterBallotRecord.objects.create(
            election=self.election, identity_hash=self.identity_hash
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                VoterBallotRecord.objects.create(
                    election=self.election, identity_hash=self.identity_hash
                )


class AadhaarBiometricTests(TestCase):
    def setUp(self):
        aadhaar._MOCK_CIDR.clear()

    def test_biometric_match_and_mismatch(self):
        provider = aadhaar.get_provider()
        number = valid_aadhaar()
        provider.enroll_biometric(number, "fingerprint", "sample-1")

        ok = provider.verify_biometric(number, "fingerprint", "sample-1")
        self.assertTrue(ok.matched)

        bad = provider.verify_biometric(number, "fingerprint", "sample-2")
        self.assertFalse(bad.matched)

    def test_modalities_and_bad_aadhaar_rejected(self):
        provider = aadhaar.get_provider()
        number = valid_aadhaar()
        for modality in ("face", "fingerprint", "iris"):
            self.assertTrue(provider.verify_biometric(number, modality, "x").matched)
        self.assertFalse(provider.verify_biometric(number, "retina", "x").matched)
        self.assertFalse(provider.verify_biometric("123", "face", "x").matched)
