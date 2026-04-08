import asyncio
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.scraper_route import router as scraper_router

# Playwright requires subprocess support; force Proactor loop on Windows.
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI()

# Allow frontend (Next.js) to talk to backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "StyleSync Backend Running 🚀"}


app.include_router(scraper_router)