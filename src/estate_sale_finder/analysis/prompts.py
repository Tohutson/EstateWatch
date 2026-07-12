from __future__ import annotations

from estate_sale_finder.domain.models import APPROVED_TARGET_CATEGORIES, TargetCategory

PROMPT_VERSION = "targets-multi-v1"

CATEGORY_DEFINITIONS = {
    TargetCategory.GOLF_CLUBS.value: (
        "golf_clubs: drivers, woods, hybrids, irons, wedges, putters, or clearly visible "
        "sets of real golf clubs. Do not report miniature/decorative clubs, clothing, shoes, "
        "hats, gloves, tees, towels, carts, scorecards, headcovers, training aids, or golf "
        "shown only on a screen or printed material."
    ),
    TargetCategory.GOLF_BAG.value: (
        "golf_bag: a real golf bag, whether empty or holding clubs. Do not report ordinary "
        "duffel bags, camera bags, luggage, or bags shown only in photos, artwork, packaging, "
        "or screens."
    ),
    TargetCategory.GOLF_BALLS.value: (
        "golf_balls: real golf balls that are clearly visible as balls or lots of balls. Do "
        "not report logos, printed pictures, ornaments, or unrelated small white objects."
    ),
    TargetCategory.MODERN_CAMERA.value: (
        "modern_camera: useful digital mirrorless, DSLR, or compact digital camera bodies. "
        "Do not report antique/vintage film cameras, disposable cameras, security cameras, "
        "webcams, action cameras, camcorders, bags by themselves, tripods, flashes, batteries, "
        "chargers, straps, filters, memory cards, books, artwork, screens, advertisements, "
        "or packaging without the actual camera."
    ),
    TargetCategory.MODERN_CAMERA_LENS.value: (
        "modern_camera_lens: interchangeable DSLR or mirrorless camera lenses. Do not report "
        "old film-era lenses unless they are clearly modern autofocus lenses, binoculars, "
        "telescopes, lens caps, filters, adapters, books, artwork, screens, advertisements, "
        "or packaging without the actual lens."
    ),
    TargetCategory.COLLECTIBLE_PERFUME_BOTTLE.value: (
        "collectible_perfume_bottle: large, ornate, decorative, display-worthy, vintage-looking, "
        "or recognizable branded perfume bottles when the actual bottle is visible and plausibly "
        "collectible or valuable; groups or collections qualify when bottles are clearly visible. "
        "Do not report tiny sample vials, travel sprays, ordinary toiletries, shampoo, lotion, "
        "medicine, cleaning bottles, empty generic glass bottles, candles, alcohol bottles, "
        "decorative glassware that is not plausibly perfume, printed pictures, or boxes/packaging "
        "only. Interpret large visually and practically; if normal-size but clearly collectible, "
        "report with lower confidence and mention uncertainty."
    ),
    TargetCategory.JEWELRY.value: (
        "jewelry: rings, necklaces, bracelets, earrings, brooches, pendants, jewelry lots, and "
        "watches that are clearly jewelry-like or collectible. Jewelry boxes or trays qualify "
        "only when jewelry is visibly present. Do not report clothing with metallic decoration, "
        "belt buckles, keys, coins, silverware, loose beads unless clearly made into jewelry, "
        "generic metal hardware, decorative boxes with no visible jewelry, jewelry shown only "
        "in artwork/books/packaging/screens, or costume accessories unless plausibly jewelry "
        "items for sale. Do not guess gemstones, precious metals, karat, authenticity, or value; "
        "use visual terms such as gold-tone, silver-tone, ring, or necklace when supported."
    ),
}


def build_system_prompt(categories: set[str] | frozenset[str]) -> str:
    selected = _validated_categories(categories)
    definitions = " ".join(CATEGORY_DEFINITIONS[category] for category in selected)
    return (
        "Classify each estate sale image independently. Report only actual visible physical "
        "objects in these approved categories: "
        f"{', '.join(selected)}. {definitions} Be conservative: do not guess when image quality "
        "is poor, do not invent brands, materials, values, gemstones, model numbers, age, or "
        "type, and use visible_brand only when a logo or marking is legible and relevant. "
        "Distinguish physical objects from photos, screens, packaging, artwork, text, and "
        "advertisements. Return confidence from visual evidence. Return modern_likelihood only "
        "for modern_camera and modern_camera_lens; use 0 for all other categories. Preserve the "
        "supplied image_ref exactly. Never invent, transform, merge, omit, or duplicate image_ref "
        "values. Return an explicit non-match for every image without an approved target, "
        "including blurry, irrelevant, or unreadable images. For each positive item, include "
        "concise notes explaining the visible evidence for the match."
    )


def build_user_prompt(categories: set[str] | frozenset[str]) -> str:
    selected = _validated_categories(categories)
    return (
        "Return strict JSON with exactly one result for every supplied image. Preserve image_ref "
        "exactly as provided, never invent or transform it, never merge multiple images into one "
        "result, and never return duplicate references. If an image has no approved target or "
        "cannot be interpreted, return contains_target=false and items=[]. Include only these "
        f"approved categories: {', '.join(selected)}."
    )


def build_response_schema(categories: set[str] | frozenset[str]) -> dict[str, object]:
    selected = _validated_categories(categories)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "image_ref": {"type": "string"},
                        "contains_target": {"type": "boolean"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "category": {"type": "string", "enum": selected},
                                    "label": {"type": "string"},
                                    "confidence": {
                                        "type": "number",
                                        "minimum": 0,
                                        "maximum": 1,
                                    },
                                    "modern_likelihood": {
                                        "type": "number",
                                        "minimum": 0,
                                        "maximum": 1,
                                    },
                                    "visible_brand": {"type": ["string", "null"]},
                                    "notes": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "category",
                                    "label",
                                    "confidence",
                                    "modern_likelihood",
                                    "visible_brand",
                                    "notes",
                                ],
                            },
                        },
                    },
                    "required": ["image_ref", "contains_target", "items"],
                },
            }
        },
        "required": ["results"],
    }


def _validated_categories(categories: set[str] | frozenset[str]) -> list[str]:
    invalid = sorted(set(categories) - APPROVED_TARGET_CATEGORIES)
    if invalid:
        raise ValueError(f"Unknown target categories: {', '.join(invalid)}")
    if not categories:
        raise ValueError("At least one target category is required")
    return sorted(categories)


VISION_SYSTEM_PROMPT = build_system_prompt(APPROVED_TARGET_CATEGORIES)
VISION_USER_PROMPT = build_user_prompt(APPROVED_TARGET_CATEGORIES)
VISION_RESPONSE_SCHEMA = build_response_schema(APPROVED_TARGET_CATEGORIES)
