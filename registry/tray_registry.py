import json

from config import TRAY_REGISTRY_PATH


class TrayRegistry:
    """Maps ArUco marker ID <-> tray label (e.g. 1 <-> 'S1') for one branch.

    Any ArUco ID not present here is not one of this branch's registered
    trays — callers should treat it as noise and ignore it, not log it.

    vault_number is a single top-level value, not per-tray: every tray in
    this branch's vault shares it (confirmed with aurus-guard's side --
    aurus-guard always returns vault_number=1 for this branch). aruco_id
    is also deliberately kept equal to shelf_number for every tray (S1 =
    aruco_id 1 = shelf_number 1, etc.) -- purely a numbering convention
    for readability, not a technical requirement of either system.
    """

    def __init__(self, path: str = TRAY_REGISTRY_PATH):
        with open(path) as f:
            data = json.load(f)

        self.branch_id = data.get("branch_id")
        self.vault_number = data.get("vault_number")
        self._id_to_label = {}
        self._label_to_id = {}
        self._shelf_to_label = {}  # shelf_number -> tray_label
        for entry in data.get("trays", []):
            aruco_id = int(entry["aruco_id"])
            label = entry["tray_label"]
            self._id_to_label[aruco_id] = label
            self._label_to_id[label] = aruco_id
            if "shelf_number" in entry:
                self._shelf_to_label[int(entry["shelf_number"])] = label

    def label_for(self, aruco_id: int):
        return self._id_to_label.get(aruco_id)

    def aruco_id_for(self, tray_label: str):
        return self._label_to_id.get(tray_label)

    def label_for_location(self, vault_number: int, shelf_number: int):
        """aurus-guard identifies a tray by vault_number/shelf_number, not
        our ArUco-based tray_label -- this bridges the two. Returns None if
        vault_number doesn't match this branch's single vault, or the
        shelf isn't registered."""
        if self.vault_number is not None and int(vault_number) != self.vault_number:
            return None
        return self._shelf_to_label.get(int(shelf_number))

    def is_registered(self, aruco_id: int) -> bool:
        return aruco_id in self._id_to_label

    def registered_labels(self):
        return sorted(self._label_to_id)
