# Machine specs (measured 2026-10-08)

> Ollama is no longer used by AI-v-Z (removed 2026-10-09); its rows are kept as a record.

Collected with `Get-CimInstance`, `nvidia-smi`, `Get-PSDrive` and the Ollama API on this PC.
Re-run these checks if the hardware, driver, Ollama or game version changes.

## Hardware

| Item | Value |
|---|---|
| OS | Windows 11 Home, 10.0.26200 (64-bit) |
| CPU | Intel Core i9-10900K @ 3.70 GHz, **10 cores / 20 threads** (Comet Lake: AVX2, no AVX-512) |
| RAM | **32 GB** (31.9 GB usable; ~13.9 GB free with the usual apps open) |
| Motherboard | Gigabyte Z490 AORUS MASTER |
| GPU | **NVIDIA GeForce RTX 2060, 6 GB** (6144 MiB), Turing |
| Driver / CUDA | NVIDIA 610.74, CUDA 13.3 (WDDM) |
| Display | 1920×1080 |
| VRAM already in use at idle | **~1.7 GB**: Windows shell, Chrome, Edge, Discord, Slack, Signal, WhatsApp, ChatGPT, Claude, iCUE, NVIDIA overlay, Steam |

### Disk

| Drive | Free | Notes |
|---|---|---|
| C: | 62 GB | Was 35 GB until the old Ollama store (`%USERPROFILE%\.ollama\models`) was deleted on 2026-10-09 |
| D: | 303 GB | Steam library with Project Zomboid |
| E: | ~273 GB | This project (`E:\Source\AI-v-Z`) and, since 2026-10-08, **Ollama's model store** (`E:\Ollama\models`) |

## Software

| Tool | Version | Path |
|---|---|---|
| Ollama | **0.40.1** (see note) | `%LOCALAPPDATA%\Programs\Ollama` |
| Node | v24.18.0 (npm 11.16.0) | `C:\Program Files\nodejs` |
| Python | 3.14.6 (`python`, `py`), 3.13.14 (`python3`), 3.12 | |
| git | 2.42.0.windows.2 | |
| JDK | Microsoft OpenJDK 11 (`javap` on PATH) | |

> **Ollama auto-updated during the spec check.** Running `ollama list` started the Ollama tray app because
> its server wasn't running, and the app's updater installed 0.40.1 over 0.35.1. 0.40.1 has been tested
> and works (schema-constrained JSON + `think:false` verified). To keep a fixed version, turn off
> auto-update in the Ollama app settings.

### Ollama model store

Moved to **`E:\Ollama\models`** on 2026-10-08. The existing models were copied there (35.4 GB, 58 files),
and the Ollama app's *Model location* setting now points at E:. That's the `models` column in
`%LOCALAPPDATA%\Ollama\db.sqlite`, the same field the Settings screen writes. The server log confirms
`OLLAMA_MODELS:E:\Ollama\models`. All 50 blobs on E: were checked against their SHA-256 names
(38.6 GiB, 0 mismatches) before the old copy on C: was deleted on 2026-10-09.

The store holds 35 GB, not the 26 GB first measured: on the first run of each Qwen 3.5 model, Ollama 0.40.1
made a converted copy (listed as `llamacpp:<hash>`; +2.7 GB for the 4B, +5.7 GB for the 9B). That's
internal to Ollama, so leave it alone.

### Ollama models on disk

| Tag | Params | Quant | Size |
|---|---|---|---|
| `qwen3.5:4b` | 4.7B (incl. vision tower) | Q4_K_M | 3.39 GB |
| `qwen3.5:latest` (= 9B) | 9.7B | Q4_K_M | 6.59 GB |
| `qwen3:4b` | 4.0B | Q4_K_M | 2.5 GB |
| `qwen2.5:3b` | 3.1B | Q4_K_M | 1.93 GB |
| `qwen2.5-coder:1.5b-base` | 1.5B | Q4_K_M | 0.99 GB |
| `codestral:latest` | 22.2B | Q4_0 | 12.57 GB |
| `tev1:0.8b` (decision model, added 2026-10-08) | 0.75B | Q8_0 | 0.81 GB |
| `tev1:4b-q4_K_M` (decision model, added 2026-10-08) | 4.2B | Q4_K_M | 2.7 GB |

## Project Zomboid

