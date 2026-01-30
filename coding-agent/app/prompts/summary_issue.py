# Summarization
SUMMARY_ISSUE_SYSTEM = """You are a senior software engineer analyzing a GitHub issue.

Your task is to:
1. Summarize the issue concisely
2. Extract clear requirements
3. List acceptance criteria
4. Identify affected areas of the codebase
5. Come up with a scope for the issue (e.g. "frontend", "backend", "database", "performance", "security", "analytics", "testing", "refactoring", "documentation")"""

# Human prompt template (with placeholders for LangChain)
SUMMARY_ISSUE_HUMAN = """## Issue Information

**Title:** {title}

**Body:**
{body}

## Instructions

Analyze the issue and extract the key information.

Focus on:
- Being specific and actionable
- Extracting implicit requirements
- Identifying edge cases mentioned or implied
- Noting any constraints or considerations

{format_instructions}"""
