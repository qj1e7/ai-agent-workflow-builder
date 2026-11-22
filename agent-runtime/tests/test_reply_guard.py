from typing import Any

import pytest

from agent_runtime.abilities import CAPABILITIES
from agent_runtime.contract import (
    ABOUT_LIMIT,
    FreeReplyAnswer,
    ReplyAbout,
    ReplyEnvelope,
    ReplyOffer,
)
from agent_runtime.how_to import HOW_TO
from agent_runtime.reply_guard import (
    CHECKS,
    NOT_READY,
    Given,
    about_of,
    claims_nothing_done,
    claims_only_what_is_built,
    failed_check,
    fits_its_form,
    guarded,
    is_plain,
    keeps_every_yes,
    makes_nothing_up,
    offer_of,
    offers_nothing,
    shown_of,
)

OPERATOR = Given(message="how can i start to use this ?", facts="")
APPROVER = Given(message="how do I use this?", facts="", sets_up=False)
FACTS = (
    '{"watchlist":[{"name":"LangGraph","our_version":"1.2.14","newest_version":"1.2.16",'
    '"open_ticket":"MOCK-142"}]}'
)
WITH_FACTS = Given(message="is langgraph behind?", facts=FACTS, sent=("watchlist",))


def said(text: str, **fields: Any) -> ReplyEnvelope:
    return ReplyEnvelope(**{"form": "answer", "text": text, **fields})


def asked(text: str, *choices: str) -> ReplyEnvelope:
    return ReplyEnvelope(form="clarify", text=text, choices=list(choices))


HELPFUL = said(
    "To start, type what you want done in the box, such as Check LangGraph for new releases "
    "every Monday at 9am. The Planner shows a card with what it understood. Change anything on "
    "it, then turn it on."
)


def test_a_helpful_how_to_answer_passes_every_check_and_is_shown_as_written():
    assert guarded(HELPFUL, OPERATOR) == FreeReplyAnswer(form="answer", text=HELPFUL.text)


def test_the_checks_run_in_the_order_the_adr_lists_them():
    assert [name for name, _ in CHECKS] == [
        "shape",
        "plain_text",
        "claims_done",
        "claims_unbuilt",
        "offers_to_act",
        "skips_a_yes",
        "made_up",
    ]


# 1. Shape.


@pytest.mark.parametrize(
    "reply",
    [
        said(""),
        said("   ​ "),
        said("x" * 601),
        said("Three workflows.", choices=["Yes", "No"]),
        said("Three workflows.", offer="github.releases"),
        asked("Which software?", "LangGraph"),
        asked("Which software?", "A", "B", "C", "D", "E"),
        asked("Which software", "LangGraph", "Redis"),
        asked("Which software?", "LangGraph", "langgraph"),
        asked("Which software?", "LangGraph", "x" * 41),
        asked("Which software?", "LangGraph", "  "),
        ReplyEnvelope(form="cant", text="I can't do that yet.", choices=["Ok", "Fine"]),
    ],
)
def test_a_reply_out_of_its_form_fails_the_shape_check(reply: ReplyEnvelope):
    assert not fits_its_form(shown_of(reply), OPERATOR)
    assert failed_check(shown_of(reply), OPERATOR) == "shape"


def test_a_clarifying_question_with_two_to_four_short_choices_fits():
    reply = asked("Which software should I watch?", "LangGraph", "Redis", "Something else")
    assert fits_its_form(shown_of(reply), OPERATOR)
    shown = guarded(reply, OPERATOR)
    assert isinstance(shown, FreeReplyAnswer)
    assert shown.choices == ["LangGraph", "Redis", "Something else"]


def test_a_second_clarifying_question_in_a_row_is_never_asked():
    reply = asked("Which day?", "Monday", "Friday")
    again = Given(message="weekly", facts="", clarified_before=True)
    assert fits_its_form(shown_of(reply), OPERATOR)
    assert not fits_its_form(shown_of(reply), again)


def test_an_empty_offer_on_an_answer_is_no_offer():
    assert fits_its_form(shown_of(said("Three workflows.", offer="  ")), OPERATOR)


# 2. Plain text.


