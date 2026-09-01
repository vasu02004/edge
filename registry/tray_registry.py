import json

from config import TRAY_REGISTRY_PATH


class TrayRegistry:
    def __init__(self, path: str = TRAY_REGISTRY_PATH):
        with open(path) as f:
            data = json.load(f)

        self.branch_id = data.get("branch_id")
        self.vault_number = data.get("vault_number")
        self._id_to_label = {}
        self._label_to_id = {}
        self._shelf_to_label = {}
        self._label_to_shelf = {}
        for entry in data.get("trays", []):
            aruco_id = int(entry["aruco_id"])
            label = entry["tray_label"]
            self._id_to_label[aruco_id] = label
            self._label_to_id[label] = aruco_id
            if "shelf_number" in entry:
                shelf_number = int(entry["shelf_number"])
                self._shelf_to_label[shelf_number] = label
                self._label_to_shelf[label] = shelf_number

    def label_for(self, aruco_id: int):
        return self._id_to_label.get(aruco_id)

    def aruco_id_for(self, tray_label: str):
        return self._label_to_id.get(tray_label)

    def label_for_location(self, vault_number: int, shelf_number: int):
        if self.vault_number is not None and int(vault_number) != self.vault_number:
            return None
        return self._shelf_to_label.get(int(shelf_number))

    def shelf_number_for(self, tray_label: str):
        return self._label_to_shelf.get(tray_label)

    def is_registered(self, aruco_id: int) -> bool:
        return aruco_id in self._id_to_label

    def registered_labels(self):
        return sorted(self._label_to_id)
