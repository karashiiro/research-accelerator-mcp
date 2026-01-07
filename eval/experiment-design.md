# Research Accelerator Evaluation Design

## Core Hypothesis

The Research Accelerator MCP server improves research efficiency across independent conversations by allowing early research efforts to "warm up" a search index that accelerates future research tasks.

### H1: Same-Task Acceleration
When a research task is performed multiple times across separate conversations, subsequent attempts benefit from indexed resources from prior attempts.

### H2: Transfer Acceleration
Research on topic A partially accelerates research on related topic B, even when the topics are not identical.

---

## Experimental Design

### Conditions

```
┌─────────────────────────────────────────────────────────────────┐
│  CONTROL                                                        │
│  • Base research agent prompt (no accelerator)                  │
│  • No MCP server connected                                      │
│  • Agent uses web search / native capabilities only             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ compare to
                              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  EXPERIMENTAL CONDITIONS (all use accelerator prompt)                           │
├─────────────┬─────────────┬─────────────┬─────────────┬─────────────┬───────────┤
│  COLD       │ IDEAL-WARM  │REALISTIC-   │RELATED-WARM │RELATED-WARM │ UNRELATED │
│             │             │WARM         │(ideal)      │(realistic)  │           │
├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┼───────────┤
│  Empty      │ Hand-       │ Agent-      │ Hand-       │ Agent-      │ Agent-    │
│  index      │ crafted     │ generated   │ crafted     │ generated   │ generated │
│             │ descriptions│ from cold   │ descriptions│ from cold   │ from cold │
│  Same task  │ Same task   │ Same task   │ Related task│ Related task│ Octopus!  │
└─────────────┴─────────────┴─────────────┴─────────────┴─────────────┴───────────┘
```

### Prompt Design: Minimal Diff Principle

To isolate the effect of the accelerator, the control and treatment prompts are **structurally identical** with minimal additions for the accelerator condition.

**Control prompt structure:**
1. Understand the request
2. Search systematically
3. Evaluate sources
4. Synthesize findings
5. Acknowledge limitations

**Accelerator prompt structure:**
1. Understand the request
2. **Check the index** ← added
3. Search systematically
4. Evaluate sources
5. **Index new discoveries** ← added (says "skip if already in index")
6. Synthesize findings
7. Acknowledge limitations

**Total additions to accelerator prompt:**
- 1 introductory sentence (~15 words) explaining the index exists
- 2 new steps (~25 words each) for checking and updating the index

This minimal diff ensures that any performance differences are attributable to the index itself, not to prompt length, different instructions, or teaching different research strategies.

**Deliberately excluded from accelerator prompt:**
- Query syntax tutorials (agent can learn from tool descriptions)
- Indexing best practices or examples
- Any additional coaching not present in control

### What Each Comparison Tests

| Comparison | Research Question | Priority |
|------------|-------------------|----------|
| Control vs Ideal-Warm | Best-case benefit of the system (upper bound) | **PRIMARY** |
| Control vs Realistic-Warm | Real-world benefit of the system | **PRIMARY** |
| Cold vs Realistic-Warm | Does warming up help in practice? (H1) | Primary |
| Ideal-Warm vs Realistic-Warm | How much do we lose from agent-generated descriptions? | Primary |
| Cold vs Related-Warm (realistic) | Does transfer happen in practice? (H2) | Primary |
| Related-Warm vs Unrelated-Warm | Is acceleration due to relevance, or just "having stuff"? | Secondary |
| Control vs Cold | What's the adoption cost before warm-up? (expected to be negative!) | Secondary |

**Important framing notes:**

1. **Two types of warm conditions**: Ideal-Warm uses hand-crafted descriptions (ceiling performance). Realistic-Warm uses agent-generated descriptions from cold runs (real-world performance).

2. **Control vs Cold is NOT testing "tool overhead"** - it's testing the adoption cost. Cold will likely perform WORSE than control because the agent wastes tokens on `research_search` calls that return nothing. This is expected and acceptable IF Realistic-Warm beats Control.

