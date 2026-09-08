# Using OpenRouter with iTE

OpenRouter is the simplest way to use iTE for free or against any model in their catalog. iTE ships with one-click OpenRouter sign-in so you don't have to copy API keys around.

## Sign in (recommended)

1. Launch iTE and run `/setup`.
2. Choose **OpenRouter** as the provider.
3. Click **Sign in with OpenRouter**.

iTE will:

- Open your browser to OpenRouter's sign-in page.
- Wait for you to approve the connection.
- Receive the API key automatically.
- Verify the key against OpenRouter and load the model list.

You don't need to copy or paste anything.

## When the browser can't open

If you're on an SSH session, inside a container, or your machine has no GUI browser available, iTE detects that automatically and shows a code field instead. The flow becomes:

1. Click **Sign in with OpenRouter**.
2. iTE opens the OpenRouter sign-in page in whatever browser you have on your local machine.
3. After approving, OpenRouter displays an authorization code on screen.
4. Copy the code, paste it into iTE's code field, and press Enter.

iTE exchanges the code for a key and continues as usual.

## Manual sign-in (advanced)

You can also paste a key directly into the API key field. This is the right path for:

- CI / automation where the browser flow isn't available.
- Pre-issued keys you've already generated from the OpenRouter dashboard.
- Users who prefer to manage keys themselves.

The pasted key is verified the same way: iTE hits `GET /api/v1/key` and `GET /api/v1/models` before saving.

## Where the key is stored

OAuth-derived keys live in `~/.ite/secrets.toml` under `[openrouter]`:

```toml
[openrouter]
api_key = "sk-or-v1-..."
key_label = "iTE CLI (my-macbook.local)"
created_at = "2026-09-07T14:32:11Z"
```

The file is created with `chmod 600` permissions. Your `config.toml` only contains `base_url` and `model.name` — never the key.

To remove the stored key, delete the `[openrouter]` table from `secrets.toml` and run `/setup` again.

## Identifying iTE's keys in your OpenRouter dashboard

Every OAuth flow registers the key under a `key_label` of `iTE CLI (<hostname>)`. The hostname is whatever `socket.gethostname()` returns on the machine that ran the flow. This makes it easy to:

- See which devices have an iTE-installed key.
- Revoke a key from a machine you no longer use.
- Track usage per device from the OpenRouter activity page.

## Revoking a key

You can revoke iTE's key at any time from <https://openrouter.ai/keys>. iTE will detect the revocation on its next request and let you sign in again.

## Troubleshooting

- **"OpenRouter rejected this API key"** — the key was revoked or deleted. Re-run `/setup` and sign in again.
- **"Authorization code expired"** — codes expire after 10 minutes. Click the sign-in button again to start a fresh flow.
- **Browser doesn't open** — your machine doesn't have a default browser configured. iTE prints the URL for you to open manually. On a headless machine, the code field appears automatically.

For deeper troubleshooting, see [OpenRouter's auth docs](https://openrouter.ai/docs/guides/overview/auth/oauth).
