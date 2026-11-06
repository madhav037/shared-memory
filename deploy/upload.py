"""What a deploy sends the server: a `docker save` of the release, less the layers the server already has.

    python3 deploy/upload.py HELD SAVED > upload.tar

SAVED is the `docker save` tar of the release's images. HELD is what the server's `layers` action printed: one line
per image it holds, that image's layers (their diff IDs, RootFS.Layers) from the bottom up. The tar written to stdout
is SAVED without the blobs of the layers the server has, and `docker load` there takes it as the whole release.

A layer is left out only where Docker skips it on load. Docker looks a layer up by its chain, the layer together with
every layer under it, so a layer counts as held only when some image the server holds starts with the same layers in
the same order; the same layer over a different parent is sent. A blob any image in the release still needs is sent.
Manifests and configs are always sent. With HELD empty, or naming nothing in the release, the whole tar goes.

What was left out and what goes is written to stderr. Standard library only, as it runs on GitHub's runner.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO


def chains(layers: list[str]) -> list[str]:
    """The chain ID of each layer: what Docker files a layer under, the layer together with all those below it."""
    found: list[str] = []
    for layer in layers:
        found.append(layer if not found else "sha256:" + hashlib.sha256(f"{found[-1]} {layer}".encode()).hexdigest())
    return found


def held_chains(held: str) -> set[str]:
    known: set[str] = set()
    for line in held.splitlines():
        if line.strip() and not line.startswith("#"):
            known.update(chains(line.split()))
    return known


@dataclass
class Image:
    name: str
    layers: list[str]  # the paths of its layer blobs in the tar, bottom up
    held: list[bool]  # whether the server has each layer, chain and all


def images(saved: tarfile.TarFile, known: set[str]) -> list[Image]:
    def read(path: str) -> bytes:
        member = saved.extractfile(path)
        if member is None:
            raise SystemExit(f"The saved images have no {path}.")
        return member.read()

    found = []
    for entry in json.loads(read("manifest.json")):
        diff_ids = json.loads(read(entry["Config"]))["rootfs"]["diff_ids"]
        if len(diff_ids) != len(entry["Layers"]):
            raise SystemExit(f"{entry['Config']} names {len(diff_ids)} layers and the manifest {len(entry['Layers'])}.")
        name = ", ".join(entry.get("RepoTags") or [entry["Config"]])
        found.append(Image(name, entry["Layers"], [chain in known for chain in chains(diff_ids)]))
    return found


def megabytes(size: int) -> str:
    return f"{size / 1_000_000:.1f} MB"


def upload(held: str, saved_path: Path, out: IO[bytes], report: IO[str]) -> int:
    """Writes the upload to `out` and returns its size before compression."""
    with tarfile.open(saved_path) as saved:
        sizes = {member.name: member.size for member in saved.getmembers()}
        release = images(saved, held_chains(held))
        needed = {path for image in release for path, has in zip(image.layers, image.held, strict=True) if not has}
        left_out = {path for image in release for path in image.layers} - needed

        for image in release:
            sent = [path for path, has in zip(image.layers, image.held, strict=True) if not has]
            report.write(
                f"{image.name}: {len(image.layers)} layers, {len(image.layers) - len(sent)} on the server, "
                f"sending {len(sent)} ({megabytes(sum(sizes.get(path, 0) for path in sent))})\n"
            )

        written = 0
        with tarfile.open(fileobj=out, mode="w|", format=tarfile.PAX_FORMAT) as upload_tar:
            for member in saved:
                if member.name in left_out:
                    continue
                upload_tar.addfile(member, saved.extractfile(member) if member.isfile() else None)
                written += member.size
        report.write(f"Left out {megabytes(sum(sizes.get(path, 0) for path in left_out))} the server has; "
                     f"sending {megabytes(written)} before compression\n")
        return written


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("usage: upload.py HELD SAVED > upload.tar")
    held_path, saved_path = Path(argv[0]), Path(argv[1])
    held = held_path.read_text(encoding="utf-8") if held_path.exists() else ""
    upload(held, saved_path, sys.stdout.buffer, sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
