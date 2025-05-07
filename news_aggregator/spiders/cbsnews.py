# news_aggregator/spiders/cbsnews_spider.py
import scrapy
from news_aggregator.items import NewsArticleItem
from urllib.parse import urljoin

class CbsnewsSpider(scrapy.Spider):
    name = 'cbsnews'
    allowed_domains = ['cbsnews.com']
    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'AUTOTHROTTLE_ENABLED': True,
        'USER_AGENT': 'NewsAggregatorBot/1.0 (+http://www.your-domain.com/botinfo) Scrapy', # Be clear
    }

    # Max articles to scrape per category
    MAX_ARTICLES_PER_CATEGORY = 4

    category_map = {
        'business': 'https://www.cbsnews.com/moneywatch/',
        'politics': 'https://www.cbsnews.com/politics/',
        'arts_culture_celebrities': 'https://www.cbsnews.com/entertainment/',
        'us_news': 'https://www.cbsnews.com/us/', # Using US News as a general category
        # No dedicated top-level sports news on cbsnews.com, might appear in 'us_news'
    }

    def start_requests(self):
        for category_name, category_url in self.category_map.items():
            yield scrapy.Request(
                url=category_url,
                callback=self.parse_category_page,
                meta={
                    'category': category_name,
                    'source': self.name,
                    'article_count': 0 # Initialize counter for this category
                }
            )

    def parse_category_page(self, response):
        category = response.meta['category']
        source = response.meta['source']
        article_count = response.meta['article_count']

        self.logger.info(f"Parsing {source} category: {category} from {response.url} (Count: {article_count})")

        # --- UPDATED Selectors for CBS News Category Pages ---
        # Each story seems to be within an <article class="item ...">
        # Note: We select the <article> tag because the <a> tag wraps everything,
        # and we want to extract elements relative to the <article>.
        promos = response.css('article.item--type-article') # More specific to article items

        if not promos:
            self.logger.warning(f"No promo blocks found for {source} {category} on {response.url} with current selectors.")
            return

        for promo in promos:
            if article_count >= self.MAX_ARTICLES_PER_CATEGORY:
                self.logger.info(f"Reached max articles ({self.MAX_ARTICLES_PER_CATEGORY}) for {category}. Stopping.")
                return

            # --- Title Extraction ---
            # Title is in <h4 class="item__hed">
            title_text = promo.css('h4.item__hed::text').get()
            if title_text: # Sometimes text is split by internal tags like <strong>
                title_text_parts = promo.css('h4.item__hed ::text').getall()
                title_text = " ".join(part.strip() for part in title_text_parts if part.strip()).strip()


            # --- URL Extraction ---
            # The article tag itself doesn't have the href, its parent <a> tag does.
            # Or, if we select the <a> tag as the promo, then it's promo.css('::attr(href)').get()
            # Given promo is <article>, we find the <a> tag first.
            # The <a> tag is a direct wrapper around most content including the <article> in some layouts, or the <article> is inside the <a>.
            # Let's assume the promo is the <article> tag as per above.
            # The <a> tag is its direct parent in this structure, or the article is inside the <a>.
            # If promo is article.item--type-article, its parent is a.item__anchor
            # article_url_relative = promo.xpath('./parent::a[@class="item__anchor"]/@href').get() # If promo is the <article>
            # Simpler if we assume promo is the <article> and the <a> is a child or the article itself is wrapped by <a>
            article_url_relative = promo.css('a.item__anchor::attr(href)').get()
            if not article_url_relative: # Fallback if the article itself is the one with the direct link
                 article_url_relative = promo.css('::attr(href)').get() # This is too broad, let's stick to the a.item__anchor from the original structure.
                 # The structure you provided: `<article ...><a href_here>...</article>` - so the <a> is a child.
                 # Or `<a href_here><article>...</article></a>`
                 # The HTML provided shows: `div > article > a`. And also `article > a`.
                 # Let's assume the promo is `article.item--type-article`
                 # Then the link is `a.item__anchor` (which is a child of article based on outer wrapper)
                 # OR if the structure is `a.item_anchor > article.item--type-article`, then
                 # article_url_relative = promo.xpath('ancestor-or-self::a[@class="item__anchor"]/@href').get()

            # Given the top level HTML snippet starts with `<div class="component__item-wrapper">`
            # and inside that, `<article class="item item--type-article">` contains `<a href=... class="item__anchor">`
            # So, if `promo` is the `article.item`, then the URL is a child `a.item__anchor`.
            article_url_relative = promo.css('a.item__anchor::attr(href)').get()


            # --- Summary Extraction ---
            # Summary is in <p class="item__dek">
            summary_text_parts = promo.css('p.item__dek ::text').getall() # Use ::text to get all text nodes
            summary_text = " ".join(part.strip() for part in summary_text_parts if part.strip()).strip()


            if title_text and article_url_relative:
                title = title_text.strip()
                url = response.urljoin(article_url_relative)

                # Basic filtering for actual articles
                if not url.startswith('https://www.cbsnews.com/'):
                    self.logger.debug(f"Skipping URL not starting with cbsnews.com: {url}")
                    continue
                if any(x in url for x in ['/video/', '/live/', '/pictures/', '/essentials/', '/show/', '/newsletters/', '/cbs-mornings/', '/video/']):
                    self.logger.debug(f"Skipping non-article (video/live/gallery/etc.) URL: {url}")
                    continue
                if len(title) < 10:
                    self.logger.debug(f"Skipping potentially non-story item with short title: {title} from {url}")
                    continue

                item_data = NewsArticleItem()
                item_data['source'] = source
                item_data['category'] = category
                item_data['title'] = title
                item_data['url'] = url
                item_data['summary'] = summary_text.strip() if summary_text else None
                item_data['full_content'] = None

                article_count += 1
                yield scrapy.Request(
                    url=item_data['url'],
                    callback=self.parse_article_page,
                    meta={'item_data': item_data}
                )
            else:
                if not title_text: self.logger.debug(f"No title for a promo in {source} {category}. Promo HTML: {promo.get()[:200]}")
                if not article_url_relative: self.logger.debug(f"No URL for a promo in {source} {category}. Promo HTML: {promo.get()[:200]}")

    def parse_article_page(self, response):
        item = response.meta['item_data']
        self.logger.info(f"Parsing article page: {item['url']}")

        # --- UPDATED Selector for full content on CBS News ---
        # Based on provided HTML, content is in <section class="content__body">
        article_body_element = response.css('section.content__body')

        full_text_paragraphs = []
        if article_body_element:
            # Extract text from <p> tags within the selected body.
            # Exclude paragraphs from known non-content sections if possible.
            all_paragraphs = article_body_element.css('p')

            for p_tag in all_paragraphs:
                # Check for common exclusion patterns within CBS articles
                is_inside_unwanted_element = p_tag.xpath(''
                    'ancestor::div[contains(@class, "module-related")] |'
                    'ancestor::div[contains(@class, "content__extension")] |' # Often related links / promos
                    'ancestor::div[contains(@class, "ad-")] |'                # Ad containers
                    'ancestor::div[contains(@id, "mpu-")] |'                  # More ad containers by ID
                    'ancestor::div[contains(@id, "leader-")] |'              # More ad containers by ID
                    'ancestor::div[contains(@class, "promo")] |'
                    'ancestor::div[contains(@class, "social-")] |'
                    'ancestor::aside |'                                       # General aside content
                    'ancestor::figure/figcaption'                             # Exclude figcaptions
                ).get()

                p_class = p_tag.attrib.get('class', '')
                # Exclude bylines, timestamps, or other meta paragraphs often found within content body
                if 'byline' in p_class or 'timestamp' in p_class or 'source' in p_class or 'note' in p_class or 'copyright' in p_class:
                    is_inside_unwanted_element = True
                
                # Check if the paragraph is likely a "KFF Health News..." attribution or similar boilerplate
                p_text_content_check = " ".join(p_tag.css('::text').getall()).strip().lower()
                if "kff health news" in p_text_content_check and "national newsroom" in p_text_content_check:
                    is_inside_unwanted_element = True
                if "contributed to this report" in p_text_content_check: # e.g., "correspondent Bernard Wolfson contributed to this report."
                    is_inside_unwanted_element = True


                if not is_inside_unwanted_element:
                    paragraph_text_nodes = p_tag.css('::text').getall()
                    cleaned_paragraph = " ".join(node.strip() for node in paragraph_text_nodes if node.strip()).strip()
                    if cleaned_paragraph and len(cleaned_paragraph) > 20: # Only keep reasonably long paragraphs
                        full_text_paragraphs.append(cleaned_paragraph)
                # else:
                #    self.logger.debug(f"Skipping paragraph due to exclusion: {p_tag.get()[:150]}")


            if full_text_paragraphs:
                item['full_content'] = "\n\n".join(full_text_paragraphs)
            else:
                self.logger.warning(f"Specific P filtering yielded no content for {item['url']} from section.content__body. Trying broader extraction (might be noisy).")
                # Fallback: if P filtering failed, try getting all text nodes, excluding known bad ancestors
                all_text_nodes = article_body_element.xpath('.//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::aside) and not(ancestor::figure/figcaption) and not(ancestor::div[contains(@class,"ad-")]) and not(ancestor::div[contains(@id,"mpu-")]) and not(ancestor::div[contains(@id,"leader-")]) and not(ancestor::div[contains(@class,"promo")]) and not(ancestor::div[contains(@class,"related")]) and not(ancestor::div[contains(@class,"social")]) and not(ancestor::div[contains(@class,"content__extension")]) and not(ancestor::ul[contains(@class,"content__tags")]) ]').getall()
                item['full_content'] = "\n\n".join(text.strip() for text in all_text_nodes if text.strip() and len(text.strip()) > 20)


            if not item['full_content']:
                 self.logger.warning(f"Extracted empty full_content for URL: {item['url']} from section.content__body even after fallback.")

        else:
            self.logger.warning(f"Could not find article body container 'section.content__body' for URL: {item['url']}")
            item['full_content'] = "CONTENT_NOT_FOUND_CONTAINER_MISSING"

        yield item