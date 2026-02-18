# Requirements Engineering Best Practices

## INVEST Criteria for User Stories

INVEST is an acronym for characteristics of a good user story:

### Independent
Stories should be self-contained and not depend on other stories for implementation.
❌ Bad: "User can see their profile" (depends on profile creation story being done first)
✅ Good: "User can view their own profile page showing name, email, and join date"

### Negotiable
Stories are not fixed contracts — they represent the conversation, not the solution.
The team should feel free to discuss and adjust implementation details.

### Valuable
Every story must deliver value to users or the business.
❌ Bad: "Add database migration for user table" (technical task, not a story)
✅ Good: "As a returning user, I can log in to see my personalized dashboard"

### Estimable
The team must be able to estimate effort. Stories that are too vague or too large cannot be estimated.
If you can't estimate it, break it down or spike it.

### Small
Stories should be completable in one sprint (1-2 weeks). Large stories ("epics") should be split.
If a story has more than 5 acceptance criteria, consider splitting it.

### Testable
Every story must have clear acceptance criteria that can be verified.

---

## Acceptance Criteria: Given/When/Then Format

Acceptance criteria define when a story is "done." Use the Given/When/Then (Gherkin) format.

### Structure
```
Given [precondition / initial context]
When  [action / event]
Then  [expected outcome / observable result]
And   [additional outcome if needed]
```

### 5 Real Examples

**Example 1: User Authentication**
```
Given I am a registered user with valid credentials
When I submit the login form with my email and password
Then I am redirected to my dashboard
And I see a "Welcome back, {name}" message
And my session is valid for 24 hours
```

**Example 2: Search with Pagination**
```
Given there are 150 products in the catalog
When I search for "laptop" and 45 results match
Then I see the first 20 results on page 1
And I see pagination controls showing "Page 1 of 3"
When I click "Next Page"
Then I see results 21-40
```

**Example 3: File Upload**
```
Given I am on the document upload page
When I select a PDF file larger than 10MB
Then I see an error: "File size exceeds 10MB limit"
And no file is uploaded
When I select a valid PDF under 10MB
Then the file uploads and I see "Upload successful"
And the file appears in my document list within 5 seconds
```

**Example 4: Email Notification**
```
Given I have email notifications enabled
When another user comments on my post
Then I receive an email within 2 minutes
And the email contains the commenter's name and comment preview
When I click the email link
Then I am taken directly to the comment thread
```

**Example 5: API Rate Limiting**
```
Given an API client has consumed 99 of their 100 requests/hour quota
When they make one more API request
Then the request succeeds with HTTP 200
When they make the next request
Then they receive HTTP 429 Too Many Requests
And the response includes Retry-After header with seconds to wait
```

---

## Common Edge Cases Checklist

When analyzing a story, always check these categories:

### Authentication & Authorization
- [ ] What happens when the user is NOT logged in?
- [ ] What if the user's session expires mid-action?
- [ ] Does this feature need role-based access? What roles can access it?
- [ ] Can user A access user B's resources?
- [ ] What about admin override capabilities?

### Empty States
- [ ] What does the UI show when there's no data yet?
- [ ] What if the search returns zero results?
- [ ] What if the list grows to thousands of items?
- [ ] What if required dependent data hasn't loaded?

### Pagination & Large Datasets
- [ ] What's the maximum number of items returned per request?
- [ ] Is there cursor-based or offset pagination?
- [ ] What happens if page number exceeds total pages?
- [ ] Are there performance implications for large datasets?

### Error Handling
- [ ] What if the external API/service is down?
- [ ] What if the database operation fails?
- [ ] What errors should be shown to users vs. logged silently?
- [ ] Is there a retry mechanism for transient failures?

### Concurrency
- [ ] What if two users edit the same resource simultaneously?
- [ ] Is there a need for optimistic locking?
- [ ] What if the same webhook is delivered twice (idempotency)?
- [ ] Race conditions in distributed environments?

### Input Validation
- [ ] What's the maximum length for text fields?
- [ ] What special characters are allowed/blocked?
- [ ] What about unicode, emoji, RTL text?
- [ ] What if required fields are empty or null?

---

## Definition of Ready (DoR) Checklist

A story is READY for development when ALL of these are true:
- [ ] The story is written in user story format ("As a... I want... So that...")
- [ ] Acceptance criteria are written in Given/When/Then format
- [ ] The story has been estimated by the team
- [ ] UI mockups or wireframes exist (for UI stories)
- [ ] External dependencies are identified and available
- [ ] The story fits in one sprint
- [ ] Edge cases have been discussed and documented
- [ ] Definition of Done criteria are clear

---

## Complexity Estimation Guide

Use T-shirt sizing for story complexity:

| Size | Story Points | Time Estimate | Description |
|------|-------------|----------------|-------------|
| XS   | 1           | < 2 hours      | Trivial change: fix typo, update config value, add one field |
| S    | 2-3         | 2-8 hours      | Simple feature: add CRUD endpoint, small UI component |
| M    | 5           | 1-3 days       | Medium feature: multiple endpoints, some business logic, basic tests |
| L    | 8           | 3-5 days       | Complex feature: multiple components, integration with external service |
| XL   | 13+         | > 1 week       | Epic: should be broken down. If you size XL, split the story |

**Factors that increase complexity:**
- Integration with external APIs
- Real-time requirements (WebSockets, SSE)
- Complex business logic or algorithms
- Data migration required
- Performance requirements (SLA, load)
- Security requirements (encryption, audit)
- Cross-team dependencies
