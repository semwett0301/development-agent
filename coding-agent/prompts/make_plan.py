# Plan creation after summary
MAKE_PLAN_SYSTEM = """You are a senior software engineer creating an implementation plan.
Create a detailed action plan with specific file changes needed to implement an issue.
All file paths and code must match the project language and stack (e.g. .ts/.tsx for TypeScript, .py for Python)."""

MAKE_PLAN_HUMAN = """## Project language and stack
{project_language}

## Issue Summary
{summary}

## Requirements
{requirements}

## Acceptance Criteria
{acceptance_criteria}

## Codebase Context
The following code snippets are relevant to this issue:

{code_context}

## Project Structure
{project_structure}

## Instructions

Create a detailed action plan with specific file changes needed to implement this issue.
Use only the project language and file extensions above (e.g. do not suggest .py files for a TypeScript project).

Action types:
- "create": Create a new file
- "modify": Modify an existing file  
- "delete": Delete a file

Rules:
1. Be specific about what code to add/change
2. Include function signatures and key logic in details
3. Order steps logically (dependencies first)
4. Include test file modifications
5. Keep changes minimal and focused
6. All file_path values must use the correct extensions for this project

{format_instructions}"""
