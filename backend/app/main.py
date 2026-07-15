from fastapi import FastAPI

from app.api.error_handlers import register_error_handlers
from app.api.query import router as query_router
from app.bootstrap.container import configure_dependencies

app = FastAPI(
    title="言出数行——银行智能问数与协同分析系统 API",
    version="0.5.2",
    description="面向银行经营分析场景的智能问数与协同分析 API",
)
app.include_router(query_router)
register_error_handlers(app)
configure_dependencies(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
