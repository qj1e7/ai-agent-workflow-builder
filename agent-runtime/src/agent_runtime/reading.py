"""What the model fills in when it reads a request typed on Home, and what code makes of it.

The model fills closed structures: the ticket search the platform will run, the ticket it will
create, the Jira project the result goes in, the schedule, and whose yes the request asks to
skip. Code renders every row a person sees from those structures, so a card claims only what
code will run, never the model's paraphrase. Code then checks every content word of the request
against the words those structures explain: whatever is left is quoted back as a part the
platform can't do, in the person's own words, never dropped. A filter the model fills with a
value the request never gave is dropped, and the request's words for it come back the same way.
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.abilities import (
    ABILITIES,
    NOT_ADVERBS,
    RELEASE_ROOTS,
    SYSTEMS,
    TICKETS,
    change_verbs_in,
    commands_a_change,
    phrase_in,
    starts_with_a_verb,
    words,
)
from agent_runtime.contract import RowKind, UnderstoodRow
from agent_runtime.planner import (
    NOTE_LIMIT,
    TEXT_LIMIT,
    missing_row,
    plain,
    said_in,
    visible_words,
)

type StatusRead = Literal["open", "done"]
type DayHow = Literal["within", "before", "since_last_run"]
type Detail = Literal["owner", "type", "status", "created", "updated", "done"]
type Says = Literal["list", "count", "summary"]
type SkipWhose = Literal["nobody", "only_me", "an_approver_or_anyone_else"]
type ClashReason = Literal["one_day", "one_time", "one_frequency"]
type AsksAbout = Literal["none", "my_workflows", "why_stopped", "needs_me", "abilities", "change"]

FILLED_IN: Final = "I filled this in. Your words didn't say it, so please check it."
FILLED_IN_FROM: Final = 'I filled some of this in from your words "{}". Please check it.'
READ_FROM: Final = 'Read from your words "{}".'
NO_TIME_SAID: Final = "Your words didn't say a time. Please choose one."
NO_TIME_BUT: Final = 'Your words said "{}" but not a time. Please choose one.'
NO_TIME_READ: Final = "I couldn't read the time in your words. Please choose one."
NOT_A_RUN_TIME: Final = 'Your words said "{}", which is not a time it runs at. Please choose one.'
NOT_EXACT: Final = 'Your words said "{}", which is not an exact time. Please choose one.'
NOT_HELD: Final = (
    'Your words said "{}". I can run it every day, every weekday or on one day a week, so please '
    "choose one."
)
NO_DAYS: Final = 'Your words said "{}" but not how many days. Please say how many.'
ONE_DAY: Final = "Your words said {}. I can only set one day, so please choose one."
ONE_TIME: Final = "Your words said {}. I can only set one time, so please choose one."
ONE_FREQUENCY: Final = "Your words said {}. Please choose how often it runs."
SAID_LIMIT: Final = 200
NO_ASSIGNEE: Final = "with no assignee"


class DaysRead(BaseModel):
    """A filter on when a ticket was created, updated or done, as the search runs it: within
    the last N days, more than N days ago, or since the last run."""

    model_config = ConfigDict(extra="ignore")

    how: DayHow = Field(
        description="within for the last N days, before for more than N days ago, as in no "
        "update for N days, or since_last_run for tickets new since the task last ran."
    )
    days: int | None = Field(
        default=None,
        ge=0,
        le=3660,
        description="The number of days the request gives. 0 for today. Null for "
        "since_last_run, or when the request gives no number: then say the words in said and "
        "the platform asks.",
    )


class SearchRead(BaseModel):
    """The ticket search the agents will run. Only the filters jira.search takes, and the
    details the agents read off each ticket it returns."""

    model_config = ConfigDict(extra="ignore")

    project: str | None = Field(
        default=None, description="The Jira project key the request names, such as MOCK."
    )
    issue_types: list[str] = Field(
        default_factory=list[str],
        description="The kinds of ticket the request names: bug, task, story, epic, sub-task, "
        "incident, improvement or defect. Empty for any kind.",
    )
    status: StatusRead | None = Field(
        default=None,
        description="open for open, to do, unresolved or not done; done for done, closed, "
        "resolved or finished. Null for any status. No other status can be searched for.",
    )
    assignee: str | None = Field(
        default=None,
        description="Who the tickets are assigned to: a name as the request writes it, me "
        "for the staff member's own, or nobody for unassigned. Null for anyone.",
    )
    created: DaysRead | None = Field(default=None, description="When the tickets were created.")
    updated: DaysRead | None = Field(
        default=None, description="When the tickets were last updated."
    )
    done: DaysRead | None = Field(default=None, description="When the tickets were done.")
    words: str | None = Field(
        default=None,
        description="Words to look for in a ticket's title or body, only when the request "
        'names a topic or area, such as login for "the login area". Never a priority, '
        "status, resolution or any other field.",
    )
    said: str = Field(
        default="",
        description="The request's words this search covers, copied exactly.",
    )


class TicketRead(BaseModel):
    """What happens with what was found: the agents list, count or sum up the tickets, and
    put the result in one new Jira ticket after an Approver says yes."""

    model_config = ConfigDict(extra="ignore")

    creates: bool = Field(
        description="True when the result goes in one new Jira ticket. False when the request "
        "only asks to see the result."
    )
    says: Says = Field(
        description="What the result is: a list of the tickets found, their count, or a "
        "summary of them."
    )
    shows: list[Detail] = Field(
        default_factory=list[Detail],
        description="The details of each ticket the result includes, when the request asks "
        "for them: owner, type, status, created, updated, done.",
    )
    said: str = Field(default="", description="The request's words this covers, copied exactly.")


class PlaceRead(BaseModel):
    """The Jira project the new ticket goes in."""

    model_config = ConfigDict(extra="ignore")

    project: str | None = Field(
        default=None, description="The Jira project key the request names for it, such as MOCK."
    )
    said: str = Field(default="", description="The request's words this covers, copied exactly.")


class SkipRead(BaseModel):
    """The model's answer to one question about the whole request: whose yes or attention does
    it ask to skip? Code refuses a skip of an Approver's yes or of anyone else's. The staff
    member's own attention is theirs to skip, because the Operator is never the Approver, and
    code accepts that only when the quoted words name the staff member and nobody else."""

    model_config = ConfigDict(extra="ignore")

    whose: SkipWhose = Field(
        description="nobody when the request skips no one's yes or attention, including a "
        "request that only reads or reports on approvals. only_me when it asks only that the "
        "staff member themselves is not asked, told or kept in the loop. "
        "an_approver_or_anyone_else when it asks for a change to go ahead without an Approver's "
        "yes, to bypass, pre-approve or self-approve it, or to leave any other person or any "
        "person at all out."
    )
    said: str | None = Field(
        default=None,
        description="The request's words that ask so, copied exactly. Null when whose is nobody.",
    )


class TaskRead(BaseModel):
    """What the model fills in when it reads a request typed on Home. The model reads; code
    decides from what it read, and shows the person only what code will run."""

    model_config = ConfigDict(extra="ignore")

    skips_the_yes: SkipRead = Field(
        description="Whether the request asks to skip, bypass, pre-approve or self-approve the "
        "Approver's yes, with the request's words that say so."
    )
    asks_about: AsksAbout = Field(
        default="none",
        description="What the request is: a task or software to set up (none), a question "
        "about the person's workflows, what you can do, or a change to a workflow they already "
        "have.",
    )
    workflow_words: str | None = Field(
        default=None,
        description="For my_workflows, why_stopped and change: the words of the request that "
        "name one workflow, copied exactly. Null when it asks about all of them, or names none.",
    )
    belongs_on_watchlist: bool = Field(
        default=False,
        description="True when the request is about software versions, releases, upgrades or "
        "patches, and asks for no known vulnerabilities.",
    )
    watchlist_word: str | None = Field(
        default=None, description="The word from the request that made you think so."
    )
    software: str | None = Field(
        default=None, description="The software the request names, as it writes it."
    )
    name: str | None = Field(
        default=None, description="For a task: 2 to 5 plain words that say what it does."
    )
    schedule: str | None = Field(
        default=None,
        description="When the task runs, in the request's own words, such as \"Every weekday "
        'at 3pm". Null when the request does not say. Never add a day or a time.',
    )
    search: SearchRead | None = Field(
        default=None, description="The ticket search the task runs. Null when it searches none."
    )
    ticket: TicketRead | None = Field(
        default=None,
        description="What happens with what was found. Null when the request does not say.",
    )
    place: PlaceRead | None = Field(
        default=None, description="Where the new ticket goes. Null when the request does not say."
    )


# The words each structure explains. Every list here can only make the platform claim less:
# a word missing from one comes back to the person as a part the platform can't do, never as a
# claim. A word in one explains a request word only when that structure is filled, and only
# inside that structure's own stretch of the request (`leftovers`).
FILLER: Final = words(
    "a an the this that these those each every all any some we us our ours you your yours it "
    "its it's they them their theirs there here one ones who whom whose which what where when "
    "how why in on at to of for with from into onto over about as per via through after before "
    "since until during between among against and or nor but so then than if whether while "
    "once yet also just only please too very rather really even ever already always again now "
    "right soon quickly simply up down out off back away is are was were be been being am do "
    "does did has have had having can could will would shall should may might must need needs "
    "needed want wants wanted like get gets got getting go goes going gone let keep keeps "
    "something anything everything thanks thank hi hello hey etc able sure make makes making "
    "help t s d m ll ve re"
)
"""Words that name no part of a task on their own. "make" is here for "make sure"; a ticket
made is "create" or "make" in the ticket's own words, which the ticket vocabulary explains.
"I", "me" and "my", "by", "under" and "still" are not here: each can carry a filter ("opened by
me", "still under review"), so a structure must explain it where it stands, or it comes back."""
SCHEDULE_WORDS: Final = words(
    "monday tuesday wednesday thursday friday saturday sunday mondays tuesdays wednesdays "
    "thursdays fridays saturdays sundays mon tue tues wed thu thur thurs fri sat sun weekday "
    "weekdays weekend weekends daily weekly "
    "monthly hourly quarterly yearly annually fortnightly biweekly day days week weeks month "
    "months hour hours quarter quarters year years fortnight morning afternoon evening night "
    "noon midday midnight"
)
SCHEDULE_VOCAB: Final = SCHEDULE_WORDS | words(
    "every each on at in the and or to from by before after first last other twice once per a an "
    "am pm o'clock start end of beginning eod"
)
TWELVE_HOUR: Final = r"\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)"
"""A 12-hour time, "9am", "9:30am" or "9.30am", whole, so its hour is never left out."""
TWENTY_FOUR_HOUR: Final = r"(?:[01]?\d|2[0-3]):[0-5]\d"
"""A 24-hour time from 0:00 to 23:59, as "16:00". "16.00" is not one: with a dot, "9.30" could
be morning or evening, so it is asked."""
NOT_INSIDE_A_NUMBER: Final = r"(?<![\d.:])\b"
TIME_OF_DAY: Final = re.compile(
    rf"{NOT_INSIDE_A_NUMBER}(?:at\s+)?{TWELVE_HOUR}\b|"
    rf"{NOT_INSIDE_A_NUMBER}(?:at\s+)?{TWENTY_FOUR_HOUR}\b|\bat\s+\d{{1,2}}\b|"
    r"\bat\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b|"
    r"\b(?:noon|midday|midnight|morning|afternoon|evening|night)\b",
    re.IGNORECASE,
)
FREQUENCY: Final = re.compile(
    r"\b(?:every|each)\s+(day|weekday|week|fortnight|month|quarter|year|hour)\b|"
    r"\b(daily|weekdays|weekly|fortnightly|biweekly|monthly|quarterly|yearly|annually|hourly)\b",
    re.IGNORECASE,
)
"""How often a schedule runs, as "every week" or "weekly"."""
OFTEN: Final = {
    "daily": "day",
    "weekdays": "weekday",
    "weekly": "week",
    "fortnightly": "fortnight",
    "biweekly": "fortnight",
    "monthly": "month",
    "quarterly": "quarter",
    "yearly": "year",
    "annually": "year",
    "hourly": "hour",
}
"""Each frequency word as the one it means, so "daily" and "every day" are the same."""
DAY_NAMES: Final = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
DAY_FORMS: Final = rf"{DAY_NAMES}|(?-i:[Mm]on|[Tt]ues?|[Ww]ed|[Tt]hu(?:rs?)?|[Ff]ri|Sat|Sun)"
"""A day of the week, whole or short, as "Monday", "Mon" or "Thurs". A short day is read only
with a capital first letter or in small letters, never in capitals, since "MON" or "WED" is a
project key. "sat" and "sun" in small letters are words of their own, so only "Sat" and "Sun"
are days."""
SHORT_FORMS: Final = words("mon mons tue tues wed thu thur thurs fri fris sat sats sun suns")
DAY: Final = re.compile(rf"\b({DAY_FORMS})s?\b", re.IGNORECASE)
SHORT_DAYS: Final = {
    "mon": "monday",
    "tue": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
}


def day_key(word: str) -> str:
    """A day of the week as code reads it, whole and in small letters, as "thursday" for "Thu"."""
    return SHORT_DAYS[word[:3].casefold()]


def _day_said(word: str) -> str:
    """A day as the card says it: the person's own word, or the whole day for a short one."""
    return word if word.casefold() in DAY_NAMES.split("|") else day_key(word).capitalize()


SCHEDULE_PHRASE: Final = re.compile(
    rf"\b(?:on\s+)?(?:the\s+)?(?:first|second|third|fourth|fifth|last|\d{{1,2}}(?:st|nd|rd|th))\s+"
    rf"(?:(?:working\s+day|(?:{DAY_NAMES})s?)\b(?:\s+of\s+(?:the|each|every)\s+month\b)?|"
    r"(?:day\s+)?of\s+(?:the|each|every)\s+month\b)|"
    rf"\b(?:every|each)\s+(?:few|couple\s+of|several|other|second|third|fourth|\d+|two|three|four|"
    rf"five|six)\s+(?:minutes?|mins?|hours?|days?|weeks?|months?|(?:{DAY_NAMES})s?)\b|"
    rf"\b(?:on\s+)?alternat(?:e|ing)\s+(?:days?|weeks?|(?:{DAY_NAMES})s?)\b|"
    r"\bbi-weekly\b|\b(?:every|each)\s+working\s+days?\b|"
    r"\bonce\s+(?:a|an|per|every)\s+\w+|"
    r"\b(?:twice|thrice|(?:two|three|four|five|six|\d+)\s+times)\s+(?:a|an|per|each|every)\s+\w+|"
    r"\b(?:on\s+)?(?:the\s+)?weekends?\b|"
    r"\b(?:except|excluding|but\s+not|apart\s+from|other\s+than)\s+(?=(?:on\s+)?(?:the\s+)?"
    rf"(?:(?:{DAY_FORMS})s?|weekdays?|weekends?|(?:public\s+|bank\s+)?holidays?)\b(?!['\u2019]))"
    r"[^,.;!?]*|"
    r"\b(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)\s*(?:-|to|through|thru|till|until)\s*"
    r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)\b",
    re.IGNORECASE,
)
"""Words that belong to a schedule's phrase though the schedule words don't name them, as
"every 30 minutes", "alternate Fridays", "once a month", "the 3rd Friday" or "every weekday
except Friday", so the whole phrase is read, and judged against what a schedule holds."""
RELATIVE_TIME: Final = re.compile(
    r"\b(?:(?:an?|one|two|three|\d+)\s+hours?\s+)?(?:later|earlier|sooner)\b", re.IGNORECASE
)
"""A time moved from the one set, as "an hour later", which is the time's own question."""
APPROXIMATE: Final = re.compile(
    r"(?:\b\d{1,2}(?:[:.]\d{2})?(?:\s*(?:am|pm))?)?-ish\b|\b(?:or\s+so|roughly|approximately|approx)\b",
    re.IGNORECASE,
)
"""A time made approximate, as "9am or so", "16:00-ish" or "roughly", so it is asked exactly."""
_VAGUE: Final = (
    r"(?:first\s+thing|eod|cob|close\s+of\s+business|(?:the\s+)?(?:end|start|beginning)\s+of\s+"
    r"(?:the\s+)?(?:business\s+|working\s+|work\s+)?day)"
)
VAGUE_TIME: Final = re.compile(rf"\b{_VAGUE}\b", re.IGNORECASE)
"""A part of the day named in words, as "first thing" or "the end of the day", which is asked as
a time unless a clock time stands beside it."""
DAY_RANGE: Final = re.compile(
    rf"\b(?:{DAY_FORMS})s?\s*(?:to|through|thru|till|until|-|\u2013|\u2014)\s*(?:{DAY_FORMS})s?\b",
    re.IGNORECASE,
)
"""Days from one to another, whole or short, with any dash, as "Monday to Friday", "Mon-Fri" or
"Tue–Thu". Only Monday to Friday is a schedule it holds: every weekday."""


def _monday_to_friday(days: str) -> bool:
    ends = [day_key(m.group(1)) for m in DAY.finditer(days)]
    return len(ends) == 2 and ends == ["monday", "friday"]


EVERY_DAY: Final = re.compile(r"\b(?:every|each)\s+day\b|\bdaily\b", re.IGNORECASE)
NOT_WEEKENDS: Final = re.compile(
    r"\b(?:except|excluding|but\s+not|apart\s+from|other\s+than)\s+(?:on\s+)?(?:the\s+)?"
    r"(?:weekends?|saturdays?\s+(?:and|&)\s+sundays?)\b(?!\s*(?:and|or|&)\b)",
    re.IGNORECASE,
)
"""The weekend left out, whole, as "except weekends" or "except Saturdays and Sundays". Beside
every day, and when it is the only thing left out, it is every weekday."""
_DAYISH: Final = (
    rf"(?:(?:{DAY_FORMS})s?|weekdays?|weekends?|(?:public\s+|bank\s+)?holidays?)\b(?!['\u2019])"
)
LEFT_OUT: Final = re.compile(
    r"\b(?:except|excluding|exclude|but\s+not|apart\s+from|other\s+than|besides|skip(?:s|ping)?|"
    r"without|never|not|no\s+longer|no|don['\u2019]?t|do\s+not|does\s+not|doesn['\u2019]?t|"
    r"stop(?:s|ping)?|pause)"
    r"(?:\s+(?:run(?:s|ning)?|it|this|that|them|on|the|any|more|longer|anymore|for|every|each|"
    r"during|over|in))*"
    rf"\s+{_DAYISH}\b(?:(?:\s*(?:,|and|or|&|nor))+\s*(?:on\s+)?(?:the\s+)?{_DAYISH}\b)*",
    re.IGNORECASE,
)
"""A day, the weekend or holidays the words leave out or say not to run on, with what follows it
in a list, as "skip Fridays", "don't run it on Mondays", "never on Fridays" or "except weekends
and holidays". It reads more than it must: it only ever makes the schedule asked."""


def left_out(words_: str) -> list[tuple[int, int]]:
    """Where the words leave out a day a schedule can't leave out: every day the words leave
    out, and every day the schedule's words name without saying to run on it, as "drop Fridays"
    or "Fridays off", but for the weekend left out beside every day when that is all they leave
    out."""
    off = _not_run_on(words_)
    if _weekend_alias(words_) and not off:
        return []
    return sorted({*_left_out_spans(words_), *off})


@lru_cache(maxsize=64)
def _left_out_spans(words_: str) -> tuple[tuple[int, int], ...]:
    return tuple(m.span() for m in LEFT_OUT.finditer(words_))


@lru_cache(maxsize=64)
def _weekend_alias(words_: str) -> bool:
    """Whether the words say every day with the weekend left out, and leave out nothing else.
    Kept per request, since each phrase of it asks."""
    found = _left_out_spans(words_)
    return (
        EVERY_DAY.search(words_) is not None
        and len(found) == 1
        and NOT_WEEKENDS.fullmatch(words_, *found[0]) is not None
    )


_NOT_A_COUNT: Final = (
    r"(?!\s*(?:days?|weeks?|months?|years?|hours?|hrs?|minutes?|mins?|seconds?|secs?|"
    r"tickets?|issues?|bugs?|items?|people|persons?|approvers?|managers?|members?|users?|"
    r"times|max|percent)\b)"
)
"""Not followed by a unit or a thing counted, so "14" in "14 days" is no hour."""
UNITS: Final = words("day days week weeks month months year years hour hours minute minutes")
"""Units a number counts, as "days" in "14 days", which belong to the count, not the schedule."""
COUNTED: Final = re.compile(_NOT_A_COUNT.replace("(?!", "(?=", 1))
"""A unit or a thing counted, after a number, as " days" in "14 days" or " tickets"."""
COUNT: Final = re.compile(rf"\b\d+{_NOT_A_COUNT.replace('(?!', '(?:', 1)}")
"""A number with what it counts, as "14 days" or "3 tickets"."""
CLOCK: Final = re.compile(
    rf"{NOT_INSIDE_A_NUMBER}(?P<twelve>{TWELVE_HOUR})\b|"
    rf"{NOT_INSIDE_A_NUMBER}(?P<day>{TWENTY_FOUR_HOUR})\b(?![.:]\d)|"
    rf"\b(?:at|or|and)\s+(?P<bare>\d{{1,2}})\b(?![:.]\d)(?!\s*(?:am|pm)\b){_NOT_A_COUNT}|"
    r"\b(?P<named>noon|midday|midnight)\b",
    re.IGNORECASE,
)
"""A time of day as the request writes it: "9am", "9.30am", "17:00", "noon", or a bare hour after
"at", "or" or "and", as in "at 9 or 10", but not a count, as "14" in "10 and 14 days"."""
_CLOCK_END: Final = rf"(?:{TWELVE_HOUR}|{TWENTY_FOUR_HOUR}|noon|midday|midnight)"
_RANGE_END: Final = rf"(?:{_CLOCK_END}|(?:[01]?\d|2[0-4])\b{_NOT_A_COUNT})"
_UNTIL: Final = r"(?:-|\u2013|\u2014|\bto\b|\btill\b|\btil\b|\buntil\b|\bthrough\b|\bthru\b)"
TIME_RANGE: Final = re.compile(
    rf"\bbetween\s+(?P<between>{_RANGE_END})\s*(?:\band\b|{_UNTIL})\s*(?P<upto>{_RANGE_END})\b|"
    rf"\bfrom\s+(?P<from>{_RANGE_END})\s*{_UNTIL}\s*(?P<to>{_RANGE_END})\b|"
    rf"{NOT_INSIDE_A_NUMBER}(?P<start>{_RANGE_END})\s*{_UNTIL}\s*(?P<end>{_RANGE_END})\b",
    re.IGNORECASE,
)
"""Two times joined as a range: "between 16:00 and 17:00", "from 4 to 5pm", "9am-5pm" or "16:00
till 17:00". A bare number is an hour, 0 to 24, never one before a unit or a thing counted, and
counts only after "between" or "from", or beside a clock time, so "10-14 days", "between 10 and
14 days" and "9am - 20 tickets" are no range."""
BOUND_TIME: Final = re.compile(
    r"\b(?:before|by|after|until|till|til|around|about|since|from|no\s+later\s+than|not\s+before|"
    rf"not\s+after)\s+(?:at\s+)?(?:{NOT_INSIDE_A_NUMBER}(?:{_CLOCK_END}|(?:[01]?\d|2[0-4])\b"
    rf"(?![:.]\d){_NOT_A_COUNT})|{_VAGUE}\b(?:\s+at\s+{NOT_INSIDE_A_NUMBER}{_CLOCK_END}\b)?)",
    re.IGNORECASE,
)
"""A time that bounds a run instead of naming it, as "before 5pm", "by 17:00", "after 9am" or "by
the end of the day at 5pm". A run at 5pm is not before 5pm, so it is never the time it runs at,
and the card asks."""


