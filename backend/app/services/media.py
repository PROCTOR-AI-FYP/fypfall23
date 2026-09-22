"""Evidence clip compression with ffmpeg.

Every uploaded clip is re-encoded, whatever the worker sent: H.264, at most
`clip_max_width` wide, `clip_fps` frames/s, no audio, no metadata, faststart
MP4 so browsers can stream it. A 2x2 contact-sheet JPEG is made from the
result; it is the permanent record once the clip is deleted.

Hardening: the container format is identified from magic bytes and ffmpeg is
told that exact demuxer with only the `file` protocol allowed, so a crafted
playlist (HLS/concat) cannot make ffmpeg fetch URLs or read other local
files. Commands run without a shell, under a timeout and a concurrency cap.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

CONTACT_SHEET_FRAMES = 4
CONTACT_SHEET_TILE_WIDTH = 320
CONTACT_SHEET_JPEG_QUALITY = 5  # ffmpeg -q:v scale, 2 (best) .. 31 (worst)
SNIFF_BYTES = 12

_semaphore: asyncio.Semaphore | None = None


class MediaProcessingError(Exception):
    """The upload is not a usable video (wrong format, too short/long, undecodable)."""


class MediaToolMissingError(RuntimeError):
    """ffmpeg/ffprobe are not installed (they are in the Docker image)."""


@dataclass(frozen=True)
class CompressedClip:
    video: bytes
    record_image: bytes
    duration_seconds: float
    original_bytes: int


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def detect_container(header: bytes) -> str:
    """Map magic bytes to an ffmpeg demuxer name; reject everything else."""
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return "mov"  # MP4 / MOV / 3GP family
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "matroska"  # MKV / WebM
    if header.startswith(b"RIFF") and header[8:12] == b"AVI ":
        return "avi"
    raise MediaProcessingError("Unsupported container; send MP4, MOV, MKV, WebM or AVI.")


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.clip_max_concurrent_transcodes)
    return _semaphore


async def _run(*args: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=settings.clip_transcode_timeout_seconds)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        raise MediaProcessingError("Video processing timed out.") from None
    if process.returncode != 0:
        detail = stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["unknown error"]
        raise MediaProcessingError(f"Video could not be processed: {detail[0][:200]}")
    return stdout


def _input_args(path: Path, demuxer: str) -> list[str]:
    return ["-protocol_whitelist", "file", "-f", demuxer, "-i", str(path)]


async def _probe_duration(path: Path, demuxer: str) -> float:
    output = await _run(
        "ffprobe", "-v", "error", "-protocol_whitelist", "file", "-f", demuxer,
        "-select_streams", "v:0", "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path),
    )
    info = json.loads(output or b"{}")
    if not info.get("streams"):
        raise MediaProcessingError("The upload contains no video stream.")
    try:
        return float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        raise MediaProcessingError("Could not read the clip duration.") from None


async def compress_clip(source: Path, workdir: Path) -> CompressedClip:
    with source.open("rb") as handle:
        demuxer = detect_container(handle.read(SNIFF_BYTES))
    if not ffmpeg_available():
        raise MediaToolMissingError("ffmpeg and ffprobe must be installed to process clips.")

    async with _get_semaphore():
        duration = await _probe_duration(source, demuxer)
        if not settings.clip_min_seconds <= duration <= settings.clip_max_seconds:
            raise MediaProcessingError(
                f"Clip must be {settings.clip_min_seconds:g}-{settings.clip_max_seconds:g} seconds long."
            )

        video_path = workdir / "clip.mp4"
        await _run(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            *_input_args(source, demuxer),
            "-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "-1",
            "-vf", f"fps={settings.clip_fps},scale='min({settings.clip_max_width},iw)':-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(settings.clip_crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-t", f"{settings.clip_max_seconds:g}",
            str(video_path),
        )
        compressed_duration = await _probe_duration(video_path, "mov")

        record_path = workdir / "record.jpg"
        await _run(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            *_input_args(video_path, "mov"),
            "-vf", f"fps={CONTACT_SHEET_FRAMES / compressed_duration:.4f},"
                   f"scale={CONTACT_SHEET_TILE_WIDTH}:-2,tile=2x2",
            "-frames:v", "1", "-q:v", str(CONTACT_SHEET_JPEG_QUALITY),
            str(record_path),
        )

    return CompressedClip(
        video=video_path.read_bytes(),
        record_image=record_path.read_bytes(),
        duration_seconds=round(compressed_duration, 2),
        original_bytes=source.stat().st_size,
    )
