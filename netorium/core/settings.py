from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, Final, Mapping

from pydantic import BaseModel, ConfigDict, ValidationError

from netorium.core.platform import user_config_path

CONFIG_TEMPLATE: Final[str] = """[app]
database_path = "~/.local/share/netorium/netorium.db"
timezone = "Asia/Almaty"
log_level = "INFO"

[prtg]
base_url = "https://prtg.example.local"
username = "admin"
passhash = "CHANGE_ME"

[active_directory]
server = "ldap://ad.example.local"
domain = "example.local"
bind_user = "CN=Netorium,CN=Users,DC=example,DC=local"
bind_password = "CHANGE_ME"

[telegram]
bot_token = "CHANGE_ME"
chat_id = "CHANGE_ME"

[updates]
source = "github"
repo = "it31wasdrexm/netorium"
check_on_start = true
"""

SECRET_KEY_MARKERS: Final[tuple[str, ...]] = (
    "chat_id",
    "password",
    "passhash",
    "secret",
    "token",
)


class ConfigError(RuntimeError):
    pass


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_path: str
    timezone: str
    log_level: str


class PrtgSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    username: str
    passhash: str


class ActiveDirectorySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: str
    domain: str
    bind_user: str
    bind_password: str


class TelegramSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_token: str
    chat_id: str


class UpdateSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    repo: str
    check_on_start: bool


class NetoriumSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: AppSettings
    prtg: PrtgSettings
    active_directory: ActiveDirectorySettings
    telegram: TelegramSettings
    updates: UpdateSettings


def default_config_path() -> Path:
    return user_config_path()


def init_config(path: Path | None = None, force: bool = False) -> Path:
    config_path = path or default_config_path()
    if config_path.exists() and not force:
        raise ConfigError(f"Config already exists: {config_path}")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return config_path


def read_config_data(path: Path | None = None) -> dict[str, Any]:
    config_path = path or default_config_path()
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}. Run `netorium config init` first.")

    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in config file: {exc}") from exc


def load_settings(path: Path | None = None) -> NetoriumSettings:
    data = read_config_data(path)
    try:
        return NetoriumSettings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config: {_format_validation_error(exc)}") from exc


def validate_settings(path: Path | None = None) -> NetoriumSettings:
    return load_settings(path)


def masked_config_text(path: Path | None = None) -> str:
    data = read_config_data(path)
    return render_toml(mask_secrets(data))


def mask_secrets(data: Mapping[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, Mapping):
            masked[key] = mask_secrets(value)
        elif _is_secret_key(key):
            masked[key] = "********"
        else:
            masked[key] = value
    return masked


def render_toml(data: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for section, values in data.items():
        if lines:
            lines.append("")
        if isinstance(values, Mapping):
            lines.append(f"[{section}]")
            for key, value in values.items():
                lines.append(f"{key} = {_format_toml_value(value)}")
        else:
            lines.append(f"{section} = {_format_toml_value(values)}")
    return "\n".join(lines)


def _is_secret_key(key: str) -> bool:
    normalized = key.lower()
    return any(marker in normalized for marker in SECRET_KEY_MARKERS)


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(str(value))


def _format_validation_error(exc: ValidationError) -> str:
    first_error = exc.errors()[0]
    location = ".".join(str(part) for part in first_error.get("loc", ()))
    message = str(first_error.get("msg", "invalid value"))
    if location:
        return f"{location}: {message}"
    return message
