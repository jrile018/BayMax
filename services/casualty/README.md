# Casualty cases C1

Case/rights/face-box validation, immutable evidence proposals, terminal human review and exercise-need export are implemented. The localized face never determines injury severity or medical priority. Missed/occluded/failed detections abstain visually while human confirmation of explicit exercise facts remains available.

Run on supplied RadeonCloud:

```
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /opt/venv/bin/python -m pytest -q
/opt/venv/bin/python -m services.casualty.demo --output artifacts/casualty/c1-trace.json
```

The committed SVG/JSON is synthetic and all model observations/reviewer actions in the demo are controls/scripted calls. No actual detector, licensed real photo, clinical labels, injury classifier, GPU performance, live dispatch or measured learner benefit exists here. Follow `INTERFACE_V1.md` for the proposed root integration boundary and pending responsibilities. Approval of rights records cannot itself establish legal permission; actual item-level evidence must be verified before any real use.
