"""Turn OCR text from NCSU "Reserve a Room" screenshots into a clean schedule."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# Short names, in the order they appear in the schedule.
LIBRARIES = {"hunt": "Hunt Library", "hill": "Hill Library"}
LIBRARY_ORDER = list(LIBRARIES.values())
LIBRARY_EMOJI = {"Hunt Library": "📚", "Hill Library": "🐺"}

# Each pattern searches anywhere in a line, because OCR sometimes glues
# extra text on (e.g. the "12" from the calendar box: "12 James B. Hunt Jr. Library").
ROOM_RE = re.compile(r"\bRoom\s+(\d{3,5})", re.IGNORECASE)
LIBRARY_RE = re.compile(r"\b(Hunt|Hill)\b.*\bLibrary\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b[A-Za-z]{3,9},?\s+([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),?\s+(\d{4})")
TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*([AP])\.?M\.?\s*[-–—~]+\s*(\d{1,2}):(\d{2})\s*([AP])\.?M",
    re.IGNORECASE,
)

MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class Reservation:
    library: str
    room: str
    day: date
    start: int  # minutes after midnight
    end: int  # minutes after midnight; past 1440 if it ends at/after midnight

    def ends_at(self):
        return datetime.combine(self.day, time()) + timedelta(minutes=self.end)


def to_minutes(hour, minute, am_pm):
    return int(hour) % 12 * 60 + int(minute) + (12 * 60 if am_pm.upper() == "P" else 0)


def parse_reservations(text):
    """Read one screenshot's OCR text. Returns (reservations, problems).

    A reservation starts at a "Room ####" line and is finished by the time line
    after it. Anything outside that (status bar, page footer) is ignored.
    """
    reservations = []
    problems = []
    current = None

    for line in text.splitlines():
        if room := ROOM_RE.search(line):
            if current:
                problems.append(f"Reservation for room {current['room']} was missing some details")
            current = {"room": room.group(1)}

        if current is None:
            continue

        if library := LIBRARY_RE.search(line):
            current.setdefault("library", LIBRARIES[library.group(1).lower()])

        if found_date := DATE_RE.search(line):
            month, day_num, year = found_date.groups()
            try:
                current.setdefault(
                    "day", datetime.strptime(f"{month.title()} {day_num} {year}", "%b %d %Y").date()
                )
            except ValueError:
                problems.append(f"Couldn't understand the date: {line.strip()!r}")

        if times := TIME_RE.search(line):
            h1, m1, ap1, h2, m2, ap2 = times.groups()
            start = to_minutes(h1, m1, ap1)
            end = to_minutes(h2, m2, ap2)
            if end <= start:
                end += MINUTES_PER_DAY
            if "library" in current and "day" in current:
                reservations.append(Reservation(current["library"], current["room"], current["day"], start, end))
            else:
                problems.append(f"Reservation for room {current['room']} was missing some details")
            current = None

    if current:
        problems.append(f"Reservation for room {current['room']} was cut off")

    return reservations, problems


def merge_reservations(reservations):
    """Remove duplicates and join back-to-back bookings of the same room."""
    merged = []
    for r in sorted(set(reservations), key=lambda r: (r.library, r.room, r.day, r.start)):
        last = merged[-1] if merged else None
        if last and (last.library, last.room, last.day) == (r.library, r.room, r.day) and r.start <= last.end:
            merged[-1] = Reservation(r.library, r.room, r.day, last.start, max(last.end, r.end))
        else:
            merged.append(r)
    return merged


def format_time(minutes):
    hour, minute = divmod(minutes % MINUTES_PER_DAY, 60)
    suffix = "am" if hour < 12 else "pm"
    hour = hour % 12 or 12
    return f"{hour}:{minute:02d}{suffix}" if minute else f"{hour}{suffix}"


def format_schedule(reservations, now):
    """Build the GroupMe message, leaving out bookings that ended before `now`.

    `now` is a plain datetime in North Carolina time (no timezone attached).
    Returns "" if there's nothing left to show.
    """
    reservations = [r for r in reservations if r.ends_at() > now]
    sections = []
    for day in sorted({r.day for r in reservations}):
        lines = [f"{day:%A, %b} {day.day}"]
        for library in LIBRARY_ORDER:
            bookings = sorted((r for r in reservations if r.day == day and r.library == library), key=lambda r: r.start)
            if not bookings:
                continue
            lines.append(f"{LIBRARY_EMOJI[library]} {library}:")
            for r in bookings:
                lines.append(f" - {format_time(r.start)}-{format_time(r.end)}: Room {r.room}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def parse_screenshots(screenshot_texts):
    """Combine every screenshot's text into one merged list. Returns (reservations, problems)."""
    all_reservations = []
    all_problems = []
    for text in screenshot_texts:
        reservations, problems = parse_reservations(text)
        all_reservations.extend(reservations)
        all_problems.extend(problems)
    return merge_reservations(all_reservations), all_problems
