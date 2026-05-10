from fastapi import FastAPI

from services.api.app.database import (
    create_engine_for_settings,
    create_session_factory,
    ensure_data_paths,
    init_database,
)
from services.api.app.project_evaluations.router import (
    router as project_evaluations_router,
)
from services.api.app.project_evaluations.router_realtime import (
    router as realtime_router,
)
from services.api.app.settings import ApiSettings


def create_app() -> FastAPI:
    settings = ApiSettings()
    ensure_data_paths(settings)
    engine = create_engine_for_settings(settings)
    init_database(engine)

    app = FastAPI(title="Project Evaluation API")
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.include_router(project_evaluations_router)
    app.include_router(realtime_router)

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "project-evaluation-api",
            "storage": {"sqlite_path": settings.APP_SQLITE_PATH},
        }

    return app


app = create_app()
