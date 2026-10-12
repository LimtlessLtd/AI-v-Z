# Reward research and the version 3 proposal (2026-10-12)

The owner asked how our reward compares with other game-playing networks. Three points were raised:

1. Dying should cost far more than 1000.
2. Bandaging, healing and wearing protection should be rewarded, and taking clothes off should cost.
3. Putting something on and taking it off again must not earn points.

This page covers what the research says and what changes it suggests. **Nothing here is built yet**; the proposal
in section 4 needs the owner's go-ahead.

## 1. What comparable agents are rewarded for

| Agent / benchmark | Kind of game | Being alive | Damage and healing | Death | Progress | Discomfort (hunger etc.) |
|---|---|---|---|---|---|---|
| **Crafter** (Hafner 2021), 2D survival: food, water, sleep, zombies, night | closest to Project Zomboid | nothing per step | −0.1 per health point lost, **+0.1 per point regained** | **no death penalty**: "the reward signal already includes a penalty for losing health points" | +1 the first time each of 22 achievements is unlocked in an episode | **nothing**: hunger, thirst and tiredness count only through the health they cost |
| **OpenAI Five** (Dota 2, 2019) | team battle | nothing | health change worth 2 (whole bar), counted up and down; a quartic curve makes the last hit points worth most | **−1** | win +5, gold, experience, buildings | – |
| **Doom agents** (ViZDoom, e.g. arXiv 1807.01960) | shooter | nothing | −0.06 for lost health | **−1** | kill +1, item pickup +0.3 | – |
| **MineRL ObtainDiamond** | Minecraft | nothing | – | episode just ends | each item in the chain the first time: log 1, planks 2 … diamond 1024 | – |
| **NetHack (NLE)** | roguelike | nothing | – | episode just ends | in-game score; −0.001 for actions that don't advance time | – |
| **Atari DQN** (Mnih 2015) | arcade | – | – | a lost life ends the training episode; every reward clipped to ±1 | game score | – |
| **AI-v-Z version 2** (live after the next update) | Project Zomboid | +1 per game minute | −2 per health point lost, wounds −10 to −50, healing earns nothing | **−1000** | first items/buildings/containers, kills | nothing |

What stands out:

* **The structure matches common practice.** A steady signal for staying alive, health as the dense signal and
  one-off progress bonuses are the usual ingredients. Crafter, the nearest benchmark, is almost exactly the owner's
  rule: moodles cost nothing in themselves, and health is what counts.
* **Our death penalty is already unusually large.** Others use about the same weight as a full health bar
  (OpenAI Five: death −1, health 2), or none at all (Crafter, MineRL, NetHack). What decides behaviour is the
  death cost compared with everything else the agent can earn before its discount runs out, not the number
  itself. Version 2 discounts by half every 2 game hours, so staying alive can earn at most about 174 points
  ahead. A death at −1000 already outweighs that about six times.
* **Healing is rewarded everywhere that health is.** Crafter and OpenAI Five count health in both directions.
  Version 2 counts only losses.

## 2. Why "far worse death" alone isn't the fix: bites kill days later

Infection rolls in the installed game (42.21, `BodyPart.setScratched`, `setCut`, `SetBitten`, read from
`projectzomboid.jar` 2026-10-12):

* a zombie scratch infects 7% of the time
* a laceration 25%
* a bite always, unless the sandbox turns transmission off

An infected character dies about 2-3 days later. The network looks about 2 game hours ahead (half-life), so it
never connects the bite to the death that follows it. Raising the death penalty doesn't change that: a cost
3 days away is discounted to almost nothing whatever its size.

**Fix:** charge the expected death when the wound happens: the chance that it carries the infection × the
death cost. A bite then costs a whole death at the moment of the bite, a laceration a quarter of one, a scratch
7%. The same amount comes off the eventual death penalty, so a life never costs more than one death in total.
This is potential-based shaping (section 3) with potential −death × P(infected).

On a bigger death number: once death outweighs everything else, raising it further leaves its own effect the
same. What changes is that everything else (being alive, progress, the hints below) weighs relatively less, and
training gets noisier, because rare huge values dominate the error. Atari DQN went the other way and clipped
everything to ±1 for that reason; PopArt (van Hasselt 2016) and DreamerV3's symlog exist to cope with huge
values. Raising it to −10,000 is fine if the network's internal scale goes up with it (`net.SCALE`).

## 3. Rewarding good actions without points to farm

Rewarding an action directly invites loops. These are well-known cases:

* **CoastRunners** (OpenAI 2016): a boat racer was rewarded for hitting targets. It circled a lagoon collecting
  respawning targets, on fire and going the wrong way, and outscored players who finished the race.
* **A bicycle agent** (Randløv & Alstrøm 1998) was rewarded for progress towards its goal. It learned to ride
  in circles.

"+points for putting a jacket on" would be the same: put it on, take it off, put it on again.

**The standard answer is potential-based shaping** (Ng, Harada & Russell 1999). Give each *state* a value Φ
(how protected, how treated, how healthy), and reward the *change*: γΦ(after) − Φ(before).

* Putting the jacket on earns the rise in Φ, and taking it off costs the same drop.
* Any loop that returns to where it started earns nothing; with discounting, slightly less than nothing.
* Ng et al. prove this is the only form of added reward that can never change which play is best.

