from .magic_news import MagicNewsSource
from .secret_lair import SecretLairSource

SOURCE_REGISTRY = {"secret_lair_eu": SecretLairSource, "magic_news": MagicNewsSource}

__all__ = ["MagicNewsSource", "SecretLairSource", "SOURCE_REGISTRY"]
