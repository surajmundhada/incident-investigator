"""Deterministic query shaping. Values are data, never executable query syntax."""

import re

STOP = set(
    "a an the is are was were be been being do does did can could should would may might how what which when where why to of in on at for from with and or but as it its this that these those i we you me my our please help understand tell explain about into have has had not no".split()
)


def keyword_query(query):
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_:-]*", query.lower())
    words = list(dict.fromkeys(word for word in words if word not in STOP and len(word) > 1))
    words.sort(key=lambda word: (not bool(re.fullmatch(r"[1-5]\d\d", word)), "_" not in word))
    # Quoting and the bound SQL parameter prevent input from becoming tsquery syntax.
    return " OR ".join('"' + word + '"' for word in words[:14])


def incident_query(incident, logs):
    errors = [row for row in logs.get("records", []) if row.get("level") == "ERROR"]
    codes = sorted({str(row["status_code"]) for row in errors if row.get("status_code")})
    dependencies = sorted({row["dependency"] for row in errors if row.get("dependency")})
    parts = [incident["service"], " ".join(codes), " ".join(dependencies), incident["title"][:120]]
    parts.extend(row["message"][:120] for row in errors[:2])
    parts.append(incident["description"][:120])
    return " ".join(part for part in parts if part).strip()[:500]
