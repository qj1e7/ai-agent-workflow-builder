# Model bake-off

The AI model provider is an open decision (`AGENTS.md`). This folder holds the evidence for that choice: a golden set of the jobs a model would do in this product, deterministic scoring, and the scores of every model we could run. It does not pick a provider. The decision memo is in [decision-memo.md](decision-memo.md). Why the eval tools sit apart from the runtime is in [ADR 0017](../../adr/0017-score-model-providers-with-an-eval-only-dependency-group.md).

## The jobs

A model has three jobs in the product today. Each one maps to code that already exists.

| Job | What the model does | Where it sits in the code | Output |
|---|---|---|---|
| `summarise` | Writes the Release checker's one-sentence finding about new releases. | `agent_runtime/summary.py`, behind the existing `AGENT_SUMMARY_MODEL` switch. The harness sends the runtime's own prompt (`summary_prompt`). | Plain text |
| `explain` | Tells a non-technical Operator what went wrong in a run, and whether a retry is safe. | The AI troubleshooter. Today a fixed rule table answers (`platform-api/.../monitoring/troubleshooter.py`). | Structured: `explanation`, `retry_safe` |
| `match` | Picks the template for an Operator's plain-English sentence and fills its parameters. | The builder's suggest route. Today a keyword match answers (`builder/templates.py`, `suggest_template`). | Structured: `template`, `params` |

Two things are left out on purpose:

- **Room lead routing.** The Room lead staffs one specialist, the Release checker, every time (`room.py`, `FixedRoomLead`). There is no choice for a model to make yet, so there is no job for it.
- **The ticket body.** The Release checker builds it in code (`_ticket` in `release_checker.py`). No model writes it, so no case scores it.

## The golden set

The cases are data files in `agent-runtime/evals/cases/`. They come from the recorded fixtures in `contracts/fixtures/` plus realistic variations.

| Job | Cases | What they cover |
|---|---|---|
| `summarise` | 12 | One release, two (the recorded run), many, twelve (tests the length cap), minor and major bumps, `v` prefixes, `package==version` and `name@version` tags, versions that differ only in the last digits, a repo with no display name. |
| `explain` | 13 | GitHub 503 (the recorded run), 502, unreachable, 404 from a misspelled repo, 403 from a private repo, a Jira 503 and a Jira timeout after approval, a declined run, a timeout, a workflow step error, a safety checker block, an out-of-order step, an action the template cannot carry out. |
| `match` | 13 | The recorded instruction, full and casual sentences, a `v`-prefixed starting tag, a GitHub link instead of `owner/name`, two vague requests, and five requests that fit no template (the access review, a Confluence edit, a password reset, a meeting room, GitLab runners). |

There is no "no new release" case. When nothing is new, the Release checker writes "No new releases since X" itself and never calls the model.

For `explain`, the model sees the run's activity log and how it ended, but not the platform's own `retryable` flag. Seeing that flag would make "retry safe" a copy job. The truth for each case comes from the platform: `retryable` on the failure (`orchestration/service.py`), and false for a declined run.

## Scoring

Every check is deterministic. A case passes only when all of its checks pass. The pass rate is passed cases over all cases.

| Check | Jobs | Fails when |
|---|---|---|
| `answered` | all | The model raised an error or its structured answer did not parse. |
| `usable_by_product` | summarise | The answer is empty, has a line break, or is over 300 characters. The runtime would throw it away and use its template instead. |
| `every_new_version` | summarise | A new version number is missing. A tag counts by its version number, so `v1.10.0` counts as `1.10.0`. |
| `required_facts` | explain | A fact the case names is missing, such as the system that failed and the kind of failure. Each fact lists the plain words that count. |
| `retry_safe_matches` | explain | `retry_safe` differs from the truth. |
| `length_cap` | explain | The explanation is over 500 characters. |
| `no_invented_version` | summarise, explain | The answer has a version number that is not in the input. |
| `no_invented_system` | summarise, explain | The answer names a system (GitHub, Jira, Confluence, Teams, PyPI and others) that is not in the input. |
| `no_jargon` | summarise, explain | The answer has a word from the jargon list (`API`, `HTTP`, `endpoint`, `payload`, `n8n`, the error type names and others), an HTTP status code such as `503`, or a code name such as `run_agents`. A summary may repeat a word from the repo's own name. |
| `no_themed_names` | summarise, explain | The answer uses one of the old themed names that `AGENTS.md` bans. |
| `no_write_claim` | summarise, explain | The answer says a ticket or page was created, opened or written, or names a ticket key such as `MOCK-142` that is not in the input. "No ticket was created" and "a ticket will be created" do not count. |
| `right_template` | match | The template is not the expected one. No template is the right answer for the five unrelated requests. |
| `params_valid` | match | A parameter breaks the builder's rule for it: `owner/name` for the repo, a Jira project key, a plain version for the last seen tag, and the one allowed tag pattern. |
| `required_params` | match | A value the sentence states is missing or different. |
| `no_invented_params` | match | The model filled a parameter the sentence does not state, such as a made-up project key. |

