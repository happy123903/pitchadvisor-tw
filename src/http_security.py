"""Bound request memory before JSON parsing, including chunked requests."""
from starlette.responses import JSONResponse


class RequestSizeLimit:
    def __init__(self, app, max_bytes=16 * 1024):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        if b'content-length' in headers:
            try:
                length = int(headers[b'content-length'])
                if length < 0:
                    raise ValueError
            except ValueError:
                return await JSONResponse({'detail': {'code': 'invalid_content_length'}}, status_code=400)(scope, receive, send)
            if length > self.max_bytes:
                return await self.reject(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > self.max_bytes:
                return await self.reject(scope, receive, send)
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        delivered = False

        async def limited_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        await self.app(scope, limited_receive, send)

    async def reject(self, scope, receive, send):
        response = JSONResponse({'detail': {'code': 'request_too_large',
            'message': '請求資料超過大小限制。'}}, status_code=413)
        await response(scope, receive, send)
