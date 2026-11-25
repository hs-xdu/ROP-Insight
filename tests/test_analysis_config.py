import json

import pytest

from rop_insight.services.analysis_config import ConfigError, load_config, ordered_modules, parse_config


class Adapter:
    supported_devices = ("cpu",)


def module(name="ridge", **changes):
    return dict(module_id=name, enabled=True, adapter_id="test", device="cpu", **changes)


def config(modules):
    return {"schema_version": 1, "modules": modules}


def test_relative_weights_and_dependency_sort(tmp_path):
    data = config([module("staging", dependencies=["ridge"]), module(weights_path="weights/ridge.pt")])
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    parsed = load_config(path, {"test": Adapter})
    order = ordered_modules(parsed)
    assert [m.module_id for m in order] == ["ridge", "staging"]
    assert order[0].weights_path == str((tmp_path / "weights/ridge.pt").resolve())


@pytest.mark.parametrize("data", [
    {}, {"schema_version": True, "modules": []}, config({}),
    config([module(), module()]), config([module(dependencies=["absent"])]),
    config([module(dependencies=["ridge"])]),
    config([module("ridge", dependencies=["vessel"]), module("vessel", dependencies=["ridge"])]),
    config([dict(module(), enabled="yes")]), config([dict(module(), device="cuda")]),
    config([dict(module(), adapter_id="unknown")]), config([dict(module(), adapter_id=None)]),
    config([module(preprocessing=[])]), config([module(postprocessing={"threshold": float("nan")})]),
    config([module(dependencies=["ridge", "ridge"])]), config([module(extra=1)]),
])
def test_invalid_config_rejected(data):
    with pytest.raises(ConfigError):
        parse_config(data, {"test": Adapter})


@pytest.mark.parametrize("contents", ["{bad json", '{"schema_version":1,"modules":NaN}'])
def test_invalid_json(tmp_path, contents):
    path = tmp_path / "bad.json"
    path.write_text(contents)
    with pytest.raises(ConfigError):
        load_config(path, {})


def test_missing_config(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.json", {})