The match rules mirror `validate_params` in the builder. The agent runtime may not import the builder's code, so a unit test checks that the mirrored rules cover exactly the parameters the builder publishes in `contracts/fixtures/builder/templates.json`.

The unit tests in `agent-runtime/tests/test_eval_scoring.py` prove the scoring is fair in both directions. The runtime's own template summary passes every `summarise` case. Each `explain` case carries a reference answer that passes. The expected `match` answer passes. Each kind of flawed answer fails the check that names its flaw.

An LLM judge is optional and off by default. Set `EVAL_JUDGE=<provider>:<model>` to get a 1 to 5 score per `summarise` and `explain` answer. The score appears as `judge_mean` in `results.json`. It never changes a pass or a fail.

Each run also records median and p95 latency, mean input and output tokens, and the cost per 100 runs where the price is known. Prices live in `agent-runtime/evals/pricing.json` with their source and date. The p95 uses the nearest-rank method, so with 12 or 13 cases it is the slowest case.

## Results

We ran the full set twice on 23 October 2026 (Singapore time), one run straight after the other, on the two local Ollama models. Every cloud provider is "not run", because no key is set yet.

| Model | Job | Pass, run 2 | Pass, run 3 | Median seconds (run 2 / run 3) | p95 seconds (run 2 / run 3) | Mean tokens in / out | $ per 100 runs |
|---|---|---|---|---|---|---|---|
| `gemma:2b` | summarise | 1/12 | 1/12 | 0.3 / 0.3 | 0.4 / 0.5 | 94 / 27 | 0 |
| `gemma:2b` | explain | 3/13 | 3/13 | 0.9 / 0.9 | 1.3 / 1.3 | 300 / 37 | 0 |
| `gemma:2b` | match | 0/13 | 0/13 | 1.6 / 1.6 | 1.8 / 1.8 | 354 / 74 | 0 |
| `deepseek-r1:latest` | summarise | 11/12 | 11/12 | 5.3 / 6.1 | 30.0 / 34.1 | 73 / 543 | 0 |
| `deepseek-r1:latest` | explain | 7/13 | 7/13 | 8.7 / 7.5 | 10.4 / 9.0 | 550 / 52 | 0 |
| `deepseek-r1:latest` | match | 11/13 | 11/13 | 8.4 / 7.9 | 15.2 / 13.7 | 632 / 26 | 0 |

Not run: Azure OpenAI, Anthropic and Google Gemini (no key set).

The cost is 0 for Ollama because there is no charge per token. The laptop and its power are not counted. What each model gets wrong is in the [decision memo](decision-memo.md).

### The spread between runs

- The pass rates are the same in both runs, for every model and every job.
- Every answer is the same, word for word: 76 of 76 (38 cases for each of the 2 models). Ollama runs at temperature 0 with a fixed seed, so these two models repeat themselves on this machine. Cloud models run without a fixed temperature, so their answers may vary more.
- The latency moves. `gemma:2b` stays within 0.1 seconds. The median for `deepseek-r1` moves by up to 1.2 seconds, and its slowest answer by up to 4.1 seconds. The answers and the token counts did not change, so this spread comes from the machine, not the model.
- Each full run took about 6.5 minutes, including the build of the eval image.

### What changed since run 1

Run 1 was on 22 October, before a fix to the cases. It scored `gemma:2b` 1/12, 2/13 and 0/13, and `deepseek-r1` 11/12, 6/13 and 11/13. The answers in runs 2 and 3 are word for word the same as in run 1. Only the scoring of two `explain` cases changed:

- **declined.** The check wanted the approver's name, Bob. Both models wrote that "the team approver" declined, which is correct and plain. "approver" now counts. The case now passes for both models. This is the whole change in the scores: `explain` went from 2 to 3 for `gemma:2b`, and from 6 to 7 for `deepseek-r1`.
- **unbound-intent.** The check accepted "isn't set up" but not the past tense. `deepseek-r1` wrote "wasn't properly set up". Now "wasn't set up", "was not set up" and "properly set up" count. This changed no score. Both models still fail the case, because they repeat the code name `create_page`.

We made both changes after reading the answers from run 1. That carries a risk: a check bent to fit one model. They stand because each answer was right and the list of accepted words was too narrow. The new words count the same way for every model.

`deepseek-r1` was a little slower in run 1 (a median of 10.3 seconds for `explain` and 9.5 seconds for `match`). Run 1 ran at another time, and we did not record how busy the machine was.

### Checks that may be wrong, left as they are

- **timed-out.** `gemma:2b` wrote "failed to come back". The list accepts "did not come back" but not this. It is the same kind of gap as "wasn't set up". Adding it would change no score, because `gemma:2b` also fails that case on the retry answer and on jargon (`TimedOut`). We left it for the team lead to decide.
- **The two Jira failures after approval.** The check wants the answer to say the request was approved. The answers from `deepseek-r1` are accurate and plain, but they do not say it. That costs `deepseek-r1` two of its six `explain` failures. The rule can be defended, because the Operator should know the approval still stands and only the Jira step failed. But it is a judgment call, and the team lead should confirm it.
- **A wrong cause can pass.** `gemma:2b` passed `safety-denied` while it blamed "a digest mismatch between the last known tag and the newly fetched releases". That cause is wrong. The checks catch invented versions, systems and ticket keys, and claims that a ticket was written. They do not catch a wrong story. The optional LLM judge or a person reading the answers can.
- **Always "not safe".** `gemma:2b` said a retry was not safe in all 13 cases. Its 6 right answers on retry are exactly the 6 cases where "not safe" is true. Read that score as a guess, not a skill.

