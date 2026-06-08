import http.server
import json

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        with open('workflow_api.json', 'w', encoding='utf-8') as f:
            f.write(post_data.decode('utf-8'))
            
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b'Success')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'X-Requested-With, Content-Type')
        self.end_headers()

server = http.server.HTTPServer(('127.0.0.1', 8999), Handler)
print("Listening on 8999...")
server.handle_request()  # Handle just one request and exit
