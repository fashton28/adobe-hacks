"""Catalogue of common real-world target formats.

RULES.md says scoring targets come from a fixed catalogue of platform formats
described the way a designer would ("Instagram Post", "YouTube Thumbnail").
The official list is not published; these are development stand-ins shared by
the evaluation runner, the web viewer and the Express add-on.
"""

FORMATS = [
    {"key": "instagram_post", "label": "Instagram Post", "width": 1080, "height": 1080},
    {"key": "instagram_portrait", "label": "Instagram Portrait", "width": 1080, "height": 1350},
    {"key": "story", "label": "Instagram / TikTok Story", "width": 1080, "height": 1920},
    {"key": "youtube_thumb", "label": "YouTube Thumbnail", "width": 1280, "height": 720},
    {"key": "facebook_cover", "label": "Facebook Cover", "width": 1640, "height": 624},
    {"key": "twitter_header", "label": "X / Twitter Header", "width": 1500, "height": 500},
    {"key": "linkedin_banner", "label": "LinkedIn Banner", "width": 1584, "height": 396},
    {"key": "pinterest_pin", "label": "Pinterest Pin", "width": 1000, "height": 1500},
    {"key": "banner_wide", "label": "Wide Web Banner", "width": 1600, "height": 400},
    {"key": "leaderboard", "label": "Leaderboard Ad", "width": 728, "height": 90},
    {"key": "skyscraper", "label": "Wide Skyscraper Ad", "width": 160, "height": 600},
    {"key": "medium_rect", "label": "Medium Rectangle Ad", "width": 300, "height": 250},
    {"key": "a4_portrait", "label": "A4 Portrait", "width": 794, "height": 1123},
]

TARGETS = {f["key"]: (f["width"], f["height"]) for f in FORMATS}
