"""Safe live diagnostics: synthetic requests, no keys or provider error strings printed."""

import argparse
import json
import logging
import re

import httpx

from backend.app.core.config import get_settings


def report(response: httpx.Response) -> dict[str, object]:
    result: dict[str, object] = {"http_status": response.status_code}
    if response.is_success:
        return result
    try:
        error = response.json().get("error", {})
        status = error.get("status", "")
        if re.fullmatch(r"[A-Z_]{1,80}", status):
            result["status"] = status
        message = str(error.get("message", "")).casefold()
        for terms, category in [
            (("api key not valid", "api_key_invalid", "invalid api key"), "invalid_key"),
            (("api key expired", "key has expired"), "expired_key"),
            (("leaked",), "key_reported_leaked"),
            (("quota", "resource exhausted"), "quota_or_rate_limit"),
            (("billing",), "billing_required"),
            (("not found", "not supported for generatecontent"), "model_unavailable"),
            (("overloaded", "high demand", "capacity"), "provider_capacity"),
            (("permission", "not enabled", "restricted"), "permission_or_restriction"),
        ]:
            if any(term in message for term in terms):
                result["category"] = category
                break
        reasons = []
        for detail in error.get("details", []):
            reason = detail.get("reason", "")
            if re.fullmatch(r"[A-Z_]{1,80}", reason):
                reasons.append(reason)
        if reasons:
            result["reasons"] = reasons
    except (ValueError, TypeError, AttributeError):
        result["category"] = "unstructured_error_response"
    return result


def main() -> None:
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="Probe an alternative without changing .env")
    parser.add_argument(
        "--application", action="store_true", help="Also test the real LangChain adapter"
    )
    args = parser.parse_args()
    settings = get_settings()
    if args.model:
        settings = settings.model_copy(update={"gemini_model": args.model})
    key = settings.gemini_api_key.get_secret_value()
    print(
        json.dumps(
            {
                "configured_model": settings.gemini_model,
                "key_present": bool(key),
                "key_has_outer_whitespace": key != key.strip(),
            }
        ),
        flush=True,
    )
    if not key:
        return
    with httpx.Client(
        base_url="https://generativelanguage.googleapis.com/v1beta/",
        headers={"x-goog-api-key": key},
        timeout=30,
    ) as client:
        try:
            response = client.get("models", params={"pageSize": 1000})
            info = report(response)
            if response.is_success:
                models = response.json().get("models", [])
                names = [
                    m["name"]
                    for m in models
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
                info["configured_model_listed"] = (
                    "models/" + settings.gemini_model.removeprefix("models/") in names
                )
                info["flash_models"] = [name for name in names if "flash" in name][:15]
            print(json.dumps({"model_discovery": info}), flush=True)
            model = settings.gemini_model.removeprefix("models/")
            response = client.post(
                f"models/{model}:generateContent",
                json={
                    "contents": [{"parts": [{"text": "Reply with the word OK."}]}],
                    "generationConfig": {"maxOutputTokens": 1024},
                },
            )
            info = report(response)
            if response.is_success:
                info["candidates_present"] = bool(response.json().get("candidates"))
                info["text_present"] = any(
                    part.get("text", "").strip()
                    for candidate in response.json().get("candidates", [])
                    for part in candidate.get("content", {}).get("parts", [])
                )
            print(json.dumps({"synthetic_generation": info}), flush=True)
            if args.application and response.is_success:
                from backend.app.services.resources import GeminiGenerator

                try:
                    answer = GeminiGenerator(settings).answer(
                        "What revenue is reported?",
                        "[1] synthetic.pdf, page 1: Revenue is 42 million dollars.",
                    )
                    print(
                        json.dumps(
                            {
                                "application_adapter": {
                                    "grounded_answer_valid": "42" in answer and "[1]" in answer
                                }
                            }
                        ),
                        flush=True,
                    )
                except Exception as exc:
                    print(
                        json.dumps({"application_adapter_failure": type(exc).__name__}), flush=True
                    )
        except httpx.HTTPError as exc:
            print(json.dumps({"transport_failure": type(exc).__name__}), flush=True)


if __name__ == "__main__":
    main()
