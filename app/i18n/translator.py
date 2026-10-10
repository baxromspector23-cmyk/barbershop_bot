from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

I18N_DIR = Path(__file__).parent


class Translator:
    def __init__(self, locales_dir: Path = I18N_DIR):
        self.locales_dir = locales_dir
        self.catalogs: dict[str, dict[str, str]] = {}
        self.load_catalogs()

    def _flatten_dict(self, d: dict[str, Any], parent_key: str = "", sep: str = ".") -> dict[str, str]:
        items: dict[str, str] = {}
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
            if isinstance(v, dict):
                items.update(self._flatten_dict(v, new_key, sep=sep))
            else:
                items[new_key] = str(v)
        return items

    def load_catalogs(self) -> None:
        for lang in ["uz", "uz_cyrl", "ru"]:
            file_path = self.locales_dir / f"{lang}.yaml"
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                self.catalogs[lang] = self._flatten_dict(data)
            else:
                self.catalogs[lang] = {}

    def get(self, key: str, lang: str = "uz", **kwargs: Any) -> str:
        if lang not in self.catalogs:
            lang = "uz"

        catalog = self.catalogs.get(lang, {})
        text = catalog.get(key)
        if text is None and lang != "uz":
            # fallback to uz
            text = self.catalogs.get("uz", {}).get(key)
        if text is None:
            return key

        if kwargs:
            try:
                return text.format(**kwargs)
            except KeyError:
                return text
        return text

    def extract_placeholders(self, text: str) -> set[str]:
        return set(re.findall(r"\{([a-zA-Z0-9_]+)\}", text))


translator = Translator()


def t(key: str, lang: str = "uz", **kwargs: Any) -> str:
    return translator.get(key, lang=lang, **kwargs)
