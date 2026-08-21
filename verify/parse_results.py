#!/usr/bin/env python3
"""Parses pytest's built-in JUnit XML report into results.json:
{"tests": {"<test_id>": "passed" | "failed", ...}}. Skipped tests are
omitted -- they're neither a pass nor a failure for regression purposes.
"""

import json
import sys
import xml.etree.ElementTree as ET


def main() -> None:
    xml_path, json_path = sys.argv[1], sys.argv[2]
    tests: dict[str, str] = {}
    try:
        root = ET.parse(xml_path).getroot()
    except (FileNotFoundError, ET.ParseError):
        # collection error before any test ran, or the suite never produced
        # a report at all -- an empty result set, not a crash.
        with open(json_path, "w") as f:
            json.dump({"tests": {}, "patch_applied": True}, f)
        return

    for testcase in root.iter("testcase"):
        classname = testcase.get("classname", "")
        name = testcase.get("name", "")
        test_id = f"{classname}::{name}" if classname else name
        if testcase.find("skipped") is not None:
            continue
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            tests[test_id] = "failed"
        else:
            tests[test_id] = "passed"

    with open(json_path, "w") as f:
        json.dump({"tests": tests, "patch_applied": True}, f)


if __name__ == "__main__":
    main()
