# Phase 2 索引流水線指南 — Indexing Pipeline

> **Goal**: A file dropped in `inbox/` is processed end-to-end and appears in Qdrant.
> **Duration**: 3-4 days
> **Prerequisites**: Phase 1 complete

---

## 2.1 Pipeline overview

```
File in /Volumes/RAID/AISecondBrain/inbox/
  │
  ▼
[FSEvents watcher] (macOS) / [inotify watcher] (Linux)
  │
  ▼
[Single-worker queue]   ← v3 invariant: ONE worker only
  │
  ▼
[ffprobe] → detect type, duration, codec
  │
  ├── text (*.md, *.txt, *.pdf, *.docx)
  │     → chunk by paragraph (max 512 tokens)
  │     → embed with nomic-embed-text
  │     → write to Qdrant (text_vec) + SQLite (chunks.db)
  │
  ├── image (*.jpg, *.png, *.heic)
  │     → resize to 224x224
  │     → embed with MobileCLIP-S0
  │     → write to Qdrant (image_vec) + SQLite (chunks.db)
  │
  ├── video (*.mp4, *.mov, *.mkv)
  │     → PySceneDetect (AdaptiveDetector) → segments ≤10s
  │     → for each segment: ffmpeg → middle frame
  │     → embed middle frame with MobileCLIP-S0
  │     → (optional) whisper transcription of audio
  │     → write to Qdrant (image_vec + text_vec) + SQLite
  │
  └── audio (*.mp3, *.m4a, *.wav)
        → whisper.cpp tiny → transcript
        → chunk transcript by sentence
        → embed with nomic-embed-text
        → write to Qdrant (text_vec) + SQLite
  │
  ▼
[SQLite (files.db)]  ← file metadata, hash, mtime
  │
  ▼
[Move file]  ← from inbox/ to media/photos|videos|audio|private
               (user approval, NEVER auto-move)
```

## 2.2 Single worker (v3 invariant)

The indexer is **single-threaded**. Parallelism is OK at the *embedding*
step (one file → N chunks → N embed calls in batch), but **not** at the
*file* step. This preserves the v3 invariant that "the index is always
consistent" — no two files are processed simultaneously.

```python
# src/scripts/indexer.py (excerpt)
class Indexer:
    def __init__(self, config):
        self.queue = Queue(maxsize=100)
        self.worker = Thread(target=self._consume, daemon=True)
        self.worker.start()

    def _consume(self):
        while True:
            filepath = self.queue.get()
            try:
                self._process_file(filepath)
            except Exception as e:
                log.error(f"Failed: {filepath}: {e}")
            finally:
                self.queue.task_done()
```

## 2.3 FSEvents / inotify watcher

```python
# src/scripts/watcher.py
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class InboxHandler(FileSystemEventHandler):
    def __init__(self, queue):
        self.queue = queue

    def on_created(self, event):
        if not event.is_directory:
            self.queue.put(event.src_path)

# On M1 (macOS), FSEvents is used by watchdog under the hood
# On workstation (Linux), inotify is used
```

## 2.4 Chunking strategies

### Text

```python
def chunk_text(text: str, max_tokens: int = 512) -> list[str]:
    """Split text by paragraph, capped at max_tokens."""
    paragraphs = text.split("\n\n")
    chunks = []
    current = []
    current_tokens = 0
    for p in paragraphs:
        tokens = len(p.split())
        if current_tokens + tokens > max_tokens and current:
            chunks.append("\n\n".join(current))
            current = [p]
            current_tokens = tokens
        else:
            current.append(p)
            current_tokens += tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks
```

### Image

```python
def prepare_image(path: str) -> np.ndarray:
    """Resize to 224x224, normalize for MobileCLIP."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    img = img.resize((224, 224), Image.LANCZOS)
    arr = np.array(img, dtype=np.float32) / 255.0
    return arr
```

### Video (PySceneDetect)

```python
from scenedetect import open_video, SceneManager, AdaptiveDetector

def slice_video(path: str, max_segment_sec: int = 10) -> list[tuple[float, float]]:
    """Return list of (start, end) tuples, each ≤ max_segment_sec."""
    video = open_video(path)
    sm = SceneManager()
    sm.add_detector(AdaptiveDetector())
    sm.detect_scenes(video)
    raw_scenes = sm.get_scene_list()

    segments = []
    for start, end in raw_scenes:
        start_sec = start.get_seconds()
        end_sec = end.get_seconds()
        if end_sec - start_sec > max_segment_sec:
            # Split long scenes into max_segment_sec chunks
            t = start_sec
            while t < end_sec:
                segments.append((t, min(t + max_segment_sec, end_sec)))
                t += max_segment_sec
        else:
            segments.append((start_sec, end_sec))
    return segments
```

### Audio (whisper)

