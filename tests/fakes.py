"""A stand-in for the Anthropic client. It answers from the request text, never the network."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS


def answer(params: dict) -> dict:
    system = params["system"][0]["text"]
    user = params["messages"][0]["content"]
    schema = params["output_config"]["format"]["schema"]
    if "label" in schema["properties"]:
        if "Never Gonna" in user:
            return {"label": "joke"}
        if "must watch" in user.lower():
            return {"label": "strong_recommendation"}
        if "wrong" in user.lower():
            return {"label": "criticism"}
        return {"label": "recommendation"}
    facets = schema["properties"]["facets"]["items"]["enum"]
    assert "Who we are" in system
    if "transformer" in user.lower() or "gpt" in user.lower():
        return {"summary": "A lecture that builds a GPT from scratch.", "why": "First-principles LLM internals.",
                "facets": [facets[0], facets[1]], "fit": 3, "category": "AI & Machine Learning", "kind": "lecture"}
    if "raft" in user.lower():
        return {"summary": "A talk on the Raft consensus algorithm.", "why": "Clear consensus intuition.",
                "facets": ["systems"], "fit": 2, "category": "Systems & Infrastructure", "kind": "talk"}
    return {"summary": "A music video.", "why": "", "facets": [], "fit": 0,
            "category": "Music", "kind": "music"}


def message(params: dict):
    return NS(
        content=[NS(type="text", text=json.dumps(answer(params)))],
        usage=NS(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0),
        stop_reason="end_turn",
    )


class FakeBatches:
    def __init__(self):
        self.store: dict[str, list] = {}
        self.created = 0
        self.polls = 0

    def create(self, requests):
        self.created += 1
        bid = f"msgbatch_{self.created:04d}"
        for r in requests:
            assert len(r["custom_id"]) <= 64
            assert "stream" not in r["params"]
        ids = [r["custom_id"] for r in requests]
        assert len(ids) == len(set(ids)), "custom_id must be unique in a batch"
        self.store[bid] = requests
        return NS(id=bid)

    def retrieve(self, bid):
        self.polls += 1
        n = len(self.store[bid])
        return NS(processing_status="ended",
                  request_counts=NS(succeeded=n, errored=0, processing=0, canceled=0, expired=0))

    def results(self, bid):
        for r in self.store[bid]:
            yield NS(custom_id=r["custom_id"], result=NS(type="succeeded", message=message(r["params"])))


class FakeMessages:
    def __init__(self):
        self.batches = FakeBatches()
        self.sync_calls = 0

    def create(self, extra_body=None, **params):
        self.sync_calls += 1
        params["output_config"] = extra_body["output_config"]
        return message(params)


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()
