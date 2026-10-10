# Disaster-response training framework

Research/design for a worldwide preparedness and aid-coordination training framework: wildfire first, civilian recovery, conditional Monte Carlo, required pathfinding, Google Maps 2D and elevated 3D. All code, builds, tests, inference, simulation, rendering and viewer services are intended to run on the supplied W7900 server; local Chrome is a thin client/control surface only.

**Flagship serious-game feature: route finding and vehicle tracking.** The planned exercise computes vehicle-compatible routes across observed road access, shows simulated buses/ambulances/supply trucks moving with position, progress, trail and ETA, and explains hazard- or closure-triggered reroutes with before/after paths. Trips stay committed while underway; unreachable and stranded states are explicit. Routes use only observed and currently available forecast information. This is planned behavior, not implemented functionality.

The project currently contains research and accepted design decisions, not a completed simulator or model/performance results. The replacement Radeon Cloud instance `rgapi-hackathon-22784-b3feb505` is Ready. Jupyter verification at 2026-10-10 05:49:08 UTC confirmed root access, W7900D 47.98 GiB, 1 GPU/16 CPU/55 GiB, Torch ROCm 10 and a synchronized tensor sum of 120; both backed-up files are restored in `/workspace`. `tmux 3.6` and a detached CPU runner have since been verified through Jupyter; direct SSH remains refused before authentication. Node and npm remain absent. No product workloads, model inference, physics, pathfinding, application performance or graphics are tested. See [server setup evidence](docs/SERVER_SETUP.md). No product implementation or GitHub mutations have occurred. The last recorded credit balance before relaunch was 52 of 53; verify the current balance, with the new launch charged inside the planned first-stage cap. See the [staged compute plan](docs/PARALLEL_BUILD_PLAN.md).

## Start here

- [Simple experience and conditional aid-planning loop](docs/EXPERIENCE_AND_PLANNING.md)
- [Competition feature/evidence blueprint](docs/COMPETITION_BLUEPRINT.md)
- [Pathfinding and route-tracking design](docs/PATHFINDING_AND_TRACKING.md)
- [Plain-language design and proposed build order](docs/PROJECT_PLAN.md)
- [Parallel build plan](docs/PARALLEL_BUILD_PLAN.md)
- [Source-backed scenario eligibility](docs/research/source-backed-scenarios.md)
- [Expanded local Hugging Face workflow](docs/research/hf-expanded-framework.md)
- [Server-only graphics feasibility gate](docs/research/server-only-graphics-gate.md)
- [Verified event rules and deadlines](docs/research/official-event-rules.md)
- [Interview decisions and open threads](docs/design-interview.md)
- [Domain vocabulary](GLOSSARY.md)
- [Skill source and license](THIRD_PARTY_NOTICES.md)
- [Research notes](docs/research/)

Unresolved hard gates include Google 2D/independent geographic 3D composition permission and genuine FSR4 ML execution on the supplied W7900 server. Neither Linux compatibility nor a separate-process workaround is assumed. The existing `jrile018/knight26` GitHub repository is private and Discussions are disabled; the event requires a public repository. No GitHub mutations have been made. Cloud setup changed from the backed-up/stopped first instance to the Ready replacement; Jupyter works, while direct SSH is still refused before authentication. Hugging Face's announced $20 credit per hacker is confirmed, but its product/scope/redemption path is unknown and is not assumed to fund W7900 runtime.

Devpost submission deadline: Sunday, October 11, 2026 at 10:00 a.m. America/New_York. The event code freeze and user compute/validation target are 11:00 a.m. Solo build.
