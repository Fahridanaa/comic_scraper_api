from datetime import datetime
import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import asyncio
import aiohttp
import logging
from aiohttp import ClientSession
import random
from typing import List, Dict, Any
from tqdm import tqdm
import unicodedata
from src.services.cloudinary_service import file_exists, folder_exists, upload_image
from src.models.comic import Comic
from src.services.db_connection import SessionLocal

# Constants
USER_AGENTS: List[str] = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15'
]
MAX_CONCURRENT_DOWNLOADS = 3
MAX_RETRIES = 3
RETRY_DELAY = 2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to be safe for all operating systems."""
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = unicodedata.normalize('NFKD', filename)
    return filename.strip()

async def fetch_data_with_retry(url: str, max_retries: int = MAX_RETRIES) -> str:
    """Fetch data with retry mechanism."""
    for attempt in range(max_retries):
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    return await response.text()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                raise
            wait_time = RETRY_DELAY * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)

def safe_select(soup: BeautifulSoup, selector: str, default: str = "N/A") -> str:
    """Safely extract text from BeautifulSoup selector with fallback."""
    try:
        element = soup.select_one(selector)
        return element.text.strip() if element else default
    except Exception as e:
        logger.warning(f"Failed to extract {selector}: {e}")
        return default

def rate_limited(min_delay=2, max_delay=5):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            await asyncio.sleep(random.uniform(min_delay, max_delay))
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Function to download images with retries
@rate_limited()
async def download_image(session: ClientSession, url: str, comic_slug: str, chapter: str = None, is_cover: bool = False, retries: int = 3):
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Referer': 'https://komikcast.cz/',
        'Accept': 'image/*',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    for attempt in range(retries):
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 429:
                    wait_time = int(response.headers.get('Retry-After', 60))
                    print(f"Rate limited. Waiting {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                content = await response.read()

                if is_cover:
                    folder = comic_slug
                    filename = "cover"
                elif chapter:
                    folder = f"{comic_slug}/chapter-{chapter}"
                    filename = url.split('/')[-1].split('.')[0]  # Remove file extension
                else:
                    raise ValueError("Either 'chapter' or 'is_cover' must be specified")

                result = upload_image(content, folder, filename)
                if result:
                    return result['secure_url']
                else:
                    print(f"Failed to upload image to Cloudinary: {filename}")
                    return ""
        except aiohttp.ClientError as e:
            if attempt == retries - 1:
                raise e
            logger.warning(f"Retry {attempt + 1}/{retries} for {url}")
            await asyncio.sleep(2 ** attempt)

# Function to fetch data
def fetch_data(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.text

# Function to save comic metadata
def save_comic_metadata(comic_meta, comic_slug):
    db = SessionLocal()
    try:
        existing_comic = db.query(Comic).filter(Comic.slug == comic_slug).first()
        if not existing_comic:
            new_comic = Comic(
                title=comic_meta['title'],
                author=comic_meta['author'],
                type=comic_meta['type'],
                status=comic_meta['status'],
                release=comic_meta['release'],
                updated_on=datetime.now(),
                genres=comic_meta['genres'],
                synopsis=comic_meta['synopsis'],
                rating=comic_meta['rating'],
                cover_image_url=comic_meta['cover_image_url'],
                slug=comic_slug
            )
            db.add(new_comic)
            print(f"Saved comic metadata to database: {comic_slug}")
        else:
            existing_comic.updated_on=datetime.now()
            print(f"Update comic metadata in database: {comic_slug}")

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error saving comic metadata to database: {str(e)}")
    finally:
        db.close()

# Function to extract comic metadata
def extract_comic_meta(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extract comic metadata with error handling."""
    try:
        return {
            'title': re.sub(r'\s+Bahasa Indonesia$', '', sanitize_filename(safe_select(soup, '.komik_info-content-body-title')), flags=re.IGNORECASE),
            'author': safe_select(soup, '.komik_info-content-info:contains("Author:")')
                     .replace('Author:', '').strip(),
            'type': safe_select(soup, '.komik_info-content-info-type a').lower(),
            'status': safe_select(soup, '.komik_info-content-info:contains("Status:")')
                     .replace('Status:', '').strip().lower(),
            'release': safe_select(soup, '.komik_info-content-info-release')
                      .replace('Released:', '').strip(),
            'genres': [g.text.strip() for g in soup.select('.komik_info-content-genre a') or []],
            'synopsis': safe_select(soup, '.komik_info-description-sinopsis'),
            'rating': safe_select(soup, '.komik_info-content-rating strong:contains("Rating")')
                     .replace('Rating ', '').strip(),
        }
    except Exception as e:
        logger.error(f"Failed to extract metadata: {e}")
        return {}

# Function to handle cover image
async def handle_cover_image(session: ClientSession, cover_image_url: str, comic_slug: str):
    if file_exists(comic_slug, 'cover'):
        print('Cover image already exists. Skipping...')
        return None
    cloudinary_url = await download_image(session, cover_image_url, comic_slug, is_cover=True)
    if cloudinary_url:
        print('Cover image uploaded successfully')
        return cloudinary_url
    else:
        print('Failed to upload cover image')
        return None

