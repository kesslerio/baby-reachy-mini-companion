from __future__ import annotations
import shutil
import logging
import subprocess
import urllib.error
import urllib.request
from typing import Any, Callable, Iterable, Protocol, ContextManager
from dataclasses import field, dataclass

from reachy_mini_conversation_app.config import config


logger = logging.getLogger(__name__)

DAEMON_MEDIA_RELEASE_URL = "http://127.0.0.1:8000/api/media/release"
DAEMON_MEDIA_STOP_SOUND_URL = "http://127.0.0.1:8000/api/media/stop_sound"
DAEMON_MEDIA_REQUEST_TIMEOUT_SECONDS = 3.0
REACHY_ALSA_IPC_KEYS = frozenset({"0x00001091", "0x00001092", "0x00001094"})

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
UrlOpen = Callable[[urllib.request.Request, float], ContextManager[Any]]


class MediaRuntime(Protocol):
    """Protocol for components that prepare media before SDK audio starts."""

    def prepare_for_audio_start(self) -> "MediaPreparationStatus":
        """Prepare media and return diagnostic status."""
        ...


@dataclass(frozen=True)
class DaemonMediaResult:
    """Result from one daemon media API request."""

    url: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class IpcCleanupResult:
    """Result from one stale IPC cleanup decision."""

    key: str
    kind: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class MediaPreparationStatus:
    """Combined media preparation status for diagnostics."""

    daemon_results: list[DaemonMediaResult] = field(default_factory=list)
    ipc_results: list[IpcCleanupResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return whether every attempted preparation step succeeded."""
        return all(result.ok for result in self.daemon_results) and all(result.ok for result in self.ipc_results)

    def log_summary(self) -> None:
        """Log a compact summary suitable for robot app logs."""
        daemon_summary = ", ".join(f"{result.url.rsplit('/', 1)[-1]}={result.detail}" for result in self.daemon_results)
        ipc_summary = ", ".join(
            f"{result.kind}:{result.key}={result.detail}" for result in self.ipc_results if result.detail != "skipped"
        )
        logger.info(
            "Media preparation complete ok=%s daemon=[%s] ipc=[%s]",
            self.ok,
            daemon_summary or "none",
            ipc_summary or "none",
        )


class MediaRuntimeCoordinator:
    """Prepare Reachy Mini media devices for app-owned audio."""

    def __init__(
        self,
        *,
        release_daemon_media: bool | None = None,
        clean_stale_alsa_ipc: bool | None = None,
        runner: CommandRunner | None = None,
        urlopen: UrlOpen | None = None,
    ) -> None:
        """Initialize with optional test doubles for daemon requests and shell commands."""
        self.release_daemon_media = (
            config.RELEASE_DAEMON_MEDIA if release_daemon_media is None else release_daemon_media
        )
        self.clean_stale_alsa_ipc = (
            config.CLEAN_STALE_ALSA_IPC if clean_stale_alsa_ipc is None else clean_stale_alsa_ipc
        )
        self._runner = runner or self._run_command
        self._urlopen = urlopen or self._open_url

    def prepare_for_audio_start(self) -> MediaPreparationStatus:
        """Release daemon-owned media and clear stale local ALSA IPC."""
        status = MediaPreparationStatus(
            daemon_results=self._release_daemon_media(),
            ipc_results=self._clean_stale_alsa_ipc(),
        )
        status.log_summary()
        return status

    def _release_daemon_media(self) -> list[DaemonMediaResult]:
        if not self.release_daemon_media:
            return []

        results: list[DaemonMediaResult] = []
        for url in (DAEMON_MEDIA_RELEASE_URL, DAEMON_MEDIA_STOP_SOUND_URL):
            request = urllib.request.Request(url, method="POST")
            try:
                with self._urlopen(request, DAEMON_MEDIA_REQUEST_TIMEOUT_SECONDS) as response:
                    status = getattr(response, "status", "ok")
                results.append(DaemonMediaResult(url=url, ok=True, detail=str(status)))
            except urllib.error.HTTPError as exc:
                results.append(DaemonMediaResult(url=url, ok=False, detail=f"http_{exc.code}"))
                logger.warning("Daemon media request %s failed with HTTP %s", url, exc.code)
            except OSError as exc:
                results.append(DaemonMediaResult(url=url, ok=False, detail=str(exc)))
                logger.warning("Daemon media request %s failed: %s", url, exc)
        return results

    def _clean_stale_alsa_ipc(self) -> list[IpcCleanupResult]:
        if not self.clean_stale_alsa_ipc:
            return []
        if shutil.which("ipcs") is None or shutil.which("ipcrm") is None:
            logger.warning("Skipping stale ALSA IPC cleanup because ipcs/ipcrm is unavailable")
            return [IpcCleanupResult(key="", kind="ipc", ok=True, detail="ipcs_or_ipcrm_missing")]

        results: list[IpcCleanupResult] = []
        results.extend(self._cleanup_ipc_kind(kind="shm", ipcs_arg="-m", ipcrm_arg="-m"))
        results.extend(self._cleanup_ipc_kind(kind="sem", ipcs_arg="-s", ipcrm_arg="-s"))
        return results

    def _cleanup_ipc_kind(self, *, kind: str, ipcs_arg: str, ipcrm_arg: str) -> list[IpcCleanupResult]:
        listing = self._runner(["ipcs", ipcs_arg])
        if listing.returncode != 0:
            return [IpcCleanupResult(key="", kind=kind, ok=False, detail=f"ipcs_failed:{listing.stderr.strip()}")]

        results: list[IpcCleanupResult] = []
        for entry in self._parse_ipcs(listing.stdout, kind=kind):
            if entry.key not in REACHY_ALSA_IPC_KEYS:
                continue
            if kind == "shm" and entry.attachments != 0:
                results.append(IpcCleanupResult(key=entry.key, kind=kind, ok=True, detail="attached"))
                continue
            cleanup = self._runner(["ipcrm", ipcrm_arg, entry.identifier])
            if cleanup.returncode == 0:
                results.append(IpcCleanupResult(key=entry.key, kind=kind, ok=True, detail="removed"))
            else:
                results.append(
                    IpcCleanupResult(key=entry.key, kind=kind, ok=False, detail=f"ipcrm_failed:{cleanup.stderr.strip()}")
                )
        return results

    @staticmethod
    def _parse_ipcs(output: str, *, kind: str) -> Iterable["_IpcEntry"]:
        for raw_line in output.splitlines():
            parts = raw_line.split()
            if len(parts) < 2 or not parts[0].startswith("0x"):
                continue
            attachments = 0
            if kind == "shm" and len(parts) >= 6:
                try:
                    attachments = int(parts[5])
                except ValueError:
                    attachments = 0
            yield _IpcEntry(key=parts[0], identifier=parts[1], attachments=attachments)

    @staticmethod
    def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, capture_output=True, text=True, check=False)

    @staticmethod
    def _open_url(request: urllib.request.Request, timeout: float) -> ContextManager[Any]:
        return urllib.request.urlopen(request, timeout=timeout)


@dataclass(frozen=True)
class _IpcEntry:
    key: str
    identifier: str
    attachments: int = 0
