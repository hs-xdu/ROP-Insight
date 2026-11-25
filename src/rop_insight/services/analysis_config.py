"""Strict JSON configuration and stable dependency ordering."""

from dataclasses import dataclass, field
import json
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModuleConfig:
    module_id: str
    enabled: bool = False
    adapter_id: str | None = None
    model_version: str | None = None
    weights_path: str | None = None
    device: str | None = None
    runtime_python: str | None = None
    weights_sha256: str | None = None
    model_source: str | None = None
    source_hashes: dict = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()
    preprocessing: dict = field(default_factory=dict)
    postprocessing: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisConfig:
    modules: tuple[ModuleConfig, ...]
    schema_version: int = 1


def parse_config(data, registry, base_dir=Path.cwd()):
    try:
        json.dumps(data, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ConfigError("配置必须为有限值 JSON 数据") from exc
    if not isinstance(data, dict) or set(data) != {"schema_version", "modules"}:
        raise ConfigError("配置需要 schema_version 和 modules")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ConfigError("不支持的配置版本")
    if not isinstance(data["modules"], list):
        raise ConfigError("modules 必须是列表")
    modules = []
    fields = set(ModuleConfig.__dataclass_fields__)
    for item in data["modules"]:
        if not isinstance(item, dict) or set(item) - fields:
            raise ConfigError("模块配置含未知字段或格式错误")
        identifier = item.get("module_id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ConfigError("module_id 必须是非空字符串")
        if type(item.get("enabled", False)) is not bool:
            raise ConfigError("enabled 必须是布尔值")
        for key in ("adapter_id", "model_version", "weights_path", "device", "runtime_python", "weights_sha256", "model_source"):
            if item.get(key) is not None and (not isinstance(item[key], str) or not item[key].strip()):
                raise ConfigError(f"{key} 必须是非空字符串或 null")
        if item.get("weights_sha256") is not None:
            import re
            if not re.fullmatch(r"[0-9a-f]{64}", item["weights_sha256"]):
                raise ConfigError("weights_sha256 必须是小写 SHA-256")
        deps = item.get("dependencies", [])
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            raise ConfigError("dependencies 必须是字符串列表")
        if len(deps) != len(set(deps)):
            raise ConfigError("模块依赖重复")
        for key in ("preprocessing", "postprocessing", "source_hashes"):
            if not isinstance(item.get(key, {}), dict):
                raise ConfigError(f"{key} 必须是对象")
        adapter = item.get("adapter_id")
        if adapter is not None and adapter not in registry:
            raise ConfigError(f"未知适配器：{adapter}")
        if item.get("enabled", False) and adapter is None:
            raise ConfigError(f"{identifier} 已启用但未配置适配器")
        if adapter and item.get("enabled", False):
            if item.get("device") not in registry[adapter].supported_devices:
                raise ConfigError(f"{identifier} 的设备不受适配器支持")
        values = dict(item, dependencies=tuple(deps))
        for field_name in ("weights_path", "runtime_python", "model_source"):
            if values.get(field_name):
                path = Path(values[field_name])
                values[field_name] = str((Path(base_dir) / path).resolve())
        modules.append(ModuleConfig(**values))
    config = AnalysisConfig(tuple(modules))
    ordered_modules(config)
    return config


def ordered_modules(config):
    by_id = {module.module_id: module for module in config.modules}
    if len(by_id) != len(config.modules):
        raise ConfigError("模块标识重复")
    order, visiting, visited = [], set(), set()

    def visit(identifier):
        if identifier not in by_id:
            raise ConfigError(f"缺失依赖：{identifier}")
        if identifier in visiting:
            raise ConfigError("模块依赖存在环")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in by_id[identifier].dependencies:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)
        order.append(by_id[identifier])

    for identifier in by_id:
        visit(identifier)
    return tuple(order)


def load_config(path, registry):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"),
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        return parse_config(data, registry, Path(path).resolve().parent)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise ConfigError(f"分析配置无效：{exc}") from exc


def default_config():
    return AnalysisConfig(tuple(ModuleConfig(name) for name in ("ridge", "vessel", "staging")))
