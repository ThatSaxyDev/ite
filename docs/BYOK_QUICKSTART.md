# iTE Quickstart

This is the shortest supported path for the current launch.

## 1. Install

```bash
pipx install ite-agent
```

## 2. Start iTE

```bash
ite
```

When cloud auth is enabled, iTE opens the hosted sign-in flow in your browser.
The default cloud API endpoint is `https://ite-cloud-api.onrender.com`.

If you are developing against a local API instead, set:

```bash
export ITE_CLOUD_API_URL=http://127.0.0.1:4000
```

## 3. Sign in

- Complete sign-in in the browser.
- Return to the terminal after approval.
- Wait for the terminal session to finish linking.

## 4. Configure your provider

Inside iTE, run:

```text
/setup
```

Enter:

- `base_url`: your OpenAI-compatible provider endpoint
- `api_key`: your provider key
- `model`: the exact model name your provider exposes

## 5. Run a real prompt

Send a normal prompt after setup completes.

If the first prompt works, your launch-critical path is healthy.

## Common failures

### Browser sign-in does not finish

- Check that the browser opened the real hosted app.
- Check that the API `BETTER_AUTH_URL` and `WEB_ORIGIN` match production.
- Check GitHub OAuth callback configuration.

### Provider request fails after `/setup`

- Verify the provider is OpenAI-compatible.
- Verify the base URL is correct, including `/v1` when required.
- Verify the API key is valid.
- Verify the model name is exactly correct.

### Session does not survive restart

- Confirm the cloud API is using persistent SQLite storage.
- Confirm the API can reach the same SQLite file after restart.
- Confirm refresh requests succeed against the deployed API origin.
