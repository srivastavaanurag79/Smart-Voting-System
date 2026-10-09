# Security Policy

## Project status

Smart Voting System is an **educational prototype**. It demonstrates encrypted,
anonymous ballots and a tamper-evident ledger, but it has **not** been audited
and is **not** certified or approved for any real, binding election. Do not use
it to run a real vote.

Because it is a prototype, there are no supported release versions. Treat
`master` as the only branch.

## Reporting a vulnerability

Please report security issues privately using GitHub's
[private security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
feature on this repository ("Security" → "Report a vulnerability"). Do not open
a public issue for a security problem.

Include, if you can:

- a description of the issue and its impact,
- steps to reproduce,
- the affected file(s) or URL(s),
- any suggested fix.

You can expect an acknowledgement within a few days. As this is a personal
prototype there is no formal SLA.

## Security properties implemented

- **Confidentiality:** ballots are encrypted with RSA-OAEP + AES-256-GCM to the
  election public key. The private key is stored outside the database.
- **Anonymity / unlinkability:** `Ballot` rows have no reference to a voter, and
  one-time voting tokens are stored only as SHA-256 fingerprints.
- **Integrity / tamper-evidence:** ballots are appended to a hash chain; anyone
  can recompute it and detect edits.
- **PII protection:** Aadhaar is encrypted at rest with Fernet; a one-way hash
  is stored for matching.
- **Access control:** tallying requires staff access and the private key.

## Known limitations (do not ignore these)

- **Single-key tally.** One party holds the decryption key. A real system uses
  threshold trustees so no single party can open a ballot.
- **Not coercion-resistant.** A voter can be forced to reveal their receipt or
  re-vote under observation.
- **Issuance linkage.** The server sees the voter and their eligible token in
  the same request. Strong unlinkability needs blind signatures (see
  `docs/IMPLEMENTATION.md`).
- **Software key storage.** Private keys are unencrypted files on disk; real
  systems use HSMs and key ceremonies.
- **Development defaults.** `DEBUG` is on and the secret key has a dev default.
  Both must be set from the environment in any real deployment.
- **Delivery side channels.** Timing, ordering and request logs can leak
  metadata if not carefully managed.
- **Face/Aadhaar are convenience factors** here, not hardened biometric or
  official identity verification.
- **SQLite by default**, which is unsuitable for concurrent, high-stakes use.

## Hardening checklist before any serious use

1. Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS` from
   the environment.
2. Move behind HTTPS with HSTS, secure cookies and a reverse proxy.
3. Replace single-key tallying with threshold trustees and an HSM-backed key
   ceremony.
4. Add blind-signature token issuance for true voter unlinkability.
5. Use a production database with backups and replication.
6. Add rate limiting, account lockout and an independent security audit.

See `docs/THREAT_MODEL.md` for the full analysis.