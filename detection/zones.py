import json

import cv2
import numpy as np

from config import ZONE_CONFIG_PATH


class ZoneChecker:
    BOUNDARY_ZONE_NAME = "boundary"

    def __init__(self, path: str = ZONE_CONFIG_PATH):
        with open(path) as f:
            data = json.load(f)

        self.branch_id = data.get("branch_id")
        self._polygons = {
            name: np.array(points, dtype=np.int32) for name, points in data.get("zones", {}).items()
        }

    def combined_boundary(self):
        return self._polygons.get(self.BOUNDARY_ZONE_NAME)

    def is_within_boundary(self, centroid) -> bool:
        boundary = self.combined_boundary()
        if boundary is None:
            return True
        x, y = centroid
        return cv2.pointPolygonTest(boundary, (float(x), float(y)), False) >= 0

    def classify(self, centroid) -> str:
        x, y = centroid
        for zone_name, polygon in self._polygons.items():
            if zone_name == self.BOUNDARY_ZONE_NAME:
                continue
            if cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= 0:
                return self._label_for(zone_name)
        return "TRANSIT"

    @staticmethod
    def _label_for(zone_name: str) -> str:
        return zone_name.replace("_zone", "").upper()

    def polygon(self, zone_name: str):
        return self._polygons.get(zone_name)
