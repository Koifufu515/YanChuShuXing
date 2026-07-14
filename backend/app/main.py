from fastapi import FastAPI

from app.api.error_handlers import register_error_handlers
from app.api.query import router as query_router
from app.bootstrap.container import configure_dependencies

app = FastAPI(
    title="BankInsight API",
    version="0.1.0",
    description="面向银行经营分析的智能问数与指标洞察 API",
)
app.include_router(query_router)
register_error_handlers(app)
configure_dependencies(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
