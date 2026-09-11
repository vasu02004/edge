def check_wrong_tray(picked_label: str, verifier, registry):
    vault_number = registry.vault_number
    shelf_number = registry.shelf_number_for(picked_label)

    try:
        active_location = verifier.get_active_location(picked_label, vault_number, shelf_number)
    except Exception as e:
        return "ASSIGNMENT_LOOKUP_FAILED", {"picked": picked_label, "reason": str(e)}

    if active_location is None:
        return "NO_ACTIVE_ASSIGNMENT", {"picked": picked_label}

    active_vault, active_shelf = active_location
    expected_label = registry.label_for_location(active_vault, active_shelf)

    if expected_label != picked_label:
        return "WRONG_TRAY", {"picked": picked_label, "expected": expected_label}

    return None, {"picked": picked_label, "expected": expected_label}
