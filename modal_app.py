"""Deploy Kahani Tak on Modal: `modal deploy modal_app.py`.
One warm CPU container (the speech model takes ~2.4 GB and ~20 s to load), SQLite + recordings on a
Modal volume, committed shortly after every write."""
import threading
import time

import modal

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install("torch==2.5.1", "torchaudio==2.5.1", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install("onnxruntime==1.20.1", "fastapi==0.115.6", "python-multipart==0.0.20", "numpy<2.2", "soundfile==0.12.1")
    .env({"MODEL_DIR": "/models/indic-conformer", "DATA_DIR": "/data", "ASR_THREADS": "2"})
    .add_local_dir("kahani", "/root/kahani", ignore=["__pycache__"])
)
models = modal.Volume.from_name("kahani-models")
data = modal.Volume.from_name("kahani-data")
app = modal.App("kahani-tak", image=image)


@app.function(cpu=2.0, memory=6144, volumes={"/models": models, "/data": data},
              secrets=[modal.Secret.from_name("kahani-test")],
              min_containers=1, max_containers=1, timeout=300, scaledown_window=1200)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def web():
    from kahani import server
    dirty = threading.Event()
    server.after_write = dirty.set

    def committer():
        while True:
            time.sleep(15)
            if dirty.is_set():
                dirty.clear()
                try:
                    data.commit()
                except Exception as e:   # logged loudly; the next write retries
                    print("volume commit failed:", e, flush=True)
    threading.Thread(target=committer, daemon=True).start()
    return server.app
