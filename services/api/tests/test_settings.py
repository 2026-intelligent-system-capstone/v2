from pathlib import Path

from services.api.app.database import ensure_data_paths
from services.api.app.settings import ApiSettings


def test_api_settings_load_default_values() -> None:
    settings = ApiSettings()

    assert settings.OPENAI_EMBEDDING_MODEL == "text-embedding-3-small"
    assert settings.QDRANT_COLLECTION_NAME == "project_evaluation_chunks"


def test_ensure_data_paths_creates_sqlite_parent_and_artifact_dir(
    tmp_path: Path,
) -> None:
    sqlite_path = tmp_path / "nested" / "app.db"
    artifact_dir = tmp_path / "artifacts"
    settings = ApiSettings(
        APP_SQLITE_PATH=str(sqlite_path),
        APP_ARTIFACT_DIR=str(artifact_dir),
    )

    ensure_data_paths(settings)

    assert sqlite_path.parent.is_dir()
    assert artifact_dir.is_dir()