3. **The Ideal vs Realistic gap** tells us how good the agent is at writing searchable descriptions. If Realistic-Warm ≈ Ideal-Warm, agent descriptions are good. If Realistic-Warm << Ideal-Warm, we may need to improve the prompt or add description quality guidance.

4. **Unrelated-Warm uses realistic descriptions** - if ML/CS descriptions somehow help octopus research, something is very wrong.

---

## Experimental Parameters

### Model Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Model | `claude-sonnet-4-20250514` | Balance of capability and cost; specify exact version for reproducibility |
| Temperature | `0` | Deterministic outputs for reproducibility |
| Max tokens | `4096` | Sufficient for research synthesis tasks |

**Note**: If comparing across models, run the full matrix for each model separately.

### Database Management

**Critical**: Warm runs must not pollute each other's data. Follow this procedure:

```
COLD RUN PROCEDURE:
1. Clear database completely (fresh start)
2. Run cold task
3. SNAPSHOT the database → save as "cold_snapshot_{task}_{run_id}.db"
4. Record what entries the agent created (for analysis)

REALISTIC-WARM RUN PROCEDURE:
1. COPY the cold snapshot to a fresh database file
2. Run warm task against the COPY
3. Discard the copy after recording metrics
4. Each warm run starts from the SAME cold snapshot

IDEAL-WARM RUN PROCEDURE:
1. Clear database completely
2. Load hand-crafted entries from tasks.md
3. Run warm task
4. Discard after recording metrics
```

**Why this matters**:
- Without snapshots, Warm Run 2 would see entries created by Warm Run 1
- Each warm run must see the EXACT same starting state
- For realistic conditions, that state comes from ONE cold run's output
- For ideal conditions, that state comes from our hand-crafted JSON

**Database file naming convention**:
```
research_cold_{task}_{run}.db      → disposable, but snapshot before discarding
research_warm_{task}_{run}.db      → copy of snapshot, discard after run
snapshots/
  cold_{task}_{run}.db             → preserved for realistic-warm runs
```

### Sample Size

| Runs per condition | Minimum | Recommended |
|--------------------|---------|-------------|
| Per task × condition | 3 | 5-10 |

**Rationale**: Even with temperature=0, there can be variance from:
- Web search result variability
- Tool call timing/ordering
- Index search result ordering

With 5 runs per condition and 5 conditions, that's 25 runs per task. With 7 tasks, that's 175 total runs for a full experiment.

**Power analysis note**: We don't have prior effect size estimates, so we're using a practical minimum. If initial results show high variance, increase N.

### Cost Estimation

Rough per-run estimates (will vary by task complexity):
- Control: ~2K-5K tokens
- Cold: ~3K-7K tokens (tool call overhead)
- Warm: ~2K-5K tokens (ideally less than cold)

At $3/M input, $15/M output (Sonnet pricing), expect ~$0.05-0.15 per run, or ~$10-25 for a full experiment.

---

## Metrics

### Primary Metrics
| Metric | Description | Why It Matters |
|--------|-------------|----------------|
| Total tokens | Input + output tokens for full task | Cost proxy |
| Task success | Did agent find/use correct resources? | Quality gate |

**Token accounting details**:
- Count ALL tokens: system prompt, user message, assistant response, tool calls, tool results
- Report input and output separately (different costs) but use total for primary comparison
- Tool calls to MCP server count as output tokens; tool results count as input tokens

**Dropped metric: Wall-clock time**
Originally planned but removed because:
- API latency varies (network, rate limits, server load)
- Not reproducible across different times/locations
- Token count is a better proxy for "work done"
- If needed, can estimate time from tokens × typical latency

### Secondary Metrics
| Metric | Description | Why It Matters |
|--------|-------------|----------------|
| `research_search` calls | Number of index queries | Index utilization |
| `research_create` calls | New resources indexed | Cache population |
| Web search calls | External searches performed | Expensive operation avoidance |
| Search hit rate | Searches returning useful results | Index quality signal |
| Description quality score | Quality of agent-generated descriptions (cold runs only) | Predicts realistic-warm performance |

### Description Quality Scoring (for cold runs)

