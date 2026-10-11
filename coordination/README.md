# Disaster-response training framework

Research/design for a worldwide preparedness and aid-coordination training framework: wildfire first, civilian recovery, conditional Monte Carlo, required pathfinding, Google Maps 2D and elevated 3D. All code, builds, tests, inference, simulation, rendering and viewer services are intended to run on the supplied W7900 server; local Chrome is a thin client/control surface only.

**Flagship serious-game feature: route finding and vehicle tracking.** The planned exercise computes vehicle-compatible routes across observed road access, shows simulated buses/ambulances/supply trucks moving with position, progress, trail and ETA, and explains hazard- or closure-triggered reroutes with before/after paths. Trips stay committed while underway; unreachable and stranded states are explicit. Routes use only observed and currently available forecast information. This is planned behavior, not implemented functionality.

This directory retains historical research and coordination guidance; it is not a current deployment status page. For the dated source-review snapshot, use [PR status](../docs/reviews/PR_STATUS_2026-10-10.md) and each PR's exact source-bound test evidence. Setup probes do not establish integrated product, model, simulation or graphics acceptance. Provider instance, access-session and billing details are maintained in private operator records.

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

Google/geographic composition permissions and genuine FSR4 ML execution retain their separately documented evidence gates. Runtime compatibility and accepted operational outcomes must be demonstrated rather than inferred. [BayMax](https://github.com/jrile018/BayMax) is public by its owner's instruction, with PRs and dedicated Discussions used for review. No account-credit or operator-access state is published here.

Devpost submission deadline: Sunday, October 11, 2026 at 10:00 a.m. America/New_York. The event code freeze and user compute/validation target are 11:00 a.m. Solo build.
