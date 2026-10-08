# Decision models for the AI's brain — research (2026-10-08)

Question: instead of a chat LLM (Qwen), could a smaller **decision model like Jev**, with open weights,
pick the AI's goals?

## Summary

- **Jev itself is closed.** TypeSafe AI serves it only through its API and OpenRouter. The weights and
  parameter count aren't published, so it breaks the "local, no cloud" rule.
- **Jev-style open models exist, and the Ollama already on this PC can serve them.** Ollama 0.35+ exposes
  the same `/v1/systemone` API as Jev. Verified locally: Ollama 0.40.1 answers on that endpoint. Nothing new
  needs installing; only a model download.
- **Best candidates for a 6 GB GPU shared with PZ:** `tev1:0.8b` (≈0.8 GB) and `tev1:4b-q4_K_M` (2.7 GB)
  from Together AI, both served by Ollama. Julia-1 (144M, Apache 2.0) and Laya (421M, Apache 2.0) are tiny
  CPU options but need their own Python packages.
- **Main trade-off for watchability:** decision models return probabilities, not sentences, so they can't
  write the speech bubble. The "why" has to come from templates or an occasional LLM call. A HUD bar like
  "flee 82% · fight 12%" may be just as watchable.
- **Closest precedent:** JEV-Star (StarCraft II) found Jev alone stalled even against an easy AI. Jev plus
  an LLM planner beat the strongest fair built-in AI. That supports a hybrid design over a single model.
- **Measured on this PC (see below):** zero-shot, `tev1:4b` is about as accurate as Qwen3.5-4B (68% vs 73%
  sensible) and ~1.5× faster, but picks something dangerous twice as often. `tev1:0.8b` is fast (175 ms,
  0.85 GB) but mostly answers "wait". Off the shelf they don't beat Qwen; fine-tuned on our own data is
  where they could.

## What a "Jev-class" decision model is

You send a **state** (text or JSON) plus named **questions**. Each question has one of three types:

| Type | Asks | Returns |
|---|---|---|
| `choice` | Which of these options? | Chosen option, probability per option, confidence |
| `noul` | Is this true? | Probability of yes |
| `score` | Where on this ordered scale? | Expected position, probability per level, confidence |

There's no prose, no reasoning text and no sampling. One forward pass scores the options, so a model can
never answer outside the list. That makes it a "System One" model (fast judgement) rather than a chat
model. Jev pricing on OpenRouter is $0.042 per million input tokens, with output free.

How this maps onto the AI's strategy layer: one call per tick could ask

```json
{
  "state": "<rendered percept, the same text bench/prompt.py builds today>",
  "questions": {
    "goal":          {"type": "choice", "instructions": "Pick the next goal",
                      "criteria": {"flee": "Run away from zombies...", "fight": "...", "...": "only the legal goals"}},
    "safe_to_sleep": {"type": "noul",   "instructions": "Is it safe to sleep here right now?"},
    "threat":        {"type": "score",  "instructions": "How dangerous is the situation?",
                      "criteria": ["calm", "watchful", "dangerous", "deadly"]}
  }
}
```

The probabilities support **confidence routing**: act on confident answers, and hand uncertain ones to the
rules or to Qwen. That's the REFLEX pattern from the paper on Jev. There, 95% of tasks succeeded with 72.7%
fewer calls to the expensive model, but it also found little gain when cheap routing is already accurate.

## Open-weights candidates

All accuracy figures come from their makers or third parties and are **not measured on this PC or on
Zomboid situations**. Benchmarks differ between sources, so compare within a row, not across rows.

