# Test Coverage Guidelines

Best practices for testing different types of code.

## Test Pyramid

The ideal test distribution:
- **70% Unit tests** - Fast, isolated tests of individual functions
- **20% Integration tests** - Test component interactions
- **10% E2E tests** - Test full user workflows

## Unit Test Characteristics

**Good unit tests are:**
- Fast (<10ms each)
- Isolated (no external dependencies)
- Deterministic (same input = same output)
- Repeatable (same results in any order)

**Structure:**
```python
def test_feature_description():
    # Arrange
    input_data = create_test_data()
    expected = expected_result()

    # Act
    result = function_under_test(input_data)

    # Assert
    assert result == expected
```

## What to Test

### Business Logic

Always test core business rules - they encode your domain knowledge.

```python
# Account balance calculation
def test_overdraft_prevented_when_insufficient_funds():
    account = Account(balance=50)
    with pytest.raises(InsufficientFunds):
        account.withdraw(100)

# Price calculation
def test_discount_applied_to_eligible_items():
    cart = Cart([item_eligible, item_not_eligible])
    assert cart.total == (100 * 0.9) + 200
```

### Boundary Conditions

Test at the edges of valid inputs:

```python
# Empty
# Single item
# Maximum allowed
# Just below maximum
# Just above maximum

def test_handles_empty_list():
    assert average([]) is None

def test_handles_single_item():
    assert average([5]) == 5

def test_handles_maximum_items():
    assert average([1] * 10000) == 1
```

### Error Paths

Test failure modes, not just success:

```python
def test_handles_invalid_json():
    with pytest.raises(ValidationError):
        parse_json_service("{" not valid json }")

def test_handles_missing_required_field():
    data = {"name": "test"}  # Missing 'email'
    with pytest.raises(RequiredFieldError):
        User.from_dict(data)

def test_handles_network_timeout():
    with patch('requests.get', side_effect=Timeout()) as mock:
        with pytest.raises(ServiceUnavailable):
            fetch_data()
```

### Async/Code Paths

Test both synchronous and async branches:

```python
async def test_successful_async_operation():
    result = await async_fetch("http://example.com")
    assert result.status == 200

async def test_async_timeout_handled():
    with pytest.raises(TimeoutError):
        await async_fetch("http://slow.com", timeout=0.001)
```

## What NOT to Test

### Third-Party Code

Don't test external libraries - trust their own tests:

```python
# Don't do this
def test_json_library_parses_json():
    # This tests standard library behavior
    assert json.loads('{"a": 1}') == {"a": 1}

# Instead, test your usage
import json

def test_parses_config_file():
    with pytest.raises(ConfigError) as exc:
        load_config("invalid" path / "config.json")
    assert "Invalid JSON" in str(exc.value)
```

### Implementation Details

Don't test private methods or internal state:

```python
# Bad - ties test to implementation
class TestShoppingCart:
    def test_uses_list_to_store_items(self):
        cart = ShoppingCart()
        assert isinstance(cart._items, list)  # BAD!

# Good - test public behavior
class TestShoppingCart:
    def test_sums_prices_of_added_items(self):
        cart = ShoppingCart()
        cart.add(Item(price=10))
        cart.add(Item(price=20))
        assert cart.total() == 30
```

### Simple Getters/Setters

```python
# Bad - tests language features
def test_setter_updates_value():
    user = User()
    user.name = "Alice"
    assert user.name == "Alice"

# Good - skip unless there's logic involved
def test_name_capitalized_on_set(self):
    user = User()
    user.name = "alice"
    assert user.name == "Alice"  # Has logic
```

## Test Data

### Fixtures vs Inline

**Use fixtures for:**
- Complex object graphs
- Reusable across multiple tests
- Slow to create (use with care)

**Use inline data for:**
- Simple, specific values
- Direct relationship to test assertion
- Different values per test

```python
# Fixture for reusable object
@pytest.fixture
def admin_user():
    return User(role="admin", has_2fa=True)

def test_admin_can_delete_resource(admin_user):
    app.login_as(admin_user)
    app.delete_resource()
    assert app.resource_deleted()

# Inline for specific values
def test_calculate_discount():
    # Test input is visible and specific
    assert calculate_discount(100, 10) == 90
    assert calculate_discount(50, 20) == 40
```

