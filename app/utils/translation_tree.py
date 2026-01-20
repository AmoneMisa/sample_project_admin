def build_tree(flat: dict) -> dict:
    tree = {}

    for key, value in flat.items():
        parts = key.split(".")
        current = tree

        for part in parts[:-1]:
            current = current.setdefault(part, {})

        current[parts[-1]] = value

    return tree
