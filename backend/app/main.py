from fastapi import FastAPI

app = FastAPI(title="Metadex API", version="0.1.0")


@app.get("/")
async def root() -> dict[str, str]:
    """Confirm that the backend scaffold is available."""
    return {"name": "Metadex API", "status": "ready"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Expose a minimal, dependency-free health check."""
    return {"status": "ok"}
