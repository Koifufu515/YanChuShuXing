from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.error_handlers import register_error_handlers
from app.api.examples import router as examples_router
from app.api.query import router as query_router
from app.bootstrap.container import configure_dependencies
from app.application.errors import ApplicationError
from app.bootstrap.container import PROJECT_ROOT
from app.core.data_source import describe_data_source
from app.core.settings import Settings

app = FastAPI(
    title="言出数行——银行智能问数与协同分析系统 API",
    version="0.5.2",
    description="面向银行经营分析场景的智能问数与协同分析 API",
)
app.include_router(query_router)
app.include_router(examples_router)
register_error_handlers(app)
configure_dependencies(app)


_CANDIDATE_FRONTEND = Path(__file__).resolve().parents[2] / "candidate_frontend"


@app.get("/candidate", include_in_schema=False)
def candidate_frontend() -> FileResponse:
    return FileResponse(_CANDIDATE_FRONTEND / "index.html")


app.mount(
    "/candidate/assets",
    StaticFiles(directory=_CANDIDATE_FRONTEND),
    name="candidate-frontend-assets",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready():
    data_environment = "real"
    try:
        settings = Settings.from_env(PROJECT_ROOT / ".env")
        data_environment = settings.data_environment
        payload = describe_data_source(
            PROJECT_ROOT,
            settings.data_environment,
            settings.database_path_override,
        )
        return {"status": "ready", **payload}
    except ApplicationError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "data_environment": data_environment,
                "database_ready": False,
                "error": exc.public_message,
            },
        )
