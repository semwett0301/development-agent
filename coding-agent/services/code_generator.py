import logging
from pathlib import Path
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

from ..models import PlanStep, StepAction, CodeChange, FileEdit, EditType, CodeGenerationOutput, CodeFixesOutput
from ..chains import create_generate_chain, create_fix_chain
from ..chains.generate_code import get_action_instructions

logger = logging.getLogger(__name__)


class CodeGenerator:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self._fix_chain: Optional[Runnable] = None

    @property
    def fix_chain(self) -> Runnable:
        if self._fix_chain is None:
            self._fix_chain = create_fix_chain(self.llm)
        return self._fix_chain

    def generate_for_step(self, step: PlanStep, current_content: Optional[str], related_context: str, conventions: str, repo_path: Path) -> CodeChange:
        """Generate code changes for a plan step.
        
        Input:
            step: The plan step to implement
            current_content: Current file content (None if creating)
            related_context: Related code from RAG
            conventions: Project conventions
            repo_path: Path to repository
        """
        logger.info(f"Generating code for step {step.id}: {step.description}")
        action_instructions = get_action_instructions(step.action.value)
        result: CodeGenerationOutput = self.generate_chain.invoke({
            "step_description": step.description,
            "step_details": step.details or "No additional details",
            "file_path": step.file_path, 
            "action": step.action.value,
            "current_content": current_content or "(file does not exist)",
            "related_context": related_context or "No related context available",
            "conventions": conventions,
            "action_instructions": action_instructions,
        })

        edit = FileEdit(
            file_path=result.file_path,
            edit_type=EditType(result.edit_type) if result.edit_type != "delete" else EditType.DELETE,
            new_content=result.new_content,
            old_content=current_content,
        )

        return CodeChange(
            step_id=step.id,
            edits=[edit],
            commit_message=result.commit_message,
            description=result.explanation,
        )

    def fix_errors(self, error_summary: str, lint_output: str, test_output: str, files_with_errors: list[str], file_contents: dict[str, str]) -> CodeFixesOutput:
        """Fix linter errors and test failures.
        
        Input:
            error_summary: Summary of all errors
            lint_output: Raw lint command output
            test_output: Raw test command output
            files_with_errors: List of file paths with errors
            file_contents: Dict mapping file path to current content
        """
        result: CodeFixesOutput = self.fix_chain.invoke({
            "error_summary": error_summary,
            "lint_output": lint_output or "No lint errors",
            "test_output": test_output or "No test failures",
            "files_with_errors": "\n".join(f"- {f}" for f in files_with_errors),
            "file_contents": "\n\n".join(formatted_contents),
        })

        return result

    def apply_changes(self, changes: CodeChange, repo_path: Path) -> list[str]:
        """
        Apply code changes to the repository.
        
        Input:
            changes: The code changes to apply
            repo_path: Path to repository
            
        Output:
            List of modified file paths
        """
        modified_files = []

        for edit in changes.edits:
            file_path = repo_path / edit.file_path
            
            logger.info(f"Applying {edit.edit_type.value} to {edit.file_path}")

            if edit.edit_type == EditType.DELETE:
                if file_path.exists():
                    file_path.unlink()
                    modified_files.append(edit.file_path)
            else:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                
                if edit.new_content is not None:
                    file_path.write_text(edit.new_content, encoding="utf-8")
                    modified_files.append(edit.file_path)

        return modified_files

    def apply_fixes(self, fixes: CodeFixesOutput, repo_path: Path) -> list[str]:
        """
        Apply code fixes to the repository.
        
        Input:
            fixes: The code fixes to apply
            repo_path: Path to repository
            
        Output:
            List of modified file paths
        """
        modified_files = []

        for fix in fixes.fixes:
            file_path = repo_path / fix.file_path
            
            logger.info(f"Applying fix to {fix.file_path}: {', '.join(fix.issues_fixed)}")

            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_path.write_text(fix.new_content, encoding="utf-8")
            modified_files.append(fix.file_path)

        return modified_files

    def get_project_conventions(self, repo_path: Path) -> str:
        """
        Extract project conventions from config files.
        
        Input:
            repo_path: Path to repository
            
        Output:
            Formatted conventions string
        """
        conventions = []

        pyproject = repo_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text()
                conventions.append("## Python Project (pyproject.toml found)")
                
                if "[tool.ruff]" in content:
                    conventions.append("- Uses Ruff for linting")
                if "[tool.black]" in content:
                    conventions.append("- Uses Black for formatting")
                if "[tool.mypy]" in content:
                    conventions.append("- Uses MyPy for type checking")
                if "[tool.pytest]" in content:
                    conventions.append("- Uses Pytest for testing")
            except Exception as e:
                logger.debug(f"Could not read pyproject.toml: {e}")

        package_json = repo_path / "package.json"
        if package_json.exists():
            try:
                import json
                content = json.loads(package_json.read_text())
                conventions.append("## JavaScript/TypeScript Project (package.json found)")
                
                deps = content.get("devDependencies", {})
                if "eslint" in deps:
                    conventions.append("- Uses ESLint for linting")
                if "prettier" in deps:
                    conventions.append("- Uses Prettier for formatting")
                if "typescript" in deps:
                    conventions.append("- Uses TypeScript")
                if "jest" in deps:
                    conventions.append("- Uses Jest for testing")
                if "vitest" in deps:
                    conventions.append("- Uses Vitest for testing")
            except Exception as e:
                logger.debug(f"Could not read package.json: {e}")

        editorconfig = repo_path / ".editorconfig"
        if editorconfig.exists():
            conventions.append("- Has .editorconfig for editor settings")

        precommit = repo_path / ".pre-commit-config.yaml"
        if precommit.exists():
            conventions.append("- Uses pre-commit hooks")

        if not conventions:
            conventions.append("No specific conventions detected. Follow general best practices.")

        return "\n".join(conventions)

    def get_project_language(self, repo_path: Path) -> str:
        """
        Detect project language and stack from config files.
        Used so the agent writes code in the correct language (e.g. TypeScript, not Python).

        Args:
            repo_path: Path to repository root

        Returns:
            Short description like "TypeScript/JavaScript. Use .ts, .tsx for React, .ts for NestJS."
            or "Python. Use .py extensions."
        """
        import json

        # Python
        if (repo_path / "pyproject.toml").exists():
            return "Python. Use .py file extensions. Follow PEP 8 and project style."

        # JavaScript/TypeScript (monorepo or single app)
        package_json = repo_path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                name = data.get("name", "")
                # Turborepo / monorepo
                if "turbo" in data.get("devDependencies", {}):
                    stacks = []
                    apps = repo_path / "apps"
                    if apps.is_dir():
                        for app in apps.iterdir():
                            if (app / "package.json").is_file():
                                try:
                                    app_pkg = json.loads((app / "package.json").read_text())
                                    deps = {**app_pkg.get("dependencies", {}), **app_pkg.get("devDependencies", {})}
                                    if "react" in deps or "vite" in deps:
                                        stacks.append("React/Vite")
                                    elif "express" in deps or "fastify" in deps:
                                        stacks.append("Node/Express")
                                    elif "nest" in str(deps).lower() or "@nestjs" in deps:
                                        stacks.append("NestJS")
                                except Exception:
                                    pass
                    if stacks:
                        return f"TypeScript/JavaScript (monorepo: {', '.join(stacks)}). Use .ts, .tsx for React, .ts for backend. All file paths must use these extensions."
                    return "TypeScript/JavaScript. Use .ts, .tsx for React, .ts for backend. All file paths must use these extensions."
            except Exception:
                pass
            return "TypeScript/JavaScript. Use .ts, .tsx, .js extensions. All file paths must use these extensions."

        return "Infer from project structure and code context. Prefer the same language and extensions as existing files."
