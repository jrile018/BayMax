# Casualty cases C1

Case/rights/face-box validation, immutable evidence proposals, terminal human review and exercise-need export are implemented. The localized face never determines injury severity or medical priority. Missed/occluded/failed detections abstain visually while human confirmation of explicit exercise facts remains available.

Run on supplied RadeonCloud:

```
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /opt/venv/bin/python -m pytest -q
/opt/venv/bin/python -m services.casualty.demo --output artifacts/casualty/c1-trace.json
```

The committed SVG/JSON is synthetic and all model observations/reviewer actions in the demo are controls/scripted calls. The lazy CPU YuNet adapter is implemented; its tests mock OpenCV and do not prove model execution. The separate CPU blank-input diagnostic completed two actual model calls with zero boxes each; `artifacts/casualty/RUNTIME_MANIFEST.json` and `runtime-smoke-source.json` bind this narrow result to its source and runtime. See `RUNTIME_PROBE.md` for its scope and commands. This does not establish face recall, localization accuracy or case-pipeline execution. Permitted real photos, clinical labels, an injury classifier, GPU performance, live dispatch and measured learner benefit remain unverified. See `DETECTOR_V1.md` for its exact inputs, failure handling and pending ingress proof. Follow `INTERFACE_V1.md` for the proposed root integration boundary and pending responsibilities. Approval of rights records cannot itself establish legal permission; actual item-level evidence must be verified before any real use.

The synthetic demo trace now includes a typed incident_gate block. It is
always pending and training-only, even when the scripted trainee accepts a
fictional exercise need. See INTERFACE_V1.md for its provenance and root
review requirements.
