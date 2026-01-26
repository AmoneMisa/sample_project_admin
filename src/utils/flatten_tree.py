def flatten_tree(tree: dict, prefix: str = "") -> dict:
    flat = {}

    for key, value in tree.items():
        full_key = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            flat.update(flatten_tree(value, full_key))
        else:
            flat[full_key] = value

    return flat
