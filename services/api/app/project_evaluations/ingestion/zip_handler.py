from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile, ZipInfo

from fastapi import HTTPException, UploadFile, status

from services.api.app.project_evaluations.domain.models import (
    ArtifactSourceType,
    ArtifactStatus,
)
from services.api.app.project_evaluations.ingestion.file_classifier import (
    CODE_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    classify_artifact,
    classify_path,
    is_safe_zip_member,
    should_ignore_path,
)
from services.api.app.project_evaluations.ingestion.text_extractors import extract_text
from services.api.app.settings import ApiSettings


@dataclass(frozen=True)
class ExtractedArtifact:
    source_path: str
    source_type: ArtifactSourceType
    status: ArtifactStatus
    raw_text: str
    metadata: dict[str, object]


async def extract_zip_artifacts(
    evaluation_id: str,
    upload: UploadFile,
    settings: ApiSettings,
) -> list[ExtractedArtifact]:
    if not upload.filename or not upload.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="zip 파일만 업로드할 수 있습니다.",
        )

    content = await upload.read()
    max_upload_bytes = settings.APP_MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="업로드 파일이 허용 크기를 초과했습니다.",
        )

    with TemporaryDirectory(prefix=f"project-evaluation-{evaluation_id}-") as temp_dir:
        zip_path = Path(temp_dir) / "upload.zip"
        extract_dir = Path(temp_dir) / "extracted"
        zip_path.write_bytes(content)
        extract_dir.mkdir()
        return extract_zip_file(zip_path, extract_dir, settings)


def extract_zip_file(
    zip_path: Path, extract_dir: Path, settings: ApiSettings
) -> list[ExtractedArtifact]:
    try:
        with ZipFile(zip_path) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if len(members) > settings.APP_MAX_ZIP_MEMBERS:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="zip 내부 파일 개수가 허용 범위를 초과했습니다.",
                )
            total_size = sum(member.file_size for member in members)
            max_extracted_bytes = settings.APP_MAX_EXTRACTED_MB * 1024 * 1024
            if total_size > max_extracted_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="압축 해제 크기가 허용 범위를 초과했습니다.",
                )

            artifacts = []
            processed_count = 0
            for member in members:
                if not is_safe_zip_member(member.filename):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="안전하지 않은 zip 경로가 포함되어 있습니다.",
                    )
                if processed_count >= settings.APP_MAX_PROCESSED_FILES:
                    artifacts.append(skipped_artifact(member, "processed_file_limit", classify_path(member.filename)))
                    continue
                artifact = extract_member(archive, member, extract_dir, settings)
                if artifact.status == ArtifactStatus.EXTRACTED:
                    processed_count += 1
                artifacts.append(artifact)
            return artifacts
    except BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효한 zip 파일이 아닙니다.",
        ) from exc


def extract_member(
    archive: ZipFile, member: ZipInfo, extract_dir: Path, settings: ApiSettings
) -> ExtractedArtifact:
    member_name = member.filename
    classification = classify_artifact(member_name)
    source_type = classification.source_type
    metadata: dict[str, object] = {
        **member_metadata(member),
        "artifact_role": classification.artifact_role.value,
        "classification_reason": classification.reason,
    }
    if classification.language:
        metadata["language"] = classification.language
    if should_ignore_path(member_name) or source_type == ArtifactSourceType.IGNORED:
        return skipped_artifact(member, classification.reason, source_type)

    max_text_bytes = settings.APP_MAX_TEXT_FILE_MB * 1024 * 1024
    if member.file_size > max_text_bytes:
        return ExtractedArtifact(
            source_path=member_name,
            source_type=source_type,
            status=ArtifactStatus.SKIPPED,
            raw_text="",
            metadata={**metadata, "reason": "file_too_large", "limit": max_text_bytes},
        )

    target_path = safe_target_path(extract_dir, member_name)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member) as source, target_path.open("wb") as target:
        target.write(source.read(max_text_bytes + 1))
    if target_path.stat().st_size > max_text_bytes:
        target_path.unlink(missing_ok=True)
        return ExtractedArtifact(
            source_path=member_name,
            source_type=source_type,
            status=ArtifactStatus.SKIPPED,
            raw_text="",
            metadata={**metadata, "reason": "file_too_large", "limit": max_text_bytes},
        )
    try:
        text = extract_text(target_path, settings)
    except (OSError, UnicodeError, ValueError) as exc:
        return ExtractedArtifact(
            source_path=member_name,
            source_type=source_type,
            status=ArtifactStatus.FAILED,
            raw_text="",
            metadata={
                **metadata,
                "reason": "extract_failed",
                "extract_error_type": type(exc).__name__,
            },
        )

    if not text.strip():
        return ExtractedArtifact(
            source_path=member_name,
            source_type=source_type,
            status=ArtifactStatus.SKIPPED,
            raw_text="",
            metadata={**metadata, "reason": "empty_text"},
        )

    return ExtractedArtifact(
        source_path=member_name,
        source_type=source_type,
        status=ArtifactStatus.EXTRACTED,
        raw_text=text,
        metadata=metadata,
    )


def member_metadata(member: ZipInfo) -> dict[str, object]:
    return {
        "filename": member.filename,
        "extension": Path(member.filename).suffix.lower(),
        "size": member.file_size,
    }


def skipped_artifact(
    member: ZipInfo,
    reason: str,
    source_type: ArtifactSourceType = ArtifactSourceType.IGNORED,
) -> ExtractedArtifact:
    classification = classify_artifact(member.filename)
    metadata: dict[str, object] = {
        **member_metadata(member),
        "reason": reason,
        "artifact_role": classification.artifact_role.value,
        "classification_reason": classification.reason,
    }
    if reason == "unsupported_extension":
        metadata["supported_extensions"] = sorted(DOCUMENT_EXTENSIONS | CODE_EXTENSIONS)
    if classification.language:
        metadata["language"] = classification.language
    return ExtractedArtifact(
        source_path=member.filename,
        source_type=source_type,
        status=ArtifactStatus.SKIPPED,
        raw_text="",
        metadata=metadata,
    )


def safe_target_path(extract_dir: Path, member_name: str) -> Path:
    target_path = (extract_dir / member_name).resolve()
    root = extract_dir.resolve()
    if not target_path.is_relative_to(root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="안전하지 않은 zip 경로가 포함되어 있습니다.",
        )
    return target_path
