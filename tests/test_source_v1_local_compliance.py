"""Compliance tests for research-experiments-20261020-source-v1-local specifications."""
import json
import hashlib
from pathlib import Path
import pytest

from app.handlers.reproduction_handler import ReproductionHandler
from app.core.model_source import save_source, extract_source
import model_source as root_model_source


ROOT_DIR = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT_DIR / "research-experiments-20261020-source-v1-local"


def test_package_manifest_integrity():
    """Verify that all files in PACKAGE_MANIFEST.json match their recorded SHA-256 hashes."""
    assert SPEC_DIR.is_dir(), "Specification directory research-experiments-20261020-source-v1-local must exist"
    manifest_path = SPEC_DIR / "PACKAGE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["document_revision"] == "20261020-source-v1-local"
    assert manifest["protocol_identity"] == "layered-d-v3"
    assert manifest["source_provenance_version"] == "d-model-source-v1"
    assert manifest["seed"] == 42

    for rel_path, file_meta in manifest["files"].items():
        full_path = SPEC_DIR / rel_path
        assert full_path.is_file(), f"File {rel_path} declared in manifest missing on disk"
        computed_sha256 = hashlib.sha256(full_path.read_bytes()).hexdigest()
        assert computed_sha256 == file_meta["sha256"], f"SHA256 mismatch for {rel_path}"
        assert full_path.stat().st_size == file_meta["bytes"], f"Byte size mismatch for {rel_path}"


def test_reproduction_handler_material_lookup():
    """Verify that ReproductionHandler reads materials from research-experiments-20261020-source-v1-local."""
    handler = ReproductionHandler()
    for case_id in ["D-01", "D-02", "D-05"]:
        materials = handler._read_experiment_materials(case_id)
        assert "method" in materials and len(materials["method"]) > 0
        assert "protocol" in materials and len(materials["protocol"]) > 0
        assert "sample" in materials and len(materials["sample"]) > 0

        # Verify parsed protocol has layered-d-v3 semantics
        proto = json.loads(materials["protocol"])
        assert proto["case_id"] == case_id
        assert len(proto["metrics"]) == 3


def test_reproduction_handler_find_official_runner():
    """Verify ReproductionHandler finds the official runner script."""
    handler = ReproductionHandler()
    runner = handler._find_official_runner()
    assert runner is not None
    assert runner.is_file()
    assert runner.name == "run_experiment.py"


def test_root_model_source_and_core_model_source_compatibility(tmp_path):
    """Verify both root model_source and app.core.model_source adhere to d-model-source-v1 extraction rules."""
    valid_resp = {
        "id": "cmpl-valid",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Here is the code:\n```python\ndef run_experiment(request):\n    return {'status': 'completed'}\n```\nDone."
                },
                "finish_reason": "stop"
            }
        ]
    }

    # Core model_source
    out_core = tmp_path / "core_impl.py"
    sha_core = save_source(valid_resp, out_core)
    assert out_core.is_file()
    assert len(sha_core) == 64

    # Root model_source
    out_root = tmp_path / "root_impl.py"
    sha_root = root_model_source.save_source(valid_resp, out_root)
    assert out_root.is_file()
    assert len(sha_root) == 64

    assert sha_core == sha_root
    assert out_core.read_text(encoding="utf-8") == out_root.read_text(encoding="utf-8")


def test_d_model_source_rejection_rules(tmp_path):
    """Verify rejection of truncated, missing run_experiment, or multiple implementations."""
    # 1. Truncated (finish_reason != 'stop')
    resp_trunc = {
        "choices": [{
            "message": {"content": "def run_experiment(request): pass"},
            "finish_reason": "length"
        }]
    }
    with pytest.raises(ValueError, match="finish_reason=stop"):
        extract_source(resp_trunc)

    # 2. Missing run_experiment(request) (fails to extract valid candidate)
    resp_no_func = {
        "choices": [{
            "message": {"content": "def other_function(x): return x"},
            "finish_reason": "stop"
        }]
    }
    with pytest.raises(ValueError, match="Expected exactly one complete Python implementation"):
        extract_source(resp_no_func)

    # 3. Multiple conflicting implementations
    resp_multi = {
        "choices": [{
            "message": {"content": "```python\ndef run_experiment(request):\n    return 1\n```\n```python\ndef run_experiment(request):\n    return 2\n```"},
            "finish_reason": "stop"
        }]
    }
    with pytest.raises(ValueError, match="Expected exactly one complete Python implementation"):
        extract_source(resp_multi)


def test_dockerfile_and_dockerignore_compliance():
    """Verify Dockerfile and .dockerignore packaging includes research-experiments-20261020-source-v1-local."""
    dockerfile_text = (ROOT_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY research-experiments-20261020-source-v1-local /app/research-experiments-20261020-source-v1-local" in dockerfile_text
    assert 'LABEL version="1.2.6"' in dockerfile_text

    dockerignore_text = (ROOT_DIR / ".dockerignore").read_text(encoding="utf-8")
    assert "!research-experiments-20261020-source-v1-local" in dockerignore_text
