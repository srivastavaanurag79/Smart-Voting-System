# Deployment (Free / Low-Cost)

How to host the prototype so anyone can test it. It is a Django app that needs
**HTTPS** (browsers gate `getUserMedia` on secure contexts) and a persistent
process.

## 0. Fastest path: one command locally

```bash
python run.py
```

This creates `.venv`, installs missing dependencies, migrates, seeds demo data
and starts the server. Use `python run.py --host 0.0.0.0 --port 8000` to expose
it on your network.

To share a local instance publicly with HTTPS for a demo, tunnel it:

```bash
ngrok http 8000
# or
cloudflared tunnel --url http://localhost:8000
```

## 1. Docker (works on Render, Railway, Fly.io, etc.)

A `Dockerfile` is included. It installs dependencies, creates `/data/keys`,
migrates, seeds demo data and serves with Gunicorn + WhiteNoise.

```bash
docker build -t smart-voting .
docker run -p 8000:8000 -v smart-voting-keys:/data/keys smart-voting
```

## 2. Free platforms

| Platform | How | Notes |
|----------|-----|-------|
| **Render** | New Web Service → Docker, or Python + start command from `Procfile` | Free TLS; free instances sleep when idle. |
| **Railway** | Deploy from repo | Generous free trial; Docker auto-detected. |
| **Fly.io** | `fly launch`, `fly deploy` | Small free allowance; persistent volumes available. |
| **PythonAnywhere** | Manual WSGI setup | Long-standing free tier for Django. |
| **GitHub Codespaces** | Open repo → run `python run.py` | Great for reviewers; not public hosting. |

## 3. Required environment variables

| Variable | Example | Notes |
|----------|---------|-------|
| `DJANGO_SECRET_KEY` | long random string | Never commit it. |
| `DJANGO_DEBUG` | `False` | Must be False in production. |
| `DJANGO_ALLOWED_HOSTS` | `myapp.onrender.com` | Comma-separated. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://myapp.onrender.com` | Required for POST over HTTPS. |
| `ELECTION_KEY_DIR` | `/data/keys` | Persistent volume; else keys reset on redeploy. |
| `AADHAAR_PROVIDER` | `mock` | `uidai` raises until implemented. |
| `FACE_MATCH_THRESHOLD` | `55` | Optional tuning. |

## 4. Platform notes

- **Render / Railway / Heroku-style:** the included `Procfile` runs
  `migrate && seed_demo && gunicorn HCI.wsgi ...`. `gunicorn` and `whitenoise`
  are in `requirements.txt`.
- **Serving static files:** WhiteNoise middleware serves them from the app; no
  CDN needed. If you use a manifest storage, run `collectstatic` during build.
- **Persistent storage:** free tiers often reset disk on redeploy. For a demo,
  seeding on boot is fine; for anything durable, mount a volume for the DB and
  `ELECTION_KEY_DIR`.
- **Webcam:** must be served over HTTPS (or `localhost`). Most platforms provide
  TLS automatically.

## 5. Post-deploy smoke test

1. Open `/` → redirects to `/Vote/home/`.
2. Log in as a demo voter; confirm redirect to the face step.
3. Open `/Vote/aadhaar/`, complete the mock Aadhaar + biometric flow.
4. Cast a ballot; confirm the receipt appears once.
5. `/Vote/verify/` → paste the receipt → "Ballot found".
6. `/Vote/bulletin/` → chain shows **valid**.
7. Log in as `thesrivas`, run the tally, check `/Vote/results/`.

## 6. Before any non-demo use

Read [../SECURITY.md](../SECURITY.md). At minimum: `DEBUG=False`, real secret
key, HTTPS/HSTS, secure cookies, a production database, threshold key custody,
rate limiting, and an independent audit. This prototype is **not** certified for
a real election.