Evaluate each `research_create` call's description on:

| Criterion | Points | Example |
|-----------|--------|---------|
| Contains author name(s) | +1 | "Vaswani et al." |
| Contains year | +1 | "2017" |
| Contains paper title or fragment | +1 | "Attention Is All You Need" |
| Contains key technical terms | +1 | "transformer", "self-attention", "positional encoding" |
| Length ≥ 50 characters | +1 | (not just "attention paper") |

**Score range**: 0-5 per entry. Average across all entries created in a cold run.

**Why this matters**: If cold runs produce low-quality descriptions (avg < 3), Realistic-Warm will underperform Ideal-Warm. This metric helps diagnose whether the system fails due to poor descriptions vs other factors.

### Quality Control
To ensure we're comparing efficiency at **equivalent quality levels**:

1. **Task success is binary**: Either the agent found the expected resources or it didn't
2. **Only compare successful runs**: If a condition fails to complete the task, that's a separate finding
3. **Ground truth tasks**: Use tasks where we KNOW what resources should be found

### Task Success Criteria (Precise Definition)

A ground truth resource is considered **"found"** if the agent's output contains ANY of:

| Match Type | Example | Counts as Found? |
|------------|---------|------------------|
| Exact URL | `https://arxiv.org/abs/1706.03762` | ✅ Yes |
| Arxiv ID | `arxiv:1706.03762` or `1706.03762` | ✅ Yes |
| DOI | `10.48550/arXiv.1706.03762` | ✅ Yes |
| Title (exact) | "Attention Is All You Need" | ✅ Yes |
| Title (fuzzy) | "Attention is All You Need paper" | ✅ Yes |
| Author + Year | "Vaswani et al. 2017" or "Vaswani 2017" | ✅ Yes |
| Author + Title fragment | "Vaswani's attention paper" | ✅ Yes |
| Generic reference | "the transformer paper" | ❌ No (too ambiguous) |
| Wrong paper | Different paper, even if relevant | ❌ No |

**Automated matching**: Use regex/string matching for URLs, arxiv IDs, DOIs. Use fuzzy string matching for titles (threshold: 80% similarity). Author+year requires both components.

**Edge cases**:
- If agent finds a DIFFERENT valid paper not in ground truth → doesn't count for success metric, but note it in qualitative analysis
- If agent mentions paper but gets details wrong (e.g., wrong year) → still counts if identifiable
- If agent uses paper from index vs finds via web search → both count, but record the source

**Success threshold**: Task is "successful" if agent finds ≥2 of 3 ground truth resources (as defined above).

---

## Task Design Principles

Tasks should:
1. Have **objectively correct answers** (specific papers, tools, or resources to find)
2. Be **repeatable** across conditions
3. Have **natural related-task pairs** for testing transfer (H2)
4. Be **representative** of real research workflows

### Training Data Contamination

**Acknowledged limitation**: Many ground truth papers (e.g., Vaswani et al. 2017) are famous and likely in the model's training data. The model may "know" these papers without searching.

**Why this is okay for our purposes**:
1. **Affects all conditions equally** - both Control and Treatment have the same training data, so this doesn't confound our comparisons
2. **Makes our test harder** - if the model already knows these papers, the index has LESS opportunity to add value. If we still see acceleration, that's a strong signal.
3. **Realistic scenario** - in real usage, users often research well-known topics where the model has prior knowledge

**What we're actually measuring**: Not "can the model name this paper?" but "does the index help the model surface relevant resources faster, with fewer tokens, and with higher reliability?"

**Optional enhancement**: Add a task family with more obscure/recent papers to test scenarios where model knowledge is weaker. This would strengthen claims if we see similar acceleration patterns.

### Example Task Structure

```
Task Family: "Transformer Architecture Research"

T1.1 (Primary): "Find seminal papers on attention mechanisms in deep learning"
   Expected: Vaswani et al. 2017, Bahdanau et al. 2014, etc.

T1.2 (Related): "Find papers on positional encoding approaches"
   Expected: May benefit from T1.1's indexed transformer papers

T0 (Unrelated): "Find papers on cephalopod cognition and problem-solving"
   Expected: Should NOT benefit from T1.1's index (completely different domain)
```

