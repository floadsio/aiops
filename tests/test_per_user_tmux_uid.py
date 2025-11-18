"""Integration tests for per-user tmux sessions with UID switching.

These tests verify that AI tools running in tmux can be launched with different
user UIDs, allowing isolation between users.
"""
import os
import pwd
import subprocess
import time
from pathlib import Path

import pytest

# Skip these tests if not running as a privileged user (needs sudo)
pytestmark = pytest.mark.skipif(
    os.geteuid() != 0 and subprocess.run(
        ["sudo", "-n", "true"],
        capture_output=True,
    ).returncode != 0,
    reason="Requires sudo access for user switching tests",
)


def test_sudo_can_switch_users():
    """Verify that sudo user switching works in the test environment."""
    # Run a command as root (or another user) and check the UID
    result = subprocess.run(
        ["sudo", "-n", "-u", "root", "id", "-u"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "0"  # root UID is 0


def test_per_user_command_runs_with_correct_uid():
    """Test that commands launched via sudo run with the target user's UID.

    This simulates how aiops launches AI tools in tmux with per-user UIDs.
    """
    # Get a non-root user to test with (typically the first regular user)
    try:
        # Try to find a user with UID >= 1000 (typical for regular users)
        test_users = [u for u in pwd.getpwall() if 1000 <= u.pw_uid < 65000]
        if not test_users:
            pytest.skip("No regular user accounts found for testing")

        test_user = test_users[0]
        target_username = test_user.pw_name
        target_uid = test_user.pw_uid
    except Exception as exc:
        pytest.skip(f"Could not determine test user: {exc}")

    # Run a simple command as the target user and verify the UID
    result = subprocess.run(
        ["sudo", "-n", "-u", target_username, "bash", "-c", "echo $UID"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, f"Command failed: {result.stderr}"
    reported_uid = result.stdout.strip()
    assert reported_uid == str(target_uid), (
        f"Expected UID {target_uid} but got {reported_uid}"
    )


def test_per_user_session_creates_files_with_correct_ownership():
    """Test that files created by per-user sessions have correct ownership.

    This is critical for workspace operations where files must be owned by
    the user, not by the Flask app user (syseng).
    """
    # Get a test user
    try:
        test_users = [u for u in pwd.getpwall() if 1000 <= u.pw_uid < 65000]
        if not test_users:
            pytest.skip("No regular user accounts found for testing")

        test_user = test_users[0]
        target_username = test_user.pw_name
        target_uid = test_user.pw_uid
        target_gid = test_user.pw_gid
    except Exception as exc:
        pytest.skip(f"Could not determine test user: {exc}")

    # Use /tmp which is accessible to all users
    test_file = Path(f"/tmp/aiops-test-ownership-{os.getpid()}.txt")

    try:
        # Create a file as the target user
        result = subprocess.run(
            [
                "sudo",
                "-n",
                "-u",
                target_username,
                "bash",
                "-c",
                f"echo 'test content' > {test_file}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0, f"File creation failed: {result.stderr}"
        assert test_file.exists(), "File was not created"

        # Verify file ownership
        stat_info = test_file.stat()
        assert stat_info.st_uid == target_uid, (
            f"File UID {stat_info.st_uid} != expected {target_uid}"
        )
        assert stat_info.st_gid == target_gid, (
            f"File GID {stat_info.st_gid} != expected {target_gid}"
        )
    finally:
        # Cleanup
        if test_file.exists():
            subprocess.run(["sudo", "rm", "-f", str(test_file)], timeout=5)


def test_tmux_pane_command_runs_as_target_user():
    """Test that commands in tmux panes can run as different users.

    This simulates the actual pattern used by aiops:
    1. Flask app (syseng) creates tmux session
    2. Inside the pane, uses sudo to switch to target user
    3. Verifies the command runs with target user's UID
    """
    # Get a test user
    try:
        test_users = [u for u in pwd.getpwall() if 1000 <= u.pw_uid < 65000]
        if not test_users:
            pytest.skip("No regular user accounts found for testing")

        test_user = test_users[0]
        target_username = test_user.pw_name
        target_uid = test_user.pw_uid
    except Exception as exc:
        pytest.skip(f"Could not determine test user: {exc}")

    # Create a unique tmux session name for this test
    session_name = f"test-uid-{os.getpid()}"

    try:
        # Create tmux session (runs as current user/syseng)
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_name],
            check=True,
            timeout=5,
        )

        # Send a command to run as target user and capture output
        output_file = f"/tmp/tmux-uid-test-{os.getpid()}.txt"
        command = f"sudo -n -u {target_username} bash -c 'echo $UID > {output_file}'"

        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, command, "Enter"],
            check=True,
            timeout=5,
        )

        # Wait for command to execute
        time.sleep(1)

        # Read the output
        output_path = Path(output_file)
        if output_path.exists():
            reported_uid = output_path.read_text().strip()
            assert reported_uid == str(target_uid), (
                f"Expected UID {target_uid} in tmux pane but got {reported_uid}"
            )
            # Cleanup
            subprocess.run(["sudo", "rm", "-f", output_file], timeout=5)
        else:
            pytest.fail("Tmux command did not create output file")

    finally:
        # Cleanup: kill the tmux session
        subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            capture_output=True,
            timeout=5,
        )


def test_workspace_directory_accessible_after_uid_switch():
    """Test that workspace directories are accessible after switching UIDs.

    This verifies the fix for issue #19: workspace parent directories need
    execute permissions so commands running as different UIDs can traverse them.
    """
    # Get a test user
    try:
        test_users = [u for u in pwd.getpwall() if 1000 <= u.pw_uid < 65000]
        if not test_users:
            pytest.skip("No regular user accounts found for testing")

        test_user = test_users[0]
        target_username = test_user.pw_name
    except Exception as exc:
        pytest.skip(f"Could not determine test user: {exc}")

    # Create a workspace-like directory structure in /tmp
    test_root = Path(f"/tmp/aiops-workspace-test-{os.getpid()}")
    workspace_dir = test_root / "workspace" / "test-project"

    try:
        workspace_dir.mkdir(parents=True)

        # Set permissions that allow traversal (o+rx)
        test_root.chmod(0o755)
        (test_root / "workspace").chmod(0o755)
        workspace_dir.chmod(0o755)

        # Try to access the directory as target user
        result = subprocess.run(
            [
                "sudo",
                "-n",
                "-u",
                target_username,
                "bash",
                "-c",
                f"cd {workspace_dir} && pwd",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        assert result.returncode == 0, (
            f"Failed to access workspace as {target_username}: {result.stderr}"
        )
        assert str(workspace_dir) in result.stdout, (
            f"Directory traversal failed: {result.stdout}"
        )
    finally:
        # Cleanup
        if test_root.exists():
            subprocess.run(["rm", "-rf", str(test_root)], timeout=5)
