# Scheduled runs

Rules for the unattended Claude runs on this repository. The owner's scheduled prompt points here; this file
holds the detail so the prompt stays short.

## Where to work

- Everything goes to `main`. Branch from the latest `main`, open a PR into `main`, merge it and delete the
  branch in the same run. Leave no branch behind. Never force-push `main`.
- Continue an open PR of your own instead of opening a duplicate.
- The owner and a local Claude session also commit to `main`: fetch before you start and before you merge.
- Do not start Phase 5.

## Every run ships work

Each run ends with at least one merged PR that closes or advances a backlog item. "Nothing was possible" is
acceptable only if every step below was tried and each one has a specific blocker written down. Being unsure
is not a blocker: if a step is possible but you hesitate, do a smaller version of it.

Take the first step that has something you can do, and do more than one if time allows:

1. **Health.** `python -m unittest discover -s tests` passes (the network tests skip without PyTorch). Keep
   the README current: install, run, controls, known issues.
2. **Phase 4 gaps that don't need the game.** For example: backlog O6 (per-kind item encoding, once the gym
   exposes item status O1-O5); N4 (flush the experience log on a timer); robustness of reading, salvage,
   caching or the dashboard in `agent/`.
3. **Phase 3 gaps that widen what the network can do or perceive.** Missing player actions (exercise, full
   crafting, disassembly, vehicles, repairs, inventory organisation), hearing a player could perceive, and
   the leaks in [OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md). A new observation field reaches the network
   only once it is on the allow-list in `agent/features.py`.
4. **The Python half of a blocked item.** Where the Lua half needs the game's files, still do the rest:
   tokens in `agent/features.py`, option handling, and unit tests with a fake `obs.json`. Mark the Lua half
   "needs the game's files" in the backlog.
5. **Leaks shielded in Python.** Drop or coarsen a leaked field in `agent/features.py` without changing the
   dense layout (as in commits d6e5438 and 64ae0f6).
6. **Tests.** Cover untested code (for example `features.item_status_tokens`, `read_records` salvage,
   `transitions`), or add a regression test for a bug recorded in the backlog.
7. **Documentation accuracy.** Check claims in `README.md`, [BACKLOG.md](BACKLOG.md) and
   [PHASE3_COVERAGE.md](PHASE3_COVERAGE.md) against the code: statuses, versions, line references. Mark
   finished items done, with the commit.

## Limits

- **No invented game APIs.** Runs can't start Project Zomboid and usually don't have its files. A Lua change
  that calls a game API needs a citation: the installed game's Lua or Java, or a repo doc that cites it
  ([ACTION_CATALOGUE.md](ACTION_CATALOGUE.md), [GAP_LIST.md](GAP_LIST.md),
  [OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md), the API lists in [BACKLOG.md](BACKLOG.md)). Without one, do
  step 4. Never claim live-game validation. Lua changes reach the game only after a pull and
  `scripts/reload-mod.ps1`.
- **Keep the trained network.** Prefer hashed tokens in `agent/features.py`. Changing the dense layout means
  bumping `features.VERSION`, which throws the trained network away: only when there is no other way, and
  say so in the report.
- **The owner's decisions; leave them alone:**
  - the reward (`agent/reward.py`);
  - the trait rule (option B, `DEBT_LIMIT`);
  - the training algorithm and its settings (runs can't see the training logs);
  - anything that scripts behaviour, stages scenarios or imitates the owner;
  - the game's speed and display settings.
- **Local only.** Everything binds to 127.0.0.1. Use the dependencies already installed; ask before
  installing anything.
- **Small and sound.** Run the tests before every push. One clean merged PR beats a large unfinished one.

## Report

End each run with a short report:

- what changed, with the PR number, and which backlog item it advances;
- how it was verified;
- what needs testing in the game, if anything;
- for each step skipped, the specific blocker (for example "O4: no `ISVehicleMechanics` source to cite").
  Record new blockers in [BACKLOG.md](BACKLOG.md) so the next run doesn't repeat the search.