@dataclass(frozen=True)
class TimeRange:
    """A range of times in the words: its two ends as written, where they stand from the first
    end to the last, and where the whole range stands, "between" and all."""

    ends: tuple[str, str]
    start: int
    end: int
    whole: tuple[int, int]


def time_ranges(text: str) -> list[TimeRange]:
    return list(_time_ranges(text))


@lru_cache(maxsize=64)
def _time_ranges(text: str) -> tuple[TimeRange, ...]:
    """Kept per request, since each phrase of it asks."""
    found: list[TimeRange] = []
    for match in TIME_RANGE.finditer(text):
        first = next(g for g in ("between", "from", "start") if match.group(g) is not None)
        last = next(g for g in ("upto", "to", "end") if match.group(g) is not None)
        ends = (match.group(first), match.group(last))
        if first == "start" and not any(re.fullmatch(_CLOCK_END, e, re.I) for e in ends):
            continue
        found.append(TimeRange(ends, match.start(first), match.end(last), match.span()))
    return tuple(found)


CLOCK_TOKEN: Final = re.compile(
    rf"^{TWELVE_HOUR}$|^{TWENTY_FOUR_HOUR}$|^\d{{1,2}}(?:st|nd|rd|th)$", re.IGNORECASE
)
TIME_SHAPED: Final = re.compile(r"\b\d{1,2}[:.]\d{1,2}\b|\bat\s+\d+\b|\bat$", re.IGNORECASE)
"""Words that held a time, read or not, as "24:00", "16.00", "at 1600", or an "at" left at the end
when its time was dropped."""
SEARCH_VOCAB: Final = words(
    "ticket tickets issue issues item items entry entries find finds finding found list lists "
    "listing listed show shows showing get gather gathers gathering collect collects "
    "collecting fetch look looks looking search searches searching pull pulls see view display "
    "identify spot check checks checking pick select filter jira project projects board "
    "backlog queue all any"
)
"""What a ticket search explains on its own. A kind of ticket, such as bugs, is explained only
by the search's issue_types, so a kind the model left out comes back to the person. "review" is
the search's verb only at the front of its clause ("Review the open bugs"); after "under" or
"in" it is a status the search can't filter by, so it is not here."""
REVIEW: Final = words("review reviews")
STILL: Final = words("still")
"""A status filter explains "still" ("still open", "still under review") but is never read
from it: "still" alone does not say open or done."""
PROJECT_KEY: Final = re.compile(r"[A-Z][A-Z0-9]{1,9}")
STATUS_VOCAB: Final[dict[StatusRead, frozenset[str]]] = {
    "open": words(
        "open unresolved outstanding active unfinished incomplete pending todo to-do ongoing "
        "live current unclosed"
    ),
    "done": words("done closed resolved finished completed complete fixed shipped solved"),
}
NEGATIONS: Final = words(
    "not never no none nothing nobody no-one isn't aren't wasn't weren't hasn't haven't un without"
)
"""Words that turn the words after them round. They are not filler: a structure explains one
only when it holds that direction ("with no update for 10 days" as updated before), so a negation
the model read the other way round comes back to the person."""
NOT_UPDATED: Final = words("untouched stale idle dormant quiet")
"""Update words that say no update on their own: a filter on them runs before, never within."""
STALE: Final = NOT_UPDATED - words("quiet")
"""The ones that say it of tickets whatever they stand beside, so a search the model read without
a day filter still asks how many days ("the stale bugs")."""
EXCLUSIONS: Final = words("except excepting excluding exclude excludes unless besides")
"""Words that leave out what follows them. A search can't leave anything out, so like a
negation one is explained only where a structure holds that direction. "other than" and "apart
from" are read as pairs."""
ISSUE_TYPES: Final[dict[str, tuple[str, ...]]] = {
    "Bug": ("bug", "bugs"),
    "Task": ("task", "tasks"),
    "Story": ("story", "stories"),
    "Epic": ("epic", "epics"),
    "Sub-task": ("sub-task", "sub-tasks", "subtask", "subtasks"),
    "Incident": ("incident", "incidents"),
    "Improvement": ("improvement", "improvements"),
    "Defect": ("defect", "defects"),
}
"""Jira's own issue types, the closed set a search can name. A word the request uses for a kind
of ticket that is not one of these, such as Major, is not a type."""
TYPE_BY_FORM: Final = {form: name for name, forms in ISSUE_TYPES.items() for form in forms}
ASSIGNEE_VOCAB: Final = words(
    "assigned assignee assignees assign owned owner owners owns own belonging belongs belong "
    "held holds unassigned nobody no-one none by"
)
ME_WORDS: Final = words("me my mine myself i i'd i'm i'll i've")
NOBODY_WORDS: Final = words("nobody no-one unassigned none")
NAME: Final = re.compile(r"^[A-Z][a-z]+(?: [A-Z][a-z]+)?$")
DAYS_VOCAB: Final = words(
    "since last past within in the days day week weeks month months year years this today "
    "yesterday ago older newer than more over less under fewer no without for from recent "
    "recently latest earlier later back run quarter fortnight hours hour"
)
WHEN_VOCAB: Final[dict[str, frozenset[str]]] = {
    "created": words("created raised filed logged submitted new newly added opened arrived"),
    "updated": words(
        "updated update updates touched changed modified edited activity active stale idle "
        "dormant quiet untouched"
    ),
    "done": STATUS_VOCAB["done"] | words("closing closure"),
}
GOVERNED: Final = (
    frozenset(TYPE_BY_FORM)
    | ASSIGNEE_VOCAB
    | ME_WORDS
    | NOT_UPDATED
    | frozenset(w for v in STATUS_VOCAB.values() for w in v)
    | frozenset(w for v in WHEN_VOCAB.values() for w in v)
)
"""The filter words a negation or an exclusion can turn round."""
TOPIC_VOCAB: Final = words(
    "about mentioning mention mentions titled called named regarding concerning containing "
    "contain contains saying say says related area topic subject feature module page title "
    "summary description body name text word words"
)
TOPIC_LEADS: Final = (
    r"about|mentioning|mentions?|titled|called|named|regarding|concerning|containing|contains?|"
    r"saying|says?|discussing|covering|on\s+the\s+subject\s+of|related\s+to|to\s+do\s+with"
)
TOPIC_PLACES: Final = r"title|summary|description|body|name|text|subject"
CREATE_VOCAB: Final = words(
    "create creates creating make makes making raise raises raising file files filing log logs "
    "logging propose proposes draft drafts write writes submit submits add adds generate "
    "generates put puts one single new another jira that which ticket tickets issue issues "
    "follow-up follow-ups followup followups summary"
)
OPEN_AS_CREATE_AFTER: Final = words("a an one single new another the up")
SAYS_VOCAB: Final[dict[Says, frozenset[str]]] = {
    "list": words(
        "list lists listing listed show shows showing include includes including each all "
        "together them it everything"
    ),
    "count": words("count counts counted counting number numbers many total tally how"),
    "summary": words(
        "sum sums summing up summary summaries summarise summarize summarised summarized recap "
        "digest overview roundup round-up write-up writeup report reports brief rundown breakdown"
    ),
}
SHOWS_VOCAB: Final[dict[Detail, frozenset[str]]] = {
    "owner": words("owner owners owns assignee assignees who whom assigned responsible holder"),
    "type": words("type types kind kinds"),
    "status": words("status statuses state states"),
    "created": words("created date dates age when"),
    "updated": words("updated update touched when"),
    "done": words("completion completed when"),
}
"""The details a ticket can show, each explained only where the ticket's own words stand.
"finished" is not a detail word: "finished by this Friday" is a due date, which no structure
holds, so it must come back."""
PLACE_VOCAB: Final = words("jira project projects board in into to put puts goes go file")
CREATE_PHRASE: Final = re.compile(
    r"\b(?:(?:create|creates|make|makes|raise|raises|file|files|log|logs|open|opens|draft|"
    r"drafts|propose|proposes|submit|submits|add|adds|generate|generates|write|writes|put|"
    r"puts)\s+)?(?:a|an|one|single|new|another)\s+(?:(?:new|single|follow-?up|summary|jira|"
    r"(?-i:[A-Z][A-Z0-9]{1,9}))\s+)*(?:ticket|issue)s?\b",
    re.IGNORECASE,
)
"""The request's own words for the new ticket, such as "create one ticket", "one SVC ticket"
or "in one new ticket": a second place the ticket structure stands in the request, because the
model's quote for the ticket is sometimes only "list them"."""
A_YES: Final = re.compile(
    r"\b(?:approv\w*|sign[- ]?offs?|signs?|signed|signing|countersign\w*|yes|okay|okayed|"
    r"okays|ok|ok'd|go-ahead|permission|consent|confirmation|confirms?|confirmed|"
    r"authori[sz]\w*|reviewed|reviewers?|reviewing|rubber-?stamp\w*|decision|decides?|decided|"
    r"green\s+light|greenlit|greenlight\w*|agreed|agrees|vouch\w*|the\s+nod|blessing|"
    r"pre-?cleared|sanction\w*|endors\w*|ratif\w*|waived?|once-over|"
    r"(?:second|another)\s+pair\s+of\s+eyes)\b",
    re.IGNORECASE,
)
"""Words that name a yes. None is in any vocabulary above, so none is ever explained by a
structure: a request that carries one either quotes it as the staff member's own attention,
which code checks, or sees it come back."""
SOMEONE: Final = re.compile(
    r"\b(?:anyone|anybody|someone|somebody|nobody|no\s+one|no-one|everyone|everybody|humans?|"
    r"persons?|people|whoever|the\s+team|teammates?|colleagues?|stakeholders?|managers?|"
    r"the\s+boss|supervisors?|directors?|leads?|gatekeepers?|committee|"
    r"(?:change|review|approval|advisory|steering)\s+board|cab|he|she|him|her|his|hers)\b",
    re.IGNORECASE,
)
"""Words that name a person, a role or a group who could give a yes. With a "no", "not" or
"without" beside them, or as "nobody", they skip that person. In a request that writes, words
no structure explains that name one are refused whatever stands beside them ("the change board
can catch up on it at their next meeting"); in one that reads they are a visible can't."""
CAPITALISED: Final = r"[A-Z][a-z]+"
NAMED_BEFORE: Final = (
    r"(?:get|getting|got|ask|asking|tell|telling|let|have|having|cc|ping|pinging|notify|"
    r"notifying|bother|bothering|consult|consulting|email|emailing|message|remind|involve|"
    r"involving|wait\s+for|waiting\s+for|wait\s+on|waiting\s+on|check\s+with|checking\s+with|"
    r"run\s+it\s+(?:by|past)|clear\s+it\s+with|hear\s+from|without|unless|"
    r"(?:me|myself|i|{name})\s+(?:or|and|nor))"
)
NAMED_AFTER: Final = (
    r"(?:'s|’s|'ll|’ll|'d|’d|can|could|will|would|shall|should|may|might|must|has|had|have|"
    r"is|was|does|did|said|says|told|tells|mentioned|mentions|gave|gives|okayed|okays|ok'd|"
    r"agreed|agrees|signed|signs|normally|usually|already|also|wants|needs|prefers|likes|"
    r"asked|wanted|knows|isn't|hasn't|doesn't|won't|to|or\s+me|and\s+me)"
)
WHO: Final = rf"(?:(?i:{SOMEONE.pattern[2:-2]})|{CAPITALISED})"
NAMED_ACTOR: Final = re.compile(
    rf"\b(?i:{NAMED_BEFORE.format(name=CAPITALISED)})\s+(?i:the\s+)?(?P<before>{WHO})\b|"
    rf"\b(?P<after>{WHO})(?:\s+{CAPITALISED})?\s*(?i:{NAMED_AFTER})\b"
)
"""A person, a role, a group or a capitalised word framed as someone who acts: asked, waited
for, or the subject of a verb ("get Ravi to", "Joanne normally okays", "the change board
can", "the duty lead doesn't", "Wei Ling's inbox", "me or Bob"). A value such as "flagged
Highest" or "the Checkout component" is never framed so, and stays a can't; nor is a person
the change acts on, as "remove anyone who has left the team", which is a can't for GitLab."""
NOBODY: Final = re.compile(r"\b(?:nobody|no\s+one|no-one)\b", re.IGNORECASE)
FROM_ME: Final = re.compile(
    r"\b(?:approval|approvals|confirmation|permission|sign[- ]?off|okay|ok|yes|go-ahead|consent)\s+"
    r"(?:from|of|by)\s+(?:me|myself)\b",
    re.IGNORECASE,
)
"""A yes the staff member gives, as "confirmation from me": theirs to skip, because the Operator
is never the Approver. The word rule makes the same exception."""
NEGATED: Final = re.compile(
    r"\b(?:no|not|without|neither|nor|never|don't|doesn't|shouldn't|needn't|spare|skip\w*|"
    r"bypass\w*)\b|n't\b",
    re.IGNORECASE,
)
SPEAKS_OF_SELF: Final = re.compile(r"\b(?:i|i'd|i'm|i'll|i've|me|my|mine|myself)\b", re.IGNORECASE)
CLAUSE_END: Final = re.compile(r"[,;:.!?]+(?=\s|$)|[()]")
JOIN: Final = re.compile(
    r"\b(?:and|then|but|also|plus)\b(?=\s+(?P<next>[^\W_][\w'’-]*))", re.IGNORECASE
)
LEADING_JOIN: Final = re.compile(r"(?:(?:and|then|but|also|plus)\s+)+", re.IGNORECASE)
POLITE: Final = words("please pls plz thanks thank you kindly hi hello hey there cheers")
POLITE_PHRASE: Final = re.compile(
    r"\b(?:no\s+problem|no\s+worries|without\s+fail|if\s+possible|thank\s+you)\b", re.IGNORECASE
)
"""Phrases that ask for nothing, so they are never a part to mark."""
LEAD_IN: Final = re.compile(
    r"\b(?:without|no|not|neither|nor|never|don't)(?:\s+(?:a|an|the|any|my|their))?\s*$",
    re.IGNORECASE,
)
TOKEN: Final = re.compile(r"[^\W_][\w'’-]*")


type Said = dict[RowKind, tuple[int, int] | None]


@dataclass(frozen=True)
class Span:
    """A run of the request's words that no structure explains, with the part of a task they
    are: None when they ask for no change and stand beside no part."""

    text: str
    start: int
    end: int
    kind: RowKind | None
    names_a_yes: bool
    names_a_person: bool = False


@dataclass(frozen=True)
class Rendered:
    """A row code wrote from a structure, with the request words that structure explains, and
    the stretches of the request the structure stands in: the model's quote for it as the
    request writes it, and, for the ticket, the request's own words for the new ticket. The
    structure explains its words only there and in the run of its own words around there."""

    row: UnderstoodRow
    explained: frozenset[str]
    said: tuple[int, int] | None
    also: tuple[int, int] | None = None


def _low(token: str) -> str:
    return token.casefold().replace("’", "'").removesuffix("'s").removesuffix("'")


def _request_tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in TOKEN.finditer(text)]


def _find(text: str, phrase: str | None, last: bool = False) -> tuple[int, int] | None:
    """Where the request writes the model's quote, or None when it does not."""
    found = phrase_in(text, phrase or "")
    if found is None:
        return None
    at = (text.casefold().rfind if last else text.casefold().find)(found.casefold())
    return None if at < 0 else (at, at + len(found))


def _locate(text: str, phrase: str | None) -> tuple[int, int] | None:
    """Where the request writes the model's quote: as written, else from the first of its
    content words to the last, each found in order after the one before ("list them, create
    one ticket that lists them" for "list the bugs, create one ticket that lists them"). None
    when the request lacks it."""
    found = _find(text, phrase)
    if found is not None:
        return found
    content = [t for t, _, _ in _request_tokens(phrase or "") if _low(t) not in FILLER]
    if not content:
        return None
    at = 0
    start: int | None = None
    for word in content:
        match = re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text[at:], re.IGNORECASE)
        if match is None:
            return None
        if start is None:
            start = at + match.start()
        at += match.end()
    return None if start is None else (start, at)


def _quote(text: str, said: tuple[int, int] | None) -> str | None:
    return None if said is None else plain(text[said[0] : said[1]], SAID_LIMIT)


def _note(text: str, said: tuple[int, int] | None, sourced: bool) -> str | None:
    quote = _quote(text, said)
    if sourced:
        return None if quote is None else READ_FROM.format(quote)
    return FILLED_IN if quote is None else FILLED_IN_FROM.format(quote)


def _forms_in(text: str, forms: frozenset[str]) -> bool:
    low = {_low(t) for t, _, _ in _request_tokens(text)}
    return bool(low & forms)


def _project_in(text: str, key: str | None) -> str | None:
    """The key as the request writes it, or None: a key the request never said is never shown."""
    if not key:
        return None
    key = key.strip().upper()
    return key if PROJECT_KEY.fullmatch(key) and said_in(key, text) else None


def _days_text(when: str, read: DaysRead) -> str | None:
    """The filter in plain words, or None when it needs a number the model left out."""
    verb = {"created": "created", "updated": "updated", "done": "finished"}[when]
    match read.how:
        case "since_last_run":
            return f"{verb} since the last run"
        case "within":
            if read.days is None:
                return None
            return f"{verb} today" if read.days == 0 else f"{verb} in the last {read.days} days"
        case "before":
            if read.days is None:
                return None
            if when == "updated":
                return f"with no update for {read.days} days"
            return f"{verb} more than {read.days} days ago"


def _assignee(text: str, said: str | None) -> tuple[str, frozenset[str]] | None:
    """The assignee filter as the request frames it, with the words it explains, or None when
    the request frames no such filter: a name alone is not an assignee."""
    if not said:
        return None
    value = said.strip()
    low = _low(value)
    if low in ME_WORDS:
        framed = re.search(
            r"\b(?:my|mine)\b|\b(?:assigned|belonging|belongs?)\s+to\s+me\b|\bowned\s+by\s+me\b|"
            r"\bi\s+own\b",
            text,
            re.IGNORECASE,
        )
        return None if framed is None else ("assigned to you", ASSIGNEE_VOCAB | ME_WORDS)
    if low in NOBODY_WORDS or low in ("no one", "not assigned"):
        framed = re.search(
            r"\bunassigned\b|\b(?:nobody|no\s+one|no-one|no\s+owner|no\s+assignee)\b|"
            r"\bwithout\s+(?:an\s+)?(?:owner|assignee)\b|\bnot\s+assigned\b",
            text,
            re.IGNORECASE,
        )
        return None if framed is None else (NO_ASSIGNEE, ASSIGNEE_VOCAB | NOBODY_WORDS)
    if NAME.fullmatch(value) is None:
        return None
    name = re.escape(value)
    framed = re.search(
        rf"\b(?:assigned|belonging|belongs|belong|given|handed)\s+to\s+{name}\b|"
        rf"\b(?:owned|held)\s+by\s+{name}\b|\b{name}['’]s\b|"
        rf"\b{name}\s+(?:owns|holds|is\s+(?:the\s+)?(?:owner|assignee))\b|"
        rf"\b(?:owner|assignee)\s*(?:is|=|:)\s*{name}\b",
        text,
        re.IGNORECASE,
    )
    if framed is None:
        return None
    return f"assigned to {value}", ASSIGNEE_VOCAB | frozenset(_low(w) for w in value.split())


def _topic(text: str, said: str | None) -> tuple[str, frozenset[str]] | None:
    """The word search as the request frames it, with the words it explains, or None when the
    request does not frame those words as a topic: a value such as P1 is not a topic."""
    if not said:
        return None
    found = phrase_in(text, said)
    if found is None:
        return None
    w = re.escape(found)
    framed = re.search(
        rf"\b(?:{TOPIC_LEADS})\s+(?:the\s+|a\s+|an\s+)?{w}\b|"
        rf"\b{w}\s+(?:area|topic|subject|feature|module|page|screen)\b|"
        rf"\b{w}\s+in\s+(?:the|their|its|a)\s+(?:{TOPIC_PLACES})\b|"
        rf"\bwords?\s+{w}\b",
        text,
        re.IGNORECASE,
    )
    if framed is None:
        return None
    return found, TOPIC_VOCAB | frozenset(_low(t) for t, _, _ in _request_tokens(found))


def _turns(tokens: list[tuple[str, int, int]], at: int) -> str | None:
    """The negation or exclusion that stands at token `at`, as written, or None."""
    low = _low(tokens[at][0])
    after = _low(tokens[at + 1][0]) if at + 1 < len(tokens) else ""
    if low in NEGATIONS or low in EXCLUSIONS or low.endswith("n't"):
        return low
    return low if (low, after) in (("other", "than"), ("apart", "from")) else None


def _governed(text: str) -> list[tuple[str, list[str]]]:
    """Each filter word that a negation or an exclusion turns round, with the words that turn
    it. One governs the first filter word after it in its clause, however far, so "nobody on
    the duty team has updated" turns "updated", and "not assigned to me that are open" turns
    "assigned", never "open"."""
    tokens = _request_tokens(text)
    clause_of = _clause_of(text, tokens)
    found: dict[int, list[str]] = {}
    for at in range(len(tokens)):
        turn = _turns(tokens, at)
        if turn is None:
            continue
        for after in range(at + 1, len(tokens)):
            if clause_of[after] != clause_of[at]:
                break
            if _low(tokens[after][0]) in GOVERNED:
                found.setdefault(after, []).append(turn)
                break
    return [(_low(tokens[at][0]), turns) for at, turns in sorted(found.items())]