@pytest.mark.parametrize(
    "text",
    [
        "Type **Check LangGraph** in the box.",
        "Type __this__ in the box.",
        "Type `Check LangGraph` in the box.",
        "See [the guide](https://example.org) first.",
        "See https://wiki.example.org/start first.",
        "See www.example.com first.",
        "Write to help.codesparks.com for help.",
        "<b>Type</b> your request.",
        "Type your request &amp; press Enter.",
        "# Getting started\nType your request.",
        "Steps:\n- Type your request\n- Check the card",
        "Steps:\n1. Type your request\n2. Check the card",
        "> Type your request.",
        "Type *anything* you like.",
    ],
)
def test_markdown_html_or_a_link_fails_the_plain_text_check(text: str):
    assert not is_plain(shown_of(said(text)), OPERATOR)


def test_a_link_in_a_choice_fails_too():
    assert not is_plain(shown_of(asked("Which one?", "LangGraph", "see example.com")), OPERATOR)


@pytest.mark.parametrize(
    "text",
    [
        "LangGraph runs 1.2.14, and the newest is 1.2.16.",
        "Node.js isn't on your Watchlist.",
        "First, type your request. Then check the card, and turn it on.",
        "The repository langchain-ai/langgraph is on your Watchlist.",
    ],
)
def test_plain_words_with_versions_and_names_pass(text: str):
    assert is_plain(shown_of(said(text)), OPERATOR)


# 3. No claim that something happened.


@pytest.mark.parametrize(
    "text",
    [
        "I've created the ticket for you.",
        "I created a workflow.",
        "We sent the list to your manager.",
        "It has been approved.",
        "The ticket was created.",
        "MOCK-12 has been sent to Bob.",
        "Your workflow is now on.",
        "The schedule is already set up.",
        "It's saved.",
        "That's done.",
        "Done! Anything else?",
        "You're all set.",
        "Your ticket is created.",
        "Bob approved your request.",
        "The Planner paused the Friday summary.",
        "The platform deleted the old tickets.",
    ],
)
def test_saying_something_happened_fails_the_claims_done_check(text: str):
    assert not claims_nothing_done(shown_of(said(text)), OPERATOR)


@pytest.mark.parametrize(
    "text",
    [
        "A ticket search sees each ticket's type, owner, whether it is open or done, and when it "
        "was created, updated and done.",
        "You can find tickets that were updated in the last 7 days.",
        "A new Jira ticket is created only after an Approver's yes.",
        "When the check is done, the result shows here.",
        "The workflows you set up are on the Workflows page.",
        "Your last run stopped, and the AI troubleshooter explains why.",
    ],
)
def test_describing_how_things_work_is_no_claim(text: str):
    assert claims_nothing_done(shown_of(said(text)), OPERATOR)


# 4. No claim of an unbuilt ability.


@pytest.mark.parametrize(
    "text",
    [
        "You can post the list in Teams.",
        "I can email you the list.",
        "I can send it to your Teams channel every Friday.",
        "You can close tickets from here.",
        "The platform can delete old tickets.",
        "I can read GitLab for you.",
        "I can check who has access in Entra.",
        "You can check for CVEs.",
        "I can watch PyPI packages too.",
        "I can tell you when Java reaches end of life.",
        "I can list the exploited flaws.",
        "I can read GitHub issues.",
        "I can update the Confluence page.",
        "You can find tickets by priority.",
        "I can set a component on the new ticket.",
        "I can look past the newest 50 tickets.",
        "Slack works too.",
        "Results go out by email.",
        "I can rename it for you.",
        "You can ask me to close the bugs.",
        "I can't read GitLab, but you can watch it in Slack.",
    ],
)
def test_an_unbuilt_ability_fails_the_claims_unbuilt_check(text: str):
    assert not claims_only_what_is_built(shown_of(said(text)), OPERATOR)


@pytest.mark.parametrize(
    "text",
    [
        "I can watch software for new releases on GitHub, read Jira tickets, sum up what I find, "
        "and create a Jira ticket after an Approver's yes.",
        "I can't post in Teams or send email yet. Run results show here, in the chat.",
        "Email isn't connected yet.",
        "I can't check for known vulnerabilities yet.",
        "You can list the open bugs in MOCK and put them in one new Jira ticket after an "
        "Approver's yes.",
        "You can pick a time and turn it on.",
        "You can change when a workflow runs, or pause it.",
        "Tap Ask the team if you want Slack messages.",
        "You can tap Ask the team to ask for Slack messages.",
        "Ask the team whether it can be added.",
        "An Approver says yes in Teams.",
    ],
)
def test_ready_abilities_and_honest_cants_pass(text: str):
    assert claims_only_what_is_built(shown_of(said(text)), OPERATOR)


