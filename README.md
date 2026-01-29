# Development Agent

A multi-agent system with a microservices architecture for automating software development workflows.

## Project Structure

```
development-agent/
├── coding-agent/       # Agent for code generation and transformation
├── indexer-service/    # Service for indexing and retrieval
├── proxy-service/      # Gateway and routing service
├── reviewer-agent/     # Agent for automated code review
```

## Getting Started

> **Note:** The project is in its initial stage. Setup instructions will be added as services are implemented.

## Commit Convention

This project follows the [Conventional Commits](https://www.conventionalcommits.org/) specification.

### Format

```
<type>(<scope>): <subject>
```

### Types

| Type       | Description                                              |
|------------|----------------------------------------------------------|
| `feat`     | A new feature                                            |
| `fix`      | A bug fix                                                |
| `chore`    | Maintenance tasks (deps, CI, configs) with no code logic |
| `refactor` | Code change that neither fixes a bug nor adds a feature  |

### Scopes

| Scope      | Description          |
|------------|----------------------|
| `coding`   | coding-agent         |
| `indexer`  | indexer-service      |
| `proxy`    | proxy-service        |
| `reviewer` | reviewer-agent       |

Scope is optional and can be omitted for cross-cutting changes.

### Examples

```
feat(coding): add code generation endpoint
fix(proxy): resolve timeout on large payloads
chore: update dependencies
refactor(reviewer): extract scoring logic into separate module
```