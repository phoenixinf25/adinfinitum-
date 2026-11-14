# Planning chat digest (for Nimansh and anyone new) — reconstructed 2026-11-14

Source: Imok's Claude-app planning chat. This is a **partial digest** rebuilt from the app's local cache (long messages and the question-UI
choices); some assistant messages are missing. The full chat is the shared link Imok has (ask Imok); where this file and the repo docs disagree,
`docs/STATUS.md`, `docs/plan/` and `docs/FORMATS.md` win.

## What we are building, in the words the chat settled on
- Challenge: NASA Space Apps 2026, **Lunar Landing Site Navigator** (judged on Impact, Creativity, Validity, Relevance, Presentation; "advanced" is not scored).
- Topic, locked in the chat: **Adinfinitium — an AI that learns the Moon and evolves 10,000 landers to discover where and when a mission can land *and survive*.**
- Framing: a **crash-test lab for Moon landings**. The main question is *where and when to land*; **survival is the score, not the goal.**
- The AI does not claim to know the real Moon: ~90% of the 5 m LOLA pixels are interpolated. Models express **uncertainty** (diffusion imagines many possible terrains;
  results are probabilities), and anything generated is shown as "GENERATED — NOT OBSERVED".

## Decisions made in the question UI (and why they matter to you)
- **Every AI model has a plain-physics backup**, built first, so the demo always works and we can show AI vs physics. Cut rule: anything not working by Sun 12:00 ships as its backup.
- **Sun/Earth planning must work first**; the chat noted judges score it most for this challenge. (Your Navigator + the light model sit on this.)
- **We design and train our own models** (no pretrained models). The hazard model learns from real LOLA + synthetic craters; trust is proven by **calibration**
  (when the AI says 80%, does it succeed ~80% of the time in simulation?).
- Simulation split: a fast **JAX GPU sim** runs the 10,000-lander swarm (TensorNEAT is JAX-based); **Basilisk** re-flies the best missions to check them.
- Scope: one high-detail south-pole region for the swarm, plus a whole-Moon site library (Apollo, CLPS, Chandrayaan-3, Chang'e, ...) for comparison.
- Evolution: the brain plus mission genes evolve; a **Dream-RSI-inspired meta layer** (no LLM) tunes the evolution strategy. Say "inspired by", not "is".
- Team of four, ~48 h, two people who can train models (Imok + Nimansh). You own the world-model side (hazard, light model) and the Navigator.
- Lander numbers (5 engines ~800 N, touchdown <= 2 m/s down, <= 0.5 m/s sideways, <= 12 deg slope) are Chandrayaan-3-style design assumptions in `config/mission.yaml`.

## Honesty rules the chat insisted on
Label everything observed / modelled / generated / unknown; no invented numbers; report AI vs the **fair** physics baseline (we found default classic guidance is a weak
opponent on `tight_fuel`: see `swarm/README.md`); the evolved pilot is "evolved residual on classic guidance"; AI-made media needs an "AI-generated" watermark, no NASA logos.

## Where things stand (see `docs/STATUS.md` for the live version)
Judging deadline plan (IST): Sat 21:00 checkpoint 1 · Sun 12:00 cut rule · Sun 17:00 code freeze · Sun 22:00 submit.