def test_what_you_can_do_is_held_to_your_role():
    setting_up = said("You can set up a workflow that checks Jira every Monday.")
    approving = said("You can approve requests from Needs you.")
    assert claims_only_what_is_built(shown_of(setting_up), OPERATOR)
    assert not claims_only_what_is_built(shown_of(setting_up), APPROVER)
    assert claims_only_what_is_built(shown_of(approving), APPROVER)
    assert not claims_only_what_is_built(shown_of(approving), OPERATOR)


@pytest.mark.parametrize(
    "text",
    [
        "You can remove LangGraph from the Watchlist.",
        "You can take node js off your watchlist, then undo it.",
    ],
)
def test_taking_software_off_the_watchlist_is_an_operators_own_action(text: str):
    assert claims_only_what_is_built(shown_of(said(text)), OPERATOR)
    assert not claims_only_what_is_built(shown_of(said(text)), APPROVER)


@pytest.mark.parametrize(
    "text",
    [
        "You can remove the old tickets.",
        "You can remove the Confluence page.",
        "You can remove Bob from the approvers.",
    ],
)
def test_removing_anything_but_watched_software_is_still_unbuilt(text: str):
    assert not claims_only_what_is_built(shown_of(said(text)), OPERATOR)


@pytest.mark.parametrize(
    "text",
    [
        "You can type Explain and a workflow's name to see what it does.",
        "You can explain the morning check from its row in Workflows.",
    ],
)
def test_explaining_a_workflow_is_open_to_both_roles(text: str):
    assert claims_only_what_is_built(shown_of(said(text)), OPERATOR)
    assert claims_only_what_is_built(shown_of(said(text)), APPROVER)


def test_what_the_planner_can_do_is_not_held_to_the_persons_role():
    assert claims_only_what_is_built(
        shown_of(said("I can watch software for new releases.")), APPROVER
    )


def test_a_choice_that_names_something_unbuilt_fails():
    assert not claims_only_what_is_built(
        shown_of(asked("Where should it go?", "A Jira ticket", "Post it in Teams")), OPERATOR
    )


def test_every_capability_that_is_not_ready_is_named_in_the_table():
    """A new Planned or Unsupported entry in the registry fails this until the guard can name it."""
    assert set(NOT_READY) == {c.id for c in CAPABILITIES if c.state != "ready"}


@pytest.mark.parametrize("spec", [c for c in CAPABILITIES if c.state != "ready"], ids=str)
def test_each_unbuilt_capability_is_caught_in_its_own_words(spec: Any):
    assert NOT_READY[spec.id](spec.plain), spec.plain
    assert not claims_only_what_is_built(shown_of(said(f"I can {spec.plain.lower()}.")), OPERATOR)


@pytest.mark.parametrize("spec", [c for c in CAPABILITIES if c.state == "ready"], ids=str)
def test_no_ready_capability_is_named_as_unbuilt(spec: Any):
    assert not any(named(spec.plain) for named in NOT_READY.values()), spec.plain


# 5. No offer to act.


@pytest.mark.parametrize(
    "text",
    [
        "I'll set that up for you.",
        "I will tell you when one is behind.",
        "Let me check that.",
        "Want me to watch it?",
        "Would you like me to add it?",
        "Shall I add it?",
        "I'm going to add it.",
        "I'll keep you posted.",
        "We'll let you know.",
        "I promise it runs on Monday.",
    ],
)
def test_an_offer_to_act_fails_the_offers_check(text: str):
    assert not offers_nothing(shown_of(said(text)), OPERATOR)


def test_telling_the_person_what_to_type_is_no_offer():
    assert offers_nothing(shown_of(said("Type Pause and its name to pause it.")), OPERATOR)
    assert offers_nothing(
        shown_of(asked("Which software should I watch?", "Redis", "Kafka")), OPERATOR
    )


# 6. No skipped yes.


