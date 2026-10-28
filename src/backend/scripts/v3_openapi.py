"""Export V3 OpenAPI 3.1 from a development-only app, regardless of production docs setting."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from research_api import router
import research_workflows_api  # noqa: F401
import research_operations_api  # noqa: F401
import research_demo_api  # noqa: F401

app = FastAPI(title="NSO V3 Research API", version="3.0.0-research.1")
app.include_router(router)
if __name__ == "__main__":
    print(json.dumps(app.openapi(), indent=2))
