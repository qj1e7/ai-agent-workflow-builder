"""Verbs that drop a day but are on no list of such verbs, each with the day it drops. A schedule
reader that knows none of them must ask the day, never fill it."""

UNKNOWN_LEADS = [
    ("nix", "Monday"),
    ("axe", "Friday"),
    ("kill", "Monday"),
    ("scratch", "Monday"),
    ("strike", "Friday"),
    ("bin", "Monday"),
    ("nuke", "Friday"),
    ("shelve", "Monday"),
    ("halt", "Friday"),
    ("ignore", "Monday"),
    ("suspend", "Friday"),
]
DAYS_LED_BY_AN_UNKNOWN_WORD = [
    form for verb, day in UNKNOWN_LEADS for form in (f"{verb} every {day}", f"{verb} {day}s")
]