def _negations(text: str, forms: frozenset[str]) -> frozenset[str]:
    """The negations and exclusions that turn one of `forms` round. Empty when none does."""
    return frozenset(t for word, turns in _governed(text) if word in forms for t in turns)


def _doubled(text: str, forms: frozenset[str]) -> bool:
    """Whether one of `forms` is turned round twice, as "not gone without an update"."""
    return any(len(turns) > 1 for word, turns in _governed(text) if word in forms)


def says_no_change(text: str) -> bool:
    """Whether the words say a ticket was not created, updated or done, as "nobody has touched
    for 10 days" or "untouched": a day filter that runs before, never within."""
    return _forms_in(text, NOT_UPDATED) or any(_negations(text, v) for v in WHEN_VOCAB.values())


def turns_round(text: str) -> bool:
    """Whether a negation or an exclusion in the words turns a filter word round, as "except
    bugs". "Won't Fix" turns none."""
    return bool(_governed(text))


def _negated_done(text: str) -> frozenset[str]:
    """Done words that one negation turns into open, as "not done" or "aren't finished"."""
    return frozenset(
        word for word, turns in _governed(text) if word in STATUS_VOCAB["done"] and len(turns) == 1
    )


PERSONS_ACTION: Final = re.compile(
    r"\b(?:i|we|you|i've|we've|i'd|we'd)\s+(?:have\s+|had\s+)?(?P<before>{when})\b|"
    r"\b(?P<after>{when})\s+by\s+(?:me|us|you|myself|[A-Z][a-z]+)\b"
)
"""A day word framed as what a person did ("the bugs I raised", "opened by me", "filed by
Bob") names the reporter, which the search can't filter by, so the day filter does not explain
that word: it comes back with the person."""


def _persons_action(span: str, when: str) -> frozenset[str]:
    forms = "|".join(re.escape(w) for w in WHEN_VOCAB[when])
    pattern = re.compile(PERSONS_ACTION.pattern.format(when=forms), re.IGNORECASE)
    return frozenset(_low(m.group("before") or m.group("after")) for m in pattern.finditer(span))


def _leads_its_clause(text: str, span: tuple[int, int] | None, forms: frozenset[str]) -> bool:
    """Whether the clause holding `span` opens with one of `forms`, after filler only."""
    start = max([0] + [m.end() for m in CLAUSE_END.finditer(text[: span[0]])]) if span else 0
    for raw, _, _ in _request_tokens(text[start : span[1] if span else len(text)]):
        if _low(raw) in forms:
            return True
        if _low(raw) not in FILLER | ME_WORDS:
            return False
    return False


def _own_run(text: str, explained: frozenset[str]) -> tuple[int, int] | None:
    """The longest run of the request's words a structure explains, with filler between, when
    it holds at least two such words: where the structure stands when the model quoted
    nothing for it ("the open DESK bugs"). None when no run is that long."""
    best: tuple[int, int] | None = None
    best_count = 0
    run: list[tuple[int, int]] = []
    count = 0
    for raw, start, end in _request_tokens(text) + [("", len(text), len(text))]:
        low = _low(raw)
        if raw and low in explained:
            run.append((start, end))
            count += 1
        elif raw and low in FILLER and run:
            run.append((start, end))
        else:
            if count >= 2 and count > best_count:
                first = next(a for a, b in run if _low(text[a:b]) in explained)
                last = next(b for a, b in reversed(run) if _low(text[a:b]) in explained)
                best, best_count = (first, last), count
            run, count = [], 0
    return best


def render_search(read: SearchRead, text: str) -> Rendered:
    """The look-for row, written from the search. A filter the request never framed is dropped,
    so its words come back to the person instead of a claim. With no quote from the model, the
    search stands on the longest run of its own words in the request."""
    said = _locate(text, read.said)
    explained: set[str] = set(SEARCH_VOCAB)
    if _leads_its_clause(text, said, REVIEW):
        explained.update(REVIEW)
    sourced = True
    types = list(
        dict.fromkeys(t for t in (TYPE_BY_FORM.get(_low(x)) for x in read.issue_types) if t)
    )
    kept_types = [
        t
        for t in types
        if _forms_in(text, frozenset(ISSUE_TYPES[t]))
        and not _negations(text, frozenset(ISSUE_TYPES[t]))
    ]
    for name in kept_types:
        explained.update(ISSUE_TYPES[name])
    subject = " and ".join(kept_types[:3]).lower() + " tickets" if kept_types else "tickets"
    status = ""
    # A status whose own words are negated, as "not done" read as done, is the wrong way round,
    # so it is dropped and its words come back. "not done" read as open holds the negation.
    if read.status is not None and not _negations(text, STATUS_VOCAB[read.status]):
        vocab = STATUS_VOCAB[read.status]
        negated = _negated_done(text) if read.status == "open" else frozenset[str]()
        if _forms_in(text, vocab) or negated:
            explained.update(vocab | negated | _negations(text, negated))
        else:
            sourced = False
        explained.update(STILL)
        status = f"{read.status} "
    parts = [f"{status}{subject}"]
    project = _project_in(text, read.project)
    if project is not None:
        parts.append(f"in {project}")
        explained.add(project.casefold())
    assignee = _assignee(text, read.assignee)
    if assignee is not None:
        negations = _negations(text, assignee[1])
        if not negations or assignee[0] == NO_ASSIGNEE:
            parts.append(assignee[0])
            explained.update(assignee[1] | negations)
    tail: list[str] = []
    for when, filter_ in _day_filters(read, text):
        quoted = text[said[0] : said[1]] if said is not None else ""
        explained.update(
            (WHEN_VOCAB[when] - _persons_action(quoted, when))
            | DAYS_VOCAB
            | _negations(text, WHEN_VOCAB[when])
        )
        shown = _days_text(when, filter_)
        if shown is None:
            continue
        tail.append(shown)
        if filter_.days is not None:
            if said_in(str(filter_.days), text) or (filter_.days == 0 and said_in("today", text)):
                explained.add(str(filter_.days))
            else:
                sourced = False
    topic = _topic(text, read.words)
    if topic is not None:
        tail.append(f'with "{topic[0]}" in the title or body')
        explained.update(topic[1])
    shown = " ".join(parts) + (", " + ", ".join(tail) if tail else "")
    shown = shown[:1].upper() + shown[1:]
    asked = days_asked(read, text)
    row = UnderstoodRow(
        kind="look_for",
        text=plain(shown, TEXT_LIMIT),
        state="missing" if asked else "understood" if sourced else "changed",
        note=NO_DAYS.format(text[asked[0] : asked[1]]) if asked else _note(text, said, sourced),
    )
    stands = said if said is not None else _own_run(text, frozenset(explained))
    return Rendered(row, frozenset(explained), stands)


def _day_filters(read: SearchRead, text: str) -> list[tuple[str, DaysRead]]:
    """The day filters the request frames in their own direction. One on a date the request
    never names, as "the last comment is older than 5 days" read as no update, is dropped like
    an assignee or a topic it never framed. One the model read the other way round, as "haven't
    been updated for 10 days" read as updated within 10 days, or turned round twice, as "not
    gone without an update", is dropped too: its words come back, never shown as understood."""
    found: list[tuple[str, DaysRead]] = []
    updated = read.updated
    if updated is None and _forms_in(text, STALE):
        updated = DaysRead(how="before")
    for when, filter_ in (
        ("created", read.created),
        ("updated", updated),
        ("done", read.done),
    ):
        forms = WHEN_VOCAB[when]
        if filter_ is None or not _forms_in(text, forms) or _doubled(text, forms):
            continue
        no_change = _negations(text, forms) or (when == "updated" and _forms_in(text, NOT_UPDATED))
        if not no_change or filter_.how == "before":
            found.append((when, filter_))
    return found


def days_asked(read: SearchRead | None, text: str) -> tuple[int, int] | None:
    """Where the request names a span of days with no number, as "stale" or "no update": the
    number is asked for, never guessed. None when every day filter has its number."""
    for when, filter_ in _day_filters(read, text) if read is not None else []:
        if filter_.how == "since_last_run" or filter_.days is not None:
            continue
        tokens = _request_tokens(text)
        for at, (raw, start, end) in enumerate(tokens):
            if _low(raw) in WHEN_VOCAB[when] | NOT_UPDATED:
                lead = at > 0 and _turns(tokens, at - 1) is not None
                return (tokens[at - 1][1] if lead else start), end
    return None


def _open_as_create(text: str) -> frozenset[str]:
    """ "open" explains a request word only as the verb that opens a ticket, as in "open one
    ticket", never as the state of the tickets looked for."""
    tokens = [_low(t) for t, _, _ in _request_tokens(text)]
    for at, token in enumerate(tokens[:-1]):
        if token in ("open", "opens", "opening") and tokens[at + 1] in OPEN_AS_CREATE_AFTER:
            return frozenset({token})
    return frozenset()


def render_ticket(read: TicketRead, text: str) -> Rendered:
    """The do row, written from what happens with what was found. A detail is kept only when
    the request's own words for the ticket ask for it, in the quote as the request writes it
    or in its own words for the new ticket; a detail the model added is dropped, not claimed."""
    said = _locate(text, read.said)
    phrase = CREATE_PHRASE.search(text) if read.creates else None
    also = None if phrase is None else (phrase.start(), phrase.end())
    verbatim = _find(text, read.said)
    quoted = " ".join(text[span[0] : span[1]] for span in (verbatim, also) if span is not None)
    explained: set[str] = set(SAYS_VOCAB[read.says])
    if phrase is not None:
        explained.update(k.casefold() for k in PROJECT_KEY.findall(phrase.group(0)))
    what = {"list": "lists them", "count": "counts them", "summary": "sums them up"}[read.says]
    details: list[str] = []
    for detail in dict.fromkeys(read.shows):
        if not _forms_in(quoted, SHOWS_VOCAB[detail]):
            continue
        explained.update(SHOWS_VOCAB[detail])
        details.append(
            {
                "owner": "who owns each one",
                "type": "each one's type",
                "status": "whether each one is open or done",
                "created": "when each one was created",
                "updated": "when each one was last updated",
                "done": "when each one was finished",
            }[detail]
        )
    with_details = f", with {' and '.join(details)}" if details else ""
    if read.creates:
        explained.update(CREATE_VOCAB | _open_as_create(text))
        shown = f"Create one ticket that {what}{with_details}"
    else:
        shown = {"list": "List them", "count": "Count them", "summary": "Sum them up"}[read.says]
        shown += with_details
    row = UnderstoodRow(
        kind="do",
        text=plain(shown, TEXT_LIMIT),
        state="understood",
        note=_note(text, _joined(text, verbatim, also), True),
    )
    return Rendered(row, frozenset(explained), said, also)


def _joined(
    text: str, said: tuple[int, int] | None, also: tuple[int, int] | None
) -> tuple[int, int] | None:
    """The request's words for the ticket, as one span when the model's quote and the request's
    own words for the new ticket stand together ("create one follow-up ticket that lists
    them" for a quote of "lists them"), so the note quotes the person's whole phrase."""
    if said is None or also is None:
        return said if said is not None else also
    start, end = min(said[0], also[0]), max(said[1], also[1])
    gap = text[min(said[1], also[1]) : max(said[0], also[0])]
    between = [_low(t) for t, _, _ in _request_tokens(gap)]
    return (start, end) if all(t in FILLER for t in between) else said


def render_place(read: PlaceRead, text: str) -> Rendered:
    """The where row, standing on the words the model quoted for the place ("in MOCK"), else
    on the key's last mention in the request."""
    project = _project_in(text, read.project)
    said = _find(text, read.said, last=True)
    if project is None:
        return Rendered(missing_row("where"), frozenset(), said)
    if said is None or not said_in(project, text[said[0] : said[1]]):
        # The model often fills the project and leaves said empty: the key as the request
        # writes it is the person's own, so the row stands on its last mention, in capitals
        # where the request writes it so, because "its" in "with its Environment" is not ITS.
        keys = list(re.finditer(rf"(?<!\w){re.escape(project)}(?!\w)", text))
        said = (keys[-1].start(), keys[-1].end()) if keys else _find(text, project, last=True)
    sourced = said is not None
    row = UnderstoodRow(
        kind="where",
        text=f"Jira project {project}",
        state="understood" if sourced else "changed",
        note=_note(text, said, sourced),
    )
    return Rendered(row, PLACE_VOCAB | frozenset({project.casefold()}), said)


def _schedule_token(token: str) -> bool:
    low = _low(token)
    if low in SHORT_FORMS and (token.isupper() or (low in ("sat", "sun") and token == low)):
        # A short day in capitals is a project key, as "MON", and "sat" and "sun" in small
        # letters are words of their own, never "Sat" or "Sun".
        return False
    return low in SCHEDULE_VOCAB or CLOCK_TOKEN.match(low) is not None or low.isdigit()


def _schedule_tokens(text: str) -> list[tuple[str, int, int, bool]]:
    """The request's tokens, each with whether it is a schedule's: a schedule word, a time or a
    number, or any word of a range of times, a bound on one or a schedule it can't hold, as
    "till" in "16:00 till 17:00", "around" in "around 4pm" or "second" in "every second
    Tuesday"."""
    return list(_scheduled(text))


@lru_cache(maxsize=64)
def _scheduled(text: str) -> tuple[tuple[str, int, int, bool], ...]:
    """Kept per request, since each of its readers asks."""
    tokens = _request_tokens(text)
    ranges = [r.whole for r in time_ranges(text)] + [
        m.span()
        for pattern in (
            DAY_RANGE,
            BOUND_TIME,
            SCHEDULE_PHRASE,
            RELATIVE_TIME,
            APPROXIMATE,
            VAGUE_TIME,
            LEFT_OUT,
        )
        for m in pattern.finditer(text)
    ]
    return tuple(
        (
            raw,
            start,
            end,
            any(a <= start and end <= b for a, b in ranges)
            or (
                _schedule_token(raw)
                and not (raw.isdigit() and COUNTED.match(text, end))
                and not (n > 0 and tokens[n - 1][0].isdigit() and _low(raw) in UNITS)
            ),
        )
        for n, (raw, start, end) in enumerate(tokens)
    )


def _a_schedule_word(token: str) -> bool:
    """A word only a schedule uses, which the schedule row carries or asks for, so it is never
    a part the platform can't do. "first" or "last" can be a filter, so they are not here."""
    low = _low(token)
    return low in SCHEDULE_WORDS | words("every each am pm o'clock") or bool(CLOCK_TOKEN.match(low))


def _no_time_said(schedule: str, text: str) -> str:
    """The note on a schedule asked for because its time was a guess, keeping the words that
    were the person's own, such as "Every Friday", and never a day the model guessed."""
    unsaid = [t for t in TIME_OF_DAY.findall(schedule) if not said_in(t.strip(), text)]
    day = schedule
    for time in unsaid:
        day = day.replace(time, " ")
    day = " ".join(day.split()).strip(" ,").removesuffix(" at").removesuffix(" in the")
    words_of_day = re.findall(r"\w+", day)
    theirs = any(w.casefold() in SCHEDULE_WORDS or TIME_OF_DAY.search(w) for w in words_of_day)
    if not theirs or not all(said_in(w, text) for w in words_of_day):
        return NO_TIME_SAID
    return NO_TIME_BUT.format(day)


def _schedule_span(text: str, shown: str) -> tuple[int, int] | None:
    """Where the request's schedule stands: the model's schedule words as the request writes
    them, else the request's first run of schedule words, which is the person's own phrase
    for it ("Each week" read as "Every Monday"). A first run that names no schedule, as "on" in
    "on GitHub", is no phrase for it: then the schedule stands where a later run says it repeats
    and names the day or the time the model read, written another way, as "every weekday at
    9am" for "Weekdays at 9am", and the whole request names them too. A day word anywhere else,
    as in "finished by this Friday" or "due Friday at 5pm", is not the schedule's, and comes
    back if nothing else explains it."""
    found = _find(text, shown)
    if found is not None:
        return found
    runs = _schedule_runs(text)
    if not runs:
        return None
    if _run_named(text, runs[0]):
        return runs[0][0][0], runs[0][-1][1]
    read = said_schedule(shown)
    if not _same_schedule(read, said_schedule(text)):
        return None
    for run in runs[1:]:
        start, end = run[0][0], run[-1][1]
        said = text[start:end]
        if REPEATS.search(said) and _same_schedule(read, said_schedule(said)):
            return start, end
    return None


REPEATS: Final = re.compile(rf"\b(?:every|each|daily|weekdays|(?:{DAY_NAMES})s)\b", re.IGNORECASE)
"""Words that say a schedule repeats, as "every", "daily" or "Fridays". A day or a time with
none, as "Friday at 5pm", may be a date, so a schedule is never taken from it alone."""


def _schedule_runs(text: str) -> list[list[tuple[int, int]]]:
    """Each run of the request's schedule tokens, in order, as the tokens' spans."""
    runs: list[list[tuple[int, int]]] = []
    run: list[tuple[int, int]] = []
    for _, start, end, scheduled in [*_schedule_tokens(text), ("", 0, 0, False)]:
        if scheduled:
            run.append((start, end))
        elif run:
            runs.append(run)
            run = []
    return runs


def _run_named(text: str, run: list[tuple[int, int]]) -> bool:
    return (
        any(_a_schedule_word(text[a:b]) for a, b in run)
        or DAY_RANGE.search(text, run[0][0], run[-1][1]) is not None
    )


def _same_schedule(
    read: tuple[str | None, str | None], said: tuple[str | None, str | None]
) -> bool:
    """Whether the words name each of the day and the time the model read, and it read one. They
    may name a time it left out, never only the time of a day it guessed."""
    named = [(a, b) for a, b in zip(read, said, strict=True) if a is not None]
    return bool(named) and all(a == b for a, b in named)


def _schedule_explained(text: str) -> frozenset[str]:
    """What the schedule explains inside its own span: schedule words, and clock tokens, numbers
    and the words of a range of times as the request writes them."""
    return SCHEDULE_VOCAB | frozenset(
        _low(raw) for raw, _, _, scheduled in _schedule_tokens(text) if scheduled
    )


@dataclass(frozen=True)
class Clash:
    """Two days, or two times, in one schedule's words. A schedule runs on one day at one time,
    so the person picks one, and neither is picked for them."""

    reason: ClashReason
    choices: tuple[str, ...]
    start: int
    end: int


def _clock(match: re.Match[str]) -> str:
    """A CLOCK match as a 24-hour time, 09:00, except a bare hour, which stays as written."""
    if (named := match.group("named")) is not None:
        return "00:00" if named.casefold() == "midnight" else "12:00"
    if (bare := match.group("bare")) is not None:
        return bare
    said = match.group("twelve") or match.group("day")
    hour, minute = (re.findall(r"\d+", said) + ["00"])[:2]
    if match.group("twelve") is None:
        return f"{int(hour):02d}:{minute}"
    return f"{int(hour) % 12 + (12 if said.casefold().endswith('pm') else 0):02d}:{minute}"


def _schedule_run(text: str, said: tuple[int, int] | None) -> tuple[int, int] | None:
    """Where the schedule stands, grown over the schedule words beside it in its clause, so
    "every Monday at 9am and every Friday at 9am" is one stretch, whichever part was quoted."""
    tokens = _schedule_tokens(text)
    inside = [i for i, (_, a, b, _) in enumerate(tokens) if said and a < said[1] and b > said[0]]
    if not inside:
        return None
    clause_of = _clause_of(text, [(raw, a, b) for raw, a, b, _ in tokens])
    first, last = inside[0], inside[-1]
    while first > 0 and clause_of[first - 1] == clause_of[first]:
        if not tokens[first - 1][3]:
            break
        first -= 1
    while last + 1 < len(tokens) and clause_of[last + 1] == clause_of[last]:
        if not tokens[last + 1][3]:
            break
        last += 1
    return tokens[first][1], tokens[last][2]


def _clash(
    reason: ClashReason, found: list[re.Match[str]], key: Callable[[re.Match[str]], str], at: int
) -> list[Clash]:
    """A clash when the matches name two or more different days or times, each in the words it
    was first said in."""
    named: dict[str, str] = {}
    for match in found:
        said = match.group(1) if reason == "one_day" else match.group(0)
        named.setdefault(key(match), re.sub(r"^(?:at|or|and)\s+", "", said, flags=re.IGNORECASE))
    if len(named) < 2:
        return []
    return [Clash(reason, tuple(named.values()), at + found[0].start(), at + found[-1].end())]


def _clashes(text: str, said: tuple[int, int] | None) -> list[Clash]:
    """Two days, times or frequencies in the schedule's own words, or else a day or a time a
    later clause names that differs from the schedule's, as "actually make it Monday"."""
    run = _schedule_run(text, said)
    if run is None:
        return []
    return _own_clashes(text, run) or _later(text, run).clashes


def _own_clashes(text: str, run: tuple[int, int]) -> list[Clash]:
    """Two frequencies, two days or two times in one stretch of schedule words. Every day,
    every weekday and a day of the week are each a day, so "Mon-Fri and Sat" is two."""
    stretch = text[run[0] : run[1]]
    often = _clash("one_frequency", list(FREQUENCY.finditer(stretch)), _often, run[0])
    days, _ = _when(stretch, text)
    named = {day.key: day.said for day in days}
    one_day = (
        [Clash("one_day", tuple(named.values()), run[0] + days[0].start, run[0] + days[-1].end)]
        if len(named) > 1 and not often
        else []
    )
    times = list(CLOCK.finditer(stretch))
    return often + one_day + (_clash("one_time", times, _clock, run[0]) or _range_clash(text, run))


SCHEDULE_TALK: Final = words(
    "actually sorry wait no not mean meant rather instead oops make made change move switch run "
    "runs set push shift reschedule bring time also too again plus then well both i more longer "
    "anymore though although however"
)
"""Words a clause may hold beside a day or a time and still speak only of when it runs, as
"actually make it Monday" or "run it at 9am"."""
TALK_WORDS: Final = FILLER | SCHEDULE_TALK | POLITE


@dataclass(frozen=True)
class Named:
    """A day or a time a schedule phrase names: as code reads it, as the person wrote it, and
    where it stands in the phrase."""

    key: str
    said: str
    start: int
    end: int


