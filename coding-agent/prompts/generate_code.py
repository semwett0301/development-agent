# Code generation prompts
GENERATE_CODE_SYSTEM = """You are a senior software engineer implementing a specific change.
Generate clean, well-documented code following project conventions.
Write code only in the same language and stack as the project (see Project Conventions: TypeScript/JavaScript vs Python). Do not mix languages."""

GENERATE_CODE_HUMAN = """## Task
{step_description}

## Details
{step_details}

## Target File
**Path:** {file_path}
**Action:** {action}

## Current File Content
{current_content}

## Related Code Context
{related_context}

## Project Conventions
{conventions}

## Instructions

Generate the code change needed for this task.

{action_instructions}

Rules:
1. Follow existing code style and conventions
2. Add appropriate docstrings and comments
3. Handle edge cases and errors properly
4. Use proper typing/type hints
5. Keep changes focused on the task
6. Use conventional commit format for commit message

For "replace" edit_type: provide the complete new file content
For "insert" edit_type: provide only the code to insert

{format_instructions}"""

ACTION_INSTRUCTIONS = {
    "create": """
You are CREATING a new file. Provide the complete file content including:
- Appropriate imports
- Docstrings for the module
- All required code
- Proper formatting
""",
    "modify": """
You are MODIFYING an existing file. Analyze the current content and provide:
- The COMPLETE new file content with your changes applied
- Preserve existing code that shouldn't change
- Integrate your changes seamlessly
""",
    "delete": """
You are DELETING this file. Confirm the deletion by setting new_content to null.
""",
}
