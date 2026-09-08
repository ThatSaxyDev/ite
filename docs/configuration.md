# Configuration

iTE requires an OpenAI-compatible model provider. Run `/setup` to configure.

## Supported Providers

### Ollama (Local)

For running models locally:

| Setting    | Value                     |
| ---------- | ------------------------- |
| Base URL   | `http://localhost:11434/v1` |
| API Key    | `ollama` (or your key)    |
| Model      | `llama3` or your model    |

Install Ollama: [ollama.com](https://ollama.com)

### OpenRouter

For access to many models through a single endpoint:

| Setting    | Value                             |
| ---------- | --------------------------------- |
| Base URL   | `https://openrouter.ai/api/v1`    |
| API Key    | Your OpenRouter key               |
| Model      | `openai/gpt-4o` or provider/model |

#### Sign in with OpenRouter (one click)

In `/setup`, pick **OpenRouter** and click **Sign in with OpenRouter**. iTE opens your browser, you approve the connection, and the resulting key is filled in and verified automatically. No copy-paste required.

- If your machine can't open a browser (SSH session, container, CI), iTE detects this and shows a code field instead. Approve the connection in your browser, paste the code iTE asks for, and iTE finishes the exchange.
- The key is stored in `~/.ite/secrets.toml` under `[openrouter]`. Your `config.toml` only contains the base URL and model name.

Manual paste still works — paste any OpenRouter key into the API key field and click **Load** as before.

### OpenAI

For OpenAI models:

| Setting    | Value                         |
| ---------- | ----------------------------- |
| Base URL   | `https://api.openai.com/v1`   |
| API Key    | Your OpenAI API key           |
| Model      | `gpt-4o`, `gpt-4o-mini`       |

## Running `/setup`

Start iTE and run the setup command:

```bash
ite
```

```
/setup
```

You'll be prompted for:
- Base URL
- API Key
- Model name

Credentials are stored securely and project settings can be customized in `.ite/config.toml`.

---

## iTE Cloud (Coming Soon)

Bundled model access is on the roadmap. iTE Cloud will offer a curated selection of high-quality models, managed directly within the platform. This eliminates the need for external API keys while providing reliable, integrated access to models optimized for coding workflows.

When available, you will be able to connect instantly without configuring third-party providers.

---

## Next Steps

[Initialize your project →](initialization.md)
