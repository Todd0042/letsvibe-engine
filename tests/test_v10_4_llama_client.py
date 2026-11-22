"""v10.4 client: an answer cut off at the token limit is asked again with more room, never salvaged in part.

Against a stand-in llama-server on a local port that cuts off the first answer the way the real one does
(stop_type "limit"), leaving JSON whose inner objects still parse."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from letsvibe_engine.versions.v10_4_verified.llama_client import MAX_ANSWER_TOKENS, LlamaMoeClient

FULL = '"checklist": {"value": {"tier": "TIER_3"}, "journey": {"setup_burden": "NONE"}}, "factors": {}}'
CUT = '"checklist": {"value": {"tier": "TIER_3"}, "journ'


def _server(replies):
    asked = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            asked.append(body["n_predict"])
            content, stop = replies[min(len(asked) - 1, len(replies) - 1)]
            out = json.dumps({"content": content, "stop_type": stop, "timings": {"prompt_n": 10, "predicted_n": 5}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, asked


def test_cut_off_answer_is_asked_again_with_more_room():
    srv, asked = _server([(CUT, "limit"), (FULL, "eos")])
    try:
        client = LlamaMoeClient(base_url=f"http://127.0.0.1:{srv.server_port}")
        out = client.generate_json("scoring_checklist", "sys", "user", max_tokens=1800)
    finally:
        srv.shutdown()
    assert set(out["checklist"]) == {"value", "journey"}  # the whole answer, not the {"tier": ...} piece of it
    assert asked[0] == 1800 and asked[1] > 1800 and asked[1] <= MAX_ANSWER_TOKENS
    assert any("cut off" in str(c.get("finish_reason")) for c in client.calls)


def test_always_cut_off_fails_instead_of_returning_a_piece():
    srv, asked = _server([(CUT, "limit")])
    try:
        client = LlamaMoeClient(base_url=f"http://127.0.0.1:{srv.server_port}")
        with pytest.raises(RuntimeError, match="cut off"):
            client.generate_json("scoring_checklist", "sys", "user", max_tokens=1800)
    finally:
        srv.shutdown()
    assert len(asked) == 3 and asked == sorted(asked)  # three tries, each with more room
