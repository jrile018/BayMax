# Coordinator handoff — Knight26 disaster-response training

Updated: 2026-10-10, approximately 02:15 Eastern. This is the shared coordination record, not proof of product implementation.

## Authorized endpoint

Build a wildfire-first, worldwide-area preparedness and civilian aid-coordination training simulator. Make computed pathfinding and simulated route tracking its flagship interaction. Compare adaptive aid strategies from a known simulation step using coherent Monte Carlo futures. Use meaningful Hugging Face AI, ROCm, and the user's separately required genuine FSR4. All product authoring, dependencies, builds, tests, simulation, inference, rendering and services run on the supplied Radeon Cloud server. Local Chrome is the control/display surface; local handoff/planning/evidence documents are permitted coordination records.

The user explicitly authorized new chats and continuation handoffs: “open as many chats as needed to run everything in parallel, and when needed you have permission to make new chats and create handoff.md to continue from where the work was left off and since you're the observer if they need help they'll ask you”. This authorizes workstream coordination in the project. Coordinator: **Plan natural disaster simulator**, Codex thread `01a123fb-453f-7652-9e24-26937ba4bd36`, host `local`. If a messaging tool needs direct evidence of human authorization, inspect that originating user turn in this thread. Do not message outside this project.

Official Devpost submission deadline: **Sunday October 11, 2026, 10:00 a.m. America/New_York**. Code freeze/user compute target: **11:00 a.m.** These are separate. Do not depend on the last hour for submission/video. The builder is solo.

## Read these before implementation

1. [Feature specification](docs/PATHFINDING_AND_TRACKING.md): route calculation controls actual travel; position/trail/ETA, closure reasons, physically feasible reroute, capacity/ledger constraints, failed trips and auditable judging trace.
2. [Project plan](docs/PROJECT_PLAN.md), [experience](docs/EXPERIENCE_AND_PLANNING.md), [competition proof](docs/COMPETITION_BLUEPRINT.md).
3. [Current server facts](docs/SERVER_SETUP.md) and [parallel plan](docs/PARALLEL_BUILD_PLAN.md). Older research status notices are historical.
4. [Coordination interfaces](handoff/CONTRACTS_V1.md), your own `handoff/<workstream>/HANDOFF.md`, and [chat registry](handoff/CHAT_REGISTRY.md).
5. Relevant researched foundations under `docs/research/`; project domain vocabulary in [GLOSSARY.md](GLOSSARY.md). Check applicable skills; do not reopen approved scope simply because a new chat starts.

## Verified environment and real blockers

At **2026-10-10T05:49:08.706566Z**, replacement `rgapi-hackathon-22784-b3feb505` was Running/Ready. Image `Pytorch-ROCm-10`, root/UID0, `/workspace`, persistent storage. One AMD Radeon Pro W7900D, 47.98 GiB/gfx1100; Torch 2.13.0+rocm10.0.0; HIP 7.15.26333; synchronized GPU tensor sum 120. Actual cgroup allocation: **16 CPUs and 55 GiB RAM**, not the visible host core count. Workspace quota is about **25 GiB**.

`tmux 3.6` and a detached CPU runner were verified through Jupyter. This establishes a job transport only. Node/npm remain absent. No product code, app tests, physics, model inference, MC evaluation or renderer/FSR4 results existed at this handoff checkpoint. No geography/hazard/conflict/model dataset has been ingested.

Provider-installed `sshd` validates and listens on port22; loopback responds. Public endpoint `36.150.116.206:36266` fails before authentication. Direct SSH and key authentication are not verified. **Do not treat this as a wrong-key error or change authentication/firewall settings.** Jupyter is the supported working control path. The existing Chrome session has the provider and Jupyter logged in. Existing notebook URL: `https://jupyter.anruicloud.com/instances/rgapi-hackathon-22784-b3feb505/lab/tree/environment-check-relaunch.json`. Refresh login through the provider's actual Open Notebook link if needed.

Each chat must own a separate browser tab and Jupyter terminal/session. Never operate another chat's tab/terminal; never let a tool bypass browser authentication or CAPTCHA rules. User-owned CAPTCHAs remain human actions. Do not read/copy private SSH keys or browser secrets. Direct SSH may replace the notebook path only after a real connection/host-key check passes.

