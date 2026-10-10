"""Catch loss of partial diagnostic evidence when remote tools time out."""
import runpy
import subprocess
from pathlib import Path
import pytest

probe_api = runpy.run_path(str(Path(__file__).parents[1] / 'graphics_probe.py'))

@pytest.mark.parametrize('stdout,stderr', [(b'partial device report\n', b'partial warning\n'), ('partial device report\n', 'partial warning\n')])
def test_timeout_retains_partial_diagnostic_evidence(monkeypatch, stdout, stderr):
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 15, output=stdout, stderr=stderr)
    monkeypatch.setattr(subprocess, 'run', timed_out)
    result = probe_api['command'](['diagnostic-tool'])
    assert result.get('stdout') == 'partial device report\n'
    assert result.get('stderr') == 'partial warning\n'
    assert result.get('timed_out') is True
    assert result['exit_code'] is None
