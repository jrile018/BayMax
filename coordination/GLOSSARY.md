# Disaster Response Training

A shared vocabulary for the proposed disaster-response exercise and its evaluation.

## Language

**Hazard model**:
A mathematical approximation of how a damaging physical process evolves under stated conditions.
_Avoid_: Exact disaster predictor

**Scenario**:
One internally consistent set of initial conditions, changing hazards, resource availability, and community needs.
_Avoid_: Forecast, guaranteed outcome

**Scenario ensemble**:
A collection of possible scenarios used to examine uncertainty under specified assumptions.
_Avoid_: Prediction of every possible future

**Aid request**:
A stated need for a particular resource or service at a location, with a quantity and urgency where known.
_Avoid_: Generic help point

**Response policy**:
A rule for choosing actions from the information available at the time of a decision.
_Avoid_: A route that knows the future

**Conditional future**:
A possible continuation consistent with observations and current commitments at the selected step, under specified uncertainty assumptions.
_Avoid_: Unconditional random disaster

**Behavior policy**:
An explicit model of how an actor responds to available information, such as departure delay or a service priority rule. Its probability assumptions require supporting data for calibration claims.
_Avoid_: Mind reading

**Nonanticipativity**:
Strategies with the same observed history make the same decision even when their hidden future differs.
_Avoid_: Perfect foresight

**Decision step**:
A timestamped known situation from which feasible next actions and adaptive continuations are compared. Ongoing trips and consumed stocks remain committed.
_Avoid_: Resetting the world to improve a live dispatch

**Preparedness training**:
A supervised exercise for practicing decisions, explaining tradeoffs and reviewing outcomes under stated assumptions.
_Avoid_: Arcade score or operational emergency forecast

**Source eligibility**:
The check that a source covers the selected region, has a usable date and license, and supports the specific current, historical or hypothetical label shown.
_Avoid_: Treating a data gap as evidence that a hazard or need exists

**Current conflict-aid scene**:
A broad-region training context whose dated conflict evidence and dated civilian-needs/response source both pass the product's proposed freshness and license checks.
_Avoid_: Tactical battle map, individual event locations or implied route-safety status

**Burnable-fuel context**:
Cited vegetation/fuel information that supports a clearly stated wildfire exercise assumption; it does not establish current fuel load, moisture, ignition or spread.
_Avoid_: Fire probability or current incident confirmation

**Evidence record**:
A source-preserving observation that stores where a claim came from, when it was received, its exact supporting text or audio segment, and whether a human accepted it.
_Avoid_: Untraceable model output

**ASR (automatic speech recognition)**:
Software that turns speech into a text hypothesis; transcription and timestamps require human review for consequential details.
_Avoid_: Verified transcript

**Cited reference retrieval**:
Ranking stored, licensed passages and returning their exact source metadata and excerpt for human inspection.
_Avoid_: A model-generated authority or calibrated confidence score

**Deterministic after-action review**:
A debrief generated from recorded decisions, source records and simulator ledger values, with each reported result linked to its computed event.
_Avoid_: LLM-invented outcome narrative

**Thin client**:
A browser UI that controls and displays an application running on the supplied server; it does not run the product's code, inference, simulation or rendering services.
_Avoid_: Local compute/display split

**Feasible plan**:
A response plan that respects the exercise's resource, access, timing, and service constraints.
_Avoid_: Shortest route

**Pathfinding**:
Computing a feasible road route for a specified aid vehicle from the access information available at a decision step.
_Avoid_: Straight-line connection, route based on hidden future information

**Route tracking**:
The simulated position, progress, traveled path, and expected arrival time of an aid vehicle during a training exercise.
_Avoid_: Live GPS tracking

**Route feasibility**:
Whether a specified vehicle can complete a route within the access, hazard, timing, and capacity constraints available at the decision step.
_Avoid_: Globally safe or guaranteed route

**Rerouting**:
Changing an aid vehicle's planned road path when new observed or currently available forecast information makes its existing route unsuitable.
_Avoid_: Teleporting, perfect-foresight routing

**Robust plan**:
A feasible response plan that performs acceptably across the examined uncertain scenarios, including adverse outcomes.
_Avoid_: Guaranteed best plan

**Unmet need**:
The quantity of a requested resource or service that has not been fulfilled by the relevant deadline.
_Avoid_: Lives lost

**After-action review**:
A debrief connecting the player's decisions, observed outcomes, and opportunities to improve.
_Avoid_: AI opinion score
