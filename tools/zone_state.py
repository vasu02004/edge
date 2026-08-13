class ZoneAnnotatorState:
    def __init__(self, zone_names):
        self.zone_names = list(zone_names)
        self._zones = {name: [] for name in self.zone_names}
        self._current_index = 0

    @property
    def current_zone_name(self):
        if self._current_index >= len(self.zone_names):
            return None
        return self.zone_names[self._current_index]

    def points_for(self, name):
        return list(self._zones[name])

    def add_point(self, x, y) -> bool:
        name = self.current_zone_name
        if name is None:
            return False
        self._zones[name].append([int(x), int(y)])
        return True

    def undo_last_point(self) -> bool:
        name = self.current_zone_name
        if name and self._zones[name]:
            self._zones[name].pop()
            return True
        return False

    def finish_current_zone(self) -> bool:
        name = self.current_zone_name
        if name is None or len(self._zones[name]) < 3:
            return False
        self._current_index += 1
        return True

    def is_complete(self) -> bool:
        return self._current_index >= len(self.zone_names)

    def to_dict(self, branch_id: str) -> dict:
        return {
            "branch_id": branch_id,
            "zones": {name: self._zones[name] for name in self.zone_names},
        }
