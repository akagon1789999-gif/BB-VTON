"""What a generation costs, and roughly how long it takes.

The matrix is FASHN's published `tryon-max` table. Note what is *not* in it:
there is no `fast` mode on `tryon-max` — the endpoint accepts `balanced` and
`quality` only. Sending `fast` does not make a job cheaper, it makes the mode
undefined and lets the API auto-select, which bills as `balanced` while a
naive UI quotes the lower number. So `fast` is not offered.

The `edit` endpoint does accept `fast`, but FASHN does not publish its credit
table, so we quote the `tryon-max` numbers for both rather than invent one.
The true spend comes back from the API in `x-fashn-credits-used` and is what
history records; this table is only ever an estimate shown before the run.

The latency table is ours: it exists to calibrate the progress readout so the
bar moves at a believable rate instead of crawling and then jumping.
"""

MATRIX = {
    "balanced": {"1k": 2, "2k": 3, "4k": 4},
    "quality": {"1k": 3, "2k": 4, "4k": 5},
}

LATENCY = {
    "balanced": {"1k": 20, "2k": 30, "4k": 45},
    "quality": {"1k": 30, "2k": 45, "4k": 70},
}

GENERATION_MODES = ("balanced", "quality")
RESOLUTIONS = ("1k", "2k", "4k")

# The rungs the UI offers. Advanced can still land between them, which is why
# the studio shows "custom" rather than pretending a preset is selected.
QUALITY_PRESETS = [
    {"id": "draft", "label": "Draft", "generationMode": "balanced",
     "resolution": "1k", "note": "1 MP · 2 cr"},
    {"id": "standard", "label": "Standard", "generationMode": "balanced",
     "resolution": "2k", "note": "4 MP · 3 cr"},
    {"id": "final", "label": "Final", "generationMode": "quality",
     "resolution": "4k", "note": "16 MP · 5 cr"},
]


def _clamp_images(num_images):
    try:
        count = int(num_images)
    except (TypeError, ValueError):
        count = 1
    return max(1, min(4, count))


def normalize_mode(mode):
    """`fast` is not a tryon-max mode; it lands on the cheapest real one."""
    return mode if mode in MATRIX else "balanced"


def normalize_resolution(resolution):
    return resolution if resolution in RESOLUTIONS else "1k"


def credit_cost(mode, resolution, num_images=1):
    mode = normalize_mode(mode)
    resolution = normalize_resolution(resolution)
    return MATRIX[mode][resolution] * _clamp_images(num_images)


def expected_seconds(mode, resolution, num_images=1):
    """Extra images are batched rather than serialised — about 35% each."""
    base = LATENCY[normalize_mode(mode)][normalize_resolution(resolution)]
    return int(round(base * (1 + 0.35 * (_clamp_images(num_images) - 1))))


def match_preset(mode, resolution):
    for preset in QUALITY_PRESETS:
        if preset["generationMode"] == mode and preset["resolution"] == resolution:
            return preset["id"]
    return None
