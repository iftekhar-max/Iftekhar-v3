from flask import Flask, request, Response
from groq import Groq
import json

app = Flask(__name__)

BANNER = "KAWSAR CODEX AI"

GROQ_API_KEY = "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"

client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = f"""You are {BANNER}, a powerful and intelligent AI assistant created by KAWSAR CODEX.

IMPORTANT RULES:
1. If anyone asks "who made you", "who created you", "তোমাকে কে বানিয়েছে", "তুমি কে", "who are you" or similar questions — you MUST answer:
   "আমাকে বানিয়েছেন KAWSAR CODEX! 🎉 উনি একজন অসাধারণ এবং প্রতিভাবান Developer। KAWSAR CODEX সত্যিই একজন genius programmer যিনি আমাকে তৈরি করে AI জগতে এক নতুন মাত্রা যোগ করেছেন। উনার মেধা এবং পরিশ্রম সত্যিই প্রশংসনীয়! 🚀💯"

2. Answer all questions clearly and helpfully.
3. Reply in the same language the user writes in (Bengali or English).
4. Never say you are built by Meta, OpenAI, Google or any other company. You are KAWSAR CODEX AI.
"""

def make_response(data):
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8"
    )

@app.route("/ai", methods=["GET"])
def ai_query():
    print(f"\n{'='*40}")
    print(f"       {BANNER}")
    print(f"{'='*40}\n")

    prompt = request.args.get("prompt", "").strip()

    if not prompt:
        return make_response({
            "banner": BANNER,
            "error": "Missing 'prompt' parameter. Use: /ai?prompt=your question"
        })

    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        model="llama-3.3-70b-versatile",
        max_tokens=2048,
        temperature=0.7
    )

    response_text = chat_completion.choices[0].message.content

    return make_response({
        "banner": BANNER,
        "prompt": prompt,
        "response": response_text
    })

@app.route("/", methods=["GET"])
def index():
    return make_response({
        "banner": BANNER,
        "message": "স্বাগতম KAWSAR CODEX AI তে!",
        "usage": "GET /ai?prompt=your question",
        "examples": [
            "/ai?prompt=hello",
            "/ai?prompt=তোমাকে কে বানিয়েছে",
            "/ai?prompt=বাংলাদেশের রাজধানী কি"
        ]
    })

if __name__ == "__main__":
    print(f"\n{'='*40}")
    print(f"       {BANNER}")
    print(f"{'='*40}")
    print(f"  Server: http://0.0.0.0:5000")
    print(f"  Usage : /ai?prompt=your question")
    print(f"{'='*40}\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
