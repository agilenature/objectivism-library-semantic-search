# The Pre-Mortem Implementation Framework

## From "What Went Wrong?" to "What Will Go Wrong?" — With a Distrustful Agent Council

---

## The Core Inversion

A traditional post-mortem asks: *"What went wrong and why?"*
A pre-mortem asks: *"Assuming this has already failed — what killed it?"*

This framework takes that second question and makes it the **engine of planning and execution**, not just a thought exercise. The pre-mortem doesn't just inform the plan — it *becomes* the plan. Every assumption surfaced in the pre-mortem maps directly to a wave of implementation designed to validate or kill that assumption as fast as possible.

---

## Step 1: The Pre-Mortem Session

### Setup

Before any planning or estimation, the team gathers and is given a single premise:

> *"It is three weeks from now. This feature/project has failed. It shipped late, it doesn't work, or it works but solves the wrong problem. What happened?"*

Everyone writes independently first. No discussion. This is critical — group dynamics suppress the very risks you're trying to surface.

### The Failure Story

Each team member writes a brief "failure narrative" — not a list of risks, but a *story* of how things fell apart. Stories surface dependencies, sequences, and cascading failures that bullet-point risk lists miss.

Example: *"We assumed the third-party API returned paginated results the same way their docs described, but it didn't. We didn't find out until day 4 because we were building the UI first. By the time we rewrote the data layer, we had to throw away the state management we'd already built on top of it."*

### Extracting Assumptions

From the failure stories, the team extracts **assumptions** — things we are treating as true but have not verified. These fall into categories:

| Category | Examples |
|---|---|
| **Technical Integration** | "The API behaves as documented." "The response times will be under 200ms." "Auth tokens refresh the way we expect." |
| **Domain Understanding** | "We understand what the user actually needs on this screen." "The business rules around X are settled." |
| **Capability** | "We know how to use this library/framework." "The existing codebase can support this pattern." |
| **Environmental** | "The staging environment mirrors production." "We'll have access to test credentials by Monday." |
| **Scope** | "This feature doesn't require changes to Y." "The design is final." |

### Ranking by Risk

Each assumption is scored on two axes:

- **Uncertainty**: How confident are we that this assumption is true? (1 = very confident, 5 = no idea)
- **Impact**: If this assumption is wrong, how much work gets invalidated? (1 = trivial, 5 = catastrophic)

**Risk = Uncertainty × Impact**

The assumptions are then **stack-ranked by risk score**, highest first. This ranked list is the backbone of the entire implementation plan.

---

## Step 2: Planning (Driven by the Pre-Mortem)

### The Shift: From "What to Build" to "What to Prove"

Traditional sprint planning asks: *"What stories do we commit to delivering?"*

Pre-mortem planning asks: *"What assumptions do we need to have validated by when, and in what order?"*

The deliverables are the same — working software. But the *sequence* is radically different. Instead of building features top-down (UI → logic → integration), you build **assumption-out** — starting from the point of greatest ignorance and working toward certainty.

### The Implementation Phase (Replaces "Sprint")

An implementation phase is not a sprint. A sprint implies a predictable cadence of delivery. An implementation phase is an **uncertainty-reduction campaign** with a fixed timebox. It ends when:

- All critical assumptions are validated and the feature is built, or
- A critical assumption is invalidated and the team pivots with full knowledge of *why*

### Wave Structure

The implementation phase is divided into **waves**. Each wave is designed to answer one or more assumptions, starting with the riskiest.

```
┌─────────────────────────────────────────────────────────┐
│                  IMPLEMENTATION PHASE                    │
│                                                         │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌────────┐ │
│  │ WAVE 1  │──▶│ WAVE 2  │──▶│ WAVE 3  │──▶│ WAVE 4 │ │
│  │ Riskiest│   │         │   │         │   │ Safest │ │
│  │ Assump. │   │ Next    │   │ Next    │   │ Assump.│ │
│  └─────────┘   └─────────┘   └─────────┘   └────────┘ │
│       │              │             │             │       │
│   ┌───┴───┐     ┌───┴───┐    ┌───┴───┐     ┌───┴───┐  │
│   │COUNCIL│     │COUNCIL│    │COUNCIL│     │COUNCIL│  │
│   │ GATE  │     │ GATE  │    │ GATE  │     │ GATE  │  │
│   └───────┘     └───────┘    └───────┘     └───────┘  │
└─────────────────────────────────────────────────────────┘
```

**Each wave has a Council Gate.** You do not proceed to Wave 2 until Wave 1's assumption has been assessed by the Agent Council. If the assumption is invalidated, you don't "fail" — you've *succeeded* in learning something critical before wasting days of downstream work.

---

## Step 3: Wave Execution

### Wave Anatomy

Each wave has a clear structure:

**1. Assumption Statement**
Write it down explicitly. "We assume that the payments API returns a transaction ID synchronously upon successful charge."

**2. The Spike (Smallest Possible Test)**
Build the absolute minimum code required to prove or disprove the assumption. This is not a prototype. It's not a proof of concept. It's a **targeted experiment**.

For the example above: a single script that hits the payments API with a test charge and logs the response. Nothing else. No error handling, no UI, no architecture. Just: *does it do what we think it does?*

