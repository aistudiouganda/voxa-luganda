"""
Audio preprocessing utilities.
Handles noise reduction, normalization, format conversion, VAD.
"""
import logging
import numpy as np
import librosa
import soundfile as sf
import tempfile
import os
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# Ugandan audio environment parameters
# Tuned for common noise profiles: traffic, market ambient, poor recording equipment
NOISE_REDUCE_KWARGS = {
    "stationary": False,
    "prop_decrease": 0.75,
    "freq_mask_smooth_hz": 500,
    "time_mask_smooth_ms": 50,
    "n_std_thresh_stationary": 1.5,
}


def apply_noise_reduction(audio_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """
    Apply noise reduction to raw PCM audio bytes (16-bit int).
    Returns processed PCM bytes.
    """
    audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    try:
        import noisereduce as nr
        reduced = nr.reduce_noise(y=audio, sr=sample_rate, **NOISE_REDUCE_KWARGS)
    except ImportError:
        reduced = audio
    output = (reduced * 32768).astype(np.int16)
    return output.tobytes()


def preprocess_audio_file(
    input_path: str,
    target_sr: int = 16000,
    apply_nr: bool = True,
    normalize: bool = True,
) -> Tuple[np.ndarray, int]:
    """
    Load and preprocess an audio file.
    Returns (audio_array, sample_rate).
    """
    # Load with librosa (handles MP3, WAV, M4A, FLAC, OGG etc.)
    audio, sr = librosa.load(input_path, sr=target_sr, mono=True)

    # Trim leading/trailing silence
    audio, _ = librosa.effects.trim(audio, top_db=25)

    # Noise reduction
    if apply_nr:
        try:
            import noisereduce as nr
            audio = nr.reduce_noise(y=audio, sr=sr, **NOISE_REDUCE_KWARGS)
        except Exception as e:
            logger.warning(f"Noise reduction failed: {e}")

    # Normalize amplitude
    if normalize and np.max(np.abs(audio)) > 0:
        audio = librosa.util.normalize(audio, norm=np.inf) * 0.95

    return audio, sr


def split_audio_by_silence(
    audio: np.ndarray,
    sr: int,
    min_silence_duration: float = 0.5,
    silence_threshold_db: float = -40.0,
    chunk_duration: float = 30.0,
) -> list:
    """
    Split audio into processable chunks using silence detection.
    Returns list of (start_sample, end_sample) tuples.
    """
    # Use librosa to detect non-silent intervals
    intervals = librosa.effects.split(
        audio,
        top_db=abs(silence_threshold_db),
        frame_length=2048,
        hop_length=512,
    )

    if len(intervals) == 0:
        return [(0, len(audio))]

    # Merge intervals that are close together
    max_gap = int(min_silence_duration * sr)
    merged = [list(intervals[0])]
    for interval in intervals[1:]:
        if interval[0] - merged[-1][1] < max_gap:
            merged[-1][1] = interval[1]
        else:
            merged.append(list(interval))

    # Further split long chunks
    max_chunk_samples = int(chunk_duration * sr)
    final_chunks = []
    for start, end in merged:
        if end - start > max_chunk_samples:
            pos = start
            while pos < end:
                final_chunks.append((pos, min(pos + max_chunk_samples, end)))
                pos += max_chunk_samples
        else:
            final_chunks.append((start, end))

    return final_chunks


def extract_audio_from_video(video_path: str) -> str:
    """
    Extract audio track from video file. Returns path to WAV file.
    Requires ffmpeg.
    """
    import subprocess
    output_path = video_path.rsplit(".", 1)[0] + "_audio.wav"
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn",  # no video
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-y",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")
    return output_path


def detect_language_segments(
    audio: np.ndarray,
    sr: int,
    whisper_model,
) -> list:
    """
    Detect language changes within audio (for code-switching detection).
    Returns list of {start, end, language} dicts.
    """
    # Split into 10-second windows and classify language
    window_size = sr * 10
    results = []

    for i in range(0, len(audio), window_size):
        chunk = audio[i:i + window_size]
        if len(chunk) < sr:  # Skip very short chunks
            continue
        # Use Whisper's language detection
        _, info = whisper_model.transcribe(chunk, task="lang_id")
        results.append({
            "start": i / sr,
            "end": min((i + window_size) / sr, len(audio) / sr),
            "language": info.language,
            "probability": info.language_probability,
        })

    return results


def compute_audio_metrics(audio: np.ndarray, sr: int) -> dict:
    """Compute quality metrics for audio analysis."""
    rms = float(librosa.feature.rms(y=audio).mean())
    spectral_centroid = float(librosa.feature.spectral_centroid(y=audio, sr=sr).mean())
    snr = float(20 * np.log10(rms / (np.std(audio[audio < np.percentile(audio, 10)]) + 1e-10) + 1e-10))

    return {
        "duration_seconds": len(audio) / sr,
        "rms_level": rms,
        "snr_db": snr,
        "spectral_centroid_hz": spectral_centroid,
        "is_noisy": snr < 15,
        "sample_rate": sr,
    }
