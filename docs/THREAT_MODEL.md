# Threat Model

Scope: the Smart Voting System prototype running locally. This document states
what the system protects, who the actors are, and - honestly - what it does not
protect.

## Assets

- **Ballot secrecy** - nobody learns how an individual voted.
- **Voter anonyminity** - a stored ballot cannot be tied to a person.
- **Election integrity** - totals reflect only valid, one-per-voter ballots.
- **Voter PII** - Aadhaar and personal records.
- **Election keys** - the ability to decrypt ballots.
- **Availability** - the service stays usable during voting.

## Actors

- **Voter** - authenticated, eligible citizen.
- **Election official** - staff user who runs the tally.
- **System administrator** - operates the server and the database.
- **External attacker** - no credentials; attacks over the network.
- **Insider attacker** - has some server or database access.

## Trust boundaries

1. Browser ↔ Django over HTTP(S).
2. Django ↔ database.
3. Django ↔ key material on disk.
4. Django ↔ Aadhaar provider (mock offline; UIDAI online in production).

## Threats and mitigations

| # | Threat | Mitigation | Residual risk |
|---|--------|-----------|---------------|
| 1 | Impersonation (vote chori) | Password + face + verified Aadhaar gate token issuance | Weak factors (face, mock Aadhaar) |
| 2 | Double voting | Electoral-roll flag + single-use token fingerprint | Concurrent races mitigated by DB uniqueness/atomicity |
| 3 | Ballot stuffing | Ballots require a valid, unused token from an authenticated eligible session | Admin with DB access could insert checksum-consistent rows |
| 4 | Ballot tampering | Encrypted payload + hash-chained ledger | Admin can rewrite the whole chain if unanchored externally |
| 5 | Reading votes | RSA-OAEP + AES-256-GCM; private key off-database | Key holder can decrypt every ballot |
| 6 | Linking voter ↔ choice | No voter FK on `Ballot`; tokens stored as hashes | Server sees voter + token in one request at issuance |
| 7 | PII theft | Aadhaar Fernet-encrypted; hash for matching | DB + key compromise exposes PII |
| 8 | Replay of a cast request | One-time token; CSRF protection | Token reuse blocked by fingerprint table |
| 9 | Key theft | Keys in `ELECTION_KEY_DIR`, excluded from VCS | Plaintext files, no HSM |
| 10 | Traffic analysis | Not addressed | Timing/order metadata can leak |
| 11 | Coercion / vote buying | Not addressed | Voter can be forced to show receipt or re-vote |
| 12 | Availability | Out of scope for a prototype | Single SQLite file, no HA |

## Explicitly out of scope / not solved

- **Coercion resistance.** The receipt proves inclusion, but a coercer can demand
  it. Real systems use re-voting with revocation or advanced cryptography.
- **End-to-end cryptographic verifiability** (zero-knowledge proofs that the
  tally is correct). Here verification is by receipt inclusion and chain check.
- **Threshold key custody.** A single key currently decrypts all ballots.
- **Biometric security.** LBPH face matching is a convenience factor, spoofable
  by a photo.
- **Aadhaar authenticity.** The mock provider checks the number's checksum, not
  the person. Only UIDAI can do that.

## Assumptions

- The election public key in `Election.public_key_pem` corresponds to the private
  key in `ELECTION_KEY_DIR`.
- Officials protect the private key and run the tally honestly.
- TLS terminates in front of Django in any non-local deployment.

## Recommended production design

1. Threshold trustees + HSM-backed key ceremony for the tally key.
2. Blind-signature ballot tokens for unlinkable issuance.
3. Public, append-only anchoring of the ledger head (e.g. periodic publication)
   so insiders cannot rewrite history unnoticed.
4. Licensed Aadhaar integration (AUA/KUA) with consent logging.
5. Independent penetration test and cryptographic review.