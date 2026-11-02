"""Run many small Claude calls cheaply and safely.

- Message Batches API: half price; most batches finish within an hour.
- Prompt caching: the shared system prompt is cached for 1 hour across the batch.
- Structured outputs: every answer is JSON that matches a schema.
- A result cache in SQLite: a re-run never pays twice for the same input.
- Batch IDs are saved before we wait, so a killed run resumes instead of re-sending.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass

# USD per million tokens, Batch API rates, checked 2026-11-02 on
# https://platform.claude.com/docs/en/about-claude/pricing (Haiku: prompts <= 100K tokens).
BATCH_PRICE = {
    "claude-haiku-5-5": (0.05, 0.25),
    "claude-sonnet-5-5": (1.00, 5.00),
    "claude-opus-5-5": (2.00, 10.00),
}
CHUNK = 5_000  # requests per batch; the API allows 100,000 and 256 MB


@dataclass
class Job:
    key: str
    user: str


def make_key(kind: str, model: str, system: str, user: str) -> str:
    return hashlib.sha1(f"{kind}\x00{model}\x00{system}\x00{user}".encode()).hexdigest()


def _params(model: str, system: str, user: str, schema: dict, max_tokens: int) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        "messages": [{"role": "user", "content": user}],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }


def _text(message) -> str:
    for block in message.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise ValueError(f"no text block (stop_reason={getattr(message, 'stop_reason', '?')})")


class Runner:
    def __init__(self, con: sqlite3.Connection, client=None, poll_seconds: int = 30):
        self.con = con
        self._client = client
        self.poll = poll_seconds

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def cached(self, keys: list[str]) -> dict[str, dict]:
        out = {}
        for i in range(0, len(keys), 900):
            part = keys[i : i + 900]
            q = f"SELECT key, result FROM llm_cache WHERE key IN ({','.join('?' * len(part))})"
            out.update({k: json.loads(r) for k, r in self.con.execute(q, part)})
        return out

    def _save(self, kind: str, key: str, message) -> bool:
        try:
            result = json.loads(_text(message))
        except (ValueError, json.JSONDecodeError):
            return False
        u = getattr(message, "usage", None)
        tin = (getattr(u, "input_tokens", 0) or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) + (
            getattr(u, "cache_creation_input_tokens", 0) or 0
        )
        self.con.execute(
            "INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?,?)",
            (key, kind, json.dumps(result), tin, getattr(u, "output_tokens", 0) or 0),
        )
        return True

    def run(
        self,
        kind: str,
        model: str,
        system: str,
        jobs: list[Job],
        schema: dict,
        max_tokens: int,
        mode: str = "batch",
        confirm: bool = True,
    ) -> dict[str, dict]:
        """Return {key: parsed JSON} for every job that has (or now gets) an answer."""
        keys = [j.key for j in jobs]
        self._resume(kind)
        done = self.cached(keys)
        # custom_id must be unique inside a batch, so drop duplicate inputs.
        todo = list({j.key: j for j in jobs if j.key not in done}.values())
        if todo:
            est_in = sum(len(system) + len(j.user) for j in todo) / 3.5 / 1e6
            est_out = len(todo) * max_tokens * 0.6 / 1e6
            pin, pout = BATCH_PRICE.get(model, (0, 0))
            if mode == "sync":
                pin, pout = pin * 2, pout * 2
            print(
                f"{kind}: {len(todo):,} new calls to {model} ({len(jobs) - len(todo):,} cached); "
                f"about {est_in:.1f}M input tokens, worst case ~${est_in * pin + est_out * pout:.2f}"
            )
            if confirm and input("Send? [y/N] ").strip().lower() != "y":
                raise SystemExit("Stopped. Nothing was sent.")
            if mode == "sync":
                self._sync(kind, model, system, todo, schema, max_tokens)
            else:
                self._batch(kind, model, system, todo, schema, max_tokens)
        return self.cached(keys)

    def _sync(self, kind, model, system, todo, schema, max_tokens):
        for i, j in enumerate(todo, 1):
            p = _params(model, system, j.user, schema, max_tokens)
            # extra_body works on every SDK version, old or new.
            msg = self.client.messages.create(
                **{k: v for k, v in p.items() if k != "output_config"},
                extra_body={"output_config": p["output_config"]},
            )
            self._save(kind, j.key, msg)
            self.con.commit()
            print(f"\r{kind}: {i:,}/{len(todo):,}", end="", flush=True)
        print()

    def _batch(self, kind, model, system, todo, schema, max_tokens):
        for i in range(0, len(todo), CHUNK):
            part = todo[i : i + CHUNK]
            batch = self.client.messages.batches.create(
                requests=[
                    {"custom_id": j.key, "params": _params(model, system, j.user, schema, max_tokens)}
                    for j in part
                ]
            )
            self.con.execute("INSERT INTO batches VALUES (?,?,?,?)", (batch.id, kind, len(part), int(time.time())))
            self.con.commit()
            print(f"{kind}: sent batch {batch.id} ({len(part):,} requests)")
        self._resume(kind)

    def _resume(self, kind: str) -> None:
        """Wait for every open batch of this kind and store its results."""
        open_ids = [r[0] for r in self.con.execute("SELECT id FROM batches WHERE kind = ?", (kind,))]
        for bid in open_ids:
            while True:
                b = self.client.messages.batches.retrieve(bid)
                c = b.request_counts
                print(
                    f"\r{kind}: batch {bid[-8:]} {b.processing_status} | done {c.succeeded:,} "
                    f"| errors {c.errored:,} | waiting {c.processing:,}",
                    end="",
                    flush=True,
                )
                if b.processing_status == "ended":
                    break
                time.sleep(self.poll)
            print()
            ok = bad = 0
            for res in self.client.messages.batches.results(bid):
                if res.result.type == "succeeded" and self._save(kind, res.custom_id, res.result.message):
                    ok += 1
                else:
                    bad += 1
            self.con.execute("DELETE FROM batches WHERE id = ?", (bid,))
            self.con.commit()
            if bad:
                print(f"{kind}: {bad:,} requests failed or expired; re-run this stage to retry only those")

    def usage(self, kind: str) -> tuple[int, int, int]:
        row = self.con.execute(
            "SELECT COUNT(*), COALESCE(SUM(in_tokens),0), COALESCE(SUM(out_tokens),0) FROM llm_cache WHERE kind = ?",
            (kind,),
        ).fetchone()
        return tuple(row)
