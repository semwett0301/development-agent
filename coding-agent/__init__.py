"""
Coding Agent - Automated code generation from GitHub issues.

This agent processes GitHub issues and automatically:
1. Analyzes and summarizes the issue
2. Creates an action plan
3. Searches for relevant code using RAG
4. Generates code changes
5. Runs linter and tests
6. Creates a pull request

Usage:
    from coding_agent import CodingAgent, run_agent
    
    # Using the convenience function
    result = run_agent(
        owner="org",
        repo="repo",
        issue_number=123,
    )
    
    # Or using the agent class directly
    agent = CodingAgent()
    issue = agent.github_client.get_issue("org", "repo", 123)
    result = agent.process_issue(issue)
"""
from .main import CodingAgent, AgentResult, run_agent
from .config import AgentConfig, load_config
from .models import Issue, IssueSummary, ActionPlan

__version__ = "0.1.0"

__all__ = [
    "CodingAgent",
    "AgentResult",
    "run_agent",
    "AgentConfig",
    "load_config",
    "Issue",
    "IssueSummary",
    "ActionPlan",
]