@pytest.mark.parametrize(
    "text",
    [
        "You can skip the approval for this one.",
        "It runs with no need to ask anyone.",
        "Nothing is written without an Approver's yes.",
        "You can approve your own request.",
        "An Approver can sign off on their own work here.",
        "I can create a ticket every Monday.",
        "It puts the list in one new Jira ticket every Friday.",
    ],
)
def test_a_skipped_yes_fails_the_yes_check(text: str):
    assert not keeps_every_yes(shown_of(said(text)), APPROVER)


def test_a_choice_that_skips_a_yes_fails_too():
    reply = asked("How should it run?", "With a yes each time", "Skip the approval")
    assert not keeps_every_yes(shown_of(reply), OPERATOR)


@pytest.mark.parametrize(
    "text",
    [
        "Every change to data waits for an Approver's yes in Teams.",
        "The person who asked is never the Approver of their own request.",
        "You never approve your own requests.",
        "It puts the list in one new Jira ticket every Friday, after an Approver's yes.",
        "You can list the open tickets.",
        "You can filter tickets by type.",
    ],
)
def test_the_yes_said_plainly_passes(text: str):
    assert keeps_every_yes(shown_of(said(text)), OPERATOR)


# An honest can't (ADR 0047, amended 20 Nov 2026). A first-person negation that acts directly on
# the words it denies clears them, through an allow-list of shapes. Anything else still fails.


@pytest.mark.parametrize(
    "text",
    [
        "I can't create a ticket without a yes.",
        "I can't create a Jira ticket without an Approver's yes, because every new Jira ticket "
        "waits for an Approver's yes in Teams.",
        "I can't create a new Jira ticket without an Approver's yes, and the person who asked is "
        "never the Approver of their own request.",
        "I don't create tickets without an Approver's yes. Type what the ticket should say in the "
        "box on Home, and it waits for an Approver's yes.",
        "I never create a ticket without approval.",
        "I can't book a meeting room. Nothing I can do comes close to that, so tap Ask the team.",
        "Uploading to SharePoint isn't something I can do yet. Tap Ask the team.",
        "Every change waits for an Approver's yes.",
    ],
)
def test_an_honest_cant_in_an_allowed_shape_passes_for_both_roles(text: str):
    assert failed_check(shown_of(said(text)), OPERATOR) is None
    assert failed_check(shown_of(said(text)), APPROVER) is None


@pytest.mark.parametrize(
    ("text", "check"),
    [
        ("I can't believe the ticket was created.", "claims_done"),
        ("I can't wait, the ticket is created.", "claims_done"),
        ("I didn't need a yes, it's done.", "claims_done"),
        ("I can't stop it, the workflow is now live.", "claims_done"),
        ("I don't need approval for this.", "skips_a_yes"),
        ("It isn't waiting for a yes.", "skips_a_yes"),
        ("This change doesn't wait for an Approver.", "skips_a_yes"),
        ("The ticket won't need to wait for approval.", "skips_a_yes"),
    ],
)
def test_a_near_miss_of_an_honest_cant_still_fails(text: str, check: str):
    assert failed_check(shown_of(said(text)), OPERATOR) == check
    assert failed_check(shown_of(said(text)), APPROVER) == check


@pytest.mark.parametrize(
    "text",
    [
        "I can't create a ticket without a yes, but you can.",
        "I can't create a ticket without a yes, but an Operator can create one.",
        "I can't create a ticket without a yes, and an Operator can.",
        "I can't create a ticket without a yes, and so can you.",
        "I can't create a ticket without a yes yet.",
        "I can't create a ticket without a yes until Friday.",
        "I can't create a ticket without a yes, until Friday.",
        "I can't create a ticket without a yes, so it goes straight through.",
        "I can't create a ticket without a yes, and the next one goes out at once.",
        "I can't create a ticket without a yes, and the rest go straight in.",
        "I can't wait to create tickets without a yes.",
        "I didn't create the ticket without a yes.",
        "I can't delete a ticket without a yes.",
        "I can't post it in Teams without a yes.",
        "An Operator can, but I can't create a ticket without a yes.",
        "Nothing I can do comes close, but I can post it in Slack.",
        "There is nothing I can do in Slack.",
    ],
)
def test_a_denial_that_also_claims_or_leaves_a_skip_open_still_fails(text: str):
    assert failed_check(shown_of(said(text)), OPERATOR) is not None
    assert failed_check(shown_of(said(text)), APPROVER) is not None