### Avoid Magic Numbers

```python
# Bad - what does 5 mean?
def test_list_returns_limited_items():
    assert len(api.list()) == 5

# Good - constant with meaning
DEFAULT_PAGE_SIZE = 20

def test_list_returns_page_size_items():
    assert len(api.list()) == DEFAULT_PAGE_SIZE
```

## Test Organization

### File Structure

```
project/
├── src/
│   ├── user.py
│   └── order.py
└── tests/
    ├── unit/
    │   ├── test_user.py
    │   └── test_order.py
    ├── integration/
    │   ├── test_user_repository.py
    │   └── test_order_workflow.py
    └── fixtures/
        └── conftest.py
```

### Test Names

Tests should describe behavior, not implementation:

```python
# Bad - describes what the code does
def test_user_init():
def test_user_set_name():
def test_user_get_name():

# Good - describes the behavior
def test_cannot_create_user_without_email():
def test_name_is_required():
def test_name_is_stripped_of_whitespace():
```

### Grouping Related Tests

```python
class TestUserCreation:
    def test_requires_email(self):
        ...

    def test_normalizes_email(self):
        ...

    def test_requires_unique_email(self):
        ...

class TestUserAuthentication:
    def test_valid_credentials_return_token(self):
        ...

    def test_invalid_credentials_raise_error(self):
        ...

    def test_expired_token_is_rejected(self):
        ...
```

## Coverage Goals

### Minimum Thresholds

| Module Type | Target | Minimum |
|-------------|--------|---------|
| Core business logic | 90% | 80% |
| API endpoints | 85% | 70% |
| Data access layer | 70% | 50% |
| UI components | 60% | 40% |

### What Counts as Covered

**Covered:**
- Code path executed during test
- Both success and error branches
- Edge cases explicitly checked

**NOT covered by default:**
- Auto-generated code
- Boilerplate (getters/setters)
- Third-party library code
- Logging statements

### Coverage Reports

```bash
# Python with pytest-cov
pytest --cov=src --cov-report=html

# JavaScript with Jest
jest --coverage --coverageDirectory=coverage

# Go
go test -coverprofile=coverage.out ./...
go tool cover -html=coverage.out
```

## Anti-Patterns

### The False Positive

```python
def test_something():
    assert True  # Passes but tests nothing!

# Better: actual assertion
def test_database_returns_user_by_id():
    user = db.get_user(1)
    assert user.email == "test@example.com"
```

### The Brittle Test

```python
# Breaks when adding new fields
def test_json_output():
    user = User(name="Alice")
    assert user.to_json() == '{"name": "Alice", "created_at": ...}'

# Better: check specific fields
def test_json_includes_name(self):
    user = User(name="Alice")
    data = user.to_json()
    assert data["name"] == "Alice"
```

### The Slow Test

```python
# Calls real HTTP endpoint
def test_api_integration(self):
    result = requests.get("https://api.example.com")
    assert result.status_code == 200

# Better: mock the HTTP call
@responses.activate
def test_api_handles_success(self):
    responses.add(
        responses.GET,
        "https://api.example.com",
        json={"status": "ok"}, status=200
    )
    service = ApiService()
    result = service.fetch()
    assert result["status"] == "ok"
```

## Test Maintenance

### When to Update Tests

1. **When behavior changes:** Update tests to match new expected behavior
2. **When bugs are found:** Write regression test first, then fix
3. **When refactoring:** Tests should catch behavior changes
4. **When dependencies change:** Update assertions if output format changes

### Refactoring Tests

Tests should be refactored like production code:

```python
# Before: Duplicated setup
class TestUser(unittest.TestCase):
    def test_can_create(self):
        user = User(name="Test", email="test@test.com")
        self.assertIsNotNone(user.id)

    def test_can_login(self):
        user = User(name="Test", email="test@test.com")
        login = user.login("password")
        self.assertTrue(login)

# After: Fixture-based
@pytest.fixture
def test_user():
    return User(name="Test", email="test@test.com")

def test_can_create(test_user):
    assert test_user.id is not None

def test_can_login(test_user):
    assert test_user.login("password") is True
```
