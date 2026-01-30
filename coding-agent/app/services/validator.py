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
            logger.info("Using Docker for validation - dependencies will be installed during build")
            return True

        if not commands.install_command:
            logger.info("No install command found, skipping dependency installation")
            return True

        logger.info(f"Installing dependencies: {commands.install_command}")
        result = self._run_command(commands.install_command, repo_path, timeout=600)

        if result["returncode"] == 0:
            logger.info("Dependencies installed successfully")
            return True
        elif result["returncode"] == 127:
            logger.warning(f"Install command not found (exit 127): {commands.install_command}")
            return True  # Skip, don't fail
        else:
            logger.error(f"Dependency installation failed with exit code {result['returncode']}")
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
            logger.warning("Docker validation failed, falling back to direct commands")

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
                    output_snippet = result.lint_output[:500] if result.lint_output.strip() else "(no output)"
                    result.lint_errors = [LintError(
                        file_path="unknown",
                        line=0,
                        column=0,
                        message=f"Linter failed with exit code {lint_result['returncode']}. Output: {output_snippet}",
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
                    traceback = result.test_output[-1500:] if result.test_output.strip() else "(no output)"
                    result.test_errors = [TestError(
                        test_name="unknown",
                        file_path=None,
                        message=f"Tests failed with exit code {test_result['returncode']}",
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

        # Get files with errors (skip "unknown" placeholder)
        error_files = set()
        for err in validation_result.lint_errors:
            if err.file_path and err.file_path != "unknown":
                error_files.add(err.file_path)
        for err in validation_result.test_errors:
            if err.file_path and err.file_path != "unknown":
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
            logger.warning("No file contents available for fixing - cannot generate fixes")
            # Try to extract useful info for unfixable list
            unfixable_msgs = []
            if validation_result.lint_output:
                unfixable_msgs.append(f"Lint errors: {validation_result.lint_output[:500]}")
            if validation_result.test_output:
                unfixable_msgs.append(f"Test errors: {validation_result.test_output[:500]}")
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
        Run validation inside Docker container.

        Returns ValidationResult if Docker validation worked, None if should fallback.
        """
        # Check if Docker is available
        docker_check = self._run_command("docker --version", repo_path, timeout=10)
        if docker_check["returncode"] != 0:
            logger.warning("Docker CLI not available")
            return None

        result = ValidationResult(success=True)

        if commands.has_docker_compose:
            return self._validate_with_compose(repo_path, commands, result)
        elif commands.has_dockerfile:
            return self._validate_with_dockerfile(repo_path, commands, result)

        return None

    def _validate_with_compose(self, repo_path: Path, commands: ProjectCommands, result: ValidationResult) -> Optional[ValidationResult]:
        """Run validation using docker-compose."""
        logger.info("Using docker-compose for validation")

        # Build the containers
        build_result = self._run_command("docker compose build", repo_path, timeout=600)
        if build_result["returncode"] != 0:
            logger.error(f"docker compose build failed: {build_result['output'][:500]}")
            return None

        service = commands.docker_service_name or "app"

        # Run lint if available
        if commands.lint_command:
            logger.info(f"Running linter in docker: {commands.lint_command}")
            lint_cmd = f"docker compose run --rm {service} {commands.lint_command}"
            lint_result = self._run_command(lint_cmd, repo_path, timeout=300)
            result.lint_command = lint_cmd
            result.lint_output = lint_result.get("output", "")

            if lint_result["returncode"] != 0:
                result.success = False
                result.lint_errors = self._parse_lint_errors(result.lint_output, commands.project_type)
                if not result.lint_errors:
                    result.lint_errors = [LintError(
                        file_path="unknown", line=0, column=0,
                        message=f"Linter failed in Docker. Output: {result.lint_output[:500]}",
                        rule="docker-lint-failure",
                    )]

        # Run tests if available
        if commands.test_command:
            logger.info(f"Running tests in docker: {commands.test_command}")
            test_cmd = f"docker compose run --rm {service} {commands.test_command}"
            test_result = self._run_command(test_cmd, repo_path, timeout=600)
            result.test_command = test_cmd
            result.test_output = test_result.get("output", "")

            if test_result["returncode"] != 0:
                result.success = False
                result.test_errors = self._parse_test_errors(result.test_output, commands.project_type)
                if not result.test_errors:
                    result.test_errors = [TestError(
                        test_name="unknown", file_path=None,
                        message=f"Tests failed in Docker",
                        traceback=result.test_output[-1500:],
                    )]

        # Cleanup
        self._run_command("docker compose down", repo_path, timeout=60)

        return result

    def _validate_with_dockerfile(self, repo_path: Path, commands: ProjectCommands, result: ValidationResult) -> Optional[ValidationResult]:
        """Run validation by building and running Dockerfile."""
        logger.info("Using Dockerfile for validation")

        # Generate a unique image name
        import hashlib
        repo_hash = hashlib.md5(str(repo_path).encode()).hexdigest()[:8]
        image_name = f"coding-agent-validation-{repo_hash}"

        # Build the image
        logger.info(f"Building Docker image: {image_name}")
        build_result = self._run_command(f"docker build -t {image_name} .", repo_path, timeout=600)
        if build_result["returncode"] != 0:
            logger.error(f"Docker build failed: {build_result['output'][:500]}")
            return None

        try:
            # Run lint if available
            if commands.lint_command:
                logger.info(f"Running linter in docker: {commands.lint_command}")
                lint_cmd = f"docker run --rm {image_name} {commands.lint_command}"
                lint_result = self._run_command(lint_cmd, repo_path, timeout=300)
                result.lint_command = lint_cmd
                result.lint_output = lint_result.get("output", "")

                if lint_result["returncode"] != 0:
                    result.success = False
                    result.lint_errors = self._parse_lint_errors(result.lint_output, commands.project_type)
                    if not result.lint_errors:
                        result.lint_errors = [LintError(
                            file_path="unknown", line=0, column=0,
                            message=f"Linter failed in Docker. Output: {result.lint_output[:500]}",
                            rule="docker-lint-failure",
                        )]

            # Run tests if available
            if commands.test_command:
                logger.info(f"Running tests in docker: {commands.test_command}")
                test_cmd = f"docker run --rm {image_name} {commands.test_command}"
                test_result = self._run_command(test_cmd, repo_path, timeout=600)
                result.test_command = test_cmd
                result.test_output = test_result.get("output", "")

                if test_result["returncode"] != 0:
                    result.success = False
                    result.test_errors = self._parse_test_errors(result.test_output, commands.project_type)
                    if not result.test_errors:
                        result.test_errors = [TestError(
                            test_name="unknown", file_path=None,
                            message=f"Tests failed in Docker",
                            traceback=result.test_output[-1500:],
                        )]

        finally:
            # Cleanup - remove the image
            self._run_command(f"docker rmi {image_name}", repo_path, timeout=60)

        return result

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

            logger.info(f"Command completed in {elapsed:.1f}s with exit code {result.returncode}")
            if result.returncode != 0:
                logger.debug(f"Command output (first 500 chars): {output[:500]}")

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

        if project_type == "python":
            # Ruff/flake8 format: path:line:col: code message
            pattern = r'^(.+?):(\d+):(\d+): (\w+) (.+)$'
            for line in output.split('\n'):
                match = re.match(pattern, line)
                if match:
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
            for line in output.split('\n'):
                match = re.match(pattern, line.strip())
                if match:
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
            for line in output.split('\n'):
                if 'error' in line.lower() or 'warning' in line.lower():
                    match = re.match(pattern, line)
                    if match:
                        errors.append(LintError(
                            file_path=match.group(1),
                            line=int(match.group(2)),
                            column=0,
                            message=line,
                        ))

        return errors[:50]  # Limit to 50 errors

    def _parse_test_errors(self, output: str, project_type: str) -> list[TestError]:
        """Parse test output into structured errors."""
        errors = []

        if project_type == "python":
            # Pytest format: FAILED test_file.py::test_name - message
            pattern = r'FAILED (.+?)::(.+?) - (.+)'
            for line in output.split('\n'):
                match = re.search(pattern, line)
                if match:
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
            for line in output.split('\n'):
                match = re.match(pattern, line)
                if match:
                    errors.append(TestError(
                        file_path=match.group(1).strip(),
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
