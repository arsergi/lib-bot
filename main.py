import json
import logging
import os

import pytesseract
import uvicorn
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lib-bot")

app = FastAPI()


@app.get("/")
def health():
    try:
        tesseract = str(pytesseract.get_tesseract_version())
    except pytesseract.TesseractNotFoundError:
        tesseract = "not installed"
    return {"status": "ok", "tesseract": tesseract}


@app.post("/groupme")
async def groupme_webhook(request: Request):
    raw = await request.body()
    try:
        payload = json.loads(raw)
        log.info("GroupMe webhook received:\n%s", json.dumps(payload, indent=2))
    except json.JSONDecodeError:
        log.warning("Webhook body was not valid JSON: %r", raw[:1000])
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
