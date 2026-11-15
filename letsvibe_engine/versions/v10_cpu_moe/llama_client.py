"""OpenAI-compatible client for llama.cpp server running --cpu-moe."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


DEFAULT_LLAMA_URL = "http://127.0.0.1:11435"
DEFAULT_MODEL_NAME = "qwen3-30b-a3b"


def _strip_thinking_and_fences(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _parse_json_payload(raw_text: str) -> Dict[str, Any]:
    cleaned = _strip_thinking_and_fences(raw_text)
    if cleaned.startswith("{{"):
        cleaned = cleaned[1:].lstrip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    idx = cleaned.find("{")
    while idx != -1:
        try:
            obj, _end = decoder.raw_decode(cleaned, idx)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        idx = cleaned.find("{", idx + 1)
    raise ValueError(f"Expected JSON object from llama-server, got: {cleaned[:240]}")


class LlamaMoeClient:
    """Calls a local CUDA + --cpu-moe llama-server over HTTP."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_sec: float = 240.0,
        cancel_check_client: Any = None,
        deadline_monotonic: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("LETSVIBE_LLAMA_URL") or DEFAULT_LLAMA_URL).rstrip("/")
        self.model = model or os.environ.get("LETSVIBE_LLAMA_MODEL_NAME") or DEFAULT_MODEL_NAME
        self.timeout_sec = timeout_sec
        self.cancel_check_client = cancel_check_client
        self.deadline_monotonic = deadline_monotonic
        self.calls: List[Dict[str, Any]] = []

    def check_health(self) -> None:
        req = urllib.request.Request(f"{self.base_url}/health", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"llama-server /health returned HTTP {resp.status}")
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"v10 requires llama-server (--cpu-moe) at {self.base_url}, but it is unreachable: {exc}. "
                f"Start it with `letsvibe-llama-server`."
            ) from exc

    def check_guards(self) -> None:
        if self.deadline_monotonic is not None and time.monotonic() > self.deadline_monotonic:
            raise TimeoutError("Engine v10 evaluation exceeded time limit")
        cb = getattr(self.cancel_check_client, "check_cancelled", None)
        if callable(cb):
            cb()

    def generate_json(
        self,
        stage: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1800,
        temperature: float = 0.15,
    ) -> Dict[str, Any]:
        self.check_guards()
        prompt = (
            f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
            f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n<think>\n\n</think>\n\n{{"
        )
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "cache_prompt": False,
            "stop": ["<|im_end|>", "<|endoftext|>"],
        }
        body = json.dumps(payload).encode("utf-8")

        last_err: Optional[Exception] = None
        for attempt in range(2):
            self.check_guards()
            t0 = time.perf_counter()
            req = urllib.request.Request(
                f"{self.base_url}/completion",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                elapsed = round(time.perf_counter() - t0, 2)
                content = "{" + (raw.get("content") or "")
                parsed = _parse_json_payload(content)
                timings = raw.get("timings") or {}
                self.calls.append(
                    {
                        "stage": stage,
                        "attempt": attempt + 1,
                        "elapsed_sec": elapsed,
                        "prompt_tokens": timings.get("prompt_n") or raw.get("tokens_evaluated") or 0,
                        "completion_tokens": timings.get("predicted_n") or raw.get("tokens_predicted") or 0,
                        "prompt_tok_s": round(float(timings.get("prompt_per_second") or 0.0), 1),
                        "gen_tok_s": round(float(timings.get("predicted_per_second") or 0.0), 1),
                        "finish_reason": raw.get("stop_type") or ("stop" if raw.get("stopped_eos") else "length"),
                    }
                )
                return parsed
            except Exception as exc:
                last_err = exc
                if attempt == 0:
                    continue
        raise RuntimeError(f"llama-server call failed in stage '{stage}': {last_err}") from last_err

    def summary(self) -> Dict[str, Any]:
        total_prompt = sum(c["prompt_tokens"] for c in self.calls)
        total_comp = sum(c["completion_tokens"] for c in self.calls)
        total_sec = round(sum(c["elapsed_sec"] for c in self.calls), 2)
        avg_prompt_tps = (
            round(sum(c["prompt_tok_s"] for c in self.calls) / len(self.calls), 1) if self.calls else 0.0
        )
        avg_gen_tps = (
            round(sum(c["gen_tok_s"] for c in self.calls) / len(self.calls), 1) if self.calls else 0.0
        )
        return {
            "llama_calls": len(self.calls),
            "llama_prompt_tokens": total_prompt,
            "llama_completion_tokens": total_comp,
            "llama_infer_sec": total_sec,
            "llama_avg_prompt_tok_s": avg_prompt_tps,
            "llama_avg_gen_tok_s": avg_gen_tps,
            "llama_call_log": self.calls,
        }