def _when(phrase: str, context: str) -> tuple[list[Named], list[Named]]:
    """The days and the times a schedule phrase names, in order: every weekday (Monday to Friday
    in any form, or every day with only the weekend left out anywhere in `context`), every day,
    a day of the week, whole or short, and a time on the clock. A day left out, as in "skip
    Fridays", is no day it runs on, and a range of other days names none."""

    def blank(text: str, pattern: re.Pattern[str]) -> str:
        return pattern.sub(lambda m: " " * len(m.group(0)), text)

    found: list[Named] = []
    blanked = blank(phrase, LEFT_OUT)
    for match in DAY_RANGE.finditer(blanked):
        if _monday_to_friday(match.group(0)):
            found.append(Named("weekdays", match.group(0), *match.span()))
    blanked = blank(blanked, DAY_RANGE)
    weekend_alias = _weekend_alias(context)
    for match in re.finditer(r"\bweekdays?\b", blanked, re.IGNORECASE):
        found.append(Named("weekdays", match.group(0), *match.span()))
    for match in EVERY_DAY.finditer(blanked):
        found.append(
            Named("weekdays" if weekend_alias else "every_day", match.group(0), *match.span())
        )
    for match in DAY.finditer(blanked):
        word = match.group(1)
        found.append(Named(day_key(word), _day_said(word), *match.span()))
    times = [
        Named(_clock(m), re.sub(r"^(?:at|or|and)\s+", "", m.group(0), flags=re.I), *m.span())
        for m in CLOCK.finditer(phrase)
    ]
    return sorted(found, key=lambda day: day.start), times


@dataclass(frozen=True)
class Phrase:
    """A run of schedule words within a clause, with: whether its clause speaks only of when it
    runs (schedule words, filler and the few words that change a schedule, as "actually make it
    Monday" or "Run it at 9am"); whether that clause changes it, as "change it to 10am"; the
    clause; and its first and last token."""

    start: int
    end: int
    talk: bool
    changes: bool
    clause: int
    first: int
    last: int


CHANGE_VERBS: Final = words("change set move push shift switch reschedule bring make run")


@lru_cache(maxsize=64)
def _runs(text: str) -> tuple[Phrase, ...]:
    """Every run of schedule words within a clause. Kept per request, since its readers ask
    more than once."""
    tokens = _schedule_tokens(text)
    clause_of = _clause_of(text, [(raw, a, b) for raw, a, b, _ in tokens])
    talk = {
        clause
        for clause in set(clause_of) - {-1}
        if all(
            scheduled or _low(raw) in TALK_WORDS
            for n, (raw, _, _, scheduled) in enumerate(tokens)
            if clause_of[n] == clause
        )
    }
    changes = {clause_of[n] for n, (raw, _, _, _) in enumerate(tokens) if _low(raw) in CHANGE_VERBS}
    runs: list[list[int]] = []
    for n, (_, _, _, scheduled) in enumerate(tokens):
        if not scheduled:
            continue
        if runs and runs[-1][-1] == n - 1 and clause_of[n] == clause_of[n - 1] != -1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return tuple(
        Phrase(
            tokens[run[0]][1],
            tokens[run[-1]][2],
            clause_of[run[0]] in talk,
            clause_of[run[0]] in changes,
            clause_of[run[0]],
            run[0],
            run[-1],
        )
        for run in runs
    )


def _phrases(text: str) -> list[Phrase]:
    """Each run of schedule words within a clause that names a day or a time."""
    return [p for p in _runs(text) if any(_when(text[p.start : p.end], text))]


def own_left_out(text: str) -> list[tuple[int, int]]:
    """The days the schedule's own words leave out: a day left out that leads its clause, as
    ", but not holidays" or ", skip Fridays if it is quiet", or that stands beside the schedule's
    own phrase with only words about when it runs between, as "every weekday except Friday" or
    "every day at 9am though not on Fridays". A day left out further into a clause, as "tickets
    we skip on Mondays", is a filter's. A day the schedule's words name without saying to run
    on it is always the schedule's own."""
    off = list(_not_run_on(text))
    spans = [span for span in left_out(text) if span not in off]
    if not spans:
        return off
    tokens = _schedule_tokens(text)
    clause_of = _clause_of(text, [(raw, a, b) for raw, a, b, _ in tokens])
    # A day inside what is left out, as "Mondays" in "skip on Mondays", makes no phrase the
    # schedule's own.
    rest = LEFT_OUT.sub(lambda m: " " * len(m.group(0)), text)
    own = [p for p in _runs(text) if p.talk or _marked(rest[p.start : p.end])]

    def talk(start: int, end: int, clause: int) -> bool:
        return all(
            scheduled or _low(raw) in TALK_WORDS
            for n, (raw, a, _, scheduled) in enumerate(tokens)
            if start <= a < end and clause_of[n] == clause
        )

    found: list[tuple[int, int]] = []
    for start, end in spans:
        clause = next((clause_of[n] for n, t in enumerate(tokens) if t[1] >= start), -1)
        beside = any(
            p.clause == clause
            and (
                (p.start < end and start < p.end)
                or talk(min(p.end, end), max(p.start, start), clause)
            )
            for p in own
        )
        # A clause that changes when it runs is the schedule's words, after a workflow's name
        # too, as "make the release check skip Fridays".
        changes = any(
            clause_of[n] == clause and not scheduled and _low(raw) in CHANGE_VERBS
            for n, (raw, a, _, scheduled) in enumerate(tokens)
            if a < start
        )
        if beside or changes or talk(0, start, clause):
            found.append((start, end))
    return sorted(found + off)


@dataclass(frozen=True)
class Later:
    """What a later clause that speaks only of when it runs does to the schedule: a day or a
    time that differs from the schedule's, asked as a choice of both; a time or a day the
    schedule lacks, which it takes; and the words of the one it asks about or takes, which the
    schedule then explains."""

    clashes: list[Clash]
    adds: str | None
    also: tuple[int, int] | None


def _later(text: str, run: tuple[int, int]) -> Later:
    """Each phrase besides the schedule's own that names a day or a time, in a clause that
    speaks only of when it runs. One that differs from the schedule's own day or time is a
    clash, never the first taken, so a correction such as "actually make it Monday" is asked;
    a time that only bounds the run or is not exact, as "by 5pm", is no time to choose. One that
    names the time or the day the schedule lacks, whole, as "Run it at 9am", adds it. Any other
    comes back as a part of its own, as before. A day it names without saying to run on it, as
    "Fridays off", is left out, so it is no choice to offer."""
    days, times = _when(text[run[0] : run[1]], text)
    off = _not_run_on(text)
    clashes: list[Clash] = []
    adds: str | None = None
    also: tuple[int, int] | None = None
    for later in _phrases(text):
        start, end = later.start, later.end
        if (start < run[1] and end > run[0]) or not later.talk:
            continue
        if any(a < end and start < b for a, b in off):
            continue
        phrase = text[start:end]
        whole = _whole_time(phrase, text, later.changes)
        their_days, their_times = _when(phrase, text)
        pairs: tuple[tuple[ClashReason, list[Named], list[Named]], ...] = (
            ("one_day", days, their_days),
            ("one_time", times, [] if inexact_time(phrase) else their_times),
        )
        clashed = False
        for reason, ours, theirs in pairs:
            known = {named.key for named in ours}
            new = [(named.key, named.said) for named in theirs if named.key not in known]
            if ours and new and not any(c.reason == reason for c in clashes):
                choices = dict([(ours[0].key, ours[0].said), *new])
                clashes.append(Clash(reason, tuple(choices.values()), start, end))
                clashed = True
        lacks = (not days and their_days) or (not times and their_times)
        if whole and (clashed or (lacks and adds is None)):
            adds = adds if clashed else _trimmed(phrase)
            also = also or (start, end)
        elif whole and not lacks:
            also = also or (start, end)
    return Later(clashes, None if clashes else adds, also)


def _whole_time(phrase: str, context: str, changes: bool = False) -> bool:
    """Whether a phrase names its time whole: every word one a schedule holds, no bound and no
    time that is not exact, and a time the schedule runs at. In a clause that changes when it
    runs, "to" or "for" leads the new time too, as "change it to 10am"."""
    clocks = list(CLOCK.finditer(phrase))
    leads = RUN_TIME_LEADS | (words("to for") if changes else frozenset[str]())
    return (
        _all_held(phrase, context)
        and BOUND_TIME.search(phrase) is None
        and APPROXIMATE.search(phrase) is None
        and all(_run_time(phrase, clock, leads) is not None for clock in clocks[:1])
    )


def _range_clash(text: str, run: tuple[int, int]) -> list[Clash]:
    """A range of times in the schedule's words, as "from 4 to 5pm", which the clock reads as
    one time or none. The schedule runs at one time, so the person picks an end, and neither is
    picked for them. Ranges are read in the whole request, so a count after an end, as "20" in
    "9am - 20 tickets", is seen."""
    ranges = [r for r in time_ranges(text) if run[0] <= r.whole[0] and r.end <= run[1]]
    return [
        Clash("one_time", r.ends, r.start, r.end)
        for r in ranges[:1]
        if r.ends[0].casefold() != r.ends[1].casefold()
    ]


def _often(match: re.Match[str]) -> str:
    word = (match.group(1) or match.group(2)).casefold()
    return OFTEN.get(word, word)


def _names_a_schedule(phrase: str) -> bool:
    """Whether a run of schedule words names a schedule: a word only a schedule uses, as "every"
    or "Friday", or a phrase such as "once a month"."""
    return SCHEDULE_PHRASE.search(phrase) is not None or any(
        _a_schedule_word(t) for t, _, _ in _request_tokens(phrase)
    )


def how_often(words_: str) -> tuple[int, int] | None:
    """Where the words ask for a schedule it can't hold: the first schedule phrase with a word
    the schedule doesn't hold, as "every other Friday", "once a month" or "every weekday except
    Friday", whole. A schedule holds one or more days, every day, every weekday or once a week,
    and one time."""
    tokens = _schedule_tokens(words_)
    clause_of = _clause_of(words_, [(raw, a, b) for raw, a, b, _ in tokens])
    run: list[tuple[int, int]] = []
    for n, (_, start, end, scheduled) in enumerate([*tokens, ("", 0, 0, False)]):
        same = run and n < len(tokens) and clause_of[n] == clause_of[n - 1]
        if scheduled and (not run or same):
            run.append((start, end))
            continue
        phrase = words_[run[0][0] : run[-1][1]] if run else ""
        if run and _names_a_schedule(phrase) and _unheld(phrase, words_):
            trimmed = _trimmed(phrase)
            at = run[0][0] + phrase.find(trimmed)
            return min([(at, at + len(trimmed)), *left_out(words_[: run[0][0]])])
        run = [(start, end)] if scheduled else []
    # A day left out anywhere, as "skip Fridays", is a schedule it can't hold, as "every weekday
    # except Friday" is. It reads more than it must, as a reader that only asks may.
    return next(iter(left_out(words_)), None)


def change_unheld(words: str) -> tuple[int, int] | None:
    """Where words that only change a schedule ask for one it can't hold: a frequency it can't
    hold, as "every other Friday", a day they name without saying to run on it, as "except
    Friday's" or "unless it's a Friday", wherever it stands, or a word that looks like a day or
    time off they leave out, as "except PH" or "except when I'm on leave", as `when_said` reads
    it, so a change never keeps a day it can't honour. Where `when_said` reads more of the words
    as left out, the stretch grows over them, as "except during business hours" round "hours"."""
    off = _not_run_on(_without_ties(words), everywhere=True)
    found = how_often(words) or next(iter(off), None)
    left = when_said(words).left_out
    if found is None:
        return next(iter(left), None)
    for start, end in left:
        if start < found[1] and found[0] < end:
            found = min(start, found[0]), max(end, found[1])
    return found


def schedule_unheld(schedule: str | None, text: str) -> tuple[int, int] | None:
    """Where the request's own schedule asks for one it can't hold, or None: its phrase, whole,
    less a clause of it that holds only what a schedule holds, as "Daily at 9am" before "except
    weekends and holidays"; else a day the words leave out anywhere, as "skip Fridays"."""
    run = _schedule_run(text, _schedule_span(text, " ".join(_kept(schedule)).strip(" ,")))
    if run is None or not _unheld(text[run[0] : run[1]], text):
        return next(iter(own_left_out(text)), None)
    parts = [
        trim(text, max(a, run[0]), min(b, run[1]))
        for a, b in clauses_of(text)
        if a < run[1] and b > run[0]
    ]
    unheld = [(a, b) for a, b in parts if a < b and _unheld(text[a:b], text)] or [run]
    stretch = text[unheld[0][0] : unheld[-1][1]]
    trimmed = _trimmed(stretch)
    at = unheld[0][0] + stretch.find(trimmed)
    return at, at + len(trimmed)


def _kept(schedule: str | None) -> list[str]:
    return [t for t in (visible_words(schedule) or "").split() if _schedule_token(t.strip(",."))]


def schedule_stretch(schedule: str | None, text: str) -> tuple[int, int] | None:
    """Where the request says when it runs, with every schedule word beside it, or None."""
    run = _schedule_run(text, _schedule_span(text, " ".join(_kept(schedule)).strip(" ,")))
    if run is None or not any(_a_schedule_word(t) for t in text[run[0] : run[1]].split()):
        return None
    return run


def schedule_clashes(schedule: str | None, text: str) -> list[Clash]:
    """The days or times that clash in the request's schedule, in the request's own words."""
    return _clashes(text, _schedule_span(text, " ".join(_kept(schedule)).strip(" ,")))


def clashes_in(words: str) -> list[Clash]:
    """The days, times or frequencies that clash anywhere in the words, as an edit's new schedule
    names them."""
    return _clashes(words, (0, len(words)))


def said_schedule(words: str) -> tuple[str | None, str | None]:
    """The one day and the one time the words name, each None when they name none or more
    than one, and both None for a schedule it can't hold. A time is 24-hour, as 09:00, except a
    bare hour, which stays as written, so it never matches a time it might not mean. A time
    that only bounds the run, as "before 5pm", or is not exact, as "9am or so", is no time. A
    day or a time of a filter or of a ticket's date, as "set the due date to Friday at 5pm", is
    none of the schedule's, and a day the words name without saying to run on it, as "drop
    Fridays", leaves both None."""
    words = _without_ties(words)
    if (
        _clashes(words, (0, len(words)))
        or how_often(words) is not None
        or _days_named(words, everywhere=True)
    ):
        return None, None
    days = {day.key for day in _when(words, words)[0]}
    at = next((_clock(m) for m in CLOCK.finditer(words)), None)
    return next(iter(days)) if len(days) == 1 else None, None if inexact_time(words) else at


PORTAL_WEEKDAYS: Final = re.compile(r"\bweek ?days?\b|\bmonday to friday\b", re.IGNORECASE)
"""Every weekday as the Portal reads it from a schedule row."""


def weekdays_said(words_: str, context: str | None = None) -> bool:
    """Whether the words name every weekday another way than the Portal reads, as "Mon-Fri",
    "Monday to Fri" or every day with only the weekend left out anywhere in `context`."""
    return any(
        day.key == "weekdays" and not PORTAL_WEEKDAYS.fullmatch(day.said)
        for day in _when(words_, context or words_)[0]
    )


def inexact_times(words_: str) -> list[tuple[int, int]]:
    """Where the words name a time that only bounds the run, as "before 5pm", or that is not
    exact, as "9am or so", which a schedule never takes as its time. The time a word such as
    "or so" follows stands with it."""
    clocks = {m.end(): m.start() for m in CLOCK.finditer(words_)}
    found = [m.span() for m in BOUND_TIME.finditer(words_)]
    for match in APPROXIMATE.finditer(words_):
        before = words_[: match.start()].rstrip()
        found.append((clocks.get(len(before), match.start()), match.end()))
    return found


def inexact_time(words_: str) -> bool:
    return bool(inexact_times(words_))


@dataclass(frozen=True)
class WhenSaid:
    """When the words say a workflow runs, as code reads them whole. A day or a time is None
    when the words don't name one, or when they name one code can't take whole, and then
    `day_asked` or `time_asked` says so, so it is asked and never kept from before. `left_out`
    is each stretch where they leave out a day, or words that look like a day or time off, as
    "skip Fridays", "except PH" or "except when I'm on leave", which no schedule holds, so the
    day is asked. It is empty when they leave out none."""

    day: str | None
    at: str | None
    day_asked: bool
    time_asked: bool
    left_out: tuple[tuple[int, int], ...]

    @property
    def said(self) -> bool:
        """Whether the words say anything about when it runs."""
        return any((self.day, self.at, self.day_asked, self.time_asked))


FREQUENT: Final = re.compile(
    r"\b(?:every|each|daily|weekly|weekdays?|fortnightly|bi-?weekly|monthly|quarterly|yearly|"
    r"annually|hourly|nightly|once|twice|thrice|alternat(?:e|ing)|\d+\s+times)\b",
    re.IGNORECASE,
)
"""A word that makes a phrase a schedule's own, as "every", "daily" or "twice". A day in a
phrase with none, as "tickets created on Monday", "Monday's notes" or "the Mon-Fri rota", is
never the day it runs."""
FILTER_LEADS: Final = words(
    "due published created updated opened closed resolved raised filed logged modified edited "
    "changed done finished merged released tagged deployed shipped since from until till by "
    "before after"
)
"""Words that make what follows a filter's, as "due" in "tickets due Friday at 5pm" or
"published" in "releases published on Monday at 9am", so it is never the run time, even
when it is the only time the words name."""
UNREAD_DAY: Final = re.compile(
    r"\b(?:every|each)\s+(?:morning|afternoon|evening|night)s?\b|\bnightly\b|"
    r"\b(?:every|each|on|it|to)\s+(?:sat|sun)\b",
    re.IGNORECASE,
)
"""How often it runs, said in a way code doesn't read, as "every morning" or "nightly"."""
UNREAD_HOUR: Final = re.compile(
    r"\b(?:morning|afternoon|evening|night|nightly|tonight|lunchtime|lunch)\b|\bo['\u2019]?clock\b|"
    r"\bhalf\s+past\b|\bquarter\s+(?:past|to)\b|"
    r"\b(?:at|it|to|past)\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b|"
    r"\b(?:make|set|move|change|run|shift|push|bring)\s+it\s+(?:to\s+)?\d{1,2}\b"
    r"(?![:.]\d|\s*(?:am|pm)\b)",
    re.IGNORECASE,
)
"""A time said in a way code doesn't read, as "the afternoon", "half past nine" or "make it 10",
so it is asked and never kept from before."""


def _marked(phrase: str) -> bool:
    """Whether a phrase is a schedule's own: it has a word such as "every" or "daily", or a day
    in the plural, as "Fridays"."""
    plural = any(m.group(0).casefold() != m.group(1).casefold() for m in DAY.finditer(phrase))
    return FREQUENT.search(phrase) is not None or plural


def _timed(phrase: str) -> bool:
    """Whether a phrase names a time it runs at, as "at 9am" or "Friday 16:00"."""
    clock = CLOCK.search(phrase)
    return clock is not None and _run_time(phrase, clock) is not None


TICKET_DATES: Final = words(
    "due date dates deadline deadlines sla slas expiry expires expiring expiration"
)
"""A ticket's own dates, as "due date", "deadline", "SLA" or "expiry"."""
DATE_LINKS: Final = words("is are was be set for as")
"""Words that may stand between a ticket's date and its value, as "is" in "the deadline is
Friday"."""
CLAUSE_MARK: Final = re.compile(r"[,;.:!?()\[\]–—]|(?<!\w)-(?!\w)")
"""A mark between two words that ends the phrase one of them stands in, as the comma in "make
it Thursday, deadline Friday"."""

type Token = tuple[str, int, int, bool]


def _tied(text: str, tokens: list[Token], first: int, last: int) -> bool:
    """Whether a run of schedule words is a filter's or a ticket's date, never when it runs: a
    filter word or "by" leads it, as "created on Monday" or "by Friday", or a ticket's date
    stands beside it, as "set the due date to Friday at 5pm", "the deadline is Friday" or "5pm
    deadlines". A run with "every", "daily" or the like is the schedule's own, as in "post
    deadlines every Friday"."""
    if FREQUENT.search(text, tokens[first][1], tokens[last][2]) is not None:
        return False

    def low(n: int) -> str:
        return _low(tokens[n][0]) if 0 <= n < len(tokens) else ""

    def joined(a: int, b: int) -> bool:
        """Whether two tokens stand in one phrase, with no comma or other mark between."""
        return (
            a >= 0
            and b < len(tokens)
            and CLAUSE_MARK.search(text[tokens[a][2] : tokens[b][1]]) is None
        )

    if low(first) == "by" or low(first - 1) in FILTER_LEADS:
        return True
    n = first - 1
    while low(n) in DATE_LINKS and joined(n, n + 1):
        n -= 1
    if low(n) in TICKET_DATES and joined(n, n + 1):
        # A ticket's date right before a day in the plural and a time is what a reminder is about,
        # as "the deadline at 9am on Fridays": the run is the schedule's own.
        run = text[tokens[first][1] : tokens[last][2]]
        return not (
            n == first - 1
            and low(first) in ("at", "on")
            and _marked(run)
            and CLOCK.search(run) is not None
        )
    return (
        low(last + 1) in TICKET_DATES
        and joined(last, last + 1)
        and (low(last + 1), low(last + 2)) != ("due", "to")
    )


@lru_cache(maxsize=64)
def _own(text: str) -> tuple[Phrase, ...]:
    """The runs of schedule words that are the schedule's own: a phrase with "every", "daily" or
    a day in the plural, a clause that speaks only of when it runs, as "Run it at 9am", and a
    time "at" names when nothing else does. A run tied to a filter or to a ticket's date is
    never one. Kept per request, since its readers ask more than once."""
    runs = _runs(text)
    tokens = _schedule_tokens(text)
    # A day inside what is left out, as "Mondays" in "we skip on Mondays", marks no schedule.
    rest = LEFT_OUT.sub(lambda m: " " * len(m.group(0)), text)
    free = [not _tied(text, tokens, p.first, p.last) for p in runs]
    marked = [free[n] and _marked(rest[p.start : p.end]) for n, p in enumerate(runs)]
    return tuple(
        p
        for n, p in enumerate(runs)
        if free[n] and (marked[n] or p.talk or (not any(marked) and _timed(text[p.start : p.end])))
    )


def _without_ties(text: str) -> str:
    """The words with every run of schedule words tied to a filter or a ticket's date turned to
    spaces, so a schedule change never reads it."""
    tokens = _schedule_tokens(text)
    for p in _runs(text):
        if _tied(text, tokens, p.first, p.last):
            text = text[: p.start] + " " * (p.end - p.start) + text[p.end :]
    return text


