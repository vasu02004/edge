from aurus_guard.client import get_expected_tray_label


def check_wrong_tray(picked_label: str, client, registry):
    """Called the moment a tray transitions to TRAY_PICKED. Looks up the
    currently-assigned tray from aurus-guard (once, not per-frame) and
    compares it against what was actually picked.

    Returns (event_type, details) where event_type is one of:
      - None                    -- correct pickup, matches the assignment
      - "WRONG_TRAY"            -- picked a different tray than assigned
      - "NO_ACTIVE_ASSIGNMENT"  -- nothing is currently assigned at all
      - "ASSIGNMENT_LOOKUP_FAILED" -- couldn't reach aurus-guard (network,
        timeout, etc.) -- don't crash the detection loop over this.
    details is a dict of whatever's relevant to that event, for the caller
    to log/format however it wants.
    """
    try:
        expected_label = get_expected_tray_label(client, registry)
    except Exception as e:
        return "ASSIGNMENT_LOOKUP_FAILED", {"picked": picked_label, "reason": str(e)}

    if expected_label is None:
        return "NO_ACTIVE_ASSIGNMENT", {"picked": picked_label}

    if expected_label != picked_label:
        return "WRONG_TRAY", {"picked": picked_label, "expected": expected_label}

    return None, {"picked": picked_label, "expected": expected_label}
