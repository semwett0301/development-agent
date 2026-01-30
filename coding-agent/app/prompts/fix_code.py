# Code erorrs and fixes
FIX_CODE_SYSTEM = """You are a senior software engineer fixing code issues.
Fix all linter errors and test failures while preserving functionality."""

FIX_CODE_HUMAN = """## Error Summary
{error_summary}

## Lint Output
```
{lint_output}
```

## Test Output
```
{test_output}
```

## Files With Errors
{files_with_errors}

## Current File Contents
{file_contents}

## Instructions

Fix all the linter errors and test failures shown above.

For each file that needs fixing, provide the corrected content.

Rules:
1. Fix ALL reported errors, not just some
2. Preserve the original intent and functionality
3. Don't introduce new issues
4. If a fix would change functionality, note it in unfixable
5. Handle each error systematically

Common fixes:
- Missing imports: Add required imports
- Type errors: Fix type annotations or add casts
- Unused variables: Remove or use them
- Missing docstrings: Add docstrings
- Formatting: Apply correct formatting
- Test failures: Fix assertions or test logic

{format_instructions}"""

# Lint errors
PARSE_LINT_ERRORS_PROMPT = """Extract lint errors from this output.

## Lint Output
```
{lint_output}
```

Respond with a JSON array of errors:

```json
[
    {{
        "file_path": "path/to/file.py",
        "line": 42,
        "column": 10,
        "message": "Error message",
        "rule": "rule-name",
        "severity": "error"
    }}
]
```

Only include actual errors, not warnings unless they block the build.
Respond ONLY with the JSON array.
"""

# Test errors
PARSE_TEST_ERRORS_PROMPT = """Extract test failures from this output.

## Test Output
```
{test_output}
```

Respond with a JSON array of failures:

```json
[
    {{
        "test_name": "test_function_name",
        "file_path": "path/to/test_file.py",
        "message": "Assertion error or failure message",
        "traceback": "Relevant traceback lines"
    }}
]
```

Only include actual test failures.
Respond ONLY with the JSON array.
"""
