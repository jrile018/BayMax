# CPU runtime smoke diagnostic

`runtime_probe.py` runs the pinned YuNet network twice on a generated 128 by 128 zero BGR raster. It checks that the isolated OpenCV runtime can create the CPU detector and return output the adapter accepts. It emits a diagnostic JSON record and no casualty case, evidence proposal, review receipt or request. This is one blank-input compatibility check; it does not establish face recall, useful localization, real-photo permission or case-pipeline behavior.

The model is `opencv/face_detection_yunet` revision `3cc26e7f1014a5ee5d74a42acee58bafc9d0a310`, file `face_detection_yunet_2023mar.onnx`, SHA256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`. `artifacts/casualty/INGRESS_MANIFEST.json` records the public artifact sources, license and runtime wheel checksum. Public model permission does not supply permission to process a photograph. The model, wheel and isolated dependency directory stay in the ignored owned artifact tree; wheel license and third-party notices are retained with the installed package.

Run only on the supplied RadeonCloud, from `/workspace/knight26/worktrees/faces`, with the verified public assets staged. Install the exact recorded wheel offline into the owned directory:

```sh
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  /opt/venv/bin/python -m pip install --no-index --no-deps --no-cache-dir \
  --target artifacts/casualty/runtime-deps \
  artifacts/casualty/assets/opencv_python_headless-4.14.0.94-cp37-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
```

The isolated package uses the existing NumPy. This command does not install dependencies into the shared environment. Declared Python/NumPy compatibility in package metadata still needs actual import and model-call evidence.

Choose a new output path for each run:

```sh
PYTHONPATH="$PWD/artifacts/casualty/runtime-deps:$PWD" \
  OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  /opt/venv/bin/python -m services.casualty.runtime_probe \
  --model artifacts/casualty/assets/face_detection_yunet_2023mar.onnx \
  --ingress-reference artifacts/casualty/INGRESS_MANIFEST.json \
  --output artifacts/casualty/runtime-smoke-source.json
```

Before forwarding, the CLI resolves its own module repository and verifies that `runtime_probe.py`, `detector.py` and `contracts.py` match that repository's HEAD. Evidence binds to that source commit and each file hash. Unrelated caller directories cannot change the recorded repository, and dirty relevant sources are rejected. An existing output is rejected before a forward or overwrite.

The detector loads a private read-only copy of the checksum-verified model, with explicit OpenCV CPU backend/target, two threads, score threshold 0.9, NMS threshold 0.3 and top-k 50. Both returned observations are validated. The report retains normalized boxes if any are returned; the blank negative passes only when both successful calls contain zero faces. Failure evidence retains completed observations, call counters, timing and bounded output diagnostics, marks the negative result unknown, and exits nonzero.

Cold timing includes detector creation, input-size configuration, the first forward and output validation. Warm timing includes the second forward and output validation. Neither is a representative workload benchmark; import, asset hashing and copying are outside those intervals. No GPU lease or GPU measurement is part of this diagnostic.

The 109 source-head controls at `d62445fb4bf57d68d3443d0264d3eae9fc498bed` use fake OpenCV and generated data. Actual import/forward status must be read from the runtime evidence, rather than inferred from these tests. Permitted real-photo bytes and item-level rights/consent evidence, actual case localization, shared C2/C3 application and learner checks remain separate gates. Request-level cross-case deduplication and shared application remain coordinator responsibilities.
