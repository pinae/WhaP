"""What a failed test leaves behind, so a nightly failure can be understood without re-running it.

pytest-playwright records traces and screenshots only for its own ``page`` and
``context`` fixtures. The harness opens most browser contexts itself -- one per
container, one per ``login`` -- so it records those here: a trace for every
context, kept when a test that used it failed. A failed test that had a
container also gets its job log, a screenshot, and the container's
``docker logs`` from the compute server.

Everything lands under pytest-playwright's ``--output`` directory
(test-results/ by default), next to the traces it writes.
"""
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from containers import tail


def slug(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")


@dataclass
class _Recording:
    context: object
    name: str
    owner: str           # the fixture that opened it; a failing test that uses that fixture keeps the trace
    failed: bool = False


@dataclass
class Recorder:
    """Records a Playwright trace in each browser context the harness opens itself."""
    output: Path
    open: list = field(default_factory=list)

    @contextmanager
    def context(self, browser, context_args, *, name, owner):
        """A new browser context, traced. The trace is saved if a test using ``owner`` fails
        while it is open, or if opening it -- signing in, starting a container -- fails."""
        recording = _Recording(browser.new_context(**context_args), name, owner)
        # DOM snapshots, no screencast: the viewer still shows every step, and a
        # container that takes minutes to start would add tens of MB of frames.
        recording.context.tracing.start(screenshots=False, snapshots=True)
        self.open.append(recording)
        try:
            yield recording.context
        except BaseException:
            recording.failed = True
            raise
        finally:
            self.open.remove(recording)
            self._finish(recording)

    def test_failed(self, item):
        for recording in self.open:
            if recording.owner in item.fixturenames:
                recording.failed = True

    def _finish(self, recording):
        try:
            if recording.failed:
                path = self.output / slug(recording.name) / "trace.zip"
                path.parent.mkdir(parents=True, exist_ok=True)
                recording.context.tracing.stop(path=str(path))
            else:
                recording.context.tracing.stop()
        finally:
            recording.context.close()


def container_evidence(page, container_id, rig, out_dir):
    """Write what is known about a container to ``out_dir``; return report sections (title, text).

    Never raises: it runs while a failure is being reported, and must not
    replace that failure with one of its own.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sections = []
    try:
        page.screenshot(path=str(out_dir / "screenshot.png"), full_page=True)
    except Exception as e:
        sections.append(("screenshot", f"could not take one: {e}"))

    try:
        response = page.request.get(f"/api/containers/{container_id}")
    except Exception as e:
        return sections + [("container", f"could not ask WhaP about container {container_id}: {e}")]
    if not response.ok:
        return sections + [("container", f"GET /api/containers/{container_id} returned {response.status}")]
    container = response.json()
    log = container.get("ansible_log") or ""
    (out_dir / "job.log").write_text(log)
    sections.append((f"container {container_id}", f"status {container.get('status')}, "
                                                   f"name {container.get('container_name')}, "
                                                   f"address {container.get('ip_address')}"))
    sections.append(("job log, last lines (all of it in job.log)", tail(log, 60)))

    name = container.get("container_name")
    if not name:
        return sections
    if not rig.compute_shell:
        return sections + [("docker logs", "not collected: set [compute] shell in rig.toml")]
    try:
        state = rig.on_compute("docker", "inspect", "--format",
                               "{{.State.Status}} exit={{.State.ExitCode}} {{.State.Error}}", name)
        logs = rig.on_compute("docker", "logs", "--tail", "500", name)
    except Exception as e:
        return sections + [("docker logs", f"could not reach the compute server: {e}")]
    text = (f"$ docker inspect: {state.stdout.strip() or state.stderr.strip()}\n"
            f"$ docker logs --tail 500 {name}\n{logs.stdout}{logs.stderr}")
    (out_dir / "docker.log").write_text(text)
    sections.append(("docker logs, last lines (more in docker.log)", tail(text, 60)))
    return sections
