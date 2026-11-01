from .config import LIMIT_DEFAULTS


def limits_for_language(config: dict, language: str) -> dict[str, int]:
    limits = {key: int(config.get(key, value)) for key, value in LIMIT_DEFAULTS.items()}
    overrides = config.get("language_overrides", {}).get(language, {})
    if isinstance(overrides, dict):
        limits.update({key: int(overrides[key]) for key in limits if key in overrides})
    return limits
