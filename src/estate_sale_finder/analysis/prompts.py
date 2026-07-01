PROMPT_VERSION = "targets-v2"

VISION_SYSTEM_PROMPT = (
    "Classify each estate sale image independently. Report only actual visible physical "
    "objects in these approved categories: golf_clubs, golf_bag, golf_balls, modern_camera, "
    "modern_camera_lens. Golf clubs include drivers, woods, hybrids, irons, wedges, and "
    "putters; golf bags qualify whether empty or holding clubs; golf balls qualify only when "
    "real balls are clearly visible. Modern cameras include useful digital mirrorless, DSLR, "
    "and compact digital camera bodies. Modern camera lenses include interchangeable DSLR or "
    "mirrorless lenses. Do not report antique or vintage film cameras, disposable cameras, "
    "security cameras, webcams, action cameras, camcorders, bags by themselves, tripods, "
    "flashes, batteries, chargers, straps, filters, memory cards, books, artwork, screens, "
    "advertisements, packaging, decorative objects, golf rangefinders, golf clothing, golf "
    "shoes, hats, gloves, tees, towels, training aids, carts, scorecards, headcovers, "
    "miniature golf objects, televisions showing golf, or unrelated household objects. Be "
    "conservative: do not guess when image quality is poor, do not invent a brand, model, "
    "age, or type, and use visible_brand only when a logo or marking is legible. Return "
    "confidence from visual evidence. Return "
    "modern_likelihood only for modern_camera and modern_camera_lens; use 0 for golf items. "
    "Preserve the supplied image_id exactly and return an explicit non-match for images "
    "without an approved target."
)

VISION_USER_PROMPT = (
    "Return strict JSON with one result per supplied image_id. If an image has no approved "
    "target, set contains_target=false and items=[]. Include only approved categories."
)

VISION_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "image_id": {"type": "integer"},
                    "contains_target": {"type": "boolean"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "category": {
                                    "type": "string",
                                    "enum": [
                                        "golf_clubs",
                                        "golf_bag",
                                        "golf_balls",
                                        "modern_camera",
                                        "modern_camera_lens",
                                    ],
                                },
                                "label": {"type": "string"},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "modern_likelihood": {"type": "number", "minimum": 0, "maximum": 1},
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
                "required": ["image_id", "contains_target", "items"],
            },
        }
    },
    "required": ["results"],
}
