"""Text we did not write, made so no reader can follow it: the runtime's copy of platform-api's
teams.inert (ADR 0036), for the Teams card and the email the cert list parser builds.

Teams says every card text field takes basic markdown, so a cert name written on a Confluence page
as [renew](https://example.com) would be a link in the card. Characters shown as nothing go first,
so none can split a marker. Then every "://" becomes "[:]//" with the dots of the address after it
broken, a "www." that starts a host becomes "www[.]" with the host's dots broken, every "mailto:"
loses its colon, and a markdown link loses its "](". Any case counts.
"""

import re
import unicodedata
from typing import Final

_IGNORABLE_MARKS: Final = frozenset("͏ᅟᅠ឴឵ㅤﾠ")
_TOKEN: Final = r"[^\s<>()\[\]]*"
_AFTER_SCHEME: Final = re.compile(r"://(" + _TOKEN + ")")
_WWW_HOST: Final = re.compile(r"(?i)(?<![/.])(www)\.(?=[^\W_])(" + _TOKEN + ")")
_MAILTO: Final = re.compile(r"(?i)mailto:")


def _visible(text: str) -> str:
    return "".join(
        c
        for c in text
        if unicodedata.category(c) != "Cf"
        and c not in _IGNORABLE_MARKS
        and not ("︀" <= c <= "️" or "\U000e0100" <= c <= "\U000e01ef")
    )


def inert(text: str) -> str:
    text = _visible(text)
    text = _AFTER_SCHEME.sub(lambda m: "[:]//" + m.group(1).replace(".", "[.]"), text)
    text = _WWW_HOST.sub(lambda m: m.group(1) + "[.]" + m.group(2).replace(".", "[.]"), text)
    text = _MAILTO.sub(lambda m: m.group(0)[:6] + "[:]", text)
    return text.replace("](", "] (")
