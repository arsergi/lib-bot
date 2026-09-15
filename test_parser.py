"""Run with: python test_parser.py"""

from datetime import datetime

from parser import format_schedule, parse_screenshots

# Exact Tesseract output from debug/sample-1.jpeg (a real screenshot).
REAL_OCR_TEXT = """e

1:58 a

+2 rooms.lib.ncsu.edu rab)

Reserve a Room

ROOM SCHEDULE MY RESERVATIONS

Current Reservations

Study Room 4411,

12 James B. Hunt Jr. Library
Saturday, Sep 12, 2026
5:00 PM - 7:00 PM
Delete

Study
Study Room 4411,

12 James B. Hunt Jr. Library
Saturday, Sep 12, 2026
7:00 PM - 9:00 PM
Delete

Contact
D. H. Hill Jr. Library

2 Broughton Drive
Campus Box 7111
"""

HUNT = "James B. Hunt Jr. Library"
HILL = "D. H. Hill Jr. Library"
LONG_AGO = datetime(2026, 1, 1)


def block(room, library, times, day="Sunday, Sep 13, 2026"):
    """Fake one reservation the way it appears in OCR text."""
    return f"Study\nStudy Room {room},\n13 {library}\n{day}\n{times}\nDelete\n\n"


def schedule(texts, now=LONG_AGO):
    reservations, problems = parse_screenshots(texts)
    return format_schedule(reservations, now), problems


def test_real_screenshot():
    message, problems = schedule([REAL_OCR_TEXT])
    assert message == "Saturday, Sep 12\n📚 Hunt Library:\n - 5pm-9pm: Room 4411", message
    assert problems == [], problems


def test_example_schedule_across_screenshots():
    screenshot_1 = (
        block(9411, HILL, "6:00 PM - 12:00 AM")
        + block(3208, HUNT, "12:00 PM - 2:00 PM")
        + block(4411, HUNT, "8:00 PM - 12:00 AM")
    )
    screenshot_2 = (
        block(4411, HUNT, "8:00 PM - 12:00 AM")  # duplicate from overlapping screenshots
        + block(3208, HUNT, "2:00 PM - 4:00 PM")
        + block(9411, HILL, "12:00 PM - 2:00 PM")
    )
    screenshot_3 = block(4324, HILL, "2:00 PM - 6:00 PM") + block(4411, HUNT, "4:00 PM - 8:00 PM")

    message, problems = schedule([screenshot_1, screenshot_2, screenshot_3])
    expected = (
        "Sunday, Sep 13\n"
        "📚 Hunt Library:\n"
        " - 12pm-4pm: Room 3208\n"
        " - 4pm-12am: Room 4411\n"
        "🐺 Hill Library:\n"
        " - 12pm-2pm: Room 9411\n"
        " - 2pm-6pm: Room 4324\n"
        " - 6pm-12am: Room 9411"
    )
    assert message == expected, message
    assert problems == [], problems


def test_cut_off_reservation_is_reported():
    text = block(4411, HUNT, "5:00 PM - 7:00 PM") + "Study\nStudy Room 3208,\n13 James B. Hunt"
    message, problems = schedule([text])
    assert message == "Sunday, Sep 13\n📚 Hunt Library:\n - 5pm-7pm: Room 4411", message
    assert problems == ["Reservation for room 3208 was cut off"], problems


def test_half_hour_times_and_multiple_days():
    text = block(4411, HUNT, "5:30 PM - 7:00 PM", day="Saturday, Sep 12, 2026") + block(
        3208, HILL, "10:00 AM - 11:30 AM", day="Sunday, Sep 13, 2026"
    )
    message, _ = schedule([text])
    expected = "Saturday, Sep 12\n📚 Hunt Library:\n - 5:30pm-7pm: Room 4411\n\nSunday, Sep 13\n🐺 Hill Library:\n - 10am-11:30am: Room 3208"
    assert message == expected, message


def test_ended_bookings_are_hidden():
    text = (
        block(3208, HUNT, "10:00 AM - 12:00 PM", day="Saturday, Sep 12, 2026")  # ended
        + block(4411, HUNT, "5:00 PM - 7:00 PM", day="Saturday, Sep 12, 2026")  # merges into 5pm-9pm
        + block(4411, HUNT, "7:00 PM - 9:00 PM", day="Saturday, Sep 12, 2026")
        + block(9411, HILL, "12:00 PM - 2:00 PM", day="Sunday, Sep 13, 2026")  # tomorrow
    )
    message, _ = schedule([text], now=datetime(2026, 9, 12, 18, 0))  # Saturday 6pm
    expected = "Saturday, Sep 12\n📚 Hunt Library:\n - 5pm-9pm: Room 4411\n\nSunday, Sep 13\n🐺 Hill Library:\n - 12pm-2pm: Room 9411"
    assert message == expected, message


def test_booking_ending_exactly_now_is_hidden():
    text = block(4411, HUNT, "5:00 PM - 7:00 PM", day="Saturday, Sep 12, 2026")
    message, _ = schedule([text], now=datetime(2026, 9, 12, 19, 0))
    assert message == "", message


def test_booking_ending_at_midnight_still_shows_late_at_night():
    text = block(4411, HUNT, "8:00 PM - 12:00 AM", day="Saturday, Sep 12, 2026")
    message, _ = schedule([text], now=datetime(2026, 9, 12, 23, 30))
    assert message == "Saturday, Sep 12\n📚 Hunt Library:\n - 8pm-12am: Room 4411", message


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"passed: {name}")
