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
