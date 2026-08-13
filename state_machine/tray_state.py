IDLE = "IDLE"
TRAY_PICKED = "TRAY_PICKED"
TRAY_IN_TRANSIT = "TRAY_IN_TRANSIT"
TRAY_ON_TABLE = "TRAY_ON_TABLE"


class TrayStateMachine:
    def __init__(self):
        self._states = {}

    def update(self, visible_this_frame: dict) -> list:
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
