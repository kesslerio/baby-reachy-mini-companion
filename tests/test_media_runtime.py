from __future__ import annotations
import subprocess

from reachy_mini_conversation_app.media_runtime import MediaRuntimeCoordinator


class _Response:
    status = 200

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_prepare_for_audio_start_releases_daemon_media(monkeypatch) -> None:
    """The coordinator requests daemon media release and stop-sound before app audio starts."""
    calls: list[str] = []

    def urlopen(request, timeout):
        calls.append(request.full_url)
        assert timeout == 3.0
        return _Response()

    monkeypatch.setattr("shutil.which", lambda command: None)
    coordinator = MediaRuntimeCoordinator(
        release_daemon_media=True,
        clean_stale_alsa_ipc=False,
        urlopen=urlopen,
    )

    status = coordinator.prepare_for_audio_start()

    assert status.ok
    assert [call.rsplit("/", 1)[-1] for call in calls] == ["release", "stop_sound"]


def test_stale_ipc_cleanup_removes_only_known_unattached_objects(monkeypatch) -> None:
    """Cleanup removes known Reachy IPC keys only when shared memory is unattached."""
    commands: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command == ["ipcs", "-m"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="\n".join(
                    [
                        "key        shmid      owner      perms      bytes      nattch",
                        "0x00001091 1          pollen     600        4096       0",
                        "0x00001092 2          pollen     600        4096       1",
                        "0x00009999 3          pollen     600        4096       0",
                    ]
                ),
                stderr="",
            )
        if command == ["ipcs", "-s"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="\n".join(
                    [
                        "key        semid      owner      perms      nsems",
                        "0x00001094 4          pollen     600        1",
                        "0x00009999 5          pollen     600        1",
                    ]
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("shutil.which", lambda command: f"/usr/bin/{command}")
    coordinator = MediaRuntimeCoordinator(
        release_daemon_media=False,
        clean_stale_alsa_ipc=True,
        runner=runner,
    )

    status = coordinator.prepare_for_audio_start()

    assert status.ok
    assert ["ipcrm", "-m", "1"] in commands
    assert ["ipcrm", "-m", "2"] not in commands
    assert ["ipcrm", "-m", "3"] not in commands
    assert ["ipcrm", "-s", "4"] in commands
    assert ["ipcrm", "-s", "5"] not in commands


def test_missing_ipc_tools_degrades_to_noop(monkeypatch) -> None:
    """Local development machines without ipcs/ipcrm do not crash startup."""
    monkeypatch.setattr("shutil.which", lambda command: None)
    coordinator = MediaRuntimeCoordinator(release_daemon_media=False, clean_stale_alsa_ipc=True)

    status = coordinator.prepare_for_audio_start()

    assert status.ok
    assert status.ipc_results[0].detail == "ipcs_or_ipcrm_missing"