**Note:** T0 (cephalopod cognition) is the single unrelated control task used across ALL task families. See `tasks.md` for full task suite.

---

## Procedure

### Phase 1: Baseline Collection
1. Run each task with CONTROL prompt (no accelerator)
2. Record: tokens, time, success, resources found
3. Repeat N times for statistical power

### Phase 2: Cold Start Collection
1. Clear index completely
2. Run each task with ACCELERATOR prompt + empty index
3. Record: all metrics + index state after completion
4. Repeat N times with fresh index each time

### Phase 3: Warm Start Collection
1. Pre-populate index with resources from Phase 2
2. Run same task with ACCELERATOR prompt + warm index
3. Record: all metrics
4. Repeat N times with same warm index

### Phase 4: Transfer Collection
1. Keep index warm from primary task
2. Run RELATED task with accelerator prompt
3. Record: all metrics + which indexed resources were used
4. Repeat for UNRELATED task as control

---

## Analysis Plan

### Primary Analysis
- Compare mean tokens/time across conditions (after filtering for successful runs)
- Use appropriate statistical tests (t-test, ANOVA) depending on distribution
- Report effect sizes, not just p-values

### Secondary Analysis
- Examine WHICH resources were retrieved in warm conditions
- Analyze search query patterns across conditions
- Look for "negative transfer" (unrelated index hurting performance)

### Expected Outcomes

**Optimistic scenario (what we hope to see):**
```
Control:                    ████████████ (baseline - 100%)
Cold:                       ██████████████ (WORSE ~115% - adoption cost, expected!)
Ideal-Warm:                 █████ (BETTER ~50% - ceiling performance!)
Realistic-Warm:             ██████ (BETTER ~60% - H1 confirmed!)
Related-Warm (realistic):   ████████ (BETTER ~80% - H2 confirmed!)
Unrelated-Warm:             ██████████████ (no benefit ~115% - confirms relevance matters)
```

This tells us:
- System is worth adopting (Realistic-Warm beats Control)
- Agent-generated descriptions are pretty good (Realistic ≈ Ideal)
- Transfer works (Related-Warm beats Cold)

**Null result scenario:**
```
Control ≈ Realistic-Warm → accelerator provides no real-world benefit
(even after warming up, no speedup detected)
```

**Description quality problem:**
```
Ideal-Warm beats Control, but Realistic-Warm ≈ Cold
→ System COULD work, but agent writes bad descriptions
→ Need to improve indexing prompt/guidance
```

**Partial success scenario:**
```
Realistic-Warm beats Control, but Related-Warm ≈ Cold → H1 confirmed, H2 rejected
(same-task acceleration works, but no transfer to related tasks)
```

**Concerning scenario:**
```
Unrelated-Warm ≈ Related-Warm → "transfer" isn't real relevance-based speedup,
just having ANY data in the index changes agent behavior somehow
```

**Very concerning scenario:**
```
Cold ≈ Control (no adoption cost) → agent ignores the tool entirely
(prompt isn't effective at getting agent to use the index)
```

---

## Open Questions

Resolved:
- [x] ~~How many repetitions (N) do we need?~~ → 5-10 per condition (see Experimental Parameters)
- [x] ~~How do we handle variance in LLM outputs?~~ → temperature=0, multiple runs, report variance
- [x] ~~Should we use temperature=0?~~ → Yes
- [x] ~~How do we define "task success" precisely?~~ → See Task Success Criteria section

Remaining:
- [ ] What's the minimum index size for meaningful warm-start benefit? (empirical question)
- [ ] Should we test with different models to see if effects generalize?
- [ ] How do we handle web search failures / rate limits during runs?
- [ ] Should we add a "tool exists but agent doesn't use it" diagnostic condition?

---

## Files in this Directory

- `experiment-design.md` - This document
- `prompt-control.md` - Base research agent prompt (no accelerator)
- `prompt-accelerator.md` - Accelerator-enabled agent prompt
- `tasks.md` - Task suite with ground truth answers
