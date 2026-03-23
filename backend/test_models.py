import os
from google import genai

client = genai.Client()
print("Listing embedding models:")
for m in client.models.list():
    if 'embedContent' in m.supported_actions or 'embed' in m.supported_actions or 'embedding' in m.name:
        print(m.name, m.supported_actions)