# Function to scrape comic metadata and chapters
async def scrape_comic_meta(session: ClientSession, url, title):
    try:
        data = fetch_data(url)
        soup = BeautifulSoup(data, 'html.parser')

        comic_meta = extract_comic_meta(soup)

        cover_image_url = soup.select_one('.komik_info-content-thumbnail img')['src']
        cover_cloudinary_url = await handle_cover_image(session, cover_image_url, title)

        if cover_cloudinary_url:
            comic_meta['cover_image_url'] = cover_cloudinary_url

        comic_meta['slug'] = title

        return comic_meta
    except Exception as e:
        print(f'Failed to scrape comic meta: {str(e)}')
        return None

# Function to scrape chapter images
async def scrape_chapter_images(session: ClientSession, url: str, comic_slug: str):
    try:
        chapter_num_match = re.search(r'chapter-(\d+)', url)
        if not chapter_num_match:
            raise ValueError("Invalid chapter URL")

        chapter_num = chapter_num_match.group(1)
        chapter_folder = f"{comic_slug}/chapter-{chapter_num}"

        # Check if the chapter folder already exists
        if folder_exists(chapter_folder):
            print(f"\nChapter {chapter_num} already exists. Skipping...")
            return []

        data = fetch_data(url)
        soup = BeautifulSoup(data, 'html.parser')

        images = [img['src'] for img in soup.select('#chapter_body > .main-reading-area img')]

        cloudinary_urls = []
        for img_url in images:
            cloudinary_url = await download_image(session, img_url, comic_slug, chapter=chapter_num)
            if cloudinary_url:
                cloudinary_urls.append(cloudinary_url)

        return cloudinary_urls

    except Exception as e:
        print(f'Failed to scrape chapter: {str(e)}')
        return []

async def get_chapter_list(soup):
    chapters = []
    try:
        chapter_links = soup.select('#chapter-wrapper > li.komik_info-chapters-item > a.chapter-link-item')
        for item in chapter_links:
            chapter_text = item.text.strip().replace("\n", " ")
            match = re.search(r'Chapter (\d+(\.\d+)?)', chapter_text)
            if match:
                chapters.append({
                    'number': float(match.group(1)),
                    'url': item['href']
                })
        # Sort chapters numerically
        return sorted(chapters, key=lambda x: x['number'])
    except Exception as e:
        print(f"Error extracting chapters: {e}")
        return []

async def download_with_progress(url: str,
                               session: ClientSession,
                               semaphore: asyncio.Semaphore,
                               comic_slug: str,
                               progress: tqdm):
    """Download chapter with progress tracking and rate limiting."""
    try:
        async with semaphore:
            await scrape_chapter_images(session, url, comic_slug)
            progress.update(1)
    except Exception as e:
        logger.error(f"Failed to download chapter {url}: {e}")

# Main execution function
async def main(title: str, base_url: str = 'https://komikcast.cz/'):
    """Enhanced main function with semaphore and progress bars."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    async with aiohttp.ClientSession() as session:
        comic_url = urljoin(base_url, f'komik/{title}/')

        try:
            data = await fetch_data_with_retry(comic_url)
            soup = BeautifulSoup(data, 'html.parser')

            comic_meta = await scrape_comic_meta(session, comic_url, title)
            if not comic_meta:
                logger.error("Failed to get comic metadata")
                return

            print("\n=== Comic Information ===")
            print(f"Title    : {comic_meta['title']}")
            print(f"Author   : {comic_meta['author']}")
            print(f"Type     : {comic_meta['type']}")
            print(f"Status   : {comic_meta['status']}")
            print(f"Rating   : {comic_meta['rating']}")
            print(f"Genres   : {', '.join(comic_meta['genres'])}")
            print(f"\nSynopsis : {comic_meta['synopsis'][:200]}...")
            print("=====================\n")

            chapters = await get_chapter_list(soup)
            if not chapters:
                logger.error("No chapters found")
                return

            latest_chapter = chapters[-1]['number']
            logger.info(f"Latest chapter: {latest_chapter}")

            user_input = input("Enter starting chapter number (press Enter to scrape all): ").strip()
            start_chapter = float(user_input) if user_input else None

            save_comic_metadata(comic_meta, title)

            chapters_to_scrape = [ch for ch in chapters
                                  if not start_chapter or ch['number'] >= start_chapter]


            chapters_to_scrape = [
                chapter for chapter in chapters_to_scrape
                if not folder_exists(f"{title}/chapter-{chapter['number']}")
            ]

            if not chapters_to_scrape:
                print("All selected chapters already exist. No new chapters to scrape.")
                return

            # Use semaphore and progress bar
            with tqdm(total=len(chapters_to_scrape), desc="Downloading chapters") as progress:
                tasks = [
                    download_with_progress(
                        url=chapter['url'],
                        session=session,
                        semaphore=semaphore,
                        comic_slug=title,
                        progress=progress
                    ) for chapter in chapters_to_scrape
                ]
                await asyncio.gather(*tasks)

        except Exception as e:
            logger.error(f"Failed to process comic: {e}")
