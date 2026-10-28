"""Optional standalone V3 deployment, without the legacy public V2 routes.

NSO_V3_SERVICE=all|npm|ipm|optimizer selects independently deployed API surfaces.
All instances must use the same durable store behind an authenticated gateway.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from research_api import router, audit_access
import research_workflows_api  # registers workflows before mounting the router  # noqa: F401
import research_operations_api  # noqa: F401
import research_extension_api  # noqa: F401
import research_demo_api  # noqa: F401


def create_app(service_name=None):
    name = service_name or os.getenv("NSO_V3_SERVICE", "all")
    if name not in {"all", "npm", "ipm", "optimizer"}:
        raise ValueError("NSO_V3_SERVICE must be all, npm, ipm or optimizer")
    production = os.getenv("NSO_ENV", "development").lower() == "production"
    app = FastAPI(
        title=f"NSO V3 {name} research",
        version="3.0.0-research.1",
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            x.strip() for x in os.getenv("ALLOWED_ORIGINS", "").split(",") if x.strip()
        ],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    app.include_router(router)
    if name != "all":
        selectors = {
            "npm": (
                "/npm/",
                "/demo/npm",
                "/demo/training",
                "/models/",
                "/outcomes/",
                "/releases/",
            ),
            "ipm": ("/ipm/", "/studies/", "/adaptive/", "/demo/study"),
            "optimizer": (
                "/optimizer/",
                "/manufacturing/",
                "/designs/",
                "/releases/review",
                "/demo/optics",
            ),
        }
        common = {
            "/api/v3/health",
            "/api/v3/research",
            "/api/v3/cases",
            "/api/v3/observations",
            "/api/v3/exposures",
        }
        app.router.routes[:] = [
            r
            for r in app.router.routes
            if not r.path.startswith("/api/v3/")
            or r.path in common
            or r.path.startswith("/api/v3/cases/")
            or any(part in r.path for part in selectors[name])
        ]

    @app.middleware("http")
    async def no_store(request, call_next):
        from nso.research_security import request_limit

        blocked = request_limit(request)
        if blocked is not None:
            return blocked
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-NSO-Research-Service"] = name
        audit_access(request, response.status_code)
        return response

    return app


app = create_app()
