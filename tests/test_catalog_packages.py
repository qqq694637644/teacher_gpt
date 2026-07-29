import pytest

from app.core.errors import LocatorIndexLoadError
from app.repositories.locator_repository import LocatorRepository
from app.services.index_compiler import LocatorIndexCompiler
from tests.helpers import complete_manifest
from tools.build_dip4e_manifest import write_manifest_package
from tools.compile_locator_index import load_manifest, write_compiled_package


def test_manifest_package_round_trips_complete_manifest(tmp_path) -> None:
    manifest = complete_manifest()
    path = tmp_path / "manifest.yaml"

    write_manifest_package(manifest, path)
    loaded = load_manifest(path)

    assert loaded == manifest
    assert path.stat().st_size < 2 * 1024 * 1024
    shards = sorted(tmp_path.glob("manifest.sections.*.yaml"))
    assert [shard.name for shard in shards] == ["manifest.sections.02.yaml"]
    assert all(shard.stat().st_size < 2 * 1024 * 1024 for shard in shards)


def test_compiled_package_round_trips_complete_index(tmp_path) -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    path = tmp_path / "compiled_locator_index.json"

    details = write_compiled_package(compiled, path)
    repository = LocatorRepository.load(path)

    assert repository.index == compiled
    assert details["section_shard_count"] == 1
    assert path.stat().st_size < 2 * 1024 * 1024
    shards = sorted(tmp_path.glob("compiled_locator_index.sections.*.json"))
    assert [shard.name for shard in shards] == ["compiled_locator_index.sections.02.json"]
    assert all(shard.stat().st_size < 2 * 1024 * 1024 for shard in shards)


def test_compiled_package_rejects_missing_shard(tmp_path) -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())
    path = tmp_path / "compiled_locator_index.json"
    write_compiled_package(compiled, path)
    next(tmp_path.glob("compiled_locator_index.sections.*.json")).unlink()

    with pytest.raises(LocatorIndexLoadError, match="invalid"):
        LocatorRepository.load(path)


def test_manifest_package_rejects_missing_shard(tmp_path) -> None:
    manifest = complete_manifest()
    path = tmp_path / "manifest.yaml"
    write_manifest_package(manifest, path)
    next(tmp_path.glob("manifest.sections.*.yaml")).unlink()

    with pytest.raises(ValueError, match="manifest validation failed"):
        load_manifest(path)
