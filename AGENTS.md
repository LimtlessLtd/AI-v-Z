# Working on AI-v-Z

The rules and working practice for anyone working on this repository: the owner, or any AI coding agent
(Claude, ChatGPT/Codex or another). Agent-specific files such as `CLAUDE.md` only point here.

A neural network on the owner's PC teaches itself to play Project Zomboid Build 42 singleplayer through a Lua
mod (the gym). Start with [README.md](README.md) (current state, how to run, known issues) and
[docs/BACKLOG.md](docs/BACKLOG.md) (what's open, in priority order, and who can take each item).

## The owner's rules

* Ask before installing anything (packages, tools, libraries).
* Everything lands on `main`: branch from the latest `main`, open a PR into `main`, merge it and delete the
  branch in the same session. No long-lived branches. Never force-push `main`.
* Commit at each milestone, and keep the README current: install steps, how to run, controls (F7, manual
  override), known issues. Pin the tested game build in the README's "Tested against" table.
* Local only: the IPC files in `%USERPROFILE%\Zomboid\Lua\aivz\` let any local program drive the character,
  and the dashboards bind 127.0.0.1. Nothing read from those files is ever executed.
* Unvetted code from elsewhere is read before it is run, and anything unsafe reported. Keep the MIT notices in
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
* Speed or memory numbers from blogs are estimates: measure on the owner's PC.
* One phase at a time; check in with the owner between phases. Phase 4 (learning) is in progress.
* No cloud services or language model in the agent, no multiplayer.
* The owner's decisions stay as they are unless the owner changes them: the reward (`agent/reward.py`,
  version 3), the trait rule (option B, `DEBT_LIMIT`), the training algorithm and its settings.
* The game runs windowed: never touch the display lines in the game's `options.ini`. Game speed is set with
  the game's own buttons only; nothing in the repo changes it.
* The network learns only from its own play: nothing that scripts its behaviour, stages practice scenarios or
  imitates the owner. It gets only what a player can perceive (`agent/features.py` is an allow-list).

## Working on the code

* Tests: `python -m unittest discover -s tests` must pass. The network tests skip without PyTorch, and
  `tests/test_lua.py` skips without the game.
* Lua runs only inside the game. Base every game call on the installed 42.21 Lua or `projectzomboid.jar`, and
  cite it. Calls already checked are cited in `docs/GAP_LIST.md`, `docs/ACTION_CATALOGUE.md` and
  `docs/OBSERVATION_AUDIT.md`. Expect an unloaded square or a missing object as nil, and test for it: don't
  lean on `pcall` (the game still logs every caught exception with a stack dump).
* On a PC with the game, `python -m unittest tests.test_lua` compiles the Lua with the game's own compiler and
  checks every method name against the game. Run it after any Lua change, wherever that change was written.
* Bump `G.VERSION` in `AIvZGym.lua` for gym changes and `A.VERSION` in `AIvZ.lua` for changes there;
  `Zomboid\Lua\aivz\loader.txt` shows which versions the game loaded.
* Never claim something works in the game unless it was run there. Lua changes reach the game after a pull
  and `scripts/reload-mod.ps1` (or a game restart).
* A new observation field reaches the network only once it is added to `agent/features.py`. Prefer hashed
  tokens: a change to the dense layout means bumping `features.VERSION`, which discards the trained network
  (an owner decision, backlog O6).
* Run the agent from `scripts/start.ps1` in its own window, never as a background task of an AI coding
  session: the task dies with the session (backlog N3).
* Record what you find in `docs/BACKLOG.md`: in "Open" with who can take it, details below it.
