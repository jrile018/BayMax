# Synthetic first-responder training prototype

Generate reproducible exercises in the cloud worktree:

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  /opt/venv/bin/python -m evals.planner.run_training \
  --seed 17 --severity 7 --episodes 4 --output /tmp/training-17
```

For a portable same-machine setup, run the server on the machine that has the exercise files and a browser, then open `http://127.0.0.1:8766/` in that browser:

```bash
/opt/venv/bin/python -m evals.planner.training_server --pack /tmp/training-17/practice.json --host 127.0.0.1 --port 8766
```

In the supplied cloud environment, the server responds correctly on cloud localhost, but interactive browser access from this workspace is currently blocked: SSH port forwarding is prohibited, Jupyter's `/proxy/8766` returns 404, and `jupyter_server_proxy` is unavailable. The generated files and HTTP tests can be reviewed there, but the cloud practice page cannot presently be opened in the local browser through that route. Use an approved same-machine deployment with instructor-only files kept outside any static web directory for an interactive exercise.

When `situations.json` and `instructor_futures.json` are adjacent to the pack, the server defaults to a live, full-mission world. Each session gets a fresh world, and a choice advances 15 simulated seconds. Later received incidents, road closures, and facility failures can change subsequent choices. The browser initially receives only episode names and the descriptive 1–10 severity scale. A session receives its current known facts and available actions; debrief appears only at the mission horizon. Random session and decision tokens prevent arbitrary node access and replayed steps. The HTML client contains no hidden future dataset. Pass `--finite` to demonstrate the bounded precomputed tree instead. `practice.html` is the same client template served at `/`; opening it as a local file will not start an exercise.

| File | Audience | Contents |
|---|---|---|
| `situations.json` | Instructor | Initial networks, resources, known needs, goals, severity assumptions, situation seeds |
| `instructor_futures.json` | Instructor only | Sampled physical events, observation delivery, future seeds |
| `evaluations.json` | Instructor | Full-mission and finite-practice planner/greedy traces and outcomes on the same futures |
| `summary.json` | Instructor | Separate paired service and cost gains for full-mission and finite-practice comparisons |
| `practice.json` | Instructor/server only | Full precomputed practice tree, including later nodes and debriefs |
| `practice.html` | Trainee client template | Same-origin server UI without embedded scenario or future data |

Keep `practice.json` and `instructor_futures.json` on the cloud host and outside any static file server. The practice server serves neither file through HTTP.

The severity number is an **instructor-defined ordinal setting from 1 through 10**. Level 5 is the generator default. The practice UI shows all ten level descriptions; each episode shows its current assumptions: road-failure chance, travel multiplier range, additional-incident count range, and facility-failure chance. These are editable synthetic defaults, not empirically estimated probabilities or a physical hazard-intensity scale. Use `--profile overrides.json` to set any of `road_failure_probability`, `travel_multiplier_range`, `additional_incident_count_range`, and `facility_failure_probability`. The CLI validates the bounds and records the resulting profile. Use `--coverage-threshold 120` to change the instructor response-time coverage goal in seconds. New incidents, closures of primary or detour roads, and facility failures are possible under the published assumptions.

The live exercise offers up to three supported choices every 15 simulated seconds through the 600-second generated mission, allowing up to 40 decisions. The finite demonstration ends after three decisions. Restarting creates a fresh session at the initial known state. The browser shows per-choice and total thinking time locally; it transmits no timer data and timing does not change simulated outcomes.

The generated goal order favors urgent service, then supplies, coverage, protection, and travel time. In this training objective, urgent service includes expected safe evacuation arrivals and completed medical service, even when care is late. The separate on-time medical counter still records deadline performance; late care does not disappear from the completed-service count. The situational planner recomputes from received facts and the currently supported action menu. Priority greedy is a **comparison baseline only**, never a trainee strategy. Each policy gets a fresh world with the same initial situation and sampled future. The live debrief comparators receive the exact trainee action menu and full 15-second mission decision budget. The finite demonstration comparators use the same three-choice menu and three-decision budget before their worlds drain to the horizon. `summary.json` reports that finite comparison separately from unrestricted full-mission runs; the live debrief's menu-constrained comparison is computed by the server on the same future.

For any counter, a positive paired gain favors the situational planner in this synthetic sample: more arrivals, timely/completed medical service or supplies; less unmet need, travel, stranding, route failure or constraint violation. Each raw counter retains its own units. Sample standard deviation uses `n-1`; standardized gain is undefined with one episode or zero variance, and the summary names that reason. The debrief shows the trainee's raw outcomes beside the finite-practice comparators and offers critique prompts. No real-world performance improvement is established by these synthetic results.

This is a generic first-responder coordination exercise, not medical-treatment or operational dispatch guidance. Its communications and exercise-evaluation emphasis is informed by the [CISA National Emergency Communications Plan](https://www.cisa.gov/national-emergency-communications-plan) and [FEMA Homeland Security Exercise and Evaluation Program resources](https://preptoolkit.fema.gov/web/hseep-resources/policy-and-guidance). Those sources do not calibrate simulator rates or validate outcomes.