RUN_VERBS: Final = words(
    "run runs running ran make makes made change changes changed move moves moved set switch "
    "switches switched shift shifts shifted push pushes pushed bring brings reschedule reschedules "
    "rescheduled do does keep keeps want wants need needs like"
)
"""Verbs whose day is the day it runs, as "make it Friday", "run it Fridays" or "I want it on
Fridays"."""
CAUSING: Final = words("make makes made have has had let lets get gets got")
"""Verbs that can have the workflow do another verb, as "make" in "make the release check skip
Fridays" or "have" in "have the check nix every Monday", so the word right before the day must
be one the reader knows."""
DOERS: Final = words("it them me us you someone somebody anyone anybody everyone")
"""Words after "make", "have", "let" or "get" that name who does the next verb, as "someone" in
"have someone check langgraph every Monday", so that verb starts the task's words."""
MODALS: Final = words("can could should would will must may might shall")
"""Words a verb follows, as "should" in "the check should nix every Monday"."""
BLANKED: Final = re.compile(r"\s{4,}")
"""Spaces where the edit flow took out the workflow's name, as in "make <the morning check>
post deadlines every Friday"."""
RUN_TALK: Final = words(
    "it its this that them i i'd i'm we we'd us you can could would should will please pls plz "
    "just only also too plus then again now instead actually rather sorry wait oops mean meant "
    "well so ok okay yes yeah both is are be for as thanks"
)
"""The other words that may stand beside a day it runs on, as "instead", "only" or "please"."""
RUN_WORDS: Final = RUN_VERBS | RUN_TALK
NOT_A_TASK: Final = RUN_WORDS | TALK_WORDS
"""Words that are no part of a task: talk and the words about running it."""
NOT_WORDS: Final = NEGATIONS | words("don't doesn't didn't won't can't cannot shouldn't")
LEAVING: Final = words(
    "drop drops dropping remove removes removing cut cuts cancel cancels cancelled canceled delete "
    "deletes scrap scraps ditch ditches omit omits exclude excludes excluding skip skips skipping "
    "pause pauses stop stops stopping lose take leave minus unless except besides without rid"
)
"""Words that leave out the day after them. `TASK_HEADS` asks for any word it doesn't know at
the front of a task's words. This list still asks after a verb that runs it, where that one
doesn't look, as "drop" in "keep the release check drop every Friday". It also has the card
quote the whole of "take Fridays out" and read "unless it's a Friday" as a day left out, not
just one it can't place. It only ever makes the reader ask."""
LABELS: Final = words("the a an this that these those our their its my your his her")
"""Words before a day that make it a label of the word after it, as "the Mon-Fri rota"."""
DAY_NAMED: Final = re.compile(
    rf"{DAY_RANGE.pattern}|\b(?:{DAY_FORMS})s?\b|\bweek ?days?\b|\bweekends?\b|"
    r"\b(?:public\s+|bank\s+)?holidays?\b",
    re.IGNORECASE,
)
"""A day as words name it: a range of days, a day of the week, whole or short, every weekday,
the weekend or holidays."""


def _not_run_on(text: str, everywhere: bool = False) -> tuple[tuple[int, int], ...]:
    """Where the schedule's own words leave a day out, so it is asked and never the day it
    runs, as "drop Fridays", "Fridays excluded", "unless it's a Friday" or "except Friday's"."""
    return tuple(span for span, left in _days_named(text, everywhere) if left)


def _unplaced(text: str) -> tuple[tuple[int, int], ...]:
    """Where the schedule's own words name one day, with no "every", no plural and no time, right
    after a word of the task, as "Check releases Monday", so code can't tell whether it is when
    the task runs: the day is asked, and nothing is crossed."""
    return tuple(span for span, left in _days_named(text) if not left)


@lru_cache(maxsize=64)
def _days_named(text: str, everywhere: bool = False) -> tuple[tuple[tuple[int, int], bool], ...]:
    """Each day the schedule's own words name without saying to run on it, with whether the
    words leave it out. The schedule's own words are a clause that holds the schedule's own
    phrase, and, beside one, a clause that is little more than a day, as "minus Friday"; with
    `everywhere`, as for words that only change a schedule, they are every clause. A day there
    counts only when the words around it say to run on it: "every Friday", "on Fridays", "make
    it Friday", "Fridays instead", "weekdays only", or, after a task's words that a word the
    reader knows starts, "every Monday", a day in the plural or a day with the time it runs at,
    as "Check every Monday", "Check langgraph Mondays" or "Check releases Monday at 9am". A word
    that leaves it out, as "drop Fridays", "Fridays excluded", "Friday is off" or "unless it's
    a Friday", or a day written "Friday's", leaves it out, with or without a time. A day that
    labels the word after it, as "Monday's tickets" or "the Mon-Fri rota", or that a filter or
    a ticket's date holds, as "created on Monday" or "the due date to Friday", is no part of the
    schedule. Kept per request, since its readers ask more than once."""
    tokens = _schedule_tokens(text)
    clause_of = _clause_of(text, [(raw, a, b) for raw, a, b, _ in tokens])
    words_in = Counter(
        clause_of[n] for n, (raw, _, _, scheduled) in enumerate(tokens) if _a_word(raw, scheduled)
    )
    owned = {p.clause for p in _own(text)}
    short = {c for c in clause_of if words_in[c] <= 1} if owned else set[int]()
    theirs = set(clause_of) if everywhere else owned | short
    starts: list[int | None] | None = None
    left = _left_out_spans(text)
    found: list[tuple[tuple[int, int], bool]] = []
    for day, tied in _days_in(text):
        clause = clause_of[day.first]
        if clause == -1 or clause not in theirs or tied:
            continue
        if any(a <= day.match.start() and day.match.end() <= b for a, b in left):
            continue
        starts = starts or _task_starts(text, tokens, clause_of)
        off = _off_the_schedule(text, tokens, clause_of, starts, day)
        if off is not None:
            # A clause beside the schedule's own is the schedule's words whole, as "or Monday if
            # Friday is a holiday".
            found.append((off[0] if clause in owned else clauses_of(text)[clause], off[1]))
    return tuple(sorted(set(found)))


def _runs_of(tokens: list[Token], clause_of: list[int]) -> dict[int, tuple[int, int, int | None]]:
    """For each schedule token, the run of schedule words it stands in, within its clause, and
    where the run's first word that says when it runs stands, as "every", "daily", "on" or
    "to", if it has one."""
    found: dict[int, tuple[int, int, int | None]] = {}
    n = 0
    while n < len(tokens):
        if not tokens[n][3]:
            n += 1
            continue
        end = n
        while end + 1 < len(tokens) and tokens[end + 1][3] and clause_of[end + 1] == clause_of[n]:
            end += 1
        frame = next(
            (
                k
                for k in range(n, end + 1)
                if _low(tokens[k][0]) in ("on", "to") or FREQUENT.fullmatch(tokens[k][0])
            ),
            None,
        )
        found.update({k: (n, end, frame) for k in range(n, end + 1)})
        n = end + 1
    return found


def _task_starts(text: str, tokens: list[Token], clause_of: list[int]) -> list[int | None]:
    """For each token, the word that must be one the reader knows for a day right after it to
    be the run day: the first word of the task's words that end at it, back to the clause's
    edge or a mark, passing over a word such as "automatically", one of `DOERS` and a channel,
    as "#ops" in "#ops nix every Monday". A word such as "should", or "to" right after a verb,
    starts the task's words again, as "nix" in "I want to nix Mondays".
    After a verb that has something else act, as "make" in "make the release check nix every
    Monday", it is the word itself, unless one of `DOERS` or a name the edit flow turned to
    spaces follows the verb, as in "make it post deadlines every Friday". After any other verb
    that runs it, as "move" in "move the release check to Tuesdays", there is none."""
    found: list[int | None] = []
    start: int | None = None
    held = own = False
    for n, (raw, _, _, scheduled) in enumerate(tokens):
        gap = text[tokens[n - 1][2] : tokens[n][1]] if n else ""
        if n and (clause_of[n] != clause_of[n - 1] or CLAUSE_MARK.search(gap) is not None):
            start, held, own = None, False, False
        found.append(None if held else (n if own or start is None else start))
        low = _low(raw)
        verb = low in RUN_VERBS or low in CAUSING
        after = text[tokens[n][2] : tokens[n + 1][1]] if n + 1 < len(tokens) else ""
        follows = _low(tokens[n + 1][0]) if n + 1 < len(tokens) else ""
        acted = low in CAUSING and (follows in DOERS or BLANKED.fullmatch(after))
        if low in MODALS or acted or (verb and follows == "to"):
            start, held, own = None, False, False
        elif verb:
            start, held, own = None, low not in CAUSING, low in CAUSING
        elif (
            start is None
            and _a_word(raw, scheduled)
            and low not in DOERS
            and text[tokens[n][1] - 1 : tokens[n][1]] != "#"
            and not (low.endswith("ly") and low not in NOT_ADVERBS)
        ):
            start = n
    return found


@dataclass(frozen=True)
class _Day:
    """A day the words name: its first and last token, the run of schedule words it stands in,
    whether a word that says when it runs leads it there, as "every" or "on", whether the run
    holds the time it runs at, as "every Friday at 9am", and its match."""

    first: int
    last: int
    run: tuple[int, int]
    every: bool
    timed: bool
    match: re.Match[str]


def _a_word(raw: str, scheduled: bool) -> bool:
    """Whether a token is a word of the task, not a schedule word, a word about when it runs,
    talk, a number or a day itself."""
    low = _low(raw)
    return not (
        scheduled
        or low in NOT_A_TASK
        or any(c.isdigit() for c in raw)
        or DAY_NAMED.fullmatch(raw.removesuffix("'s").removesuffix("’s")) is not None
    )


def _off_the_schedule(
    text: str, tokens: list[Token], clause_of: list[int], starts: list[int | None], day: _Day
) -> tuple[tuple[int, int], bool] | None:
    """The day's words with what leaves it out and True, when the words leave it out; the day's
    run of schedule words and False, when code can't place it; or None when the words say to run
    on it, or when it labels the word after it."""
    clause = clause_of[day.first]

    def inside(n: int) -> bool:
        return 0 <= n < len(tokens) and clause_of[n] == clause

    def low(n: int) -> str:
        return _low(tokens[n][0])

    def word(n: int) -> bool:
        return _a_word(tokens[n][0], tokens[n][3])

    first, last = day.run
    every = day.every
    possessive = text[day.match.end() : day.match.end() + 1] in ("'", "’")
    if _a_label(text, tokens, clause_of, day):
        return None
    lead, before, head = _talk_beside(text, tokens, clause_of, first - 1, -1)
    trail, after, tail = _talk_beside(text, tokens, clause_of, last + 1, 1)
    odd = [n for n in lead if low(n) not in RUN_TALK]
    odd_after = [n for n in trail if low(n) not in RUN_WORDS]
    led = head if before in ("verb", "word") else None
    turned = [
        n for n in ([] if led is None else [led - 1, led]) if inside(n) and low(n) in NOT_WORDS
    ]
    negated = bool(turned) or any(low(n) in NOT_WORDS for n in lead)
    dropped = led is not None and low(led) in LEAVING
    if every:
        # "every Friday" and "on Fridays" say when a task runs, unless a negation or a word that
        # leaves it out leads them, as "drop every Friday", or a word that is not about running
        # stands alone beside them, as "nothing on Fridays" or "every Friday off".
        lead_off = negated or dropped or (before == "edge" and bool(odd))
        trail_off = after == "edge" and bool(odd_after)
    else:
        # A day on its own says when it runs beside words about running it, or after a task's
        # words in the plural or with its time, and with no one word after it, as "excluded" in
        # "Fridays excluded".
        later, n = 0, last + 1
        while inside(n) and not tokens[n][3] and later < 2:
            later, n = later + word(n), n + 1
        lead_off = negated or dropped or bool(odd)
        trail_off = bool(odd_after) or later == 1
    if possessive or lead_off or trail_off:
        start, end = first, last
        if lead_off:
            start = min([led, *turned]) if led is not None else (lead or [first])[-1]
        if trail_off:
            end = tail if after == "word" and tail is not None else (trail or [last])[-1]
        return (tokens[start][1], tokens[end][2]), True
    # After a task's words, "every", a plural or the time it runs at, as "every Friday at 9am",
    # says it is a schedule, and only when a word the reader knows starts those words, as
    # "Check" in "Check langgraph Mondays", or a channel does, as "#ops". Code can't place any
    # other, as "nix every Monday".
    start = None if before != "word" or head is None else starts[head]
    channel = start is not None and text[tokens[start][1] - 1 : tokens[start][1]] == "#"
    unknown = start is not None and low(start) not in TASK_HEADS and not channel
    if before == "word" and (unknown or not (every or day.timed or _marked(day.match.group(0)))):
        return (tokens[first][1], tokens[last][2]), False
    return None


def _a_label(text: str, tokens: list[Token], clause_of: list[int], day: _Day) -> bool:
    """Whether a day labels the word after it, as "Monday's tickets" or "the Mon-Fri rota"."""
    clause = clause_of[day.first]

    def inside(n: int) -> bool:
        return 0 <= n < len(tokens) and clause_of[n] == clause

    possessive = text[day.match.end() : day.match.end() + 1] in ("'", "’")
    label = possessive or (inside(day.first - 1) and _low(tokens[day.first - 1][0]) in LABELS)
    return label and any(
        inside(n) and _a_word(tokens[n][0], tokens[n][3]) for n in (day.last + 1, day.run[1] + 1)
    )


@lru_cache(maxsize=64)
def _days_in(text: str) -> tuple[tuple[_Day, bool], ...]:
    """Every day the words name, as `DAY_NAMED` reads one, with whether a filter or a ticket's
    date holds its run of schedule words, as "created on Monday" or "the due date to Friday". A
    day inside a word, as "Mon-Fri" in "2026-Mon-Fri", names none. Kept per request, since its
    readers ask more than once."""
    matches = list(DAY_NAMED.finditer(text))
    if not matches:
        return ()
    tokens = _schedule_tokens(text)
    clause_of = _clause_of(text, [(raw, a, b) for raw, a, b, _ in tokens])
    token_at = {a: n for n, (_, a, _, _) in enumerate(tokens)}
    runs = _runs_of(tokens, clause_of)
    of_run: dict[tuple[int, int], tuple[bool, bool]] = {}
    found: list[tuple[_Day, bool]] = []
    for match in matches:
        first = token_at.get(match.start())
        if first is None:
            continue
        last = first
        while last + 1 < len(tokens) and tokens[last + 1][1] < match.end():
            last += 1
        run = (runs.get(first, (first, first, None))[0], runs.get(last, (last, last, None))[1])
        if run not in of_run:
            timed = CLOCK.search(text, tokens[run[0]][1], tokens[run[1]][2]) is not None
            of_run[run] = (_tied(text, tokens, *run), timed)
        tied, timed = of_run[run]
        frame = runs.get(first, (first, first, None))[2]
        day = _Day(first, last, run, frame is not None and frame < first, timed, match)
        found.append((day, tied))
    return tuple(found)


LEAVE_OUT: Final = EXCLUSIONS | words("skip skips skipping skipped not no non without but never")
"""Words that leave out what follows them, as "except", "skip", "not", "non-" or "but".
"other than" and "apart from" are read as pairs."""
LEAVE_OUT_PAIRS: Final = frozenset({("other", "than"), ("apart", "from")})
STOPS: Final = words("until till stop stops stopping stopped end ends ending ended")
"""Words that end the runs, as "until" in "check langgraph until Friday" or "stop" in "list
tickets due Friday, then stop". A day in their sentence is never a filter's."""
FILTERED: Final = (
    TICKETS
    | frozenset(RELEASE_ROOTS)
    | words("item items entry entries")
    | frozenset(w for v in STATUS_VOCAB.values() for w in v)
    | frozenset(w for v in WHEN_VOCAB.values() for w in v)
    | ASSIGNEE_VOCAB
    | ME_WORDS
    | NOT_UPDATED
    | TICKET_DATES
)
"""Words a filter's word may follow, as "tickets" in "tickets closed on Friday", "touched" in
"nobody touched since Friday" or "me" in "waiting for me since Monday"."""
FILTERS_OWN: Final = (
    frozenset(w for v in STATUS_VOCAB.values() for w in v)
    | frozenset(w for v in WHEN_VOCAB.values() for w in v)
    | NOT_UPDATED
    | TICKET_DATES
    | FILTER_LEADS - words("since from until till by before after")
)
"""A filter's own words, as "touched" in "not touched since Monday"."""


def _left_out_before(tokens: list[Token], clause_of: list[int]) -> list[bool]:
    """For each token, whether a word that leaves something out stands before it in its clause,
    or joins the clause on, as "except" in "except Friday's check", "leave" in "leave out
    Friday's check" or "but" in "but we are closed on Fridays". One right before a filter's own
    word is the filter's, as "not" in "not touched since Monday"."""
    found: list[bool] = []
    seen = False
    for n, (raw, _, _, _) in enumerate(tokens):
        if n and clause_of[n - 1] not in (clause_of[n], -1):
            seen = False
        found.append(seen)
        low = _low(raw)
        pair = n > 0 and (_low(tokens[n - 1][0]), low) in LEAVE_OUT_PAIRS
        prefix = "-" in low and low.partition("-")[0] in LEAVE_OUT
        filters = low in NEGATIONS and n + 1 < len(tokens) and _low(tokens[n + 1][0]) in FILTERS_OWN
        leaves = pair or prefix or low in LEAVE_OUT or low in LEAVING
        seen = seen or (leaves and not filters)
    return found


def _sentences_stopped(text: str, tokens: list[Token]) -> list[bool]:
    """For each token, whether its sentence holds a word that ends the runs, as "then stop"."""
    sentence = [0] * len(tokens)
    for n in range(1, len(tokens)):
        ends = CLAUSE_END.search(text[tokens[n - 1][2] : tokens[n][1]])
        sentence[n] = sentence[n - 1] + bool(ends and ends.group(0).strip(","))
    stopped = {sentence[n] for n, (raw, _, _, _) in enumerate(tokens) if _low(raw) in STOPS}
    return [at in stopped for at in sentence]


def _tied_whole(text: str, tokens: list[Token], clause_of: list[int], day: _Day) -> bool:
    """Whether the day's run, which `_tied` holds, is held as a whole phrase: by a ticket's
    date, as "due Friday" or "the deadline is Friday", or by a filter's word right after what
    it filters, as "tickets closed on Friday", "tickets in MOCK opened on Tuesday" or "tickets
    not updated from Monday to Friday". A filter's
    word after anything else, as "closed" in "the office is closed on Fridays", holds nothing,
    and "until" or "till" never does."""
    first = day.run[0]
    clause = clause_of[day.first]

    def low(n: int) -> str:
        return _low(tokens[n][0]) if 0 <= n < len(tokens) and clause_of[n] == clause else ""

    def joined(a: int, b: int) -> bool:
        return CLAUSE_MARK.search(text[tokens[a][2] : tokens[b][1]]) is None

    lead = first if low(first) == "by" else first - 1
    if low(lead) not in FILTER_LEADS or low(lead) in TICKET_DATES:
        return True
    if low(lead) in STOPS:
        return False
    n = lead - 1
    while low(n) and (low(n) in ("in", *NEGATIONS) or PROJECT_KEY.fullmatch(tokens[n][0])):
        if not joined(n, n + 1):
            return False
        n -= 1
    return low(n) in FILTERED and joined(n, n + 1)


@lru_cache(maxsize=64)
def _days_held(text: str) -> tuple[tuple[tuple[int, int], bool], ...]:
    """Where every day the words name stands, with whether a filter, a ticket's date or a label
    holds it, as "tickets created on Monday", "the due date to Friday" or "Monday's tickets". A
    day is held only where `_tied` or a label holds it, and only as a whole phrase
    (`_tied_whole`). A word that leaves something out before it in its clause undoes the hold,
    as "except" in "except Friday's check", and so does a word that ends the runs in its
    sentence, as "then stop". Kept per request."""
    days = _days_in(text)
    if not days:
        return ()
    tokens = _schedule_tokens(text)
    clause_of = _clause_of(text, [(raw, a, b) for raw, a, b, _ in tokens])
    left_out = _left_out_before(tokens, clause_of)
    stopped = _sentences_stopped(text, tokens)
    return tuple(
        (
            day.match.span(),
            not left_out[day.first]
            and not stopped[day.first]
            and (
                (tied and _tied_whole(text, tokens, clause_of, day))
                or _a_label(text, tokens, clause_of, day)
            ),
        )
        for day, tied in days
    )


WEEK: Final = tuple(DAY_NAMES.split("|"))
WEEKDAYS: Final = frozenset(WEEK[:5])


def _runs_on(key: str) -> frozenset[str]:
    """The days of the week a run day runs on: all seven for every day, Monday to Friday for
    every weekday, and a day of the week itself."""
    return {"every_day": frozenset(WEEK), "weekdays": WEEKDAYS}.get(key, frozenset({key}))


def _may_fall_on(said: str) -> frozenset[str]:
    """The days of the week a day the words name may fall on: a day itself, every day of a
    range, Monday to Friday for a weekday, Saturday and Sunday for the weekend, and any day for
    a holiday."""
    if (span := DAY_RANGE.fullmatch(said)) is not None:
        first, last = (WEEK.index(day_key(m.group(1))) for m in DAY.finditer(span.group(0)))
        return frozenset(WEEK[(first + n) % 7] for n in range((last - first) % 7 + 1))
    if (day := DAY.fullmatch(said)) is not None:
        return frozenset({day_key(day.group(1))})
    if re.fullmatch(r"week ?days?", said, re.IGNORECASE):
        return WEEKDAYS
    if re.fullmatch(r"weekends?", said, re.IGNORECASE):
        return frozenset(WEEK[5:])
    return frozenset(WEEK)


def _day_unread(text: str, days: set[str], read: dict[int, int], timed: bool) -> bool:
    """Whether the words name a day the reader didn't read as the day it runs, `read` by where
    each read day starts and ends, so it is asked. With no run day of their own, any such day is
    asked, but one a filter, a ticket's date or a label holds beside a time of their own. Beside
    a run day, one that may fall on a day the workflow runs is asked, as "Fridays" in "every day
    at 9am, check langgraph except Fridays", and one it never runs on is left to the filter it
    may be, as "Mondays" in "Every Friday at 9am, list tickets we skip on Mondays"."""
    runs_on = frozenset[str]().union(*(_runs_on(key) for key in days))
    for (start, end), held in _days_held(text):
        if (held and (timed or bool(days))) or read.get(start, -1) >= end:
            continue
        if not days or _may_fall_on(text[start:end]) & runs_on:
            return True
    return False


type Stop = Literal["edge", "run", "verb", "word"]


