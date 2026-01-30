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

## Services

| Service          | Port   | Description                               |
|------------------|--------|-------------------------------------------|
| coding-agent     | `8001` | Agent for code generation and transformation |
| indexer-service   | `8002` | Service for indexing and retrieval         |
| proxy-service     | `8003` | Gateway and routing service               |
| reviewer-agent    | `8004` | Agent for automated code review           |

## Getting Started

### Prerequisites

- Python 3.12+
- Docker & Docker Compose

### Setup

```bash
cp .env.example .env
make setup
```

This will install all dependencies, dev tools, and configure git hooks (pre-commit runs lint + tests).

### Infrastructure

Start the services:

```bash
docker compose up -d
```

This will start:

| Service    | Port   | Description            |
|------------|--------|------------------------|
| PostgreSQL | `5432` | Primary database       |
| Kafka      | `9092` | Message broker (KRaft) |
| Chroma     | `8000` | Vector database        |

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