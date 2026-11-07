"""File storage behind one small interface (IMPLEMENTATION_PLAN §4: S3/R2 can implement it later).

Layout under STORAGE_DIR (gitignored):
    uploads/<lecture_id>/original.<ext>   the file the user uploaded
    audio/<lecture_id>/chunk_000.flac     16 kHz mono pieces sent to speech recognition

Paths are built only from the lecture UUID and an allow-listed extension, never from the
user's file name, so an upload cannot write outside the storage folder.
"""

import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol

from fastapi import status

from app.core.errors import AppError

if TYPE_CHECKING:
    from app.core.config import Settings

COPY_BLOCK = 1024 * 1024  # 1 MiB


class FileTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "FILE_TOO_LARGE"


class StorageService(Protocol):
    def save_upload(self, stream: BinaryIO, lecture_id: uuid.UUID, ext: str, max_bytes: int) -> tuple[Path, int]: ...
    def upload_path(self, lecture_id: uuid.UUID, ext: str) -> Path: ...
    def audio_dir(self, lecture_id: uuid.UUID) -> Path: ...
    def delete_lecture(self, lecture_id: uuid.UUID) -> None: ...
    def relative(self, path: Path) -> str: ...
    def resolve(self, rel: str) -> Path: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def upload_path(self, lecture_id: uuid.UUID, ext: str) -> Path:
        return self.root / "uploads" / str(lecture_id) / f"original.{ext}"

    def audio_dir(self, lecture_id: uuid.UUID) -> Path:
        return self.root / "audio" / str(lecture_id)

    def save_upload(self, stream: BinaryIO, lecture_id: uuid.UUID, ext: str, max_bytes: int) -> tuple[Path, int]:
        """Copy the upload to disk in 1 MiB blocks; stop and clean up as soon as it exceeds max_bytes."""
        dest = self.upload_path(lecture_id, ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with dest.open("wb") as out:
                while block := stream.read(COPY_BLOCK):
                    written += len(block)
                    if written > max_bytes:
                        raise FileTooLargeError(
                            f"File is larger than the {max_bytes // (1024 * 1024)} MB limit",
                            details={"max_mb": max_bytes // (1024 * 1024)},
                        )
                    out.write(block)
        except BaseException:
            shutil.rmtree(dest.parent, ignore_errors=True)
            raise
        return dest, written

    def relative(self, path: Path) -> str:
        """Path stored in the database: relative to STORAGE_DIR, with forward slashes."""
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()

    def resolve(self, rel: str) -> Path:
        full = (self.root / rel).resolve()
        if not full.is_relative_to(self.root.resolve()):
            raise ValueError("path escapes the storage folder")
        return full

    def delete_lecture(self, lecture_id: uuid.UUID) -> None:
        for folder in (self.root / "uploads" / str(lecture_id), self.audio_dir(lecture_id)):
            shutil.rmtree(folder, ignore_errors=True)


def storage_from_settings(settings: "Settings") -> StorageService:
    return LocalStorage(settings.storage_path)
