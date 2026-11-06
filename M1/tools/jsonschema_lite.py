"""A small, dependency-free JSON Schema checker (the subset ClaimSense schemas use).

Supported keywords: type (incl. type lists), required, properties, additionalProperties (bool),
enum, const, pattern, format (date, date-time, uuid), minimum, maximum, minLength, items,
minItems, uniqueItems, oneOf, $ref (local "#/$defs/..." only).

Kept stdlib-only so validation runs in CI and on any laptop with no installs ($0 floor). The
schemas themselves are standard draft 2020-12, so they also validate with the `jsonschema` package.
"""
import re
from datetime import date, datetime

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _is_type(value, t):
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[t])


def _check_format(value, fmt):
    try:
        if fmt == "date":
            date.fromisoformat(value)
        elif fmt == "date-time":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif fmt == "uuid":
            return bool(_UUID.match(value))
    except (ValueError, TypeError):
        return False
    return True


def validate(value, schema, root=None, path="$"):
    """Return a list of error strings (empty list = valid)."""
    root = root or schema
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/$defs/"), f"only local refs supported: {ref}"
        return validate(value, root["$defs"][ref.split("/")[-1]], root, path)
    errs = []
    if "oneOf" in schema:
        matches = [s for s in schema["oneOf"] if not validate(value, s, root, path)]
        if len(matches) != 1:
            errs.append(f"{path}: must match exactly one schema in oneOf (matched {len(matches)})")
        return errs
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, t) for t in types):
            return [f"{path}: expected {'/'.join(types)}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: {value!r} does not match /{schema['pattern']}/")
        if "format" in schema and not _check_format(value, schema["format"]):
            errs.append(f"{path}: {value!r} is not a valid {schema['format']}")
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{path}: shorter than {schema['minLength']}")
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}: missing required '{k}'")
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                errs += validate(v, props[k], root, f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected property '{k}'")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if schema.get("uniqueItems") and len({repr(x) for x in value}) != len(value):
            errs.append(f"{path}: items must be unique")
        if "items" in schema:
            for i, item in enumerate(value):
                errs += validate(item, schema["items"], root, f"{path}[{i}]")
    return errs
