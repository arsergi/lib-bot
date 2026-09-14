"""Run with: python test_parser.py"""

from parser import build_schedule

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


def block(room, library, times, day="Sunday, Sep 13, 2026"):
    """Fake one reservation the way it appears in OCR text."""
    return f"Study\nStudy Room {room},\n13 {library}\n{day}\n{times}\nDelete\n\n"


def test_real_screenshot():
    message, problems = build_schedule([REAL_OCR_TEXT])
    assert message == "Hunt Library:\n - 5pm-9pm: Room 4411", message
    assert problems == [], problems


def test_example_schedule_across_screenshots():
    hunt = "James B. Hunt Jr. Library"
    hill = "D. H. Hill Jr. Library"
    screenshot_1 = (
        block(9411, hill, "6:00 PM - 12:00 AM")
        + block(3208, hunt, "12:00 PM - 2:00 PM")
        + block(4411, hunt, "8:00 PM - 12:00 AM")
    )
    screenshot_2 = (
        block(4411, hunt, "8:00 PM - 12:00 AM")  # duplicate from overlapping screenshots
        + block(3208, hunt, "2:00 PM - 4:00 PM")
        + block(9411, hill, "12:00 PM - 2:00 PM")
    )
    screenshot_3 = block(4324, hill, "2:00 PM - 6:00 PM") + block(4411, hunt, "4:00 PM - 8:00 PM")

    message, problems = build_schedule([screenshot_1, screenshot_2, screenshot_3])
    expected = (
        "Hunt Library:\n"
        " - 12pm-4pm: Room 3208\n"
        " - 4pm-12am: Room 4411\n"
        "Hill Library:\n"
        " - 12pm-2pm: Room 9411\n"
        " - 2pm-6pm: Room 4324\n"
        " - 6pm-12am: Room 9411"
    )
    assert message == expected, message
    assert problems == [], problems


def test_cut_off_reservation_is_reported():
    text = block(4411, "James B. Hunt Jr. Library", "5:00 PM - 7:00 PM") + "Study\nStudy Room 3208,\n13 James B. Hunt"
    message, problems = build_schedule([text])
    assert message == "Hunt Library:\n - 5pm-7pm: Room 4411", message
    assert problems == ["Reservation for room 3208 was cut off"], problems


def test_half_hour_times_and_multiple_days():
    text = block(4411, "James B. Hunt Jr. Library", "5:30 PM - 7:00 PM", day="Saturday, Sep 12, 2026") + block(
        3208, "D. H. Hill Jr. Library", "10:00 AM - 11:30 AM", day="Sunday, Sep 13, 2026"
    )
    message, _ = build_schedule([text])
    expected = "Saturday, Sep 12\nHunt Library:\n - 5:30pm-7pm: Room 4411\n\nSunday, Sep 13\nHill Library:\n - 10am-11:30am: Room 3208"
    assert message == expected, message


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"passed: {name}")