## What limits the local numbers

- **Model size.** `gemma:2b` has 3 billion parameters, stored at 4 bits (Q4_0). `deepseek-r1:latest` has 8.2 billion (Qwen3 architecture), stored at 4 bits (Q4_K_M). Cloud models are much larger.
- **Hardware.** An Apple M3 Max laptop with 16 cores and 128 GB of memory, running Ollama 0.15.4. `ollama ps` showed both models fully on the laptop's GPU. A DevNet server without a GPU would be much slower.
- **Warm, not cold.** The harness sends each model one warm-up call before it times anything, so loading the model is not in the latency. The warm-up took 0.8 to 1.6 seconds for `gemma:2b` and 3.7 to 4.5 seconds for `deepseek-r1`. Each answer is timed inside a Docker container that calls Ollama on the host, which adds a little.
- **Thinking.** `deepseek-r1` reasons before it answers. A one-sentence summary used 543 output tokens on average. That is where its time goes.
- **One at a time.** The cases run one after another. We did not test many runs at once.
- **A busy machine.** Both runs waited until the team's browser tests had finished. During the runs, the load average over one minute was between 0.5 and 5.9 on 16 cores.
- **Context size.** Ollama loaded both models with a context of 4,096 tokens. The longest prompt is about 630 tokens, so nothing was cut off.

## What is not measured yet

- Any cloud model. Azure OpenAI, Anthropic and Google Gemini stay "not run" until someone adds a key.
- How good the wording is. The LLM judge is off, and no person has rated the answers.
- Larger local models, and the hardware DevNet would really have.
- The cost on Azure. `pricing.json` has no Azure prices yet, because the deployment and region are not chosen.
- Rate limits and quotas on the student subscription, and many runs at the same time.
- Room lead routing and the ticket body, because no model does them in the product today.
- Other prompts. Each job has one prompt, and we did not tune it for any model.

## Add a cloud provider and rerun

You need Docker and the provider's key. Nothing else. The script passes each setting to the container by name, so the key never shows on the command line, in the output or in `results.json`. If a call fails, the harness also removes the keys, the Azure endpoint and the Ollama address from the error before it prints or saves it. Keep keys in your shell only. Never put them in a file in the repo.

1. Set the provider's variables in your shell. Use `read -s` so the key does not land in your shell history.

   **Azure OpenAI.** You need a deployment for each model you want to score. The deployment names are the ones you chose in Azure AI Foundry.

   ```sh
   read -s AZURE_OPENAI_API_KEY && export AZURE_OPENAI_API_KEY
   export AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
   export AZURE_OPENAI_API_VERSION=<the API version your resource supports>
   export AZURE_OPENAI_DEPLOYMENTS=<deployment-1>,<deployment-2>
   ```

   **Anthropic.** It scores `claude-haiku-5-5` and `claude-sonnet-5-5` unless you set `ANTHROPIC_MODELS`.

   ```sh
   read -s ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
   export ANTHROPIC_MODELS=claude-haiku-5-5,claude-sonnet-5-5
   ```

   **Google Gemini.** Name the models to score. Check the current model names in Google AI Studio.

   ```sh
   read -s GOOGLE_API_KEY && export GOOGLE_API_KEY
   export GOOGLE_MODELS=<model-1>,<model-2>
   ```

2. Run the bake-off from the repo root:

   ```sh
   scripts/evals.sh
   ```

   The local Ollama models run too. To skip them, run `OLLAMA_BASE_URL= scripts/evals.sh`.

3. Add the price of each new model to `agent-runtime/evals/pricing.json`, with the page you took it from and the date, then run again. Without a price, the cost column says "unknown". The key is `<provider>:<model>`, for example `azure_openai:<deployment-1>`.

4. Update the results table in this README from the printed table. Do not commit `results.json`. It holds every answer the models gave, word for word. To keep it as evidence, link the CI run's `eval-results` artifact from the PR.

Cloud models reject `temperature: 0` in some families (newer Claude models and reasoning models do). So the harness sends no temperature to cloud providers unless you set `EVAL_TEMPERATURE`. Ollama runs at temperature 0 with a fixed seed.

**In CI.** The `evals` workflow runs only when started by hand (Actions, then "evals", then "Run workflow"). Add the keys as repository secrets: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`. Add the model lists as repository variables: `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENTS`, `ANTHROPIC_MODELS`, `GOOGLE_MODELS`. A provider without its secret is reported as "not run" and the job still passes. The results are attached to the run as the `eval-results` artifact. Adding secrets changes repository settings, so a human does it.
