# Manual Testing Checklist

Click-by-click manual tests for the prototype. Start the app with `python run.py`
and open <http://127.0.0.1:8000/>. Camera tests need HTTPS or `localhost`.

Demo logins (from `python manage.py seed_demo`): `guptaabhishek / gupta1234`
(voter), `thesrivas / thesri1234` (admin).

## A. Pages load

- [ ] `/` redirects to `/Vote/home/`.
- [ ] `/Vote/home/`, `/Vote/about/`, `/Vote/login/`, `/Vote/results/`,
      `/Vote/bulletin/`, `/Vote/verify/`, `/Vote/face_login/` all return 200.

## B. Password login

- [ ] Wrong password → redirected to `/Vote/invalid/` with an error message.
- [ ] `guptaabhishek / gupta1234` → logged in, redirected to the face step.

## C. Aadhaar identity verification (optional)

Identity verification is optional in the demo — you can vote without it — but it
strengthens the one-person-one-vote guarantee.

- [ ] Visit `/Vote/aadhaar/`. The field is formatted `XXXX-XXXX-XXXX`.
- [ ] Enter any 12-digit number (the mock accepts it even if it is not a real
      Aadhaar); leave OTP blank and submit → a mock OTP is shown.
- [ ] Re-submit with that OTP → success. A biometric is optional: capture one
      (face) or type a sample (fingerprint/iris), or leave it blank.
- [ ] Try a number that is not 12 digits → rejected with a clear message.
- [ ] Try the same Aadhaar on a second account → rejected as already linked.

The mock provider is lenient by design. For reference, a number that passes the
real Verhoeff checksum can be generated with:

```powershell
.\.venv\Scripts\python.exe -c "import os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','HCI.settings');import django;django.setup();from Vote import aadhaar;b='23456789012';print(next(b+str(c) for c in range(10) if aadhaar.is_valid_aadhaar(b+str(c))))"
```

## D. Face enrolment (browser webcam)

- [ ] `/Vote/face_index/` → allow camera → *Start capture* (20 frames) →
      counter reaches 20 → *Save* → success message with sample count.
- [ ] Cover the camera and capture → save fails with "No face detected".

## E. Face sign-in

- [ ] `/Vote/face_login/` → allow camera → *Verify* → "Welcome … Redirecting".
- [ ] With no enrolled face (or camera covered) → "Face not recognised".

## F. Voting

- [ ] `/Vote/vote/` shows one panel per contest with all candidates.
- [ ] Submitting with a contest unselected → error "select a candidate for every
      contest".
- [ ] Select one candidate per contest and submit → receipt is shown (64-char
      hash), shown **once**.
- [ ] Refreshing `/Vote/vote/` after voting → redirected to `/Vote/voted/`.

## G. Verify the receipt

- [ ] `/Vote/verify/` → paste the receipt → "Ballot found … chain is valid".
- [ ] Paste a random hash → "No ballot matches that receipt".

## H. Public ledger

- [ ] `/Vote/bulletin/` shows rows with receipt / prev hash / entry hash.
- [ ] Integrity label shows **valid**.

## I. Tally and results

- [ ] As `guptaabhishek`, `/Vote/results/` shows "results not published".
- [ ] As `thesrivas`, `/Vote/results/` → *Run tally* → success.
- [ ] Results now show vote totals and charts matching the ballots cast.

## J. One person, one vote

- [ ] Confirm no second ballot exists for the same Aadhaar identity after a
      second attempt (blocked with a message).
- [ ] (Automated coverage: `python manage.py test` — 19 tests.)

## K. EPIC electoral-roll import

- [ ] Run `python manage.py import_electoral_roll sample.csv --dry-run` and
      confirm masked EPIC values are printed and nothing is written.
- [ ] Run without `--dry-run` and confirm the profile shows encrypted fields in
      the admin (`epic_hash`, `epic_encrypted`, `encrypted_details`).

## L. Deployment sanity (optional)

- [ ] Follow [DEPLOYMENT.md](DEPLOYMENT.md) to run under Docker or a free host.
- [ ] Confirm HTTPS and the camera prompt on the deployed URL.