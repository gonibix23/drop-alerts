from __future__ import annotations

import pytest

from drop_alerts.config import Settings


FIELDS = (
    "discord_webhook_url", "discord_webhook_url_magic",
    "discord_webhook_url_one_piece", "discord_webhook_url_pokemon",
)
WEBHOOK = "https://discord.com/api/webhooks/123/private-routing-token"


def test_routes_are_optional_and_general_webhook_remains_supported():
    empty = Settings.from_env({})
    assert all(getattr(empty, field) == "" for field in FIELDS)
    legacy = Settings.from_env({"DISCORD_WEBHOOK_URL": WEBHOOK})
    assert legacy.discord_webhook_url == WEBHOOK
    assert all(getattr(legacy, field) == "" for field in FIELDS[1:])


def test_three_routes_without_general_webhook_are_independent():
    values = {field.upper(): WEBHOOK + "-" + str(index) for index, field in enumerate(FIELDS[1:])}
    settings = Settings.from_env(values)
    assert settings.discord_webhook_url == ""
    for field in FIELDS[1:]:
        assert getattr(settings, field) == values[field.upper()]
    assert "private-routing-token" not in repr(settings)


@pytest.mark.parametrize("field", FIELDS)
def test_webhook_secrets_from_environment_and_mounted_files(tmp_path, field):
    key = field.upper()
    path = tmp_path / "webhook-secret"
    path.write_text("\n  " + WEBHOOK + "  \n", encoding="utf-8")
    assert getattr(Settings.from_env({key: " " + WEBHOOK + "\n"}), field) == WEBHOOK
    settings = Settings.from_env({key + "_FILE": str(path), key: ""})
    assert getattr(settings, field) == WEBHOOK
    assert "private-routing-token" not in repr(settings)
    with pytest.raises(ValueError) as exc:
        Settings.from_env({key: WEBHOOK, key + "_FILE": str(path)})
    assert key in str(exc.value)
    assert WEBHOOK not in str(exc.value)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", (
    "http://discord.com/api/webhooks/123/private-routing-token",
    "https://discord.com.attacker.invalid/api/webhooks/123/private-routing-token",
    "https://private-routing-token@discord.com/api/webhooks/123/token",
    "https://discord.com/channels/123/private-routing-token",
    "https://discord.com/api/webhooks/123/private-routing-token\nInjected: bad",
    "https://[private-routing-token/api/webhooks/123/token",
))
def test_invalid_route_rejected_without_disclosing_secret(field, value):
    with pytest.raises(ValueError) as exc:
        Settings.from_env({field.upper(): value})
    assert field.upper() in str(exc.value)
    assert "private-routing-token" not in str(exc.value)


@pytest.mark.parametrize("host", ("discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"))
def test_supported_discord_hosts_for_route(host):
    value = WEBHOOK.replace("discord.com", host)
    assert Settings.from_env({"DISCORD_WEBHOOK_URL_ONE_PIECE": value}).discord_webhook_url_one_piece == value