**3. The Evaluation Window**
Some assumptions can be validated in an hour. Others require waiting — for an external team to respond, for data to accumulate, for an environment to be provisioned. The wave accounts for this. While waiting, the team can do **non-dependent work** (documentation, tooling, lower-risk assumptions that don't block anything).

**4. The Council Gate** *(see "The Agent Council" below)*

---

## The Agent Council: The Innovation

### The Problem With Human-Only Gates

In the original framework, the gate decision is made by the development team. This works, but it has weaknesses: teams anchor on their initial plan, confirmation bias creeps into assumption validation ("it *mostly* worked, let's move on"), and the cognitive load of simultaneously writing code *and* assessing strategic risk is enormous.

### The Solution: A Council of Specialized Agents

When the team is working with programming agents — AI agents that can read code, execute spikes, analyze outputs, and reason about systems — the gate decision is no longer a meeting. It's a **council deliberation**.

At every wave gate, instead of a single agent or a single human making the call, a council of agents convenes. Each agent has a distinct role and a distinct question it must answer. The council's collective assessment determines what happens next.

---

## The Distrust Doctrine

### The Default Is "No"

This is the philosophical foundation of the entire gate mechanism, and it must be understood before the council roles make sense:

> **The council's default position is that the spike did not work. The burden of proof lies entirely on the evidence to overcome that default.**

This is not cynicism. It is not pessimism. It is a deliberate epistemic posture borrowed from disciplines where false confidence kills:

- **Medicine:** A drug is assumed ineffective and harmful until clinical trials prove otherwise. The FDA doesn't ask "did this drug work?" — it asks "can you prove, beyond our distrust, that this drug works?"
- **Aviation:** Every system is assumed to fail. Redundancy isn't added because something *might* go wrong — it's added because something *will* go wrong and you need proof that the backup works before you trust the primary.
- **Law:** The accused is presumed innocent. The prosecution must overcome that presumption with evidence. The jury doesn't start neutral — it starts distrustful of the prosecution's claims.

Software development — especially when integrating with external systems, unfamiliar technologies, or poorly documented APIs — deserves the same posture. **The spike is the prosecution. The gate is the jury. And the jury starts distrustful.**

### Why Distrust, Not Neutrality?

A neutral gate asks: *"What happened?"*
A distrustful gate asks: *"Why should we believe what happened is real, repeatable, and sufficient?"*

The difference is enormous in practice. A neutral gate accepts a 200 OK response from an API and says "it works." A distrustful gate asks:

- Was that a cached response?
- Will it return 200 under different auth conditions?
- Will it return 200 at 10x the request volume?
- Will it return 200 tomorrow, or was this a test endpoint that gets rotated?
- Did we actually read the response body, or just the status code?
- Did we test it once, or did we test it enough times to distinguish signal from luck?

**Distrust is the engine that generates verification steps.** Without it, verification is shallow. With it, verification is driven by the question: *"What would it take to fool us into thinking this works when it doesn't?"*

### The Distrust Spectrum

Not all assumptions require the same level of distrust. The council calibrates its skepticism based on the risk score from Step 1:

```
RISK SCORE    DISTRUST LEVEL    GATE POSTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  20-25       HOSTILE            "Prove it works under adversarial
                                  conditions. We actively try to
                                  break it before we believe it."

  13-19       SKEPTICAL          "Prove it works beyond the happy
                                  path. Show us failure cases that
                                  didn't fail."

   7-12       CAUTIOUS           "Prove it works as claimed. Show
                                  us the evidence, not just the
                                  assertion."

   1-6        WATCHFUL           "Confirm it works. A single clean
                                  test is probably sufficient, but
                                  document it."
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

At **HOSTILE** distrust, the council doesn't just review results — it actively designs counter-tests. "You say the API returns consistent pagination? Let me hit it with 50 concurrent requests with overlapping cursors and see if the results are still consistent." The council is trying to *break* the assumption, not confirm it.

At **WATCHFUL** distrust, a clean test result with documented evidence is sufficient. But even here, the gate never accepts "it seemed to work" or "no errors were thrown." There must be positive evidence of correct behavior, not merely an absence of observed failure.

### The Three Requirements for Gate Passage

No matter the distrust level, every assumption must clear three hurdles to pass the gate:

**1. Positive Evidence (Not Absence of Failure)**

The spike must produce **affirmative proof** that the assumption is true — not merely the absence of evidence that it's false.

```
INSUFFICIENT: "We called the API and didn't get an error."
SUFFICIENT:   "We called the API, received a 200 with a response
               body matching the documented schema. We parsed the
               transaction ID from the response and used it in a
               subsequent call, which also succeeded. Here are
               both response bodies."
```

"It didn't break" is not evidence that it works. A silent failure — an API that returns 200 with an empty body, a WebSocket that connects but never sends data, a pagination cursor that works but silently drops records — passes a "no errors" check but fails a "positive evidence" check.

**2. Reproducibility (Not a Single Observation)**

The spike must demonstrate that the result is repeatable, not a one-time artifact of timing, caching, test data, or environment state.

```
INSUFFICIENT: "We ran it once and it worked."
SUFFICIENT:   "We ran it 20 times across a 30-minute window.
               18/20 succeeded. 2 returned 503 (service
               unavailable). Average latency: 340ms.
               P95 latency: 890ms. Results consistent
               across runs."
```

The distrust level determines the reproduction threshold. At HOSTILE, the council may demand hundreds of runs, different times of day, different payload sizes. At WATCHFUL, 3-5 consistent runs may suffice. But one run is never enough.

**3. Boundary Testing (Not Just the Happy Path)**

The spike must test at least one condition *outside* the expected happy path. What happens at the edges?

```
INSUFFICIENT: "We fetched page 1 of results successfully."
SUFFICIENT:   "We fetched pages 1, 2, and 3. We also tested:
               - Page 0 (returned 400, as expected)
               - A page beyond the last (returned empty array,
                 not an error — this affects our UI logic)
               - A request with an expired cursor (returned 401,
                 not 400 — our error handling needs to account
                 for this)"
```

The distrustful question is always: *"What happens when the input isn't perfect?"* Because in production, the input is never perfect.

---

### Council Composition

```
┌──────────────────────────────────────────────────────────────────┐
│                    THE DISTRUSTFUL COUNCIL                        │
│                                                                  │
│  Default posture: "This did not work. Prove us wrong."           │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐      │
│  │  RISK AGENT  │  │  STRATEGY    │  │  RESULTS AGENT    │      │
│  │              │  │  AGENT       │  │                   │      │
│  │ "What could  │  │              │  │ "What did the     │      │
│  │  still go    │  │ "What are    │  │  spike actually   │      │
│  │  wrong that  │  │  our options │  │  prove — and what │      │
│  │  we haven't  │  │  if this     │  │  didn't it prove  │      │
│  │  thought of?"│  │  isn't real?"│  │  that it should   │      │
│  │              │  │              │  │  have?"           │      │
│  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘      │
│         │                 │                    │                 │
│         └────────┬────────┴────────────────────┘                 │
│                  ▼                                               │
│         ┌────────────────┐                                       │
│         │  NEXT-STEP     │                                       │
│         │  AGENT         │                                       │
│         │                │                                       │
│         │ "Is the burden │                                       │
│         │  of proof met? │                                       │
│         │  What must we  │                                       │
│         │  do next to    │                                       │
│         │  increase our  │                                       │
│         │  confidence?"  │                                       │
│         └────────────────┘                                       │
└──────────────────────────────────────────────────────────────────┘
```

### The Four Council Roles (Under the Distrust Doctrine)

---

#### 1. The Results Agent

**Core Question:** *"What did the spike actually prove — and what didn't it prove that it should have?"*

**Distrust Lens:** The Results Agent is the forensic investigator. It treats the spike output like a crime scene — every piece of evidence is catalogued, but the absence of evidence is catalogued too. It actively looks for what's *missing* from the results, not just what's present.

The Results Agent operates with the assumption that **the spike's own design may be flawed.** A spike that tests the wrong thing and passes is more dangerous than a spike that tests the right thing and fails. So the Results Agent asks:

- Did the spike actually test the assumption, or did it test something adjacent?
- Is the evidence **positive** (we observed correct behavior) or **negative** (we didn't observe incorrect behavior)? These are not the same thing.
- What did we *not* test that the assumption implicitly requires?
- Could the results be explained by something other than the assumption being true? (Caching, test fixtures, sandbox behavior, rate limiting not yet triggered)

**Output:** A findings report with an explicit **evidence gap analysis**:

```
ASSUMPTION: "The API supports cursor-based pagination."

TEST EXECUTED: Fetched 3 sequential pages using cursor tokens.

POSITIVE EVIDENCE:
  ✓ Pages 1-3 returned 200 with valid JSON
  ✓ Each response included a next_cursor field
  ✓ Records across pages did not overlap (verified by ID)
  ✓ Tested 5 times across 20 minutes — consistent results

EVIDENCE GAPS (what we did NOT prove):
  ✗ Did not test behavior when underlying data changes between
    page requests (cursor stability under mutation)
  ✗ Did not test cursor expiration (how long is a cursor valid?)
  ✗ Did not test behavior at the last page (does it return
    null cursor, empty cursor, or omit the field?)
  ✗ Did not test with concurrent pagination requests
    (cursor isolation between sessions)
  ✗ Only tested with default page size — did not test custom
    page sizes or maximum record limits

EVIDENCE QUALITY: MODERATE
  3 of 5 reproducibility runs. 0 boundary conditions tested.
  Positive evidence present but narrow.

DISTRUST CHALLENGE: "The happy path works. We have no idea
  what happens off the happy path."
```

The **Distrust Challenge** at the bottom is a required field. The Results Agent must articulate, in plain language, the strongest reason to *not* believe the assumption is validated. This forces the agent to argue against its own findings.

---

#### 2. The Risk Agent

**Core Question:** *"What could still go wrong that we haven't thought of?"*

**Distrust Lens:** The Risk Agent reads the Results Agent's findings and its evidence gap analysis, and it asks the most paranoid question possible: *"If I were actively trying to make this project fail, what would I exploit right now?"*

The Risk Agent's distrust is not directed at the team — it's directed at **reality**. Reality doesn't cooperate with your assumptions. APIs change without notice. Documentation lies. Test environments behave differently from production. The Risk Agent's job is to imagine all the ways reality will betray the team's confidence.

Specifically, the Risk Agent:

- Takes each evidence gap from the Results Agent and assigns it a **betrayal probability** — how likely is this gap to become a real problem?
- Identifies **hidden coupling** — assumptions that look independent but are actually connected. ("If pagination cursors expire, and our UI lazy-loads pages on scroll, we have a silent data loss bug that won't show up until real users with slow scroll speeds hit the feature.")
- Generates **adversarial scenarios** — not just "what if this doesn't work?" but "what if this *appears* to work in testing but fails in production in a way we won't detect for days?"
- Assesses whether the current distrust level is **calibrated correctly.** Maybe the spike revealed that this assumption is more dangerous than originally scored. The Risk Agent can recommend escalating the distrust level.

**Output:** A risk assessment that explicitly maps evidence gaps to potential failures:

```
RISK ASSESSMENT — WAVE 2 GATE

BASED ON: Results Agent findings (evidence quality: MODERATE)

EVIDENCE GAP → FAILURE SCENARIO MAPPING:

1. Cursor stability under mutation → BETRAYAL PROBABILITY: HIGH
   Scenario: User is paginating through transactions. A new
   transaction arrives between page 2 and page 3 requests.
   Cursor shifts. User either sees a duplicate record or
   misses one entirely. Neither produces an error.
   Detection difficulty: VERY HARD (silent data inconsistency)

2. Cursor expiration → BETRAYAL PROBABILITY: MEDIUM
   Scenario: User leaves tab open, returns 30 minutes later,
   clicks "next page." Cursor has expired. API returns... what?
   We don't know. Could be 400, 401, 500, or stale data.
   Detection difficulty: MODERATE (would surface as user-reported bug)

3. Last-page behavior → BETRAYAL PROBABILITY: LOW
   Scenario: UI attempts to fetch a next page that doesn't exist.
   If the API omits the cursor field instead of returning null,
   our code may throw an undefined reference error.
   Detection difficulty: EASY (would surface in QA)

DISTRUST LEVEL RECOMMENDATION: ESCALATE from SKEPTICAL to HOSTILE
  Rationale: Gap #1 (cursor stability) is a silent data integrity
  issue. These are the most dangerous class of bug — they don't
  announce themselves. This assumption needs adversarial testing
  before we proceed.

RECOMMENDED ADVERSARIAL TESTS:
  - Insert a record via a second client during active pagination
  - Expire a cursor by waiting (or by manipulating clock/tokens)
  - Request page_size=1 and page_size=10000 to test boundaries
  - Paginate with two concurrent sessions using the same query
```

---

#### 3. The Strategy Agent

**Core Question:** *"What are our options if this isn't real?"*

**Distrust Lens:** The Strategy Agent takes the distrust posture to its strategic conclusion. While the Results Agent asks "do we have proof?" and the Risk Agent asks "what could betray us?", the Strategy Agent asks: *"What's our plan for each possible world?"*

The Strategy Agent generates options not from a neutral starting point but from the distrustful premise that **the current evidence may not hold.** This means every option set includes at least one path that assumes the spike results are misleading:

- **Option A: Conditional Proceed.** The evidence passes the gate, *but* we build the next wave with explicit rollback points in case the current assumption fails under production conditions.
- **Option B: Deepen Before Proceeding.** The evidence is insufficient at the current distrust level. Run the adversarial tests the Risk Agent recommended before moving forward. Accept the time cost.
- **Option C: Proceed With a Safety Net.** Accept the current evidence but design the architecture so that if the assumption fails later, the blast radius is contained. (Feature flags, fallback paths, abstraction layers that allow swapping the integration.)
- **Option D: Pivot.** The evidence, combined with the risk assessment, suggests this approach is fundamentally fragile. Here are alternative architectures that carry different assumption chains.
- **Option E: Escalate.** The findings require a decision beyond the team's scope.

The critical innovation: **Option A is never "proceed with full confidence."** Even when the gate passes, the Strategy Agent builds distrust into the forward path. Confidence is earned incrementally over waves, not granted at a single gate.

**Output:** A set of strategic options, each with an explicit **confidence prerequisite** — what would need to be true for this option to be safe.

---

#### 4. The Next-Step Agent

**Core Question:** *"Is the burden of proof met? What must we do next to increase our confidence?"*

**Distrust Lens:** The Next-Step Agent is the only agent that can recommend proceeding — and it treats that recommendation as a serious act. It operates under a principle borrowed from engineering ethics:

> **"If this recommendation is wrong and the assumption fails in production, can I point to the evidence that justified this decision?"**

The Next-Step Agent doesn't just synthesize — it **stress-tests its own recommendation against the distrust criteria:**

1. **Positive Evidence Check:** Did the Results Agent find affirmative proof, not just absence of failure?
2. **Reproducibility Check:** Was the result demonstrated multiple times under varied conditions?
3. **Boundary Check:** Was at least one non-happy-path condition tested?
4. **Risk Acceptance Check:** Are the residual risks identified by the Risk Agent acceptable? Are the betrayal probabilities low enough? Are the failure scenarios detectable?
5. **Confidence Trajectory Check:** Is our confidence *increasing* across waves? Or are we accumulating unresolved risks that compound?

Only when all five checks are satisfied does the Next-Step Agent recommend proceeding. If any check fails, the recommendation is to **deepen the current wave** — not to skip ahead optimistically.

**Output:** A next-step directive with an explicit **confidence scorecard:**

```
RECOMMENDATION: DEEPEN WAVE 2 (do not proceed to Wave 3)

CONFIDENCE SCORECARD:
  ✓ Positive Evidence:     YES — cursor pagination returns valid data
  ✓ Reproducibility:       YES — consistent across 5 runs
  ✗ Boundary Testing:      NO  — no edge cases tested
  ✗ Risk Acceptance:       NO  — cursor stability under mutation is
                                  a HIGH betrayal probability with
                                  VERY HARD detection
  ~ Confidence Trajectory: MIXED — Wave 1 increased confidence,
                                    Wave 2 has stalled

RATIONALE: The happy path is validated, but the council cannot
recommend proceeding when a high-probability, hard-to-detect failure
mode remains untested. The Risk Agent's adversarial tests must be
executed before the gate can pass.

PRESCRIBED ACTIONS FOR WAVE 2 EXTENSION:
1. Execute cursor mutation test (insert record during pagination)
2. Execute cursor expiration test (wait 30 min, resume)
3. Execute boundary test (last page, page_size extremes)
4. Reconvene council with extended results

ESTIMATED TIME: 3-4 hours of spike work + 1 hour council review

IF ADVERSARIAL TESTS PASS: Proceed to Wave 3 with confidence
IF ADVERSARIAL TESTS FAIL: Trigger Strategy Agent Option B or D
```

---

### How the Council Operates

#### The Deliberation Sequence

The council doesn't operate in parallel. It operates in a **deliberation sequence** — each agent builds on the previous one's output, ensuring that later assessments are grounded in earlier ones.

```
SPIKE COMPLETES
      │
      ▼
┌─────────────────┐
│ RESULTS AGENT   │  ← Forensic analysis. What was proven?
│                 │    What WASN'T proven? Evidence gap analysis.
│                 │    Ends with a Distrust Challenge.
└────────┬────────┘
         │ Findings Report + Evidence Gaps + Distrust Challenge
         ▼
┌─────────────────┐
│ RISK AGENT      │  ← Maps evidence gaps to failure scenarios.
│                 │    Assigns betrayal probabilities.
│                 │    Designs adversarial counter-tests.
│                 │    May escalate distrust level.
└────────┬────────┘
         │ Risk Assessment + Adversarial Test Recommendations
         ▼
┌─────────────────┐
│ STRATEGY AGENT  │  ← Generates options assuming evidence may
│                 │    not hold. Every option includes distrust.
│                 │    No option is "proceed with full confidence."
└────────┬────────┘
         │ Strategic Options with Confidence Prerequisites
         ▼
┌─────────────────┐
│ NEXT-STEP AGENT │  ← Runs 5-point confidence scorecard.
│                 │    Recommends proceed, deepen, or pivot.
│                 │    Must justify against distrust criteria.
└────────┬────────┘
         │ Recommendation + Confidence Scorecard
         ▼
┌─────────────────┐
│ HUMAN REVIEW    │  ← Approve, override, or discuss.
│                 │    The council informs. Humans decide.
└─────────────────┘
```

This sequence matters. If the Strategy Agent reasons before the Results Agent has established facts, strategy drifts into speculation. If the Risk Agent assesses before results are in, risk becomes anxiety rather than analysis. The sequence enforces **evidence-first reasoning, distrust-second, options-third, action-last.**

#### The Council Record

Every council deliberation produces a **Council Record** — a structured document that captures each agent's output and the final decision. This record serves multiple purposes:

- **Institutional memory.** Future waves can reference why past decisions were made.
- **Audit trail.** If the project fails later, the council records show exactly what was known, what was *distrusted*, and why the team chose the path it chose despite that distrust.
- **Pattern recognition.** Over multiple implementation phases, the council records reveal systemic patterns — recurring evidence gaps, common betrayal scenarios, distrust levels that were miscalibrated.
- **Distrust calibration.** Were we distrustful enough? Records from failed projects can be compared against their council records to identify where distrust was too low.

```
┌────────────────────────────────────────────────────────────┐
│           COUNCIL RECORD — WAVE 1 GATE                     │
│                                                            │
│ Date: 2026-02-20                                           │
│ Assumption: API supports WebSocket for real-time data      │
│ Distrust Level: HOSTILE (Risk Score: 25)                   │
│ Spike Duration: 4 hours                                    │
│                                                            │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ RESULTS AGENT FINDINGS                                 │ │
│ │ WebSocket: REJECTED (HTTP 426)                         │ │
│ │ Alternative found: Long-polling at /v2/poll            │ │
│ │ Polling latency: 2.1s avg (n=50)                       │ │
│ │ Evidence Quality: MODERATE                             │ │
│ │                                                        │ │
│ │ EVIDENCE GAPS:                                         │ │
│ │  ✗ Polling under concurrent load untested              │ │
│ │  ✗ Rate limiting behavior unknown                      │ │
│ │  ✗ Polling response consistency unverified             │ │
│ │                                                        │ │
│ │ DISTRUST CHALLENGE: "We know polling exists. We don't  │ │
│ │  know if polling is viable at production scale."       │ │
│ └────────────────────────────────────────────────────────┘ │
│                                                            │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ RISK AGENT ASSESSMENT                                  │ │
│ │ Primary assumption: INVALIDATED                        │ │
│ │ Alternative (polling): UNPROVEN                        │ │
│ │ Betrayal probability (scalability): HIGH               │ │
│ │ Betrayal probability (rate limits): MEDIUM             │ │
│ │ Distrust level recommendation: REMAIN HOSTILE          │ │
│ │                                                        │ │
│ │ ADVERSARIAL TESTS PRESCRIBED:                          │ │
│ │  → 100 concurrent polling connections                  │ │
│ │  → Sustained polling for 1 hour (rate limit surface)   │ │
│ │  → Polling with degraded network conditions            │ │
│ └────────────────────────────────────────────────────────┘ │
│                                                            │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ STRATEGY AGENT OPTIONS                                 │ │
│ │ A: Conditional proceed — build with polling, but       │ │
│ │    architect for swap-out if it fails at scale         │ │
│ │ B: Deepen — run adversarial tests before proceeding    │ │
│ │ C: Escalate to vendor for streaming API ETA            │ │
│ │ D: Redesign around eventual consistency                │ │
│ │                                                        │ │
│ │ NOTE: No option grants full confidence in polling.     │ │
│ └────────────────────────────────────────────────────────┘ │
│                                                            │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ NEXT-STEP AGENT RECOMMENDATION                         │ │
│ │                                                        │ │
│ │ CONFIDENCE SCORECARD:                                  │ │
│ │  ✓ Positive Evidence (WebSocket absent — clear)        │ │
│ │  ✓ Reproducibility (50 polling requests consistent)    │ │
│ │  ✗ Boundary Testing (no load/concurrency testing)      │ │
│ │  ✗ Risk Acceptance (HIGH betrayal probability open)    │ │
│ │  ~ Confidence Trajectory (learned a lot, but new       │ │
│ │    unknowns introduced)                                │ │
│ │                                                        │ │
│ │ VERDICT: DEEPEN. Burden of proof NOT met.              │ │
│ │ Run adversarial tests. Then reconvene.                 │ │
│ └────────────────────────────────────────────────────────┘ │
│                                                            │
│ HUMAN DECISION: Approved. Run adversarial tests.           │
│ Also pursue vendor outreach in parallel (non-blocking).    │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

### Why a Council, Not a Single Agent

A single programming agent can write code, run tests, and report results. But a single agent has a fatal flaw in a distrust-based system: **it will trust itself.**

An agent that writes a spike and then evaluates that spike is both the prosecution and the jury. It has an inherent bias toward concluding that its own work succeeded. It tested what it thought was important. It interpreted the results through the lens of what it expected. It didn't test what it didn't think to test — and it can't see that gap.

The council structure introduces **adversarial tension** — not among teammates, but among perspectives:

- The **Results Agent** distrusts interpretations. It demands raw evidence.
- The **Risk Agent** distrusts the evidence itself. It hunts for what the evidence doesn't cover.
- The **Strategy Agent** distrusts the forward path. It refuses to plan as if confidence is warranted.
- The **Next-Step Agent** distrusts premature action. It won't recommend proceeding without a passing scorecard.

No single agent holds the distrust alone. The distrust is **distributed across four lenses**, each distrustful of something different. This is what makes the system robust: the Risk Agent can't be talked out of its skepticism by the Strategy Agent's optimism, because they operate in sequence, not in debate.

The council also prevents the single most dangerous failure mode in AI-assisted development: **an agent that confidently proceeds on a flawed assumption because nothing in its single-perspective evaluation flagged it.** When four agents with four different forms of distrust examine the same evidence, the probability of a critical blind spot drops dramatically.

### Distrust Is Not Paralysis

A common objection: "If the gate is always distrustful, nothing will ever pass. You'll spike forever and never build."

This misunderstands the doctrine. Distrust doesn't mean "never proceed." It means "proceed only when the burden of proof is met." The burden is calibrated by risk score — a WATCHFUL gate passes quickly, a HOSTILE gate demands adversarial testing. But all gates pass when evidence is sufficient.

The framework is designed to spend more time distrusting *early* (when assumptions are unvalidated and the blast radius of being wrong is enormous) so that it can spend less time distrusting *late* (when the foundation is solid and the remaining work is lower-risk). Distrust front-loads the hard questions. The final waves — building the actual feature on validated ground — move fast *because* the early waves moved carefully.

---

## Step 4: The Full Flow

Putting it all together, an implementation phase looks like this:

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  STEP 1: PRE-MORTEM                                              │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Failure Stories → Assumption Extraction → Risk Ranking   │    │
│  └──────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  STEP 2: PLANNING                                                │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Ranked Assumptions → Wave Sequence → Spike Definitions   │    │
│  └──────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  STEP 3: WAVE EXECUTION + COUNCIL GATES                          │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                                                          │    │
│  │  WAVE 1 ──▶ SPIKE ──▶ ┌────────────────────┐            │    │
│  │                        │   COUNCIL GATE     │            │    │
│  │                        │                    │            │    │
│  │                        │ Results Agent ──┐  │            │    │
│  │                        │ Risk Agent ─────┤  │            │    │
│  │                        │ Strategy Agent ─┤  │            │    │
│  │                        │ Next-Step Agent ─┘ │            │    │
│  │                        │                    │            │    │
│  │                        │ → Human Review     │            │    │
│  │                        └──────┬─────────────┘            │    │
│  │                               │                          │    │
│  │              ┌────────────────┼────────────────┐         │    │
│  │              ▼                ▼                ▼         │    │
│  │          PROCEED          ADJUST           PIVOT         │    │
│  │              │                │                │         │    │
│  │              ▼                ▼                ▼         │    │
│  │          WAVE 2 ──▶     WAVE 2* ──▶     RE-PLAN         │    │
│  │          (as planned)   (modified)      (new waves)      │    │
│  │              │                │                │         │    │
│  │              └───────┬────────┘                │         │    │
│  │                      ▼                        │         │    │
│  │               COUNCIL GATE                    │         │    │
│  │                      │                        │         │    │
│  │                     ...                      ...        │    │
│  │                      │                        │         │    │
│  │                      ▼                        ▼         │    │
│  │              FINAL WAVE: BUILD WITH CONFIDENCE           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Practical Example (Revisited With the Council)

### The Scenario

The team is building a screen that displays a customer's transaction history from a third-party banking API. The screen includes filtering, pagination, and real-time balance updates. The team is working with programming agents.

### Step 1: Pre-Mortem

The team (human + agents) generates failure stories. The agents contribute by analyzing the API documentation and flagging inconsistencies, ambiguities, and undocumented behaviors they detect — things human developers might skim past.

### Step 2: Planning

Assumptions are ranked. The wave plan is established:

| Wave | Assumption | Risk Score |
|---|---|---|
| 1 | The API supports WebSocket or streaming for real-time data | 25 |
| 2 | Pagination works as documented (cursor-based) | 16 |
| 3 | Response payload includes all fields needed for filtering | 12 |
| 4 | API response times are under 300ms for typical queries | 9 |

### Step 3: Wave 1 Execution

A programming agent writes and executes the spike — attempts a WebSocket connection, logs the response, tests the polling alternative.

**Council Gate convenes (Distrust Level: HOSTILE):**

**Results Agent:** "WebSocket rejected. Polling endpoint found. Latency: 2.1s average over 50 requests. Here are the raw logs. **Evidence gaps:** we did not test polling under concurrent load, did not test rate limiting, did not verify response consistency across runs. **Distrust Challenge:** we know polling exists, but we have no evidence it's viable at the scale we need."

**Risk Agent:** "Primary assumption invalidated — that's clear. But the team is already gravitating toward the polling alternative, and I distrust that gravitational pull. The polling endpoint *appeared* to work 50 times in a low-load test environment. **Betrayal scenarios:** (1) vendor rate-limits polling at 60 req/min in production — our 50-request test wouldn't have triggered that; (2) polling responses are eventually consistent with a 5-second lag we didn't measure; (3) polling endpoint is undocumented and unsupported — vendor could deprecate it. **I recommend REMAINING at HOSTILE distrust level** and prescribing adversarial tests: 100 concurrent connections, sustained 1-hour polling, and an explicit vendor inquiry about the polling endpoint's support status."

**Strategy Agent:** "Given that the council distrusts the polling alternative, here are the options — and note that none of them assume polling is safe. **Option A:** Conditional proceed — architect for polling *but* behind an abstraction layer so we can swap to a different mechanism if polling fails under real conditions. Accept 3-4 hours of adversarial testing first. **Option B:** Deepen this wave entirely — run all adversarial tests and vendor inquiry before making any architectural decisions. **Option C:** Pivot now — redesign around periodic batch refresh (every 30s) instead of real-time, which eliminates the polling dependency entirely. **Option D:** Escalate — the product promise of 'real-time' may not be achievable with this vendor. Product needs to know before we invest further."

**Next-Step Agent:** "Running the confidence scorecard. Positive evidence: partial — we know WebSocket is out, polling exists. Reproducibility: yes for basic requests. Boundary testing: **not met** — zero adversarial conditions tested. Risk acceptance: **not met** — HIGH betrayal probability on scalability. Confidence trajectory: we learned a lot, but we've exchanged one unknown for several new ones. **Verdict: DEEPEN. Burden of proof is not met.** Prescribe the adversarial tests. Reconvene council in 4 hours."

**Human Review:** "Agreed — run the adversarial tests. Also, I know this vendor's sales engineer. I'll email them directly about the polling endpoint's SLA. That'll run in parallel."

### Step 3: Wave 1 Extended (Adversarial Tests)

The programming agent runs 100 concurrent polling connections, sustains polling for 1 hour, tests with degraded network conditions.

**Council reconvenes (Distrust Level: HOSTILE):**

**Results Agent:** "Adversarial results in. 100 concurrent connections: 94 succeeded, 6 returned 429 (rate limited). Rate limit header indicates 100 req/min per API key. Sustained 1-hour test: stable, no degradation, but rate limit confirmed. Response consistency: all responses matched — no eventual consistency issues detected in this window. Vendor sales engineer confirmed polling endpoint is supported but rate-limited at 100 req/min on the standard tier. **Evidence quality upgraded to HIGH.** **Remaining gap:** we haven't tested behavior when rate limit is hit *and* retried — does the 429 come with a Retry-After header?"

**Risk Agent:** "Significantly better. Betrayal probability on scalability: **reduced to MEDIUM** — the 100 req/min rate limit is a real constraint but a known one. We can design around it. Betrayal probability on support status: **reduced to LOW** — vendor confirmed it's supported. **New risk surfaced:** our architecture needs to handle 429 gracefully. If we have 50 users paginating simultaneously, we'll hit the rate limit. This is a design constraint, not a blocker, but it must be factored into Wave 2. **Distrust level recommendation: DOWNGRADE to SKEPTICAL.** The adversarial tests did their job."

**Strategy Agent:** "The picture has clarified. Option A (conditional proceed with abstraction layer) is now the strongest path. The rate limit is a constraint we can design for — request pooling, client-side caching, staggered refresh intervals. Confidence prerequisite for proceeding: the team must have a rate-limit mitigation strategy *before* Wave 2 begins."

**Next-Step Agent:** "Updated scorecard. Positive evidence: **yes.** Reproducibility: **yes** — consistent across 1 hour and 100 connections. Boundary testing: **yes** — adversarial conditions tested, rate limit discovered and quantified. Risk acceptance: **yes** — remaining risks are known and designable. Confidence trajectory: **strong upward.** **Verdict: PROCEED to Wave 2** with the constraint that rate-limit mitigation must be part of the Wave 2 spike design."

**Human Review:** "Approved. Good call on running the adversarial tests — we'd have hit that rate limit on day 2 of integration otherwise."

---

## The Shaich Parallel

Ron Shaich's personal pre-mortem — projecting to his deathbed and working backward — maps elegantly onto this framework:

| Shaich's Method | Software Pre-Mortem |
|---|---|
| Imagine the end (deathbed) | Imagine the failure (post-launch disaster) |
| Identify what you'd regret | Identify the assumptions that would cause regret |
| Categorize (body, relationships, work, spirit) | Categorize (integration, domain, capability, environment, scope) |
| Work backward to present-day initiatives | Work backward to wave-ordered spikes |
| Quarterly reviews | Council Gate decisions at each wave |
| "Future histories" (success stories) | The validated assumption chain *is* the success story |
| "Bankruptcy stories" (failure narratives) | The pre-mortem failure stories |

And now, with the Distrustful Agent Council, there's a deeper parallel: Shaich doesn't trust his own comfort. He doesn't trust the feeling that "things are going fine." He assumes that without deliberate intervention, he will drift toward a deathbed full of regrets. That is distrust — distrust of complacency, distrust of the default path. The council operates the same way. It doesn't trust that a spike "worked." It assumes that without deliberate adversarial scrutiny, the team will drift toward a production failure built on untested confidence.

The philosophical core is identical: **confront the worst outcome while you still have time to change it.**

---

## Anti-Patterns to Avoid

**"We already know this API"** — Familiarity breeds assumption blindness. If you used it six months ago, its behavior may have changed. Test anyway.

**Skipping the failure stories and going straight to risk lists** — Lists are sanitized. Stories reveal the *cascading* nature of failure that lists flatten away.

**Treating waves as mini-sprints** — A wave is not about delivering shippable increments. It's about validating truths. The spike for Wave 1 might be 30 lines of throwaway code. That's fine. That's the point.

**Anchoring on the plan after Wave 1** — If Wave 1 invalidates your riskiest assumption, the entire wave plan may need to be rewritten. That's not a planning failure. That's the framework saving you from a much larger failure downstream.

**Doing all waves in parallel** — The whole point is sequential dependency. Wave 2 should only proceed on the foundation of Wave 1's validated assumption. Parallelizing reintroduces the exact risk the framework is designed to eliminate.

**Letting one agent dominate the council** — If the Next-Step Agent always overrides the Risk Agent in the name of velocity, you've recreated the very problem the council was designed to solve. The tension between agents is a feature, not a bug.

**Skipping the human review** — The council recommends. Humans decide. Agents lack the organizational context, political awareness, and strategic judgment that certain gate decisions require. The council surfaces information and options; it doesn't replace accountability.

**Treating "no errors" as validation** — This is the single most dangerous anti-pattern in spike evaluation. The absence of failure is not the presence of success. The distrust doctrine exists specifically to combat this. Demand positive evidence.

**Reducing distrust level too quickly** — It's tempting to downgrade from HOSTILE to WATCHFUL after one good result. The Risk Agent should control distrust calibration, and it should require adversarial evidence — not just happy-path evidence — before downgrading.

**Letting the spike designer evaluate the spike** — If the same agent that wrote the spike also serves as the Results Agent, it will unconsciously evaluate its own work generously. The Results Agent should be a *different* agent (or at minimum, a different prompt/persona) than the one that authored the spike.

**Confusing distrust with dysfunction** — Distrust in this framework is epistemic, not interpersonal. The council doesn't distrust the *team* — it distrusts *unverified claims about external reality*. The API doesn't care about your feelings. The gate shouldn't either.

---

## Summary

1. **Step 1 — Pre-Mortem**: Assume failure. Write the story of how it happened. Extract assumptions. Rank by risk. The risk score determines the distrust level.
2. **Step 2 — Planning**: Map ranked assumptions to waves. Define spikes for each wave. Sequence by risk, not by feature.
3. **Step 3 — Wave Execution + Distrustful Council Gates**: Execute spikes. At each gate, the Agent Council deliberates in sequence — Results (with evidence gaps and a Distrust Challenge), Risk (with betrayal probabilities and adversarial test prescriptions), Strategy (with no option assuming full confidence), Next Step (with a 5-point confidence scorecard). The default is "this did not work." The burden of proof is on the evidence. Humans review and decide.
4. **Build**: Once critical assumptions survive the council's distrust — with positive evidence, reproducibility, and boundary testing — build the feature on ground that has been tested not just for success, but for resistance to failure.

The goal is not to eliminate uncertainty — that's impossible. The goal is to **refuse to believe uncertainty has been eliminated until the evidence forces you to believe it.** Distrust is not the enemy of progress. Misplaced confidence is.
