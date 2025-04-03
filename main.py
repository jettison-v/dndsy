from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from llm import ask_dndsy

load_dotenv()

app = FastAPI()

class Query(BaseModel):
    question: str

@app.post("/query")
async def query_dndsy(query: Query):
    answer = ask_dndsy(query.question)
    return {"answer": answer}