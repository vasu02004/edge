IDLE = "IDLE"
TRAY_PICKED = "TRAY_PICKED"
TRAY_IN_TRANSIT = "TRAY_IN_TRANSIT"
TRAY_ON_TABLE = "TRAY_ON_TABLE"


class TrayStateMachine:
    """Per-tray IDLE -> TRAY_PICKED -> TRAY_IN_TRANSIT -> TRAY_ON_TABLE,
    driven purely by zone classification (VAULT/TABLE/TRANSIT). Log-only
    for this step -- no classifier, no alerts, no aurus-guard yet.

    Deliberate deviations from the original spec's strict pseudocode, for
    robustness against the jittery real-world detection we saw in Step 6
    (frames aren't reliably observed in sequence):
      - TRAY_PICKED + TABLE -> TRAY_ON_TABLE directly (not just via
        TRAY_IN_TRANSIT + TABLE), so a fast pickup that skips a TRANSIT
        reading between frames doesn't get stuck in TRAY_PICKED forever.
      - TRAY_PICKED or TRAY_IN_TRANSIT + VAULT -> IDLE ("put it back"),
        so an abandoned pickup resets cleanly instead of getting stuck.
      - TRAY_ON_TABLE + zone != TABLE -> IDLE ("leaving the table"), so a
        fresh pickup cycle can start once the tray moves off the table.
        This is a deliberate simplification for now: it throws away the
        "was this tray ever on the table" memory as soon as it leaves,
        which is fine while nothing downstream needs that memory yet.
        Once open/close detection + the alert rule engine (Phase B/C) are
        built, they'll need that memory to persist across this exact
        transition -- revisit this reset then, don't just reuse it as-is.

    Known limitation (not handled, same spirit as Step 6's open item):
    IDLE + TABLE with no prior TRANSIT observation does not transition --
    a tray whose very first-ever detection already sits inside table_zone
    stays IDLE. This matches the original spec (a "pick" must be observed
    via TRANSIT first) and is expected to be rare given our frame rate;
    revisit if live testing shows it happening.
    """

    def __init__(self):
        self._states = {}  # tray_label -> current state string

    def update(self, visible_this_frame: dict) -> list:
        """visible_this_frame: {tray_label: zone_str} for every registered
        marker detected this frame. Trays absent this frame are left
        untouched here -- disappearance/boundary-crossing is handled
        elsewhere (detection/zones.py's is_within_boundary()).
        Returns a list of (tray_label, old_state, new_state) for every
        transition that fired this call."""
        transitions = []

        for label, zone in visible_this_frame.items():
            state = self._states.get(label, IDLE)
            new_state = state

            if state == IDLE and zone == "TRANSIT":
                new_state = TRAY_PICKED
            elif state == TRAY_PICKED and zone == "TRANSIT":
                new_state = TRAY_IN_TRANSIT
            elif state == TRAY_PICKED and zone == "TABLE":
                new_state = TRAY_ON_TABLE
            elif state == TRAY_IN_TRANSIT and zone == "TABLE":
                new_state = TRAY_ON_TABLE
            elif state in (TRAY_PICKED, TRAY_IN_TRANSIT) and zone == "VAULT":
                new_state = IDLE
            elif state == TRAY_ON_TABLE and zone != "TABLE":
                new_state = IDLE

            if new_state != state:
                transitions.append((label, state, new_state))
                self._states[label] = new_state

        return transitions

    def state_for(self, tray_label: str) -> str:
        return self._states.get(tray_label, IDLE)
