"""Tests for CLI singular command aliases.

Verifies that singular forms of CLI commands work alongside plural forms.
"""

from click.testing import CliRunner
from aiops_cli.cli import cli


def test_singular_project_command_exists():
    """Test that 'aiops project' singular form is available."""
    runner = CliRunner()
    result = runner.invoke(cli, ["project", "--help"])
    assert result.exit_code == 0
    assert "Project management commands" in result.output


def test_plural_project_command_still_works():
    """Test that 'aiops projects' plural form still works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["projects", "--help"])
    assert result.exit_code == 0
    assert "Project management commands" in result.output


def test_singular_session_command_exists():
    """Test that 'aiops session' singular form is available."""
    runner = CliRunner()
    result = runner.invoke(cli, ["session", "--help"])
    assert result.exit_code == 0
    assert "Session management commands" in result.output


def test_plural_session_command_still_works():
    """Test that 'aiops sessions' plural form still works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["sessions", "--help"])
    assert result.exit_code == 0
    assert "Session management commands" in result.output


def test_singular_tenant_command_exists():
    """Test that 'aiops tenant' singular form is available."""
    runner = CliRunner()
    result = runner.invoke(cli, ["tenant", "--help"])
    assert result.exit_code == 0
    assert "Tenant management commands" in result.output


def test_plural_tenant_command_still_works():
    """Test that 'aiops tenants' plural form still works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["tenants", "--help"])
    assert result.exit_code == 0
    assert "Tenant management commands" in result.output


def test_singular_integration_command_exists():
    """Test that 'aiops integration' singular form is available."""
    runner = CliRunner()
    result = runner.invoke(cli, ["integration", "--help"])
    assert result.exit_code == 0
    assert "Integration management commands" in result.output


def test_plural_integration_command_still_works():
    """Test that 'aiops integrations' plural form still works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["integrations", "--help"])
    assert result.exit_code == 0
    assert "Integration management commands" in result.output


def test_singular_credential_command_exists():
    """Test that 'aiops credential' singular form is available."""
    runner = CliRunner()
    result = runner.invoke(cli, ["credential", "--help"])
    assert result.exit_code == 0
    assert "Manage personal integration credentials" in result.output


def test_plural_credential_command_still_works():
    """Test that 'aiops credentials' plural form still works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["credentials", "--help"])
    assert result.exit_code == 0
    assert "Manage personal integration credentials" in result.output


def test_singular_and_plural_are_equivalent():
    """Test that singular and plural forms show same help text (minus form reference)."""
    runner = CliRunner()

    # Test project
    singular = runner.invoke(cli, ["project", "--help"])
    plural = runner.invoke(cli, ["projects", "--help"])
    assert singular.exit_code == plural.exit_code == 0
    # Both should have the same commands listed
    for cmd in ["list", "get", "create", "status"]:
        assert cmd in singular.output
        assert cmd in plural.output


def test_project_subcommands_work_via_singular():
    """Test that project subcommands work via singular form."""
    runner = CliRunner()
    result = runner.invoke(cli, ["project", "list", "--help"])
    assert result.exit_code == 0
    assert "List projects" in result.output


def test_session_subcommands_work_via_singular():
    """Test that session subcommands work via singular form."""
    runner = CliRunner()
    result = runner.invoke(cli, ["session", "list", "--help"])
    assert result.exit_code == 0
    assert "List active sessions" in result.output


def test_tenant_subcommands_work_via_singular():
    """Test that tenant subcommands work via singular form."""
    runner = CliRunner()
    result = runner.invoke(cli, ["tenant", "list", "--help"])
    assert result.exit_code == 0
    assert "List tenants" in result.output


def test_integration_subcommands_work_via_singular():
    """Test that integration subcommands work via singular form."""
    runner = CliRunner()
    result = runner.invoke(cli, ["integration", "list", "--help"])
    assert result.exit_code == 0
    assert "List integrations" in result.output


def test_credential_subcommands_work_via_singular():
    """Test that credential subcommands work via singular form."""
    runner = CliRunner()
    result = runner.invoke(cli, ["credential", "list", "--help"])
    assert result.exit_code == 0
    assert "List your personal integration credentials" in result.output


def test_singular_issue_command_exists():
    """Test that 'aiops issue' singular form is available."""
    runner = CliRunner()
    result = runner.invoke(cli, ["issue", "--help"])
    assert result.exit_code == 0
    assert "Issue management commands" in result.output


def test_plural_issue_command_still_works():
    """Test that 'aiops issues' plural form still works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["issues", "--help"])
    assert result.exit_code == 0
    assert "Issue management commands" in result.output


def test_singular_agent_command_exists():
    """Test that 'aiops agent' singular form is available."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "--help"])
    assert result.exit_code == 0
    assert "Agent context management commands" in result.output


def test_plural_agent_command_still_works():
    """Test that 'aiops agents' plural form still works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agents", "--help"])
    assert result.exit_code == 0
    assert "Agent context management commands" in result.output


def test_issue_subcommands_work_via_singular():
    """Test that issue subcommands work via singular form."""
    runner = CliRunner()
    result = runner.invoke(cli, ["issue", "list", "--help"])
    assert result.exit_code == 0
    assert "List" in result.output


def test_agent_subcommands_work_via_singular():
    """Test that agent subcommands work via singular form."""
    runner = CliRunner()
    result = runner.invoke(cli, ["agent", "global", "--help"])
    assert result.exit_code == 0
    assert "Agent context" in result.output or "global" in result.output
