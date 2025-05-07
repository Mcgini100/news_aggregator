# news_aggregator/spiders/cnn_spider.py
import scrapy
from news_aggregator.items import NewsArticleItem
from urllib.parse import urljoin
import json # For parsing JSON-LD if available or needed

class CnnSpider(scrapy.Spider):
    name = 'cnn'
    allowed_domains = ['edition.cnn.com'] # Ensure 'edition.' is included if that's the primary domain
    custom_settings = {
        'DOWNLOAD_DELAY': 2, # CNN can be sensitive to scraping
        'AUTOTHROTTLE_ENABLED': True,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 NewsAggregatorBot/1.0 (+http://www.your-domain.com/botinfo)',
    }

    MAX_ARTICLES_PER_CATEGORY = 4

    category_map = {
        'politics': 'https://edition.cnn.com/politics',
        'business': 'https://edition.cnn.com/business',
        'arts_culture_celebrities': 'https://edition.cnn.com/entertainment',
        'sports': 'https://edition.cnn.com/sport'
    }

    def start_requests(self):
        for category_name, category_url in self.category_map.items():
            yield scrapy.Request(
                url=category_url,
                callback=self.parse_category_page,
                meta={
                    'category': category_name,
                    'source': self.name,
                    'article_count': 0
                }
            )

    def parse_category_page(self, response):
        category = response.meta['category']
        source = response.meta['source']
        article_count = response.meta['article_count']

        self.logger.info(f"Parsing {source} category: {category} from {response.url} (Count: {article_count})")

        # --- UPDATED Selectors for CNN Category Pages ---
        # Each story seems to be within a <div data-component-name="card" ... class="card ...">
        promos = response.css('div.card[data-component-name="card"]')

        if not promos:
            self.logger.warning(f"No promo blocks found for {source} {category} on {response.url} with current selectors.")
            # Fallback for other layouts if the primary one fails
            promos = response.css('a[data-link-type="article"]') # This might select links directly
            if not promos:
                self.logger.warning(f"Fallback selector also found no promos for {source} {category}.")
                return

        processed_urls = set()

        for promo_element in promos:
            if article_count >= self.MAX_ARTICLES_PER_CATEGORY:
                self.logger.info(f"Reached max articles ({self.MAX_ARTICLES_PER_CATEGORY}) for {category}. Stopping.")
                return

            article_url_relative = None
            title_text = None

            # If the promo_element is the card div itself
            if promo_element.attrib.get('data-component-name') == 'card':
                # URL can be from data-open-link attribute on the card div
                article_url_relative = promo_element.attrib.get('data-open-link')
                # Or from the href of an <a> tag inside
                if not article_url_relative:
                    article_url_relative = promo_element.css('a.container__link--type-article::attr(href)').get()
                
                # Title from span.container__headline-text
                title_text = promo_element.css('span.container__headline-text::text').get()

            # If the promo_element is an <a> tag (from fallback selector)
            elif promo_element.root.tag == 'a' and promo_element.attrib.get('data-link-type') == 'article':
                article_url_relative = promo_element.attrib.get('href')
                # Try to find a headline within this <a> tag
                title_text = promo_element.css('span[data-editable="headline"]::text, span.container__headline-text::text, h2::text, h3::text, h4::text').get()
                if not title_text: # Get any prominent text from the link itself
                    all_text_in_link = promo_element.css('::text').getall()
                    title_text = " ".join(t.strip() for t in all_text_in_link if t.strip() and len(t.strip()) > 5).strip()


            if not article_url_relative or not article_url_relative.strip().startswith('/'):
                # self.logger.debug(f"Skipping promo with no valid relative URL. Promo: {promo_element.get()[:150]}")
                continue

            url = response.urljoin(article_url_relative.strip())

            if url in processed_urls:
                # self.logger.debug(f"Already processed URL: {url}")
                continue
            
            if not url.startswith('https://edition.cnn.com/'):
                self.logger.debug(f"Skipping URL not starting with edition.cnn.com: {url}")
                continue

            # Check if URL path contains date (common for articles) or category name
            # e.g., /2025/05/07/politics/some-article-slug
            # And ensure it's not just a section link like /politics/
            path_parts = [part for part in url.split('cnn.com/')[-1].split('/') if part]
            if not (len(path_parts) > 1 and path_parts[-1] != category): # Ensure it's not just /category/
                if not (len(path_parts) > 2 and path_parts[0].isdigit() and path_parts[1].isdigit() and path_parts[2].isdigit()): # Check for YYYY/MM/DD
                    self.logger.debug(f"Skipping URL that doesn't look like a specific article path: {url}")
                    continue
            
            if any(x in url for x in ['/videos/', '/live-news/', '/gallery/', '/profiles/', '/specials/', '/shows/', '/interactive/', '/amp/']):
                self.logger.debug(f"Skipping non-article (video/live/gallery/etc.) URL: {url}")
                continue


            if not title_text or len(title_text.strip()) < 10:
                self.logger.debug(f"Skipping promo with no valid title or short title for URL {url}. Title: '{title_text}'. Promo: {promo_element.get()[:150]}")
                continue

            title = title_text.strip()
            
            # Summary is rarely present on CNN category pages for these cards
            summary_text = None

            item_data = NewsArticleItem()
            item_data['source'] = source
            item_data['category'] = category
            item_data['title'] = title
            item_data['url'] = url
            item_data['summary'] = summary_text.strip() if summary_text else None
            item_data['full_content'] = None

            processed_urls.add(url)
            article_count += 1
            yield scrapy.Request(
                url=item_data['url'],
                callback=self.parse_article_page,
                meta={'item_data': item_data}
            )

    def parse_article_page(self, response):
        item = response.meta['item_data']
        self.logger.info(f"Parsing article page: {item['url']}")

        # --- Attempt to get from JSON-LD first ---
        json_ld_scripts = response.xpath('//script[@type="application/ld+json"]/text()').getall()
        article_body_from_json = None
        for script_content in json_ld_scripts:
            try:
                # CNN JSON-LD can be a list of objects or a single object
                data_objects = json.loads(script_content)
                if not isinstance(data_objects, list):
                    data_objects = [data_objects]
                
                for data in data_objects:
                    if isinstance(data, dict) and (data.get("@type") == "NewsArticle" or "Article" in data.get("@type", []) or data.get("@type") == "ReportageNewsArticle"):
                        article_body_from_json = data.get("articleBody")
                        if article_body_from_json:
                            # Sometimes it has HTML, sometimes just text. If HTML, we might want to parse it.
                            # For now, assume it's mostly clean text or we accept minor HTML tags.
                            item['full_content'] = article_body_from_json.strip() # Basic strip
                            # If it contains HTML, a more robust cleaning would be:
                            # from w3lib.html import remove_tags
                            # item['full_content'] = remove_tags(article_body_from_json).strip()
                            self.logger.debug(f"Extracted articleBody from JSON-LD for {item['url']}")
                            yield item
                            return
            except json.JSONDecodeError as e:
                self.logger.debug(f"JSONDecodeError parsing JSON-LD for {item['url']}: {e}")
            except Exception as e:
                self.logger.debug(f"Error processing JSON-LD for {item['url']}: {e}")


        # --- If JSON-LD fails or no articleBody, try CSS selectors ---
        self.logger.debug(f"JSON-LD did not yield articleBody for {item['url']}. Trying CSS selectors.")
        
        # Primary content container based on provided HTML:
        article_content_element = response.css('div.article__content[data-editable="content"]')

        collected_paragraphs = []
        if article_content_element:
            # Paragraphs are <p class="paragraph ..."> or could be other elements if structure changes.
            # Let's target paragraphs specifically within this container.
            # Also consider divs that might act as paragraphs if p tags are not used consistently.
            paragraph_selectors = article_content_element.css('p.paragraph, div.paragraph') # Targeting specific paragraph classes

            for p_tag in paragraph_selectors:
                # Exclude known non-content elements within the article body
                # Check ancestors for ad components, source components, etc.
                is_unwanted = p_tag.xpath(''
                    'ancestor::div[contains(@data-uri, "ad-slot")] |' # Ad slots by data-uri
                    'ancestor::div[contains(@class, "ad")] |' # General ad class
                    'ancestor::div[@data-component-name="source"] |' # Source/cite component
                    'ancestor::figure/figcaption |' # Figcaptions
                    'ancestor::aside |'
                    'ancestor::div[contains(@class, "related-content")] |'
                    'ancestor::div[contains(@class, "gallery")] |'
                    'ancestor::div[contains(@class, "video")] |'
                    'self::p[starts-with(normalize-space(.), "Related:") or starts-with(normalize-space(.), "Watch:") or starts-with(normalize-space(.), "READ MORE")]'
                ).get()

                if not is_unwanted:
                    text_nodes = p_tag.css('::text').getall()
                    cleaned_text = " ".join(t.strip() for t in text_nodes if t.strip()).strip()
                    if cleaned_text and len(cleaned_text) > 15:
                        collected_paragraphs.append(cleaned_text)
                # else:
                #    self.logger.debug(f"Skipping paragraph due to exclusion: {p_tag.get()[:100]}")
            
            if collected_paragraphs:
                item['full_content'] = "\n\n".join(collected_paragraphs)
                self.logger.debug(f"Found article body paragraphs using CSS selectors for {item['url']}")
            else:
                self.logger.warning(f"CSS selectors for paragraphs in div.article__content yielded no text for {item['url']}. Content HTML: {article_content_element.get()[:500]}")
        else:
            self.logger.warning(f"Could not find primary article content container 'div.article__content' for {item['url']}")

        if not item.get('full_content'):
            # Broader fallback if the specific container wasn't found or was empty
            self.logger.warning(f"Primary content extraction failed for {item['url']}. Trying broader fallback.")
            # Try a common pattern for CNN body content if the specific one fails
            broader_body = response.css('div[data-zn-id*="body-text"] .zn-body__paragraph')
            if broader_body:
                texts = []
                for p_element in broader_body:
                    text_nodes = p_element.css('::text').getall()
                    cleaned_text = " ".join(t.strip() for t in text_nodes if t.strip()).strip()
                    if cleaned_text and len(cleaned_text) > 15:
                        texts.append(cleaned_text)
                if texts:
                     item['full_content'] = "\n\n".join(texts)
                     self.logger.debug(f"Used fallback selector 'div[data-zn-id*=\"body-text\"] .zn-body__paragraph' for {item['url']}")

        if not item.get('full_content'):
            self.logger.error(f"Failed to extract content for {item['url']} after all attempts.")
            item['full_content'] = "CONTENT_EXTRACTION_FAILED"

        yield item