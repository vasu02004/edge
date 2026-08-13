from aurus_guard.client import get_expected_tray_label


def check_wrong_tray(picked_label: str, client, registry):
    try:
        expected_label = get_expected_tray_label(client, registry)
    except Exception as e:
        return "ASSIGNMENT_LOOKUP_FAILED", {"picked": picked_label, "reason": str(e)}

    if expected_label is None:
        return "NO_ACTIVE_ASSIGNMENT", {"picked": picked_label}

    if expected_label != picked_label:
        return "WRONG_TRAY", {"picked": picked_label, "expected": expected_label}

    return None, {"picked": picked_label, "expected": expected_label}
