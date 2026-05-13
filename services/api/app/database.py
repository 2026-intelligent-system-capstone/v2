from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from services.api.app.project_evaluations.persistence.models import Base
from services.api.app.settings import ApiSettings


def ensure_data_paths(settings: ApiSettings) -> None:
    sqlite_path = Path(settings.APP_SQLITE_PATH)
    artifact_dir = Path(settings.APP_ARTIFACT_DIR)

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)


def create_engine_for_settings(settings: ApiSettings) -> Engine:
    engine = create_engine(
        f"sqlite:///{settings.APP_SQLITE_PATH}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def init_database(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema_columns(engine)


def ensure_schema_columns(engine: Engine) -> None:
    columns_by_table = {
        "project_evaluations": {
            "room_name": "VARCHAR(200) NOT NULL DEFAULT ''",
            "room_password_hash": "TEXT NOT NULL DEFAULT ''",
            "admin_password_hash": "TEXT NOT NULL DEFAULT ''",
            "question_policy_json": "TEXT NOT NULL DEFAULT '{}'",
        },
        "interview_sessions": {
            "participant_name": "VARCHAR(200) NOT NULL DEFAULT ''",
            "session_token_hash": "TEXT NOT NULL DEFAULT ''",
        },
        "extracted_project_contexts": {
            "rag_status_json": "TEXT NOT NULL DEFAULT '{}'",
        },
        "interview_questions": {
            "verification_focus": "TEXT NOT NULL DEFAULT ''",
            "expected_evidence": "TEXT NOT NULL DEFAULT ''",
            "source_ref_requirements": "TEXT NOT NULL DEFAULT ''",
        },
        "interview_turns": {
            "follow_up_reason": "TEXT NOT NULL DEFAULT ''",
            "finalized_score": "FLOAT",
            "conversation_history_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    }
    with engine.begin() as connection:
        for table_name, column_defs in columns_by_table.items():
            existing = {
                row[1]
                for row in connection.execute(text(f"PRAGMA table_info({table_name})"))
            }
            for column_name, column_sql in column_defs.items():
                if column_name not in existing:
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
                    )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_interview_turn_session_question "
                "ON interview_turns (session_id, question_id)"
            )
        )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session(
    session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    with session_factory() as session:
        yield session
