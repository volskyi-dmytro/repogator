# Code Review Guidelines

## Security Checklist

### Injection Attacks
- [ ] SQL: Are all queries parameterized? No string interpolation in SQL
- [ ] Command injection: Is `os.system()`, `subprocess` used with user input? Use `shlex.quote()`
- [ ] SSRF: Does the app make HTTP requests to user-provided URLs without validation?
- [ ] Path traversal: Are file paths validated to prevent `../../etc/passwd` attacks?
- [ ] Template injection: Are user inputs ever passed to template engines unsanitized?

### Authentication & Authorization
- [ ] Are endpoints protected that should be?
- [ ] Is JWT/token validation correct? Check expiry, signature, claims
- [ ] Are passwords hashed with bcrypt/argon2? Never MD5/SHA1 for passwords
- [ ] Is there proper RBAC — does the code check if user can do X, not just if user is logged in?

### Secrets in Code
- [ ] No hardcoded API keys, passwords, or tokens
- [ ] No secrets in comments
- [ ] Environment variables used for all configuration
- [ ] `.env` files not committed (check .gitignore)

### Input Validation
- [ ] All user input validated at entry points
- [ ] File uploads: check MIME type AND extension, scan for malware if applicable
- [ ] Request size limits configured
- [ ] Rate limiting on public endpoints

---

## Python-Specific Patterns

### Async Safety
```python
# Bad: blocking call in async context
async def get_data():
    time.sleep(5)  # blocks the event loop!
    result = requests.get(url)  # sync HTTP in async!

# Good: async all the way
async def get_data():
    await asyncio.sleep(5)
    async with httpx.AsyncClient() as client:
        result = await client.get(url)
```

### Exception Handling
```python
# Bad: bare except, swallows all errors
try:
    do_something()
except:
    pass

# Bad: except Exception too broad, hides bugs
try:
    do_something()
except Exception:
    logger.error("Something failed")

# Good: specific exceptions, proper logging
try:
    result = await call_api()
except httpx.TimeoutException:
    logger.warning("API timeout, retrying", exc_info=True)
    raise
except httpx.HTTPStatusError as e:
    logger.error("API error", status_code=e.response.status_code)
    raise
```

### Type Hints
- All function signatures should have type hints (parameters + return type)
- Use `Optional[X]` or `X | None` for nullable values
- Use Pydantic models for validated data transfer objects
- Prefer `list[str]` over `List[str]` (Python 3.10+)

### Resource Management
```python
# Bad: resource leak
conn = await asyncpg.connect(...)
result = await conn.fetch(query)
# conn never closed if exception occurs

# Good: context manager
async with asyncpg.create_pool(...) as pool:
    async with pool.acquire() as conn:
        result = await conn.fetch(query)
```

---

## Performance Red Flags

### N+1 Query Problem
```python
# Bad: N+1 queries
users = await db.execute(select(User)).scalars().all()
for user in users:
    orders = await db.execute(select(Order).where(Order.user_id == user.id))
    # 1 query for users + N queries for orders

# Good: JOIN or eager loading
users_with_orders = await db.execute(
    select(User).options(selectinload(User.orders))
)
```

### Missing Database Indexes
- Foreign keys should always be indexed
- Columns used in WHERE clauses frequently should be indexed
- Composite indexes for multi-column WHERE conditions
- Check: does the query use `.filter()` on an un-indexed column?

### Sync Calls in Async Context
- `requests` library → use `httpx` with async client
- `time.sleep()` → use `asyncio.sleep()`
- Synchronous file I/O → use `aiofiles`
- CPU-bound work → use `asyncio.run_in_executor()`

### Memory Issues
- Large datasets: use generators/streaming instead of loading all into memory
- Unbounded caches without TTL or size limits
- Log aggregation accumulating in memory

---

## Test Coverage Expectations

### Minimum Coverage by Layer
| Layer | Coverage Target | What to Test |
|-------|----------------|--------------|
| API endpoints | 90%+ | Happy path, validation errors, auth failures |
| Business logic | 85%+ | All branches, edge cases, error paths |
| Data models | 70%+ | Validators, constraints, relationships |
| Infrastructure | 60%+ | Connection handling, retry logic |

### What to Test
- Happy path (the expected behavior)
- Error cases (what happens when things fail)
- Edge cases (empty input, null, boundary values)
- Security (auth required, injection attempts)
- Don't test: third-party library internals, language built-ins

### Test Quality Checklist
- [ ] Tests are independent (no shared state between tests)
- [ ] Mocks used for external services (DB, APIs, email)
- [ ] Tests have descriptive names: `test_webhook_returns_401_with_invalid_signature`
- [ ] No magic numbers — use named constants
- [ ] Assertions are specific (not just `assert result is not None`)

---

## PR Size Guidelines

### Ideal PR Size
- **Target**: < 400 lines changed
- **Maximum**: 600 lines (beyond this, requires justification)
- **Files**: Ideally < 10 files per PR

### When PRs Are Too Large
- Split by feature area (e.g., data model changes vs. API changes)
- Split by layer (backend first, then frontend)
- Create a "foundation" PR with shared models/utilities first

### PR Description Must Include
- What changed and why (not just what — that's in the diff)
- How to test it manually
- Screenshots for UI changes
- Link to the issue/ticket

### Review Turnaround
- First review within 24 hours of PR creation
- No PR should wait more than 48 hours for initial review
