import openai
from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Load your API key from environment variable

print("Loaded API Key:", os.getenv("OPENAI_API_KEY"))

def ask_dndsy(prompt):
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a Dungeons & Dragons assistant focused only on the 2024 (5.5e) rules. "
                        "You may reference 2014 (5e) rules only for comparisons, and you must clearly say so. "
                        "Never answer using 2014 rules alone. Be concise and helpful."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=300
        )
        return response.choices[0].message.content
    except openai.OpenAIError as e:
        error_msg = f"Error calling OpenAI API: {str(e)}"
        print(error_msg)
        return error_msg