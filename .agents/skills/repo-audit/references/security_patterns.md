# Security Anti-Patterns

Common security vulnerabilities and how to identify them.

## SQL Injection

**What it is:** Attacker-controlled data is executed as SQL.

**Patterns to find:**
- String concatenation for SQL queries: `cursor.execute("SELECT * FROM users WHERE id = " + user_id)`
- %-formatting in SQL strings: `cursor.execute("SELECT * FROM users WHERE id = %%s", user_id)`
- f-strings in SQL: `f"SELECT * FROM users WHERE id = {user_id}"`

**How to fix:** Use parameterized queries (placeholders that are properly escaped).

**Safe alternatives:**
```python
# Good: Python
# db-api
connection.execute("SELECT * FROM users WHERE id = ?", (user_id,))
# SQLAlchemy
session.query(User).filter(User.id == user_id).first()

# Good: JavaScript/Node
// mysql2
connection.execute("SELECT * FROM users WHERE id = ?", [userId])
// Prisma
prisma.user.findUnique({ where: { id: userId } })
```

## Cross-Site Scripting (XSS)

**What it is:** User input is rendered as HTML/JS without escaping.

**Patterns to find:**
- `.innerHTML = userData`
- `dangerouslySetInnerHTML` in React
- Template literals with user data: `element.innerHTML = \`<div>${userText}</div>\``

**How to fix:** Escape output or use framework-provided safe rendering.

**Safe alternatives:**
```javascript
// React: Use JSX automatically escapes
\<div\>{userText}\</div\>

// Vanilla JS: Use textContent, not innerHTML
element.textContent = userText;

// Explicit escaping
element.innerHTML = DOMPurify.sanitize(userText);
```

## Command Injection

**What it is:** User data is passed to shell or exec functions.

**Patterns to find:**
- `os.system(f"echo {user_input}")`
- `exec(user_code)`
- `subprocess.call(user_cmd, shell=True)`
- `child_process.exec(userCmd)`

**How to fix:** Pass arguments as arrays, not strings. Avoid shell=True.

**Safe alternatives:**
```python
# Good
subprocess.run(["ls", "-la", user_path], shell=False)

# Bad
cmd = f"ls -la {user_path}"  # vulnerable to "; rm -rf /"
subprocess.call(cmd, shell=True)
```

## Hardcoded Secrets

**What it is:** API keys, passwords, or tokens stored in source code.

**Patterns to find:**
- `password = "abc123"`
- `API_KEY = "sk-"` (OpenAI)
- `JWT_SECRET = "..."`
- Values matching known patterns in `.env` files

**How to fix:** Use environment variables or secrets managers.

**Safe alternatives:**
```python
import os

api_key = os.environ.get("API_KEY")
if not api_key:
    raise ValueError("API_KEY environment variable required")
```

## Path Traversal

**What it is:** User-controlled paths access unintended files.

**Patterns to find:**
- `open(user_path, "r")` without validation
- Serving files based on user input: `send_file(f"/uploads/{filename}")`
- Directory traversal patterns: `../`, `..\`

**How to fix:** Validate and sanitize paths. Use allowlists.

**Safe alternatives:**
```python
from pathlib import Path

upload_dir = Path("/app/uploads")
requested = Path(user_path).name  # strip directories
safe_path = upload_dir / requested

# Verify it's still in upload_dir
if safe_path.resolve() != upload_dir / safe_path.name:
    raise PermissionError("Invalid path")
```

## Insecure Deserialization

**What it is:** Untrusted data is deserialized without validation.

**Patterns to find:**
- `pickle.loads(user_data)` - NEVER deserialzie user input
- `yaml.load(user_data, Loader=yaml.Loader)`
- `eval(json_str)` with user-controlled data

**How to fix:** Use JSON. If binary serialization is required, use msgpack or similar with validation.

**Safe alternatives:**
```python
import json

# Safe
data = json.loads(user_data)

# NOT safe for user input
import pickle
data = pickle.loads(user_data)  # Can execute arbitrary code
```

## Weak Cryptography

**What it is:** Using outdated or broken cryptographic algorithms.

**Patterns to find:**
- MD5 or SHA1 for password hashing
- ECB mode for encryption
- Hardcoded keys
- `random.random()` for security purposes

**How to fix:** Use modern, vetted libraries.

**Safe alternatives:**
```python
from cryptography.fernet import Fernet
import bcrypt
import secrets

# Password hashing
hashed = bcrypt.hashpw(password, bcrypt.gensalt())

# Secure random
secure_token = secrets.token_urlsafe(32)

# Encryption (at rest)
key = Fernet.generate_key()
cipher = Fernet(key)
encrypted = cipher.encrypt(data)
```

## Missing Authentication/Authorization

**What it is:** Endpoints or resources are unprotected.

**Patterns to find:**
- API routes without `@login_required` decorators
- Admin functions without role checks
- Internal APIs accessible externally
- `*allow-origin: *` CORS policies

**How to fix:** Implement consistent auth middleware.

**Safe patterns:**
```python
# Flask example
from flask_login import login_required

@app.route("/admin")
@login_required
def admin():
    if not current_user.is_admin:
        abort(403)
    return render_template("admin.html")
```

## Information Leakage

**What it is:** Application reveals sensitive information in errors.

**Patterns to find:**
- `return {"error": str(e)}` with full traceback
- Detailed 500 error pages in production
- Stack traces in production logs that get exposed

**How to fix:** Sanitize error messages. Log full details, show users minimal info.

**Safe patterns:**
```python
import logging

logger = logging.getLogger(__name__)

try:
    process_user_data(user_input)
except ValidationError as e:
    # Safe for user
    return {"error": "Invalid input"}, 400
except Exception as e:
    # Log full details
    logger.exception("Processing failed")
    # Safe for user
    return {"error": "Internal error"}, 500
```

## Rate Limiting Bypass

**What it is:** Resource-intensive operations can be spammed.

**Patterns to find:**
- Login endpoints without rate limiting
- Email sending endpoints
- Password reset triggers
- API endpoints without throttling

**How to fix:** Implement rate limiting at the route or application level.

**Safe patterns:**
```python
from flask_limiter import Limiter

limiter = Limiter(app, key_func=lambda: request.remote_addr)

@app.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    ...
```
