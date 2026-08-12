import json

from config import TRAY_REGISTRY_PATH


class TrayRegistry:
    """Maps ArUco marker ID <-> tray label (e.g. 0 <-> 'S1') for one branch.

    Any ArUco ID not present here is not one of this branch's registered
    trays — callers should treat it as noise and ignore it, not log it.
    """

    def __init__(self, path: str = TRAY_REGISTRY_PATH):
        with open(path) as f:
            data = json.load(f)

        self.branch_id = data.get("branch_id")
        self._id_to_label = {}
        self._label_to_id = {}
        self._location_to_label = {}  # (vault_number, shelf_number) -> tray_label
        for entry in data.get("trays", []):
            aruco_id = int(entry["aruco_id"])
            label = entry["tray_label"]
            self._id_to_label[aruco_id] = label
            self._label_to_id[label] = aruco_id
            if "vault_number" in entry and "shelf_number" in entry:
                location = (int(entry["vault_number"]), int(entry["shelf_number"]))
                self._location_to_label[location] = label

    def label_for(self, aruco_id: int):
        return self._id_to_label.get(aruco_id)

    def aruco_id_for(self, tray_label: str):
        return self._label_to_id.get(tray_label)

    def label_for_location(self, vault_number: int, shelf_number: int):
        """aurus-guard identifies a tray by vault_number/shelf_number, not
        our ArUco-based tray_label -- this bridges the two."""
        return self._location_to_label.get((int(vault_number), int(shelf_number)))

    def is_registered(self, aruco_id: int) -> bool:
        return aruco_id in self._id_to_label

    def registered_labels(self):
        return sorted(self._label_to_id)
