# Documentation Standards

## API Endpoint Documentation Format

Every API endpoint must be documented with:

```python
@router.post(
    "/webhook",
    summary="Receive GitHub webhook",
    description="""
    Receives webhook events from GitHub and processes them asynchronously.

    The endpoint verifies the X-Hub-Signature-256 header using HMAC-SHA256.
    Events are persisted to the database before queuing for processing.
    Returns immediately with 200 to avoid GitHub webhook timeouts.
    """,
    response_description="Acknowledgment that webhook was received",
    responses={
        200: {"description": "Webhook received and queued for processing"},
        401: {"description": "Invalid signature"},
        422: {"description": "Invalid payload structure"},
    },
    tags=["webhooks"],
)
```

### OpenAPI/Swagger Standards
- Use `summary` for short descriptions (shown in endpoint list)
- Use `description` for detailed explanation
- Document all response codes (including errors)
- Use `tags` to group related endpoints
- Include example request/response bodies for complex endpoints

---

## README Structure Template

Every project README should follow this structure:

```markdown
# Project Name

> One-line description of what it does

## What It Does
[2-3 sentences for non-technical audience]

## Architecture
[ASCII diagram or image]

## Tech Stack
| Component | Technology |
|-----------|-----------|
| ...       | ...       |

## Quick Start
1. Clone the repo
2. Configure environment
3. Start services
4. Verify it works

## Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| ...      | ...         | Yes/No   | ...     |

## API Reference
[Links to Swagger UI or endpoint table]

## Development
[How to run tests, contribute]

## Deployment
[How to deploy to production]

## License
```

---

## Inline Comment Standards

### When to Comment
Comment when explaining WHY, not WHAT:
```python
# GitHub has a 65536 byte limit on PR diffs — truncate to avoid API errors
diff = pr_diff[:65000] if len(pr_diff) > 65000 else pr_diff

# Using compare_digest to prevent timing attacks on HMAC comparison
if not hmac.compare_digest(expected_sig, received_sig):
    raise HTTPException(status_code=401)
```

### When NOT to Comment
Don't comment the obvious:
```python
# Increment counter by 1
counter += 1  # This is self-explanatory

# Return the result
return result  # Never do this
```

### Docstring Format (Google Style)
```python
async def post_comment(self, repo: str, issue_number: int, body: str) -> dict:
    """Post a comment to a GitHub issue or pull request.

    Args:
        repo: Full repository name in "owner/repo" format.
        issue_number: The issue or PR number to comment on.
        body: The markdown-formatted comment body.

    Returns:
        The created comment object from GitHub API.

    Raises:
        httpx.HTTPStatusError: If GitHub API returns an error response.
        httpx.TimeoutException: If the request times out after retries.
    """
```

---

## Changelog Format (Keep a Changelog)

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2024-01-15

### Added
- Initial release of RepoGator
- GitHub webhook receiver with signature verification
- Requirements Agent for issue enrichment
- Code Review Agent for PR analysis
- Dark theme monitoring dashboard

### Changed
- N/A (initial release)

### Fixed
- N/A (initial release)

### Security
- HMAC-SHA256 webhook signature verification
- No secrets stored in code (all via environment variables)

## [0.1.0] - 2024-01-01

### Added
- Project skeleton
- Basic FastAPI setup
```

---

## Version Numbering

Use Semantic Versioning (semver): MAJOR.MINOR.PATCH

- **MAJOR**: Breaking changes (API incompatibility, removed features)
- **MINOR**: New features (backwards compatible)
- **PATCH**: Bug fixes (backwards compatible)

For pre-1.0 projects, use 0.MINOR.PATCH where MINOR breaking changes are allowed.
