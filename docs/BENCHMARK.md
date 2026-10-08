# Phase 0 — brain benchmark

**Date:** 2026-10-08 · **Ollama:** 0.40.1 · **GPU:** RTX 2060 6 GB · **PZ:** closed for all runs so far
(see "Still to measure")

## Setup

- **31 hand-made situations** (`bench/snapshots.py`): hunger, thirst, chases, hordes, night, bleeding, a
  bite, overloaded, exhausted, panic, soaked, food poisoning, water shut-off, a helicopter event, and others.
  Each one lists its legal goals, a "sensible" set and a "dangerous/wasteful" set.
- **LLM settings as planned:** the `format` JSON schema with `goal` as an enum of the legal goals,
  `think:false`, `keep_alive:-1`, `num_ctx 4096`, `temperature 0.3`, `num_predict 80`. Prompt ≈ 630 tokens
  (≈ 1,100 with `--long`). Answers are ≈ 24 tokens.
- 3 repeats per situation (1 for the CPU and long-prompt latency runs). Latency is wall-clock per decision,
  measured after the model was already loaded.
- **`rules`** is a no-LLM baseline (`bench/rules.py`): a hand-written utility scorer over the same
  percept. ⚠️ I wrote both the rules and the "sensible" answers, so its 100% is optimistic. It shows
  what simple rules can do, not how they'd perform on situations nobody planned for.

## Results

| Config | Valid JSON | Sensible | Bad | Stable | Median ms | p95 ms | Cold start ms | Prompt tok (max) | Model VRAM MiB | GPU used before → peak MiB |
|---|---|---|---|---|---|---|---|---|---|---|
| rules · auto · PZ closed | 100% | 100% | 0% | 100% | <1 | <1 | <1 | – | – | – |
| qwen3.5:4b · auto · long · PZ closed | 100% | 65% | 6% | 100% | 1,152 | 1,194 | 5,335 | 1115 | 2983 / 2983 | 1562 → 5308 |
| qwen3.5:4b · auto · PZ closed | 100% | 73% | 5% | 90% | 801 | 896 | 4,971 | 632 | 2983 / 2983 | 1618 → 5408 |
| qwen3.5:4b · auto · why-first · PZ closed | 100% | 68% | 6% | 45% | 817 | 908 | 4,661 | 632 | 2983 / 2983 | 1582 → 5313 |
| qwen3.5:4b · cpu · PZ closed | 100% | 71% | 3% | 100% | 7,784 | 8,664 | 12,182 | 632 | 0 / 2989 | 1575 → 1565 |
| qwen3.5:latest · auto · PZ closed | 100% | 81% | 2% | 84% | 3,616 | 4,127 | 15,810 | 632 | 3357 / 5864 | 1561 → 5687 |
| qwen3:4b · auto · PZ closed | 100% | 66% | 5% | 94% | 559 | 641 | 11,382 | 604 | 3031 / 3031 | 1561 → 4691 |

"Sensible" means the goal was in the acceptable set. "Bad" means it was in the dangerous/wasteful set.
"Stable" means all 3 repeats agreed.

## What the numbers say

1. **The output format is solved.** Every config gave 100% valid JSON with a legal goal, because the
   schema enum makes illegal goals impossible.
2. **Decision quality is the weak point.** `qwen3.5:4b` picked a sensible goal 73% of the time and a
   dangerous one 5% of the time. `qwen3.5:9b` reached 81%/2%. The older `qwen3:4b` got 66%. The rule
   scorer got all 31 (with the caveat above).
3. **Typical LLM mistakes** (all from the 4B):
   - drinks when severely hungry with food in the bag (the 9B does this too)
   - loots a house **in the dark with no flashlight**
   - goes looting while **overloaded**
   - eats when full
   - rests instead of sleeping when severely tired at a secured home
   - flees from a single zombie while holding a bat

   Some of these are only conservative (fleeing, resting), but looting in the dark and looting while
   overloaded are real ways to die.
4. **Reason-before-goal is worse.** Putting `why` before `goal` in the schema dropped accuracy to 68% and
   consistency across repeats to 45%; it often invented thirst ("I need water"). Keep `goal` first.
5. **More context hurts.** Adding ~25 memory lines (1,115 tokens) cost ~350 ms and *dropped* accuracy to
   65%. The percept should stay short.
6. **Latency on this machine:**

   | Config | Per decision |
   |---|---|
   | 4B on GPU | 0.8 s (p95 0.9 s) |
   | 4B, long prompt | 1.15 s |
   | 4B on CPU only | 7.8 s (p95 8.7 s) |
   | 9B (57% on GPU) | 3.6 s |
   | Rules | <0.1 ms |
