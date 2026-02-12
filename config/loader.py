from tomllib import TOMLDecodeError
from config.config import Config
from pathlib import Path
from platformdirs import user_config_dir

CONFIG_FILE_NAME = "config.toml"


def get_config_dir() -> Path:
    return Path(user_config_dir("ite"))


def get_system_config_path() -> Path:
    return get_config_dir() / CONFIG_FILE_NAME


def _parse_toml(path: Path):
    try:
        pass
    except TOMLDecodeError:
        raise ConfigError()


def load_config(
    cwd: Path | None,
) -> Config:
    cwd = cwd or Path.cwd()

    system_path = get_system_config_path()

    if system_path.is_file():
        pass
