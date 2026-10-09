"""Face capture / recognition helpers.

Unlike the original code, nothing here opens a webcam on the server. The
browser captures frames (``navigator.mediaDevices.getUserMedia``) and posts
them to Django, which detects, crops and either stores (enrolment) or matches
(login) the face using an LBPH recogniser.
"""

from __future__ import annotations

import base64
import binascii
import os
import re

import cv2
import numpy as np
from django.conf import settings

FACE_SIZE = (200, 200)
_ID_RE = re.compile(r"^[^.]+\.([^.]+)\.")


def _cascade() -> "cv2.CascadeClassifier":
    path = str(settings.FACE_CASCADE_PATH)
    cascade = cv2.CascadeClassifier(path)
    if cascade.empty():
        raise RuntimeError(f"Could not load face cascade from {path}")
    return cascade


def decode_frame(data_url: str) -> np.ndarray:
    """Decode a data URL or raw base64 image into a BGR numpy array."""
    if not data_url:
        raise ValueError("Empty image")
    payload = data_url.split(",", 1)[1] if "," in data_url else data_url
    try:
        raw = base64.b64decode(payload)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid base64 image") from exc
    arr = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode image")
    return image


def detect_faces(frame: np.ndarray) -> tuple[np.ndarray, list]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _cascade().detectMultiScale(gray, 1.3, 5)
    return gray, list(faces)


def crop_face(gray: np.ndarray, box) -> np.ndarray:
    x, y, w, h = box
    face = gray[y : y + h, x : x + w]
    return cv2.resize(face, FACE_SIZE)


def enroll_frames(voter_id: str, frames: list[str], max_samples: int = 40) -> int:
    """Persist detected faces for ``voter_id``. Returns number of samples saved.

    Samples are written as ``<id>.<n>.jpg`` which the LBPH trainer parses.
    """
    settings.FACE_DATASET_DIR.mkdir(parents=True, exist_ok=True)
    # Continue numbering after any existing samples for this voter.
    existing = [
        f
        for f in os.listdir(settings.FACE_DATASET_DIR)
        if f.startswith(f"User.{voter_id}.")
    ]
    start = len(existing)
    saved = 0
    for frame in frames:
        if saved >= max_samples:
            break
        try:
            image = decode_frame(frame)
        except ValueError:
            continue
        gray, faces = detect_faces(image)
        if not faces:
            continue
        face = crop_face(gray, faces[0])
        start += 1
        out = settings.FACE_DATASET_DIR / f"User.{voter_id}.{start}.jpg"
        cv2.imwrite(str(out), face)
        saved += 1
    return saved


def has_samples(voter_id: str) -> bool:
    if not settings.FACE_DATASET_DIR.exists():
        return False
    return any(
        f.startswith(f"User.{voter_id}.") for f in os.listdir(settings.FACE_DATASET_DIR)
    )


def train_model() -> int:
    """Train the LBPH recogniser from the dataset. Returns the sample count."""
    if not settings.FACE_DATASET_DIR.exists():
        return 0
    images, labels = [], []
    for name in sorted(os.listdir(settings.FACE_DATASET_DIR)):
        match = _ID_RE.match(name)
        if not match:
            continue
        path = settings.FACE_DATASET_DIR / name
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        # Same size/colour pipeline as crop_face() so train and predict agree.
        images.append(cv2.resize(gray, FACE_SIZE))
        labels.append(match.group(1))

    if not images:
        return 0

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    numeric = {label: i for i, label in enumerate(sorted(set(labels)))}
    recognizer.train(images, np.array([numeric[label] for label in labels], dtype="int32"))
    settings.FACE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    recognizer.save(str(settings.FACE_MODEL_PATH))

    # Persist the label mapping next to the model so predictions map back to ids.
    mapping_path = settings.FACE_MODEL_PATH.with_suffix(".labels")
    mapping_path.write_text("\n".join(f"{i} {label}" for label, i in numeric.items()))
    return len(images)


def _load_label_map() -> dict[int, str]:
    mapping_path = settings.FACE_MODEL_PATH.with_suffix(".labels")
    if mapping_path.exists():
        result = {}
        for line in mapping_path.read_text().splitlines():
            if not line.strip():
                continue
            index, label = line.split(" ", 1)
            result[int(index)] = label
        return result
    return {}


def predict(frame_data_url: str) -> tuple[str | None, float]:
    """Return ``(voter_id, confidence)`` for the largest face in the frame.

    ``voter_id`` is ``None`` when no face is found or the model is missing.
    Lower confidence means a better match.
    """
    if not settings.FACE_MODEL_PATH.exists():
        return None, 0.0
    try:
        image = decode_frame(frame_data_url)
    except ValueError:
        return None, 0.0
    gray, faces = detect_faces(image)
    if not faces:
        return None, 0.0

    # Use the largest detected face.
    box = max(faces, key=lambda f: f[2] * f[3])
    face = crop_face(gray, box)

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(str(settings.FACE_MODEL_PATH))
    label_index, confidence = recognizer.predict(face)
    label_map = _load_label_map()
    # Newer models store a mapping; fall back to the raw id for legacy models.
    voter_id = label_map.get(label_index, str(label_index))
    return voter_id, float(confidence)
