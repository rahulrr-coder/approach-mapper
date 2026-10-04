import os
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.llm import LLMError, map_approach

STATIC = Path(__file__).resolve().parent.parent / "static"
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_TXT_CHARS = 12_000

app = FastAPI(title="Approach Mapper")


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


@app.get("/api/health")
def health():
    return {"ok": True, "model": os.getenv("LLM_MODEL", "")}


@app.post("/api/map")
async def map_problem(text: str = Form(""), files: list[UploadFile] = File(default=[])):
    max_bytes = int(os.getenv("MAX_UPLOAD_MB", "8")) * 1024 * 1024
    parts, images = [text.strip()], []
    for f in files:
        data = await f.read()
        if len(data) > max_bytes:
            return err(413, f"{f.filename} is larger than {max_bytes // 1024 // 1024} MB.")
        if f.content_type in IMAGE_TYPES:
            images.append(data)
        elif (f.filename or "").lower().endswith(".txt") or f.content_type == "text/plain":
            parts.append(data.decode("utf-8", errors="replace"))
        else:
            return err(415, f"{f.filename}: only jpg, png, webp images and .txt files are supported.")
    if len(images) > 3:
        return err(400, "Please upload at most 3 images.")
    problem = "\n\n".join(p for p in parts if p)[:MAX_TXT_CHARS]
    if not problem and not images:
        return err(400, "Paste a problem or upload an image/.txt file first.")
    try:
        approach, meta = map_approach(problem, images)
    except LLMError as e:
        return err(e.status, e.message)
    return {"approach": approach.model_dump(by_alias=True), "meta": meta}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
