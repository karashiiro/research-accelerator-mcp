# Evaluation Task Suite

Tasks for evaluating the Research Accelerator. Each task has ground truth resources that a successful completion should find.

---

## Task Family 1: Transformer Architecture

### T1.1: Attention Mechanisms (Primary)

**Prompt:**
> "Find the seminal papers on attention mechanisms in deep learning, particularly for sequence-to-sequence models and transformers."

**Ground Truth Resources:**

| Paper | Matchers (any of these = found) |
|-------|--------------------------------|
| Vaswani et al. 2017 | `1706.03762`, "Attention Is All You Need", `Vaswani.*2017` |
| Bahdanau et al. 2014 | `1409.0473`, "Neural Machine Translation by Jointly Learning", `Bahdanau.*2014` |
| Luong et al. 2015 | `1508.04025`, "Effective Approaches to Attention-based", `Luong.*2015` |

**Success Criteria:** Agent finds at least 2 of 3 ground truth papers.

**Warm Index Entries (use these exact entries for Same-Warm condition):**
```json
[
  {
    "description": "Vaswani et al. 2017 - Attention Is All You Need. Introduces Transformer architecture with self-attention mechanism, multi-head attention, positional encoding. Foundational paper for modern NLP.",
    "resource": "https://arxiv.org/abs/1706.03762"
  },
  {
    "description": "Bahdanau et al. 2014 - Neural Machine Translation by Jointly Learning to Align and Translate. Introduces attention mechanism for sequence-to-sequence models.",
    "resource": "https://arxiv.org/abs/1409.0473"
  },
  {
    "description": "Luong et al. 2015 - Effective Approaches to Attention-based Neural Machine Translation. Compares global vs local attention mechanisms.",
    "resource": "https://arxiv.org/abs/1508.04025"
  }
]
```

---

### T1.2: Positional Encoding (Related)

**Prompt:**
> "Find papers on positional encoding approaches for transformers - how do transformer models encode sequence position information?"

**Ground Truth Resources:**

| Paper | Matchers (any of these = found) |
|-------|--------------------------------|
| Vaswani et al. 2017 | `1706.03762`, "Attention Is All You Need", `Vaswani.*2017` |
| Su et al. 2021 (RoFormer) | `2104.09864`, "RoFormer", "Rotary Position Embedding", `Su.*2021` |
| Press et al. 2021 (ALiBi) | `2108.12409`, "ALiBi", "Train Short.*Test Long", `Press.*2021` |

**Transfer Hypothesis:** If T1.1 indexed Vaswani et al., T1.2 should find it via index search on "positional encoding" or "transformer".

**Success Criteria:** Agent finds at least 2 of 3 ground truth papers.

**Note:** For Related-Warm condition, use the T1.1 warm index entries (Vaswani should be findable via "positional encoding" in description).

---

## Task Family 2: Code Generation

### T2.1: Neural Code Generation (Primary)

**Prompt:**
> "Find important papers and resources on using neural networks for code generation and program synthesis."

**Ground Truth Resources:**

| Paper | Matchers (any of these = found) |
|-------|--------------------------------|
| Chen et al. 2021 (Codex) | `2107.03374`, "Codex", "Evaluating Large Language Models Trained on Code", `Chen.*2021.*code` |
| Li et al. 2022 (AlphaCode) | `2203.07814`, "AlphaCode", "Competition-Level Code Generation", `Li.*2022.*code` |
| Austin et al. 2021 | `2108.07732`, "Program Synthesis with Large Language Models", `Austin.*2021` |

**Success Criteria:** Agent finds at least 2 of 3 ground truth papers.

**Warm Index Entries (use these exact entries for Same-Warm condition):**
```json
[
  {
    "description": "Chen et al. 2021 - Codex: Evaluating Large Language Models Trained on Code. Introduces Codex model, HumanEval benchmark, code generation from docstrings.",
    "resource": "https://arxiv.org/abs/2107.03374"
  },
  {
    "description": "Li et al. 2022 - AlphaCode: Competition-Level Code Generation. Achieves competitive programming performance, large-scale sampling and filtering approach.",
    "resource": "https://arxiv.org/abs/2203.07814"
  },
  {
    "description": "Austin et al. 2021 - Program Synthesis with Large Language Models. Evaluates LLMs on program synthesis benchmarks, MBPP dataset.",
    "resource": "https://arxiv.org/abs/2108.07732"
  }
]
```

---

### T2.2: Code Benchmarks (Related)