DENIED = "I can't create a ticket without a yes"


@pytest.mark.parametrize(
    "text",
    [
        f"{DENIED}, and the yes is optional.",
        f"{DENIED}, and I say yes.",
        f"{DENIED}, and I give the yes.",
        f"{DENIED}, and I count as the Approver.",
        f"{DENIED}, and an Operator can create one.",
        f"{DENIED}, and Operators create them in one tap.",
        f"{DENIED}, and approval is skipped.",
        f"{DENIED}, and the gate is off.",
        f"{DENIED}, and it goes ahead anyway.",
        f"{DENIED}, and you're allowed to create one.",
        f"{DENIED}, and you may create one yourself.",
        f"{DENIED}, and this one is exempt.",
        f"{DENIED}, and you needn't wait.",
        f"{DENIED}, because you already gave it.",
        f"{DENIED}, and the Approver says yes.",
        f"An Operator can create one, because {DENIED}.",
        f"{DENIED}.\nBut you can.",
        f"{DENIED}. The gate is off.",
        f"{DENIED}. Every change waits for an Approver's yes. But you can.",
        f"An Operator can create one. {DENIED}.",
        "Nothing I can do but book a room.",
        "Nothing I can do except book a room for you.",
        "It isn't anything I can do, apart from book the room.",
        "Nothing I can do is better than booking a room for you.",
        "Nothing I can do waits for a yes.",
        "Nothing I can do needs a yes.",
        "Nothing that I can do is stopped by an Approver.",
        "Nothing I can do is off limits.",
        "Nothing I can do, and book the room for you.",
        "It needn't wait.",
        "It need not wait for a yes.",
    ],
)
def test_what_the_safety_review_found_still_falls_back(text: str):
    """Each passed the first allow-lists. A denial may stand only beside the prompt's own words
    about a yes, and a negated "I can" covers only "do" up to the end of its clause."""
    assert failed_check(shown_of(said(text)), OPERATOR) is not None
    assert failed_check(shown_of(said(text)), APPROVER) is not None


@pytest.mark.parametrize(
    "text",
    [
        "You can't create a ticket without a yes.",
        "Sorry, I can't create a ticket without a yes.",
        "I can't read it without a yes.",
        "Nothing the platform can do comes close, so tap Ask the team.",
        "If you need SharePoint, tap Ask the team.",
    ],
)
def test_a_denial_in_a_shape_off_the_allow_list_still_fails(text: str):
    assert failed_check(shown_of(said(text)), OPERATOR) is not None


# 7. Nothing made up.


@pytest.mark.parametrize(
    "text",
    [
        "LangGraph 1.3.0 is out.",
        "Your Watchlist shows LangGraph at v1.2.15.",
        "Ticket MOCK-999 is open.",
        "The upgrade ticket is OPS-142.",
    ],
)
def test_a_key_or_a_version_not_in_the_facts_fails_the_made_up_check(text: str):
    assert not makes_nothing_up(shown_of(said(text)), WITH_FACTS)


@pytest.mark.parametrize(
    "text",
    [
        "LangGraph runs 1.2.14 and the newest is 1.2.16.",
        "Your Watchlist shows LangGraph at v1.2.16.",
        "MOCK-142 is open for LangGraph.",
    ],
)
def test_a_key_or_a_version_from_the_facts_passes(text: str):
    assert makes_nothing_up(shown_of(said(text)), WITH_FACTS)


def test_a_version_the_person_typed_is_theirs_to_quote():
    given = Given(message="Is LangGraph 1.3 out yet?", facts=FACTS)
    assert makes_nothing_up(shown_of(said("LangGraph 1.3 isn't on your Watchlist yet.")), given)


# 7, grown (ADR 0049): a name the text says a list holds must be in that list in the facts.

HELD = Given(
    message="add redis",
    facts=(
        '{"watchlist":[{"name":"LangGraph","our_version":"1.2.14"},{"name":"Redis"},'
        '{"name":"React Native"}],'
        '"workflows":[{"name":"Morning bug list"}],"other_workflows":["Friday summary"],'
        '"needs_you":{"total":2}}'
    ),
)