def _talk_beside(
    text: str, tokens: list[Token], clause_of: list[int], at: int, step: int
) -> tuple[list[int], Stop, int | None]:
    """The talk beside a run of schedule words, walking from `at` by `step`, and what ends it:
    the clause's edge or a mark such as a dash, another run or a number, which the
    schedule's own readers judge, a verb that runs it (before the run only), or a word of the
    task, with where that stands."""
    talk: list[int] = []
    clause = clause_of[at - step]
    n = at
    while 0 <= n < len(tokens) and clause_of[n] == clause:
        gap = text[tokens[min(n, n - step)][2] : tokens[max(n, n - step)][1]]
        if CLAUSE_MARK.search(gap) is not None:
            break
        raw, _, _, scheduled = tokens[n]
        if scheduled or any(c.isdigit() for c in raw):
            return talk, "run", n
        if step < 0 and _low(raw) in RUN_VERBS:
            return talk, "verb", n
        if _a_word(raw, scheduled):
            return talk, "word", n
        talk.append(n)
        n += step
    return talk, "edge", None


@lru_cache(maxsize=64)
def when_said(words: str) -> WhenSaid:
    """The run time the words give, read from what a schedule holds, as the card's schedule row
    is. Only the schedule's own words count: a phrase with "every", "daily" or a day in the
    plural, a clause that speaks only of when it runs, as "Run it at 9am", and a time "at"
    names when nothing else does. A day in a filter, a label or a name, as "tickets created on
    Monday" or "the Mon-Fri rota", is never the day it runs. When code can't take the day or the
    time whole, it is asked, never kept from before: a schedule it can't hold or a day left out,
    as "every other Friday" or "skip Fridays", two days or two times, a time another phrase
    could give, a bound, a time that is not exact, a bare hour, or one said in words code
    doesn't read, as "the afternoon" or "half past nine". When the words name a day or a time
    only where no schedule stands, it is asked too, so a change never keeps the run time from
    before beside it. A day or a time tied to a filter or a ticket's date, as "set the due date
    to Friday at 5pm", is never the run time, and a day the schedule's words name without saying
    to run on it, as "drop Fridays" or "Fridays off", is left out, so it is asked. Any other day
    they name that is not the day it runs is asked, as "Mondays" in "check langgraph except
    Mondays", unless a filter, a ticket's date or a label holds it beside a time or a day of
    their own, or the day it runs never falls on it, as "Mondays" beside "Every Friday at 9am".
    A filter or a label holds a day only as a whole phrase, with no word that leaves something
    out before it in its clause, so "except Friday's check" is asked, and so is a filter's day
    in a sentence that ends the runs, as "until Friday" or "then stop". A word that looks like
    a day or time off after "except", "not", "drop", "only" or the like is asked too, as "except
    PH", "except Firday", "except 25 Dec", "except EOM" or "PH excluded", and so is a stretch of
    time or a count of days they leave out, as "except when I'm off", "skip the code freeze" or
    "except for 2 days", and days after "on" that look like days, as "on business days". A day
    right after such a word is left out even where it stands as the day it runs, as "run at 10am
    barring Fridays". This holds with no schedule of their own too, so a change such as "check
    langgraph except PH" never keeps the run time from before. Any other word they leave out is
    a filter's, as "except langchain", and so is a condition, as "post only when there is a new
    release"."""
    own = _own(words)
    unheld = [
        p
        for p in own
        if _names_a_schedule(words[p.start : p.end]) and _unheld(words[p.start : p.end], words)
    ]
    off = own_left_out(words)
    phrases = _phrases(words)
    texts = [words[p.start : p.end] for p in phrases]
    chosen = [n for n, p in enumerate(phrases) if p in own]
    named = [_when(text, words) for text in texts]
    days = {day.key for n in chosen for day in named[n][0]}
    read = {
        phrases[n].start + d.start: phrases[n].start + d.end for n in chosen for d in named[n][0]
    }
    said = [(phrases[n].start, phrases[n].end) for n in chosen]
    day_like = _left_out_day_like(words, days, read, said)
    if off or unheld:
        return WhenSaid(None, None, True, True, _joined_spans([*off, *day_like]))
    # A time another phrase names could be the run time, unless a filter or a ticket's date
    # holds it, as "created" in "tickets created at 9am" or "5pm deadlines", which is never the
    # run time.
    tokens = _schedule_tokens(words)
    doubt = [
        n
        for n, p in enumerate(phrases)
        if n not in chosen and _timed(texts[n]) and not _tied(words, tokens, p.first, p.last)
    ]
    beside = {day.key for n in doubt for day in named[n][0]} - days
    often = {_often(m) for n in chosen for m in FREQUENCY.finditer(texts[n])}
    reasons = {
        c.reason for n in chosen for c in _own_clashes(words, (phrases[n].start, phrases[n].end))
    }
    unchosen = not chosen and bool(phrases)
    day_asked = (
        len(days) > 1
        or (unchosen and any(found for found, _ in named))
        or bool(beside)
        or len(often) > 1
        or bool(reasons & {"one_day", "one_frequency"})
        or UNREAD_DAY.search(words) is not None
        or bool(_unplaced(words))
        or _day_unread(words, days, read, bool(chosen))
        or bool(day_like)
    )
    day = None if day_asked or not days else next(iter(days))
    times = {time.key for n in chosen for time in named[n][1]}
    at = next(iter(times)) if len(times) == 1 else None
    time_asked = (
        len(times) > 1
        or (unchosen and any(found for _, found in named))
        or any(named[n][1] for n in doubt)
        or "one_time" in reasons
        or inexact_time(words)
        or RELATIVE_TIME.search(words) is not None
        or (CLOCK.search(words) is None and (UNREAD_TIME.search(words) or VAGUE_TIME.search(words)))
        or (not times and UNREAD_HOUR.search(words) is not None)
        or any(
            named[n][1] and not _whole_time(texts[n], words, phrases[n].talk and phrases[n].changes)
            for n in chosen
        )
        or (at is not None and re.fullmatch(r"\d{2}:\d{2}", at) is None)
    )
    return WhenSaid(day, None if time_asked else at, day_asked, bool(time_asked), day_like)


def _clash_note(clashes: list[Clash]) -> str:
    """The note on a schedule asked for because it names two of a kind, cut to fit a note."""
    return plain(_clash_notes(clashes), NOTE_LIMIT)


def _clash_notes(clashes: list[Clash]) -> str:
    return " ".join(
        {"one_day": ONE_DAY, "one_time": ONE_TIME, "one_frequency": ONE_FREQUENCY}[c.reason].format(
            " and ".join(f'"{choice}"' for choice in c.choices)
        )
        for c in clashes
    )


def _time_lost(schedule: str | None, shown: str, text: str, said: tuple[int, int] | None) -> bool:
    """Whether a time was written for the schedule, by the person or the model, but the row
    reads none. Such a row is never marked understood: the card asks for the time again."""
    if CLOCK.search(shown) is not None:
        return False
    run = _schedule_run(text, said)
    stretch = text[run[0] : run[1]] if run is not None else ""
    return any(TIME_SHAPED.search(w) for w in (stretch, visible_words(schedule) or "", shown))


def _time_not_read(shown: str, text: str) -> UnderstoodRow:
    """The row for a schedule whose time could not be read. Its day words stay when they are
    the person's own, so the card asks only for the time, and nothing after them does, such as
    a dangling "at"."""
    tokens = shown.split()
    days = [i for i, t in enumerate(tokens) if _low(t.strip(",.")) in SCHEDULE_WORDS]
    day = " ".join(tokens[: days[-1] + 1]).strip(" ,") if days else ""
    theirs = bool(day) and all(said_in(w, text) for w in re.findall(r"\w+", day))
    return UnderstoodRow(
        kind="schedule",
        text=plain(day[:1].upper() + day[1:], TEXT_LIMIT) if theirs else "",
        state="missing",
        note=NO_TIME_READ,
    )


HELD_WORDS: Final = words(
    "monday tuesday wednesday thursday friday saturday sunday mondays tuesdays wednesdays "
    "thursdays fridays saturdays sundays mon mons tue tues wed thu thur thurs fri fris sat sats "
    "sun suns every each day daily weekday weekdays week weekly once "
    "a an on at in the and from to through thru till until am pm o'clock morning afternoon evening "
    "night noon midday midnight"
)
"""The words a schedule holds, and no others: one or more days, every day, every weekday or once
a week, and a time."""


UNREAD_TIME: Final = re.compile(
    r"(?:\bat\s+)?\b\d{1,2}[:.]\d{1,2}\b|\bat\s+\d+\b|\b\d{1,2}\s*o['\u2019]?clock\b", re.IGNORECASE
)
"""A time written for the schedule, read or not, as "24:00", "16.00", "at 1600" or "10
o'clock"."""


JOINING: Final = words("before after by of or per start end beginning first last eod")
"""Schedule words that say nothing about how often on their own, as "before" in "before the
weekly meeting". They end a schedule's own words."""


def _unheld_words(phrase: str, context: str | None = None) -> list[str]:
    """The words of a schedule phrase the schedule doesn't hold. A time, read or not, a bound on
    one, as "before 5pm", and a time that is not exact are the time's own question, so they are
    set aside first. A day range holds only as Monday to Friday, every weekday, written whole
    or short, as "Mon-Fri". The weekend left out holds beside every day anywhere in `context`,
    the whole request, when it is all they leave out, so "Daily at 9am, except weekends" is
    every weekday and "Daily at 9am, except weekends and holidays" is not."""
    ranges = [m.group(0) for m in DAY_RANGE.finditer(phrase)]
    unheld = [r for r in ranges if not _monday_to_friday(r)]
    held = [DAY_RANGE] + ([NOT_WEEKENDS] if _weekend_alias(context or phrase) else [])
    patterns = (
        *held,
        BOUND_TIME,
        RELATIVE_TIME,
        APPROXIMATE,
        VAGUE_TIME,
        CLOCK,
        UNREAD_TIME,
        TIME_OF_DAY,
    )
    for pattern in patterns:
        phrase = pattern.sub(" ", phrase)
    return unheld + [
        t
        for t, _, _ in _request_tokens(phrase)
        if _low(t) not in HELD_WORDS or (t.isupper() and _low(t) in SHORT_FORMS)
    ]


def _unheld(phrase: str, context: str | None = None) -> bool:
    """Whether a schedule phrase asks for one it can't hold: a word it doesn't hold that is about
    how often, as "other", "month" or "except". A joining word alone, as "before the weekly
    meeting", leaves the schedule as it is, and comes back on its own."""
    found = _unheld_words(phrase, context)
    spans = [m.group(0).casefold() for m in SCHEDULE_PHRASE.finditer(phrase)]
    return any(
        _low(w) not in JOINING or any(_low(w) in span.split() for span in spans) for w in found
    )


def _all_held(phrase: str, context: str | None = None) -> bool:
    """Whether every word of a schedule phrase is one the schedule holds."""
    return not _unheld_words(phrase, context)


RUN_TIME_LEADS: Final = SCHEDULE_WORDS - words("noon midday midnight") | words("at")
"""The word before a time that makes it the time a schedule runs at: "at", or a day word beside
it, as "Every Friday 16:00" or "Friday morning 9am"."""
TRAILING: Final = words("and or in on the to from by before after of a an per at every each")


def _their_schedule(text: str, said: tuple[int, int] | None) -> str | None:
    """The person's own schedule words, when code reads them whole: a run time "at" leads or a
    day word stands beside, or no time at all, and no time it can't read. None otherwise, so a
    bound such as "before 5pm" or a time like "16.00" is asked for, never taken."""
    run = _schedule_run(text, said)
    if run is None:
        return None
    stretch = text[run[0] : run[1]]
    clocks = list(CLOCK.finditer(stretch))
    if BOUND_TIME.search(stretch) or (not clocks and TIME_SHAPED.search(stretch)):
        return None
    if (clocks and _run_time(stretch, clocks[0]) is None) or not _all_held(stretch, text):
        return None
    if APPROXIMATE.search(stretch) or (VAGUE_TIME.search(stretch) and not clocks):
        return None
    return _trimmed(stretch) or None


def _trimmed(stretch: str) -> str:
    """The schedule words without joining words at either end, as a dangling "at" or "and"."""
    tokens = _request_tokens(stretch)
    while tokens and _low(tokens[-1][0]) in TRAILING:
        tokens.pop()
    while tokens and _low(tokens[0][0]) in words("and or then"):
        tokens.pop(0)
    return stretch[tokens[0][1] : tokens[-1][2]] if tokens else ""


def _run_time(
    stretch: str, clock: re.Match[str], leads: frozenset[str] | None = None
) -> str | None:
    """The time as written when it is the time a schedule runs at: "at" leads it, or a day word
    stands before it, as "Every Friday 16:00". None for any other, so it is asked."""
    if clock.group("bare") is not None:
        said = clock.group(0)
        return clock.group("bare") if said.casefold().startswith("at") else None
    lead = [t for t, _, _ in _request_tokens(stretch[: clock.start()])]
    known = RUN_TIME_LEADS if leads is None else leads
    return None if lead and _low(lead[-1]) not in known else clock.group(0)


def _time_asked(shown: str, text: str, note: str) -> UnderstoodRow:
    """The row for a schedule whose time is a bound, as "before 5pm", or not exact, as "9am or
    so": the person's day words, and the time asked for, with why."""
    return _time_not_read(shown, text).model_copy(update={"note": note})


BY_HAND: Final = re.compile(
    r"\bonly\s+when\s+I\s+ask\b|\b(?:only\s+)?when\s+I\s+run\s+it\b|\bon\s+demand\b"
    r"|\b(?:only\s+)?run(?:\s+it)?\s+manually\b|\bonly\s+manually\b",
    re.IGNORECASE,
)
"""Words that ask for no schedule, so it runs only when someone presses Run now. An allow-list,
which the Portal reads the schedule row with too: any other words for when it runs are asked,
never guessed. "manually" counts only for running it, so "tickets we triaged manually" is not
one."""
NOT_BY_HAND: Final = re.compile(
    r"\b(?:not|never|nobody|no\s+one|without)\b|n['’]t\b", re.IGNORECASE
)
"""A no in the clause turns the words round, as "so I don't have to run it manually"."""


def _by_hand(schedule: str | None, text: str) -> Rendered | None:
    """The schedule row of a request that asks to run only by hand, in its own words, whatever
    the model read. None while the request names a schedule besides, which stays the schedule or
    is asked: Run now starts any workflow. Words beside a no in their clause are not a choice."""
    names_one = any(own and _a_schedule_word(raw) for raw, _, _, own in _schedule_tokens(text))
    if names_one or schedule_stretch(schedule, text) is not None or how_often(text) is not None:
        return None
    clauses = clauses_of(text)
    for found in BY_HAND.finditer(text):
        a, b = next(((a, b) for a, b in clauses if a <= found.start() < b), found.span())
        if NOT_BY_HAND.search(text[a:b]):
            continue
        said = found.group(0)
        row = UnderstoodRow(
            kind="schedule",
            text=plain(said[:1].upper() + said[1:], TEXT_LIMIT),
            state="understood",
        )
        return Rendered(row, frozenset(_low(t) for t, _, _ in _request_tokens(said)), found.span())
    return None


def render_schedule(schedule: str | None, text: str) -> Rendered:
    """The schedule row: the model's words kept to schedule words only, with a time the request
    never said asked for, not filled in, and a day it never said shown as a guess. Two days or
    two times in the request's schedule are asked for, never the first one picked, and so is a
    time that only bounds the run, as "before 5pm". When the model leaves out or rewrites the
    time or day the person wrote, the row is the person's own words, never the model's day with
    their time. With no schedule read, the row is missing and asks for one, and the request's
    own schedule words stand under it, so they are never a can't of another kind."""
    if (by_hand := _by_hand(schedule, text)) is not None:
        return by_hand
    kept = _kept(schedule)
    shown = re.sub(r"(?:\s+(?:and|or))+$", "", " ".join(kept).strip(" ,"), flags=re.IGNORECASE)
    said = _schedule_span(text, shown)
    run = _schedule_run(text, said)
    later = Later([], None, None) if run is None else _later(text, run)
    left = own_left_out(text)
    # A later clause that speaks only of when it runs, or a day left out, as "but skip Fridays",
    # is the schedule's, so its words never come back as a part of another kind: the schedule
    # asks about it or takes it.
    also = later.also or (left[0] if left else None)
    # The words that leave the day out are the schedule's to ask about too, as "unless" in
    # "unless it's a Friday", so they get the schedule's one cross.
    leaving = frozenset(_low(t) for a, b in left[:1] for t, _, _ in _request_tokens(text[a:b]))
    explained = _schedule_explained(text) | (SCHEDULE_TALK if also else frozenset[str]()) | leaving

    def rendered(row: UnderstoodRow, at: tuple[int, int] | None) -> Rendered:
        return Rendered(row, explained, at, also)

    clashes = _clashes(text, said)
    if clashes:
        return rendered(missing_row("schedule", _clash_note(clashes)), said)
    stretch = "" if run is None else text[run[0] : run[1]]
    if stretch and _unheld(stretch, text):
        quoted = plain(_trimmed(stretch), NOTE_LIMIT - len(NOT_HELD.format("")))
        return rendered(missing_row("schedule", NOT_HELD.format(quoted)), said)
    if left:
        # A day left out anywhere, as "but skip Fridays", is never run on: the card asks.
        quoted = plain(text[left[0][0] : left[0][1]], NOTE_LIMIT - len(NOT_HELD.format("")))
        return rendered(missing_row("schedule", NOT_HELD.format(quoted)), said)
    if _unplaced(text):
        # A day code can't place, as "Check releases Monday", is asked, and the task's words
        # are never crossed as a schedule it can't hold.
        return rendered(missing_row("schedule"), said)
    if not any(_low(t) in SCHEDULE_WORDS or CLOCK_TOKEN.match(_low(t)) for t in kept):
        return rendered(missing_row("schedule"), said)
    if (bound := BOUND_TIME.search(stretch)) is not None:
        note = NOT_A_RUN_TIME.format(plain(bound.group(0), SAID_LIMIT))
        return rendered(_time_asked(shown, text, note), said)
    vague = APPROXIMATE.search(stretch) or (
        VAGUE_TIME.search(stretch) if CLOCK.search(stretch) is None else None
    )
    if vague is not None:
        note = NOT_EXACT.format(plain(vague.group(0), SAID_LIMIT))
        return rendered(_time_asked(shown, text, note), said)
    theirs = _their_schedule(text, said)
    if theirs is not None:
        # Their own words, whenever the schedule holds every one of them, so the card never says
        # their words lacked what they hold, whatever the model wrote. A time the model guessed
        # for words with none is asked, keeping their day.
        whole = theirs if later.adds is None else f"{theirs} {later.adds}"
        if (canonical := _canonical(whole, text)) is not None:
            return rendered(canonical, said)
        if later.adds is not None:
            text_ = plain(whole[:1].upper() + whole[1:], TEXT_LIMIT)
            return rendered(UnderstoodRow(kind="schedule", text=text_, state="understood"), said)
        guessed = any(not said_in(time.strip(), text) for time in TIME_OF_DAY.findall(shown))
        if guessed and CLOCK.search(theirs) is None:
            note = NO_TIME_BUT.format(theirs)
            return rendered(_time_asked(theirs, text, note), _schedule_span(text, theirs))
        shown = theirs
        said = _schedule_span(text, shown)
    if any(not said_in(time.strip(), text) for time in TIME_OF_DAY.findall(shown)):
        if CLOCK.search(stretch) is None and TIME_SHAPED.search(stretch):
            return rendered(_time_not_read(shown, text), said)
        return rendered(missing_row("schedule", _no_time_said(shown, text)), said)
    if _time_lost(schedule, shown, text, said):
        return rendered(_time_not_read(shown, text), said)
    guessed = [w for w in re.findall(r"\w+", shown) if w.casefold() in SCHEDULE_WORDS]
    sourced = _find(text, shown) is not None and all(said_in(w, text) for w in guessed)
    row = UnderstoodRow(
        kind="schedule",
        text=plain(shown[:1].upper() + shown[1:], TEXT_LIMIT),
        state="understood" if sourced else "changed",
        note=None if sourced else FILLED_IN,
    )
    return rendered(row, said)


def _canonical(theirs: str, text: str) -> UnderstoodRow | None:
    """Their schedule as the card and the Portal write it, read from their words, when they
    wrote a day in a way the Portal doesn't read: every weekday written another way, as
    "Mon-Fri at 9am", is "Every weekday at 9am", and a short day, as "every Mon at 09:00", is
    "Every Monday at 09:00". None when their words are already so."""
    note = READ_FROM.format(plain(theirs, SAID_LIMIT))
    if weekdays_said(theirs, text):
        clock = CLOCK.search(theirs)
        said = "" if clock is None else re.sub(r"^(?:at|or|and)\s+", "", clock.group(0), flags=re.I)
        at = f" at {said}" if said else ""
        return UnderstoodRow(
            kind="schedule", text=f"Every weekday{at}", state="understood", note=note
        )
    whole = DAY_NAMES.split("|")
    if all(m.group(1).casefold() in whole for m in DAY.finditer(theirs)):
        return None
    written = DAY.sub(
        lambda m: (
            m.group(0)
            if m.group(1).casefold() in whole
            else day_key(m.group(1)).capitalize() + m.group(0)[len(m.group(1)) :]
        ),
        theirs,
    )
    row = plain(written[:1].upper() + written[1:], TEXT_LIMIT)
    return UnderstoodRow(kind="schedule", text=row, state="understood", note=note)


INSTRUCTION: Final = re.compile(
    r"\b(?:instructions?|rules|prompts?|developer\s+mode|pretend|ignore|disregard)\b|"
    r"\b(?:reply|respond|answer|say|repeat)\s+(?:that|with|only|exactly|back)\b",
    re.IGNORECASE,
)
"""Words that tell the Planner what to say or to drop its rules, as "Ignore all previous
instructions" or "Reply that MOCK-77 has been created". They are no task to set up."""


RUNS_BY_ITSELF: Final = re.compile(
    r"\b(?:(?:run|runs|do)\s+(?:it|this|that|them)\s+)?(?:automatically|by\s+itself|on\s+its\s+own|"
    r"on\s+autopilot|hands[-\s]free|in\s+the\s+background)\b|"
    r"\bset\s+(?:it\s+)?and\s+forget(?:\s+(?:about\s+)?it)?\b|"
    r"\b(?:run|runs)\s+(?:it|this|that|them)\b(?=\s+(?:every|each|daily|weekly|monthly|on\s+[A-Za-z]+days?)\b)",
    re.IGNORECASE,
)
"""Words that say the task runs by itself, as every workflow does on its schedule: "run it
automatically", "set and forget". They name no person and no yes, so a write beside them still
waits for one, and any word that does name one still comes back."""


def without_runs_by_itself(words: str) -> str:
    """The words less those that say the task runs by itself, as "set and forget"."""
    return " ".join(RUNS_BY_ITSELF.sub(" ", words).split())