In practice it acts as a hint that speeds learning. It never overrides survival: if taking a coat off really
helps, for example to stop overheating, the network can still learn to.

The same tool covers healing (Φ = health: losing a point costs, regaining it pays back), wound care
(Φ = −untreated wounds: a new wound costs, bandaging pays back) and the infection charge in section 2.

## 4. Proposal: reward version 3

| What | Kind | Points |
|---|---|---|
| Being alive | per game minute | **+1** (unchanged) |
| Dying | once | **−10,000** (owner: "far worse"; or keep −1000, see decision 1) |
| Infection risk | potential: when a zombie wound appears, its infection chance × the death cost | scratch **−700**, laceration **−2,500**, bite **−10,000**; refunded from the death penalty, so a life never costs more than one death |
| Health | potential | **−20** per point lost, **+20** per point regained (full health = a fifth of a death) |
| Untreated wounds | potential | **−100** when an open wound appears, **+100** when it's bandaged (and −100 if a needed bandage comes off) |
| Protection | potential: the bite and scratch defence of worn clothing, averaged over the 17 body parts as the game's protection panel shows it | **0 to +1,000**: putting clothing on pays its share, taking it off costs the same; a leather jacket ≈ +100-200 |
| Kills, first items/buildings/containers | as now | +10, +3, +5, +0.5 |
| Moodles (hunger, pain, panic …) | – | **0** |

Every potential term earns nothing over a loop, so there is nothing to farm. The death penalty and being
alive are the only terms that decide what is truly best; the rest are hints that make it learn faster.

**Why the NN keeps taking clothes off now:** each worn item is its own `take_off` option (up to 4). On average
3 of 34 options are `take_off`, so random exploration (10% of picks, and all picks before a network exists)
chooses one about one time in eleven. Version 2 gives no reason not to. The protection term makes each removal cost straight away.

**What it needs:**

* The gym reports the per-body-part bite and scratch defence (`IsoGameCharacter:getBodyPartClothingDefense`, the
  protection panel's own numbers, listed in BACKLOG item O1). This is not run in game yet.
* The reward computes Φ for each observation. Training adds γ^minutes × Φ(after) − Φ(before), with Φ = 0 after a
  death, and re-scores older experience: the protection term is zero where the old records lack it.
* Tests, and `net.SCALE` raised for the larger values.
* The network starts over once more (reward version 3).

## 5. Decisions for the owner

1. **Death size:** −10,000 (recommended if you want it far worse; the infection charge makes it bite at the
   right moment), or keep −1,000.
2. **Protection as a hint or a lasting want:** the potential above (recommended: nothing to farm, never overrides
   survival), or a per-minute bonus for being protected. That second option can't be farmed either, but it makes
   the network want clothing for its own sake, for example a winter coat in a heatwave.
3. **Look-ahead:** 2 game hours now. OpenAI Five lengthened its horizon as training went on (60 s to 840 s).
   Starvation and infection play out over days here, so lengthening ours once the network survives a few hours
   is a later step.

## Sources

* Hafner 2021, *Benchmarking the Spectrum of Agent Capabilities* (Crafter), sections 3.1-3.3:
  <https://arxiv.org/abs/2109.06780>, <https://github.com/danijar/crafter>
* OpenAI 2019, *Dota 2 with Large Scale Deep Reinforcement Learning*, appendix G (reward weights) and horizon
  table: <https://arxiv.org/abs/1912.06680>
* *Deep Reinforcement Learning for Doom using Unsupervised Auxiliary Tasks*, shaped rewards:
  <https://arxiv.org/abs/1807.01960>
* MineRL ObtainDiamond rewards: <https://minerl.readthedocs.io/en/stable/environments/diamond.html>
* Küttler et al. 2020, *The NetHack Learning Environment*: <https://arxiv.org/abs/2006.13760>
* Ng, Harada & Russell 1999, *Policy Invariance Under Reward Transformations*:
  <https://www.cs.utexas.edu/~shivaram/readings/b2hd-NgHR1999.html>
* Randløv & Alstrøm 1998, *Learning to Drive a Bicycle Using RL and Shaping*:
  <https://www.cs.utexas.edu/~shivaram/readings/b2hd-RandlovAlstrom1998.html>. The circling behaviour is as
  reported in the survey <https://arxiv.org/abs/2002.00444>.
* OpenAI 2016, *Faulty reward functions in the wild*: <https://openai.com/index/faulty-reward-functions/>
* Russell & Norvig's 4×3 world: a step cost below −1.6284 sends the agent into the −1 exit. This is the same
  trap as version 1's discomfort. Lecture notes:
  <https://cs.uwaterloo.ca/~a23gao/cs486686_f18/slides/lec14_markov_decision_process_typednotes.pdf>
* van Hasselt et al. 2016, *Learning values across many orders of magnitude* (PopArt):
  <https://arxiv.org/abs/1602.07714>
* Project Zomboid infection odds: `projectzomboid.jar` 42.21 (`generateZombieInfection(7)` for scratches,
  `(25)` for lacerations, bites always, gated by `SandboxOptions.lore.transmission`). Player guides agree:
  <https://pzfans.com/bitten_in_pz_build_41_vs_42_survival_hacks_unveiled/>
