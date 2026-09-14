import asyncio
import io
import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytesseract
import uvicorn
from fastapi import FastAPI, Request
from PIL import Image

from parser import Reservation, format_schedule, merge_reservations, parse_screenshots

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lib-bot")

BOT_ID = os.environ.get("GROUPME_BOT_ID", "")
# Scholarship chair and Andrew. Override with the ALLOWED_SENDER_IDS variable in Railway.
DEFAULT_ALLOWED_SENDERS = "114035989,106005336"
ALLOWED_SENDERS = set(re.findall(r"\d+", os.environ.get("ALLOWED_SENDER_IDS") or DEFAULT_ALLOWED_SENDERS))
WAIT_SECONDS = int(os.environ.get("WAIT_SECONDS", "60"))
# On Railway this is the volume (/data). On a Mac it falls back to the ignored debug/ folder.
SAVED_FILE = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "debug")) / "reservations.json"
NC_TIME = ZoneInfo("America/New_York")
GROUPME_MAX_LENGTH = 1000

log.info("Allowed sender IDs: %s", ", ".join(sorted(ALLOWED_SENDERS)))

app = FastAPI()

pending_image_urls = []
timer_task = None
background_tasks = set()  # keeps running tasks from being garbage collected
processing_lock = asyncio.Lock()


def now_in_nc():
    return datetime.now(NC_TIME).replace(tzinfo=None)


def load_saved():
    if not SAVED_FILE.exists():
        return []
    rows = json.loads(SAVED_FILE.read_text())
    return [Reservation(r["library"], r["room"], date.fromisoformat(r["day"]), r["start"], r["end"]) for r in rows]


def save(reservations):
    rows = [{**r.__dict__, "day": r.day.isoformat()} for r in reservations]
    SAVED_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = SAVED_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(rows, indent=2))
    temp_file.replace(SAVED_FILE)  # swap in all at once so a crash can't leave half a file


def ocr(image_bytes):
    return pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))


async def read_screenshots(urls):
    texts = []
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for number, url in enumerate(urls, start=1):
            try:
                response = await client.get(url)
                response.raise_for_status()
                text = await asyncio.to_thread(ocr, response.content)
                log.info("OCR text from screenshot %d of %d:\n%s", number, len(urls), text)
                texts.append(text)
            except Exception:
                log.exception("Couldn't read screenshot %d of %d: %s", number, len(urls), url)
    return texts


def split_message(message):
    """GroupMe cuts off long messages, so break at line boundaries if needed."""
    chunks = [""]
    for line in message.split("\n"):
        if chunks[-1] and len(chunks[-1]) + 1 + len(line) > GROUPME_MAX_LENGTH:
            chunks.append("")
        chunks[-1] = f"{chunks[-1]}\n{line}" if chunks[-1] else line
    return [chunk.strip("\n") for chunk in chunks if chunk.strip()]


async def post_to_groupme(message):
    if not BOT_ID:
        log.warning("GROUPME_BOT_ID isn't set, so not posting. Message would have been:\n%s", message)
        return
    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in split_message(message):
            response = await client.post(
                "https://api.groupme.com/v3/bots/post", json={"bot_id": BOT_ID, "text": chunk}
            )
            if response.status_code >= 400:
                log.error("GroupMe rejected the post (HTTP %s): %s", response.status_code, response.text)
                return
    log.info("Posted schedule to GroupMe:\n%s", message)


async def process_and_post(always_post):
    """Read waiting screenshots, save their reservations, and post the schedule.

    The timer passes always_post=False so a batch with no reservations stays quiet.
    !rooms passes always_post=True.
    """
    async with processing_lock:
        urls = pending_image_urls.copy()
        pending_image_urls.clear()
        now = now_in_nc()
        reservations = [r for r in load_saved() if r.ends_at() > now]
        found = 0

        if urls:
            new_reservations, problems = parse_screenshots(await read_screenshots(urls))
            for problem in problems:
                log.warning("Parser problem: %s", problem)
            found = len(new_reservations)
            log.info("Found %d reservations in %d screenshots", found, len(urls))
            reservations = [r for r in merge_reservations(reservations + new_reservations) if r.ends_at() > now]

        save(reservations)

        if not always_post and found == 0:
            log.info("No reservations found in those screenshots, so not posting")
            return

        await post_to_groupme(format_schedule(reservations, now) or "No upcoming room reservations.")


async def wait_then_process():
    global timer_task
    await asyncio.sleep(WAIT_SECONDS)
    timer_task = None  # past the wait, so a new screenshot can't cancel us mid-processing
    await process_and_post(always_post=False)


def run_in_background(coroutine):
    task = asyncio.create_task(coroutine)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task


def cancel_timer():
    global timer_task
    if timer_task:
        timer_task.cancel()
        timer_task = None


@app.get("/")
def health():
    try:
        tesseract = str(pytesseract.get_tesseract_version())
    except pytesseract.TesseractNotFoundError:
        tesseract = "not installed"
    return {"status": "ok", "tesseract": tesseract}


@app.post("/groupme")
async def groupme_webhook(request: Request):
    global timer_task
    try:
        message = json.loads(await request.body())
    except json.JSONDecodeError:
        log.warning("Webhook body was not valid JSON")
        return {"ok": True}

    if message.get("sender_type") != "user" or message.get("system"):
        log.info("Ignoring %s message from %s", message.get("sender_type"), message.get("name"))
        return {"ok": True}

    if str(message.get("sender_id")) not in ALLOWED_SENDERS:
        log.info("Ignoring message from %s (sender_id %s)", message.get("name"), message.get("sender_id"))
        return {"ok": True}

    image_urls = [a["url"] for a in message.get("attachments", []) if a.get("type") == "image" and a.get("url")]
    is_rooms_command = (message.get("text") or "").strip().lower() == "!rooms"
    log.info(
        "Message from %s: %d image(s)%s", message.get("name"), len(image_urls), ", !rooms" if is_rooms_command else ""
    )

    if image_urls:
        pending_image_urls.extend(image_urls)
        cancel_timer()
        if not is_rooms_command:
            timer_task = run_in_background(wait_then_process())
            log.info("%d screenshot(s) waiting, posting in %d seconds", len(pending_image_urls), WAIT_SECONDS)

    if is_rooms_command:
        cancel_timer()
        run_in_background(process_and_post(always_post=True))

    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
