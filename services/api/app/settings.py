from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_ANALYSIS_MODEL: str = "gpt-4o-mini"
    OPENAI_QUESTION_MODEL: str = "gpt-4o-mini"
    OPENAI_EVAL_MODEL: str = "gpt-4o-mini"
    OPENAI_REALTIME_MODEL: str = "gpt-4o-realtime-preview-2024-12-17"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION_NAME: str = "project_evaluation_chunks"
    APP_SQLITE_PATH: str = "data/app.db"
    APP_ARTIFACT_DIR: str = "data/artifacts"
    APP_MAX_UPLOAD_MB: int = 50
    APP_MAX_EXTRACTED_MB: int = 150
    APP_MAX_TEXT_FILE_MB: int = 2
    APP_MAX_ZIP_MEMBERS: int = 500
    APP_MAX_PROCESSED_FILES: int = 120
    APP_MAX_EXTRACTED_TEXT_CHARS: int = 500_000
    APP_MAX_PDF_PAGES: int = 30
    APP_MAX_DOCX_PARAGRAPHS: int = 2_000
    APP_MAX_PPTX_SLIDES: int = 80

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )
