"""Deploying from GitHub (deploy/deploy.sh), run as GitHub's SSH key runs it.

The script runs on a host shared with someone else's sites, so what is checked here is what keeps them and the running
release safe: a release that isn't healthy is replaced by the one it replaced, nothing switches when the backup fails
or the host's web server is in trouble, a release sent without the layers the host has still deploys, `layers` only
reads, and the key can ask for nothing but a check, its layers, a deploy of a commit on main or a drill.
Docker, nginx and the network are stand-ins that write down what they were asked; git is real.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import REPO_ROOT

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="deploy.sh runs on the Linux host")

SCRIPT = REPO_ROOT / "deploy" / "deploy.sh"
IMAGES = ("shared-memory-server", "shared-memory-caddy", "shared-memory-backup")

# Images are files named for their tag, holding the release they were built from; `docker tag` copies one. An image's
# layers, bottom up, are in .layers/ under the same name. An upload is a line per image, its name and its layers, and a
# `blob` line for each layer it carries. As Docker does, loading skips a layer whose chain (it and every layer beneath
# it) an image here already starts with, and fails on any other layer the upload doesn't carry.
DOCKER = r"""#!/usr/bin/env bash
echo "docker $*" >> "$STUB_LOG"
images="$STUB_IMAGES"
held() {
    local image
    for image in "$images"/.layers/*; do
        [ -e "$image" ] || continue
        case "$(cat "$image") " in "$1 "*) return 0 ;; esac
    done
    return 1
}
case "$1" in
    version) echo "29.9.1" ;;
    info) case "$3" in *Driver*) echo overlayfs ;; *) echo "[name=seccomp,profile=builtin name=rootless name=cgroupns]" ;; esac ;;
    load)
        blobs=" "; uploaded=()
        while read -r name layers; do
            if [ "$name" = blob ]; then blobs+="$layers "; else uploaded+=("$name $layers"); fi
        done
        for line in "${uploaded[@]}"; do
            read -r name layers <<< "$line"; chain=""
            for layer in $layers; do
                chain="${chain:+$chain }$layer"
                held "$chain" || case "$blobs" in *" $layer "*) ;; *) echo "no layer $layer for $name" >&2; exit 1 ;; esac
            done
        done
        for line in "${uploaded[@]}"; do
            read -r name layers <<< "$line"
            echo "$name" > "$images/$name"
            [ -z "$layers" ] || echo "$layers" > "$images/.layers/$name"
        done ;;
    image)
        case "$2" in
            ls) for f in "$images/$5":*; do [ -e "$f" ] && echo "${f##*/}"; done; true ;;
            inspect)
                case "$3 $4" in
                    *RootFS.Layers*) cat "$images/.layers/$5" ;;
                    -f*) cat "$images/$5" ;;
                    *) [ -e "$images/$3" ] ;;
                esac ;;
            rm) rm -f "$images/$4" "$images/.layers/$4" ;;
            prune) ;;
        esac ;;
    tag) cp "$images/$2" "$images/$3"; [ ! -e "$images/.layers/$2" ] || cp "$images/.layers/$2" "$images/.layers/$3" ;;
    images) for f in "$images/$2":*; do [ -e "$f" ] && echo "${f##*:}"; done; true ;;
    compose)
        shift
        case "$1 $2 $3 $4" in
            "exec -T backup backup") exit "${STUB_BACKUP_EXIT:-0}" ;;
        esac
        case "$1" in
            ps) [ "$2" = "--services" ] && printf 'server\ndb\ncaddy\nbackup\n' || echo "server Up" ;;
            up) serving=$(cat "$images/shared-memory-server:latest")
                echo "up $serving" >> "$STUB_LOG"
                if [ -n "${STUB_OWNER_BREAKS:-}" ]; then echo 502 > "$STUB_OWNER"; fi
                if [ "$serving" = "${STUB_FAILS_TO_START:-none}" ]; then exit 1; fi ;;
        esac ;;
esac
"""

CURL = r"""#!/usr/bin/env bash
url="${@: -1}"
for arg in "$@"; do case "$arg" in http*) url="$arg" ;; esac; done
case "$url" in
    https://127.0.0.1/|http://127.0.0.1/) cat "$STUB_OWNER" ;;
    */hooks/session-start)
        [ "$(cat "$STUB_IMAGES/shared-memory-server:latest")" = "${STUB_UNHEALTHY:-none}" ] && echo 502 || echo 200 ;;
    *) echo 200 ;;
esac
"""

STANDINS = {
    "docker": DOCKER,
    "curl": CURL,
    "systemctl": '#!/usr/bin/env bash\nexit "${STUB_NGINX_EXIT:-0}"\n',
    "ss": "#!/usr/bin/env bash\necho 'LISTEN 0 511 0.0.0.0:80'\n",
}


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Host:
    """A host running release `running`, with `newer` on main and `stray` on a branch that never reached it."""

    def __init__(self, root: Path) -> None:
        self.home = root / "home"
        self.log = root / "log"
        self.images = root / "images"
        self.owner = root / "owner"
        bin_dir = root / "bin"
        for directory in (self.home, self.images, bin_dir):
            directory.mkdir()
        for name, body in STANDINS.items():
            (bin_dir / name).write_text(body, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        if shutil.which("flock") is None:
            (bin_dir / "flock").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (bin_dir / "flock").chmod(0o755)
        self.log.write_text("", encoding="utf-8")
        self.owner.write_text("200", encoding="utf-8")

        origin = root / "origin"
        work = root / "work"
        git("init", "-q", "-b", "main", str(work), cwd=root)
        git("config", "user.email", "test@example.com", cwd=work)
        git("config", "user.name", "Test", cwd=work)
        (work / "deploy").mkdir()
        (work / "deploy" / "compose.yaml").write_text("name: shared-memory\n", encoding="utf-8")
        git("add", ".", cwd=work)
        git("commit", "-q", "-m", "running", cwd=work)
        self.running = git("rev-parse", "HEAD", cwd=work)
        git("commit", "-q", "--allow-empty", "-m", "newer", cwd=work)
        self.newer = git("rev-parse", "HEAD", cwd=work)
        git("checkout", "-q", "-b", "stray", cwd=work)
        git("commit", "-q", "--allow-empty", "-m", "stray", cwd=work)
        self.stray = git("rev-parse", "HEAD", cwd=work)
        git("clone", "-q", "--bare", str(work), str(origin), cwd=root)

        self.repo = self.home / "shared-memory"
        git("clone", "-q", str(origin), str(self.repo), cwd=root)
        git("checkout", "-q", "--detach", self.running, cwd=self.repo)
        (self.repo / "deploy" / ".env").write_text("SHARED_MEMORY_DOMAIN=memory.test\n", encoding="utf-8")
        (self.images / ".layers").mkdir()
        for image in IMAGES:
            (self.images / f"{image}:latest").write_text(f"{image}@running\n", encoding="utf-8")
            (self.images / ".layers" / f"{image}:latest").write_text(f"{image}-base {image}@running\n", "utf-8")

        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.home),
            "STUB_LOG": str(self.log),
            "STUB_IMAGES": str(self.images),
            "STUB_OWNER": str(self.owner),
            "SHARED_MEMORY_HEALTH_SECONDS": "1",
            "SHARED_MEMORY_HEALTH_INTERVAL": "0.2",
            "SHARED_MEMORY_DEPLOY_MIN_FREE_GB": "0",
            "SHARED_MEMORY_DEPLOY_MIN_AVAILABLE_MB": "0",
        }

    def ssh(self, command: str, upload: str = "", **stubs: str) -> subprocess.CompletedProcess[bytes]:
        """Runs the script as the forced command of GitHub's key, with `upload` arriving on stdin."""
        env = {**self.env, **stubs, "SSH_ORIGINAL_COMMAND": command}
        return subprocess.run(["bash", str(SCRIPT)], input=gzip.compress(upload.encode()), env=env, capture_output=True)

    def release(self, commit: str) -> str:
        """What `docker save` of a release's three images carries, in the stand-ins' terms."""
        return "".join(f"{image}:{commit}\n" for image in IMAGES)

    def layered_release(self, commit: str, *, carrying_base: bool) -> str:
        """A release whose images each sit on the base the running ones have, with or without that base's layers."""
        lines = [f"{image}:{commit} {image}-base {image}@{commit}\n" for image in IMAGES]
        lines += [f"blob {image}@{commit}\n" for image in IMAGES]
        lines += [f"blob {image}-base\n" for image in IMAGES] if carrying_base else []
        return "".join(lines)

    def serving(self) -> str:
        """The release the server image tagged latest was built from."""
        return (self.images / "shared-memory-server:latest").read_text(encoding="utf-8").strip()

    def head(self) -> str:
        return git("rev-parse", "HEAD", cwd=self.repo)

    def calls(self) -> str:
        return self.log.read_text(encoding="utf-8")


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def test_a_healthy_release_replaces_the_running_one_after_a_backup(host: Host) -> None:
    done = host.ssh(f"deploy {host.newer}", host.release(host.newer))

    assert done.returncode == 0, done.stderr.decode()
    assert host.serving() == f"shared-memory-server:{host.newer}"
    assert host.head() == host.newer
    calls = host.calls()
    assert calls.index("backup backup now") < calls.index("compose up"), "the backup comes before the switch"
    assert "--no-build" in calls, "the host never builds"
    assert (host.images / "shared-memory-server:previous").read_text().strip() == "shared-memory-server@running"


def test_an_unhealthy_release_is_replaced_by_the_one_it_replaced(host: Host) -> None:
    done = host.ssh(
        f"deploy {host.newer}", host.release(host.newer), STUB_UNHEALTHY=f"shared-memory-server:{host.newer}"
    )

    assert done.returncode == 1
    assert b"so " + host.running.encode() + b" runs again" in done.stderr
    assert host.serving() == "shared-memory-server@running"
    assert host.head() == host.running


def test_a_release_that_fails_to_start_is_replaced_by_the_one_it_replaced(host: Host) -> None:
    done = host.ssh(
        f"deploy {host.newer}", host.release(host.newer), STUB_FAILS_TO_START=f"shared-memory-server:{host.newer}"
    )

    assert done.returncode == 1
    assert b"runs again" in done.stderr
    assert host.serving() == "shared-memory-server@running"
    assert host.head() == host.running


def test_nothing_switches_when_the_backup_fails(host: Host) -> None:
    done = host.ssh(f"deploy {host.newer}", host.release(host.newer), STUB_BACKUP_EXIT="1")

    assert done.returncode == 1
    assert b"The backup failed" in done.stderr
    assert "compose up" not in host.calls()
    assert host.serving() == "shared-memory-server@running"
    assert host.head() == host.running


def test_nothing_loads_when_the_hosts_web_server_is_down(host: Host) -> None:
    done = host.ssh(f"deploy {host.newer}", host.release(host.newer), STUB_NGINX_EXIT="3")

    assert done.returncode == 1
    assert b"nginx isn't running" in done.stderr
    assert "docker load" not in host.calls()


def test_a_deploy_that_changes_what_the_hosts_web_server_answers_fails_loudly(host: Host) -> None:
    done = host.ssh(f"deploy {host.newer}", host.release(host.newer), STUB_OWNER_BREAKS="1")

    assert done.returncode == 1
    assert b"answered http 200, https 200 before the deploy and http 502, https 502 after it" in done.stderr


def test_only_a_commit_on_main_deploys(host: Host) -> None:
    done = host.ssh(f"deploy {host.stray}", host.release(host.stray))

    assert done.returncode == 1
    assert b"isn't on main" in done.stderr
    assert "docker load" not in host.calls()
    assert host.head() == host.running


@pytest.mark.parametrize(
    "command",
    ["bash -c id", "deploy $(id)", "deploy main", "check; id", "deploy {commit} drill", "drill now", "layers all", ""],
)
def test_the_key_can_ask_for_nothing_but_a_check_its_layers_a_deploy_or_a_drill(host: Host, command: str) -> None:
    done = host.ssh(command.format(commit=host.newer))

    assert done.returncode == 1
    assert "compose up" not in host.calls()
    assert host.head() == host.running


