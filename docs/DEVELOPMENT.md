# Development Setup

For contributing to iTE or running from source.

## Local Install (Editable)

```bash
git clone https://github.com/ThatSaxyDev/ite.git
cd ite
pip install -e .
```

## Build from Source

```bash
python -m build
pipx install dist/ite_agent-*.whl
```

## Environment Variables

- `ITE_CLOUD_API_URL` - Override cloud API endpoint (default: `https://ite-cloud-api.onrender.com`)

## Architecture

See main repo README for full architecture docs.
