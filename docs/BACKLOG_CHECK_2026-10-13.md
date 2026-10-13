# Local backlog check, 2026-10-13

Read-only review of the owner's running game and natural experience, through 13:19:46 British Summer Time.
No choices, deaths, items or practice situations were supplied. The owner restarted the game and agent at
13:06; this review did not restart them. This advances the earlier rows before G10 washing is implemented.

## N16/N17: heap and native audio hang

`logs/hang-20261013-125718-9380.txt` and `hang-20261013-130517-9380.txt` each contain three dumps.
All six place the game-logic **MainThread** in exactly this stack:

```
fmod.javafmodJNI.FMOD_Studio_EventInstance3D (Native Method)
fmod.javafmod.FMOD_Studio_EventInstance3D
fmod.fmod.FMODSoundEmitter$EventSound.tick
fmod.fmod.FMODSoundEmitter.tick
zombie.characters.CharacterSoundEmitter.tick
zombie.characters.IsoGameCharacter.updateEmitter
zombie.characters.animals.IsoAnimal.update
```

The render thread (`main`) waits in `SpriteRenderer.waitForReadyState`. Within each set the MainThread CPU
counter does not advance between dumps. This identifies a native audio call that is not returning; it does
not establish the reason inside that call or explain the earlier respawn hangs, for which there are no
dumps. No AIvZ or Kahlua frame appears in this game-logic stack. The game's volume being zero does not stop
its sound-emitter updates. **Blocker:** the captured wait is inside the game's native audio library, with
no demonstrated Lua fix. Keep the reports for a game/audio investigation; do not change the owner's sound
or gameplay settings as a speculative workaround.

`logs/gc-9380.log` has 38 old-generation Live samples, from 1,449 MB at 10:43 to 1,738 MB at 13:03. The last
six are 1,657 / 1,731 / 1,728 / 1,767 / 1,741 / 1,738 MB. This has grown since the previous review; it does
not prove either that another leak exists or that N16 is solved. The recipe cache resets at `G.newLife`,
the zombie cache is pruned at each observation and the moveable cache retains only the latest scan.
**Blocker:** this session ended before the required 90,000-decision run. Continue measuring the new
process's GC log; a larger heap is still an owner decision.

## Re-picking an action: longer comparison

Outcome counts group a selected option with subsequent `continue` choices and, from 11:30, equivalent
running-option picks. A terminal result belongs to the pending action, rather than being derived by
subtracting its tick age from a decision id. Play decisions exclude creation and death records.

| Interval | Play decisions | Logged done | Done/hour | Failed/1,000 decisions | Fence done / failed |
|---|---:|---:|---:|---:|---:|
| 09:30–11:30 | 15,472 | 4,368 | 2,184 | 84.2 | 129 / 127 |
| 11:30–12:55 | 15,948 | 3,110 | 2,195 | 37.4 | 189 / 63 |

The later period ends before the hang. This extends the first 13-minute check but is not an isolated
experiment: other gym changes and different lives also occurred. Total completions/hour hardly changed;
fence outcomes and failures improved. It does not support claiming a general throughput increase.

## Sitting and subsequent movement

Life 1056, `logs/experience/20261013-12.jsonl.gz`, naturally rested on furniture:

| Time | Decision | Visible result / chosen action |
|---|---:|---|
| 12:31:15 | 21217 | `rest` done, age 22; sitting and furniture posture true at (7825.5, 11287.5); chose `go_room` kitchen |
| 12:31:15 | 21218 | Sitting and furniture posture false; room walk running, at (7825.1, 11287.5) |
| 12:31:16 | 21219 | Standing at (7824.5, 11288.5), after changing the action to `smash` |
| 12:32:18 | 21464 | Separately selected `get_up` done, age 26; sitting false |

This verifies both getting up before movement after a furniture rest and completion of the explicit
Get Up action. The room walk above was replaced, so it is not evidence that that room walk finished.
The owner restarted the agent at 10:26 and 13:06, resolving the earlier token-restart prerequisite.
General long-session path/room verification remains separate from this completed sitting check.

## Treatments and supplies

Since 10:26:43, logged terminal outcomes include 17 bandages, five bandage removals, three glass removals,
two fills, 54 reads, 20 light switches and 57 stove switches. These are the executors' checked results,
not a screen inspection of every action. One fill at 12:52:54 (life 1068, decision 25460) used
`Base.JuiceBoxFruitpunch`; the source was marked tainted. There is no completed later bottle drink in
this sample. **G11 verification blocker:** no completed disinfect, stitch, splint, poultice, bullet
removal, burn cleaning, stitch/splint removal or pill use in this interval. Await natural supplies
and opportunities. G10 can advance with washing while that live verification waits.

The 68 network deaths since 10:26:43 have median survival 2.335 game hours and zero kills. Of 6,244
bleeding decisions, 1,480 offered a bandage and 92 picked it. This is a larger cohort than yesterday's
nine lives, but gym coverage and environments changed too; it does not establish a learning gain.
No reward, policy or training settings are changed by this review.