@pytest.mark.parametrize(
    "text",
    [
        "Your Watchlist already holds Kubernetes.",
        "Your Watchlist holds LangGraph and Kubernetes.",
        "The Watchlist has Redis, LangGraph, and Kubernetes.",
        "Your Watchlist already holds LangGraph Studio.",
        "Kubernetes is on your Watchlist.",
        "LangGraph and Kubernetes are already on the Watchlist.",
        "Your Software watchlist includes Kafka at 3.7.0.",
        "You already watch Kubernetes.",
        "Your workflows include Night audit.",
        "Your workflow list has a workflow called Night audit.",
        "Night audit is one of your workflows.",
        "Needs you holds Kubernetes.",
        "Your Watchlist holds both Redis and Kafka.",
        "Your Watchlist holds React.",
        "Your workflows include Redis.",
        "Your Watchlist holds Morning bug list.",
        "Needs you shows Morning bug list.",
        "Your Watchlist already holds Go. Open the Watchlist to see its line.",
        "Go is on your Watchlist.",
        "Next is on your Watchlist, and so is Redis.",
        "Your Watchlist holds Redis and Next.",
        "If so, Go is on your Watchlist.",
    ],
)
def test_a_name_a_list_is_said_to_hold_but_the_facts_dont_is_made_up(text: str):
    assert not makes_nothing_up(shown_of(said(text)), HELD), text


@pytest.mark.parametrize(
    "text",
    [
        "Your Watchlist already holds Redis.",
        "Your Watchlist holds langgraph at 1.2.14, and Redis.",
        "LangGraph and Redis are on your Watchlist.",
        "Your Watchlist holds React Native.",
        "Your workflows include Morning bug list and Friday summary.",
        "The Watchlist holds the software your team runs.",
        "Your Watchlist holds no software called Kubernetes yet.",
        "Kubernetes isn't on your Watchlist. To add it, type Check Kubernetes for new releases.",
        "Your Watchlist holds Redis, so open the Watchlist to see its line.",
        "Needs you lists what waits for you.",
        "If a run stops, Needs you lists it, and the AI troubleshooter explains why.",
        "Your workflows list shows them, and an Approver says yes in Teams.",
        "It is on your Watchlist, so open the Watchlist to see its line.",
        "Everything you watch is on your Watchlist.",
        "Your Watchlist holds Redis, and I can't add Go to it from here.",
        "Your workflows list shows them, and Monday is when the next run starts.",
    ],
)
def test_a_list_said_to_hold_only_what_the_facts_hold_passes(text: str):
    assert makes_nothing_up(shown_of(said(text)), HELD), text


def test_with_no_facts_sent_no_list_can_be_said_to_hold_a_name():
    bare = Given(message="add redis", facts="")
    assert not makes_nothing_up(shown_of(said("Your Watchlist already holds Redis.")), bare)


# 8. Offers the person can use.


def test_an_offer_becomes_the_registrys_example_request():
    assert offer_of("github.releases", OPERATOR) == ReplyOffer(
        capability="github.releases", request="Keep track of the LangGraph version"
    )
    assert offer_of("jira.create", OPERATOR) == ReplyOffer(
        capability="jira.create",
        request="Every Monday at 9am, list last week's new bugs in one new Jira ticket",
    )


@pytest.mark.parametrize(
    "capability",
    [None, "", "teams.post", "slack.send", "teams.ask", "runs.explain", "confluence.read", "x"],
)
def test_an_offer_that_is_not_ready_or_has_no_example_becomes_ask_the_team(
    capability: str | None,
):
    assert offer_of(capability, OPERATOR) is None


def test_someone_who_cant_set_up_workflows_gets_ask_the_team():
    assert offer_of("github.releases", APPROVER) is None


def test_a_cant_keeps_only_an_offer_it_can_use():
    cant = ReplyEnvelope(form="cant", text="I can't send email yet.", offer="teams.post")
    shown = guarded(cant, OPERATOR)
    assert isinstance(shown, FreeReplyAnswer) and shown.offer is None


