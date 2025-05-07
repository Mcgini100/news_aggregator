import scrapy

class NewsArticleItem(scrapy.Item):
    source = scrapy.Field()       # e.g., 'BBC', 'The Independent'
    category = scrapy.Field()     # e.g., 'business', 'politics'
    title = scrapy.Field()
    url = scrapy.Field()
    summary = scrapy.Field()      # Optional, may not always be present
    full_content = scrapy.Field()
    # published_date = scrapy.Field() # Optional and often difficult to parse consistently