def test_a_check_changes_nothing(host: Host) -> None:
    done = host.ssh("check")

    assert done.returncode == 0, done.stderr.decode()
    assert host.running.encode() in done.stdout
    for change in ("docker load", "docker tag", "compose up", "backup now"):
        assert change not in host.calls()


def test_layers_says_what_each_release_image_is_made_of_and_changes_nothing(host: Host) -> None:
    done = host.ssh("layers")

    assert done.returncode == 0, done.stderr.decode()
    first, *held = done.stdout.decode().splitlines()
    assert first == "# Docker 29.9.1, storage overlayfs"
    assert held == sorted(f"{image}-base {image}@running" for image in IMAGES)
    for call in host.calls().splitlines():
        assert call.startswith(("docker version", "docker info", "docker image ls", "docker image inspect")), call
    assert host.head() == host.running


def test_a_release_sent_without_the_layers_the_host_has_deploys(host: Host) -> None:
    done = host.ssh(f"deploy {host.newer}", host.layered_release(host.newer, carrying_base=False))

    assert done.returncode == 0, done.stderr.decode()
    assert host.serving() == f"shared-memory-server:{host.newer}"
    assert (host.images / ".layers" / "shared-memory-server:latest").read_text().split() == [
        "shared-memory-server-base",
        f"shared-memory-server@{host.newer}",
    ]


def test_a_release_missing_a_layer_the_host_lacks_switches_nothing(host: Host) -> None:
    for image in IMAGES:
        (host.images / ".layers" / f"{image}:latest").write_text(f"{image}-older-base {image}@running\n", "utf-8")

    done = host.ssh(f"deploy {host.newer}", host.layered_release(host.newer, carrying_base=False))

    assert done.returncode == 1
    assert b"The images didn't load. Nothing was switched." in done.stderr
    assert "backup now" not in host.calls()
    assert "compose up" not in host.calls()
    assert host.serving() == "shared-memory-server@running"


def test_a_release_carrying_every_layer_deploys_onto_a_host_that_has_none_of_them(host: Host) -> None:
    for image in IMAGES:
        (host.images / ".layers" / f"{image}:latest").unlink()

    done = host.ssh(f"deploy {host.newer}", host.layered_release(host.newer, carrying_base=True))

    assert done.returncode == 0, done.stderr.decode()
    assert host.serving() == f"shared-memory-server:{host.newer}"


def deployed(host: Host) -> Host:
    """The host after `newer` was deployed over `running`, with an empty record of calls."""
    done = host.ssh(f"deploy {host.newer}", host.release(host.newer))
    assert done.returncode == 0, done.stderr.decode()
    host.log.write_text("", encoding="utf-8")
    return host


def test_a_drill_really_runs_the_release_before_and_comes_back(host: Host) -> None:
    done = deployed(host).ssh("drill")

    assert done.returncode == 0, done.stderr.decode()
    ups = [line for line in host.calls().splitlines() if line.startswith("up ")]
    assert ups == ["up shared-memory-server@running", f"up shared-memory-server:{host.newer}"], "a swap both ways"
    assert host.calls().index("backup backup now") < host.calls().index("compose up")
    assert host.serving() == f"shared-memory-server:{host.newer}"
    assert host.head() == host.newer
    assert b"Drill done" in done.stdout


def test_a_drill_whose_release_before_is_unhealthy_comes_back_and_says_so(host: Host) -> None:
    done = deployed(host).ssh("drill", STUB_UNHEALTHY="shared-memory-server@running")

    assert done.returncode == 1
    assert b"isn't healthy" in done.stderr
    assert host.serving() == f"shared-memory-server:{host.newer}"
    assert host.head() == host.newer


def test_a_drill_with_no_release_before_changes_nothing(host: Host) -> None:
    done = host.ssh("drill")

    assert done.returncode == 1
    assert b"No release before" in done.stderr
    assert "compose up" not in host.calls()


def test_a_drill_refuses_when_the_release_before_is_the_same_images(host: Host) -> None:
    deployed(host)
    for image in IMAGES:
        shutil.copy(host.images / f"{image}:latest", host.images / f"{image}:previous")

    done = host.ssh("drill")

    assert done.returncode == 1
    assert b"the same images" in done.stderr
    assert "compose up" not in host.calls()