7. **VRAM:**
   - **4B:** takes 2,983 MiB itself; with the CUDA context, GPU usage went from ~1.6 GB to **5.4 of 6.1
     GB** before PZ was even running. **With PZ open it won't fit entirely on the GPU** unless desktop apps
     are closed. Expect latency somewhere between the GPU and CPU numbers. Not yet measured.
   - **9B:** only 3.4 of its 5.9 GB fit on the GPU.

## Winner

- **As the LLM brain: `qwen3.5:4b`, goal-first, short percept.** It's the only option that is both
  reasonably fast and reasonably good on this GPU. The 9B is more accurate but 4–5× slower and doesn't fit
  alongside PZ.
- **As the decision-maker: a rule/utility scorer beat every LLM here, in under a millisecond, with no
  VRAM.** The likely best design for this PC is a hybrid: rules pick the goal, and the LLM narrates, plus
  possibly breaks ties or vetoes in unusual situations. A small model trained on logged decisions could
  replace the rules later. This needs your decision before Phase 1.

## Still to measure

- [ ] **With PZ open** (load a save, then `python bench/run_bench.py --model qwen3.5:4b`). This is the
      decisive VRAM/latency number.
- [ ] `qwen3.5:2b-q4_K_M` (1.9 GB): would fit on the GPU alongside PZ. Needs a download (approval).
- [ ] Gemma 4 challenger: `gemma4:e2b-it-qat` (4.3 GB) is the realistic size here; `gemma4:e4b-it-qat`
      (6.1 GB) would run mostly on CPU. Needs a download (approval).
- [ ] A fairer test set: situations written by you, or taken from real game logs in Phase 1, that the rules
      weren't written against.

## Reproduce

```bash
python bench/run_bench.py --model qwen3.5:4b
```

```bash
python bench/report.py
```

Raw answers, including every "why" line, are in `bench/results/raw/*.jsonl`.

## Appendix: every situation, every config

<details><summary>Per-snapshot picks (✅ all sensible · ⚠️ some not sensible · ❌ at least one dangerous pick)</summary>