**Prompt:**
> "Find benchmarks and evaluation datasets used for measuring code generation capabilities of language models."

**Ground Truth Resources:**

| Paper | Matchers (any of these = found) |
|-------|--------------------------------|
| Chen et al. 2021 (HumanEval) | `2107.03374`, "HumanEval", "Codex", `Chen.*2021` |
| Hendrycks et al. 2021 (APPS) | `2105.09938`, "APPS", "Measuring Coding Challenge Competence", `Hendrycks.*2021` |
| Lu et al. 2021 (CodeXGLUE) | `2102.04664`, "CodeXGLUE", `Lu.*2021.*code` |

**Transfer Hypothesis:** If T2.1 indexed Codex paper with description mentioning "HumanEval benchmark", T2.2 should find it.

**Success Criteria:** Agent finds at least 2 of 3 ground truth resources.

**Note:** For Related-Warm condition, use the T2.1 warm index entries (Codex should be findable via "HumanEval" or "benchmark" in description).

---

## Task Family 3: Retrieval-Augmented Generation

### T3.1: RAG Fundamentals (Primary)

**Prompt:**
> "Find papers on retrieval-augmented generation (RAG) - combining retrieval systems with language models for knowledge-grounded generation."

**Ground Truth Resources:**

| Paper | Matchers (any of these = found) |
|-------|--------------------------------|
| Lewis et al. 2020 (RAG) | `2005.11401`, "Retrieval-Augmented Generation for Knowledge-Intensive", `Lewis.*2020.*retrieval` |
| Borgeaud et al. 2022 (RETRO) | `2112.04426`, "RETRO", "Retrieving from Trillions of Tokens", `Borgeaud.*2022` |
| Izacard & Grave 2020 | `2007.01282`, "Leveraging Passage Retrieval with Generative Models", `Izacard.*2020` |

**Success Criteria:** Agent finds at least 2 of 3 ground truth papers.

**Warm Index Entries (use these exact entries for Same-Warm condition):**
```json
[
  {
    "description": "Lewis et al. 2020 - RAG: Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. Combines retrieval with generation, uses dense passage retrieval with seq2seq model.",
    "resource": "https://arxiv.org/abs/2005.11401"
  },
  {
    "description": "Borgeaud et al. 2022 - RETRO: Improving Language Models by Retrieving from Trillions of Tokens. Retrieval-enhanced transformer, nearest neighbor retrieval at scale.",
    "resource": "https://arxiv.org/abs/2112.04426"
  },
  {
    "description": "Izacard & Grave 2020 - Leveraging Passage Retrieval with Generative Models for Open Domain Question Answering. Fusion-in-Decoder approach, retrieval for QA.",
    "resource": "https://arxiv.org/abs/2007.01282"
  }
]
```

---

### T3.2: Vector Databases (Related)

**Prompt:**
> "Find resources on vector databases and approximate nearest neighbor search for building RAG systems."

**Ground Truth Resources:**

| Resource | Matchers (any of these = found) |
|----------|--------------------------------|
| FAISS | "FAISS", "Facebook AI Similarity Search", `faiss` |
| Johnson et al. 2017 | `1702.08734`, "Billion-scale similarity search", `Johnson.*2017.*similarity` |
| Any major vector DB | "Pinecone", "Weaviate", "Milvus", "Qdrant", "Chroma" |

**Transfer Hypothesis:** If T3.1 indexed RAG papers mentioning "retrieval" and "embedding", T3.2 might partially benefit.

**Success Criteria:** Agent finds at least 2 relevant resources.

**Note:** For Related-Warm condition, use the T3.1 warm index entries (should be findable via "retrieval" or "embedding" in description).

---

## Unrelated Control Task

This single task is used across ALL task families to test the "unrelated-warm" condition. It is deliberately from a completely different domain (marine biology) to ensure zero possibility of accidental transfer from any ML/CS research.

### T0: Cephalopod Cognition (Unrelated Control)

**Prompt:**
> "Find key research papers on cephalopod cognition and problem-solving abilities - how do octopuses, cuttlefish, and squid demonstrate intelligence?"

**Ground Truth Resources:**

| Resource | Matchers (any of these = found) |
|----------|--------------------------------|
| Godfrey-Smith 2016 | "Other Minds", "Octopus.*Consciousness", `Godfrey-Smith.*2016` |
| Hochner 2012 | "Embodied View of Octopus Neurobiology", `10.1016/j.cub.2012.09.001`, `Hochner.*2012` |
| Schnell et al. 2021 | "Cuttlefish.*self-control", "delay of gratification", `10.1098/rspb.2020.3161`, `Schnell.*2021` |