def instructs_the_planner(words: str) -> bool:
    return INSTRUCTION.search(words) is not None


def only_schedule_words(words: str) -> bool:
    """Whether every word that isn't filler is a schedule's, as "Every Friday at 9am"."""
    content = [t for t, _, _ in _request_tokens(words) if _low(t) not in FILLER]
    return bool(content) and all(_schedule_token(t) for t in content)


def polite(words: str) -> bool:
    """Whether the words ask for nothing: thanks, please, "no problem" or "without fail"."""
    rest = POLITE_PHRASE.sub(" ", words)
    return all(_low(t) in POLITE for t, _, _ in _request_tokens(rest))


def _clause_ends(text: str) -> list[tuple[int, int]]:
    """Where clauses end, never inside the days a schedule leaves out, so "except weekends and
    holidays" or "except weekends, holidays" stays one part."""
    joins = [
        (m.start(), m.end()) for m in JOIN.finditer(text) if not _schedule_token(m.group("next"))
    ]
    left = [m.span() for m in LEFT_OUT.finditer(text)]
    ends = [(m.start(), m.end()) for m in CLAUSE_END.finditer(text)] + joins
    return sorted(end for end in ends if not any(a < end[0] < b for a, b in left))


def clauses_of(text: str) -> list[tuple[int, int]]:
    """Each clause of the request, trimmed. A clause ends at a comma, a full stop or other
    punctuation, or at "and", "then", "but", "also" or "plus", except inside a schedule, so
    "every Monday and Friday at 9am" stays one clause, and between two lone words, so "set and
    forget" stays one too."""
    return list(_clauses(text))


@lru_cache(maxsize=64)
def _clauses(text: str) -> tuple[tuple[int, int], ...]:
    """Kept per request, since each of its readers asks."""
    found: list[tuple[int, int]] = []
    at = 0
    for start, end in [*_clause_ends(text), (len(text), len(text))]:
        clause = trim(text, at, start)
        lead = LEADING_JOIN.match(text, clause[0], clause[1])
        if lead is not None:
            clause = trim(text, lead.end(), clause[1])
        if clause[0] < clause[1]:
            if found and _joined_words(text, found[-1], clause):
                clause = (found.pop()[0], clause[1])
            found.append(clause)
        at = max(at, end)
    return tuple(found)


def _joined_words(text: str, before: tuple[int, int], after: tuple[int, int]) -> bool:
    """Whether two clauses are one word each with only a joining word between them."""
    lone = all(len(_request_tokens(text[a:b])) == 1 for a, b in (before, after))
    return lone and CLAUSE_END.search(text[before[1] : after[0]]) is None


def _clause_of(text: str, tokens: list[tuple[str, int, int]]) -> list[int]:
    """The index of the clause each token stands in, or -1 for a joining word between two."""
    clauses = clauses_of(text)
    return [
        next((n for n, (a, b) in enumerate(clauses) if a <= start < b), -1)
        for _, start, _ in tokens
    ]


def trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and not text[start].isalnum():
        start += 1
    while end > start and not text[end - 1].isalnum():
        end -= 1
    return start, end


def _asks_for_a_change(words: str) -> bool:
    """Whether the words order a change themselves, as "flag the new ticket", "and set their
    priority" or "email me a copy". A change verb that is not an order, as "my call" or "is set
    to Staging", is not one."""
    return commands_a_change(words) or (starts_with_a_verb(words) and bool(change_verbs_in(words)))


def _overlaps(said: tuple[int, int] | None, run: tuple[int, int]) -> bool:
    return said is not None and run[0] < said[1] and run[1] > said[0]


def _kind_of(
    text: str, start: int, end: int, run: tuple[int, int], said: Said, beside: RowKind | None
) -> RowKind | None:
    """The part the words are, judged on the words no structure explains in them (`run`):
    inside the model's quote for the search, what to look for; schedule words only, the
    schedule; an order for a change, the do part; else the part the place's quote covers, the
    part whose words they stand beside, or the part a quote covers. The model's quote for the
    ticket often covers the whole request, so it decides last. Words that still fit no part
    are what to look for when they name tickets, else None."""
    look = said.get("look_for")
    if look is not None and look[0] <= start and end <= look[1]:
        return "look_for"
    content = [t for t, _, _ in _request_tokens(text[start:end]) if _low(t) not in FILLER]
    if content and all(_schedule_token(t) for t in content):
        return "schedule"
    if _asks_for_a_change(text[run[0] : run[1]]):
        return "do"
    if _overlaps(said.get("where"), run):
        return "where"
    # Unread words beside a schedule are the schedule's only when they are schedule words.
    unread = [t for t, _, _ in _request_tokens(text[run[0] : run[1]])]
    if beside is not None and (beside != "schedule" or any(map(_schedule_token, unread))):
        return beside
    if _overlaps(said.get("do"), run):
        return "do"
    if _overlaps(said.get("look_for"), run) or any(_low(t) in TICKETS for t in content):
        return "look_for"
    return None


BESIDE_FIRST: Final[tuple[RowKind, ...]] = ("look_for", "do", "where", "schedule")
"""Which part a word two structures explain belongs to, as "tickets" in "the SUP tickets with
more than 10 comments", which the search and the new ticket both explain."""


def _beside(
    clause_of: list[int], parts_at: dict[int, set[RowKind]], first: int, last: int
) -> RowKind | None:
    """The part whose words the unexplained words from token `first` to `last` stand beside in
    their clause: the nearest word a structure explains before them, else after them, as
    "tasks" before "10 hours logged" in "the OPS tasks with over 10 hours logged"."""
    for at in (*range(first - 1, -1, -1), *range(last + 1, len(clause_of))):
        if clause_of[at] == clause_of[first] and parts_at.get(at):
            return next(k for k in BESIDE_FIRST if k in parts_at[at])
    return None


def negated(text: str) -> bool:
    """Whether the words say no to something, as "don't ping me" or "run it without me"."""
    return NEGATED.search(text) is not None


def names_a_yes(text: str) -> bool:
    """Whether the words name a yes, or a person left out of one."""
    text = FROM_ME.sub(" ", text)
    if A_YES.search(text) is not None or NOBODY.search(text) is not None:
        return True
    return SOMEONE.search(text) is not None and NEGATED.search(text) is not None


STATEMENT: Final = re.compile(
    r"\b(?:can|could|will|would|shall|should|may|might|must|is|are|was|were)\b|n't\b",
    re.IGNORECASE,
)


def a_statement(text: str) -> bool:
    """Whether the words are a statement about someone or something rather than an order:
    "the change board can catch up on it" has a modal after its first word."""
    first = TOKEN.search(text)
    return first is not None and STATEMENT.search(text[first.end() :]) is not None


def names_a_person(text: str, start: int, end: int) -> bool:
    """Whether the request's words from `start` to `end` name another person, a role or a
    group as someone who acts: one of `SOMEONE`, or a capitalised word that is not the
    request's first word, a project key, a system, or a word a structure could explain, framed
    as `NAMED_ACTOR` says. A person left out, as "without anyone", is `names_a_yes`'s."""
    for match in NAMED_ACTOR.finditer(text[start:end]):
        name = match.group("before") or match.group("after")
        if SOMEONE.fullmatch(name) is not None:
            return True
        if not NAME.fullmatch(name):
            continue
        at = start + match.start(match.lastgroup or "after")
        if at == 0 or name.casefold() in KNOWN_WORDS or name.casefold() in SYSTEMS:
            continue
        return True
    return False