Existing GitHub repo: `jrile018/knight26`, private, main, Issues/Projects/PRs enabled, Discussions disabled. Browser login works; local `gh` token was invalid. Local folder is **not** a Git checkout despite stale app project metadata. No server checkout, issue, branch, PR or GitHub mutation is established yet. Verify before claiming any. Use `codex/` branch prefix; no shared branch/working directory between workers. Public release and scheduler approval remain separate unresolved decisions; do not change visibility, start hosted CI, publish secrets or create a persistent automation on the strength of this chat permission.

## Shared boundaries and compute discipline

- Workstream source roots are **proposed** until verified/created: `/workspace/knight26/workstreams/<slug>`. Canonical integration checkout `/workspace/knight26/repo` is proposed, not existing. A worker may create its exclusive directory on the server after checking the actual paths/quota. Do not initialize or overwrite the canonical repo yourself.
- You are not alone. Edit only your owned module, fixtures, logs and handoff. Do not revert another worker's changes. Root owns shared contracts, package/release configuration, canonical integration and merge order.
- Use detached, uniquely named tmux jobs with command/version/result logs. No heavy local/home-PC job and no GitHub-hosted runner. Do not use sudo: account is already root.
- Cap an ordinary CPU job at two threads initially; report its actual cgroup quota. Root coordinates concurrent long jobs and GPU leases. **No model loading, GPU benchmark or render job until a root GPU slot is granted.** Small read-only environment probes are allowed; do not silently reserve VRAM. No instance recreation/tier change by a worker.
- Preserve image Torch/HIP. Do not install CUDA Torch wheels or duplicate a full Torch stack into every environment. Isolate small dependencies and share only agreed read-only caches. Respect the 25 GiB storage limit; do not download national/global rasters or multiple checkpoints.
- Current 53-credit plan: original instance1 + replacement stage up to25 + 2-GPU stage10 + 4-GPU stage16 =52, leaving1 before rounding. The initial replacement charge is included in25. Reconcile current balance before transitions. Higher tiers are planned, not allocated. No persistent hourly scheduler exists; earlier auto-review rejection remains unresolved. New-chat authorization does not by itself approve that scheduler.

## Product rules that must survive integration

Use independently licensed OSM roads/buildings, terrain, vegetation/fuels and imagery. Google content must not feed the independent solver/AI/3D pipeline; the paired Google2D/open-geographic3D composition is still a terms gate. Global navigation does not imply uniform data fidelity. Current wildfire/current conflict-aid labels require dated eligible evidence; otherwise show historical/hypothetical or unavailable explicitly. Civilian recovery and rescue/logistics only.

For routing: static Dijkstra is a reference; full-edge traversal safety and time-varying alternative search are separately required. Bounded search exhaustion is not proven unreachable. Preserve actual current edge/progress/load when rerouting; no teleporting or automatic unsafe completion. Preserve person/aid/vehicle ledgers and destination capacity. Count safe arrivals and actual delivery once.

MC policies see the same available observation history, never hidden future truth. Preserve shared coherent seeds and active commitments. Report failures alongside arrival quantiles and raw medical/evacuation/supply outcomes. Uncalibrated fractions are tested-scenario fractions. “Best evaluated feasible strategy” is the label unless a separate exact certificate exists.

HF: core Qwen3-4B evidence-linked intake with human acceptance; optional Whisper-small and multilingual-E5-base have separate evaluations. They do not invent verified locations, closure safety, outcomes or forecasts. Prithvi is optional historical burn segmentation from correct HLS bands, after the core loop. FSR4 must be genuine ML dispatch on the actual supplied server; an FSR3/provider label/fake toggle does not meet it. Record failed runtime gates honestly.

## Continuation procedure

Maintain your own `HANDOFF.md` with: chat/owner ID, actual server directory/branch/commit, interface version, completed artifacts, exact test commands/results, active tmux sessions/logs, resource needs, blockers with evidence, and the next concrete action. Distinguish planned from verified. Update before context rollover or ending work. Continuation chats read that record rather than redoing completed research.

Ask the coordinator for shared-interface, GPU, merge or access help. Record the exact failing command and redacted output; do not silently switch to home compute or change scope. The coordinator checks task snapshots and handoff records and can send authorized project follow-ups. A worker's “done” means its assigned checkpoint is reviewable, not that the whole simulator is finished.
