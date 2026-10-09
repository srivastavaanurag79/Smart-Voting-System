# EPIC / Electoral-Roll Migration

How ECI electoral-roll data (EPIC) is migrated into this system **encrypted**, so
that no single party - not a DBA, not an operator, not the tally authority - can
directly learn who voted for whom.

## 1. Background: what EPIC and the electoral roll contain

The **EPIC** (Elector's Photo Identity Card) number is the identity key on an
elector's card. The electoral roll holds, per elector:

- EPIC number
- Name, relative's name, age/DOB, gender
- Address / residence
- Constituency, part/section, polling-station placement
- Photograph
- ECI-internal identifiers

Two things matter for e-voting:

- **Who the elector is** (identity) - bound here via Aadhaar.
- **Whether the elector is entitled to vote in this election** (the roll) - bound
  via the EPIC entry.

## 2. Storage model in this system

| EPIC / roll field | Column | Storage |
|-------------------|--------|---------|
| EPIC number (match/dedupe) | `UserProfile.epic_hash` | SHA-256, one-way, indexed |
| EPIC number (audit) | `UserProfile.epic_encrypted` | Fernet ciphertext |
| Name / address / DOB / gender / education / occupation / marital status | `UserProfile.encrypted_details` | Fernet ciphertext of JSON |
| Aadhaar (if linked) | `aadhaar_encrypted` + `identity_hash` | Fernet ciphertext + SHA-256 |
| Roll / entitlement | `UserProfile.id` (+ election config) | Roll id used as eligibility key |

Nothing above is stored in plaintext except the **one-way hash** used for
matching. A raw database dump yields ciphertext and hashes.

## 3. Why this enforces "nobody knows who voted for whom"

The system splits three facts across three independent stores:

```
Identity + entitlement   ->  electoral roll (this document)
Ballot content           ->  encrypted Ballot row (no voter reference)
Eligibility consumed?    ->  VoterBallotRecord(election, identity_hash)  (no choice)
```

- The vote content lives only as ciphertext to the **tally key**.
- The roll knows *who* exists but holds **no ballot** and **no reference** to one.
- The ledger holds ciphertext with **no identity**.

To reconstruct "who voted for whom" you would have to simultaneously:

1. hold a quorum of the tally key (threshold trustees),
2. break the issuance unlinkability (blind signatures), and
3. defeat the operational separation of roll / ledger / key custody.

That is the entire design intent: no single party, by construction, can know the
mapping.

## 4. The import command

```bash
python manage.py import_electoral_roll eci_roll.csv --dry-run
python manage.py import_electoral_roll eci_roll.csv
```

CSV header (case-insensitive):

```
epic,username,first_name,last_name,residence,country,education,occupation,marital_status,aadhaar
```

Behaviour:

- Streams rows (safe for very large rolls).
- Encrypts EPIC and all personal fields before writing.
- Stores only `epic_hash` in cleartext (for matching/dedupe).
- `--dry-run` previews masked EPIC values (`XXXXXX4567`) and writes nothing.
- Creates or updates a `UserProfile` per row; existing profile ids are preserved.

Example:

```
Row 2: epic=XXXXXX4567 user=rollvoter fields=7
```

## 5. Migration checklist for a real deployment

1. **Legal basis.** Migrating roll data into a voting system is a new processing
   purpose; document it and obtain the required authority.
2. **Consent & notice.** Inform electors how identity data is used and minimised.
3. **Key management.** Generate the PII key (`keys/pii.key`) in an HSM/KMS, never
   in the repo. Rotate and back up securely.
4. **Reconciliation cadence.** Rolls change (additions, deletions, address
   changes); schedule periodic encrypted re-imports, not a one-time load.
5. **De-duplication.** `epic_hash` and `identity_hash` unique constraints catch
   duplicates; handle conflicts deliberately.
6. **Constituency isolation.** Scope ballots and rolls per election/constituency
   so a voter only sees their contests.
7. **Retention & purge.** Encrypted PII is purged after the election's audit
   window; the anonymous ledger remains.
8. **Audit.** Log authentication reference ids (never raw Aadhaar/EPIC) so the
   process is auditable without exposing data.

## 6. Extending to a real ECI integration

- Replace the CSV import with ECI's authoritative feed/API for your jurisdiction.
- Keep the **encrypt-before-store** rule regardless of the source.
- Store constituency/part/section as **access-controlled or encrypted metadata**
  scoped for eligibility, not exposed broadly.
- If ECI links EPIC↔Aadhaar itself, consume that linkage as an opaque token and
  store only hashes.

See [AADHAAR_INTEGRATION.md](AADHAAR_INTEGRATION.md) for the identity side and
[THREAT_MODEL.md](THREAT_MODEL.md) for the security analysis.