KNOWN_WORDS: Final = (
    FILLER
    | SCHEDULE_VOCAB
    | SEARCH_VOCAB
    | REVIEW
    | STILL
    | ME_WORDS
    | ASSIGNEE_VOCAB
    | DAYS_VOCAB
    | TOPIC_VOCAB
    | CREATE_VOCAB
    | PLACE_VOCAB
    | frozenset(w for v in STATUS_VOCAB.values() for w in v)
    | frozenset(w for v in WHEN_VOCAB.values() for w in v)
    | frozenset(w for v in SAYS_VOCAB.values() for w in v)
    | frozenset(w for v in SHOWS_VOCAB.values() for w in v)
    | frozenset(TYPE_BY_FORM)
)
"""Every word a structure could explain, so a capitalised one of them at a clause's front
("Create", "List", "Every") is never read as a name."""
TASK_HEADS: Final = (
    KNOWN_WORDS
    | frozenset(
        word
        for ability in ABILITIES
        for said in (ability.verbs, ability.makes, ability.about)
        for word in said or ()
    )
    | words(
        "post posted send sent share publish remind notify alert alerts message email emailed "
        "ping tell know ready close archive sync backup clean schedule follow flag escalate chase "
        "nudge grab happen occur trigger repeat fire kick changelog changelogs"
    )
)
"""Words that may start a task's words before the day it runs on, as "Check" in "Check langgraph
Mondays". They are every word a structure could explain, what the capability registry says a
task does, makes or is about, and words that send its result, as "sent" in "have the report
sent every Monday", name a task of their own or say that it runs. Any other word there may
leave the day out, as "nix" in "nix every Monday", so the day is asked. "clear", "block",
"free" and "end" stay off, because each can leave a day out."""
LINKS: Final = words(
    "the a an any all some this that these those our your their my its his her on in at during "
    "over for of from until till through between before after since by to with when while if"
)
"""Words that link what a word leaves out to the rest, as "on" in "except on Fridays"."""
LIST_JOINS: Final = words("and or nor")
WHILE: Final = words("when whenever while during")
"""Words that start a stretch of time or a condition. After a word that leaves something out,
they leave out time off when the words after them look like a day or time off, as "except when
I'm off" or "not during Hari Raya", and a condition otherwise, as "only when there is a new
release"."""
AWAY: Final = words(
    "away leave sick mc pto al reservist overseas abroad travelling traveling unwell sabbatical "
    "maternity paternity ph"
)
"""Time off in a stretch after "when", "while" or "during", as "away" in "skip it while I'm
away", "MC" in "except when I'm on MC" or "PTO", and "ph" in any case."""
AWAY_PHRASES: Final = frozenset(
    {
        ("in", "camp"),
        ("on", "course"),
        ("on", "training"),
        ("out", "of", "office"),
        ("day", "off"),
        ("days", "off"),
        ("time", "off"),
        ("business", "hours"),
        ("office", "hours"),
        ("working", "hours"),
    }
)
"""Time off in a stretch said in more than one word, as "in camp", "out of office", "time
off" or "business hours"."""
AWAY_PHRASE_ENDS: Final = frozenset(phrase[-1] for phrase in AWAY_PHRASES)
STRETCH_ENDS: Final = words("week weeks window windows")
"""Words that make a stretch they end time off, as "release week" or "the maintenance
window"."""
A_PERSON_IS: Final = frozenset(
    {("i'm",), ("we're",), ("they're",), ("i", "am"), ("we", "are"), ("they", "are")}
)
PEOPLE: Final = words(
    "boss bosses manager managers lead leads team teams approver approvers supervisor supervisors"
)
"""A person before "out" or "off" that makes it time off, as "I'm out", "we are off" or "the
boss is out", never "a new version is out", "LangGraph is out" or "the alerts are off"."""
DAYISH: Final = (SCHEDULE_VOCAB - LINKS - LIST_JOINS) | words(
    "today tonight tomorrow yesterday next holiday holidays"
)
"""Words that may name a day or a stretch of days, as "week", "first", "end" or "tomorrow"."""
NOT_A_DAY: Final = (
    KNOWN_WORDS
    | TASK_HEADS
    | NOT_WORDS
    | NOT_A_TASK
    | CAUSING
    | DOERS
    | MODALS
    | LEAVE_OUT
    | frozenset(SYSTEMS)
    | words("longer anymore more")
) - DAYISH
"""Words the reader knows that name no day: what a structure could explain, what a task does,
makes or is about, the systems it names, talk, and words that turn or leave out what follows
them."""
_SPAN: Final = r"\d+\s*(?:days?|weeks?|fortnights?|months?|years?)\b"
TIME_COUNT: Final = re.compile(rf"\b{_SPAN}", re.IGNORECASE)
"""A count of days or longer, as "2 days" in "except for 2 days", which may leave days out."""
FILTER_COUNT: Final = re.compile(
    rf"\b(?:{'|'.join(sorted(NOT_UPDATED | frozenset(w for v in WHEN_VOCAB.values() for w in v)))})"
    rf"\s+(?:(?:for|in|within|over)\s+)?(?:the\s+)?(?:(?:last|past)\s+)?{_SPAN}|"
    rf"\b(?:than|within)\s+{_SPAN}|\b(?:last|past)\s+{_SPAN}|\b{_SPAN}\s+ago\b",
    re.IGNORECASE,
)
"""A count of days a filter holds, as "no update for 10 days" or "older than 30 days"."""
_MONTHS: Final = (
    r"jan(?:uary)?|feb(?:ruary)?|march|(?-i:M)ar|(?-i:M)ay|apr(?:il)?|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_DATE: Final = r"(?:0?[1-9]|[12]\d|3[01])"
_MONTH: Final = r"(?:0?[1-9]|1[0-2])"
_SLASHED: Final = (
    rf"(?:(?:1[3-9]|2\d|3[01])/{_MONTH}(?:/\d{{2,4}})?|{_DATE}/{_MONTH}/\d{{2,4}}|"
    rf"(?:(?<=\bon\s)|(?<=\bfrom\s)|(?<=\btill\s)|(?<=\buntil\s)){_DATE}/{_MONTH}(?!\s+of\b))"
)
CALENDAR_DAYS: Final = re.compile(
    rf"\b(?:(?<![.:/]){_DATE}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})\b|"
    rf"(?:{_MONTHS})\.?\s+{_DATE}(?:st|nd|rd|th)?(?![\w:/]|\.\d)|"
    rf"(?<![.:/])(?<!version\s)(?!24/7\b){_SLASHED}(?![\w/]|\.\d)|"
    r"(?:month|quarter|year)[\s-]*end\b|end[\s-]+of[\s-]+(?:the[\s-]+)?(?:month|quarter|year)\b|"
    r"eom\b|"
    r"(?:code|change|release|deploy(?:ment)?)[\s-]+freezes?\b|the\s+freeze(?=\s*(?:[,.;:!?)]|$))|"
    r"freeze\s+(?:period|window)s?\b|blackout\s+(?:period|window|date|day)s?\b)",
    re.IGNORECASE,
)
"""A date, the end of a month, a quarter or a year, or a freeze, which may leave days out, as
"25 Dec", "Dec 25", "25/12", "EOM", "quarter end", "the end of the year", "the code freeze" or
"the blackout window", and "the freeze" where it ends its clause, never "the freeze step".
"May" and "Mar" count only with a capital, never "items 2 may need". A day and a month with a
"/" count only with a day of 13 or more, a year, or "on", "from", "till" or "until" before them
and no "of" after, as "25/12", "1/5/2027" or "on 1/5", so a fraction or a score, as "3/4", "2/2
approvals" or "on 3/4 of the boards", is no date. Nor is a version, as "3.12", "v2/1" or
"version 1/2", or "24/7"."""
COUNTS_DAYS: Final = 1
COUNTS_FOR_A_FILTER: Final = 2
"""What a count, a date, month end or a freeze marks where it stands: days that may be left
out, or a filter's count."""
SHORT_LEAVE_OUT: Final = words(
    "exception excl excluded excepted w/o n/a x sans barring outside aside"
)
"""Short and other forms of the words that leave something out, as "excl. PH", "w/o PH", "PH
n/a", "sans PH" or "with the exception of PH"."""
ACTS_ON: Final = LEAVING | words(
    "avoid avoids avoiding ignore ignores ignoring off bar save mute quiet silent disable disabled "
    "nothing rest"
)
"""Words that leave out what follows them straight away, as "drop PH", "avoid PH", "bar PH" or
"quiet on PH", but not a thing they act on, as "pause the React check"."""
OBJECTS: Final = words(
    "the a an any all some this that these those our your their my its his her each every it "
    "them me us you myself yourself ourselves themselves itself"
)
NOT_RUN: Final = NOT_WORDS - NEGATIONS
"""Negated verbs, as "don't" or "won't". One leaves out only running, as "don't run on PH", not
"don't ask me"."""
RUN: Final = words("run runs running")
LEAVES_BEFORE: Final = NOT_RUN | words("off miss")
"""Words that leave out the words right before them at the end of a clause, besides the words
that leave out what follows them, as "PH don't run", "PH off" or "give PH a miss"."""
NEEDED: Final = words("required necessary")
"""Words after a trailing word that leaves something out, as "PH not required"."""
LEAVING_OUT: Final = LEAVE_OUT | SHORT_LEAVE_OUT | ACTS_ON | NOT_RUN
SHORT_EXCEPT: Final = words("ex exc")
"""Short forms of "except" that leave out only a word that looks like a day right after them,
as "ex PH" or "exc. PH", never "ex employees"."""
_LEAVES_WORDS: Final = LEAVING_OUT | LEAVES_BEFORE | SHORT_EXCEPT | {"only", "on"}
LEAVES: Final = re.compile(
    rf"\b(?:{'|'.join(map(re.escape, sorted(_LEAVES_WORDS)))}|other\s+than|apart\s+from)\b",
    re.IGNORECASE,
)
"""A word that leaves something out, keeps only something, or limits the days, as "on" in "on
business days", anywhere in the words."""
DAY_WORDS: Final = (
    frozenset(WEEK)
    | frozenset(f"{day}s" for day in WEEK)
    | SHORT_FORMS
    | words("weekday weekdays weekend weekends")
)
"""Days and the reader's short days, read in any case, as "FRI" or "sat and sun"."""
TWO_LETTER_DAYS: Final = words("mo tu we th fr sa su")
"""Days in two letters, read as days only where "/" or "-" joins them to another day, as
"Sa/Su" or "Mo-Fr", never "we" or "Fr" alone."""
MORE_SHORT_DAYS: Final = words("tues weds thur thurs frid w/e")
"""Short days the reader's own short days leave out, as "Frid", "weds" or "w/e"."""
TIME_OFF: Final = words(
    "holiday holidays hol hols vacation vacations ooo xmas christmas easter eve festive deepavali "
    "diwali vesak thaipusam ramadan january february march april june july august september "
    "october november december"
)
"""Holidays, time off and months, which may fall on any day, as "Xmas", "Deepavali" or
"December". "Hari Raya" and "New Year" are read as pairs."""
TIME_OFF_PAIRS: Final = frozenset({("hari", "raya"), ("new", "year")})
TIME_OFF_NOUNS: Final = words("leave off break")
"""Time off that is also a verb or a word of a verb, as "leave", read as time off only as a
noun, as "on leave", "I'm off" or "the break", never "leave out", "turn off the alerts", "if it
is off" or "break-fix"."""
NOT_DAYS: Final = words("today tonight tomorrow yesterday everyday midday")
"""Words ending in "day" that never name a day left out, as "everyday requests"."""
TYPO_OF: Final = (DAY_WORDS - SHORT_FORMS) | words("holiday holidays")
"""The words a typo may be of, as "Firday", "Thrusdays", "weeknds" or "Holdiays"."""
HOLIDAY_CODE: Final = re.compile(r"(?:PH|CNY|NYE|OOO)(?:['’]?s)?")
"""The codes in capitals for days off, as "PH", "PHs" or "CNY". Any other code, as "UAT" or
"PRs", is a filter's. "ph" or "P.H." is the code only right after a word that leaves it out."""
ORDINAL: Final = re.compile(r"\d{1,2}(?:st|nd|rd|th)")
"""A day of the month, as "the 25th"."""
DATED: Final = DAY_WORDS | words(
    "of week january february march april may june july august september october november "
    "december jan feb mar apr jun jul aug sep sept oct nov dec"
)
"""Words after a day of the month that make it a date, as "Dec" in "25th Dec" or "of" in "the
1st of the month", not "party" in "3rd party ones". A word that leaves it out does too, as
"excluded" in "the 25th excluded"."""
PLACES: Final = words("in into project projects")
"""Words before a project key, as "in SUP"."""
KEYED: Final = TICKETS | words("item items board boards project projects backlog queue")
"""Words after a project key, as "SUP bugs"."""

type CoverKind = Literal["leaves", "only", "join", "link", "while", "known", "kept", "day"]
type Mark = Literal["", ",", "."]


@dataclass(frozen=True)
class _Covered:
    """A word as a word that leaves something out may cover it: one that leaves something out
    ("except"), keeps only something ("only"), joins a list ("and"), links ("on", "the"),
    starts a stretch of time ("when"), a word that names no day, a day the workflow never runs
    on, or a word that may name a day it runs on. `mark` is what stands between it and the word
    before: "," for a comma or "&", "." for any other mark that ends a clause, or "". `low` is
    the word as code reads it, `day` whether `DAY_NAMED` reads it, `own` whether it stands in
    the schedule's own phrase, and `off` whether it is time off in a stretch after "when",
    "while" or "during", as "away", "PTO", "out of office", "out" in "I'm out" or "the boss is
    out", "window" in "the maintenance window", "p" in "p.h." or "freeze" in "the freeze".
    `start` and `end` are where the request writes it."""

    kind: CoverKind
    mark: Mark
    low: str
    day: bool
    own: bool
    off: bool
    start: int
    end: int

    @property
    def talk(self) -> bool:
        """Talk that may stand between a word that leaves something out and what it covers, as
        "as always" in "except, as always, Friday's check"."""
        return self.kind == "known" and self.low in TALK_WORDS


def _pieces(text: str) -> list[tuple[str, int, int]]:
    """The request's words, with a time whole, as "9:30", "w/o", "w/a", "n/o", "n/a" and "w/e"
    whole, and a word with a hyphen that the reader doesn't know split at it, as "non-Fridays"
    or "SAT-MON"."""
    clocks = iter(m.span() for m in CLOCK.finditer(text))
    clock = next(clocks, None)
    found: list[tuple[str, int, int]] = []
    for raw, start, end in _request_tokens(text):
        while clock is not None and clock[1] <= start:
            clock = next(clocks, None)
        if found and text[found[-1][1] : end].casefold() in ("w/o", "w/a", "n/o", "n/a", "w/e"):
            found[-1] = (text[found[-1][1] : end], found[-1][1], end)
        elif clock is not None and clock[0] <= start:
            if not found or found[-1][1:] != clock:
                found.append((text[clock[0] : clock[1]], *clock))
        elif (
            "-" in raw
            and _low(raw) not in NOT_A_DAY
            and not DAY_NAMED.fullmatch(raw)
            and _low(raw).replace("-", "") not in DAY_WORDS
        ):
            found.extend(
                (m.group(0), start + m.start(), start + m.end()) for m in re.finditer(r"[^-]+", raw)
            )
        else:
            found.append((raw, start, end))
    return found


def _left_out_day_like(
    text: str, days: set[str], read: dict[int, int], said: list[tuple[int, int]]
) -> tuple[tuple[int, int], ...]:
    """Each stretch where a word that leaves something out, as "except", "not", "skip", "non-" or
    "but", or one that keeps only something, as "only", covers a word that looks like a day or
    time off, as "PH", "Firday", "payday" or "Xmas", a date, month end or a freeze, as "25 Dec",
    "EOM" or "the code freeze", or a day the workflow may run on, from the one word to the
    other. Any other word it covers is a filter's, as "bugs" in "except bugs" or "langchain" in
    "except langchain". It covers the rest of its clause, and goes on past "and", "or" or a
    comma, unless a word that names no day starts what follows, as "and post them". "when",
    "while" or "during" in what it covers leave out time off when the words after them, to the
    next mark, look like a day or time off, as "except when I'm off" or "skip it while I'm
    away", and a condition otherwise, as "post only when there is a new release". "on" or
    "only" beside a word that looks like a day limit the days, as "on business days"."""
    if LEAVES.search(text) is None:
        return ()
    words = _covered(text, days, read, said)
    time_off = _time_off_after(words) if any(w.kind == "while" for w in words) else []
    found: list[tuple[int, int]] = []
    covering = listing = fresh = False
    cover = 0
    for n, word in enumerate(words):
        # Right after the word that leaves something out, marks and talk are passed over, as in
        # "except: PH" or "except, as always, Friday's check".
        if fresh and word.talk:
            continue
        if word.mark == "." and not fresh:
            covering = listing = False
        elif word.mark == "," and covering and not fresh:
            listing = True
        if word.kind == "while" and (fresh or covering) and time_off[n]:
            found.append((words[cover].start, _last_time_off(words, n).end))
        fresh = False
        lead = words[cover] if covering else None
        if word.kind == "only" and word.mark == "" and n and words[n - 1].kind == "day":
            found.append(((lead or _from(words, n - 1)).start, word.end))
        named = _names_days(words, n) if word.low == "on" and not word.own else None
        if named is not None:
            found.append(((lead or word).start, _through(words, named).end))
        trailed = _trails(words, n) if word.kind == "leaves" or word.low in LEAVES_BEFORE else None
        if trailed is not None:
            found.append(trailed)
        if word.kind == "join":
            listing = listing or covering
            continue
        if listing and word.kind not in ("link", "while"):
            listing = False
            ahead = words[n + 1] if n + 1 < len(words) else None
            new_part = ahead is None or ahead.mark != "" or ahead.kind != "day"
            if word.kind == "known" and new_part:
                covering = False
        if covering and word.kind == "day":
            found.append((words[cover].start, _through(words, n).end))
        if word.kind in ("leaves", "only"):
            covering = fresh = True
            paired = n > 0 and not word.mark and (words[n - 1].low, word.low) in LEAVE_OUT_PAIRS
            cover = n - 1 if paired else n
    return _joined_spans(found)


def _joined_spans(spans: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """The stretches in order, with each run of overlapping ones made one."""
    joined: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if joined and start < joined[-1][1]:
            joined[-1] = (joined[-1][0], max(end, joined[-1][1]))
        else:
            joined.append((start, end))
    return tuple(joined)


def _through(words: list[_Covered], n: int) -> _Covered:
    """The last of the words from `n` that look like a day, past links between them, as "Dec"
    in "25 Dec" or "quarter" in "the end of the quarter"."""
    last = words[n]
    for word in words[n + 1 :]:
        if word.mark or word.kind not in ("day", "link"):
            break
        if word.kind == "day":
            last = word
    return last


def _from(words: list[_Covered], n: int) -> _Covered:
    """The first of the words up to `n` that look like a day, as "month" in "month end"."""
    while n and not words[n].mark and words[n - 1].kind == "day":
        n -= 1
    return words[n]


def _last_time_off(words: list[_Covered], n: int) -> _Covered:
    """The last word after "when", "while" or "during" at `n`, to the next mark, that looks like
    a day or time off, as "leave" in "except when I'm on leave and post it"."""
    last = words[n]
    for word in words[n + 1 :]:
        if word.mark:
            break
        if word.day or word.kind == "day" or word.off:
            last = word
    return last


def _time_off_after(words: list[_Covered]) -> list[bool]:
    """For each word, whether the words after it, to the next mark, look like a day or time off,
    as "I'm off", "I'm out", "on leave", "Hari Raya", "the code freeze" or "the freeze"."""
    after = [False] * len(words)
    for n in range(len(words) - 2, -1, -1):
        word = words[n + 1]
        if not word.mark:
            after[n] = after[n + 1] or word.day or word.kind == "day" or word.off
    return after


def _time_off(lows: list[str], marks: list[Mark], n: int) -> bool:
    """Whether word `n` is time off in a stretch after "when", "while" or "during": a word of
    `AWAY`, the last word of one of `AWAY_PHRASES`, "out" or "off" after a person, as "I'm out"
    or "the boss is out", or "week" or "window" at the end of the stretch, as "release week"."""
    low = lows[n]
    if low in AWAY:
        return True
    if low in AWAY_PHRASE_ENDS and any(
        tuple(lows[max(0, n + 1 - len(phrase)) : n + 1]) == phrase
        and not any(marks[n + 2 - len(phrase) : n + 1])
        for phrase in AWAY_PHRASES
    ):
        return True
    if low in STRETCH_ENDS:
        return n + 1 == len(lows) or marks[n + 1] != ""
    if low not in ("out", "off") or n == 0 or marks[n]:
        return False
    two = (lows[n - 2], lows[n - 1]) if n > 1 and not marks[n - 1] else None
    return (
        (lows[n - 1],) in A_PERSON_IS
        or two in A_PERSON_IS
        or (two is not None and two[1] in ("is", "are") and two[0] in PEOPLE)
    )


def _trails(words: list[_Covered], n: int) -> tuple[int, int] | None:
    """Where the word at `n` leaves out the words right before it, ending its clause but for
    talk, as "excluded" in "PH excluded", "skip" in "PH: skip" or "don't" in "PH don't run", and
    one of those words looks like a day or is a day it may run on: from those words to the last
    talk after `n`, or None."""
    end = n + 1
    while (
        end < min(n + 3, len(words))
        and not words[end].mark
        and (words[end].talk or words[end].low in NEEDED)
    ):
        end += 1
    if end < len(words) and not words[end].mark:
        return None
    m = n - 1
    while m >= max(0, n - 4) and words[m].kind != "join":
        if words[m].kind == "day":
            return _from(words, m).start, words[end - 1].end
        if words[m].mark:
            break
        m -= 1
    return None


def _names_days(words: list[_Covered], n: int) -> int | None:
    """Where the words after "on" at `n`, past up to three words such as "the", look like a day
    the reader doesn't read, as "days" in "check langgraph on business days", or None. A day of
    the week is left to the day check, as "Monday" in "tickets created on Monday"."""
    m = n + 1
    while m < min(n + 4, len(words)) and words[m].kind == "link" and not words[m].mark:
        m += 1
    while m < len(words) and not words[m].mark and words[m].kind not in ("link", "join"):
        if words[m].kind == "day" and not words[m].day:
            return m
        m += 1
    return None


def _leaves_out(lows: list[str], marks: list[Mark], n: int) -> bool:
    """Whether word `n` leaves out what follows it, as "except", "excl." or "other than". A verb
    such as "drop" leaves out only what follows it straight away, as "drop PH", not "drop that
    step", and a negated verb only running, as "don't run on PH". One right before a filter's
    own word is the filter's, as "not" in "not touched since Monday"."""
    low = lows[n]
    ahead = lows[n + 1] if n + 1 < len(lows) and not marks[n + 1] else None
    if low in NEGATIONS and ahead in FILTERS_OWN:
        return False
    if low in LEAVE_OUT or low in SHORT_LEAVE_OUT or (n and (lows[n - 1], low) in LEAVE_OUT_PAIRS):
        return True
    if low in ACTS_ON:
        return ahead is not None and ahead not in OBJECTS
    return low in NOT_RUN and bool(RUN & set(lows[n + 1 : n + 4]))


@lru_cache(maxsize=4096)
def _a_typo_of_a_day(low: str) -> bool:
    """Whether a word the reader doesn't know is a typo of a day, the weekend or a holiday,
    starting with the same letter: one edit in a word of 5 to 7 letters, as "Firday" or
    "weeknds", or two in a longer one, as "Thrusdays". "wk" is read as "week", as in "wkends"."""
    if low in NOT_A_DAY or low in DAYISH:
        return False
    if low.startswith("wk"):
        low = "week" + low[2:]
    if len(low) < 5:
        return False
    most = 1 if len(low) < 8 else 2
    return any(
        target[0] == low[0] and abs(len(target) - len(low)) <= most and _edits(low, target) <= most
        for target in TYPO_OF
    )


def _edits(a: str, b: str) -> int:
    """The fewest letters added, left out or changed, or pairs side by side swapped, that make
    `a` into `b`, as 1 from "Firday" to "friday"."""
    two_up: list[int] = []
    up = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        row = [i]
        for j in range(1, len(b) + 1):
            cost = min(up[j] + 1, row[j - 1] + 1, up[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cost = min(cost, two_up[j - 2] + 1)
            row.append(cost)
        two_up, up = up, row
    return up[-1]


def _day_like(
    text: str,
    pieces: list[tuple[str, int, int]],
    lows: list[str],
    marks: list[Mark],
    n: int,
    fresh: bool,
) -> bool:
    """Whether word `n` looks like a day or time off: a day or a short day in any case, as "FRI"
    or "sat", a word ending in "day" or "days", as "payday" or "workdays", a typo of a day, as
    "Firday", a code for days off, as "PH" or "CNY", or "ph" right after a word that leaves it
    out (`fresh`), a holiday or time off, as "Xmas", "Hari Raya" or "on leave", a day of the
    month, as "the 25th" or "25th Dec", two-letter days joined by "/" or "-", as "Sa/Su", "w/e",
    or the start of a day's name, as "Frid". A word in capitals where a project key stands, as "in
    SAT" or "the SAT tickets", is the key."""
    raw, low = pieces[n][0], lows[n]
    before = lows[n - 1] if n else ""
    after = lows[n + 1] if n + 1 < len(lows) and not marks[n + 1] else ""
    gap = text[pieces[n][2] : pieces[n + 1][1]] if n + 1 < len(pieces) else ""
    if PROJECT_KEY.fullmatch(raw) and (before in PLACES or after in KEYED):
        return False
    if HOLIDAY_CODE.fullmatch(raw):
        return True
    if fresh and (low == "ph" or (low == "p" and gap == "." and lows[n + 1] == "h")):
        return True
    if low.replace("-", "") in DAY_WORDS or low in TIME_OFF or (before, low) in TIME_OFF_PAIRS:
        return True
    if low in TWO_LETTER_DAYS:
        return any(
            text[pieces[min(m, n)][2] : pieces[max(m, n)][1]] in ("/", "-")
            and (lows[m] in TWO_LETTER_DAYS or lows[m] in DAY_WORDS)
            for m in (n - 1, n + 1)
            if 0 <= m < len(pieces)
        )
    if low in MORE_SHORT_DAYS:
        return True
    if ORDINAL.fullmatch(low):
        return not after or after in DATED or after in LEAVING_OUT or after in LEAVES_BEFORE
    if low in TIME_OFF_NOUNS:
        noun = before in LINKS or before in OBJECTS or before in ("i'm", "we're")
        return gap != "-" and (noun or (not after and low != "off"))
    if low.endswith(("day", "days")) and low not in NOT_DAYS:
        return True
    return _a_typo_of_a_day(low)


def _covered(
    text: str, days: set[str], read: dict[int, int], said: list[tuple[int, int]]
) -> list[_Covered]:
    """The request's words as `_left_out_day_like` reads them. `read` holds where each day read as
    the day it runs starts and ends, and `said` the schedule's own phrases, read whole. A day the
    run day never falls on is kept, and so is the word a day labels, as "hotfixes" in "except
    Friday's hotfixes"."""
    pieces = _pieces(text)
    lows = [_low(raw) for raw, _, _ in pieces]
    after = [*lows[1:], ""]
    marks: list[Mark] = []
    for n, (_, start, _) in enumerate(pieces):
        gap = text[pieces[n - 1][2] : start] if n else ""
        ends = CLAUSE_END.search(gap)
        stops = ends is not None and ends.group(0).strip(",") != ""
        marks.append("." if stops else "," if ends or "&" in gap else "")
    runs_on = frozenset[str]().union(*(_runs_on(key) for key in days))
    known = bytearray(len(text) + 1)
    for a, b in [
        *said,
        *(m.span() for p in (CLOCK, POLITE_PHRASE, A_YES, SOMEONE) for m in p.finditer(text)),
    ]:
        known[a:b] = b"\1" * (b - a)
    counts = bytearray(len(text) + 1)
    for p, value in (
        (TIME_COUNT, COUNTS_DAYS),
        (CALENDAR_DAYS, COUNTS_DAYS),
        (FILTER_COUNT, COUNTS_FOR_A_FILTER),
    ):
        for m in p.finditer(text):
            counts[m.start() : m.end()] = bytes([value]) * (m.end() - m.start())
    schedule = bytearray(len(text) + 1)
    for a, b in said:
        counts[a:b] = bytes(b - a)
        schedule[a:b] = b"\1" * (b - a)
    asks_nothing = bytearray(len(text) + 1)
    for m in (*POLITE_PHRASE.finditer(text), *A_YES.finditer(text)):
        asks_nothing[m.start() : m.end()] = b"\1" * (m.end() - m.start())
    found: list[_Covered] = []
    labelled = fresh = False
    for n, (raw, start, end) in enumerate(pieces):
        low = lows[n]
        bare = re.sub(r"['’]s$", "", raw)
        day = DAY_NAMED.fullmatch(bare) is not None
        ex = (
            low in SHORT_EXCEPT
            and n + 1 < len(pieces)
            and (
                counts[pieces[n + 1][1]] == COUNTS_DAYS
                or any(
                    DAY_NAMED.fullmatch(text, pieces[n + 1][1], pieces[m][2]) is not None
                    for m in range(n + 1, min(n + 3, len(pieces)))
                )
                or tuple(lows[n + 1 : n + 3]) in TIME_OFF_PAIRS
                or _day_like(text, pieces, lows, marks, n + 1, True)
            )
        )
        kind: CoverKind
        if day:
            # A day right after a word that leaves it out is left out, even where the
            # schedule's own phrase read it as the day it runs, as "barring Fridays". A mark
            # between them ends what the word covers, as "no, Friday at 9am".
            ran = read.get(start, -1) >= start + len(bare) and not (fresh and marks[n] == "")
            never = bool(days) and not _may_fall_on(bare) & runs_on
            kind = "known" if ran else "kept" if never else "day"
        elif (ex or _leaves_out(lows, marks, n)) and not asks_nothing[start]:
            kind = "leaves"
        elif low == "only":
            kind = "only"
        elif low in LIST_JOINS:
            kind = "join"
        elif low in WHILE:
            kind = "while"
        elif low in LINKS:
            kind = "link"
        elif counts[start] == COUNTS_DAYS:
            kind = "day"
        elif (
            labelled
            or counts[start] == COUNTS_FOR_A_FILTER
            or (known[start] and known[end - 1])
            or (low, after[n]) in LEAVE_OUT_PAIRS
        ):
            kind = "known"
        elif (
            not said
            and low.endswith(("day", "days"))
            and any(
                text[pieces[min(m, n)][2] : pieces[max(m, n)][1]] == "-"
                and lows[m] not in LEAVING_OUT
                for m in (n - 1, n + 1)
                if 0 <= m < len(pieces)
            )
        ):
            # With no schedule of their own, a hyphen that joins "day" to a word names a kind of
            # thing, as "zero-day patches" or "same-day fixes". Beside a schedule it still asks,
            # as on main.
            kind = "known"
        elif _day_like(text, pieces, lows, marks, n, fresh):
            kind = "day"
        else:
            kind = "known"
        gap = text[end : pieces[n + 1][1]] if n + 1 < len(pieces) else ""
        off = (
            _time_off(lows, marks, n)
            or (low == "freeze" and n > 0 and lows[n - 1] == "the" and gap != "-")
            or (low == "p" and gap == "." and lows[n + 1] == "h")
        )
        found.append(_Covered(kind, marks[n], low, day, bool(schedule[start]), off, start, end))
        labelled = day and (bare != raw or (n > 0 and lows[n - 1] in LABELS))
        fresh = kind == "leaves" or (fresh and kind == "link")
    return found


def _region(
    tokens: list[tuple[str, int, int]],
    clause_of: list[int],
    core: tuple[int, int],
    explained: frozenset[str],
) -> set[int]:
    """The token indexes a structure stands in: every token of `core`, the stretch of the
    request it was located in, grown outwards over filler and the structure's own words until
    a word it does not explain or the end of the clause. "me" after a verb the structure
    explains ("Show me the") is passed over."""
    inside = [i for i, (_, start, end) in enumerate(tokens) if start < core[1] and end > core[0]]
    if not inside:
        return set()
    found = set(inside)

    def own(i: int) -> bool:
        low = _low(tokens[i][0])
        return low in FILLER or low in explained

    for step, edge in ((-1, inside[0]), (1, inside[-1])):
        i = edge + step
        while 0 <= i < len(tokens) and clause_of[i] == clause_of[edge]:
            if own(i) or (
                step == -1
                and _low(tokens[i][0]) in ME_WORDS
                and i - 1 >= 0
                and clause_of[i - 1] == clause_of[edge]
                and _low(tokens[i - 1][0]) in explained
            ):
                found.add(i)
            else:
                break
            i += step
    return found


def leftovers(
    text: str,
    rendered: list[Rendered],
    covered: list[tuple[int, int]],
    said: Said,
    writes: bool = False,
) -> list[Span]:
    """The request's words that nothing explains, clause by clause. A structure explains a
    word only where it stands: in the stretch of the request its quote was located in, and
    the run of its own words and filler around that, so the search's assignee never explains
    "assign" in the new ticket's clause, and the schedule never explains "Friday" in "finished
    by this Friday". A clause whose first content word is unexplained comes back from that
    word to its end, because the whole part is unread, and a clause no structure explains a
    word of comes back whole, little words and all ("let me know", "for them"), unless it is
    only thanks or please; otherwise the run from the first unexplained word to the last. A
    "without", "no" or "not" right before the run comes with it, so "without approval" keeps
    its "without". In a request that writes, a run that names a yes, a person, a role or a
    group takes its whole clause, so the refusal reads as the person wrote it."""
    tokens = _request_tokens(text)
    clauses = clauses_of(text)
    clause_of = _clause_of(text, tokens)
    explains: list[set[int]] = []
    for r in rendered:
        region: set[int] = set()
        for core in (r.said, r.also):
            if core is not None:
                region |= _region(tokens, clause_of, core, r.explained)
        explains.append({i for i in region if _low(tokens[i][0]) in r.explained})
    parts_at: dict[int, set[RowKind]] = {}
    for r, found in zip(rendered, explains, strict=True):
        for i in found:
            parts_at.setdefault(i, set()).add(r.row.kind)
    known = set[int]().union(*explains) if explains else set[int]()
    # A cover inside the search's own quote ("by me" in "the PAY tickets opened by me") would
    # hide a filter the search can't run, so the staff member's attention is only ever theirs
    # to skip outside it.
    quoted = [r.said for r in rendered if r.row.kind == "look_for" and r.said is not None]
    covered = [(a, b) for a, b in covered if not any(q[0] <= a and b <= q[1] for q in quoted)]
    kind_words = covered + [(m.start(), m.end()) for m in POLITE_PHRASE.finditer(text)]
    known |= {
        i
        for i, (_, start, end) in enumerate(tokens)
        if any(a <= start and end <= b for a, b in kind_words)
    }
    spans: list[Span] = []
    for n, (c_start, c_end) in enumerate(clauses):
        clause = text[c_start:c_end]
        theirs = [(c_start + m.start(), c_start + m.end()) for m in FROM_ME.finditer(clause)]
        content: list[tuple[int, int]] = []
        unread: list[int] = []
        before = ""
        at = 0
        for i, (raw, start, end) in enumerate(tokens):
            if clause_of[i] != n:
                continue
            low = _low(raw)
            names = (
                A_YES.fullmatch(raw) is not None
                or SOMEONE.fullmatch(raw) is not None
                or (low == "one" and before == "no")
                or (low in ("team", "boss") and before == "the")
            ) and not any(a <= start and end <= b for a, b in theirs)
            filler = low in FILLER and not (raw[:1].isupper() and at) and not names
            before = low
            at += 1
            if filler:
                continue
            content.append((start, end))
            if i not in known:
                unread.append(i)
        mine = [i for i, c in enumerate(clause_of) if c == n]
        unheard = not any(i in known for i in mine)
        if not unread and (content or not unheard or polite(text[c_start:c_end])):
            continue
        if not unread:
            unread = mine
            content = [(tokens[i][1], tokens[i][2]) for i in mine]
        _, first, _ = tokens[unread[0]]
        _, _, last = tokens[unread[-1]]
        run = (first, last)
        start = c_start if unheard else first
        end = c_end if first == content[0][0] else last
        lead = LEAD_IN.search(text[c_start:start])
        if lead is not None:
            start = c_start + lead.start()
        names = names_a_yes(text[start:end])
        someone = names_a_person(text, start, end)
        if (names or someone) and writes:
            start, end = content[0][0], c_end
        start, end = trim(text, start, end)
        beside = _beside(clause_of, parts_at, unread[0], unread[-1])
        kind = _kind_of(text, start, end, run, said, beside)
        spans.append(Span(text[start:end], start, end, kind, names, someone))
    return spans


def task_shaped(read: TaskRead, text: str) -> bool:
    """Whether the reading, or the request, describes a task: a structure is filled, or the
    request asks for a change in its own words."""
    return any((read.search, read.ticket, read.place, read.schedule)) or bool(change_verbs_in(text))


def speaks_only_of_self(text: str, start: int, end: int) -> bool:
    """Whether the request's words from `start` to `end`, which the model called the staff
    member's own, really name them and nobody else: the words say I, me, my, mine or myself,
    and no yes, no other person, and no name."""
    quote = FROM_ME.sub(" me ", text[start:end])
    return (
        SPEAKS_OF_SELF.search(quote) is not None
        and A_YES.search(quote) is None
        and SOMEONE.search(quote) is None
        and not names_a_person(text, start, end)
        and not any(
            NAME.fullmatch(w) and w.casefold() not in KNOWN_WORDS
            for w in re.findall(r"\w+", text[start:end])[1:]
        )
    )
