import asyncio
import aiohttp
import random

NEWS_SAMPLES = [
    {
        "title": "Новый рейд открыт!",
        "content": "Сегодня открывается новый рейд на 40 человек. Готовьте свои гильдии!",
        "category": "raids"
    },
    {
        "title": "Обновление баланса классов",
        "content": "В следующем патче будет проведена балансировка всех классов. Подробности внутри.",
        "category": "updates"
    },
    {
        "title": "Турнир PvP стартует",
        "content": "Регистрация на ежемесячный турнир PvP открыта. Призовой фонд: 1 000 000 золота!",
        "category": "events"
    },
    {
        "title": "Новый класс: Некромант",
        "content": "В игру добавлен новый класс Некромант. Повелевайте армией нежити!",
        "category": "updates"
    },
    {
        "title": "Технические работы",
        "content": "Плановые технические работы завтра с 03:00 до 07:00 МСК.",
        "category": "maintenance"
    }
]


async def send_news(session, news):
    """Отправка одной новости на сервер."""
    async with session.post('http://localhost:8081/news', json=news) as response:
        result = await response.json()
        print(f"Sent: {news['title']}")
        print(f"Response: {result}\n")


async def main():
    """Отправка тестовых новостей."""
    async with aiohttp.ClientSession() as session:
        print("Sending test news...\n")
        
        for news in NEWS_SAMPLES:
            await send_news(session, news)
            await asyncio.sleep(2)  # Пауза между новостями
        
        print("All news sent!")


async def send_single_news():
    """Отправка одной случайной новости."""
    async with aiohttp.ClientSession() as session:
        news = random.choice(NEWS_SAMPLES)
        await send_news(session, news)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--single':
        asyncio.run(send_single_news())
    else:
        asyncio.run(main())