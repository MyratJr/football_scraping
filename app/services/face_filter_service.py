import logging
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from app.core.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MIN_FACE_PX = 40      # ignore tiny background faces (they cause false matches)
MIN_DET_SCORE = 0.6   # ignore uncertain detections
MIN_REFERENCES = 3


def _read_image(path: Path):
    # np.fromfile + imdecode also works with non-ASCII Windows paths
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


class FaceFilterService:
    """Checks images and videos for a specific person using reference photos."""

    def __init__(self, reference_dir: str, threshold: float, video_frames: int, model_dir: str) -> None:
        self._threshold = threshold
        self._video_frames = video_frames
        self._app = FaceAnalysis(
            name="buffalo_l",
            root=str(Path(model_dir).resolve()),   # models go to <model_dir>/models/buffalo_l
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "recognition"],
        )
        self._app.prepare(ctx_id=-1, det_size=(640, 640))
        self._refs = self._load_references(Path(reference_dir))
        logger.info("Face filter ready: %d reference faces, threshold %.2f",
                    len(self._refs), threshold)

    # ------------------------------------------------------------------ references
    def _load_references(self, folder: Path) -> np.ndarray:
        embeddings = []
        for p in sorted(folder.glob("*")):
            if p.suffix.lower() not in IMAGE_EXT:
                continue
            img = _read_image(p)
            faces = self._app.get(img) if img is not None else []
            if not faces:
                logger.warning("No face found in reference %s, skipped", p.name)
                continue
            # use the largest face in the photo
            face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
            embeddings.append(face.normed_embedding)

        if len(embeddings) < MIN_REFERENCES:
            # fail loudly: silently passing every post would defeat the filter
            raise RuntimeError(
                f"Need at least {MIN_REFERENCES} usable reference photos in '{folder}', "
                f"found {len(embeddings)}"
            )
        return np.stack(embeddings)

    # ------------------------------------------------------------------ scoring
    def best_score(self, img) -> float:
        """Highest similarity between any face in `img` and any reference photo."""
        faces = [
            f for f in self._app.get(img)
            if f.det_score >= MIN_DET_SCORE and (f.bbox[2] - f.bbox[0]) >= MIN_FACE_PX
        ]
        if not faces:
            return 0.0
        query = np.stack([f.normed_embedding for f in faces])
        return float((query @ self._refs.T).max())  # embeddings are normalized: dot = cosine

    def frames(self, video_path: Path) -> Iterator[tuple[int, np.ndarray]]:
        cap = cv2.VideoCapture(str(video_path))
        try:
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total <= 0:
                return
            for idx in np.linspace(0, total - 1, min(self._video_frames, total), dtype=int):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
                ok, frame = cap.read()
                if ok:
                    yield int(idx), frame
        finally:
            cap.release()

    # ------------------------------------------------------------------ public API
    def find_match(self, image_paths: list[str] | None, video_paths: list[str] | None) -> str | None:
        for p in image_paths or []:
            img = _read_image(Path(p))
            if img is None:
                continue
            score = self.best_score(img)
            if score >= self._threshold:
                return f"face match in {Path(p).name} (score {score:.2f})"

        for vp in video_paths or []:
            if not Path(vp).exists():
                continue
            for idx, frame in self.frames(Path(vp)):
                score = self.best_score(frame)
                if score >= self._threshold:
                    return f"face match in {Path(vp).name} frame {idx} (score {score:.2f})"
        return None


@lru_cache
def get_face_filter() -> FaceFilterService:
    """One model per worker process. The task container is rebuilt on every run,
    so a container provider would reload the model each time."""
    return FaceFilterService(
        settings.FACE_REFERENCE_DIR,
        settings.FACE_MATCH_THRESHOLD,
        settings.FACE_VIDEO_FRAMES,
        settings.FACE_MODEL_DIR,
    )


if __name__ == "__main__":
    # Tuning tool: python -m app.services.face_filter_service media\images\X_1.jpg media\reels\Y.mp4
    import sys

    svc = get_face_filter()
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.suffix.lower() in IMAGE_EXT:
            score = svc.best_score(_read_image(p))
        else:
            score = max((svc.best_score(f) for _, f in svc.frames(p)), default=0.0)
        print(f"{score:.3f}  {arg}")