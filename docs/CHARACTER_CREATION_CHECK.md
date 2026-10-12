# Character creation menu, gym 0.4.44

Backlog G6, 2026-10-12. The screen's points calculation was already implemented in `creationPoints`;
the remaining changes are selecting a profession, respecting the actual Next button, and preserving
the profession's free traits during emergency debt repair. The owner's option B stays unchanged:
buy good traits only down to `DEBT_LIMIT = -12`, then add bad traits only until debt is repaid.

## Verified installed 42.21 sources

Game paths are relative to `media/lua` in Project Zomboid 42.21.0 (Steam build 25485521,
revision 4a0e9546ec):

- `client/OptionScreens/CharacterCreationProfession.lua:434-488`, `onSelectProf`: selects the real
  definition and applies its free traits, exclusions, skills, points and clothes. `populateProfessionList`
  at 871-875 fills the real list with `profession:getUIName()` and a definition as `item`.
- The same file, `render` at 827-836: enables Next only when `PointToSpend() >= 0`. `PointToSpend`
  at 860-866 includes profession cost, sandbox free points and the negative-trait penalty.
- `client/ISUI/ISButton.lua:onMouseUp` checks `enable` before invoking the handler; `isEnabled`
  at 441-442 exposes it. Directly calling the screen's NEXT handler bypasses this check.
- `CharacterCreationProfession.lua:onSelectChosenTrait` (375), `addTrait` (649), `removeTrait` (700)
  and list builders (901/912): profession-granted traits are free and cannot be removed/bought.
- `CharacterCreationProfession.lua:1097` reads `MainScreen.instance.desc:getCharacterProfession()`
  when resolving the normal spawn points for the selected profession.

## Resulting behavior

Every new character first gets the real profession list as `choose_profession` options, including
the screen's names, types and point costs. The agent's answer selects that list item and calls
`onSelectProf`. A refusal is a failed choice; an unavailable/refusing list retains the screen's
already selected profession through the existing bounded failure fallback. A reload in the middle
of an old trait-choice sequence lets that sequence finish rather than changing its profession.

The good-trait buying and bad-trait repayment stages then proceed with the same rule as before.
Next is invoked through the actual `playButton` only when the game's points are known, nonnegative,
and the button is enabled. Emergency repair removes only non-free, paid traits. If it cannot repay
the debt, Next stays disabled; it does not bypass the game's legality check.

The selected profession is visible in creation and in the character's descriptor. It is deliberately
included in `agent/features.py` as the same hashed token in both contexts. The option uses existing
name/type/category/cost inputs. No dense layout, features version, trained network, reward, policy
settings, town selection or game speed changes. Restarting the agent is needed for its new state
token; its existing option encoder already accepts the new verb and fields.

## Validation

All 126 unit tests pass, including the installed game's Lua compilation and method-name checks,
the preserved option-B tests and a profession-token test linking creation to the life without
changing dense inputs. This is source/compiler validation; a live result is still needed.

After reloading gym 0.4.44, observe a natural death/respawn: a profession choice completed, the
displayed points including its cost, good purchases respecting -12, bad traits only while in debt,
Next enabled before proceeding, and the new life's profession matching the selected type. Do not
force a death, choose a profession for the network or stage a scenario to obtain these examples.

### Natural respawn checked at 21:57

The loader accepted mod 0.5.8 / gym 0.4.44. At 21:57:29, decision 12753 offered 25 professions with
eight displayed points; the bot chose Park Ranger. At 12754 its selection was done and the game
displayed -4 points. It chose Nutritionist (cost 2), displayed points became -6, and it chose
`done_buying`. During repayment it chose Prone to Illness (cost -4), leaving -2, then Sleepyhead
(cost -4) to repay the remaining debt. At 21:57:37 the next life, Len Spooner, was playing with
`profession: base:parkranger`, matching the selected type, and an empty gym error field.

The actual final button state was not serialized into a decision record; proceeding passed the
running `creationReady` guard, which requires known nonnegative game points and an enabled button.
This verifies a normal full profession/buy/pay/start path. It does not exercise the emergency-repair,
missing-list or timeout fallbacks. No deaths or choices were forced. Three new lives in the flushed
sample had Park Ranger; the new profession state token still needs the owner to restart Python.
