"""
Service for finding lint and test commands in project config files.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ProjectCommands:
    """Commands discovered in project configuration."""
    lint_command: Optional[str] = None
    test_command: Optional[str] = None
    format_command: Optional[str] = None
    build_command: Optional[str] = None
    install_command: Optional[str] = None
    source_file: str = ""
    project_type: str = "unknown"


class ConfigFinder:
    """Find lint/test commands in project configuration files."""

    # Files to check, in priority order
    CONFIG_FILES = [
        "Makefile",
        "package.json",
        "pyproject.toml",
        "setup.cfg",
        "tox.ini",
        ".pre-commit-config.yaml",
        "README.md",
    ]

    def find_commands(self, repo_path: Path) -> ProjectCommands:
        """
        Find lint and test commands from project configuration.
        
        Args:
            repo_path: Path to repository root
            
        Returns:
            ProjectCommands with discovered commands
        """
        commands = ProjectCommands()

        # Check each config file
        for config_file in self.CONFIG_FILES:
            file_path = repo_path / config_file
            if file_path.exists():
                try:
                    self._parse_config_file(file_path, commands)
                except Exception as e:
                    logger.warning(f"Failed to parse {config_file}: {e}")

            # Stop if we have both lint and test commands
            if commands.lint_command and commands.test_command:
                break

        # Set defaults based on project type if commands not found
        self._set_defaults(repo_path, commands)

        logger.info(f"Found commands - lint: {commands.lint_command}, test: {commands.test_command}")
        return commands

    def _parse_config_file(self, file_path: Path, commands: ProjectCommands) -> None:
        """Parse a configuration file for commands."""
        filename = file_path.name
        content = file_path.read_text(encoding="utf-8", errors="ignore")

        if filename == "Makefile":
            self._parse_makefile(content, commands)
        elif filename == "package.json":
            self._parse_package_json(content, commands)
        elif filename == "pyproject.toml":
            self._parse_pyproject_toml(content, commands)
        elif filename == "setup.cfg":
            self._parse_setup_cfg(content, commands)
        elif filename == "tox.ini":
            self._parse_tox_ini(content, commands)
        elif filename == "README.md":
            self._parse_readme(content, commands)

    def _parse_makefile(self, content: str, commands: ProjectCommands) -> None:
        """Parse Makefile for targets."""
        commands.source_file = "Makefile"

        # Find lint target
        if re.search(r'^lint\s*:', content, re.MULTILINE):
            commands.lint_command = "make lint"
        elif re.search(r'^check\s*:', content, re.MULTILINE):
            commands.lint_command = "make check"

        # Find test target
        if re.search(r'^test\s*:', content, re.MULTILINE):
            commands.test_command = "make test"

        # Find format target
        if re.search(r'^format\s*:', content, re.MULTILINE):
            commands.format_command = "make format"
        elif re.search(r'^fmt\s*:', content, re.MULTILINE):
            commands.format_command = "make fmt"

    def _parse_package_json(self, content: str, commands: ProjectCommands) -> None:
        """Parse package.json for npm scripts."""
        try:
            data = json.loads(content)
            scripts = data.get("scripts", {})
            commands.source_file = "package.json"
            commands.project_type = "javascript"

            if "lint" in scripts:
                commands.lint_command = "npm run lint"
            elif "eslint" in scripts:
                commands.lint_command = "npm run eslint"

            if "test" in scripts:
                commands.test_command = "npm test"
            elif "test:unit" in scripts:
                commands.test_command = "npm run test:unit"

            if "format" in scripts:
                commands.format_command = "npm run format"
            elif "prettier" in scripts:
                commands.format_command = "npm run prettier"

            if "build" in scripts:
                commands.build_command = "npm run build"

            commands.install_command = "npm install"

        except json.JSONDecodeError:
            pass

    def _parse_pyproject_toml(self, content: str, commands: ProjectCommands) -> None:
        """Parse pyproject.toml for tool configurations."""
        commands.source_file = "pyproject.toml"
        commands.project_type = "python"

        # Check for ruff
        if "[tool.ruff]" in content:
            commands.lint_command = "ruff check ."

        # Check for flake8
        elif "[tool.flake8]" in content:
            commands.lint_command = "flake8 ."

        # Check for pytest
        if "[tool.pytest" in content:
            if not commands.test_command:
                commands.test_command = "pytest"

        # Check for black
        if "[tool.black]" in content:
            commands.format_command = "black ."

        # Check for poetry
        if "[tool.poetry]" in content:
            commands.install_command = "poetry install"
            if not commands.lint_command and "[tool.ruff]" not in content:
                commands.lint_command = "poetry run ruff check ."
            if not commands.test_command:
                commands.test_command = "poetry run pytest"

        # Check for PDM
        elif "[project]" in content and "[tool.pdm]" in content:
            commands.install_command = "pdm install"

    def _parse_setup_cfg(self, content: str, commands: ProjectCommands) -> None:
        """Parse setup.cfg for tool configurations."""
        if commands.source_file:
            return  # Already have better source

        commands.source_file = "setup.cfg"
        commands.project_type = "python"

        if "[flake8]" in content and not commands.lint_command:
            commands.lint_command = "flake8 ."

        if "[tool:pytest]" in content and not commands.test_command:
            commands.test_command = "pytest"

    def _parse_tox_ini(self, content: str, commands: ProjectCommands) -> None:
        """Parse tox.ini for test configuration."""
        if commands.test_command:
            return

        commands.source_file = "tox.ini"
        commands.project_type = "python"

        if "[testenv:lint]" in content:
            commands.lint_command = "tox -e lint"
        if "[testenv]" in content:
            commands.test_command = "tox"

    def _parse_readme(self, content: str, commands: ProjectCommands) -> None:
        """Parse README.md for command hints (last resort)."""
        content_lower = content.lower()

        if not commands.lint_command:
            # Look for lint commands in code blocks
            lint_patterns = [
                r'```(?:bash|sh|shell)?\s*\n\s*((?:npm run |yarn |pnpm )?lint[^\n]*)',
                r'```(?:bash|sh|shell)?\s*\n\s*((?:ruff|flake8|eslint)[^\n]*)',
            ]
            for pattern in lint_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    commands.lint_command = match.group(1).strip()
                    break

        if not commands.test_command:
            test_patterns = [
                r'```(?:bash|sh|shell)?\s*\n\s*((?:npm |yarn |pnpm )?test[^\n]*)',
                r'```(?:bash|sh|shell)?\s*\n\s*(pytest[^\n]*)',
            ]
            for pattern in test_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    commands.test_command = match.group(1).strip()
                    break

    def _set_defaults(self, repo_path: Path, commands: ProjectCommands) -> None:
        """Set default commands based on project type."""
        # Detect project type if not set
        if commands.project_type == "unknown":
            if (repo_path / "package.json").exists():
                commands.project_type = "javascript"
            elif (repo_path / "pyproject.toml").exists() or (repo_path / "setup.py").exists():
                commands.project_type = "python"
            elif (repo_path / "go.mod").exists():
                commands.project_type = "go"
            elif (repo_path / "Cargo.toml").exists():
                commands.project_type = "rust"

        # Set defaults based on project type
        if commands.project_type == "python":
            if not commands.lint_command:
                # Check if ruff is likely available
                if (repo_path / "pyproject.toml").exists():
                    commands.lint_command = "ruff check ."
                else:
                    commands.lint_command = "flake8 ."
            if not commands.test_command:
                commands.test_command = "pytest"
            if not commands.install_command:
                if (repo_path / "requirements.txt").exists():
                    commands.install_command = "pip install -r requirements.txt"
                else:
                    commands.install_command = "pip install -e ."

        elif commands.project_type == "javascript":
            if not commands.lint_command:
                commands.lint_command = "npm run lint"
            if not commands.test_command:
                commands.test_command = "npm test"
            if not commands.install_command:
                commands.install_command = "npm install"

        elif commands.project_type == "go":
            if not commands.lint_command:
                commands.lint_command = "golangci-lint run"
            if not commands.test_command:
                commands.test_command = "go test ./..."

        elif commands.project_type == "rust":
            if not commands.lint_command:
                commands.lint_command = "cargo clippy"
            if not commands.test_command:
                commands.test_command = "cargo test"
