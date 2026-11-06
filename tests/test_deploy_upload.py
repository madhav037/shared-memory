"""What a deploy sends the server (deploy/upload.py) and what the server image's base is named by (deploy/server_base.py).

The upload is a real `docker save` layout, written here, run through the real script: it leaves out exactly the layer
blobs Docker would skip on the server, and nothing else. Whether real Docker takes the result is proved in CI against
real daemons (the transfer job in .github/workflows/checks.yml).
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from types import ModuleType

from shared_memory.embeddings import MODEL
from tests.support import REPO_ROOT

UPLOAD = REPO_ROOT / "deploy" / "upload.py"


def layer(text: str) -> tuple[str, bytes]:
    """An uncompressed layer holding one file, and its diff ID."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        body = text.encode()
        info = tarfile.TarInfo(text)
        info.size = len(body)
        archive.addfile(info, io.BytesIO(body))
    data = buffer.getvalue()
    return "sha256:" + hashlib.sha256(data).hexdigest(), data


def blob_path(digest: str) -> str:
    return "blobs/sha256/" + digest.removeprefix("sha256:")


def diff_ids(*texts: str) -> list[str]:
    return [layer(text)[0] for text in texts]


def save(path: Path, images: dict[str, list[str]]) -> Path:
    """A `docker save` of `images`, each named and made of layers holding the given texts, bottom up."""
    blobs: dict[str, bytes] = {}
    manifest = []
    for name, texts in images.items():
        layers = [layer(text) for text in texts]
        for digest, data in layers:
            blobs[blob_path(digest)] = data
        config = json.dumps({"rootfs": {"type": "layers", "diff_ids": [digest for digest, _ in layers]}}).encode()
        config_path = blob_path("sha256:" + hashlib.sha256(config).hexdigest())
        blobs[config_path] = config
        manifest.append({"Config": config_path, "RepoTags": [name], "Layers": [blob_path(d) for d, _ in layers]})
    files = {
        "oci-layout": b'{"imageLayoutVersion": "1.0.0"}',
        "index.json": b'{"schemaVersion": 2, "manifests": []}',
        **blobs,
        "manifest.json": json.dumps(manifest).encode(),
    }
    with tarfile.open(path, "w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def upload(tmp_path: Path, held: list[list[str]], images: dict[str, list[str]]) -> tuple[dict[str, bytes], str]:
    """Runs the script as a deploy does; returns what the upload holds and what it said."""
    (tmp_path / "held").write_text(
        "# Docker 29.9.1, storage overlayfs\n" + "".join(" ".join(line) + "\n" for line in held), encoding="utf-8"
    )
    saved = save(tmp_path / "saved.tar", images)
    done = subprocess.run(
        [sys.executable, str(UPLOAD), str(tmp_path / "held"), str(saved)], capture_output=True, check=True
    )
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as archive:
        held_files = {}
        for member in archive.getmembers():
            extracted = archive.extractfile(member)
            assert extracted is not None
            held_files[member.name] = extracted.read()
    return held_files, done.stderr.decode()


def test_with_nothing_on_the_server_everything_is_sent(tmp_path: Path) -> None:
    sent, said = upload(tmp_path, [], {"shared-memory-server:new": ["os", "deps", "app"]})

    with tarfile.open(tmp_path / "saved.tar") as saved:
        assert set(sent) == set(saved.getnames())
    assert "3 layers, 0 on the server, sending 3" in said


def test_only_the_layers_the_server_lacks_are_sent(tmp_path: Path) -> None:
    sent, said = upload(
        tmp_path, [diff_ids("os", "deps", "old app")], {"shared-memory-server:new": ["os", "deps", "new app"]}
    )

    os_layer, deps_layer, app_layer = diff_ids("os", "deps", "new app")
    assert blob_path(os_layer) not in sent and blob_path(deps_layer) not in sent
    assert sent[blob_path(app_layer)] == layer("new app")[1], "a layer that goes, goes unchanged"
    assert {"manifest.json", "index.json", "oci-layout"} <= set(sent)
    assert len([name for name in sent if name.startswith("blobs/")]) == 2, "the new layer and the config"
    assert "shared-memory-server:new: 3 layers, 2 on the server, sending 1" in said


def test_a_layer_the_server_has_over_a_different_layer_is_sent(tmp_path: Path) -> None:
    # Docker files a layer under its chain, so the same layer over another parent is a layer the server lacks.
    sent, said = upload(tmp_path, [diff_ids("older os", "deps")], {"shared-memory-server:new": ["os", "deps", "app"]})

    assert all(blob_path(digest) in sent for digest in diff_ids("os", "deps", "app"))
    assert "0 on the server, sending 3" in said


def test_a_layer_another_image_in_the_release_still_needs_is_sent(tmp_path: Path) -> None:
    sent, said = upload(
        tmp_path,
        [diff_ids("os", "shared")],
        {"shared-memory-server:new": ["os", "shared", "app"], "shared-memory-caddy:new": ["alpine", "shared"]},
    )

    os_layer, shared_layer = diff_ids("os", "shared")
    assert blob_path(os_layer) not in sent
    assert blob_path(shared_layer) in sent, "the Caddy image's chain to it is new"
    assert "shared-memory-server:new: 3 layers, 2 on the server, sending 1" in said
    assert "shared-memory-caddy:new: 2 layers, 0 on the server, sending 2" in said


def server_base() -> ModuleType:
    spec = importlib.util.spec_from_file_location("server_base", REPO_ROOT / "deploy" / "server_base.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_of_the_base_inputs(tmp_path: Path) -> Path:
    for name in ("Dockerfile", "uv.lock", "pyproject.toml"):
        shutil.copy(REPO_ROOT / name, tmp_path / name)
    return tmp_path


def test_the_base_is_renamed_when_its_dependencies_change_and_only_then(tmp_path: Path) -> None:
    base = server_base()
    root = copy_of_the_base_inputs(tmp_path)
    named = base.tag(root)

    pyproject = root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text(encoding="utf-8") + '\n[tool.example]\nsetting = "x"\n', "utf-8")
    dockerfile = root / "Dockerfile"
    dockerfile.write_text(dockerfile.read_text(encoding="utf-8") + "LABEL example=1\n", encoding="utf-8")
    assert base.tag(root) == named, "the linters' settings and the release stage aren't in the base"

    (root / "uv.lock").write_text((root / "uv.lock").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert base.tag(root) != named
    copy_of_the_base_inputs(tmp_path)
    pyproject.write_text(pyproject.read_text(encoding="utf-8").replace('"pyyaml>=6.0.3",', ""), encoding="utf-8")
    assert base.tag(root) != named
    copy_of_the_base_inputs(tmp_path)
    dockerfile.write_text(dockerfile.read_text(encoding="utf-8").replace("--no-install-recommends git", "--no-install-recommends git curl"), encoding="utf-8")
    assert base.tag(root) != named


def test_the_base_installs_exactly_the_projects_dependencies() -> None:
    base = server_base()
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    reduced = tomllib.loads(base.dependencies(pyproject))

    project = tomllib.loads(pyproject)["project"]
    assert reduced["project"]["dependencies"] == project["dependencies"]
    assert reduced["project"]["name"] == project["name"]
    assert "tool" not in reduced


def test_the_base_carries_the_search_model_the_server_uses() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    found = re.search(r"^ARG SEARCH_MODEL=(\S+)$", dockerfile, re.MULTILINE)

    assert found is not None and found.group(1) == MODEL
    assert dockerfile.index("ARG SEARCH_MODEL") < dockerfile.index(server_base().RELEASE_STAGE)
