"""Stable model keys used by the developer feature flag."""

SIGLIP_MODEL_KEY = "siglip2"
OPENCLIP_MODEL_KEY = "openclip"
DEFAULT_MODEL_KEY = OPENCLIP_MODEL_KEY

MODEL_IDS = {
    SIGLIP_MODEL_KEY: "siglip2-base-patch16-224",
    OPENCLIP_MODEL_KEY: "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
}

OPENCLIP_BUNDLE_VERSION = "openclip-v1"
OPENCLIP_REVISION = "1a25a446712ba5ee05982a381eed697ef9b435cf"
OPENCLIP_PIPELINE_VERSION = 2

BUNDLE_VERSIONS = {
    OPENCLIP_MODEL_KEY: OPENCLIP_BUNDLE_VERSION,
}

# Former official product keys persisted in AppData before OpenCLIP adoption.
LEGACY_OFFICIAL_MODEL_KEYS = frozenset({SIGLIP_MODEL_KEY})


def normalize_model_key(value: object) -> str:
    key = str(value or "").strip().lower()
    return key if key in MODEL_IDS else DEFAULT_MODEL_KEY


def model_id_for_key(value: object) -> str:
    return MODEL_IDS[normalize_model_key(value)]


def bundle_version_for_key(value: object) -> str | None:
    return BUNDLE_VERSIONS.get(normalize_model_key(value))


def key_for_model_id(model_id: object) -> str | None:
    value = str(model_id or "").strip()
    for key, known in MODEL_IDS.items():
        if known == value:
            return key
    return None
