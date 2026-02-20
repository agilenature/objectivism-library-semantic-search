"""FSM state and transition constants for the file lifecycle."""

# Valid states for gemini_state column
VALID_STATES = frozenset({
    "untracked",
    "uploading",
    "processing",
    "indexed",
    "failed",
})

# Valid state transitions (from_state, to_state)
VALID_EDGES = frozenset({
    ("untracked", "uploading"),
    ("uploading", "processing"),
    ("processing", "indexed"),
    ("uploading", "failed"),
    ("processing", "failed"),
})

# Event names mapped to (from_state, to_state)
EVENTS = {
    "start_upload": ("untracked", "uploading"),
    "complete_upload": ("uploading", "processing"),
    "complete_processing": ("processing", "indexed"),
    "fail_upload": ("uploading", "failed"),
    "fail_processing": ("processing", "failed"),
}

# Reverse lookup: from_state -> list of valid events
EVENTS_FROM_STATE = {}
for event_name, (from_state, _to_state) in EVENTS.items():
    EVENTS_FROM_STATE.setdefault(from_state, []).append(event_name)
