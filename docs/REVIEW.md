# Code review of the two reference repos (2026-10-08)

Both repos were cloned into a scratch folder and **read, not run**. Nothing from them was installed or
executed on this PC. AI-v-Z copies selected code from both (MIT; see
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)) and leaves out the parts flagged below.

## botsofcog/claude-survives-zomboid (commit `418c19f`, 2026-07-16, 9 commits)

| Part | Verdict |
|---|---|
| `mods/ClaudeSurvivor/.../ClaudeSurvivor.lua` (33 KB) | **Safe.** It only calls Project Zomboid's own APIs. File access is limited to two fixed names in the game's sandboxed `Zomboid/Lua` folder (`claude_percept.json`, `claude_intent.txt`). There is no `loadstring`, OS call or network call. The same file is copied 4× in the repo (identical hashes). |
| `bridge/pz-bridge.mjs` | **Exposed to the network.** `server.listen(8799)` has no host, so it binds every interface: anyone on your LAN can read `/api/state` and use `/god`. `/god` is a **GET** that puts text straight into the LLM prompt, so any web page you visit can also trigger it (CSRF). Not malicious, but don't run it as is. |
| `bridge/llm.mjs` | Default backend is the `claude` CLI, spawned with `shell: true`. It also offers cloud backends (Anthropic, OpenAI, Gemini, OpenRouter) through API keys in environment variables. The prompt is passed through stdin or as an argument; no other command injection was found. |
| `install.ps1` | Fine: copies the mod into `%USERPROFILE%\Zomboid\mods`, deleting any existing copy there first. |
| `.github/workflows/ci.yml` | Fine: syntax checks only. |
| Game API details | Some calls predate 42.21. For example, `ISOpenCloseCurtain:new` is given a window and an extra argument; in 42.21 the signature is `(character, item)`. Curtains are left out of AI-v-Z for now. |

**What AI-v-Z took:** the percept/intent file IPC, the reflex structure (fight when it can win, otherwise
break away), sneaking at mid range, the HUD layout, auto fast-forward, manual override.
**Left out:** the Node bridge (rewritten in Python, bound to `127.0.0.1`, no state-changing endpoints), the
"voice from beyond" channel, the cloud backends.

## whatcheers/Claude-Plays-ProjectZomboid (commit `1f13c89`, 2026-10-03, 33 commits, mod v0.14.0)

| Part | Verdict |
|---|---|
| `mod/ClaudeBot/42/.../ClaudeBot.lua` (3,250 lines) | Mostly solid, recent, and written for 42.20.4. **One real hazard:** the `eval` command runs `Zomboid/Lua/claudebot/eval.lua` through `reloadLuaFile`, so **any local program can run arbitrary Lua inside your game** by writing that file and a command. It's meant for debugging, but it's always on. |
| `ClaudeBotLoader.lua` | Hot reload via `reloadLuaFile` of the mod's own file when `claudebot/reload.txt` changes. This one is fine: it only re-runs code that's already in the mod folder. |
| `pz.py` | `pz.py watch` serves the turn log on **`0.0.0.0:5160`** and prints your LAN IP, so it's read-only but visible to your whole network. |
| `watch.html` | Loads fonts from Google Fonts, an external request each time it's opened. |
| `install.cmd` | **Don't run as is.** Besides linking the mod, it copies `.claude/agents/pz-player.md` into your **global** `%USERPROFILE%\.claude\agents\`, which installs a Claude Code agent prompt into every Claude Code session on this PC. |
| `.claude/agents/pz-player.md` | An agent prompt for Claude Code ("You are the player…"). It's plain text, but it's instructions aimed at an AI; treat it as content, not something to install. |

**What AI-v-Z took:** the JSON encoder, pathfinding with `ISPathFindAction:pathToLocationF` and failure
callbacks, container walking and transfers, drinking straight from sinks (`ISTakeWaterAction`), the
attack/shove details (aim at the floor for downed zombies, shove when inside weapon reach), the flee-square
search, wound and stat reading, and the hot-reload loader **without `eval`**.

## AI-v-Z's own exposure, for comparison

- The IPC files in `%USERPROFILE%\Zomboid\Lua\aivz\` can drive the character. Any program running as you
  can write `intent.txt`, which is the same trust level as your mods folder. Nothing in AI-v-Z executes
  code from those files.
- The dashboard binds `127.0.0.1` only, refuses requests whose `Host` isn't `127.0.0.1`/`localhost`
  (blocking DNS rebinding), and has no endpoints that change anything.
- The bridge only talks to Ollama on `127.0.0.1` and refuses any other host.