```python
import whisper

def transcribe_audio(path: str) -> str:
    """Use whisper.cpp tiny (M1) or faster-whisper (workstation)."""
    # On M1: call whisper.cpp via subprocess
    # On workstation: use faster-whisper directly
    ...
```

## 2.5 Embedding calls

```python
# Text (always on M1)
def embed_text(text: str) -> list[float]:
    import requests
    r = requests.post("http://127.0.0.1:11434/api/embeddings",
                      json={"model": "nomic-embed-text", "prompt": text})
    return r.json()["embedding"]  # 768-dim

# Image (always on M1)
def embed_image(arr: np.ndarray) -> list[float]:
    from mobileclip import MobileCLIP
    model = MobileCLIP.from_pretrained("apple/mobileclip-s0")
    return model.encode_image(arr).tolist()  # 512-dim

# Long text (on-demand, workstation)
def embed_text_long(text: str) -> list[float]:
    from flagembedding import BGEM3
    model = BGEM3()
    return model.encode([text])["dense_vecs"][0].tolist()  # 1024-dim
```

## 2.6 Qdrant upsert

```python
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

client = QdrantClient(url="http://127.0.0.1:6333")

def upsert_point(file_id: str, chunk_id: int, text_vec=None, image_vec=None, payload: dict):
    vectors = {}
    if text_vec is not None:
        vectors["text_vec"] = text_vec
    if image_vec is not None:
        vectors["image_vec"] = image_vec

    point = PointStruct(
        id=hash(f"{file_id}:{chunk_id}") % (2**63),  # stable id
        vector=vectors,
        payload={
            "file_id": file_id,
            "chunk_id": chunk_id,
            "ingested_at": datetime.utcnow().isoformat(),
            **payload,
        }
    )
    client.upsert(collection_name="second_brain", points=[point])
```

**Note**: The point id is `hash(file_id:chunk_id) % 2^63` so re-running
the indexer is idempotent.

## 2.7 SQLite metadata

```sql
-- files.db
CREATE TABLE files (
    file_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    type TEXT NOT NULL,        -- 'text', 'image', 'video', 'audio'
    size_bytes INTEGER,
    hash_sha256 TEXT,
    mtime INTEGER,
    indexed_at INTEGER,
    chunks INTEGER DEFAULT 0,
    suggested_move TEXT        -- v3: "Move to media/photos?"; NULL if not yet
);

-- chunks.db (could be separate; for v4 we keep in files.db)
CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    file_id TEXT REFERENCES files(file_id),
    chunk_index INTEGER,
    chunk_type TEXT,            -- 'paragraph', 'frame', 'transcript'
    text_content TEXT,          -- for text/transcript chunks
    point_id INTEGER            -- Qdrant point id
);
```

## 2.8 "Never auto-move" enforcement

```python
# After indexing, ask Hermes to suggest a move (but never do it)
def suggest_move(file_id: str):
    file_info = db.get_file(file_id)
    suggestion = hermes.suggest_move(file_info)
    db.set_suggested_move(file_id, suggestion)
    return suggestion
    # e.g. "Looks like a photo. Move to /Volumes/RAID/AISecondBrain/media/photos/? (y/N)"

# The actual move only happens with explicit user input
def confirm_move(file_id: str):
    """Called only when user types 'y' to the suggestion."""
    ...
```

## 2.9 End-to-end test

```bash
# Drop a test file in inbox/
cp ~/Pictures/test_photo.jpg /Volumes/RAID/AISecondBrain/inbox/

# Watch the indexer log
tail -f ~/ai-brain/logs/indexer.log

# Within 30s, should see:
#   [INFO] Detected: test_photo.jpg (image, 2.3MB)
#   [INFO] Resized to 224x224
#   [INFO] Embedded with MobileCLIP-S0 (1 vector)
#   [INFO] Upserted to Qdrant: point_id=123456789
#   [INFO] Suggestion: "Move to /Volumes/RAID/AISecondBrain/media/photos/?"

# Verify in Qdrant
curl -s -X POST http://127.0.0.1:6333/collections/second_brain/points/scroll \
  -H "Content-Type: application/json" \
  -d '{"limit": 5, "with_payload": true, "with_vector": false}' | jq
```

## 2.10 Common gotchas

| Problem | Fix |
|---|---|
| Indexer hangs on HEIC | Convert to JPG first (`sips -s format jpeg`) |
| PySceneDetect misses cuts | Lower `AdaptiveDetector.threshold` from 3.0 to 2.0 |
| Whisper mis-transcribes Chinese | Route to workstation's faster-whisper large-v3 |
| SQLite locks | Use WAL mode: `PRAGMA journal_mode=WAL` |
| Qdrant OOM on big batches | Reduce `UPSERT_BATCH` from 100 to 10 |
| FSEvents not firing | Check SIP isn't blocking; restart indexer |

---

## Next phase

→ [`Phase_3_Hermes整合指南.md`](Phase_3_Hermes整合指南.md) — Hermes integration
