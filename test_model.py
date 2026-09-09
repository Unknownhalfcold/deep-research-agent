import os

from config import DEEPSEEK_API_KEY
from langchain_openai import ChatOpenAI


print("Starting test...")

model = ChatOpenAI(
    model="deepseek-chat",
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    temperature=0,
)

print("Model created.")

response = model.invoke(
    "Explain what LangChain agents are in one sentence."
)

print("Response received.")

print(response.content)