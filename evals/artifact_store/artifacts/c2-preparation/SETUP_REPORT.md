# Isolated Bucket SDK setup evidence

- Cloud interpreter: `/opt/venv/bin/python`, CPython 3.14.4.
- Isolated target: `/workspace/knight26/deps/hf-buckets`.
- Install command used `pip install --no-index --no-deps --target` with only six locally verified wheel paths. No source tree, model dependency target, base site-packages, or model files were intentionally changed.
- `/workspace/knight26/artifacts/hf/buckets/resolution-plan.json` records supported wheel tags, Python-version compatibility, all wheel declarations, and 15 active `Requires-Dist` checks. All were satisfied by the six selected wheels or existing `/opt/venv` packages before installation.
- `/workspace/knight26/artifacts/hf/buckets/official-digest-check.json` records exact SHA256 hashes. The five fresh wheels match official PyPI metadata; the hf-xet wheel is byte-identical to the pre-existing model wheelhouse artifact.
- Selected versions: huggingface-hub 2.2.0; click 8.5.0; httpx2 2.13.1; httpcore2 2.13.1; truststore 0.10.4; hf-xet 1.7.0.
- `/workspace/knight26/artifacts/hf/buckets/install.log` records successful offline install. `/workspace/knight26/artifacts/hf/buckets/api-capabilities.json` records import paths, versions, symbols, and signatures from the isolated target. All six modules import from the target; Torch was not imported during the capability check.
- `bucket_info`, `list_bucket_tree`, `batch_bucket_files`, `download_bucket_files`, and `get_token` are available. `upload_bucket_files` is absent; `batch_bucket_files(..., add=[(local, remote)])` is the supported upload path. Bucket tree items expose `path` and `type`; files use `type='file'`, folders `type='directory'`.
- The model dependency target's path/size/mtime inventory hash in `model-target-before.sha256` exactly matches `model-target-after.sha256` and `model-target-after-api.sha256`. Base Torch remains 2.13.0+rocm10.0.0 at `/opt/venv/lib/python3.14/site-packages/torch/__init__.py` per `resolution-plan.json` and `base-after.json`.

This is an offline import and API shape check. It does not verify private bucket access, authentication, authorization, quota, bucket writes, network egress, or live service behavior. No credentials were inspected or created, and no network/auth/GPU/model API call was made.
- `/workspace/knight26/artifacts/hf/buckets/backend-call-bindings.json` confirms the backend's exact `bucket_info`, `list_bucket_tree`, `batch_bucket_files`, and `download_bucket_files` call shapes bind to installed signatures without invoking them. It also confirms a locally constructed `BucketInfo` exposes `private: bool` with `private=True`. The `get_token` signature was bound, but the function was not called.
- The model target inventory remains unchanged after these checks as recorded in `model-target-after-bind.sha256`.