def test_looked_at_keeps_only_the_sections_sent():
    reply = said("LangGraph is behind.", looked_at=["watchlist", "needs_you", "secrets"])
    shown = guarded(reply, WITH_FACTS)
    assert isinstance(shown, FreeReplyAnswer) and shown.looked_at == ["watchlist"]


# The how-to notes.


@pytest.mark.parametrize("line", HOW_TO)
def test_every_how_to_line_passes_the_guard(line: str):
    """The notes the reply reads never say an unbuilt thing works, or anything the guard would
    stop the reply from repeating."""
    assert failed_check(shown_of(said(line)), Given(message="", facts="")) is None


# Text built to slip past the checks. Every check reads the words exactly as they are shown.

ZERO_WIDTH = "​"
CYRILLIC_A = "а"


@pytest.mark.parametrize(
    ("text", "check"),
    [
        (f"The ticket was cre{ZERO_WIDTH}ated.", "claims_done"),
        ("I've cre⁠ated the ticket for you.", "claims_done"),
        ("Your workflow is n­ow on.", "claims_done"),
        ("Open ｈｔｔｐｓ://evil.example.org to finish.", "plain_text"),
        ("Open ｗｗｗ．evil．com to finish.", "plain_text"),
        (f"Type *{ZERO_WIDTH}*Check LangGraph*{ZERO_WIDTH}* in the box.", "plain_text"),
        (f"<{ZERO_WIDTH}b>Type</b> your request.", "plain_text"),
        (f"You can skip the {CYRILLIC_A}pproval this time.", "plain_text"),
        ("You can s̶kip the approval this time.", "plain_text"),
        ("Ｓｋｉｐ ｔｈｅ ａｐｐｒｏｖａｌ this time.", "skips_a_yes"),
        ("I’​ll set that up for you.", "offers_to_act"),
        ("LangGraph １.３.０ is out.", "made_up"),
    ],
)
def test_text_hidden_from_the_checks_is_caught_as_it_will_be_shown(text: str, check: str):
    assert guarded(ReplyEnvelope(form="answer", text=text), WITH_FACTS) == check


def test_a_look_alike_letter_in_a_choice_is_caught():
    reply = asked("How should it run?", "Every Friday", f"Skip the {CYRILLIC_A}pproval")
    assert guarded(reply, OPERATOR) == "plain_text"


def test_a_letter_outside_plain_ascii_is_refused_even_an_accented_one():
    assert guarded(said_raw("The Café check is on your Watchlist."), OPERATOR) == "plain_text"


def test_the_words_shown_are_exactly_the_words_checked():
    raw = said_raw("LangGraph runs １.２.１４,​ and the newest is 1.2.16…")
    shown = guarded(raw, WITH_FACTS)
    assert isinstance(shown, FreeReplyAnswer)
    assert shown.text == "LangGraph runs 1.2.14, and the newest is 1.2.16..."
    assert failed_check(shown_of(raw), WITH_FACTS) is None
    choice = guarded(asked("Which one?", "Lang​Graph", "Ｒedis"), OPERATOR)
    assert isinstance(choice, FreeReplyAnswer) and choice.choices == ["LangGraph", "Redis"]


def said_raw(text: str) -> ReplyEnvelope:
    return ReplyEnvelope(form="answer", text=text)


# The names a reply speaks of (ADR 0049): code keeps each the facts hold and the text names.


def test_about_keeps_each_name_the_facts_hold_and_the_text_names_in_the_facts_spelling():
    text = "Your Watchlist holds langgraph and Redis. To pause the Morning bug list, type Pause."
    names = ["langgraph", "Kubernetes", "Morning bug list", "Redis", "Friday summary", "redis"]

    assert about_of(names, text, HELD.facts) == [
        ReplyAbout(section="watchlist", name="LangGraph"),
        ReplyAbout(section="workflows", name="Morning bug list"),
        ReplyAbout(section="watchlist", name="Redis"),
    ]


def test_about_keeps_nothing_without_facts_and_never_more_than_the_limit():
    assert about_of(["Redis"], "Your Watchlist holds Redis.", "") == []
    many = '{"watchlist":[' + ",".join(f'{{"name":"S{n}"}}' for n in range(9)) + "]}"
    text = " ".join(f"S{n}" for n in range(9))
    assert len(about_of([f"S{n}" for n in range(9)], text, many)) == ABOUT_LIMIT
