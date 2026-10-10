"""Offline lifecycle regressions for the ROCm Qwen adapter."""
import gc
import sys
import types
import weakref

import pytest

from services.intake.qwen import QwenProvider


REVISION = "a" * 40


def fake_runtime(monkeypatch, *, transfer_error=None, cleanup_error=None):
    events = []
    instances = []
    model_refs = []

    class Model:
        def to(self, device):
            events.append(("to", device))
            if transfer_error is not None:
                raise transfer_error
            return self

        def eval(self):
            events.append("eval")
            return self

    class Loader:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            if args[0] == QwenProvider.name:
                assert kwargs["trust_remote_code"] is False
                assert kwargs["local_files_only"] is True
            model = Model()
            model_refs.append(weakref.ref(model))
            return model

    class Tokenizer:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            return object()

    def cleanup(name):
        events.append(name)
        if cleanup_error is not None:
            raise cleanup_error

    cuda = types.SimpleNamespace(
        is_available=lambda: True,
        reset_peak_memory_stats=lambda: None,
        synchronize=lambda: cleanup("synchronize"),
        empty_cache=lambda: cleanup("empty_cache"),
        get_device_name=lambda index: "fake GPU",
        max_memory_allocated=lambda: 0,
    )
    torch = types.ModuleType("torch")
    torch.cuda = cuda
    torch.version = types.SimpleNamespace(hip="fake HIP")
    torch.bfloat16 = object()
    torch.__version__ = "fake"
    torch.set_num_threads = lambda count: events.append(("threads", count))
    transformers = types.ModuleType("transformers")
    transformers.AutoTokenizer = Tokenizer
    transformers.AutoModelForCausalLM = Loader
    transformers.__version__ = "fake"
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    return events, model_refs


def test_partial_load_releases_model_after_transfer_error(monkeypatch):
    transfer_error = RuntimeError("transfer failed")
    events, model_refs = fake_runtime(monkeypatch, transfer_error=transfer_error)
    provider = QwenProvider.__new__(QwenProvider)
    with pytest.raises(RuntimeError, match="transfer failed") as raised:
        provider.__init__(REVISION, "/unused")
    assert raised.value is transfer_error
    assert provider.model is None
    assert provider.tokenizer is None
    assert "empty_cache" in events and "synchronize" in events
    del raised
    transfer_error.__traceback__ = None
    gc.collect()
    assert model_refs[0]() is None


def test_partial_load_preserves_original_error_when_cleanup_fails(monkeypatch):
    transfer_error = KeyboardInterrupt("transfer interrupted")
    events, _ = fake_runtime(monkeypatch, transfer_error=transfer_error,
                             cleanup_error=RuntimeError("cleanup failed"))
    provider = QwenProvider.__new__(QwenProvider)
    with pytest.raises(KeyboardInterrupt) as raised:
        provider.__init__(REVISION, "/unused")
    assert raised.value is transfer_error
    assert provider.model is None and provider.tokenizer is None
    assert "empty_cache" in events and "synchronize" in events


def test_close_is_idempotent_even_if_cuda_cleanup_fails(monkeypatch):
    events, model_refs = fake_runtime(monkeypatch,
                                      cleanup_error=RuntimeError("cleanup failed"))
    provider = QwenProvider.__new__(QwenProvider)
    # The constructor's load-stage synchronize also fails here.
    with pytest.raises(RuntimeError, match="cleanup failed"):
        provider.__init__(REVISION, "/unused")
    provider.close()
    provider.close()
    assert provider.model is None and provider.tokenizer is None
    assert events.count("empty_cache") == 3
    assert events.count("synchronize") == 4
    gc.collect()
    assert model_refs[0]() is None


def test_close_does_not_mask_inference_error(monkeypatch):
    fake_runtime(monkeypatch)
    provider = QwenProvider(REVISION, "/unused")

    class BrokenTokenizer:
        def apply_chat_template(self, *args, **kwargs):
            raise ValueError("template failed")

    provider.tokenizer = BrokenTokenizer()
    provider.torch.cuda.empty_cache = lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed"))
    with pytest.raises(ValueError, match="template failed"):
        try:
            provider.extract(types.SimpleNamespace(text="fictional report"))
        finally:
            provider.close()
    assert provider.model is None and provider.tokenizer is None


def test_load_vram_cap_uses_resource_budget_error(monkeypatch):
    fake_runtime(monkeypatch)
    sys.modules["torch"].cuda.max_memory_allocated = lambda: 14 * 1024**3 + 1
    provider = QwenProvider.__new__(QwenProvider)
    from services.intake.qwen import ResourceBudgetError
    with pytest.raises(ResourceBudgetError, match="model load exceeded"):
        provider.__init__(REVISION, "/unused")
    assert provider.model is None and provider.tokenizer is None


