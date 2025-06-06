import html
import json
import boto3
import os
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from collections import defaultdict

# Initialize DynamoDB
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["MOVIE_SHOWTIME_OPTIONS_TABLE"])

AMC_THEATER_SLUGS = [
    "amc-roosevelt-collection-16",
    "amc-dine-in-block-37",
    "amc-river-east-21"
]

KNOWN_FORMATS = {
    "dolby cinema": "Dolby Cinema",
    "reald 3d": "RealD 3D",
    "dine-in delivery to seat": "Dine-In Delivery To Seat",
    "laser at amc": "Laser At AMC"
}

def normalize_format(raw: str) -> str:
    clean = raw.strip().lower()
    for known in KNOWN_FORMATS:
        if known in clean:
            return KNOWN_FORMATS[known]
    return "Other"

def fetch_amc_showtimes_for_day(movie_title: str, date_str: str) -> list:
    base_url = "https://www.amctheatres.com/movie-theatres/chicago"
    headers = {"User-Agent": "Mozilla/5.0"}
    results_by_theater = defaultdict(lambda: defaultdict(set))
    normalized_title = movie_title.strip().lower()

    for slug in AMC_THEATER_SLUGS:
        url = f"{base_url}/{slug}/showtimes?date={date_str}"
        print(f"Scraping {url}")
        try:
            res = requests.get(url, headers=headers)
            if res.status_code != 200:
                print(f"[WARN] Failed to fetch from {url}")
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            sections = soup.find_all("section", attrs={"aria-label": True})

            for section in sections:
                aria_label = html.unescape(section["aria-label"].strip()).lower()
                if f"showtimes for {normalized_title}" not in aria_label:
                    continue

                format_blocks = section.find_all(["li", "div"], recursive=True)

                for block in format_blocks:
                    showtime_links = block.find_all("a", href=True)
                    showtimes = [
                        a.get_text(strip=True)
                        for a in showtime_links
                        if "/showtimes/" in a["href"]
                    ]
                    if not showtimes:
                        continue

                    format_label_tag = block.find(["span", "p"])
                    raw_format = (
                        format_label_tag.get_text(strip=True).title()
                        if format_label_tag else "Standard"
                    )

                    label_clean = raw_format.lower()
                    if "up to" in label_clean or "off" in label_clean or label_clean == "standard":
                        continue

                    format_key = normalize_format(raw_format)

                    for slot in showtimes:
                        results_by_theater[slug][format_key].add(slot)

                break  # Only one match per movie per section

        except Exception as e:
            print(f"[ERROR] Scraping failed for {url}: {e}")

    final_results = []
    for slug, formats in results_by_theater.items():
        formatted = [
            {
                "type": fmt,
                "slots": [
                    {"time": slot, "date": date_str}
                    for slot in sorted(slots)
                ]
            }
            for fmt, slots in formats.items()
        ]
        if formatted:
            final_results.append({
                "name": slug.replace("-", " ").title(),
                "formats": formatted
            })

    return final_results


def handler(event, context):
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            movie_id = body.get("movieId")
            movie_title = body.get("movieTitle")
            show_date = body.get("showDate")

            if not movie_id or not movie_title or not show_date:
                print(f"[SKIP] Invalid message: {body}")
                continue

            theaters = fetch_amc_showtimes_for_day(movie_title, show_date)

            item = {
                "movieId": movie_id,
                "showDate": show_date,
                "movieTitle": movie_title,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "theaters": theaters
            }

            table.put_item(Item=item)
            print(f"[SUCCESS] Stored movieId={movie_id} showDate={show_date}")

        except Exception as e:
            print(f"[ERROR] Failed to process record: {e}")
