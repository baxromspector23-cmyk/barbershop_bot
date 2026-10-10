from __future__ import annotations

from app.i18n.translator import Translator


def test_catalogs_have_identical_keys_and_placeholders():
    translator = Translator()
    langs = ["uz", "uz_cyrl", "ru"]

    for lang in langs:
        assert lang in translator.catalogs, f"Catalog for {lang} not loaded"
        assert len(translator.catalogs[lang]) > 0, f"Catalog {lang} is empty"

    uz_keys = set(translator.catalogs["uz"].keys())
    uz_cyrl_keys = set(translator.catalogs["uz_cyrl"].keys())
    ru_keys = set(translator.catalogs["ru"].keys())

    # Check key equality
    missing_in_cyrl = uz_keys - uz_cyrl_keys
    extra_in_cyrl = uz_cyrl_keys - uz_keys
    assert not missing_in_cyrl, f"Keys missing in uz_cyrl: {missing_in_cyrl}"
    assert not extra_in_cyrl, f"Extra keys in uz_cyrl: {extra_in_cyrl}"

    missing_in_ru = uz_keys - ru_keys
    extra_in_ru = ru_keys - uz_keys
    assert not missing_in_ru, f"Keys missing in ru: {missing_in_ru}"
    assert not extra_in_ru, f"Extra keys in ru: {extra_in_ru}"

    # Check placeholders match across all keys
    for key in uz_keys:
        uz_placeholders = translator.extract_placeholders(translator.catalogs["uz"][key])
        cyrl_placeholders = translator.extract_placeholders(translator.catalogs["uz_cyrl"][key])
        ru_placeholders = translator.extract_placeholders(translator.catalogs["ru"][key])

        assert uz_placeholders == cyrl_placeholders, (
            f"Placeholder mismatch for '{key}': uz has {uz_placeholders}, "
            f"uz_cyrl has {cyrl_placeholders}"
        )
        assert uz_placeholders == ru_placeholders, (
            f"Placeholder mismatch for '{key}': uz has {uz_placeholders}, "
            f"ru has {ru_placeholders}"
        )


def test_translator_fallback_and_formatting():
    translator = Translator()
    # Test formatting with existing key
    formatted = translator.get("client.heads_up", lang="uz", n=1, barber="Ali")
    assert "Ali" in formatted
    assert "1" in formatted

    # Test Cyrillic
    formatted_cyrl = translator.get("client.heads_up", lang="uz_cyrl", n=1, barber="Али")
    assert "Али" in formatted_cyrl

    # Test Russian
    formatted_ru = translator.get("client.heads_up", lang="ru", n=1, barber="Али")
    assert "Али" in formatted_ru

    # Test unknown lang fallback
    fallback = translator.get("common.welcome", lang="unknown_lang")
    assert "Assalomu alaykum" in fallback
