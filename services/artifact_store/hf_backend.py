"""Optional Bucket transport. Import only in a separate artifact-only Python environment."""
from __future__ import annotations

import importlib.metadata
import re
import threading
from pathlib import Path

from . import ArtifactError


class SetupNeeded(ArtifactError):
    """Remote transfer is unavailable until the separate client is ready."""


class HfBucketBackend:
    """Existing private Bucket adapter; never creates/deletes buckets or edits auth.

    Must run in a separately provisioned artifact client environment. The model
    environment's huggingface_hub 0.36.2 is intentionally untouched.
    """

    def __init__(self, bucket_id: str, *, remaining_free_bytes: int,
                 caller_confirmed_free_quota: bool = False,
                 isolated_client_environment: bool = False):
        if not isolated_client_environment:
            raise SetupNeeded("run a separate artifact-only client environment")
        if not caller_confirmed_free_quota or type(remaining_free_bytes) is not int or remaining_free_bytes < 0:
            raise SetupNeeded("caller-confirmed remaining FREE private storage quota required")
        if not isinstance(bucket_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", bucket_id):
            raise SetupNeeded("existing namespace/bucket ID required")
        try:
            version = importlib.metadata.version("huggingface_hub")
            parts = tuple(int(x) for x in version.split(".")[:2])
            if parts < (1, 5):
                raise SetupNeeded(f"huggingface_hub {version} lacks Bucket API; separate >=1.5 client needed")
            from huggingface_hub import bucket_info, list_bucket_tree, batch_bucket_files, download_bucket_files, get_token
        except (importlib.metadata.PackageNotFoundError, ImportError, ValueError) as exc:
            raise SetupNeeded("compatible Bucket client unavailable") from exc
        if not get_token():
            raise SetupNeeded("existing Hub authentication unavailable")
        info = bucket_info(bucket_id)
        if info.private is not True:
            raise SetupNeeded("existing Bucket must be private")
        self.bucket_id = bucket_id
        self._budget_lock = threading.Lock()
        self._remaining_free_bytes = remaining_free_bytes
        self._reserved_unspent_bytes = 0
        self._list = list_bucket_tree
        self._upload = batch_bucket_files
        self._download = download_bucket_files

    @property
    def remaining_free_bytes(self) -> int:
        """Unreserved portion of this process's caller-confirmed budget."""
        with self._budget_lock:
            return self._remaining_free_bytes

    def preflight_upload(self, byte_count: int):
        """Atomically reserve bytes. Ambiguous transfer failures never refund them."""
        if type(byte_count) is not int or byte_count < 0:
            raise SetupNeeded("upload byte count must be an exact nonnegative integer")
        with self._budget_lock:
            if byte_count > self._remaining_free_bytes:
                raise SetupNeeded("artifact exceeds caller-confirmed remaining FREE quota")
            self._remaining_free_bytes -= byte_count
            self._reserved_unspent_bytes += byte_count

    def list_files(self, prefix):
        return [item.path for item in self._list(self.bucket_id, prefix=prefix, recursive=True)
                if item.type == "file"]

    def upload_files(self, pairs):
        """Consume a prior reservation before issuing a nontransactional SDK batch."""
        additions = [(str(local), remote) for local, remote in pairs]
        byte_count = sum(Path(local).stat().st_size for local, _ in additions)
        with self._budget_lock:
            if byte_count > self._reserved_unspent_bytes:
                raise SetupNeeded("upload bytes require an unused preflight reservation")
            self._reserved_unspent_bytes -= byte_count
        self._upload(self.bucket_id, add=additions)

    def download_files(self, pairs):
        self._download(self.bucket_id, files=[(remote, str(local)) for remote, local in pairs])
