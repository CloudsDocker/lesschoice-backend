import json

import httpx

from . import config

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"


class GeminiError(Exception):
    pass


def _build_prompt(prompt: str, constraints: str, liked_titles: list[str],
                   blacklisted_titles: list[str], already_suggested_titles: list[str], count: int) -> str:
    lines = [
        "You are recommending real, specific named places for a trip decision app.",
        f"Context: {prompt}",
        f"Constraints: {constraints}",
        f"Suggest {count} new distinct real places that fit the context and constraints.",
    ]
    if liked_titles:
        lines.append(f"The user liked these places, favor a similar style/category/vibe: {', '.join(liked_titles)}.")
    if blacklisted_titles:
        lines.append(f"The user disliked these places, avoid them and anything similar in style or category: {', '.join(blacklisted_titles)}.")
    if already_suggested_titles:
        lines.append(f"Do not repeat any of these already-suggested places: {', '.join(already_suggested_titles)}.")
    lines.append(
        "For each place, also give the name and a short description in the primary local/native language "
        "spoken where that place is located (e.g. for Shanghai, localTitle would be in Chinese characters). "
        "If the local language is English, leave localTitle and localDescription as empty strings."
    )
    lines.append(
        'Respond with ONLY a JSON array, no markdown fences, in this exact shape:\n'
        '[{"title": "Place Name", "subtitle": "short tagline", "description": "one engaging sentence under 140 characters", '
        '"category": "one or two words", "localTitle": "Place name in the local language, or empty string", '
        '"localDescription": "one short sentence in the local language, or empty string"}]'
    )
    return "\n".join(lines)


async def fetch_places(prompt: str, constraints: str, liked_titles: list[str],
                        blacklisted_titles: list[str], already_suggested_titles: list[str],
                        count: int) -> list[dict]:
    instructions = _build_prompt(prompt, constraints, liked_titles, blacklisted_titles,
                                  already_suggested_titles, count)

    body = {
        "contents": [{"parts": [{"text": instructions}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            GEMINI_URL,
            params={"key": config.GEMINI_API_KEY},
            json=body,
        )

    if response.status_code != 200:
        raise GeminiError(f"Gemini request failed: {response.status_code} {response.text}")

    data = response.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise GeminiError("Gemini response missing expected content") from exc

    try:
        places = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeminiError("Gemini response was not valid JSON") from exc

    return places
