"""Hindi speech recognition with AI4Bharat IndicConformer (MIT licence,
https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual), CTC decoding, run locally on CPU.

Why this model and not an LLM: in our tests an LLM transcriber "fixed" children's wrong words, so a
child who misread was marked as reading well. A CTC acoustic model writes what it hears.
The loading/decoding below follows AI4Bharat's model_onnx.py (MIT), reduced to Hindi CTC.
"""
import json
import os
import pathlib
import subprocess

import numpy as np
import onnxruntime as ort
import torch

MODEL_DIR = pathlib.Path(os.environ.get("MODEL_DIR", os.path.expanduser("~/models/indic-conformer")))
SAMPLE_RATE = 16000
BLANK_ID = 256


def decode_audio(path):
    """Any phone recording (wav, webm/opus, mp4/aac, ogg) -> 16 kHz mono float32, via ffmpeg."""
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def has_speech(samples, frame=400, min_voiced_s=0.3):
    """Rough energy check: at least 0.3 s of 25 ms frames louder than -40 dBFS."""
    n = len(samples) // frame
    if n == 0:
        return False
    rms = np.sqrt(np.mean(np.square(samples[: n * frame].reshape(n, frame)), axis=1))
    return int((rms > 0.01).sum()) * frame / SAMPLE_RATE >= min_voiced_s


class Transcriber:
    def __init__(self, model_dir=MODEL_DIR):
        assets = pathlib.Path(model_dir) / "assets"
        if not (assets / "encoder.onnx").exists():
            raise FileNotFoundError(f"IndicConformer model not found in {model_dir}")
        opts = ort.SessionOptions(); opts.intra_op_num_threads = int(os.environ.get("ASR_THREADS", "4"))
        self.pre = torch.jit.load(str(assets / "preprocessor.ts"), map_location="cpu")
        self.encoder = ort.InferenceSession(str(assets / "encoder.onnx"), opts, providers=["CPUExecutionProvider"])
        self.ctc = ort.InferenceSession(str(assets / "ctc_decoder.onnx"), opts, providers=["CPUExecutionProvider"])
        self.vocab = json.loads((assets / "vocab.json").read_text())["hi"]
        self.mask = json.loads((assets / "language_masks.json").read_text())["hi"]

    def transcribe(self, samples):
        """samples: 16 kHz mono float32. Returns (text, seconds of audio)."""
        secs = len(samples) / SAMPLE_RATE
        if len(samples) < SAMPLE_RATE // 4 or not has_speech(samples):
            return "", secs          # silence: the model would otherwise invent a syllable
        samples = np.array(samples, dtype=np.float32)   # writable copy for torch
        wav = torch.from_numpy(np.ascontiguousarray(samples)).unsqueeze(0)
        with torch.no_grad():
            feats, length = self.pre(input_signal=wav, length=torch.tensor([wav.shape[-1]]))
        enc, _ = self.encoder.run(["outputs", "encoded_lengths"], {"audio_signal": feats.numpy(), "length": length.numpy()})
        logp = self.ctc.run(["logprobs"], {"encoder_output": enc})[0][0][:, self.mask]
        ids = logp.argmax(-1)
        keep = [int(i) for k, i in enumerate(ids) if i != BLANK_ID and (k == 0 or i != ids[k - 1])]
        text = "".join(self.vocab[i] for i in keep).replace("▁", " ").strip()
        return text, secs

    def transcribe_file(self, path):
        return self.transcribe(decode_audio(path))[0]