| Snapshot | Sensible | rules · auto · PZ closed | qwen3.5:4b · auto · long · PZ closed | qwen3.5:4b · auto · PZ closed | qwen3.5:4b · auto · why-first · PZ closed | qwen3.5:4b · cpu · PZ closed | qwen3.5:latest · auto · PZ closed | qwen3:4b · auto · PZ closed |
|---|---|---|---|---|---|---|---|---|
| `day1_start` | loot_here | ✅ loot_here | ✅ loot_here | ✅ loot_here×3 | ⚠️ drink×2, loot_here | ⚠️ drink | ✅ loot_here×3 | ⚠️ secure_building×3 |
| `thirsty_sink` | drink | ✅ drink | ⚠️ fill_water | ⚠️ fill_water×3 | ⚠️ fill_water×2, drink | ⚠️ fill_water | ✅ drink×3 | ✅ drink×3 |
| `hungry_has_food` | eat | ✅ eat | ⚠️ drink | ⚠️ drink×3 | ⚠️ eat×2, drink | ⚠️ drink | ⚠️ drink×3 | ✅ eat×3 |
| `hungry_thirsty_empty` | loot_building | ✅ loot_building | ✅ loot_building | ✅ loot_building×3 | ✅ loot_building×3 | ✅ loot_building | ⚠️ explore×2, loot_building | ⚠️ explore×3 |
| `lone_zombie_armed` | fight | ✅ fight | ⚠️ flee | ⚠️ flee×3 | ⚠️ flee×2, fight | ⚠️ flee | ✅ fight×3 | ❌ loot_building×3 |
| `group_five_chasing` | flee | ✅ flee | ✅ flee | ✅ flee×3 | ✅ flee×3 | ✅ flee | ✅ flee×3 | ✅ flee×3 |
| `horde_approaching_indoors` | secure_building, hide, flee | ✅ secure_building | ✅ secure_building | ✅ secure_building×3 | ✅ secure_building, flee, hide | ✅ secure_building | ⚠️ secure_building×2, loot_here | ✅ flee×3 |
| `night_outdoors_no_light` | retreat_home | ✅ retreat_home | ❌ loot_building | ❌ loot_building×3 | ❌ wait, loot_building, retreat_home | ❌ loot_building | ❌ retreat_home×2, loot_building | ✅ retreat_home×3 |
| `night_home_tired` | sleep | ✅ sleep | ⚠️ rest | ⚠️ rest×3 | ⚠️ rest×3 | ⚠️ rest | ✅ sleep×3 | ✅ sleep×3 |
| `tired_zombies_near_unsecured` | secure_building, hide, fight | ✅ secure_building | ✅ secure_building | ✅ secure_building×3 | ❌ sleep×2, secure_building | ✅ secure_building | ✅ secure_building×3 | ❌ secure_building×2, sleep |
| `bleeding_safe` | bandage | ✅ bandage | ✅ bandage | ✅ bandage×3 | ✅ bandage×3 | ✅ bandage | ✅ bandage×3 | ✅ bandage×3 |
| `bleeding_chased` | flee | ✅ flee | ✅ flee | ✅ flee×3 | ⚠️ bandage×2, flee | ✅ flee | ✅ flee×3 | ✅ flee×3 |
| `bitten_at_home` | bandage | ✅ bandage | ✅ bandage | ✅ bandage×3 | ✅ bandage×3 | ✅ bandage | ✅ bandage×3 | ✅ bandage×3 |
| `house_fully_looted` | loot_building, explore | ✅ loot_building | ⚠️ retreat_home | ⚠️ retreat_home, rest, loot_building | ⚠️ secure_building×2, retreat_home | ⚠️ secure_building | ⚠️ retreat_home×3 | ⚠️ secure_building×3 |
| `overloaded_near_home` | retreat_home, drop_weight | ✅ retreat_home | ❌ loot_building | ❌ loot_building×2, retreat_home | ❌ drop_weight×2, loot_building | ✅ drop_weight | ❌ retreat_home×2, explore | ❌ retreat_home×2, loot_building |
| `exhausted_safe` | rest | ✅ rest | ⚠️ loot_here | ✅ rest×3 | ✅ rest×3 | ✅ rest | ✅ rest×3 | ⚠️ loot_here×3 |
| `exhausted_zombies_close` | hide, flee | ✅ flee | ✅ flee | ✅ flee×3 | ✅ flee×3 | ✅ flee | ✅ flee×3 | ✅ flee×3 |
| `unarmed_has_weapon` | equip_weapon | ✅ equip_weapon | ✅ equip_weapon | ✅ equip_weapon×3 | ⚠️ equip_weapon×2, loot_building | ✅ equip_weapon | ✅ equip_weapon×3 | ⚠️ loot_building×3 |
| `panic_after_chase` | rest, hide, wait | ✅ rest | ⚠️ loot_here | ⚠️ loot_here×3 | ✅ rest×3 | ⚠️ loot_here | ⚠️ loot_here×3 | ⚠️ loot_here×3 |
| `soaked_cold` | retreat_home | ✅ retreat_home | ✅ retreat_home | ✅ retreat_home×3 | ⚠️ change_clothes×3 | ✅ retreat_home | ✅ retreat_home×3 | ✅ retreat_home×3 |
| `food_poisoning` | rest, sleep, drink, wait | ✅ rest | ✅ drink | ✅ drink×3 | ❌ eat×2, drink | ✅ drink | ✅ wait×3 | ✅ rest×3 |
| `water_shutoff` | drink | ✅ drink | ⚠️ loot_here | ✅ drink×3 | ✅ drink×3 | ✅ drink | ⚠️ loot_here×3 | ⚠️ loot_here×3 |
| `all_good_daytime` | loot_building, explore | ✅ loot_building | ⚠️ eat | ⚠️ eat×3 | ✅ loot_building×3 | ⚠️ eat | ⚠️ loot_building, explore, eat | ⚠️ rest×3 |
| `zombies_at_door` | secure_building, fight | ✅ fight | ✅ secure_building | ✅ secure_building×3 | ⚠️ hide×2, secure_building | ✅ secure_building | ✅ secure_building×3 | ✅ secure_building×3 |
| `dusk_far_from_home` | retreat_home, loot_building | ✅ retreat_home | ✅ retreat_home | ✅ retreat_home×3 | ✅ loot_building×2, retreat_home | ✅ retreat_home | ✅ loot_building×3 | ✅ retreat_home×3 |
| `pain_painkillers` | take_medicine, rest | ✅ take_medicine | ✅ take_medicine | ✅ take_medicine×3 | ⚠️ wait, rest, take_medicine | ✅ take_medicine | ✅ take_medicine×3 | ✅ rest×3 |
| `weapon_breaking` | equip_weapon | ✅ equip_weapon | ✅ equip_weapon | ✅ equip_weapon×3 | ✅ equip_weapon×3 | ✅ equip_weapon | ✅ equip_weapon×3 | ⚠️ loot_building×3 |
| `surrounded` | flee, fight | ✅ flee | ✅ flee | ✅ flee×3 | ✅ flee×3 | ✅ flee | ✅ flee×3 | ✅ fight×3 |
| `extreme_thirst_blocked` | fight, drink | ✅ drink | ✅ drink | ✅ drink×3 | ✅ drink×3 | ✅ drink | ✅ drink×3 | ✅ drink×3 |
| `night_home_not_tired` | wait, rest | ✅ wait | ✅ wait | ✅ wait×3 | ⚠️ wait×2, eat | ✅ wait | ✅ wait×3 | ✅ wait×3 |
| `helicopter_event` | retreat_home, hide, flee | ✅ retreat_home | ✅ retreat_home | ✅ hide×2, retreat_home | ✅ flee, hide, retreat_home | ✅ retreat_home | ✅ retreat_home×3 | ✅ flee×3 |

</details>
