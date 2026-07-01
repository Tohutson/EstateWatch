PROMPT_VERSION = "vision-v1"

VISION_SYSTEM_PROMPT = (
    "You classify estate sale photos for useful modern camera equipment and golf equipment. "
    "Identify only actual visible physical items. Distinguish modern digital cameras from "
    "antique film cameras, security cameras, toys, paintings, books, televisions, packaging, "
    "and decorative objects. Distinguish real golf equipment from miniature golf, televised "
    "golf, artwork, or decor. Estimate modern likelihood only when visible evidence supports "
    "it. Identify visible brands only when legible. Do not invent model numbers."
)

VISION_USER_PROMPT = (
    "Return one result per supplied image id. Target categories are camera, camera_lens, "
    "camera_accessory, golf_clubs, golf_bag, golf_rangefinder, golf_accessory, and other. "
    "Include items only when they are likely useful matches for shopping."
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
                                        "camera",
                                        "camera_lens",
                                        "camera_accessory",
                                        "golf_clubs",
                                        "golf_bag",
                                        "golf_rangefinder",
                                        "golf_accessory",
                                        "other",
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