| Model | Maker | Size | Licence | How to run here | Reported accuracy | Fits beside PZ on 6 GB? |
|---|---|---|---|---|---|---|
| **`tev1:0.8b`** | Together AI | 0.8B (Qwen3.5 fine-tune), ~0.8 GB | Weights licence **not stated** ("experimental") | **Ollama, `/v1/systemone`** | 63.5% (Ollama's 13-dataset mean) | **Yes, easily** |
| **`tev1:4b-q4_K_M`** | Together AI | 4B, 2.7 GB | Not stated | **Ollama** | 73.3% (same benchmark) | Borderline (same size class as `qwen3.5:4b`) |
| `nimble` | Bespoke Labs | 9B (Qwen3.5-9B fine-tune), 9.3 GB | Apache 2.0 | Ollama | 75.7% (same benchmark; Jev 76.0%) | **No**, CPU only (slow) |
| Julia-1 | Supersonic Labs | 144M (mmBERT-small encoder), 550 MB | Apache 2.0 | Own Python package; ONNX; GGUF via llama.cpp | 73.15% on typed-decisions (lab-reported; Jev 72.7–74.0%) | Yes, CPU |
| Laya | Convai Innovations | 421M (ModernBERT-large) | Apache 2.0 | `pip install laya` | **0.362 zero-shot** (below the majority-class baseline); 0.766 after fine-tuning | Yes; CPU 193–464 ms |
| Kev-4B | Jared Palmer | Qwen3.5-4B-Base + LoRA + head | Apache 2.0 (adapter) | llama.cpp GGUF (secondary source) | 79.7% vs Jev 81.1% (author's suite) | Probably |
| decider-4b v2 | Mapika | 4.2B | Apache 2.0 (third-party claim) | Unverified | 3rd on one JevBench board (v1.4.2.2, 64.13) | Probably |

Other notes:

- There are dozens more community "open Jev" models. One directory lists ~55, nearly all from the last
  three weeks, with self-reported scores on their own test sets. Two unrelated leaderboards both call
  themselves "JevBench". One of them (jevbench.dev) scores models on **winning full StarCraft II and
  Minecraft games**, and Jev 1.13 leads it with an 84% win rate.
- Julia-1 handles 2–20 options per question, and all these models get worse as option lists grow. The AI
  only ever offers 4–7 legal goals, which is comfortably inside that range.
- Laya's own server binds `0.0.0.0` with no authentication unless `LAYA_API_KEY` is set. If we use it, it
  must be bound to localhost. Same local-only rule as the IPC files.
- These projects are weeks old and unvetted. Models served through Ollama need no new code on this PC.
  Python packages (`laya`, Julia-1's runtime) would need the same "read before running" review as the
  Zomboid repos.

## Other kinds of "decision model" (checked, poor fit)

| Kind | Example | Why not for this project |
|---|---|---|
| Pixel → gamepad game agents | NVIDIA **NitroGen** (~493M; 40k hours across 1,000+ games; CVPR 2026) | Built for gamepad action games. PZ is mouse, keyboard and inventory. It would compete with PZ for the GPU every frame. NVIDIA non-commercial licence |
| World models / JEPA | Meta **V-JEPA 2-AC** (~300M action predictor on a ViT-g encoder; MIT code), **V-JEPA 2.1** (Mar 2026, encoders only) | Robot-arm planning at ~16 s per action. No game agents found. It would need hours of action-labelled PZ video |
| Small function-calling LMs | Google **FunctionGemma** 270M (CPU, ~550 MB; 58% → 85% after fine-tuning on Mobile Actions) | Still generative. Worth it only as a fine-tune target once we have logs |
| Tabular in-context learners | **TabPFN** v2 (commercial use OK with attribution); 2.5 and 3.5 (non-commercial weights) | Learns from a few hundred logged decisions without training, but needs logs first and numeric features, not text |
| Classical game AI | Utility scoring (our `bench/rules.py`), behaviour trees, GOAP; PZ's B42 *Bandits* NPC mod | Instant and free. Our rule baseline already matched every benchmark situation, with the caveats in BENCHMARK.md |

## What this suggests for the AI

The research points the same way as the benchmark: a layered brain where each part does what it's good at.

1. **Rules (Lua, every tick):** list legal goals, score them, and act alone when one goal clearly wins
   (bleeding → bandage, 5 chasing → flee).
2. **Decision model (Ollama `/v1/systemone`, ~every 1–2 s):** `choice` over the legal goals, plus
   `noul`/`score` questions, using the rules' facts as state. Candidates: `tev1:0.8b` first (fits beside
   PZ), then `tev1:4b`.
3. **LLM (Qwen3.5-4B, occasionally):** called when the decision model's confidence is low or disagrees with
   the rules, and to write the speech-bubble line. This is the JEV-Star split: fast selector plus slower
   planner.
4. **Later:** fine-tune Julia-1 or Laya (144–421M, trainable on this RTX 2060) on the AI's own logged
   decisions and your corrections.

## Measured on this PC (2026-10-08, PZ closed)

Same 31 situations, percept and game brief as the Qwen runs. Each decision model got one `choice` question
over the legal goals. Full tables are in [BENCHMARK.md](BENCHMARK.md).

| | Rules | `qwen3.5:4b` | `tev1:4b-q4_K_M` | `tev1:0.8b` |
|---|---|---|---|---|
| Sensible / bad | 100% / 0% (optimistic) | 73% / 5% | 68% / 10% | 39% / 19% |
| Latency, fresh situation | <1 ms | 815 ms | 551 ms | 175 ms |
| VRAM | 0 | 2,983 MiB | 2,761 MiB | 852 MiB |
| Speech-bubble text | template | yes | no | no |

- `tev1:4b` over-picks **looting**: it loots with zombies at the door, in the dark, and when overloaded.
  `tev1:0.8b` answers `wait` in 18 of 31 situations.
- Confidence: `tev1:4b` was right on every answer with confidence ≥0.7, but that's only 10% of decisions.
  Routing low-confidence cases to Qwen gave 75% sensible / 5% bad (estimated offline), barely better than
  Qwen alone.
- Ollama's `/v1/systemone` ignores `options.num_gpu`, so these models always load onto the GPU. Both
  models' Ollama packages ship the Apache 2.0 licence text.

## Next step

Zero-shot decision models aren't worth the extra moving part yet. The plan that fits the data:

1. **Phase 1:** rules (`bench/rules.py`, ported to Lua) make the decisions. Qwen3.5-4B writes the speech
   bubble and gets consulted when the top rule scores are close. Every decision gets logged with its percept.
2. **Then:** use those logs, plus your corrections, to fine-tune a small decision model (Julia-1 at 144M or
   Laya at 421M train on this RTX 2060; `tev1` is a Qwen3.5 fine-tune). Re-run this benchmark, plus a
   held-out set from real play, before letting it drive.

## Sources

- Jev: [MarkTechPost launch article](https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/) ·
  [OpenRouter Jev docs](https://openrouter.ai/docs/guides/community/jev) ·
  [OpenRouter jev-1.13 pricing](https://openrouter.ai/typesafe/jev-1.13) ·
  [Is Jev open source? (madewithjev)](https://madewithjev.com/open-source-jev) ·
  [Jev architecture: undisclosed](https://systemonemodels.org/guides/jev-architecture/)
- REFLEX paper: [arXiv 2609.26532](https://arxiv.org/abs/2609.26532) · JEV-Star (StarCraft II):
  [arXiv 2609.27331](https://arxiv.org/abs/2609.27331) · [jev-plays-starcraft-2 harness](https://github.com/rapidstartup/jev-plays-starcraft-2) ·
  [jevbench.dev leaderboard](https://jevbench.dev/leaderboard) · [JevBench (typed decisions)](https://github.com/fstandhartinger/jevbench)
- Ollama: [Ollama now supports Jev-style decision models](https://ollama.com/blog/ollama-now-supports-jev-style-decision-models) ·
  [tev1](https://ollama.com/library/tev1) · [tev1 tags](https://ollama.com/library/tev1/tags) · [nimble](https://ollama.com/library/nimble)
- llama.cpp: [Decision-model support and GGUFs (explainx)](https://explainx.ai/blog/llama-cpp-decision-model-support-2026)
- Julia-1: [model card](https://huggingface.co/SupersonicLabs/Julia-1) ·
  [MarkTechPost](https://www.marktechpost.com/2026/09/26/supersonic-labs-releases-julia-1-a-144-3m-parameter-open-decision-model-that-runs-on-a-cpu/)
- Laya: [model card](https://huggingface.co/convaiinnovations/laya) ·
  [Laya vs Jev (techaiwire)](https://techaiwire.com/articles/laya-open-weights-jev-typed-decisions/)
- Open reproduction: [open-jev-typed-decision-engine](https://github.com/eightman999/open-jev-typed-decision-engine) ·
  decider-4b: [JevBench comparison](https://jev-ai.pro/compare/jev-vs-decider) · Tev1 licence status:
  [llmconfigurator](https://llmconfigurator.com/en/models/tev1/tev1-4b)
- NitroGen: [CVPR 2026 paper](https://openaccess.thecvf.com/content/CVPR2026/html/Magne_NitroGen_An_Open_Foundation_Model_for_Generalist_Gaming_Agents_CVPR_2026_paper.html) ·
  [arXiv 2601.02427](https://arxiv.org/abs/2601.02427)
- V-JEPA: [V-JEPA 2 paper](https://arxiv.org/abs/2506.09985) · [vjepa2 repo](https://github.com/facebookresearch/vjepa2) ·
  [V-JEPA 2.1](https://arxiv.org/abs/2603.14482)
- FunctionGemma: [Google docs](https://ai.google.dev/gemma/docs/functiongemma) · TabPFN:
  [TabPFN-2.5 model card](https://huggingface.co/Prior-Labs/tabpfn_2_5) · [Prior Labs model licences](https://docs.priorlabs.ai/models)
- PZ NPC mods: [Bandits mod (PCGamesN)](https://www.pcgamesn.com/project-zomboid/bandits-mod) ·
  [B42 NPC mods overview](https://pzfans.com/zomboid_npc_mods_in_b42_surviving_the_apocalypse_with_friends/)
