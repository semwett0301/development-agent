"""
Service for validating code changes (linting, testing).
Uses LangChain chains for error fixing.
"""
import logging
import subprocess
import re
from pathlib import Path
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

from ..models import ValidationResult, LintError, TestError, CodeFixesOutput
from ..chains import create_fix_chain
from .config_finder import ConfigFinder, ProjectCommands

logger = logging.getLogger(__name__)


class Validator:
    """Validate code changes by running linter and tests."""

    def __init__(self, llm: BaseChatModel, config_finder: Optional[ConfigFinder] = None, langfuse_callbacks: Optional[list] = None):
        """
        Initialize the validator.

        Input:
            llm: LangChain chat model to use
            config_finder: Optional config finder for project commands
            langfuse_callbacks: Optional list of callbacks for Langfuse tracing
        """
        self.llm = llm
        self.config_finder = config_finder or ConfigFinder()
        self._langfuse_callbacks = langfuse_callbacks
        self._fix_chain: Optional[Runnable] = None

    @property
    def fix_chain(self) -> Runnable:
        """Lazy-loaded fix chain."""
        if self._fix_chain is None:
            self._fix_chain = create_fix_chain(self.llm)
        return self._fix_chain

    def install_dependencies(self, repo_path: Path, commands: Optional[ProjectCommands] = None) -> bool:
        """
        Install project dependencies before validation.

        Input:
            repo_path: Path to repository
            commands: Pre-discovered project commands (optional)

        Output:
            True if installation succeeded or skipped, False if failed
        """
        if commands is None:
            commands = self.config_finder.find_commands(repo_path)

        # Skip install if using Docker (dependencies installed during build)
        if commands.has_docker_compose or commands.has_dockerfile:
            logger.info(
                "Using Docker for validation - dependencies will be installed during build")
            return True

        if not commands.install_command:
            logger.info(
                "No install command found, skipping dependency installation")
            return True

        logger.info(f"Installing dependencies: {commands.install_command}")
        result = self._run_command(
            commands.install_command, repo_path, timeout=600)

        if result["returncode"] == 0:
            logger.info("Dependencies installed successfully")
            return True
        if result["returncode"] == 127:
            logger.warning(f"Install command not found (exit 127): {
                           commands.install_command}")
            return True  # Skip, don't fail

        logger.error(f"Dependency installation failed with exit code {
                     result['returncode']}")
        logger.debug(f"Install output: {result['output'][:1000]}")
        return False

    def validate(self, repo_path: Path, commands: Optional[ProjectCommands] = None) -> ValidationResult:
        """
        Run linter and tests on the repository.

        Input:
            repo_path: Path to repository
            commands: Pre-discovered project commands (optional)

        Output:
            ValidationResult with errors
        """
        if commands is None:
            commands = self.config_finder.find_commands(repo_path)

        # Try Docker-based validation if available
        if commands.has_docker_compose or commands.has_dockerfile:
            docker_result = self._validate_with_docker(repo_path, commands)
            if docker_result is not None:
                return docker_result
            logger.warning(
                "Docker validation failed, falling back to direct commands")

        result = ValidationResult(success=True)

        # Run linter
        if commands.lint_command:
            logger.info(f"Running linter: {commands.lint_command}")
            lint_result = self._run_command(commands.lint_command, repo_path)
            result.lint_command = commands.lint_command
            result.lint_output = lint_result.get("output", "")

            if lint_result["returncode"] != 0:
                result.success = False
                result.lint_errors = self._parse_lint_errors(
                    result.lint_output,
                    commands.project_type,
                )
                # Fallback: if command failed but no errors parsed, add generic error
                if not result.lint_errors:
                    output_snippet = result.lint_output[:500] if result.lint_output.strip(
                    ) else "(no output)"
                    result.lint_errors = [LintError(
                        file_path="unknown",
                        line=0,
                        column=0,
                        message=f"Linter failed with exit code {
                            lint_result['returncode']}. Output: {output_snippet}",
                        rule="lint-failure",
                    )]
        else:
            logger.warning("No lint command found, skipping linting")

        # Run tests
        if commands.test_command:
            logger.info(f"Running tests: {commands.test_command}")
            test_result = self._run_command(commands.test_command, repo_path)
            result.test_command = commands.test_command
            result.test_output = test_result.get("output", "")

            if test_result["returncode"] != 0:
                result.success = False
                result.test_errors = self._parse_test_errors(
                    result.test_output,
                    commands.project_type,
                )
                # Fallback: if command failed but no errors parsed, add generic error
                if not result.test_errors:
                    traceback = result.test_output[-1500:] if result.test_output.strip(
                    ) else "(no output)"
                    result.test_errors = [TestError(
                        test_name="unknown",
                        file_path=None,
                        message=f"Tests failed with exit code {
                            test_result['returncode']}",
                        traceback=traceback,
                    )]
        else:
            logger.warning("No test command found, skipping tests")

        return result

    def fix_errors(self, validation_result: ValidationResult, repo_path: Path) -> CodeFixesOutput:
        """
        Use LLM chain to fix linter and test errors.

        Input:
            validation_result: The validation result with errors
            repo_path: Path to repository

        Output:
            CodeFixesOutput with fixes for each file
        """
        if validation_result.success:
            return CodeFixesOutput(fixes=[], explanation="No errors to fix", unfixable=[])

        # Get files with errors (skip invalid paths)
        error_files = set()
        for err in validation_result.lint_errors:
            if self._is_valid_file_path(err.file_path):
                error_files.add(err.file_path)
        for err in validation_result.test_errors:
            if self._is_valid_file_path(err.file_path):
                error_files.add(err.file_path)

        logger.info(f"Files with errors: {error_files}")

        # Read current content of error files
        file_contents = {}
        formatted_contents = []
        for file_path in error_files:
            full_path = repo_path / file_path
            if full_path.exists():
                try:
                    content = full_path.read_text()
                    file_contents[file_path] = content
                    formatted_contents.append(
                        f"### {file_path}\n```\n{content}\n```")
                except Exception as e:
                    logger.warning(f"Could not read {file_path}: {e}")
            else:
                logger.warning(f"File not found: {full_path}")

        # If no file contents found, we can't generate fixes
        if not formatted_contents:
            logger.warning(
                "No file contents available for fixing - cannot generate fixes")
            # Try to extract useful info for unfixable list
            unfixable_msgs = []
            if validation_result.lint_output:
                unfixable_msgs.append(
                    f"Lint errors: {validation_result.lint_output[:500]}")
            if validation_result.test_output:
                unfixable_msgs.append(
                    f"Test errors: {validation_result.test_output[:500]}")
            return CodeFixesOutput(
                fixes=[],
                explanation="Could not locate files to fix",
                unfixable=unfixable_msgs or ["Unknown error files"],
            )

        logger.info(f"Loaded {len(formatted_contents)} files for fixing")

        # Invoke the fix chain
        invoke_kwargs = {}
        if self._langfuse_callbacks:
            invoke_kwargs["config"] = {"callbacks": self._langfuse_callbacks}
        result: CodeFixesOutput = self.fix_chain.invoke({
            "error_summary": validation_result.get_error_summary(),
            "lint_output": validation_result.lint_output[:3000],  # Truncate
            "test_output": validation_result.test_output[:3000],  # Truncate
            "files_with_errors": "\n".join(f"- {f}" for f in error_files),
            "file_contents": "\n\n".join(formatted_contents),
        }, **invoke_kwargs)

        logger.info(f"Fix chain returned {len(result.fixes)} fixes")
        return result

    def apply_fixes(self, fixes: CodeFixesOutput, repo_path: Path) -> list[str]:
        """
        Apply fixes to files.

        Input:
            fixes: CodeFixesOutput with file fixes
            repo_path: Path to repository

        Output:
            List of fixed file paths
        """
        fixed_files = []

        for fix in fixes.fixes:
            full_path = repo_path / fix.file_path
            try:
                full_path.write_text(fix.new_content, encoding="utf-8")
                fixed_files.append(fix.file_path)
                logger.info(f"Applied fix to {fix.file_path}: {
                            ', '.join(fix.issues_fixed)}")
            except Exception as e:
                logger.error(f"Failed to apply fix to {fix.file_path}: {e}")

        if fixes.unfixable:
            logger.warning(f"Unfixable issues: {fixes.unfixable}")

        return fixed_files

    def _validate_with_docker(self, repo_path: Path, commands: ProjectCommands) -> Optional[ValidationResult]:
        """
        Run validation inside a generic Docker container with mounted code.

        Instead of using project's docker-compose (which may have databases, etc.),
        we create a simple container with just the tools needed for lint/test.

        Returns ValidationResult if Docker validation worked, None if should fallback.
        """
        # Check if Docker is available
        docker_check = self._run_command(
            "docker --version", repo_path, timeout=10)
        if docker_check["returncode"] != 0:
            logger.warning("Docker CLI not available")
            return None

        # Use a generic validation container based on project type
        return self._validate_with_generic_container(repo_path, commands)

    def _get_docker_image_for_project(self, project_type: str) -> str:
        """Get the appropriate Docker image for the project type."""
        images = {
            "javascript": "node:20-alpine",
            "typescript": "node:20-alpine",
            "python": "python:3.12-slim",
            "go": "golang:1.22-alpine",
            "rust": "rust:1.75-slim",
        }
        return images.get(project_type, "node:20-alpine")

    def _create_missing_env_files(self, repo_path: Path) -> list[str]:
        """
        Create missing .env files with placeholder values.
        Returns list of created files.
        """
        created_files = []

        # Find .env.example or .env.template files
        env_templates = list(repo_path.glob("**/.env.example")) + \
            list(repo_path.glob("**/.env.template")) + \
            list(repo_path.glob("**/.env.sample"))

        for template in env_templates:
            # Skip node_modules
            if "node_modules" in str(template):
                continue

            env_file = template.parent / ".env"
            if not env_file.exists():
                try:
                    # Copy template to .env
                    content = template.read_text()
                    env_file.write_text(content)
                    rel_path = str(env_file.relative_to(repo_path))
                    created_files.append(rel_path)
                    logger.info(f"Created {rel_path} from {template.name}")
                except Exception as e:
                    logger.warning(f"Failed to create .env from {
                                   template}: {e}")

        # Also check docker-compose for env_file references
        compose_files = ["docker-compose.yml",
                         "docker-compose.yaml", "compose.yml", "compose.yaml"]
        for compose_name in compose_files:
            compose_path = repo_path / compose_name
            if compose_path.exists():
                try:
                    content = compose_path.read_text()
                    # Find env_file references
                    env_refs = re.findall(
                        r'env_file:\s*(?:-\s*)?["\']?([^"\'\n]+)["\']?', content)
                    for env_ref in env_refs:
                        env_path = repo_path / env_ref.strip()
                        if not env_path.exists():
                            # Create empty .env file
                            env_path.parent.mkdir(parents=True, exist_ok=True)
                            env_path.write_text(
                                "# Auto-generated placeholder\nNODE_ENV=development\n")
                            rel_path = str(env_path.relative_to(repo_path))
                            created_files.append(rel_path)
                            logger.info(f"Created placeholder {rel_path}")
                except Exception as e:
                    logger.warning(f"Failed to parse {compose_name}: {e}")

        return created_files

    def _run_lint_in_container(
        self, container_name: str, lint_command: str, install_cmd: Optional[str],
        pm_install: str, repo_path: Path, project_type: str, result: ValidationResult
    ) -> None:
        """Run lint command in container and update result."""
        if install_cmd:
            full_cmd = f"{pm_install}{install_cmd} && {lint_command}"
        else:
            full_cmd = f"{pm_install}{lint_command}"

        logger.info(f"Running lint: {full_cmd}")
        docker_cmd = f'docker exec {container_name} sh -c "{full_cmd}"'
        lint_result = self._run_command(docker_cmd, repo_path, timeout=600)
        result.lint_command = docker_cmd
        result.lint_output = lint_result.get("output", "")
        self._process_lint_result(lint_result, project_type, result)

    def _run_tests_in_container(
        self, container_name: str, test_command: str, cmd_prefix: str,
        repo_path: Path, project_type: str, result: ValidationResult
    ) -> None:
        """Run test command in container and update result."""
        full_cmd = f"{cmd_prefix}{
            test_command}" if cmd_prefix else test_command

        logger.info(f"Running tests: {full_cmd}")
        docker_cmd = f'docker exec {container_name} sh -c "{full_cmd}"'
        test_result = self._run_command(docker_cmd, repo_path, timeout=600)
        result.test_command = docker_cmd
        result.test_output = test_result.get("output", "")
        self._process_test_result(test_result, project_type, result)

    def _process_lint_result(
        self, lint_result: dict, project_type: str, result: ValidationResult, docker_label: str = ""
    ) -> None:
        """Process lint result and update ValidationResult."""
        logger.info(f"Lint result: exit={lint_result['returncode']}, "
                    f"output_len={len(result.lint_output)}")
        if lint_result["returncode"] != 0:
            logger.warning(f"Lint output: {result.lint_output[:1000]}")
            result.success = False
            result.lint_errors = self._parse_lint_errors(
                result.lint_output, project_type)
            logger.info(f"Parsed {len(result.lint_errors)} lint errors")
            if not result.lint_errors:
                msg = f"Linter failed{docker_label}. Output: {
                    result.lint_output[:500]}"
                result.lint_errors = [LintError(
                    file_path="unknown", line=0, column=0, message=msg, rule="lint-failure",
                )]
        else:
            logger.info("Lint passed")

    def _process_test_result(
        self, test_result: dict, project_type: str, result: ValidationResult, docker_label: str = ""
    ) -> None:
        """Process test result and update ValidationResult."""
        logger.info(f"Test result: exit={test_result['returncode']}, "
                    f"output_len={len(result.test_output)}")
        if test_result["returncode"] != 0:
            logger.warning(f"Test output: {result.test_output[:1000]}")
            result.success = False
            result.test_errors = self._parse_test_errors(
                result.test_output, project_type)
            logger.info(f"Parsed {len(result.test_errors)} test errors")
            if not result.test_errors:
                result.test_errors = [TestError(
                    test_name="unknown", file_path=None,
                    message=f"Tests failed{docker_label}",
                    traceback=result.test_output[-1500:],
                )]
        else:
            logger.info("Tests passed")

    def _validate_with_generic_container(self, repo_path: Path, commands: ProjectCommands) -> Optional[ValidationResult]:
        """
        Run validation in a generic container using docker cp (for Docker-in-Docker compatibility).

        This approach:
        1. Creates a container with the right image
        2. Copies code into the container using docker cp
        3. Installs dependencies and runs lint/test
        4. Cleans up the container
        """
        result = ValidationResult(success=True)

        project_type = commands.project_type or "javascript"
        image = self._get_docker_image_for_project(project_type)
        logger.info(f"Using generic container for validation: {image}")

        # Create missing config files (.env, etc.)
        created_files = self._create_missing_env_files(repo_path)
        if created_files:
            logger.info(f"Created config files: {created_files}")

        # Get install command and convert npm commands to correct package manager
        install_cmd = self._get_install_command(project_type, repo_path)
        lint_command = self._convert_npm_command(
            commands.lint_command, repo_path) if commands.lint_command else None
        test_command = self._convert_npm_command(
            commands.test_command, repo_path) if commands.test_command else None

        # For pnpm/yarn we need to install them first in alpine
        pm = self._detect_js_package_manager(repo_path)
        pm_install = ""
        if project_type in ("javascript", "typescript"):
            if pm == "pnpm":
                pm_install = "npm install -g pnpm && "
            elif pm == "yarn":
                pm_install = "npm install -g yarn && "

        # Create a unique container name
        import hashlib
        container_name = f"validation-{hashlib.md5(
            str(repo_path).encode()).hexdigest()[:8]}"

        # Remove any existing container with same name
        self._run_command(
            f'docker rm -f {container_name}', repo_path, timeout=30)

        # Create container with working directory /app
        create_result = self._run_command(
            f'docker create --name {container_name} -w /app {image} sleep infinity',
            repo_path, timeout=60
        )
        if create_result["returncode"] != 0:
            logger.error(f"Failed to create container: {
                         create_result['output']}")
            return None

        try:
            # Copy code into container
            logger.info("Copying code into container...")
            copy_result = self._run_command(
                f'docker cp "{repo_path}/." {container_name}:/app/',
                repo_path, timeout=120
            )
            if copy_result["returncode"] != 0:
                logger.error(f"Failed to copy code: {copy_result['output']}")
                return None

            # Start the container
            start_result = self._run_command(
                f'docker start {container_name}',
                repo_path, timeout=30
            )
            if start_result["returncode"] != 0:
                logger.error(f"Failed to start container: {
                             start_result['output']}")
                return None

            logger.info(f"Container {container_name} started")

            # Run lint if available
            if lint_command:
                self._run_lint_in_container(
                    container_name, lint_command, install_cmd,
                    pm_install, repo_path, project_type, result
                )

            # Run tests if available (reuse installed dependencies)
            if test_command:
                already_installed = bool(lint_command and result.lint_output)
                if already_installed:
                    cmd_prefix = ""
                elif install_cmd:
                    cmd_prefix = f"{pm_install}{install_cmd} && "
                else:
                    cmd_prefix = pm_install
                self._run_tests_in_container(
                    container_name, test_command, cmd_prefix,
                    repo_path, project_type, result
                )

            logger.info(f"Validation complete: success={result.success}, "
                        f"lint_errors={len(result.lint_errors)}, test_errors={len(result.test_errors)}")
            return result

        finally:
            # Cleanup container
            logger.info(f"Cleaning up container {container_name}")
            self._run_command(
                f'docker rm -f {container_name}', repo_path, timeout=30)

    def _validate_with_compose(self, repo_path: Path, commands: ProjectCommands, result: ValidationResult) -> Optional[ValidationResult]:
        """Run validation using docker-compose."""
        logger.info("Using docker-compose for validation")

        # Build the containers (with --no-cache to ensure fresh build)
        build_result = self._run_command(
            "docker compose build --no-cache", repo_path, timeout=600)
        if build_result["returncode"] != 0:
            logger.error(f"docker compose build failed: {
                         build_result['output'][:500]}")
            return None

        service = commands.docker_service_name or "app"

        # Get install command for this project type
        install_cmd = self._get_install_command(
            commands.project_type, repo_path)

        # Convert npm commands to the correct package manager (yarn/pnpm)
        lint_command = self._convert_npm_command(
            commands.lint_command, repo_path) if commands.lint_command else None
        test_command = self._convert_npm_command(
            commands.test_command, repo_path) if commands.test_command else None

        # Run lint if available (chain install + lint in single container)
        if lint_command:
            if install_cmd:
                full_cmd = f"sh -c '{install_cmd} && {lint_command}'"
                logger.info(f"Running in docker: {
                            install_cmd} && {lint_command}")
            else:
                full_cmd = lint_command
                logger.info(f"Running linter in docker: {lint_command}")

            lint_cmd = f"docker compose run --rm {service} {full_cmd}"
            lint_result = self._run_command(lint_cmd, repo_path, timeout=600)
            result.lint_command = lint_cmd
            result.lint_output = lint_result.get("output", "")
            self._process_lint_result(
                lint_result, commands.project_type, result, " in Docker")

        # Run tests if available (chain install + test in single container)
        if test_command:
            if install_cmd:
                full_cmd = f"sh -c '{install_cmd} && {test_command}'"
                logger.info(f"Running in docker: {
                            install_cmd} && {test_command}")
            else:
                full_cmd = test_command
                logger.info(f"Running tests in docker: {test_command}")

            test_cmd = f"docker compose run --rm {service} {full_cmd}"
            test_result = self._run_command(test_cmd, repo_path, timeout=600)
            result.test_command = test_cmd
            result.test_output = test_result.get("output", "")
            self._process_test_result(
                test_result, commands.project_type, result, " in Docker")

        # Cleanup
        self._run_command("docker compose down", repo_path, timeout=60)

        logger.info(f"Docker compose validation complete: success={result.success}, "
                    f"lint_errors={len(result.lint_errors)}, test_errors={len(result.test_errors)}")
        return result

    def _validate_with_dockerfile(self, repo_path: Path, commands: ProjectCommands, result: ValidationResult) -> Optional[ValidationResult]:
        """Run validation by building and running Dockerfile."""
        logger.info("Using Dockerfile for validation")

        # Generate a unique image name
        import hashlib
        repo_hash = hashlib.md5(str(repo_path).encode()).hexdigest()[:8]
        image_name = f"coding-agent-validation-{repo_hash}"

        # Build the image (with --no-cache to ensure fresh build)
        logger.info(f"Building Docker image: {image_name}")
        build_result = self._run_command(
            f"docker build --no-cache -t {image_name} .", repo_path, timeout=600)
        if build_result["returncode"] != 0:
            logger.error(f"Docker build failed: {
                         build_result['output'][:500]}")
            return None

        # Get install command for this project type
        install_cmd = self._get_install_command(
            commands.project_type, repo_path)

        # Convert npm commands to the correct package manager (yarn/pnpm)
        lint_command = self._convert_npm_command(
            commands.lint_command, repo_path) if commands.lint_command else None
        test_command = self._convert_npm_command(
            commands.test_command, repo_path) if commands.test_command else None

        try:
            # Run lint if available (with dependencies install)
            if lint_command:
                if install_cmd:
                    full_cmd = f"sh -c '{install_cmd} && {lint_command}'"
                    logger.info(f"Running in docker: {
                                install_cmd} && {lint_command}")
                else:
                    full_cmd = lint_command
                    logger.info(f"Running linter in docker: {lint_command}")

                lint_cmd = f"docker run --rm {image_name} {full_cmd}"
                lint_result = self._run_command(
                    lint_cmd, repo_path, timeout=300)
                result.lint_command = lint_cmd
                result.lint_output = lint_result.get("output", "")
                self._process_lint_result(
                    lint_result, commands.project_type, result, " in Docker")

            # Run tests if available (with dependencies install)
            if test_command:
                if install_cmd:
                    full_cmd = f"sh -c '{install_cmd} && {test_command}'"
                    logger.info(f"Running in docker: {
                                install_cmd} && {test_command}")
                else:
                    full_cmd = test_command
                    logger.info(f"Running tests in docker: {test_command}")

                test_cmd = f"docker run --rm {image_name} {full_cmd}"
                test_result = self._run_command(
                    test_cmd, repo_path, timeout=600)
                result.test_command = test_cmd
                result.test_output = test_result.get("output", "")
                self._process_test_result(
                    test_result, commands.project_type, result, " in Docker")

        finally:
            # Cleanup - remove the image
            self._run_command(
                f"docker rmi {image_name}", repo_path, timeout=60)

        logger.info(f"Dockerfile validation complete: success={result.success}, "
                    f"lint_errors={len(result.lint_errors)}, test_errors={len(result.test_errors)}")
        return result

    def _detect_js_package_manager(self, repo_path: Path) -> str:
        """Detect which JavaScript package manager the project uses."""
        if (repo_path / "yarn.lock").exists():
            return "yarn"
        if (repo_path / "pnpm-lock.yaml").exists():
            return "pnpm"
        # Default to npm
        return "npm"

    def _get_install_command(self, project_type: Optional[str], repo_path: Path) -> Optional[str]:
        """Get the appropriate install command for the project type."""
        if not project_type:
            return None

        # Check for specific files to determine install command
        if project_type in ("javascript", "typescript"):
            pm = self._detect_js_package_manager(repo_path)
            return f"{pm} install"
        if project_type == "python":
            if (repo_path / "pyproject.toml").exists():
                return "pip install -e ."
            if (repo_path / "requirements.txt").exists():
                return "pip install -r requirements.txt"
            if (repo_path / "setup.py").exists():
                return "pip install -e ."
            return "pip install -r requirements.txt"
        if project_type == "go":
            return "go mod download"
        if project_type == "rust":
            return "cargo fetch"

        return None

    def _convert_npm_command(self, command: str, repo_path: Path) -> str:
        """Convert npm command to the appropriate package manager."""
        if not command:
            return command

        pm = self._detect_js_package_manager(repo_path)
        if pm == "npm":
            return command

        # Convert npm commands to yarn/pnpm equivalents
        if command.startswith("npm run "):
            script = command[8:]  # Remove "npm run "
            return f"{pm} run {script}"
        if command.startswith("npm test"):
            return f"{pm} test"
        if command == "npm install":
            return f"{pm} install"

        return command

    def _is_valid_file_path(self, file_path: Optional[str]) -> bool:
        """Check if a string looks like a valid file path."""
        if not file_path:
            return False
        if file_path == "unknown":
            return False

        # Filter out Docker log timestamps and other garbage
        invalid_patterns = [
            'time=',      # Docker log timestamp
            'level=',     # Docker log level
            'msg=',       # Docker log message
            '\\x',        # Escape sequences
            '\x00',       # Null bytes
            '<',          # HTML/XML tags
            '>',
        ]
        for pattern in invalid_patterns:
            if pattern in file_path:
                return False

        # Must look like a file path (has extension or is in a directory)
        if '/' not in file_path and '.' not in file_path:
            return False

        # Sanity check on length
        if len(file_path) > 500:
            return False

        return True

    def _run_command(self, command: str, cwd: Path, timeout: int = 300) -> dict:
        """Run a shell command."""
        import time
        start_time = time.time()
        logger.debug(f"Running command: {command} in {cwd}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            elapsed = time.time() - start_time
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            # Log with command name for clarity
            cmd_short = command[:60] + "..." if len(command) > 60 else command
            logger.info(f"[{cmd_short}] completed in {
                        elapsed:.1f}s, exit={result.returncode}")
            if result.returncode != 0:
                logger.debug(f"Command output (first 500 chars): {
                             output[:500]}")

            return {
                "returncode": result.returncode,
                "output": output,
            }
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            logger.error(f"Command timed out after {elapsed:.1f}s")
            return {
                "returncode": -1,
                "output": f"Command timed out after {timeout}s",
            }
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Command failed after {elapsed:.1f}s: {e}")
            return {
                "returncode": -1,
                "output": str(e),
            }

    def _parse_lint_errors(self, output: str, project_type: str) -> list[LintError]:
        """Parse linter output into structured errors."""
        errors = []

        # Filter out Docker log lines
        filtered_lines = [
            line for line in output.split('\n')
            if not self._is_docker_log_line(line)
        ]
        filtered_output = '\n'.join(filtered_lines)

        if project_type == "python":
            # Ruff/flake8 format: path:line:col: code message
            pattern = r'^(.+?):(\d+):(\d+): (\w+) (.+)$'
            for line in filtered_lines:
                match = re.match(pattern, line)
                if match and self._is_valid_file_path(match.group(1)):
                    errors.append(LintError(
                        file_path=match.group(1),
                        line=int(match.group(2)),
                        column=int(match.group(3)),
                        rule=match.group(4),
                        message=match.group(5),
                    ))

        elif project_type == "javascript":
            # ESLint format: path:line:col: message rule
            pattern = r'^(.+?):(\d+):(\d+): (.+?) \[(.+?)\]$'
            for line in filtered_lines:
                match = re.match(pattern, line.strip())
                if match and self._is_valid_file_path(match.group(1)):
                    errors.append(LintError(
                        file_path=match.group(1),
                        line=int(match.group(2)),
                        column=int(match.group(3)),
                        message=match.group(4),
                        rule=match.group(5),
                    ))

        # Fallback: just extract file:line patterns
        if not errors:
            pattern = r'^(.+?):(\d+)'
            for line in filtered_lines:
                if 'error' in line.lower() or 'warning' in line.lower():
                    match = re.match(pattern, line)
                    if match and self._is_valid_file_path(match.group(1)):
                        errors.append(LintError(
                            file_path=match.group(1),
                            line=int(match.group(2)),
                            column=0,
                            message=line,
                        ))

        return errors[:50]  # Limit to 50 errors

    def _is_docker_log_line(self, line: str) -> bool:
        """Check if a line is a Docker log line that should be filtered."""
        docker_patterns = [
            'time="',
            'level=',
            'msg="',
            'docker',
            'container',
            'Pulling from',
            'Digest:',
            'Status:',
            'latest:',
            '----->',
            'Step ',
            'Successfully built',
            'Successfully tagged',
        ]
        line_lower = line.lower()
        return any(pattern.lower() in line_lower for pattern in docker_patterns)

    def _parse_test_errors(self, output: str, project_type: str) -> list[TestError]:
        """Parse test output into structured errors."""
        errors = []

        # Filter out Docker log lines
        filtered_lines = [
            line for line in output.split('\n')
            if not self._is_docker_log_line(line)
        ]

        if project_type == "python":
            # Pytest format: FAILED test_file.py::test_name - message
            pattern = r'FAILED (.+?)::(.+?) - (.+)'
            for line in filtered_lines:
                match = re.search(pattern, line)
                if match and self._is_valid_file_path(match.group(1)):
                    errors.append(TestError(
                        file_path=match.group(1),
                        test_name=match.group(2),
                        message=match.group(3),
                    ))

            # Also look for assertion errors
            if not errors and 'AssertionError' in output:
                errors.append(TestError(
                    test_name="Unknown",
                    file_path=None,
                    message="AssertionError in tests",
                    traceback=output[-1000:],
                ))

        elif project_type == "javascript":
            # Jest format: FAIL path - test name
            pattern = r'FAIL\s+(.+)'
            for line in filtered_lines:
                match = re.match(pattern, line)
                if match:
                    file_path = match.group(1).strip()
                    if self._is_valid_file_path(file_path):
                        errors.append(TestError(
                            file_path=file_path,
                            test_name="Unknown",
                            message="Test failed",
                        ))

        # Fallback
        if not errors and ('FAILED' in output or 'FAIL' in output or 'Error' in output):
            errors.append(TestError(
                test_name="Unknown",
                file_path=None,
                message="Test failure detected",
                traceback=output[-1500:],
            ))

        return errors[:20]
