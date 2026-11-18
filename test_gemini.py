from dotenv import load_dotenv
from openai import OpenAI
import os
import time

load_dotenv()

client = OpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    timeout=120.0,
    max_retries=0,
)

print("Sending request to Gemini...", flush=True)

start = time.time()

try:
    response = client.chat.completions.create(
        model="gemini-3.6-flash",
        messages=[
            {"role": "user", "content": "Reply with Hello"}
        ],
        reasoning_effort="low",
    )

    print("Response:", response.choices[0].message.content)
    print(f"Time taken: {time.time() - start:.2f} seconds")

except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")