"""Legacy story fallback path; current production drafts through draft_story.py.

Retained for explicit manual evaluation. See docs/LEGACY.md before use.
"""

import json
import random

import requests

from config import GEMINI_API_KEY, OLLAMA_HOST, OLLAMA_MODEL, STORY_MAX_WORDS

SYSTEM_PROMPT = """You are an expert YouTube Shorts and TikTok viral storyteller.
Your task is to write an engaging, immersive micro-story / thriller script.

STRICT RULES:
1. Use at most 140 words. There is no minimum duration or word count: prioritize a complete, clear story without padding.
2. The Hook (0-3s): The very first sentence MUST grab attention with extreme urgency or a bizarre, intriguing premise.
3. Rhythm: Fast-paced, sensory-rich, first-person narrative ("I", "we", "he"). Keep sentences punchy.
4. Retention: Build continuous tension with a shocking twist or cliffhanger in the final 5 seconds.
5. Monetization Safe: DO NOT use copyrighted names (e.g. change "Peter Parker" to "a young photojournalist with spider-like reflexes" or keep it an original thriller/urban legend).
6. Output ONLY a raw JSON object with two keys:
   - "title": A viral 4-8 word title
   - "script": The plain narration script with no stage directions, no sound effects, no parentheticals.
7. Write for spoken delivery: use natural complete phrases, ordinary punctuation, and no ellipses, em dashes, or artificial dramatic pauses. Do not break clauses into disconnected fragments.

Example JSON output:
{
  "title": "The Rule You Can Never Break",
  "script": "Every night at exactly 3:17 AM, my grandfather's antique grandfather clock rings four times instead of three. The rule in our family has always been simple: whatever happens, do not look into the glass pendulum casing. Last night, I couldn't take the curiosity anymore. I crept down the wooden staircase, holding my breath. When the chime struck 3:17, the glass didn't show my reflection. It showed a figure standing in my bedroom upstairs, staring down at my empty bed. And then... my phone buzzed in my hand with a text from an unknown number: 'Why did you leave your room?'"
}
"""


def fetch_reddit_prompts(subreddit: str = "shortscarystories", limit: int = 10) -> list[dict]:
    """Fetches trending story premises from Reddit's public API without API keys."""
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=week&limit={limit}"

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            posts = []
            for child in data.get("data", {}).get("children", []):
                p = child.get("data", {})
                title = p.get("title", "")
                selftext = p.get("selftext", "")
                if len(title) > 10 and not p.get("stickied"):
                    posts.append(
                        {
                            "title": title,
                            "content": selftext[:600],
                            "score": p.get("score", 0),
                        }
                    )
            return posts
    except Exception as e:
        print(f"[!] Reddit fetch warning: {e}")
    return []


def call_ollama(prompt: str, model: str = OLLAMA_MODEL) -> str | None:
    """Invokes local Ollama (Nous Hermes, Llama 3, etc.) for generation."""
    try:
        url = f"{OLLAMA_HOST}/api/generate"
        payload = {
            "model": model,
            "system": SYSTEM_PROMPT,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        res = requests.post(url, json=payload, timeout=90)
        if res.status_code == 200:
            return res.json().get("response")
    except Exception as e:
        print(f"[!] Ollama connection failed: {e}")
    return None


def call_gemini(prompt: str, api_key: str = GEMINI_API_KEY) -> str | None:
    """Fallback to Gemini API if configured."""
    if not api_key:
        return None
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code == 200:
            data = res.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[!] Gemini API error: {e}")
    return None


def fallback_viral_story(topic: str = "") -> dict:
    """Pre-crafted storytelling templates for the legacy manual path."""
    templates = [
        {
            "title": "The Rule of the Elevator",
            "script": "If you ever enter an elevator and find a stranger pressing the button for floor zero, do not speak. In modern skyscrapers, floor zero does not exist on the blueprints. Last Tuesday, I made the mistake of making eye contact. The man wore a vintage tailored suit with no face where his eyes should have been. As the elevator began to drop past the basement levels, the numbers on the display turned into red symbols I couldn't read. When the doors finally opened, I wasn't in our lobby. I was looking out at an endless ocean of black fog with dozens of people standing completely still. The man whispered: 'Floor zero. Your turn to wait.' And the doors closed behind me.",
        },
        {
            "title": "The Deep Woods Anomaly",
            "script": "My brother and I built a cabin three miles into the northern pine woods. We had one golden rule: if you hear someone screaming your name in our mother's voice, stay inside and lock both deadbolts. Our mother passed away five years ago. Yesterday at dusk, the temperature plummeted twenty degrees in seconds. The windows rattled, and then I heard it clearly from behind the shed: my own voice, begging to be let inside. I looked through the peephole. Standing on the porch was a creature wearing my exact jacket, standing on twisted, backwards legs, holding a replica of my car keys. It smiled with too many teeth and knocked twice. I haven't moved from this corner in fourteen hours.",
        },
        {
            "title": "The Infinite Flight",
            "script": "Flight 814 was supposed to be a standard six-hour journey from Tokyo to Los Angeles. But after eight hours, the flight attendants stopped serving drinks and pulled every window blind shut. When a passenger in row twelve opened his blind, the entire cabin went silent. Outside was not the ocean. It was a vast, starry sky beneath us, and our plane was flying completely upside down over a colossal glowing city that doesn't exist on any map. The captain came over the intercom, his voice shaking: 'Ladies and gentlemen, we missed the exit corridor. We have twenty minutes of fuel left, and nowhere to land.' That was three days ago, and our fuel gauge still hasn't moved.",
        },
    ]
    return random.choice(templates)


def generate_story(topic: str = "", subreddit: str = "shortscarystories") -> dict:
    """Main pipeline entry to produce an engaging, monetization-safe short story."""
    prompt_text = ""

    # 1. Check Reddit for trending premises if no specific topic given
    if not topic:
        posts = fetch_reddit_prompts(subreddit)
        if posts:
            chosen = random.choice(posts)
            prompt_text = f"Adapt this premise into a complete monologue of at most 140 words, with no minimum length, for a YouTube Short: Title: {chosen['title']}. Content: {chosen['content']}"
            print(f"[+] Sourced premise from r/{subreddit}: '{chosen['title'][:50]}...'")
        else:
            prompt_text = "Write a high-suspense psychological thriller short about a mysterious rule someone broke."
    else:
        prompt_text = f"Write a complete short story of at most 140 words, with no minimum length, based on this topic: '{topic}'."

    # 2. Try Ollama (Local)
    raw_json = call_ollama(prompt_text)

    # 3. Try Gemini API
    if not raw_json:
        raw_json = call_gemini(prompt_text)

    # 4. Parse JSON result
    if raw_json:
        try:
            cleaned = raw_json.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:-3].strip()
            data = json.loads(cleaned)
            if (
                isinstance(data.get("script"), str)
                and 1 <= len(data["script"].split()) <= STORY_MAX_WORDS
            ):
                print(
                    f"[+] Story generated via LLM: '{data.get('title', 'Untitled')}' ({len(data['script'].split())} words)"
                )
                return data
        except Exception as e:
            print(f"[!] JSON parsing error from LLM response: {e}")

    # 5. High-quality fallback template
    print("[*] Using high-retention fallback story template.")
    return fallback_viral_story(topic)


if __name__ == "__main__":
    story = generate_story()
    print("\n--- RESULT ---")
    print("Title:", story["title"])
    print("Word Count:", len(story["script"].split()))
    print("Script:\n", story["script"])
