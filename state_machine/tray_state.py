import time

IDLE = "IDLE"
TRAY_IN_TRANSIT = "TRAY_IN_TRANSIT"
TRAY_ON_TABLE = "TRAY_ON_TABLE"


class TrayStateMachine:
    def __init__(self):
        self._states = {}
        self._left_vault_at = {}

    def update(self, visible_this_frame: dict) -> list:
        """Returns a list of (label, old_state, new_state, duration_out_seconds)
        transitions. duration_out_seconds is None except when new_state is IDLE
        after having left it (i.e. the tray just returned to the vault), in which
        case it's how long the tray was away."""
        transitions = []

        for label, zone in visible_this_frame.items():
            state = self._states.get(label, IDLE)
            new_state = state

            if state == IDLE and zone == "TRANSIT":
                new_state = TRAY_IN_TRANSIT
            elif state == IDLE and zone == "TABLE":
                # First-ever sighting is already outside the vault (e.g. camera
                # started, or a tray was placed before it came online) — without
                # this, the tray silently stays IDLE forever and never reaches
                # the wrong-tray/alert check at all.
                new_state = TRAY_ON_TABLE
            elif state == TRAY_IN_TRANSIT and zone == "TABLE":
                new_state = TRAY_ON_TABLE
            elif state == TRAY_IN_TRANSIT and zone == "VAULT":
                new_state = IDLE
            elif state == TRAY_ON_TABLE and zone != "TABLE":
                new_state = IDLE

            if new_state != state:
                duration_out = None
                if state == IDLE and new_state != IDLE:
                    self._left_vault_at[label] = time.monotonic()
                elif new_state == IDLE and label in self._left_vault_at:
                    duration_out = time.monotonic() - self._left_vault_at.pop(label)

                transitions.append((label, state, new_state, duration_out))
                self._states[label] = new_state

        return transitions

    def state_for(self, tray_label: str) -> str:
        return self._states.get(tray_label, IDLE)

    def reset(self):
        """Clears all tracked per-tray state. Call at the end of the active-hours
        window so a tray that never made it back to IDLE that day (camera miss,
        occlusion, etc.) doesn't leave a stale _left_vault_at timestamp sitting
        around into the next day's session."""
        self._states.clear()
        self._left_vault_at.clear()
