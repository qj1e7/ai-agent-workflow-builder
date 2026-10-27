---
status: proposed
---

# Cross-check versions and known vulnerabilities across a fixed list of trusted sources

ADR 0019 made GitHub releases the only source for the software watchlist, and said each new source would get its own ADR. That is too narrow for what a support team runs. Java libraries are published on Maven Central, Python packages on PyPI, and server software as Docker images. One source can also be wrong or late. A version can be tagged on GitHub before it reaches the registry the team installs from. The sponsor's pain point is "software version and patch housekeeping", and the part that matters most is security. A newer version alone does not say whether upgrading is urgent.

So the watchlist gets two specialist agents, both defined by agent cards (ADR 0023). The Planner brings them into any workflow about software versions or vulnerabilities. Today that is the weekly check, and a request like "tell us when our software has a critical vulnerability" is sent to the watchlist, as release checks already are. Both agents read the watchlist as their list of what the team runs.

**The Version checker** replaces the release checker.
- It reads each watched software's newest version from the registry the team installs it from: Maven Central, npm, PyPI, NuGet or Docker Hub. For projects that publish nowhere else, it reads GitHub releases.
- It cross-checks GitHub. If the two disagree, the registry the team installs from wins, and the difference is shown. For example, "GitHub shows 0.120.2, not on PyPI yet."
- It reads support dates from endoflife.date, so the watchlist shows versions whose security fixes end soon.
- When an Operator doesn't know where a piece of software is published, it searches that vendor's official site and suggests a source. A person confirms the suggestion before any check uses it.

**The Vulnerability checker** looks only at the version the team runs.
- It finds known vulnerabilities in OSV.dev, which matches packages by ecosystem, name and version.
- It reads each one's official record and severity score from NVD, and checks the vendor's own advisory where there is one.
- It checks CISA's Known Exploited Vulnerabilities list.
- It merges findings by CVE number, and each finding shows which sources reported it.
- A vulnerability that is critical (CVSS 9.0 or higher) or on CISA's list marks the upgrade ticket as urgent. The ticket still waits for an Approver, like any other.

Every source above is read by a tool the team builds and tests (ADR 0023). All of them only read, so none needs approval.

## Considered options

- **Search the whole web for versions and vulnerabilities.** It would find more, but blogs and copy sites often show old or wrong numbers. Two searches can disagree, which an Approver cannot check. Every page an agent reads could also carry planted instructions. So web search is used only to suggest a source, only on the vendor's own site, and a person confirms the result.
- **NVD alone.** NVD is the official source, but it matches products by CPE names. Each watched software would need its CPE name found and confirmed by a person. In 2024 NVD also fell behind on adding CPE data to new CVEs.
- **OSV alone.** Matching is easy, but severity would come from the advisory, not from NVD, and nothing would say whether a flaw is being exploited.
- **One agent for both jobs.** It would be simpler. But reading versions and looking up vulnerabilities fail for different reasons, use different tools, and are useful on their own.
- **Scanning the team's own build files**, such as a Maven `pom.xml`. It would find versions without anyone typing them, but it needs access to CODESparks' code inside DevNet. That is Phase 2, as ADR 0019 already says.

## Consequences

- **The source list is fixed.** The watched-software contract gains the source kinds `maven`, `npm`, `pypi`, `nuget` and `docker`, and the Version checker picks its reader by kind. This ADR covers the sources listed here. A source not on the list is a new external dependency and needs its own ADR.
- **"Suggest a source" needs the AI model,** whose choice is still open. Its search is limited to the vendor's site, and it can only suggest.
- **Rate limits.**
  - NVD allows about 5 requests every 30 seconds without a key, and 50 with a free key. The key is a secret, so it lives in Key Vault.
  - OSV has a batch query.
  - CVE details and CISA's list can be cached between checks.
  - A weekly check of about 40 tools fits.
- **Wrong matches are possible.** OSV matches some versions loosely. Every urgent ticket links the CVE record, CISA's list and the vendor's advisory, so the Approver can check the evidence first.
- **Gaps.** endoflife.date does not cover every product, so some tools show no support date. A vulnerability with no fixed version yet cannot raise an upgrade ticket, and what happens then is left for later.
- **DevNet.** These are public internet services. Inside DevNet they need an allowed outbound route or an internal mirror (ADR 0005).
- **Terms of use.** Check each data source's terms of use before handover.
- **Glossary.** `GLOSSARY.md` gains **Known vulnerability** and **End of life**, and **Source** now covers every registry above.
- **Code.** The release checker template becomes the Version checker card. Renaming it in code is a separate change.
