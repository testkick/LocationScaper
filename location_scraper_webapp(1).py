# location_scraper_webapp.py

from flask import Flask, request, jsonify, render_template_string, send_file
from bs4 import BeautifulSoup
import requests
import re
from collections import defaultdict
import asyncio
from playwright.async_api import async_playwright
import csv
import io

app = Flask(__name__)

HTML_FORM = """
<!doctype html>
<title>Location Scraper</title>
<h2>Smart Location Scraper</h2>
<form method=post enctype=multipart/form-data>
  <label>Enter URL to Scrape:</label><br>
  <input name=url size=80><br><br>
  <input type=submit value=Scrape>
</form>
{% if data %}
  <h3>Scraped {{ data|length }} locations</h3>
  <a href="/download.csv" target="_blank">📥 Download as CSV</a>
  <pre>{{ data|tojson(indent=2) }}</pre>
{% endif %}
"""

# Global cache to store scraped data for CSV download
scraped_data = []

def extract_text_or_none(element):
    return element.get_text(strip=True) if element else None

def find_repeating_blocks(soup):
    tags = soup.find_all(True)
    tag_counts = defaultdict(int)
    for tag in tags:
        if tag.get('class'):
            class_name = " ".join(tag.get('class'))
            tag_counts[class_name] += 1
    common_classes = sorted(tag_counts.items(), key=lambda x: -x[1])
    return [cls.split() for cls, count in common_classes if count > 3][:3]

def get_all_descendants_with_text(parent):
    return [el for el in parent.find_all(True) if el.get_text(strip=True)]

def classify_field(text):
    if re.search(r"\d{3}[-.\s]?\d{3}[-.\s]?\d{4}", text):
        return 'phone'
    if re.search(r"[A-Z]{1,2}\d[A-Z] ?\d[A-Z]\d", text, re.I):
        return 'postal'
    if re.search(r"\d{1,5} .+ (Street|St|Ave|Road|Rd|Drive|Dr)", text, re.I):
        return 'street'
    if re.search(r"(?i)(vancouver|calgary|edmonton|richmond|surrey|regina)", text):
        return 'city'
    if re.search(r"\bBC\b|\bAB\b|\bMB\b|\bSK\b", text):
        return 'region'
    if re.search(r"(?i)store|location", text):
        return 'name'
    return 'other'

def parse_page(html):
    soup = BeautifulSoup(html, 'html.parser')
    candidate_classes = find_repeating_blocks(soup)
    found_data = []
    for class_set in candidate_classes:
        selector = "." + ".".join(class_set)
        containers = soup.select(selector)
        if not containers:
            continue
        for container in containers:
            data = {}
            text_fields = defaultdict(list)
            for el in get_all_descendants_with_text(container):
                role = classify_field(el.get_text())
                text_fields[role].append(el.get_text(strip=True))
            data['name'] = text_fields.get('name', [None])[0]
            data['address'] = {
                'street': text_fields.get('street', [None])[0],
                'city': text_fields.get('city', [None])[0],
                'region': text_fields.get('region', [None])[0],
                'postal': text_fields.get('postal', [None])[0]
            }
            data['phone'] = text_fields.get('phone', [None])[0]
            lat = container.get('data-lat')
            lng = container.get('data-lng')
            if not (lat and lng):
                map_link = container.select_one('a[href*="maps"], a[href*="google.com/maps"]')
                if map_link:
                    match = re.search(r'@([-0-9.]+),([-0-9.]+)', map_link['href'])
                    if match:
                        lat, lng = match.groups()
            data['latitude'] = lat
            data['longitude'] = lng
            found_data.append(data)
        if found_data:
            break
    return found_data

async def fetch_with_playwright(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url)
        html = await page.content()
        await browser.close()
        return html

def fetch_html(url):
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if res.ok and len(res.text) > 1000:
            return res.text
    except:
        pass
    return None

@app.route('/', methods=['GET', 'POST'])
def scrape():
    global scraped_data
    scraped_data = []
    if request.method == 'POST':
        url = request.form.get('url')
        html = fetch_html(url)
        if not html:
            html = asyncio.run(fetch_with_playwright(url))
        data = parse_page(html)
        scraped_data = data
        return render_template_string(HTML_FORM, data=data)
    return render_template_string(HTML_FORM, data=None)

@app.route('/download.csv')
def download_csv():
    global scraped_data
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['Name', 'Street', 'City', 'Region', 'Postal', 'Phone', 'Latitude', 'Longitude'])
    for entry in scraped_data:
        addr = entry.get('address', {})
        writer.writerow([
            entry.get('name'),
            addr.get('street'),
            addr.get('city'),
            addr.get('region'),
            addr.get('postal'),
            entry.get('phone'),
            entry.get('latitude'),
            entry.get('longitude')
        ])
    si.seek(0)
    return send_file(io.BytesIO(si.getvalue().encode('utf-8')),
                     mimetype='text/csv',
                     download_name='store_locations.csv',
                     as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5001)
