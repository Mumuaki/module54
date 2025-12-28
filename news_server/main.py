import asyncio
import json
import logging
from datetime import datetime
from typing import Set
from weakref import WeakSet

from aiohttp import web, WSMsgType, WSCloseCode

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NewsServer:
    """
    Сервер новостей с поддержкой WebSocket.
    
    Позволяет:
    - Подключаться клиентам через WebSocket
    - Получать новости через POST /news
    - Рассылать новости всем подключенным клиентам
    - Поддерживать соединение через ping/pong
    """
    
    def __init__(self):
        self.websockets: Set[web.WebSocketResponse] = WeakSet()
        
        self.news_history: list = []
        self.max_history = 100
         
        self.ping_interval = 30
    
    async def websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        """
        Обработчик WebSocket соединений.
        
        Управляет жизненным циклом соединения:
        - Установка соединения
        - Отправка истории новостей
        - Обработка ping/pong
        - Закрытие соединения
        """
        ws = web.WebSocketResponse(heartbeat=self.ping_interval)
        await ws.prepare(request)
        
        # Добавляем соединение в множество активных
        self.websockets.add(ws)
        client_id = id(ws)
        logger.info(f"Client {client_id} connected. Total clients: {len(self.websockets)}")
        
        try:
            # Отправляем историю новостей новому клиенту
            if self.news_history:
                await ws.send_json({
                    'type': 'history',
                    'data': self.news_history[-10:]  # Последние 10 новостей
                })
            
            # Отправляем приветственное сообщение
            await ws.send_json({
                'type': 'connected',
                'message': 'Successfully connected to news server',
                'client_id': client_id
            })
            
            # Основной цикл обработки сообщений от клиента
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self.handle_client_message(ws, data)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from client {client_id}")
                        await ws.send_json({
                            'type': 'error',
                            'message': 'Invalid JSON format'
                        })
                
                elif msg.type == WSMsgType.PING:
                    # Автоматически обрабатывается через heartbeat
                    logger.debug(f"Ping from client {client_id}")
                
                elif msg.type == WSMsgType.PONG:
                    logger.debug(f"Pong from client {client_id}")
                
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error from client {client_id}: {ws.exception()}")
                    break
        
        except asyncio.CancelledError:
            logger.info(f"Connection cancelled for client {client_id}")
        
        finally:
            # Удаляем соединение из множества
            self.websockets.discard(ws)
            logger.info(f"Client {client_id} disconnected. Total clients: {len(self.websockets)}")
        
        return ws
    
    async def handle_client_message(self, ws: web.WebSocketResponse, data: dict):
        """Обработка сообщений от клиента."""
        
        msg_type = data.get('type')
        
        if msg_type == 'ping':
            # Ответ на ping от клиента (проверка соединения)
            await ws.send_json({
                'type': 'pong',
                'timestamp': datetime.now().isoformat()
            })
        
        elif msg_type == 'get_history':
            # Запрос истории новостей
            count = min(data.get('count', 10), self.max_history)
            await ws.send_json({
                'type': 'history',
                'data': self.news_history[-count:]
            })
        
        else:
            await ws.send_json({
                'type': 'error',
                'message': f'Unknown message type: {msg_type}'
            })
    
    async def post_news(self, request: web.Request) -> web.Response:
        """
        Обработчик POST /news для получения новостей от внешних сервисов.
        
        Ожидает JSON:
        {
            "title": "Заголовок новости",
            "content": "Текст новости",
            "category": "optional category"
        }
        """
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {'error': 'Invalid JSON'},
                status=400
            )
        
        # Валидация данных
        title = data.get('title')
        content = data.get('content')
        
        if not title or not content:
            return web.json_response(
                {'error': 'Title and content are required'},
                status=400
            )
        
        # Создаем объект новости
        news_item = {
            'id': len(self.news_history) + 1,
            'title': title,
            'content': content,
            'category': data.get('category', 'general'),
            'timestamp': datetime.now().isoformat(),
        }
        
        # Добавляем в историю
        self.news_history.append(news_item)
        if len(self.news_history) > self.max_history:
            self.news_history = self.news_history[-self.max_history:]
        
        # Рассылаем всем подключенным клиентам
        await self.broadcast_news(news_item)
        
        logger.info(f"News posted: {title}. Broadcast to {len(self.websockets)} clients")
        
        return web.json_response({
            'status': 'success',
            'news_id': news_item['id'],
            'clients_notified': len(self.websockets)
        })
    
    async def broadcast_news(self, news_item: dict):
        """Рассылка новости всем подключенным клиентам."""
        
        if not self.websockets:
            return
        
        message = {
            'type': 'news',
            'data': news_item
        }
        
        # Создаем задачи для отправки всем клиентам
        tasks = []
        disconnected = []
        
        for ws in self.websockets:
            if ws.closed:
                disconnected.append(ws)
                continue
            tasks.append(self.send_to_client(ws, message))
        
        # Удаляем отключенных клиентов
        for ws in disconnected:
            self.websockets.discard(ws)
        
        # Отправляем всем параллельно
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Логируем ошибки
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Failed to send to client: {result}")
    
    async def send_to_client(self, ws: web.WebSocketResponse, message: dict):
        """Безопасная отправка сообщения клиенту."""
        try:
            await ws.send_json(message)
        except ConnectionResetError:
            self.websockets.discard(ws)
            raise
    
    async def health_check(self, request: web.Request) -> web.Response:
        """
        Эндпоинт для проверки здоровья сервера.
        GET /health
        """
        return web.json_response({
            'status': 'healthy',
            'connected_clients': len(self.websockets),
            'news_count': len(self.news_history),
            'timestamp': datetime.now().isoformat()
        })
    
    async def get_stats(self, request: web.Request) -> web.Response:
        """
        Статистика сервера.
        GET /stats
        """
        return web.json_response({
            'connected_clients': len(self.websockets),
            'total_news': len(self.news_history),
            'recent_news': self.news_history[-5:] if self.news_history else []
        })
    
    async def index(self, request: web.Request) -> web.FileResponse:
        """Отдача главной страницы."""
        return web.FileResponse('./static/index.html')


def create_app() -> web.Application:
    """Фабрика приложения."""
    
    app = web.Application()
    server = NewsServer()
    
    # Маршруты
    app.router.add_get('/', server.index)
    app.router.add_get('/ws', server.websocket_handler)
    app.router.add_post('/news', server.post_news)
    app.router.add_get('/health', server.health_check)
    app.router.add_get('/stats', server.get_stats)
    
    # Статические файлы
    app.router.add_static('/static/', path='./static', name='static')
    
    # Сохраняем ссылку на сервер в приложении
    app['news_server'] = server
    
    return app


if __name__ == '__main__':
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=8081)