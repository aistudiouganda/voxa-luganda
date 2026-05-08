"""WebSocket endpoint for real-time streaming transcription."""
import asyncio
import json
import logging
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter()


class StreamingTranscriber:
    """Manages a live transcription WebSocket session."""

    def __init__(self, websocket: WebSocket, language: str = "lug", translate: bool = True):
        self.ws = websocket
        self.language = language
        self.translate = translate
        self.audio_buffer = bytearray()
        self.chunk_duration_ms = 500  # Process every 500ms
        self.sample_rate = 16000
        self.bytes_per_sample = 2  # 16-bit PCM
        self.chunk_bytes = int(self.sample_rate * self.bytes_per_sample * self.chunk_duration_ms / 1000)
        self.current_speaker = 0
        self.segment_id = 0

    async def send(self, data: dict):
        await self.ws.send_json(data)

    async def process_chunk(self, audio_bytes: bytes):
        """Process audio chunk through the pipeline."""
        self.audio_buffer.extend(audio_bytes)

        # Process when we have enough data
        if len(self.audio_buffer) >= self.chunk_bytes:
            chunk = bytes(self.audio_buffer[:self.chunk_bytes])
            self.audio_buffer = self.audio_buffer[self.chunk_bytes:]
            await self._transcribe_chunk(chunk)

    async def _transcribe_chunk(self, chunk: bytes):
        """Run ASR on a chunk and stream result."""
        try:
            from services.model_manager import model_manager

            # Transcribe with Whisper
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                model_manager.transcribe_chunk,
                chunk,
                self.language,
                self.sample_rate,
            )

            if not result or not result.get("text", "").strip():
                return

            self.segment_id += 1
            payload = {
                "type": "segment",
                "id": self.segment_id,
                "speaker": self.current_speaker,
                "text": result["text"].strip(),
                "language": result.get("language", self.language),
                "confidence": result.get("confidence", 0.9),
                "timestamp": time.time(),
                "partial": result.get("partial", False),
            }

            # Translate if requested
            if self.translate and result.get("language") in ("lug", "luganda"):
                translation = await asyncio.get_event_loop().run_in_executor(
                    None,
                    model_manager.translate,
                    result["text"],
                    "lug_Latn",
                    "eng_Latn",
                )
                payload["translation"] = translation

            await self.send(payload)

        except Exception as e:
            logger.error(f"Chunk transcription error: {e}")
            await self.send({"type": "error", "message": str(e)})


@router.websocket("/transcribe")
async def live_transcription(
    websocket: WebSocket,
    language: str = Query("lug"),
    translate: bool = Query(True),
    noise_reduction: bool = Query(True),
    token: Optional[str] = Query(None),
):
    """
    WebSocket endpoint for real-time audio transcription.

    Client sends:
      - Binary: raw PCM audio (16-bit, 16kHz, mono)
      - JSON: control messages {"type": "config", ...}

    Server sends:
      - {"type": "segment", "text": "...", "translation": "...", ...}
      - {"type": "speaker_change", "speaker": 1, ...}
      - {"type": "error", "message": "..."}
      - {"type": "connected", "session_id": "..."}
    """
    await websocket.accept()

    transcriber = StreamingTranscriber(websocket, language=language, translate=translate)
    session_id = f"sess_{int(time.time())}"

    await transcriber.send({
        "type": "connected",
        "session_id": session_id,
        "config": {
            "language": language,
            "translate": translate,
            "noise_reduction": noise_reduction,
            "sample_rate": transcriber.sample_rate,
            "chunk_duration_ms": transcriber.chunk_duration_ms,
        }
    })
    logger.info(f"WebSocket session started: {session_id}")

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message:
                # Audio data
                audio_data = message["bytes"]
                if noise_reduction:
                    from services.audio_processor import apply_noise_reduction
                    audio_data = await asyncio.get_event_loop().run_in_executor(
                        None, apply_noise_reduction, audio_data, transcriber.sample_rate
                    )
                await transcriber.process_chunk(audio_data)

            elif "text" in message:
                # Control message
                try:
                    ctrl = json.loads(message["text"])
                    if ctrl.get("type") == "speaker_change":
                        transcriber.current_speaker = ctrl.get("speaker", 0)
                    elif ctrl.get("type") == "stop":
                        break
                except json.JSONDecodeError:
                    pass

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error [{session_id}]: {e}")
        try:
            await transcriber.send({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        logger.info(f"WebSocket session ended: {session_id}")
