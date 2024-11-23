# src/app.py
import argparse
import asyncio
from .comic_scraper import main as scraper_main

def parse_arguments():
    parser = argparse.ArgumentParser(description="Scrape comic from website")
    parser.add_argument("title", help="The title of the comic to scrape")
    parser.add_argument("--base-url", default="https://komikcast.cz/",
                        help="Base URL of the comic website")
    return parser.parse_args()

async def run_scraper():
    args = parse_arguments()
    await scraper_main(args.title, args.base_url)

if __name__ == "__main__":
    asyncio.run(run_scraper())
