from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
router = APIRouter()


@router.get("/", include_in_schema=False)
def serve_frontend_index() -> FileResponse:
    index_path = FRONTEND_DIST / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="frontend build is not available")
    return FileResponse(index_path, media_type="text/html")


@router.get("/{frontend_path:path}", include_in_schema=False)
def serve_frontend_asset(frontend_path: str) -> FileResponse:
    if frontend_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")

    index_path = FRONTEND_DIST / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="frontend build is not available")

    root = FRONTEND_DIST.resolve()
    candidate = (FRONTEND_DIST / frontend_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        candidate = index_path

    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(index_path, media_type="text/html")