def inference_provider(monkeypatch):
    fake_runtime(monkeypatch)
    provider = QwenProvider(REVISION, "/unused")

    class InputIds:
        shape = (1, 2)

    class Inputs(dict):
        def to(self, device):
            assert device == "cuda:0"
            return self

    class Tokenizer:
        eos_token_id = 0

        def apply_chat_template(self, *args, **kwargs):
            return "prompt"

        def __call__(self, *args, **kwargs):
            return Inputs(input_ids=InputIds())

        def decode(self, suffix, **kwargs):
            return '{"language":"en","flags":[],"claims":[]}'

    provider.tokenizer = Tokenizer()
    provider.torch.inference_mode = lambda: __import__("contextlib").nullcontext()
    return provider


@pytest.mark.parametrize("oom_location", ["cuda", "torch"])
def test_generation_oom_uses_resource_budget_error_with_cause(monkeypatch, oom_location):
    from services.intake.qwen import ResourceBudgetError
    provider = inference_provider(monkeypatch)
    oom_type = type("FakeOutOfMemoryError", (RuntimeError,), {})
    setattr(provider.torch.cuda if oom_location == "cuda" else provider.torch,
            "OutOfMemoryError", oom_type)
    original = oom_type("device exhausted")
    provider.model.generate = lambda **kwargs: (_ for _ in ()).throw(original)
    with pytest.raises(ResourceBudgetError, match="GPU out of memory") as raised:
        provider.extract(types.SimpleNamespace(text="fictional report"))
    assert raised.value.__cause__ is original
    provider.close()


def test_inference_vram_cap_uses_resource_budget_error(monkeypatch):
    from services.intake.qwen import ResourceBudgetError
    provider = inference_provider(monkeypatch)
    class Output:
        def __getitem__(self, key):
            return [1]
    provider.model.generate = lambda **kwargs: Output()
    provider.torch.cuda.max_memory_allocated = lambda: 14 * 1024**3 + 1
    with pytest.raises(ResourceBudgetError, match="inference exceeded"):
        provider.extract(types.SimpleNamespace(text="fictional report"))
    provider.close()


def test_input_transfer_oom_uses_resource_budget_error(monkeypatch):
    from services.intake.qwen import ResourceBudgetError
    provider = inference_provider(monkeypatch)
    oom_type = type("TransferOutOfMemoryError", (RuntimeError,), {})
    provider.torch.cuda.OutOfMemoryError = oom_type
    original = oom_type("input transfer exhausted")
    input_type = type(provider.tokenizer("prompt"))
    monkeypatch.setattr(input_type, "to", lambda self, device: (_ for _ in ()).throw(original))
    provider.model.generate = lambda **kwargs: pytest.fail("generation must not run")
    with pytest.raises(ResourceBudgetError, match="GPU out of memory") as raised:
        provider.extract(types.SimpleNamespace(text="fictional report"))
    assert raised.value.__cause__ is original
    provider.close()


def test_synchronize_oom_uses_resource_budget_error(monkeypatch):
    from services.intake.qwen import ResourceBudgetError
    provider = inference_provider(monkeypatch)
    oom_type = type("SyncOutOfMemoryError", (RuntimeError,), {})
    provider.torch.OutOfMemoryError = oom_type
    original = oom_type("synchronize exhausted")
    output_refs = []
    class Output:
        pass
    def generate(**kwargs):
        output = Output()
        output_refs.append(weakref.ref(output))
        return output
    provider.model.generate = generate
    provider.torch.cuda.synchronize = lambda: (_ for _ in ()).throw(original)
    with pytest.raises(ResourceBudgetError, match="GPU out of memory") as raised:
        provider.extract(types.SimpleNamespace(text="fictional report"))
    assert raised.value.__cause__ is original
    gc.collect()
    assert output_refs[0]() is None
    provider.close()


def test_temp_gpu_refs_released_after_success(monkeypatch):
    provider = inference_provider(monkeypatch)
    output_refs = []
    suffix_refs = []

    class Suffix:
        def __len__(self):
            return 1

    class Output:
        def __getitem__(self, key):
            suffix = Suffix()
            suffix_refs.append(weakref.ref(suffix))
            return suffix

    def generate(**kwargs):
        output = Output()
        output_refs.append(weakref.ref(output))
        return output

    provider.model.generate = generate
    from services.intake.schema import Report
    result = provider.extract(Report("mock", "fictional exercise", 10.0, "fictional report"))
    assert result == {"language": "en", "flags": [], "claims": []}
    gc.collect()
    assert output_refs[0]() is None and suffix_refs[0]() is None
    provider.close()