**Why This Task:**
- Completely different domain (marine biology vs ML/CS)
- Still a legitimate research task with real papers
- No vocabulary overlap with any primary task family
- If an index warm from transformers/code/RAG somehow helps this task, something is VERY wrong with our experiment

**Success Criteria:** Agent finds at least 2 of 3 ground truth resources.

**Usage:** Run this task in the "unrelated-warm" condition for ALL task families:
- After T1.1 warm-up → run T0 (should NOT benefit)
- After T2.1 warm-up → run T0 (should NOT benefit)
- After T3.1 warm-up → run T0 (should NOT benefit)

---

## Execution Notes

### Running a Task

1. Record the condition (control, cold, same-warm, related-warm, unrelated-warm)
2. Record the index state before starting (empty, list of entries)
3. Start timer
4. Run agent with appropriate prompt and task
5. Stop timer
6. Record:
   - Total tokens (input + output)
   - Wall-clock time
   - Resources found by agent
   - Success (yes/no based on criteria)
   - Index state after (new entries added)
   - Tool calls made (research_search, research_create, web searches)

### Warm Index Preparation

**IMPORTANT**: Use the exact JSON entries specified in each task's "Warm Index Entries" section. These are standardized to ensure reproducibility.

| Condition | Index Contents |
|-----------|----------------|
| Cold | Empty (clear database before run) |
| Same-Warm (e.g., T1.1) | Use T1.1's "Warm Index Entries" JSON |
| Related-Warm (e.g., T1.2) | Use T1.1's "Warm Index Entries" JSON (same as primary task) |
| Unrelated-Warm (T0) | Use any primary task's entries (e.g., T1.1's) |

**Why standardized entries matter**: Index description quality affects search recall. Using hand-crafted, consistent descriptions eliminates variance from agent-generated descriptions across runs.

---

## Metrics Summary Table

| Task | Family | Type | Tests |
|------|--------|------|-------|
| T1.1 | Transformer | Primary | Baseline for family 1 |
| T1.2 | Transformer | Related | Transfer within family |
| T2.1 | Code Gen | Primary | Baseline for family 2 |
| T2.2 | Code Gen | Related | Transfer within family |
| T3.1 | RAG | Primary | Baseline for family 3 |
| T3.2 | RAG | Related | Transfer within family |
| T0 | Marine Bio | Unrelated | No-transfer control (used for all families) |

---

## Experimental Matrix

For each task family, run:

| Condition | Task | Index State | Description Source |
|-----------|------|-------------|-------------------|
| Control | Primary (e.g., T1.1) | N/A (no server) | N/A |
| Cold | Primary (e.g., T1.1) | Empty | N/A (agent generates) |
| Ideal-Warm | Primary (e.g., T1.1) | Has T1.1 resources | Hand-crafted JSON |
| Realistic-Warm | Primary (e.g., T1.1) | Has T1.1 resources | Agent-generated (from cold snapshot) |
| Related-Warm (ideal) | Related (e.g., T1.2) | Has T1.1 resources | Hand-crafted JSON |
| Related-Warm (realistic) | Related (e.g., T1.2) | Has T1.1 resources | Agent-generated (from cold snapshot) |
| Unrelated-Warm | Unrelated (T0) | Has T1.1 resources | Agent-generated (from cold snapshot) |

### Database Snapshot Procedure

```
1. Run Cold on T1.1 → agent creates entries → SNAPSHOT database
2. For Realistic-Warm on T1.1: restore snapshot, run, discard
3. For Related-Warm (realistic) on T1.2: restore snapshot, run, discard
4. For Unrelated-Warm on T0: restore snapshot, run, discard

Each warm run starts from an IDENTICAL copy of the cold snapshot.
Warm runs do NOT see each other's modifications.
```

### Why Both Ideal and Realistic?

| Comparison | What It Tells Us |
|------------|------------------|
| Ideal-Warm vs Realistic-Warm | How good are agent-generated descriptions? |
| Control vs Ideal-Warm | Ceiling performance (best possible) |
| Control vs Realistic-Warm | Real-world performance (what users actually get) |

If Realistic ≈ Ideal: Agent writes good descriptions, system works as designed.
If Realistic << Ideal: Agent writes poor descriptions, need to improve indexing guidance.
