import aiohttp
import feedparser
from typing import List, Dict
from utils.logger import get_logger

logger = get_logger("news_service")

RSS_FEEDS = [
    # Fuentes técnicas internacionales
    {
        "nombre": "Anthropic",
        "url": "https://www.anthropic.com/rss.xml"
    },
    {
        "nombre": "OpenAI",
        "url": "https://openai.com/news/rss.xml"
    },
    {
        "nombre": "LangChain",
        "url": "https://blog.langchain.dev/rss/"
    },
    {
        "nombre": "HuggingFace",
        "url": "https://huggingface.co/blog/feed.xml"
    },
    {
        "nombre": "DeepLearning.AI",
        "url": "https://www.deeplearning.ai/feed/"
    },
    # Substacks especializados
    {
        "nombre": "Ahead of AI",
        "url": "https://magazine.sebastianraschka.com/feed"
    },
    {
        "nombre": "The Algorithmic Bridge",
        "url": "https://thealgorithmicbridge.substack.com/feed"
    },
    {
        "nombre": "Latent Space",
        "url": "https://www.latent.space/feed"
    },
    {
        "nombre": "Ben's Bites",
        "url": "https://bensbites.beehiiv.com/feed"
    },
    # Fuentes en español
    {
        "nombre": "Café con IA",
        "url": "https://cafeconia.substack.com/feed"
    },
    {
        "nombre": "Cero a Senior",
        "url": "https://ceroasenior.substack.com/feed"
    },
    {
        "nombre": "Xataka",
        "url": "https://feeds.weblogssl.com/xataka2"
    },
]


async def fetch_rss_feed(feed: Dict) -> List[Dict]:
    """Descarga y parsea un feed RSS."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                feed["url"],
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"User-Agent": "Mozilla/5.0"}
            ) as response:
                if response.status != 200:
                    logger.warning(
                        f"Feed {feed['nombre']} devolvió {response.status}"
                    )
                    return []
                content = await response.text()

        parsed = feedparser.parse(content)
        items = []
        for entry in parsed.entries[:5]:  # Máx 5 por feed
            items.append({
                "fuente": feed["nombre"],
                "titulo": entry.get("title", ""),
                "url": entry.get("link", ""),
                "resumen": entry.get("summary", "")[:300],
                "fecha": entry.get("published", "")
            })
        logger.info(f"Feed {feed['nombre']}: {len(items)} items")
        return items
    except Exception as e:
        logger.error(f"Error fetching {feed['nombre']}: {e}")
        return []


async def get_all_news() -> List[Dict]:
    """Descarga todos los feeds RSS en paralelo."""
    import asyncio
    tasks = [fetch_rss_feed(feed) for feed in RSS_FEEDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items = []
    for result in results:
        if isinstance(result, list):
            all_items.extend(result)

    logger.info(f"Total noticias descargadas: {len(all_items)}")
    return all_items


def format_news_for_llm(items: List[Dict]) -> str:
    """Formatea noticias para enviarlas al LLM a filtrar."""
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. [{item['fuente']}] {item['titulo']}\n"
            f"   URL: {item['url']}\n"
            f"   Resumen: {item['resumen']}"
        )
    return "\n\n".join(lines)


def format_news_for_telegram(items: List[Dict]) -> str:
    """Formatea noticias filtradas para Telegram."""
    if not items:
        return ""

    iconos = {
        "Anthropic": "🤖",
        "OpenAI": "🧠",
        "LangChain": "🔗",
        "HuggingFace": "🤗",
        "DeepLearning.AI": "📚",
        "Ahead of AI": "🔬",
        "The Algorithmic Bridge": "🌉",
        "Latent Space": "🚀",
        "Ben's Bites": "🍔",
        "Café con IA": "☕",
        "Cero a Senior": "📈",
        "Xataka": "📱",
    }

    RELEVANT_SOURCES = ['Café con IA', 'Cero a Senior']

    lines = ["📰 *Noticias de IA relevantes para ti:*\n"]
    for item in items:
        fuente = item.get("fuente", "")
        icono = iconos.get(fuente, "📌")
        
        titulo_display = item['titulo']
        if fuente in RELEVANT_SOURCES:
            titulo_display = f"⭐️ {titulo_display}"
            
        lines.append(
            f"{icono} *{titulo_display}*\n"
            f"   {item.get('url', '')}"
        )
    return "\n\n".join(lines)