| Item | Value |
|---|---|
| Install | Steam, `D:\Program Files\steamapps\common\ProjectZomboid` |
| Game version | **42.21** (from `zombie/core/Core.class` → `GameVersion(42, 21)`), git rev `4a0e9546ec`. Mod-break version 42.0. Updated from 42.20 (`b0bbce05d5`) on 2026-10-08 |
| Steam build | `25485521` (latest available on 2026-10-08) |
| Branch | Default (no beta key), so B42 is the stable branch |
| JVM heap | `-Xmx3072m` (from `ProjectZomboid64.json`) |
| User folder | `%USERPROFILE%\Zomboid` (has `Lua\`, `mods\`, `Saves\`, `Logs\`) |
| Last game launch | `console.txt` is dated **2024-06-20 (Build 41)**, so B42 hasn't been launched on this PC yet. Old saves are B41 and won't load in B42 |

## First measurements (PZ closed, warm model)

Probe: `qwen3.5:4b`, `num_ctx 4096`, `think:false`, `format` = JSON schema with a goal enum, 85-token
prompt, ~40-token answer.

| Mode | VRAM | Prompt speed | Generation speed | Total per decision |
|---|---|---|---|---|
| Full GPU (auto) | 2983 MiB model (nvidia-smi +3.8 GB incl. CUDA context) | ~1500 tok/s | ~55 tok/s | **0.78–0.80 s** |
| CPU only (`num_gpu: 0`) | 0 | ~500 tok/s | ~7.4 tok/s | **5.6–5.9 s** |

Rough estimate for a full ~1.5k-token percept: about 1.8 s on GPU and about 8.5 s on CPU. The benchmark
measures this directly.
The first call after the Ollama update spent 25 s loading and 32 s on the prompt; that only happens once.

## VRAM budget

```
6144 MiB  total
-1700     Windows + desktop apps at idle (can be reduced: close/disable HW accel in Chrome, Discord, Slack…)
-1000..2000  Project Zomboid B42 at 1080p (estimate, to be measured)
-3800     qwen3.5:4b loaded on GPU incl. CUDA context (measured)
= -360 .. -1360 MiB  → does not fully fit with everything open
```

## Recommendation

Your machine is in the **≤6 GB VRAM tier**, so the brain is **Qwen3.5-4B (`qwen3.5:4b`, Q4_K_M)**.

- With PZ running, the 4B model probably won't fit entirely on the GPU, and Ollama will move some layers to
  the CPU. The benchmark needs to measure three setups: (a) auto-offload with PZ open, (b) CPU only, and
  (c) a smaller model that fits entirely on the GPU (`qwen3.5:2b-q4_K_M`, 1.9 GB).
- **Brain cadence:** about 5 s if the model stays mostly on the GPU, about 10 s on CPU (your table's
  estimate matches what I measured).
- Closing the GPU-heavy background apps (or turning off their hardware acceleration) frees about 1 GB of
  VRAM. That is probably the difference between full-GPU and partial-CPU.

### Problems with the original plan

1. **Qwen3.5-9B can't be the default here.** `qwen3.5:9b` Q4_K_M is 6.6 GB, larger than the whole card. It
   is already installed as `qwen3.5:latest`, so it can be tested as a reference, not as a contender.
2. **Gemma 4 E4B is much bigger than "4B" suggests.** On ollama.com, `gemma4:e4b-it-q4_K_M` is 6.6 GB and
   `gemma4:e4b-it-qat` is 6.1 GB, because it carries per-layer embeddings plus vision and audio towers.
   That doesn't fit alongside PZ. A fair challenger on this card is **`gemma4:e2b-it-qat` (4.3 GB)**, or
   run E4B CPU-only and accept the slower latency.
3. **C: had only 35 GB free with the Ollama store on it.** Done: the store moved to `E:\Ollama\models`
   (see above). Deleting the old C: copy is your call.
4. **The PZ build will change under us.** Steam updates the game automatically. The README records the
   exact version each test ran against.

### Verified Ollama tags (ollama.com, 2026-10-08)

| Candidate | Tag | Size |
|---|---|---|
| Qwen3.5-9B | `qwen3.5:9b` / `qwen3.5:9b-q4_K_M` (`latest` = 9b) | 6.6 GB |
| Qwen3.5-4B | `qwen3.5:4b` / `qwen3.5:4b-q4_K_M` | 3.3 GB |
| Qwen3.5-2B | `qwen3.5:2b-q4_K_M` (plain `qwen3.5:2b` is the larger 2.7 GB build) | 1.9 GB |
| Gemma 4 E4B | `gemma4:e4b` (= `latest`), `gemma4:e4b-it-q4_K_M`, `gemma4:e4b-it-qat` | 6.6 / 6.1 GB |
| Gemma 4 E2B | `gemma4:e2b-it-qat`, `gemma4:e2b-it-q4_K_M` | 4.3 / 4.6 GB |
| Gemma 4 26B-A4B | `gemma4:26b-a4b-it-qat` | 16 GB (not for this PC) |
