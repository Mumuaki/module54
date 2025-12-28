import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Set
from weakref import WeakSet

from aiohttp import web, WSMsgType, WSCloseCode


class NewsServer:
    
    def __init__(self):
        self.websockets: Set[web.WebSocketResponse] = WeakSet()
        
        self.news_history: list = []
        self.max_history = 100
         
        self.ping_interval = 30
    
    async def websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=self.ping_interval)
        await ws.prepare(request)
        
        self.websockets.add(ws)
        client_id = id(ws)
        
        try:
            if self.news_history:
                await ws.send_json({
                    'type': 'history',
                    'data': self.news_history[-10:]
                })
            
            await ws.send_json({
                'type': 'connected',
                'message': 'Successfully connected to news server',
                'client_id': client_id
            })
            
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self.handle_client_message(ws, data)
                    except json.JSONDecodeError:
                        await ws.send_json({
                            'type': 'error',
                            'message': 'Invalid JSON format'
                        })
                
                elif msg.type == WSMsgType.PING:
                    pass
                
                elif msg.type == WSMsgType.PONG:
                    pass
                
                elif msg.type == WSMsgType.ERROR:
                    break
        
        except asyncio.CancelledError:
            pass
        
        finally:
            self.websockets.discard(ws)
        
        return ws
    
    async def handle_client_message(self, ws: web.WebSocketResponse, data: dict):
        msg_type = data.get('type')
        
        if msg_type == 'ping':
            await ws.send_json({
                'type': 'pong',
                'timestamp': datetime.now().isoformat()
            })
        
        elif msg_type == 'get_history':
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
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {'error': 'Invalid JSON'},
                status=400
            )
        
        title = data.get('title')
        content = data.get('content')
        
        if not title or not content:
            return web.json_response(
                {'error': 'Title and content are required'},
                status=400
            )
        
        news_item = {
            'id': len(self.news_history) + 1,
            'title': title,
            'content': content,
            'category': data.get('category', 'general'),
            'timestamp': datetime.now().isoformat(),
        }
        
        self.news_history.append(news_item)
        if len(self.news_history) > self.max_history:
            self.news_history = self.news_history[-self.max_history:]
        
        await self.broadcast_news(news_item)
        
        return web.json_response({
            'status': 'success',
            'news_id': news_item['id'],
            'clients_notified': len(self.websockets)
        })
    
    async def broadcast_news(self, news_item: dict):
        if not self.websockets:
            return
        
        message = {
            'type': 'news',
            'data': news_item
        }
        
        tasks = []
        disconnected = []
        
        for ws in self.websockets:
            if ws.closed:
                disconnected.append(ws)
                continue
            tasks.append(self.send_to_client(ws, message))
        
        for ws in disconnected:
            self.websockets.discard(ws)
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
    
    async def send_to_client(self, ws: web.WebSocketResponse, message: dict):
        try:
            await ws.send_json(message)
        except ConnectionResetError:
            self.websockets.discard(ws)
            raise
    
    async def health_check(self, request: web.Request) -> web.Response:
        return web.json_response({
            'status': 'healthy',
            'connected_clients': len(self.websockets),
            'news_count': len(self.news_history),
            'timestamp': datetime.now().isoformat()
        })
    
    async def get_stats(self, request: web.Request) -> web.Response:
        return web.json_response({
            'connected_clients': len(self.websockets),
            'total_news': len(self.news_history),
            'recent_news': self.news_history[-5:] if self.news_history else []
        })
    
    async def index(self, request: web.Request) -> web.FileResponse:
        static_dir = Path(__file__).parent.parent / 'static'
        return web.FileResponse(static_dir / 'index.html')


def create_app() -> web.Application:
    app = web.Application()
    server = NewsServer()
    
    app.router.add_get('/', server.index)
    app.router.add_get('/ws', server.websocket_handler)
    app.router.add_post('/news', server.post_news)
    app.router.add_get('/health', server.health_check)
    app.router.add_get('/stats', server.get_stats)
    
    static_dir = Path(__file__).parent.parent / 'static'
    app.router.add_static('/static/', path=static_dir, name='static')
    
    app['news_server'] = server
    
    return app


if __name__ == '__main__':
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=8081)