import pytest
from agentflow.cli import cli
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


def test_help_lists_init_command(runner):
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "init" in result.output


def test_init_non_interactive_generates_basic_project(monkeypatch, runner, tmp_path):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "init",
            "--template",
            "basic",
            "--name",
            "my-agent",
            "--base-url",
            "http://localhost:9000",
            "--api-key",
            "af-live-test",
            "--non-interactive",
        ],
    )

    project_dir = tmp_path / "my-agent"

    assert result.exit_code == 0
    assert (project_dir / "main.py").exists()
    assert (project_dir / "requirements.txt").exists()
    assert (project_dir / ".env.example").exists()
    assert (project_dir / "README.md").exists()
    assert "Creating my-agent/" in result.output
    assert "Created my-agent/main.py" in result.output
    assert 'base_url="http://localhost:9000"' in (project_dir / "main.py").read_text()
    assert "AGENTFLOW_API_KEY=af-live-test" in (project_dir / ".env.example").read_text()


def test_init_non_interactive_uses_env_api_key(monkeypatch, runner, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTFLOW_API_KEY", "af-env-key")

    result = runner.invoke(
        cli,
        [
            "init",
            "--template",
            "basic",
            "--name",
            "env-agent",
            "--non-interactive",
        ],
    )

    project_dir = tmp_path / "env-agent"

    assert result.exit_code == 0
    assert "http://localhost:8000" in (project_dir / "main.py").read_text()
    assert "AGENTFLOW_API_KEY=af-env-key" in (project_dir / ".env.example").read_text()


def test_init_non_interactive_allows_missing_api_key(monkeypatch, runner, tmp_path):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "init",
            "--template",
            "basic",
            "--name",
            "ci-agent",
            "--non-interactive",
        ],
    )

    project_dir = tmp_path / "ci-agent"

    assert result.exit_code == 0
    assert (project_dir / "main.py").exists()
    assert 'api_key=""' in (project_dir / "main.py").read_text()
    assert "AGENTFLOW_API_KEY=" in (project_dir / ".env.example").read_text()


def test_init_interactive_generates_langchain_project(monkeypatch, runner, tmp_path):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        ["init"],
        input="lang-agent\n\nlang-api-key\nlangchain\n",
    )

    project_dir = tmp_path / "lang-agent"

    assert result.exit_code == 0
    assert "AgentFlow Project Setup" in result.output
    assert (project_dir / "main.py").exists()
    assert (project_dir / "requirements.txt").exists()
    assert "http://localhost:8000" in (project_dir / "main.py").read_text()
    assert "AgentFlowToolkit" in (project_dir / "main.py").read_text()
    assert "langchain-openai" in (project_dir / "requirements.txt").read_text()


def test_init_non_interactive_generates_crewai_project(monkeypatch, runner, tmp_path):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "init",
            "--template",
            "crewai",
            "--name",
            "crew-agent",
            "--base-url",
            "http://localhost:8100",
            "--api-key",
            "crew-key",
            "--non-interactive",
        ],
    )

    project_dir = tmp_path / "crew-agent"

    assert result.exit_code == 0
    assert (project_dir / "main.py").exists()
    assert "get_agentflow_tools" in (project_dir / "main.py").read_text()
    assert "crewai-tools" in (project_dir / "requirements.txt").read_text()


def test_init_non_interactive_generates_vercel_ai_project(monkeypatch, runner, tmp_path):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "init",
            "--template",
            "vercel-ai",
            "--name",
            "chat-agent",
            "--base-url",
            "http://localhost:8200",
            "--api-key",
            "vercel-key",
            "--non-interactive",
        ],
    )

    project_dir = tmp_path / "chat-agent"

    assert result.exit_code == 0
    assert (project_dir / "package.json").exists()
    assert (project_dir / "app" / "page.tsx").exists()
    assert (project_dir / "app" / "api" / "chat" / "route.ts").exists()
    assert "@agentflow/client" in (project_dir / "package.json").read_text()
    assert "streamText" in (project_dir / "app" / "api" / "chat" / "route.ts").read_text()


def test_init_fails_when_target_directory_exists(monkeypatch, runner, tmp_path):
    project_dir = tmp_path / "existing-agent"
    project_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "init",
            "--template",
            "basic",
            "--name",
            "existing-agent",
            "--api-key",
            "af-existing",
            "--non-interactive",
        ],
    )

    assert result.exit_code != 0
    assert "already exists" in result.output
