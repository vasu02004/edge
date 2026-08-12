import cv2

from config import ARUCO_DICTIONARY


class ArucoDetector:
    """Detects ArUco markers in a frame: ID, 4 corners, centroid per marker."""

    def __init__(self, dictionary_name: str = ARUCO_DICTIONARY):
        dict_id = getattr(cv2.aruco, dictionary_name)
        self.dictionary = cv2.aruco.getPredefinedDictionary(dict_id)
        self.parameters = cv2.aruco.DetectorParameters()
        self.detector = cv2.aruco.ArucoDetector(self.dictionary, self.parameters)

    def detect(self, frame):
        corners, ids, _rejected = self.detector.detectMarkers(frame)
        results = []
        if ids is not None:
            for marker_corners, marker_id in zip(corners, ids.flatten()):
                pts = marker_corners.reshape(4, 2)
                centroid = pts.mean(axis=0)
                results.append(
                    {
                        "id": int(marker_id),
                        "corners": pts,
                        "centroid": (float(centroid[0]), float(centroid[1])),
                    }
                )
        return results
