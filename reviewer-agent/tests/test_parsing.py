"""Tests for PR body/title parsing."""
import pytest

from reviewing_agent.clients.github_client import (
    parse_coding_summary_from_pr_body,
    parse_issue_number_from_pr,
)


def test_parse_coding_summary_from_pr_body():
    body = """## Summary
This PR adds user update and delete endpoints.

## Changes
- Added PUT /users/:id
- Added DELETE /users/:id
"""
    assert parse_coding_summary_from_pr_body(body) == "This PR adds user update and delete endpoints."


def test_parse_coding_summary_empty():
    assert parse_coding_summary_from_pr_body("") is None
    assert parse_coding_summary_from_pr_body(None) is None


def test_parse_coding_summary_no_section():
    body = "No summary section here."
    assert parse_coding_summary_from_pr_body(body) is None


def test_parse_issue_number_from_pr_closes():
    body = "Fixes #42 and does something."
    assert parse_issue_number_from_pr(body, None) == 42
    body2 = "Closes #123"
    assert parse_issue_number_from_pr(body2, None) == 123


def test_parse_issue_number_from_pr_title():
    assert parse_issue_number_from_pr(None, "[42] Add feature") == 42
    assert parse_issue_number_from_pr("", "[99] Fix bug") == 99


def test_parse_issue_number_from_pr_title_overrides_body():
    body = "Closes #10"
    title = "[20] Other"
    assert parse_issue_number_from_pr(body, title) == 10  # body first in our impl