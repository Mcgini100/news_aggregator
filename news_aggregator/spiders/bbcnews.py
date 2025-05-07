import scrapy
from news_aggregator.items import NewsArticleItem
from urllib.parse import urljoin

class BbcNewsSpider(scrapy.Spider):
    name = 'bbc'
    allowed_domains = ['bbc.com', 'bbc.co.uk']
    custom_settings = {
        'DOWNLOAD_DELAY': 1.5,
        'AUTOTHROTTLE_ENABLED': True,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    }

    category_map = {
        'business': 'https://www.bbc.com/business', # This often redirects to /news/business
        'politics': 'https://www.bbc.com/news/politics',
        'arts_culture_celebrities': 'https://www.bbc.com/news/entertainment_and_arts',
        'sports': 'https://www.bbc.com/sport'
    }

    category_item_counts = {}
    MAX_ITEMS_PER_CATEGORY = 4

    def start_requests(self):
        for category_name, category_url in self.category_map.items():
            self.category_item_counts[category_name] = 0
            yield scrapy.Request(
                url=category_url,
                callback=self.parse_category_page,
                meta={'category': category_name, 'source': self.name}
            )

    def parse_category_page(self, response):
        category = response.meta['category']
        source = response.meta['source']
        self.logger.info(f"Parsing {source} category: {category} from {response.url}")

        if self.category_item_counts.get(category, 0) >= self.MAX_ITEMS_PER_CATEGORY:
            self.logger.info(f"Reached max items ({self.MAX_ITEMS_PER_CATEGORY}) for category: {category}. Skipping.")
            return

        # --- SELECTORS FOR CATEGORY PAGE ---
        # Based on your provided HTML for /business and common patterns
        # For bbc.com/news/ or bbc.com/business:
        promo_selectors_news = [
            'div[data-indexcard="true"]',               # Primary for card-based layouts
            'div.gs-c-promo',                           # Older GEL promos
            'li.lx-stream-post',                        # Live stream posts
            'div[data-entityid][type="article"]',       # Common for ssrcss articles in some contexts
            'div[data-entityid][type="STYLink"]'        # Common for ssrcss links
        ]
        # For bbc.com/sport (likely uses different structure)
        promo_selectors_sport = [
            'div.ssrcss-t58pur-PromoLink',              # Example for sport, might need adjustment
            'a.ssrcss-sxweo-PromoLink.exn3ah95',        # From your sport promo example
            'div.qa-promo',                             # QA marker common on sport
            'article[class*="sp-c-cluster"]',           # Sport clusters
            'div[class*="promo--highlight"]',           # Sport highlight promos
            'div[data-reactid*=".default-promo"]'       # React-based promos on sport
        ]

        promos = []
        current_selectors_list = []

        if "bbc.com/sport" in response.url or "bbc.co.uk/sport" in response.url:
            current_selectors_list = promo_selectors_sport
            self.logger.info(f"Using SPORT selectors for {response.url}")
        else:
            current_selectors_list = promo_selectors_news
            self.logger.info(f"Using NEWS/BUSINESS selectors for {response.url}")

        for sel in current_selectors_list:
            found_promos = response.css(sel)
            if found_promos:
                self.logger.debug(f"Found {len(found_promos)} promos with selector '{sel}' for {category} on {response.url}")
                promos.extend(found_promos)
            # Stop if we have enough candidates to likely get MAX_ITEMS_PER_CATEGORY
            if len(promos) > self.MAX_ITEMS_PER_CATEGORY + 10: # Get a few extra
                break
        
        # If still no promos, try a very generic one as a last resort
        if not promos:
            self.logger.warning(f"Specific promo selectors failed for {response.url}. Trying generic 'a[href*=\"/articles/\"]'.")
            # This looks for any link containing '/articles/' which is common for BBC story URLs
            generic_promos = response.css('a[href*="/articles/"], a[href*="/news/"], a[href*="/sport/"]')
            # We need to be careful here as these 'a' tags might not be proper promo blocks.
            # For each such link, we'd need to navigate up to a common parent if we want summary, etc.
            # For simplicity now, we'll assume the link itself contains or is very near the title.
            if generic_promos:
                 promos.extend(generic_promos)


        if not promos:
            self.logger.warning(f"No promo blocks found for {source} {category} on {response.url} with any selectors.")
            return

        processed_urls = set()

        for promo in promos:
            if self.category_item_counts.get(category, 0) >= self.MAX_ITEMS_PER_CATEGORY:
                self.logger.info(f"Reached max items ({self.MAX_ITEMS_PER_CATEGORY}) for category: {category}.")
                break

            title_text = None
            article_url = None
            summary_text = None

            # --- Title Extraction ---
            if "bbc.com/sport" in response.url or "bbc.co.uk/sport" in response.url:
                # Sport title selectors
                title_text_candidate = promo.css('p.ssrcss-1b1mki6-PromoHeadline span[aria-hidden="false"]::text').get() # From your example
                if not title_text_candidate:
                    title_text_candidate = promo.css('.qa-promo-title::text').get()
                if not title_text_candidate: # If promo is the 'a' tag itself
                    title_text_candidate = promo.css('span[role="text"] p span::text, ::text').get() # Extracts first text
                if title_text_candidate: title_text = title_text_candidate.strip()
            else: # News/Business title selectors
                title_text_candidate = promo.css('h2[data-testid="card-headline"]::text').get() # From your /business example
                if not title_text_candidate:
                    title_text_candidate = promo.css('h3 a::text, a h3::text, h3::text').get() # Common GEL
                if not title_text_candidate:
                     title_text_candidate = promo.css('a[data-testid="internal-link"] div[type="TITLE"]::text, a[data-testid="headline-link"]::text').get() # ssrcss
                if title_text_candidate: title_text = title_text_candidate.strip()

            # --- URL Extraction ---
            url_candidate = promo.css('a::attr(href)').get() # Most general
            if url_candidate: article_url = url_candidate

            # --- Summary Extraction (Optional - attempt for news/business) ---
            if not ("bbc.com/sport" in response.url or "bbc.co.uk/sport" in response.url):
                summary_text_candidate = promo.css('p[data-testid="card-description"]::text').get()
                if summary_text_candidate: summary_text = summary_text_candidate.strip()


            if title_text and article_url:
                title = title_text
                url = response.urljoin(article_url)

                if not (url.startswith('https://www.bbc.com/') or url.startswith('https://www.bbc.co.uk/')):
                    self.logger.debug(f"Skipping URL from different domain: {url}")
                    continue
                if any(x in url for x in ['/live/', '.av.', '/sounds/', '/programmes/', '/weather', '/iwonder', '/bitesize', '/future', '/worklife', '/travel', '/culture/', '/podcasts', '/videos/', '/authors/', '/correspondents/', '/topics/']) or not ('/articles/' in url or '/news/' in url or '/sport/' in url.replace("https://www.bbc.co.uk","")):
                    self.logger.debug(f"Skipping non-article type URL: {url}")
                    continue
                if len(title) < 10 or "advertisement" in title.lower():
                    self.logger.debug(f"Skipping item with short or non-story title: '{title}' from {url}")
                    continue
                if url in processed_urls:
                    self.logger.debug(f"Skipping already processed URL: {url}")
                    continue
                processed_urls.add(url)

                item_data = NewsArticleItem()
                item_data['source'] = source
                item_data['category'] = category
                item_data['title'] = title
                item_data['url'] = url
                item_data['summary'] = summary_text
                item_data['full_content'] = None

                self.category_item_counts[category] = self.category_item_counts.get(category, 0) + 1
                self.logger.info(f"Yielding request for: {title} ({url}). Count for {category}: {self.category_item_counts[category]}")

                yield scrapy.Request(
                    url=item_data['url'],
                    callback=self.parse_article_page,
                    meta={'item_data': item_data}
                )
            else:
                if not title_text: self.logger.debug(f"No valid title for promo in {source} {category}. Promo HTML: {promo.get()[:200]}")
                if not article_url: self.logger.debug(f"No valid URL for promo in {source} {category}. Promo HTML: {promo.get()[:200]}")


    def parse_article_page(self, response):
        item = response.meta['item_data']
        self.logger.info(f"Parsing BBC article page: {item['url']}")

        # Main content container (based on your provided HTML for an article page)
        article_body_element = response.css('article.ssrcss-z9afcx-ArticleWrapper, main#main-content article')
        if not article_body_element:
            article_body_element = response.css('article[role="main"], article.article') # Broader fallbacks
        
        if article_body_element:
            # If SelectorList, take the first one.
            # This ensures we operate on a single element if multiple match (e.g. `article` only)
            if isinstance(article_body_element, scrapy.selector.unified.SelectorList):
                if len(article_body_element) > 0:
                    article_body_element = article_body_element[0]
                else:
                    self.logger.warning(f"Article body selector list was empty for URL: {item['url']}")
                    item['full_content'] = "CONTENT_NOT_FOUND_CONTAINER_EMPTY_LIST"
                    yield item
                    return

            full_text_paragraphs = []
            # Paragraphs with class 'ssrcss-1q0x1qg-Paragraph e1jhz7w10'
            # and also those within 'div[data-component="text-block"]'
            # The `article_body_element.css(...)` makes these relative to the found body.
            content_paragraphs = article_body_element.css('div[data-component="text-block"] p.ssrcss-1q0x1qg-Paragraph, article > div > p.ssrcss-1q0x1qg-Paragraph, main > article > div > p.ssrcss-1q0x1qg-Paragraph')
            
            # If the specific ssrcss paragraph class isn't found (e.g., older GEL articles), try more general <p>
            if not content_paragraphs:
                self.logger.debug(f"Specific ssrcss paragraph class not found for {item['url']}. Trying general p tags.")
                content_paragraphs = article_body_element.css('p')


            for p_tag in content_paragraphs:
                is_inside_unwanted_parent = p_tag.xpath(''
                    'ancestor::figure | '
                    'ancestor::aside | '
                    'ancestor::div[contains(@class, "Disclaimer")] | '
                    'ancestor::div[contains(@class, "LinksComponentWrapper")] | '
                    'ancestor::section[contains(@class, "LinksWrapper")] | '
                    'ancestor::div[contains(@class, "TopicListWrapper")] | '
                    'ancestor::div[contains(@id, "dotcom-mpu")] | '
                    'ancestor::div[contains(@class, "riddle2-wrapper")] | '
                    'ancestor::div[contains(@data-component, "links-block")] |'
                    'ancestor::div[contains(@data-component, "social-embed")] |'
                    'ancestor::div[contains(@data-component, "sty-media-gallery")] |'
                    'ancestor::div[contains(@class, "Explainer")] |'
                    'ancestor::figcaption'
                ).get()

                if is_inside_unwanted_parent:
                    continue

                paragraph_text_nodes = p_tag.css('::text').getall()
                cleaned_paragraph = " ".join(node.strip() for node in paragraph_text_nodes if node.strip()).strip()
                
                if cleaned_paragraph and len(cleaned_paragraph.split()) > 2:
                    if cleaned_paragraph.lower().startswith(("follow bbc", "image source,", "image caption,", "media caption,", "photo by", "video by", "reporting by")) or \
                       "read more:" in cleaned_paragraph.lower() or \
                       "watch more:" in cleaned_paragraph.lower() or \
                       "listen to:" in cleaned_paragraph.lower() or \
                       "copyright" in cleaned_paragraph.lower() and "getty" in cleaned_paragraph.lower() or \
                       cleaned_paragraph.endswith("contributed to this report."):
                        continue
                    full_text_paragraphs.append(cleaned_paragraph)

            if full_text_paragraphs:
                item['full_content'] = "\n\n".join(full_text_paragraphs)
            else:
                self.logger.warning(f"Paragraph filtering yielded no content for {item['url']}. Body HTML: {article_body_element.get()[:500]}")
                item['full_content'] = "CONTENT_EXTRACTION_FAILED_NO_PARAGRAPHS"
        else:
            self.logger.warning(f"Could not find any article body container for URL: {item['url']}")
            item['full_content'] = "CONTENT_NOT_FOUND_CONTAINER_MISSING"

        yield item