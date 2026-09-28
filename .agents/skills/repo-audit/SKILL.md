---
name: repo-audit
description: Review codebases for bugs, security risks, and missing test coverage. Use when iTE needs to audit code for potential issues before PR review, during security reviews, or when asked to find bugs, risks, or missing tests in a codebase.
---

# Repo Audit

Comprehensive code review for identifying bugs, security risks, and test coverage gaps.

## When to Use

Use this skill to audit codebases in these scenarios:
- Pre-PR review: Catch issues before code reaches reviewers
- Security audit: Identify vulnerabilities and security anti-patterns
- Test coverage analysis: Find untested code paths and missing test scenarios
- Risk assessment: Evaluate code quality and potential failure points

## Workflow

1. **Understand the scope**: Identify target language(s), frameworks, and audit focus
2. **Run automated checks**: Use bundled scripts for pattern detection
3. **Manual review**: Examine high-risk areas identified in Step 2
4. **Report findings**: Categorize by severity and provide concrete recommendations

## Automated Detection

### Test Coverage Analysis

Run the test coverage analyzer:

```bash
python3 /path/to/skill/scripts/audit_test_coverage.py [options]
```

Options:
- `--python`: Analyze Python test coverage (pytest/unittest patterns)
- `--js`: Analyze JavaScript/TypeScript coverage (Jest/Vitest patterns)
- `--output`: Specify output format (text/json)

Results include:
- Files without corresponding tests
- Test files with low assertion counts
- Functions/classes missing test coverage

### Bug Pattern Detection

Run the bug pattern finder:

```bash
python3 /path/to/skill/scripts/find_common_bugs.py [options]
```

Options:
- `--lang python|js|ts|go`: Target language
- `--severity high|medium|low`: Filter by severity
- `--patterns list`: List available pattern checks

Common patterns detected:
- Unused imports/variables
- Unhandled exceptions
- Resource leaks (files, connections)
- SQL injection vectors
- Hardcoded secrets

## Manual Review Checklist

### Security

- [ ] Input validation on all user-facing endpoints
- [ ] Output escaping to prevent XSS
- [ ] Authentication/authorization checks
- [ ] CSRF protection on state-changing operations
- [ ] Secrets not hardcoded in source

### Logic & Bugs

- [ ] Null/undefined checks where values may be optional
- [ ] Race conditions in concurrent code
- [ ] Off-by-one errors in loops
- [ ] Mutable default arguments in Python functions
- [ ] Proper error handling paths

### Testing

- [ ] Unit tests for business logic
- [ ] Integration tests for API endpoints
- [ ] Edge cases covered (null, empty, large inputs)
- [ ] Error paths tested
- [ ] Test names describe behavior, not implementation

### Performance

- [ ] N+1 query patterns in database access
- [ ] Unbounded loops or recursion
- [ ] Large object instantiation in loops
- [ ] Synchronous calls in async contexts

## Reference Materials

- **Security anti-patterns**: See [references/security_patterns.md](references/security_patterns.md)
- **Bug patterns by language**: See [references/common_bug_patterns.md](references/common_bug_patterns.md)
- **Test coverage guidelines**: See [references/test_guidelines.md](references/test_guidelines.md)

## Severity Classification

| Severity | Criteria | Action |
|----------|----------|--------|
| **Critical** | Security vulnerability, data loss risk | Block merge, fix immediately |
| **High** | Likely runtime error, undefined behavior | Address before merge |
| **Medium** | Missing edge case handling, minor logic issues | Address within sprint |
| **Low** | Style issues, missing optimizations | Tech debt, address as time allows |
