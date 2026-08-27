from pathlib import Path

from timesheet_clerk.config import SimplicateConfig


def test_simplicate_config_loads_missing_values_from_profile_env(tmp_path, monkeypatch):
    env_file = tmp_path / "atlas.env"
    env_file.write_text(
        "SIMPLICATE_BASE_URL=https://example.simplicate.nl/api/v2\n"
        "SIMPLICATE_API_KEY=test-key\n"
        "SIMPLICATE_API_SECRET=test-secret\n"
        "SIMPLICATE_EMPLOYEE_ID=employee-123\n",
        encoding="utf-8",
    )
    for key in (
        "SIMPLICATE_BASE_URL",
        "SIMPLICATE_API_KEY",
        "SIMPLICATE_API_SECRET",
        "SIMPLICATE_EMPLOYEE_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HERMES_PROFILE_ENV", str(env_file))

    config = SimplicateConfig.from_env()

    assert config.base_url == "https://example.simplicate.nl/api/v2"
    assert config.api_key == "test-key"
    assert config.api_secret == "test-secret"
    assert config.employee_id == "employee-123"


def test_process_environment_wins_over_profile_env(tmp_path, monkeypatch):
    env_file = tmp_path / "atlas.env"
    env_file.write_text(
        "SIMPLICATE_BASE_URL=https://profile.example/api/v2\n"
        "SIMPLICATE_API_KEY=profile-key\n"
        "SIMPLICATE_API_SECRET=profile-secret\n"
        "SIMPLICATE_EMPLOYEE_ID=profile-employee\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_PROFILE_ENV", str(env_file))
    monkeypatch.setenv("SIMPLICATE_BASE_URL", "https://process.example/api/v2")
    monkeypatch.setenv("SIMPLICATE_API_KEY", "process-key")
    monkeypatch.setenv("SIMPLICATE_API_SECRET", "process-secret")
    monkeypatch.setenv("SIMPLICATE_EMPLOYEE_ID", "process-employee")

    config = SimplicateConfig.from_env()

    assert config.base_url == "https://process.example/api/v2"
    assert config.api_key == "process-key"
    assert config.api_secret == "process-secret"
    assert config.employee_id == "process-employee"
