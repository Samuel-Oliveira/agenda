#!/usr/bin/env python3
"""Exporta o GitHub Project (v2) do usuário para agenda.json.

Inclui as views pedidas (nome + filtro) e todos os itens com seus campos,
para que a tarefa agendada do Claude aplique o filtro de cada view.

Variáveis de ambiente:
  GH_TOKEN        PAT com leitura de Projects (classic: read:project + repo)
  PROJECT_OWNER   ex.: Samuel-Oliveira
  PROJECT_NUMBER  ex.: 2
  VIEW_NUMBERS    ex.: 7,11
"""
import json
import os
import subprocess
from datetime import datetime, timezone, timedelta

OWNER = os.environ.get("PROJECT_OWNER", "Samuel-Oliveira")
NUMBER = int(os.environ.get("PROJECT_NUMBER", "2"))
VIEWS = {int(v) for v in os.environ.get("VIEW_NUMBERS", "7,11").split(",") if v.strip()}

FIELD = "field { ... on ProjectV2FieldCommon { name } }"
QUERY = f"""
query($owner: String!, $number: Int!, $after: String) {{
  user(login: $owner) {{
    projectV2(number: $number) {{
      title
      url
      fields(first: 50) {{ nodes {{ ... on ProjectV2FieldCommon {{ name dataType }} }} }}
      views(first: 50) {{ nodes {{ number name filter layout }} }}
      items(first: 100, after: $after) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{
          id
          type
          isArchived
          content {{
            __typename
            ... on Issue {{ title url number state body repository {{ nameWithOwner }}
                           assignees(first: 10) {{ nodes {{ login }} }}
                           labels(first: 20) {{ nodes {{ name }} }} }}
            ... on PullRequest {{ title url number state repository {{ nameWithOwner }} }}
            ... on DraftIssue {{ title body }}
          }}
          fieldValues(first: 50) {{
            nodes {{
              __typename
              ... on ProjectV2ItemFieldDateValue {{ date {FIELD} }}
              ... on ProjectV2ItemFieldSingleSelectValue {{ name {FIELD} }}
              ... on ProjectV2ItemFieldTextValue {{ text {FIELD} }}
              ... on ProjectV2ItemFieldNumberValue {{ number {FIELD} }}
              ... on ProjectV2ItemFieldIterationValue {{ title startDate duration {FIELD} }}
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""


def gql(after):
    cmd = ["gh", "api", "graphql", "-f", f"query={QUERY}",
           "-f", f"owner={OWNER}", "-F", f"number={NUMBER}"]
    if after:
        cmd += ["-f", f"after={after}"]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return json.loads(out)["data"]["user"]["projectV2"]


def flatten(node):
    fields = {}
    for fv in node["fieldValues"]["nodes"]:
        name = (fv.get("field") or {}).get("name")
        if not name:
            continue
        t = fv["__typename"]
        if t.endswith("DateValue"):
            fields[name] = fv["date"]
        elif t.endswith("SingleSelectValue"):
            fields[name] = fv["name"]
        elif t.endswith("TextValue"):
            fields[name] = fv["text"]
        elif t.endswith("NumberValue"):
            fields[name] = fv["number"]
        elif t.endswith("IterationValue"):
            fields[name] = {"title": fv["title"], "startDate": fv["startDate"],
                            "duration": fv["duration"]}
    c = node.get("content") or {}
    return {
        "type": node["type"],
        "archived": node["isArchived"],
        "title": c.get("title") or fields.get("Title"),
        "url": c.get("url"),
        "state": c.get("state"),
        "repository": (c.get("repository") or {}).get("nameWithOwner"),
        "assignees": [a["login"] for a in (c.get("assignees") or {}).get("nodes", [])],
        "labels": [l["name"] for l in (c.get("labels") or {}).get("nodes", [])],
        "body": (c.get("body") or "")[:500],
        "fields": fields,
    }


def main():
    items, after, meta = [], None, None
    while True:
        p = gql(after)
        meta = meta or p
        items += [flatten(n) for n in p["items"]["nodes"]]
        if not p["items"]["pageInfo"]["hasNextPage"]:
            break
        after = p["items"]["pageInfo"]["endCursor"]

    brt = timezone(timedelta(hours=-3))
    data = {
        "generated_at": datetime.now(brt).isoformat(timespec="seconds"),
        "project": {"title": meta["title"], "url": meta["url"]},
        "fields": [f for f in meta["fields"]["nodes"] if f],
        "views": [v for v in meta["views"]["nodes"] if v["number"] in VIEWS],
        "items": [i for i in items if not i["archived"]],
    }
    with open("agenda.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"{len(data['items'])} itens, views: {[v['name'] for v in data['views']]}")


if __name__ == "__main__":
    main()
